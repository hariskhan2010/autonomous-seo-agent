"""Read-only API load test (Phase 13) — no extra dependencies, just httpx + asyncio.

Hammers the list/read endpoints with N concurrent workers for D seconds and reports throughput,
latency percentiles and error rate per endpoint. GET only, by design: it never creates, approves
or executes anything, so it is safe to point at any environment you're allowed to load.

    make loadtest ARGS="--base-url http://localhost:8000 --concurrency 20 --duration 60"

Identity: `--token` (a real bearer JWT) or, against an `ENV=dev` API, the `X-Dev-*` headers with a
random tenant (RLS then scopes every query to that empty tenant — the queries still run for real).
Pass `--project-id` to exercise the per-project filters. Exit code is non-zero if the error rate
exceeds `--max-error-rate` or p95 exceeds `--max-p95-ms`, so it can gate a deploy.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

import httpx

READ_ENDPOINTS = (
    "/v1/health",
    "/v1/projects",
    "/v1/opportunities",
    "/v1/issues",
    "/v1/changes",
    "/v1/crawls",
    "/v1/keywords",
    "/v1/anomalies",
    "/v1/experiments",
    "/v1/geo/visibility",
)


@dataclass
class Stats:
    latencies_ms: list[float] = field(default_factory=list)
    errors: int = 0
    statuses: dict[int, int] = field(default_factory=lambda: defaultdict(int))


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = min(len(sorted_vals) - 1, max(0, round(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[k]


async def _worker(
    client: httpx.AsyncClient, endpoints: list[str], deadline: float, params: dict[str, str],
    stats: dict[str, Stats],
) -> None:
    while time.monotonic() < deadline:
        ep = random.choice(endpoints)  # noqa: S311 - load spreading, not crypto
        started = time.perf_counter()
        try:
            resp = await client.get(ep, params=params if ep != "/v1/health" else None)
            ms = (time.perf_counter() - started) * 1000
            s = stats[ep]
            s.statuses[resp.status_code] += 1
            if resp.status_code >= 500 or resp.status_code in (401, 403):
                s.errors += 1
            else:
                s.latencies_ms.append(ms)
        except httpx.HTTPError:
            stats[ep].errors += 1


async def run(args: argparse.Namespace) -> int:
    if args.token:
        headers = {"Authorization": f"Bearer {args.token}"}
    else:
        headers = {
            "X-Dev-Tenant": args.tenant_id or str(uuid.uuid4()),
            "X-Dev-User": str(uuid.uuid4()),
            "X-Dev-Role": "viewer",
        }
    params = {"project_id": args.project_id} if args.project_id else {}
    stats: dict[str, Stats] = defaultdict(Stats)
    limits = httpx.Limits(
        max_connections=args.concurrency, max_keepalive_connections=args.concurrency,
    )
    async with httpx.AsyncClient(
        base_url=args.base_url, headers=headers, timeout=args.timeout, limits=limits,
    ) as client:
        # Fail fast on a wrong URL/identity instead of reporting 100% errors after a full run.
        probe = await client.get("/v1/projects")
        if probe.status_code != 200:
            print(f"probe GET /v1/projects -> {probe.status_code}: {probe.text[:200]}",
                  file=sys.stderr)
            return 2
        deadline = time.monotonic() + args.duration
        started = time.monotonic()
        await asyncio.gather(*(
            _worker(client, list(READ_ENDPOINTS), deadline, params, stats)
            for _ in range(args.concurrency)
        ))
        elapsed = time.monotonic() - started

    all_lat = sorted(v for s in stats.values() for v in s.latencies_ms)
    total_ok = len(all_lat)
    total_err = sum(s.errors for s in stats.values())
    total = total_ok + total_err
    err_rate = total_err / total if total else 1.0
    p95 = _pct(all_lat, 95)

    print(f"\n{args.base_url}  concurrency={args.concurrency}  duration={elapsed:.1f}s")
    print(f"{'endpoint':<22}{'reqs':>7}{'err':>6}{'p50':>9}{'p95':>9}{'p99':>9}  statuses")
    for ep in READ_ENDPOINTS:
        s = stats.get(ep)
        if s is None:
            continue
        lat = sorted(s.latencies_ms)
        n = len(lat) + s.errors
        print(f"{ep:<22}{n:>7}{s.errors:>6}{_pct(lat, 50):>8.0f}m{_pct(lat, 95):>8.0f}m"
              f"{_pct(lat, 99):>8.0f}m  {dict(s.statuses)}")
    print(f"{'TOTAL':<22}{total:>7}{total_err:>6}{_pct(all_lat, 50):>8.0f}m{p95:>8.0f}m"
          f"{_pct(all_lat, 99):>8.0f}m")
    mean = statistics.fmean(all_lat) if all_lat else 0.0
    print(f"throughput {total / elapsed:.1f} req/s   mean {mean:.0f} ms   "
          f"error rate {err_rate:.2%}")

    failed = []
    if err_rate > args.max_error_rate:
        failed.append(f"error rate {err_rate:.2%} > {args.max_error_rate:.2%}")
    if args.max_p95_ms and p95 > args.max_p95_ms:
        failed.append(f"p95 {p95:.0f} ms > {args.max_p95_ms:.0f} ms")
    if failed:
        print("FAIL: " + "; ".join(failed))
        return 1
    print("PASS")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--duration", type=float, default=30.0, help="seconds")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--token", help="bearer JWT; omit for X-Dev-* headers (ENV=dev only)")
    ap.add_argument("--tenant-id", help="X-Dev-Tenant to use (default: a random, empty tenant)")
    ap.add_argument("--project-id")
    ap.add_argument("--max-error-rate", type=float, default=0.01)
    ap.add_argument("--max-p95-ms", type=float, default=0.0, help="0 = don't gate on latency")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
