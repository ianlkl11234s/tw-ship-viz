#!/bin/bash
set -e

# 匯出環境變數給 cron（cron 不繼承容器環境）
printenv | grep -v '^_=' > /etc/environment 2>/dev/null || true

# 每日 07:00（台灣時間）更新 S3 → SQLite → Arrow
cat > /etc/cron.d/ship-update << 'CRON'
0 7 * * * root . /etc/environment; cd /app && python3 scripts/import_to_db.py --incremental >> /var/log/cron.log 2>&1 && python3 scripts/cleanup_old_data.py --days 14 >> /var/log/cron.log 2>&1 && python3 scripts/generate_arrow.py --days 14 >> /var/log/cron.log 2>&1
CRON
chmod 0644 /etc/cron.d/ship-update
crontab /etc/cron.d/ship-update
touch /var/log/cron.log

echo "[scheduler] cron 已設定：每日 07:00 (Asia/Taipei) 更新資料"

# 前景執行 cron
exec cron -f
