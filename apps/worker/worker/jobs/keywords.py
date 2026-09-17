"""`keywords.ingest` + `serp.analyze` worker jobs (A-TO-Z-PLAN.md §Phase 4).

`keywords.ingest` — upsert a batch of terms, classify multi-label intent, cluster, persist.
`serp.analyze` — pull one SERP via the provider abstraction, store the run + results + features
+ entities + an `evidence` row (kind='serp_snapshot')."""

from __future__ import annotations

import datetime as dt
import uuid

import structlog
from integrations.serp import get_provider
from integrations.serp.fake import FakeSerpProvider
from sqlalchemy.orm import Session

from db.models.events import OutboxEvent
from db.models.evidence import Evidence
from db.models.geo import AiCitation, AiPrompt, AiPromptRun, AiResponse
from db.models.keywords import Keyword, KeywordCluster, SearchIntent
from db.models.serp import SerpEntity, SerpFeature, SerpResult, SerpRun
from db.session import tenant_session
from seo_core.confidence import score as confidence_score
from seo_core.crawl.fingerprint import content_hash
from seo_core.geo import parse_citations
from seo_core.keywords import classify_intent, cluster_keywords, normalize
from seo_core.keywords.clustering import KeywordInput
from seo_core.serp import analyze_serp
from seo_core.serp.models import SerpItem

log = structlog.get_logger("job.keywords")
UTC = dt.UTC


def _as_int(v: object) -> int | None:
    return int(v) if isinstance(v, (int, float)) else None


def ingest(tenant_id: str, project_id: str, terms: list[dict[str, object]] | list[str],
           locale: str = "en-US", correlation_id: str | None = None) -> dict[str, object]:
    tid, pid = uuid.UUID(tenant_id), uuid.UUID(project_id)
    rows: list[dict[str, object]] = [
        t if isinstance(t, dict) else {"term": t} for t in terms
    ]
    with tenant_session(tid, pid) as s:
        kw_ids: dict[str, uuid.UUID] = {}
        for row in rows:
            term = str(row["term"])
            norm = normalize(term)
            existing = s.query(Keyword).filter(
                Keyword.project_id == pid, Keyword.normalized == norm
            ).one_or_none()
            if existing is None:
                kw = Keyword(
                    tenant_id=tid, project_id=pid, term=term, normalized=norm,
                    source=str(row.get("source", "seed")), locale=locale,
                    volume=_as_int(row.get("volume")), volume_estimated=row.get("volume") is None,
                )
                s.add(kw)
                s.flush()
            else:
                kw = existing
            kw_ids[norm] = kw.id
            s.query(SearchIntent).filter(SearchIntent.keyword_id == kw.id).delete()
            for scored in classify_intent(term):
                s.add(SearchIntent(
                    tenant_id=tid, project_id=pid, keyword_id=kw.id,
                    label=scored.label.value, confidence=scored.confidence, method=scored.method,
                ))

        clusters = cluster_keywords(
            [KeywordInput(str(r["term"]), _as_int(r.get("volume"))) for r in rows]
        )
        s.query(KeywordCluster).filter(KeywordCluster.project_id == pid).delete()
        for c in clusters:
            cl = KeywordCluster(
                tenant_id=tid, project_id=pid, name=c.name, slug=c.slug, method="token_jaccard",
                size=c.size, volume_sum=c.volume_sum, primary_intent=c.primary_intent,
                intents=c.intents,
            )
            s.add(cl)
            s.flush()
            for term in c.terms:
                kid = kw_ids.get(normalize(term))
                if kid:
                    s.query(Keyword).filter(Keyword.id == kid).update({"cluster_id": cl.id})

        s.add(OutboxEvent(
            tenant_id=tid, project_id=pid, type="keywords.ingested", version=1,
            correlation_id=correlation_id or str(uuid.uuid4()),
            payload={"keywords": len(kw_ids), "clusters": len(clusters)},
        ))
    log.info("keywords.ingested", keywords=len(kw_ids), clusters=len(clusters))
    return {"keywords": len(kw_ids), "clusters": len(clusters)}


