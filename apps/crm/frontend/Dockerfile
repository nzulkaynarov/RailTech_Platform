# syntax=docker/dockerfile:1.7
# dev — vite dev server (hot reload); prod — статика, раздаётся file-server'ом Caddy.

FROM node:22-slim AS base
ENV PNPM_HOME=/pnpm PATH="/pnpm:$PATH"
RUN corepack enable
WORKDIR /web
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile

FROM base AS dev
EXPOSE 5173
CMD ["pnpm", "dev"]

FROM base AS build
COPY . .
RUN pnpm build

FROM caddy:2.11.7-alpine AS prod
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
EXPOSE 8080
