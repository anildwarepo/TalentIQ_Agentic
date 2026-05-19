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