def analyze_query(tenant_id: str, project_id: str, query: str, *,
                  own_domain: str | None = None, competitor_domains: list[str] | None = None,
                  brand: str | None = None, competitor_names: list[str] | None = None,
                  provider_name: str | None = None, use_fake: bool = False,
                  correlation_id: str | None = None) -> dict[str, object]:
    tid, pid = uuid.UUID(tenant_id), uuid.UUID(project_id)
    provider = FakeSerpProvider() if use_fake else get_provider(provider_name)
    payload = provider.search(query)
    analysis = analyze_serp(payload, own_domain=own_domain, competitor_domains=competitor_domains)
    ch = content_hash(repr(payload.raw) or f"{query}|{[i.url for i in payload.organic]}")
    now = dt.datetime.now(UTC)
    comp = {d.removeprefix("www.") for d in (competitor_domains or [])}

    with tenant_session(tid, pid) as s:
        run = SerpRun(
            tenant_id=tid, project_id=pid, query=query, provider=payload.provider,
            locale=payload.locale, device=payload.device, content_hash=ch, fetched_at=now,
            stats={"feature_types": analysis.feature_types, "own_position": analysis.own_position},
        )
        s.add(run)
        s.flush()
        for item in payload.organic:
            dom = _domain(item.url)
            s.add(SerpResult(
                tenant_id=tid, project_id=pid, serp_run_id=run.id, position=item.position,
                url=item.url, domain=dom, title=item.title,
                is_own=bool(own_domain and dom == own_domain.removeprefix("www.")),
                is_competitor=dom in comp,
            ))
        for feat in payload.features:
            s.add(SerpFeature(
                tenant_id=tid, project_id=pid, serp_run_id=run.id, feature_type=feat.type,
                position=feat.position, data={"items": feat.items, **feat.data},
            ))
        for term, weight in analysis.entities:
            s.add(SerpEntity(
                tenant_id=tid, project_id=pid, serp_run_id=run.id, name=term[:200],
                kind="question" if term.endswith("?") else "topic", weight=weight,
            ))
        s.add(Evidence(
            tenant_id=tid, project_id=pid, kind="serp_snapshot", source_url=None,
            serp_run_id=run.id, content_hash=ch, provider=payload.provider,
            parser="seo_core.serp.features", parser_version="0.1.0",
            collected_at=now, confidence=confidence_score("serpapi"),
        ))

        ai_overview_text = next(
            (str(feat.data.get("text")) for feat in payload.features
             if feat.type == "ai_overview" and feat.data.get("text")),
            None,
        )
        if ai_overview_text and brand:
            _record_ai_overview_citation(
                s, tid=tid, pid=pid, query=query, text=ai_overview_text, locale=payload.locale,
                brand=brand, own_domain=own_domain, competitor_names=competitor_names,
                competitor_domains=competitor_domains, now=now,
            )
        s.add(OutboxEvent(
            tenant_id=tid, project_id=pid, type="serp.analyzed", version=1,
            correlation_id=correlation_id or str(uuid.uuid4()),
            payload={"serp_run_id": str(run.id), "query": query,
                     "features": analysis.feature_types, "top_domains": analysis.top_domains},
        ))
    log.info("serp.analyzed", query=query, features=analysis.feature_types,
             top_domains=analysis.top_domains[:5])
    return {
        "top_domains": analysis.top_domains, "feature_types": analysis.feature_types,
        "questions": analysis.questions, "content_gap": analysis.content_gap,
    }


def _domain(url: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or "").removeprefix("www.")


def _record_ai_overview_citation(
    s: Session, *, tid: uuid.UUID, pid: uuid.UUID, query: str, text: str, locale: str,
    brand: str, own_domain: str | None, competitor_names: list[str] | None,
    competitor_domains: list[str] | None, now: dt.datetime,
) -> None:
    """Parses brand/competitor citations out of a Google AI Overview block and records the same
    evidence trail `geo.battery` uses for chat providers — under provider='google_ai_overview',
    a synthetic per-query `AiPrompt` (kind='ai_overview'). Citation-only: aggregate visibility
    scoring across many AI Overview pulls belongs in a batch job (like `geo.battery`), since
    `ai_visibility_scores` aggregates per cluster+week and a single query would collide there."""
    text_hash = content_hash(query)
    prompt = s.query(AiPrompt).filter(
        AiPrompt.project_id == pid, AiPrompt.kind == "ai_overview", AiPrompt.text_hash == text_hash,
    ).one_or_none()
    if prompt is None:
        prompt = AiPrompt(tenant_id=tid, project_id=pid, kind="ai_overview", text=query,
                          text_hash=text_hash, version="1")
        s.add(prompt)
        s.flush()

    prompt_run = AiPromptRun(
        tenant_id=tid, project_id=pid, prompt_id=prompt.id, prompt_version=prompt.version,
        provider="google_ai_overview", model="ai_overview", model_version="ai_overview",
        locale=locale, ran_at=now, parser="seo_core.geo.citations", parser_version="0.1.0",
    )
    s.add(prompt_run)
    s.flush()

    resp_hash = content_hash(text)
    s.add(AiResponse(tenant_id=tid, project_id=pid, prompt_run_id=prompt_run.id,
                     content_hash=resp_hash, text=text))
    s.add(Evidence(
        tenant_id=tid, project_id=pid, kind="ai_response", source_url=None,
        ai_prompt_run_id=prompt_run.id, content_hash=resp_hash, provider="google_ai_overview",
        parser="seo_core.geo.citations", parser_version="0.1.0",
        collected_at=now, confidence=confidence_score("ai_response"),
    ))

    cit = parse_citations(
        text, brand=brand, own_domain=own_domain or "", competitor_names=competitor_names or [],
        competitor_domains=competitor_domains,
    )
    s.add(AiCitation(
        tenant_id=tid, project_id=pid, prompt_run_id=prompt_run.id,
        brand_mentioned=cit.brand_mentioned, brand_position=cit.brand_position,
        competitors_mentioned=cit.competitors_mentioned, cited_urls=cit.cited_urls,
        own_url_cited=cit.own_url_cited, sentiment=cit.sentiment,
    ))


_ = SerpItem  # keep import (SerpItem re-exported for job callers/tests)
