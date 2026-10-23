# Cabinet — статика SPA: сборка Vite + nginx (образец — apps/erp/frontend/Dockerfile).
# Собственной логики в контейнере нет (ADR-0004): /api/portal/* на ERP ведёт Caddy с того же домена.

# ── Сборка ──────────────────────────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Только VITE_*-переменные без секретов (docs/systems/cabinet/CONVENTIONS.md §2.8). VITE_API_URL пустой — запросы same-origin.
# VITE_CRM_URL — CRM для формы «Я новый клиент» (M2-CAB-03); пусто — вместо формы «Написать в Telegram».
ARG VITE_API_URL=
ARG VITE_BOT_USERNAME=
ARG VITE_CRM_URL=
ENV VITE_API_URL=${VITE_API_URL} \
    VITE_BOT_USERNAME=${VITE_BOT_USERNAME} \
    VITE_CRM_URL=${VITE_CRM_URL}

# Мок портального API в прод-сборку не попадает (ветка import.meta.env.DEV); воркер MSW не нужен.
RUN npm run build && rm -f dist/mockServiceWorker.js

# ── Отдача ──────────────────────────────────────────────────────────────────────────────────
FROM nginx:stable-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

RUN chown -R nginx:nginx /usr/share/nginx/html /etc/nginx/conf.d && \
    mkdir -p /var/cache/nginx && chown -R nginx:nginx /var/cache/nginx && \
    touch /var/run/nginx.pid && chown nginx:nginx /var/run/nginx.pid

USER nginx

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O - http://127.0.0.1/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
