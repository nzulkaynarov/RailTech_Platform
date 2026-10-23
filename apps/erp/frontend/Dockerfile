# ==============================================================================
# ERP Frontend — Multi-stage Dockerfile
# Stage 1 (builder): Builds React + Vite app
# Stage 2 (runtime): Serves with nginx
# ==============================================================================

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app

ENV NODE_OPTIONS=--max-old-space-size=2048

# Copy package files
COPY package.json package-lock.json ./

# Install all dependencies (including devDependencies for build)
RUN npm ci --legacy-peer-deps

# Copy source code
COPY . .

# Build arguments for environment variables
ARG VITE_API_URL=http://localhost:8000
# Origin only (no /ws path): the frontend appends /ws/notifications/ itself.
ARG VITE_WS_URL=ws://localhost:8000
# Sentry — empty by default so dev builds stay inert; prod sets it via the
# deploy workflow + compose build args. See Docs/ops/observability.md.
ARG VITE_SENTRY_DSN=
ARG VITE_SENTRY_ENVIRONMENT=production

ENV VITE_API_URL=${VITE_API_URL} \
    VITE_WS_URL=${VITE_WS_URL} \
    VITE_SENTRY_DSN=${VITE_SENTRY_DSN} \
    VITE_SENTRY_ENVIRONMENT=${VITE_SENTRY_ENVIRONMENT}

# Build the application
RUN npm run build


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
# Версия и digest закреплены (S0-9): сборка воспроизводима; обновление — осознанной правкой (stable-ветка nginx).
FROM nginx:1.30.6-alpine3.24@sha256:47928bf67eb62a1863cb08d9ecb52d3e704304ba614eaee17884204677702951

WORKDIR /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built application from builder
COPY --from=builder /app/dist .

# Set permissions for nginx user
RUN chown -R nginx:nginx /usr/share/nginx/html && \
    chmod -R 755 /usr/share/nginx/html && \
    chown -R nginx:nginx /etc/nginx/conf.d && \
    mkdir -p /var/cache/nginx && \
    chown -R nginx:nginx /var/cache/nginx && \
    touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid

# Switch to nginx user (non-root)
USER nginx

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O - http://127.0.0.1/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
