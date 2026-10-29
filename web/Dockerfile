FROM node:22-alpine AS builder

ARG API_HOST=http://api:8000
ENV API_HOST=${API_HOST}
ENV NEXT_TELEMETRY_DISABLED=1

ARG BASE_URL=http://localhost:3000
ENV BASE_URL=${BASE_URL}

WORKDIR /app

# package-lock.json을 존중하는 npm ci로 결정적 빌드를 보장한다.
# npm 캐시는 같은 레이어에서 지워 빌드 디스크 사용량을 줄인다.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund --cache /tmp/npm-cache && rm -rf /tmp/npm-cache

COPY . .
# 빌드 후 devDeps를 제거해 런타임 의존성만 남긴다.
# (별도 deps-prod 스테이지에서 npm ci를 한 번 더 실행하지 않아 피크 디스크 사용량이 절반으로 줄어든다.)
RUN npm run build && npm prune --omit=dev

FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV API_HOST=http://api:8000

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY start.sh ./start.sh
RUN chmod +x start.sh

RUN addgroup -S writ && adduser -S writ -G writ

USER writ

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/ && wget -q -O /dev/null ${API_HOST}/api/server-info || exit 1

CMD ["npm", "start"]
