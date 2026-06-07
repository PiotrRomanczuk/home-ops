FROM node:24-alpine

WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund

COPY src ./src
COPY public ./public

EXPOSE 8080
CMD ["node", "--experimental-strip-types", "src/server.ts"]
