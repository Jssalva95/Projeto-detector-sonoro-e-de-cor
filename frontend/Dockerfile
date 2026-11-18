FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL
ARG VITE_WS_URL
RUN npm run build
CMD ["sh", "-c", "exec npm run dev -- --host 0.0.0.0 --port \"$FRONTEND_PORT\" --strictPort"]
