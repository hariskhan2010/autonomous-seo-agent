"""`content.analyze` worker job (A-TO-Z-PLAN.md §Phase 5).

Builds the content inventory from a crawl run, scores each item with the deterministic rubric,
flags thin/outdated/orphan pages, detects cannibalization, and emits `content.analyzed`.

`llm_judge` / `judge_and_revise` are the Phase 5 deferred LLM judge + revision loop: LLM-calling
logic belongs in the worker, never in `seo_core` (which stays pure/deterministic, §V)."""

from __future__ import annotations

import datetime as dt
import uuid

import structlog
from pydantic import BaseModel

from db.models.content import ContentItem, ContentScore
from db.models.crawl import CrawlResult, CrawlRun
from db.models.events import OutboxEvent
from db.session import tenant_session
from llm import Message, Role
from llm.router import complete, complete_structured
from seo_core.content import (
    cannibalization_groups,
    classify_content_type,
    content_flags,
    rule_judge,
)
from seo_core.content.judge import RUBRIC_DIMENSIONS, RubricScore
from seo_core.content.signals import ContentRow
from seo_core.crawl.fingerprint import content_hash

log = structlog.get_logger("job.content")
UTC = dt.UTC


class _JudgeVerdict(BaseModel):
    score: float
    verdict: str
    dimensions: dict[str, float]
    notes: str


def llm_judge(
    text: str, *, keyword: str | None = None, target_words: int = 700,
    expected_headings: list[str] | None = None, tenant_id: str | None = None,
    project_id: str | None = None, correlation_id: str | None = None,
) -> RubricScore:
    """LLM-scored rubric via the `JUDGE` role — cross-checked against `rule_judge`, never the
    sole arbiter (A-TO-Z-PLAN.md §Phase 5). A wild disagreement (>30 pts) or a call/parse failure
    falls back to the deterministic rule score rather than trusting the LLM blindly."""
    baseline = rule_judge(text, keyword=keyword, target_words=target_words,
                          expected_headings=expected_headings)
    system = (
        "You are a strict SEO content quality judge. Score the article on these dimensions "
        f"(0-20 each, sum is the overall score out of 100): {', '.join(RUBRIC_DIMENSIONS)}. "
        "verdict is PASS (score >= 70), REVISE (40-69), or FAIL (< 40). Be specific and "
        "critical in `notes` — name what's missing, not just that something is."
    )
    messages = [Message("user", f"Target keyword: {keyword or '(none)'}\n\n{text}")]
    try:
        parsed, _ = complete_structured(
            Role.JUDGE, system=system, messages=messages, schema=_JudgeVerdict,
            tenant_id=tenant_id, project_id=project_id, caller="content.llm_judge",
            correlation_id=correlation_id,
        )
    except Exception:
        log.warning("llm_judge.failed_using_rule_baseline", rule_score=baseline.score)
        return baseline

    if abs(parsed.score - baseline.score) > 30:
        log.warning("llm_judge.disagreement_with_rule_baseline",
                    llm_score=parsed.score, rule_score=baseline.score)
        return baseline
    return RubricScore(score=parsed.score, verdict=parsed.verdict, dimensions=parsed.dimensions,
                       scorer="llm", notes=parsed.notes)


def _revise(
    text: str, judged: RubricScore, *, keyword: str | None, tenant_id: str | None,
    project_id: str | None, correlation_id: str | None,
) -> str:
    weak = ", ".join(d for d, _ in sorted(judged.dimensions.items(), key=lambda kv: kv[1])[:2])
    system = (
        "You are an SEO content editor. Revise the article to address its weakest rubric "
        f"dimensions ({weak or 'overall quality'}) per the judge's notes, without changing its "
        "factual claims. Return only the revised article body — no preamble, no commentary."
    )
    messages = [Message(
        "user",
        f"Target keyword: {keyword or '(none)'}\n\nJudge notes: {judged.notes}\n\n---\n{text}",
    )]
    result = complete(Role.WORKER, system=system, messages=messages, tenant_id=tenant_id,
                      project_id=project_id, caller="content.revision",
                      correlation_id=correlation_id)
    return result.text


