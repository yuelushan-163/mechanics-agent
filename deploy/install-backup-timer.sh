#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 执行此脚本。" >&2
  exit 1
fi

cat >/etc/systemd/system/mechanics-mongodb-backup.service <<'EOF'
[Unit]
Description=Backup Mechanics Agent MongoDB
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/mechanics-agent
ExecStart=/opt/mechanics-agent/deploy/backup-mongodb.sh
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
EOF

cat >/etc/systemd/system/mechanics-mongodb-backup.timer <<'EOF'
[Unit]
Description=Daily Mechanics Agent MongoDB backup

[Timer]
OnCalendar=*-*-* 03:30:00 Asia/Shanghai
Persistent=true
RandomizedDelaySec=15m

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now mechanics-mongodb-backup.timer
systemctl list-timers mechanics-mongodb-backup.timer --no-pager

echo "MongoDB 每日备份计时器已启用。"
