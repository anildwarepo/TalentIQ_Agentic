#!/bin/sh
set -e

# ── Discover the in-cluster DNS resolver ──────────────────────
# Required so nginx can re-resolve $backend_url at request time
# (Container Apps pods get new IPs on every restart).
NAMESERVER=$(grep -m1 '^nameserver' /etc/resolv.conf | awk '{print $2}')
export NAMESERVER=${NAMESERVER:-168.63.129.16}

# ── Derive the Host header value from BACKEND_URL ────────────
# nginx wants only the hostname (no scheme, no port, no path).
# BACKEND_URL is injected by the Container App env (see main.bicep).
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
BACKEND_HOST=$(echo "$BACKEND_URL" | sed -E 's|^[a-z]+://||; s|[:/].*$||')
export BACKEND_URL
export BACKEND_HOST

# ── Render the nginx config template ─────────────────────────
envsubst '${BACKEND_URL} ${BACKEND_HOST} ${NAMESERVER}' \
    < /etc/nginx/templates/default.conf.template \
    > /etc/nginx/conf.d/default.conf

echo "nginx resolver: $NAMESERVER"
echo "backend URL:    $BACKEND_URL"
echo "backend Host:   $BACKEND_HOST"

exec "$@"
