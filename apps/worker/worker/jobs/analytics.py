"""Analytics + learning worker jobs (A-TO-Z-PLAN.md §Phase 9).

metrics.ingest    — pull a date range from the provider → metric_snapshots (idempotent).
anomaly.detect    — run the deterministic detector over a metric → anomalies + investigation stub.
experiment.eval   — evaluate a concluded experiment with the methodology engine (no causal claims
                    without a control arm) → verdict + learning + opportunity-weight update.
"""

from __future__ import annotations

import datetime as dt
import uuid

import structlog
from integrations.analytics import FakeMetricsProvider, get_metrics_provider
from sqlalchemy import Numeric, cast, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from common.crypto import decrypt_secret
from db.models.analytics import (
    Anomaly,
    Experiment,
    Learning,
    MetricSnapshot,
    OpportunityWeight,
)
from db.models.credential import OAuthCredential
from db.models.events import OutboxEvent
from db.session import tenant_session
from seo_core.analytics.anomaly import Point, detect_anomalies
from seo_core.analytics.experiments import ExperimentSpec, evaluate_experiment

log = structlog.get_logger("job.analytics")
UTC = dt.UTC


def _active_google_credential(s: Session, project_id: uuid.UUID) -> OAuthCredential | None:
    return s.query(OAuthCredential).filter(
        OAuthCredential.project_id == project_id, OAuthCredential.provider == "google",
        OAuthCredential.revoked_at.is_(None),
    ).order_by(OAuthCredential.connected_at.desc()).first()


def ingest(tenant_id: str, project_id: str, *, days: int = 90,
           metrics: list[str] | None = None, use_fake: bool = False,
           fake_drop_on: str | None = None, provider_kind: str = "gsc",
           site_url: str | None = None, property_id: str | None = None,
           refresh_token: str | None = None, correlation_id: str | None = None) -> dict[str, object]:
    tid, pid = uuid.UUID(tenant_id), uuid.UUID(project_id)
    metrics = metrics or ["clicks", "impressions", "position", "organic_sessions"]
    end = dt.date.today()
    start = end - dt.timedelta(days=days)

    # Phase 12/13: fall back to the project's stored, encrypted Google connection when the caller
    # didn't pass a refresh_token explicitly — closes the gap `get_metrics_provider`'s own
    # docstring used to flag as "per-tenant connection storage isn't wired up yet."
    if not use_fake and not refresh_token and provider_kind in ("gsc", "ga4"):
        with tenant_session(tid, pid) as s:
            cred = _active_google_credential(s, pid)
            if cred is not None:
                refresh_token = decrypt_secret(cred.encrypted_refresh_token)
                if provider_kind == "ga4" and not property_id:
                    property_id = cred.provider_meta.get("ga4_property_id")

    provider = (
        FakeMetricsProvider(drop_on=dt.date.fromisoformat(fake_drop_on) if fake_drop_on else None)
        if use_fake else get_metrics_provider(
            provider_kind, site_url=site_url, property_id=property_id, refresh_token=refresh_token,
        )
    )
    rows = provider.fetch(start=start, end=end, metrics=metrics)

    with tenant_session(tid, pid) as s:
        upserts = 0
        for r in rows:
            existing = s.query(MetricSnapshot).filter(
                MetricSnapshot.project_id == pid, MetricSnapshot.metric == r.metric,
                MetricSnapshot.scope == r.scope, MetricSnapshot.scope_ref == r.scope_ref,
                MetricSnapshot.date == r.date,
            ).one_or_none()
            if existing is None:
                s.add(MetricSnapshot(
                    tenant_id=tid, project_id=pid, metric=r.metric, scope=r.scope,
                    scope_ref=r.scope_ref, date=r.date, value=r.value, source=r.source,
                ))
                upserts += 1
            else:
                existing.value = r.value
        s.add(OutboxEvent(tenant_id=tid, project_id=pid, type="metrics.ingested", version=1,
                          correlation_id=correlation_id or str(uuid.uuid4()),
                          payload={"rows": len(rows), "new": upserts, "metrics": metrics}))
    log.info("metrics.ingested", rows=len(rows), new=upserts)
    return {"rows": len(rows), "new": upserts}


def detect(tenant_id: str, project_id: str, metric: str,
           correlation_id: str | None = None) -> dict[str, object]:
    tid, pid = uuid.UUID(tenant_id), uuid.UUID(project_id)
    with tenant_session(tid, pid) as s:
        snaps = s.query(MetricSnapshot).filter(
            MetricSnapshot.project_id == pid, MetricSnapshot.metric == metric,
            MetricSnapshot.scope == "site",
        ).order_by(MetricSnapshot.date).all()
        series = [Point(date=sn.date, value=float(sn.value)) for sn in snaps]
        hits = detect_anomalies(metric, series)
        created = 0
        for h in hits:
            exists = s.query(Anomaly).filter(
                Anomaly.project_id == pid, Anomaly.metric == h.metric,
                Anomaly.detected_on == h.date,
            ).first()
            if exists:
                continue
            s.add(Anomaly(
                tenant_id=tid, project_id=pid, metric=h.metric, detected_on=h.date,
                direction=h.direction, magnitude_pct=h.magnitude_pct, baseline=h.baseline,
                observed=h.observed, z_score=h.z_score, status="open",
                investigation={"checklist": ["gsc", "rankings", "indexation",
                                             "deployment_history", "crawl_errors"]},
            ))
            created += 1
        if created:
            s.add(OutboxEvent(tenant_id=tid, project_id=pid, type="traffic.anomaly.detected",
                              version=1, correlation_id=correlation_id or str(uuid.uuid4()),
                              payload={"metric": metric, "count": created}))
    log.info("anomaly.detected", metric=metric, count=created)
    return {"metric": metric, "anomalies": created}


