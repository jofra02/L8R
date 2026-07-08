FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Deploy provenance: scripts/deploy/redeploy.sh bakes the deployed git SHA and
# asserts it against the running container after `up`
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.revision=$GIT_SHA

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
