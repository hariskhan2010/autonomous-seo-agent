"""Reporting engine (A-TO-Z-PLAN.md §Phase 12, §44 — deterministic).

Produces Markdown reports from structured data (issues, opportunities, metrics, changes,
experiments, AI visibility). PDF/email delivery is a thin wrapper added with the mail provider.
Every figure cites its source; no LLM in the numbers (§V) — an optional `WORKER` pass only
phrases the executive summary prose."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass
class Report:
    title: str
    generated_at: dt.datetime
    markdown: str
    sections: list[str] = field(default_factory=list)


def _table(headers: list[str], rows: list[list[object]]) -> str:
    if not rows:
        return "_(none)_\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out) + "\n"


def executive_report(
    *,
    project_name: str,
    metrics: dict[str, tuple[float, float]],   # metric -> (current, prior)
    open_opportunities: list[dict[str, object]],
    recent_changes: list[dict[str, object]],
    ai_visibility: dict[str, float],
    now: dt.datetime | None = None,
) -> Report:
    now = now or dt.datetime.now(dt.UTC)
    lines = [f"# Executive SEO Report — {project_name}", "", f"_Generated {now:%Y-%m-%d}_", ""]

    lines.append("## Performance (vs prior period)\n")
    rows: list[list[object]] = []
    for m, (cur, prior) in metrics.items():
        delta = ((cur - prior) / prior * 100) if prior else 0.0
        arrow = "▲" if delta > 1 else ("▼" if delta < -1 else "▬")
        rows.append([m, f"{cur:,.1f}", f"{prior:,.1f}", f"{arrow} {delta:+.1f}%"])
    lines.append(_table(["Metric", "Current", "Prior", "Change"], rows))

    p0p1 = [o for o in open_opportunities if o.get("priority") in ("P0", "P1")]
    lines.append(f"## Priority opportunities ({len(p0p1)} of {len(open_opportunities)} open)\n")
    lines.append(_table(
        ["Priority", "Type", "Title", "Score", "Action class"],
        [[o.get("priority"), o.get("type"), str(o.get("title", ""))[:60], f"{float(o.get('score', 0) or 0):.0f}", o.get("action_class", "")]
         for o in sorted(p0p1, key=lambda x: -x.get("score", 0))[:15]],
    ))

    lines.append("## Recent changes\n")
    lines.append(_table(
        ["Target", "State", "Verified", "Applied"],
        [[c["target"][:50], c["state"], "✓" if c.get("verified") else "—",
          (c.get("applied_at") or "")[:10]] for c in recent_changes[:15]],
    ))

    lines.append("## AI-search visibility (by provider)\n")
    lines.append(_table(["Provider", "Visibility score (0-100)"],
                        [[p, f"{s:.1f}"] for p, s in sorted(ai_visibility.items())]))

    md = "\n".join(lines)
    return Report(title=f"Executive SEO Report — {project_name}", generated_at=now, markdown=md,
                  sections=["performance", "opportunities", "changes", "ai_visibility"])


def technical_report(
    *, project_name: str, issues_by_severity: dict[str, list[dict[str, object]]],
    now: dt.datetime | None = None,
) -> Report:
    now = now or dt.datetime.now(dt.UTC)
    lines = [f"# Technical SEO Report — {project_name}", "", f"_Generated {now:%Y-%m-%d}_", ""]
    order = ["critical", "high", "medium", "low", "info"]
    total = sum(len(v) for v in issues_by_severity.values())
    lines.append(f"**{total} open issues** — "
                 + ", ".join(f"{len(issues_by_severity.get(s, []))} {s}" for s in order) + "\n")
    for sev in order:
        items = issues_by_severity.get(sev, [])
        if not items:
            continue
        lines.append(f"## {sev.title()} ({len(items)})\n")
        lines.append(_table(
            ["Check", "URL / pattern", "Fix"],
            [[i.get("check_code"), str(i.get("url") or i.get("url_pattern") or "*")[:50],
              str(i.get("fix") or "")[:70]] for i in items[:30]],
        ))
    md = "\n".join(lines)
    return Report(title=f"Technical SEO Report — {project_name}", generated_at=now, markdown=md,
                  sections=order)
