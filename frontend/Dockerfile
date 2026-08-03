# syntax=docker/dockerfile:1.7

FROM node:24.18.0-bookworm-slim AS dependencies

ENV PNPM_HOME="/pnpm" \
    PATH="/pnpm:${PATH}" \
    NEXT_TELEMETRY_DISABLED=1

RUN corepack enable

WORKDIR /workspace

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY frontend/package.json ./frontend/package.json

RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --filter @lets-go-video-agent/web...


FROM dependencies AS builder

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

COPY frontend ./frontend

RUN pnpm --dir frontend build


FROM node:24.18.0-bookworm-slim AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

WORKDIR /app

# Next.js standalone 输出只携带运行所需依赖，显著缩小最终镜像。
COPY --from=builder --chown=node:node /workspace/frontend/.next/standalone ./
COPY --from=builder --chown=node:node /workspace/frontend/.next/static \
    ./frontend/.next/static

USER node

EXPOSE 3000

CMD ["node", "frontend/server.js"]
