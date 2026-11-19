# Stage 1: the Mapa SPA (ingest/web, Vite) → /public/mapa
FROM node:24-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# Stage 2: the ingest API + console
FROM node:24-alpine

WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund

COPY src ./src
COPY public ./public
COPY --from=web /public/mapa ./public/mapa

EXPOSE 8080
CMD ["node", "--experimental-strip-types", "src/server.ts"]
