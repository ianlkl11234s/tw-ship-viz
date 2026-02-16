#!/bin/bash
set -e

echo "[ship-gis] 啟動中..."

# === 環境變數匯出給 cron ===
printenv | grep -v '^_=' > /etc/environment 2>/dev/null || true

# === 每日 07:00（台灣時間）更新資料 ===
cat > /etc/cron.d/ship-update << 'CRON'
0 7 * * * root . /etc/environment; cd /app && python3 scripts/import_to_db.py --incremental >> /var/log/cron.log 2>&1 && python3 scripts/cleanup_old_data.py --days 14 >> /var/log/cron.log 2>&1 && python3 scripts/generate_arrow.py --days 14 >> /var/log/cron.log 2>&1
CRON
chmod 0644 /etc/cron.d/ship-update
crontab /etc/cron.d/ship-update
touch /var/log/cron.log
cron
echo "[ship-gis] cron 排程已啟動（每日 07:00 更新）"

# === 首次啟動：若無 Arrow 資料則立即產出 ===
if [ ! -f frontend/public/data/trajectory.arrow ]; then
  echo "[ship-gis] 未偵測到 Arrow 資料，嘗試產出..."
  if [ -f data/ship_data.db ]; then
    python3 scripts/generate_arrow.py --days 14 2>&1 || echo "[ship-gis] Arrow 產出失敗（可能資料庫為空）"
  else
    echo "[ship-gis] 資料庫不存在，跳過 Arrow 產出"
  fi
fi

# === 啟動 API（Zeabur 透過 PORT 環境變數指定 port）===
echo "[ship-gis] 啟動 API server on port ${PORT:-8000}"
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