def evaluate(tenant_id: str, project_id: str, experiment_id: str,
             correlation_id: str | None = None) -> dict[str, object]:
    tid, pid, eid = uuid.UUID(tenant_id), uuid.UUID(project_id), uuid.UUID(experiment_id)
    with tenant_session(tid, pid) as s:
        exp = s.get(Experiment, eid)
        if exp is None:
            raise ValueError("experiment not found")

        def _vals(metric: str, a: dt.date, b: dt.date, refs: list[str] | None = None) -> list[float]:
            q = s.query(MetricSnapshot).filter(
                MetricSnapshot.project_id == pid, MetricSnapshot.metric == metric,
                MetricSnapshot.date >= a, MetricSnapshot.date <= b,
            )
            if refs:
                q = q.filter(MetricSnapshot.scope_ref.in_(refs))
            return [float(x.value) for x in q.all()]

        t_end = exp.treatment_start + dt.timedelta(days=exp.measurement_window_days)
        control = exp.control or {}
        spec = ExperimentSpec(
            primary_metric=exp.primary_metric,
            baseline=_vals(exp.primary_metric, exp.baseline_start, exp.baseline_end),
            treatment=_vals(exp.primary_metric, exp.treatment_start, t_end),
            treatment_start=exp.treatment_start,
            measurement_window_days=exp.measurement_window_days,
            control_baseline=_vals(exp.primary_metric, exp.baseline_start, exp.baseline_end,
                                   control.get("refs")) if control.get("kind") == "holdout" else [],
            control_treatment=_vals(exp.primary_metric, exp.treatment_start, t_end,
                                    control.get("refs")) if control.get("kind") == "holdout" else [],
            tracking_changed=bool((exp.methodology or {}).get("tracking_changed")),
        )
        res = evaluate_experiment(spec)
        exp.state = "concluded"
        exp.verdict = res.verdict
        exp.confidence = res.confidence
        exp.confounders = res.confounders
        exp.result = {
            "effect_pct": res.effect_pct, "control_adjusted_pct": res.control_adjusted_pct,
            "causal_language_allowed": res.causal_language_allowed,
        }
        exp.methodology = {**(exp.methodology or {}), **res.methodology}
        exp.concluded_at = dt.datetime.now(UTC)
        s.add(exp)

        weight_delta = 0.0
        if res.verdict == "success" and res.confidence >= 0.7:
            weight_delta = 0.1
        elif res.verdict == "regression" and res.confidence >= 0.7:
            weight_delta = -0.15

        learning = Learning(
            tenant_id=tid, project_id=pid, source_type="experiment", source_id=eid,
            opportunity_type=exp.experiment_type, verdict=res.verdict, confidence=res.confidence,
            weight_delta=weight_delta,
            statement=(f"{exp.experiment_type}: {res.verdict} "
                       f"({'associated with' if not res.causal_language_allowed else 'caused'} "
                       f"{res.effect_pct:+.1f}% on {exp.primary_metric}; "
                       f"{'controlled' if res.methodology['has_control'] else 'before/after only'})"),
            methodology_note=str(res.methodology),
        )
        s.add(learning)
        s.flush()

        if weight_delta:
            # Atomic upsert (Phase 13 hardening), not check-then-insert-or-update: two experiments
            # that share an `opportunity_type` can genuinely conclude around the same time on two
            # different workers, and this row might not exist yet for either of them. A
            # SELECT ... FOR UPDATE only locks a row that already exists — it does nothing for the
            # brand-new-opportunity_type case, where both transactions see no row, both try to
            # INSERT, and one loses to a UniqueViolation (proven by
            # `test_concurrent_evaluations_sharing_an_opportunity_type_dont_lose_an_update`, which
            # is exactly this scenario). `INSERT ... ON CONFLICT DO UPDATE` handles the insert-race
            # AND the update-race in one atomic statement, computed from the row's actual current
            # value at the database level rather than a value read earlier in Python.
            fresh_multiplier = round(max(0.3, min(2.0, 1.0 + weight_delta)), 3)
            stmt = pg_insert(OpportunityWeight).values(
                tenant_id=tid, project_id=pid, opportunity_type=exp.experiment_type,
                multiplier=fresh_multiplier, updated_from_learning=learning.id,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_opportunity_weights_type",
                set_={
                    # Postgres's 2-arg `round()` only has a `numeric` overload, not
                    # `double precision` — without the explicit cast this raises
                    # `function round(double precision, integer) does not exist`.
                    "multiplier": func.round(
                        cast(
                            func.greatest(0.3, func.least(
                                2.0, OpportunityWeight.multiplier + weight_delta,
                            )),
                            Numeric(5, 3),
                        ), 3,
                    ),
                    "updated_from_learning": stmt.excluded.updated_from_learning,
                },
            )
            s.execute(stmt)

        s.add(OutboxEvent(tenant_id=tid, project_id=pid, type="experiment.completed", version=1,
                          correlation_id=correlation_id or str(uuid.uuid4()),
                          payload={"experiment_id": experiment_id, "verdict": res.verdict,
                                   "weight_delta": weight_delta}))

    log.info("experiment.evaluated", experiment_id=experiment_id, verdict=res.verdict,
             weight_delta=weight_delta)
    return {"verdict": res.verdict, "confidence": res.confidence, "effect_pct": res.effect_pct,
            "confounders": res.confounders, "causal_language_allowed": res.causal_language_allowed,
            "weight_delta": weight_delta}