def judge_and_revise(
    text: str, *, keyword: str | None = None, target_words: int = 700,
    expected_headings: list[str] | None = None, tenant_id: str | None = None,
    project_id: str | None = None, max_revisions: int = 3,
    correlation_id: str | None = None,
) -> dict[str, object]:
    """The Phase-5 quality gate loop: judge → if REVISE, revise → re-judge, up to `max_revisions`
    times (A-TO-Z-PLAN.md pipeline: `fact-checker → judge → if REVISE: revision (max 3) →
    re-judge`). A cheap `rule_judge` PASS short-circuits before any LLM call is made."""
    current = text
    quick = rule_judge(current, keyword=keyword, target_words=target_words,
                       expected_headings=expected_headings)
    if quick.verdict == "PASS":
        return {"text": current, "judged": quick, "revisions": 0}

    judged = llm_judge(current, keyword=keyword, target_words=target_words,
                       expected_headings=expected_headings, tenant_id=tenant_id,
                       project_id=project_id, correlation_id=correlation_id)
    attempts = 0
    while judged.verdict == "REVISE" and attempts < max_revisions:
        current = _revise(current, judged, keyword=keyword, tenant_id=tenant_id,
                          project_id=project_id, correlation_id=correlation_id)
        attempts += 1
        judged = llm_judge(current, keyword=keyword, target_words=target_words,
                           expected_headings=expected_headings, tenant_id=tenant_id,
                           project_id=project_id, correlation_id=correlation_id)
    return {"text": current, "judged": judged, "revisions": attempts}


def run(tenant_id: str, project_id: str, crawl_run_id: str,
        correlation_id: str | None = None) -> dict[str, object]:
    tid, pid, rid = uuid.UUID(tenant_id), uuid.UUID(project_id), uuid.UUID(crawl_run_id)
    now = dt.datetime.now(UTC)

    with tenant_session(tid, pid) as s:
        if s.get(CrawlRun, rid) is None:
            raise ValueError("crawl_run not found")
        results = (
            s.query(CrawlResult)
            .filter(CrawlResult.crawl_run_id == rid, CrawlResult.http_status == 200)
            .all()
        )
        incoming: dict[str, int] = {}
        for r in results:
            for link in r.internal_links or []:
                incoming[link] = incoming.get(link, 0) + 1

        rows: list[ContentRow] = []
        upserts = 0
        for r in results:
            ctype = classify_content_type(
                url=r.url,
                schema_types=[str(b.get("@type", "")) for b in (r.schema_blocks or [])],
                word_count=r.word_count,
                internal_link_count=len(r.internal_links or []),
            )
            uh = content_hash(r.url)
            crow = ContentRow(
                url=r.url, content_type=ctype, word_count=r.word_count,
                internal_links_in=incoming.get(r.url, 0),
            )
            rows.append(crow)
            flags = content_flags(crow, now=now)

            item = (
                s.query(ContentItem)
                .filter(ContentItem.project_id == pid, ContentItem.url_hash == uh)
                .one_or_none()
            )
            if item is None:
                item = ContentItem(
                    tenant_id=tid, project_id=pid, url=r.url, url_hash=uh, content_type=ctype,
                    title=r.title, word_count=r.word_count, flags=flags,
                )
                s.add(item)
                s.flush()
            else:
                item.content_type = ctype
                item.title = r.title
                item.word_count = r.word_count
                item.flags = flags
                s.add(item)
                s.flush()
            upserts += 1

            # Text proxy from parsed fields; full-body scoring reads the snapshot's raw_key later.
            text_proxy = " ".join(filter(None, [
                r.title, r.meta_description, r.h1,
                *(h for hs in (r.headings or {}).values() for h in hs),
            ]))
            rj = rule_judge(text_proxy, keyword=None, target_words=max(1, r.word_count or 700))
            s.add(ContentScore(
                tenant_id=tid, project_id=pid, content_item_id=item.id, scorer="rule",
                score=rj.score, verdict=rj.verdict, dimensions=rj.dimensions,
            ))

        groups = cannibalization_groups(rows)
        by_flag: dict[str, int] = {}
        for row in rows:
            for f in content_flags(row, now=now):
                by_flag[f] = by_flag.get(f, 0) + 1

        s.add(OutboxEvent(
            tenant_id=tid, project_id=pid, type="content.analyzed", version=1,
            correlation_id=correlation_id or str(uuid.uuid4()),
            payload={"items": upserts, "flags": by_flag, "cannibalization_groups": len(groups)},
        ))

    log.info("content.analyzed", items=upserts, flags=by_flag, cannibalization=len(groups))
    return {"items": upserts, "flags": by_flag, "cannibalization_groups": groups}
