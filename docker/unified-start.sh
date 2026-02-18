#!/bin/bash
# 不使用 set -e：避免非關鍵錯誤導致容器崩潰

echo "[ship-gis] 啟動中..."

# Arrow 輸出目錄（永久儲存區）
ARROW_DIR="${ARROW_OUTPUT_DIR:-frontend/public/data}"
mkdir -p "$ARROW_DIR"

# === 地理參考檔案：從 image 複製到 data volume ===
for f in ports.geojson taiwan_land.json; do
  if [ -f "geodata/$f" ] && [ ! -f "data/$f" ]; then
    cp "geodata/$f" "data/$f"
    echo "[ship-gis] 複製 $f → data/"
  fi
done

# === 環境變數匯出給 cron ===
printenv | grep -v '^_=' > /etc/environment 2>/dev/null || true

# === 每日 07:00（台灣時間）更新資料 ===
if command -v cron &> /dev/null; then
  cat > /etc/cron.d/ship-update << 'CRON'
0 7 * * * root . /etc/environment; cd /app && python3 scripts/import_to_db.py --incremental >> /var/log/cron.log 2>&1 && python3 scripts/cleanup_old_data.py --days 14 >> /var/log/cron.log 2>&1 && python3 scripts/generate_arrow.py --days 14 >> /var/log/cron.log 2>&1
CRON
  chmod 0644 /etc/cron.d/ship-update
  crontab /etc/cron.d/ship-update
  touch /var/log/cron.log
  cron
  echo "[ship-gis] cron 排程已啟動（每日 07:00 更新）"
else
  echo "[ship-gis] cron 不可用，跳過排程設定"
fi

# === 首次啟動：若無 Arrow 資料則背景產出（不阻塞 API）===
if [ ! -f "$ARROW_DIR/trajectory.arrow" ] && [ -f data/ship_data.db ]; then
  echo "[ship-gis] 未偵測到 Arrow 資料，背景產出中..."
  (PYTHONUNBUFFERED=1 python3 scripts/generate_arrow.py --days 14 >> /var/log/arrow-gen.log 2>&1 && \
   echo "[ship-gis] $(date): Arrow 產出完成" >> /var/log/arrow-gen.log || \
   echo "[ship-gis] $(date): Arrow 產出失敗" >> /var/log/arrow-gen.log) &
  echo "[ship-gis] Arrow 產出已在背景啟動 (PID: $!)"
elif [ ! -f data/ship_data.db ]; then
  echo "[ship-gis] 資料庫不存在，跳過 Arrow 產出（請先執行 import_to_db.py）"
else
  echo "[ship-gis] Arrow 資料已存在（${ARROW_DIR}）"
fi

# === 啟動 API（前景，確保容器存活）===
echo "[ship-gis] 啟動 API server on port ${PORT:-8000}"
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
