FROM node:20-slim AS builder

WORKDIR /app

ARG NEXT_PUBLIC_REPLAYD_API_URL=http://localhost:8788
ARG NEXT_PUBLIC_OIDC_ENABLED=false
ENV NEXT_PUBLIC_REPLAYD_API_URL=$NEXT_PUBLIC_REPLAYD_API_URL
ENV NEXT_PUBLIC_OIDC_ENABLED=$NEXT_PUBLIC_OIDC_ENABLED

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM node:20-slim AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

RUN groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
