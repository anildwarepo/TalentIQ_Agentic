# TalentIQ FastAPI Backend — uvicorn on port 8000
FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg (libpq), native builds, and git (for VCS-installed deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
        git \
    && rm -rf /var/lib/apt/lists/*

# uv = fast dependency resolver
RUN pip install --no-cache-dir uv

# Copy dependency manifest first for layer caching
COPY pyproject.toml ./

# --prerelease=allow because agent-framework ships pre-1.0 betas
RUN uv pip install --system --no-cache --prerelease=allow -r pyproject.toml

# Copy application code
COPY talent_backend ./talent_backend

EXPOSE 8000

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8000

# python -m talent_backend launches uvicorn using BACKEND_HOST/BACKEND_PORT (config.py)
CMD ["python", "-m", "talent_backend"]
