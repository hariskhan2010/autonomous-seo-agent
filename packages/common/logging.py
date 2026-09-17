"""Structured JSON logging with secret redaction and correlation-id binding
(A-TO-Z-PLAN.md §O — observability from Phase 1). Keeps the per-run JSON contract from
seo-agent/utils/logger.py."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.typing import EventDict, WrappedLogger

from common.redaction import redact
from common.settings import settings


def _redact_event(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    secrets = settings.secret_values()
    for key, val in list(event_dict.items()):
        if isinstance(val, str):
            event_dict[key] = redact(val, secrets)
    return event_dict


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_event,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "app") -> Any:
    return structlog.get_logger(name)
