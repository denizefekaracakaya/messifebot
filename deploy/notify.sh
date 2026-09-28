#!/usr/bin/env bash
# Admin'lere Telegram bildirimi gönderir.
# Kullanım: bash notify.sh "mesaj" [dosya]
# Token ve admin ID'leri MESSIFEBOT_ENV (varsayılan /etc/messifebot.env) dosyasından okunur.
# Token asla ekrana/loga yazılmaz. Token veya admin yoksa sessizce 0 ile çıkar.
set -uo pipefail

ENV_FILE=${MESSIFEBOT_ENV:-/etc/messifebot.env}
MESSAGE=${1:-}
DOCUMENT=${2:-}

read_var() {
  # KEY=değer satırını okur; tırnakları, boşlukları ve CR'yi temizler
  grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"' \r"
}

TOKEN=$(read_var BOT_TOKEN)
ADMINS=$(read_var ADMIN_IDS | tr ',' ' ')
ADMINS=$(echo $ADMINS)   # fazla boşlukları sadeleştir

[ -n "$TOKEN" ] && [ -n "$ADMINS" ] || exit 0

if [ "${NOTIFY_DRY_RUN:-0}" = "1" ]; then
  echo "DRY-RUN token=$TOKEN admins=$ADMINS"
  exit 0
fi

API="https://api.telegram.org/bot$TOKEN"
for chat_id in $ADMINS; do
  if [ -n "$DOCUMENT" ]; then
    printf 'url = "%s/sendDocument"\n' "$API" | curl -sS -m 120 -o /dev/null -K - \
      -F "chat_id=$chat_id" -F "disable_notification=true" \
      -F "caption=$MESSAGE" -F "document=@$DOCUMENT" \
      || echo "notify: $chat_id için dosya gönderilemedi" >&2
  else
    printf 'url = "%s/sendMessage"\n' "$API" | curl -sS -m 30 -o /dev/null -K - \
      --data-urlencode "chat_id=$chat_id" \
      --data-urlencode "text=$MESSAGE" \
      || echo "notify: $chat_id için mesaj gönderilemedi" >&2
  fi
done
exit 0
