"""Logical model roles (A-TO-Z-PLAN.md §H.1, ADR-0005). Code references these, never model
names."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    STRATEGY = "STRATEGY"   # orchestration, planning, major content decisions
    WORKER = "WORKER"       # analysis, drafting, most agent tasks
    FAST = "FAST"           # classification, extraction, aggregation
    JUDGE = "JUDGE"         # rubric scoring, fact-check — must differ from WORKER's family
    EMBEDDING = "EMBEDDING" # vector generation
