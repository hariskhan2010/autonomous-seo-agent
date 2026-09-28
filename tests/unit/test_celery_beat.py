"""Celery beat wiring (Phase 11 deferral): `scheduler.tick` + `events.relay` run on a timer for
every configured (tenant, project) target, at the intervals from `common.settings`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from worker.app import celery_app
from worker.beat import BeatTarget, build_beat_schedule, parse_beat_targets

from common.settings import settings

T1, P1 = str(uuid.uuid4()), str(uuid.uuid4())
T2, P2 = str(uuid.uuid4()), str(uuid.uuid4())
REPO = Path(__file__).resolve().parents[2]


def test_schedule_has_tick_and_relay_entries_per_target() -> None:
    sched = build_beat_schedule(
        [BeatTarget(T1, P1), BeatTarget(T2, P2)],
        scheduler_tick_seconds=60.0, events_relay_seconds=15.0,
    )
    assert set(sched) == {
        f"scheduler.tick:{P1}", f"events.relay:{P1}",
        f"scheduler.tick:{P2}", f"events.relay:{P2}",
    }
    tick = sched[f"scheduler.tick:{P1}"]
    assert tick["task"] == "scheduler.tick"
    assert tick["schedule"] == 60.0
    assert tick["kwargs"] == {"tenant_id": T1, "project_id": P1}
    assert tick["options"] == {"expires": 60.0}
    relay = sched[f"events.relay:{P2}"]
    assert relay["task"] == "events.relay"
    assert relay["schedule"] == 15.0
    assert relay["kwargs"] == {"tenant_id": T2, "project_id": P2}


def test_scheduled_task_names_are_registered_tasks() -> None:
    sched = build_beat_schedule([BeatTarget(T1, P1)], scheduler_tick_seconds=1,
                                events_relay_seconds=1)
    for entry in sched.values():
        assert entry["task"] in celery_app.tasks


def test_parse_targets_trims_dedupes_and_skips_blanks() -> None:
    raw = f" {T1}:{P1} ,, {T2}:{P2},{T1}:{P1} "
    assert parse_beat_targets(raw) == [BeatTarget(T1, P1), BeatTarget(T2, P2)]
    assert parse_beat_targets("") == []


@pytest.mark.parametrize("raw", ["not-a-pair", f"{T1}:nope", f"nope:{P1}"])
def test_parse_targets_rejects_malformed_pairs(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_beat_targets(raw)


def test_non_positive_interval_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_beat_schedule([BeatTarget(T1, P1)], scheduler_tick_seconds=0,
                            events_relay_seconds=15)


def test_app_conf_uses_the_settings_driven_schedule() -> None:
    assert celery_app.conf.beat_schedule == build_beat_schedule(
        parse_beat_targets(settings.beat_targets),
        scheduler_tick_seconds=settings.beat_scheduler_tick_seconds,
        events_relay_seconds=settings.beat_events_relay_seconds,
    )


def test_env_config_reaches_the_celery_app() -> None:
    """End to end in a fresh interpreter: env vars -> Settings -> `celery_app.conf.beat_schedule`
    (a subprocess, because `worker.app` builds the schedule once at import)."""
    env = {
        **os.environ,
        "BEAT_TARGETS": f"{T1}:{P1}",
        "BEAT_SCHEDULER_TICK_SECONDS": "120",
        "BEAT_EVENTS_RELAY_SECONDS": "5",
        "PYTHONPATH": os.pathsep.join(
            str(REPO / p) for p in ("", "packages", "apps/api", "apps/worker")
        ),
    }
    code = (
        "import json; from worker.app import celery_app as a; "
        "print(json.dumps({k: [v['task'], v['schedule']] "
        "for k, v in a.conf.beat_schedule.items()}))"
    )
    out = subprocess.run(  # noqa: S603 - fixed argv, our own interpreter
        [sys.executable, "-c", code], env=env, cwd=REPO, capture_output=True, text=True,
        check=True, timeout=60,
    )
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {
        f"scheduler.tick:{P1}": ["scheduler.tick", 120.0],
        f"events.relay:{P1}": ["events.relay", 5.0],
    }
