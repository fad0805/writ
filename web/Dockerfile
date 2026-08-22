FROM node:22-alpine AS builder

ARG API_HOST=http://api:8000
ENV API_HOST=${API_HOST}

ARG BASE_URL=http://localhost:3000
ENV BASE_URL=${BASE_URL}

WORKDIR /app

# package-lock.json을 존중하는 npm ci로 결정적 빌드를 보장한다.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# runner에는 런타임 의존성만 담는다(빌드 도구체인/devDeps 제외).
FROM node:22-alpine AS deps-prod
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV API_HOST=http://api:8000

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts ./
COPY --from=deps-prod /app/node_modules ./node_modules
COPY --from=deps-prod /app/package.json ./package.json
COPY start.sh ./start.sh
RUN chmod +x start.sh

RUN addgroup -S writ && adduser -S writ -G writ

USER writ

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/ && wget -q -O /dev/null ${API_HOST}/api/server-info || exit 1

CMD ["npm", "start"]
