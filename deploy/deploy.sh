#!/usr/bin/env bash
# MessifeBot deploy: origin/main'i çeker, gerekirse bağımlılıkları kurar, servisi yeniden
# başlatır ve 20 sn sağlık kontrolü yapar. Başarısızsa önceki sürüme geri döner (çıkış 1).
# Root olarak /usr/local/sbin/messifebot-deploy kopyası çalıştırılır (setup_server.sh kurar).
set -euo pipefail

APP_USER=messifebot
APP_DIR=/opt/messifebot
DATA_DIR=/var/lib/messifebot
SERVICE=messifebot
HEALTH_WAIT=20

[ "$(id -u)" = 0 ] || { echo "root olarak çalıştırın"; exit 1; }
exec 9>/run/messifebot-deploy.lock
flock -n 9 || { echo "Başka bir deploy çalışıyor"; exit 1; }

as_app() { sudo -u "$APP_USER" -H "$@"; }
notify() { as_app bash "$APP_DIR/deploy/notify.sh" "$1" || true; }
short() { as_app git -C "$APP_DIR" rev-parse --short "$1"; }

switch_to() {  # $1 = hedef commit, $2 = şu anki commit
  as_app git -C "$APP_DIR" reset --quiet --hard "$1" || return 1
  if [ "$1" != "$2" ] && ! as_app git -C "$APP_DIR" diff --quiet "$2" "$1" -- requirements.txt; then
    echo "==> requirements.txt değişti, bağımlılıklar kuruluyor"
    as_app "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt" || return 1
  fi
  short "$1" | as_app tee "$DATA_DIR/version" >/dev/null || return 1
}

healthy() {
  systemctl reset-failed "$SERVICE" 2>/dev/null || true
  systemctl restart "$SERVICE"
  sleep 3
  local pid_first pid_last
  pid_first=$(systemctl show -p MainPID --value "$SERVICE")
  sleep $((HEALTH_WAIT - 3))
  pid_last=$(systemctl show -p MainPID --value "$SERVICE")
  systemctl is-active --quiet "$SERVICE" && [ "$pid_first" != "0" ] && [ "$pid_first" = "$pid_last" ]
}

cd "$APP_DIR"
PREV=$(as_app git -C "$APP_DIR" rev-parse HEAD)
as_app git -C "$APP_DIR" fetch --quiet origin main
NEW=$(as_app git -C "$APP_DIR" rev-parse origin/main)
echo "==> $(short "$PREV") -> $(short "$NEW")"

if switch_to "$NEW" "$PREV" && healthy; then
  echo "✅ Deploy tamam: $(short "$NEW") çalışıyor"
  exit 0
fi

echo "❌ $(short "$NEW") sağlıklı başlamadı. Son loglar:"
journalctl -u "$SERVICE" -n 40 --no-pager || true

if [ "$NEW" = "$PREV" ]; then
  notify "🚨 Deploy başarısız: $(short "$NEW") sağlıklı başlamadı ve geri dönülecek başka sürüm yok. Sunucuyu kontrol edin."
  exit 1
fi

echo "==> $(short "$PREV") sürümüne geri dönülüyor"
if switch_to "$PREV" "$NEW" && healthy; then
  notify "⚠️ Deploy başarısız: $(short "$NEW") sağlıklı başlamadı. Önceki sürüm $(short "$PREV") ile devam ediliyor."
else
  notify "🚨 Deploy başarısız ve önceki sürüm $(short "$PREV") de başlamadı! Sunucuyu kontrol edin."
fi
exit 1
