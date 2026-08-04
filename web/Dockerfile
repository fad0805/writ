FROM node:20-alpine AS builder

ARG API_HOST=http://api:8000
ENV API_HOST=${API_HOST}

ARG BASE_URL=http://localhost:3000
ENV BASE_URL=${BASE_URL}

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV API_HOST=http://api:8000

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/next.config.ts ./
COPY --from=builder /app/node_modules ./node_modules

RUN addgroup -S writ && adduser -S writ -G writ

USER writ

EXPOSE 3000

CMD ["npm", "start"]
