# ─── Stage 1: build the Vite SPA ────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# VITE_API_BASE_URL is unused at build time — runtime nginx proxies /api/* and /af/*.
# Kept for build flexibility (e.g. an absolute URL when not using the proxy).
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# Build args passed by talent_infra_modules/03-frontend/deploy.ps1.
# Vite inlines VITE_* into the bundle at build time — they cannot be set at runtime.
ARG VITE_API_BASE=""
ENV VITE_API_BASE=$VITE_API_BASE

ARG VITE_AF_BACKEND_URL="/af"
ENV VITE_AF_BACKEND_URL=$VITE_AF_BACKEND_URL

ARG VITE_AGENT_NAME="talentiq-agent"
ENV VITE_AGENT_NAME=$VITE_AGENT_NAME

# Demo / partial-environment auth bypass — see talent_infra_modules/AUTH-DISABLED.md.
# When "true", main.jsx skips MsalProvider and App.jsx treats the user as authenticated.
# Default is "false" (production behavior, MSAL flows as normal).
ARG VITE_DISABLE_AUTH="false"
ENV VITE_DISABLE_AUTH=$VITE_DISABLE_AUTH

RUN npm run build

# ─── Stage 2: nginx serve + reverse proxy to backend ────────
FROM nginx:alpine

# envsubst lives in gettext — needed to template default.conf at runtime
RUN apk add --no-cache gettext

# nginx config template — BACKEND_URL / BACKEND_HOST / NAMESERVER substituted at startup
COPY nginx.conf /etc/nginx/templates/default.conf.template

# Built SPA assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Entrypoint resolves the in-cluster DNS server + renders the nginx template
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 80

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
