# ── Build stage ────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json ./
RUN npm install --legacy-peer-deps

COPY . .
RUN npm run build

# ── Runtime stage (nginx) ───────────────────────────────────────
FROM nginx:1.27-alpine

# wget for Docker healthcheck; envsubst is already in nginx:alpine
RUN apk add --no-cache wget

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy the config TEMPLATE (not the final conf — key is substituted at runtime)
RUN mkdir -p /etc/nginx/templates
COPY nginx.conf.template /etc/nginx/templates/dashboard.conf.template

# Copy static build
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy entrypoint that runs envsubst then starts nginx
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 3000

# INTERNAL_KEY is injected at runtime via env_file / environment in docker-compose
# It is NEVER baked into the image.
ENTRYPOINT ["/docker-entrypoint.sh"]
