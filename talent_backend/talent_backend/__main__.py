"""Entry point: ``python -m talent_backend``

Starts the FastAPI backend with uvicorn.
"""

from __future__ import annotations

import logging
import sys

import uvicorn

from talent_backend.config import BACKEND_HOST, BACKEND_PORT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)

# Silence noisy Azure SDK / HTTP loggers — they dump full request+response
# headers at INFO which floods the console on every Cosmos / AOAI call.
for _noisy in (
    "azure",
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.cosmos",
    "azure.cosmos._cosmos_http_logging_policy",
    "azure.identity",
    "azure.identity._credentials",
    "azure.identity.aio",
    "azure.identity.aio._credentials",
    "azure.identity.aio._internal",
    "httpx",
    "httpcore",
    "openai",
    "mcp.client.streamable_http",
):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger("talent_backend")


def main() -> None:
    logger.info("Starting TalentIQ backend on %s:%d", BACKEND_HOST, BACKEND_PORT)
    uvicorn.run(
        "talent_backend.api:app",
        host=BACKEND_HOST,
        port=BACKEND_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
