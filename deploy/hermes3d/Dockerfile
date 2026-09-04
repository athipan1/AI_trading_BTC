ARG HERMES3D_REF=beb76292747b816ef317aa6f9a3992e0014f81d9

FROM node:22-slim AS source
ARG HERMES3D_REF
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --filter=blob:none https://github.com/iamlukethedev/Hermes3D.git /app \
    && cd /app \
    && git checkout "${HERMES3D_REF}" \
    && rm -rf /app/.git
WORKDIR /app
COPY deploy/hermes3d/overlay/ /app/

FROM node:22-slim AS deps
WORKDIR /app
COPY --from=source /app/package.json /app/package-lock.json ./
RUN npm ci --ignore-scripts --omit=dev

FROM node:22-slim AS builder
WORKDIR /app
COPY --from=source /app/package.json /app/package-lock.json ./
RUN npm ci --ignore-scripts
COPY --from=source /app ./
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_PUBLIC_GATEWAY_URL=http://127.0.0.1:8000
RUN npm run build

FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/server ./server
COPY --from=deps /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.ts ./next.config.ts
EXPOSE 3000
CMD ["node", "server/index.js"]
