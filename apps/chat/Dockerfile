FROM node:22-slim
# The customer chat app (CP-0049) for scripts/docker_stack.py. Build context: apps/chat. Settings come from the environment at run time.
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build
ENV NODE_ENV=production PORT=3100
EXPOSE 3100
CMD ["npm", "start"]
