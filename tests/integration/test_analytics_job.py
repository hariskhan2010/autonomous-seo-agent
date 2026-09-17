"""Analytics + learning jobs against Neon (A-TO-Z-PLAN.md §Phase 9 acceptance)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from db.models.analytics import (
    Anomaly,
    Experiment,
    Learning,
    MetricSnapshot,
    OpportunityWeight,
)
from db.models.credential import OAuthCredential
from db.models.events import OutboxEvent
from db.models.identity import Tenant
from db.models.project import Project
from db.session import tenant_session

UTC = dt.UTC


@pytest.fixture
def project():
    t, p = uuid.uuid4(), uuid.uuid4()
    with tenant_session(t, p) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        s.add(Project(id=p, tenant_id=t, name="P", slug="p", approval_mode="assisted"))
    yield t, p
    with tenant_session(t, p) as s:
        for m in (Learning, OpportunityWeight, Anomaly, Experiment, MetricSnapshot,
                  OutboxEvent, OAuthCredential, Project, Tenant):
            s.query(m).delete()


def test_ingest_then_detect_anomaly(project) -> None:
    from worker.jobs.analytics import detect, ingest

    t, p = project
    drop_day = (dt.date.today() - dt.timedelta(days=12)).isoformat()
    out = ingest(str(t), str(p), days=90, metrics=["clicks"], use_fake=True, fake_drop_on=drop_day)
    assert out["new"] > 60

    d = detect(str(t), str(p), "clicks")
    assert d["anomalies"] >= 1
    with tenant_session(t, p) as s:
        a = s.query(Anomaly).first()
        assert a.direction == "drop" and a.metric == "clicks"
        assert s.query(OutboxEvent).filter(OutboxEvent.type == "traffic.anomaly.detected").count() == 1


def test_ingest_resolves_a_stored_google_credential_when_no_token_is_passed(
    project, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 12/13: `get_metrics_provider`'s docstring used to say per-tenant connection storage
    "isn't wired up yet" — this proves the wiring, without a real Google network call."""
    import worker.jobs.analytics as analytics_module

    from common.crypto import encrypt_secret

    t, p = project
    with tenant_session(t, p) as s:
        s.add(OAuthCredential(
            tenant_id=t, project_id=p, provider="google", account_email="me@example.com",
            scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
            encrypted_refresh_token=encrypt_secret("the-real-refresh-token"),
            connected_by=uuid.uuid4(), connected_at=dt.datetime.now(UTC),
        ))

    captured: dict[str, object] = {}

    class _StubProvider:
        name = "gsc"

        def fetch(self, *, start, end, metrics):  # noqa: ANN001 - matches MetricsProvider Protocol
            return []

    def fake_get_metrics_provider(kind, *, site_url=None, property_id=None, refresh_token=None):
        captured["kind"], captured["refresh_token"] = kind, refresh_token
        return _StubProvider()

    monkeypatch.setattr(analytics_module, "get_metrics_provider", fake_get_metrics_provider)

    analytics_module.ingest(str(t), str(p), days=5, metrics=["clicks"], provider_kind="gsc",
                            site_url="https://example.com/")
    assert captured["refresh_token"] == "the-real-refresh-token"


def test_experiment_eval_records_learning_and_shifts_weight(project) -> None:
    from worker.jobs.analytics import evaluate

    t, p = project
    b_start = dt.date(2026, 1, 1)
    b_end = dt.date(2026, 1, 20)
    t_start = dt.date(2026, 2, 1)
    with tenant_session(t, p) as s:
        # seed a clean baseline + a strong treatment lift + a flat control
        d = b_start
        while d <= t_start + dt.timedelta(days=30):
            in_treat = d >= t_start
            s.add(MetricSnapshot(tenant_id=t, project_id=p, metric="clicks", scope="site",
                                 scope_ref="*", date=d, value=130.0 if in_treat else 100.0))
            s.add(MetricSnapshot(tenant_id=t, project_id=p, metric="clicks", scope="page",
                                 scope_ref="holdout", date=d, value=100.0))
            d += dt.timedelta(days=1)
        exp = Experiment(
            tenant_id=t, project_id=p, experiment_type="title", hypothesis="new titles lift CTR",
            primary_metric="clicks", baseline_start=b_start, baseline_end=b_end,
            treatment_start=t_start, measurement_window_days=28,
            control={"kind": "holdout", "refs": ["holdout"]}, state="measuring",
        )
        s.add(exp)
        s.flush()
        eid = str(exp.id)

    res = evaluate(str(t), str(p), eid)
    assert res["verdict"] == "success"
    assert res["causal_language_allowed"] is True
    assert res["weight_delta"] > 0

    with tenant_session(t, p) as s:
        learning = s.query(Learning).one()
        assert "caused" in learning.statement
        w = s.query(OpportunityWeight).filter(OpportunityWeight.opportunity_type == "title").one()
        assert float(w.multiplier) > 1.0


def test_concurrent_evaluations_sharing_an_opportunity_type_dont_lose_an_update(project) -> None:
    """Phase 13 hardening: two different experiments sharing an `opportunity_type` can genuinely
    conclude around the same time on two different workers, and the row may not exist yet for
    either of them — proves the atomic `INSERT ... ON CONFLICT DO UPDATE` upsert against real
    Postgres with two threads racing to create/update the same row."""
    from concurrent.futures import ThreadPoolExecutor

    from worker.jobs.analytics import evaluate

    t, p = project
    b_start = dt.date(2026, 1, 1)
    b_end = dt.date(2026, 1, 20)
    t_start = dt.date(2026, 2, 1)
    with tenant_session(t, p) as s:
        d = b_start
        while d <= t_start + dt.timedelta(days=30):
            in_treat = d >= t_start
            s.add(MetricSnapshot(tenant_id=t, project_id=p, metric="clicks", scope="site",
                                 scope_ref="*", date=d, value=130.0 if in_treat else 100.0))
            s.add(MetricSnapshot(tenant_id=t, project_id=p, metric="clicks", scope="page",
                                 scope_ref="holdout", date=d, value=100.0))
            d += dt.timedelta(days=1)
        exp_ids = []
        for _ in range(2):
            exp = Experiment(
                tenant_id=t, project_id=p, experiment_type="title", hypothesis="new titles lift CTR",
                primary_metric="clicks", baseline_start=b_start, baseline_end=b_end,
                treatment_start=t_start, measurement_window_days=28,
                control={"kind": "holdout", "refs": ["holdout"]}, state="measuring",
            )
            s.add(exp)
            s.flush()
            exp_ids.append(str(exp.id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda eid: evaluate(str(t), str(p), eid), exp_ids))

    for res in results:
        assert res["weight_delta"] > 0

    with tenant_session(t, p) as s:
        w = s.query(OpportunityWeight).filter(OpportunityWeight.opportunity_type == "title").one()
        expected = round(1.0 + sum(r["weight_delta"] for r in results), 3)
        assert float(w.multiplier) == pytest.approx(expected), (
            "final multiplier must reflect BOTH evaluations — a lost update would leave it "
            "equal to only one experiment's delta"
        )
        # two independent experiments each completed once — not one shared completion event.
        assert s.query(OutboxEvent).filter(OutboxEvent.type == "experiment.completed").count() == 2
