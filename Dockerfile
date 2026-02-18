# Zeabur / 單容器部署：前端 + API + 每日排程
# =============================================

# === Stage 1: Build frontend ===
FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# === Stage 2: Production ===
FROM python:3.12-slim

ENV TZ=Asia/Taipei
ENV ARROW_OUTPUT_DIR=/app/data/arrow
RUN apt-get update && apt-get install -y --no-install-recommends cron tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依賴
COPY scripts/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 應用程式碼
COPY api/ ./api/
COPY scripts/ ./scripts/
COPY --from=frontend-build /app/dist ./frontend/dist/

# 資料目錄
RUN mkdir -p data frontend/public/data

# 地理參考檔案放到 /app/geodata（不被 volume 覆蓋）
# 啟動時由 start.sh 複製到 /app/data/
COPY data/ports.geojson data/taiwan_land.json ./geodata/

# 啟動腳本
COPY docker/unified-start.sh ./start.sh
RUN chmod +x start.sh

EXPOSE 8000
CMD ["./start.sh"]
