"""`geo.battery` worker job (A-TO-Z-PLAN.md §Phase 10).

For a cluster's prompt set × providers: run each → store raw response (evidence, kind='ai_response')
+ parsed citations + a weekly AI Visibility Score per provider. Full context on every datapoint."""

from __future__ import annotations

import datetime as dt
import uuid

import structlog
from integrations.ai_providers import FakeAiProvider, get_ai_provider

from db.models.events import OutboxEvent
from db.models.evidence import Evidence
from db.models.geo import AiCitation, AiPrompt, AiPromptRun, AiResponse, AiVisibilityScore
from db.session import tenant_session
from seo_core.confidence import score as confidence_score
from seo_core.crawl.fingerprint import content_hash
from seo_core.geo import generate_prompt_library, parse_citations, visibility_score
from seo_core.geo.citations import Citation

log = structlog.get_logger("job.geo")
UTC = dt.UTC


def _week(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def seed_prompts(tenant_id: str, project_id: str, *, cluster_id: str, brand: str, category: str,
                 seed_keywords: list[str] | None = None,
                 competitor_names: list[str] | None = None) -> dict[str, object]:
    """Generates the deterministic ~30-50 prompt battery for a cluster (`seo_core.geo.prompts`)
    and upserts it as `AiPrompt` rows — idempotent on (project_id, kind, text_hash), so re-running
    for the same cluster/brand/category never duplicates prompts, only adds newly-generated ones."""
    tid, pid, cid = uuid.UUID(tenant_id), uuid.UUID(project_id), uuid.UUID(cluster_id)
    generated = generate_prompt_library(
        brand=brand, category=category, seed_keywords=seed_keywords,
        competitor_names=competitor_names,
    )
    created = 0
    with tenant_session(tid, pid) as s:
        for gp in generated:
            text_hash = content_hash(gp.text)
            existing = s.query(AiPrompt).filter(
                AiPrompt.project_id == pid, AiPrompt.kind == gp.kind,
                AiPrompt.text_hash == text_hash,
            ).one_or_none()
            if existing is None:
                s.add(AiPrompt(tenant_id=tid, project_id=pid, cluster_id=cid, kind=gp.kind,
                               text=gp.text, text_hash=text_hash, version="1"))
                created += 1
    log.info("geo.prompts.seeded", cluster_id=cluster_id, generated=len(generated), created=created)
    return {"generated": len(generated), "created": created}


def battery(tenant_id: str, project_id: str, *, cluster_id: str | None = None,
            providers: list[str] | None = None, brand: str, own_domain: str,
            competitor_names: list[str] | None = None, competitor_domains: list[str] | None = None,
            use_fake: bool = False, correlation_id: str | None = None) -> dict[str, object]:
    tid, pid = uuid.UUID(tenant_id), uuid.UUID(project_id)
    providers = providers or (["fake"] if use_fake else ["openrouter", "gemini", "perplexity"])
    now = dt.datetime.now(UTC)
    week = _week(now.date())

    with tenant_session(tid, pid) as s:
        q = s.query(AiPrompt).filter(AiPrompt.project_id == pid, AiPrompt.active.is_(True))
        if cluster_id:
            q = q.filter(AiPrompt.cluster_id == uuid.UUID(cluster_id))
        prompts = q.all()
        if not prompts:
            return {"prompts": 0, "note": "no active prompts for this cluster"}

        per_provider: dict[str, list[object]] = {p: [] for p in providers}
        runs = 0
        for prov_name in providers:
            provider = FakeAiProvider() if (use_fake or prov_name == "fake") else get_ai_provider(prov_name)
            for prompt in prompts:
                res = provider.ask(prompt.text)
                ch = content_hash(res.text)
                run = AiPromptRun(
                    tenant_id=tid, project_id=pid, prompt_id=prompt.id,
                    prompt_version=prompt.version, provider=res.provider, model=res.model,
                    model_version=res.model_version, locale=res.locale, ran_at=res.ran_at,
                )
                s.add(run)
                s.flush()
                s.add(AiResponse(tenant_id=tid, project_id=pid, prompt_run_id=run.id,
                                 content_hash=ch, text=res.text))
                s.add(Evidence(
                    tenant_id=tid, project_id=pid, kind="ai_response", source_url=None,
                    ai_prompt_run_id=run.id, content_hash=ch, provider=res.provider,
                    parser="seo_core.geo.citations", parser_version="0.1.0",
                    collected_at=now, confidence=confidence_score("ai_response"),
                ))
                cit = parse_citations(
                    res.text, brand=brand, own_domain=own_domain,
                    competitor_names=competitor_names or [],
                    competitor_domains=competitor_domains or [],
                )
                s.add(AiCitation(
                    tenant_id=tid, project_id=pid, prompt_run_id=run.id,
                    brand_mentioned=cit.brand_mentioned, brand_position=cit.brand_position,
                    competitors_mentioned=cit.competitors_mentioned, cited_urls=cit.cited_urls,
                    own_url_cited=cit.own_url_cited, sentiment=cit.sentiment,
                ))
                per_provider[res.provider].append(cit)
                runs += 1

        scores: dict[str, float] = {}
        for prov, cits in per_provider.items():
            if not cits:
                continue
            vs = visibility_score([c for c in cits if isinstance(c, Citation)])
            scores[prov] = vs.score
            existing = s.query(AiVisibilityScore).filter(
                AiVisibilityScore.project_id == pid,
                AiVisibilityScore.provider == prov,
                AiVisibilityScore.week == week,
                AiVisibilityScore.cluster_id == (uuid.UUID(cluster_id) if cluster_id else None),
            ).one_or_none()
            payload = dict(
                score=vs.score, brand_mention_rate=vs.brand_mention_rate,
                own_citation_rate=vs.own_citation_rate, prompts_run=vs.prompts_run,
                detail={"avg_brand_position": vs.avg_brand_position,
                        "competitor_share": vs.competitor_share},
            )
            if existing:
                for k, v in payload.items():
                    setattr(existing, k, v)
            else:
                s.add(AiVisibilityScore(
                    tenant_id=tid, project_id=pid,
                    cluster_id=uuid.UUID(cluster_id) if cluster_id else None,
                    provider=prov, week=week, **payload,
                ))

        s.add(OutboxEvent(tenant_id=tid, project_id=pid, type="geo.battery.completed", version=1,
                          correlation_id=correlation_id or str(uuid.uuid4()),
                          payload={"runs": runs, "providers": providers, "scores": scores}))

    log.info("geo.battery.completed", runs=runs, scores=scores)
    return {"runs": runs, "providers": providers, "visibility_scores": scores}
