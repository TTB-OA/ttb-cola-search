"""Azure Monitor / OpenTelemetry wiring.

Telemetry is strictly optional: with no connection string configured this module
is a no-op, which is how local development and the test suite run. Nothing here
may raise into application startup.
"""
from __future__ import annotations

import logging
import os

from .config import Settings

logger = logging.getLogger(__name__)

SERVICE_NAME = "ttb-cola-search-api"

# Excluded from request tracing: the readiness probe fires every 30s forever, and
# the blob proxy is hit once per rendered thumbnail. Both are pure ingestion cost.
EXCLUDED_URLS = ",".join(
    [
        r"api/health",
        r"api/colas/[^/]+/images/.*",
    ]
)

_configured = False


def configure_telemetry(settings: Settings) -> bool:
    """Initialise Azure Monitor export. Returns True when telemetry is active."""
    global _configured

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # The Azure SDKs log every token request and HTTP round trip at INFO, which
    # is both noise and per-GB ingestion cost.
    for noisy in ("azure.core.pipeline.policies.http_logging_policy", "azure.identity"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if _configured:
        return True
    if not settings.telemetry_enabled or not settings.applicationinsights_connection_string:
        logger.info("Telemetry disabled (no Application Insights connection string).")
        return False

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        os.environ.setdefault("OTEL_PYTHON_EXCLUDED_URLS", EXCLUDED_URLS)
        os.environ.setdefault("OTEL_PYTHON_FASTAPI_EXCLUDED_URLS", EXCLUDED_URLS)

        configure_azure_monitor(
            connection_string=settings.applicationinsights_connection_string,
            resource_attributes={"service.name": SERVICE_NAME},
            sampling_ratio=settings.telemetry_sampling_ratio,
            logger_name=None,
            instrumentation_options={
                "django": {"enabled": False},
                "flask": {"enabled": False},
            },
        )
    except Exception:
        logger.exception("Telemetry initialisation failed; continuing without it.")
        return False

    _configured = True
    logger.info("Telemetry enabled (sampling_ratio=%s).", settings.telemetry_sampling_ratio)
    return True
