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
