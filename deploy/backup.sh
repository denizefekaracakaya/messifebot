#!/usr/bin/env bash
# SQLite veritabanının çevrimiçi yedeği: bütünlük kontrolü, gzip, 14 gün saklama.
# Pazar günleri veya --send ile en son yedek admin'e Telegram'dan gönderilir.
set -euo pipefail

DATA_DIR=${MESSIFEBOT_DATA:-/var/lib/messifebot}
DB="$DATA_DIR/chat_stats.db"
OUT="$DATA_DIR/backups"
KEEP_DAYS=14
HERE=$(cd "$(dirname "$0")" && pwd)
notify() { bash "$HERE/notify.sh" "$@" || true; }

SEND=0
[ "${1:-}" = "--send" ] && SEND=1
[ "$(date +%u)" = "7" ] && SEND=1

mkdir -p "$OUT"
STAMP=$(date +%Y%m%d-%H%M)
TMP="$OUT/.tmp-$STAMP.db"
FINAL="$OUT/chat_stats-$STAMP.db.gz"
trap 'rm -f "$TMP" "$FINAL.part"' EXIT
trap 'notify "❗ Yedek betiği beklenmedik bir hata verdi ($STAMP)"' ERR

if [ ! -f "$DB" ]; then
  notify "❗ Veritabanı dosyası bulunamadı"
  echo "Veritabanı dosyası yok: $DB" >&2
  exit 1
fi

if ! sqlite3 "$DB" ".backup '$TMP'" 2>/dev/null; then
  notify "❗ Veritabanı yedeği alınamadı ($STAMP). Sunucuyu kontrol edin."
  echo "Yedek alınamadı: $DB" >&2
  exit 1
fi

RESULT=$(sqlite3 "$TMP" "PRAGMA integrity_check;" 2>&1 || true)
if [ "$RESULT" != "ok" ]; then
  notify "❗ Veritabanı yedeği bozuk çıktı ($STAMP). Veritabanı kontrol edilmeli."
  echo "Bütünlük kontrolü başarısız: $RESULT" >&2
  exit 1
fi

gzip -c "$TMP" > "$FINAL.part"
mv "$FINAL.part" "$FINAL"
find "$OUT" -maxdepth 1 -name 'chat_stats-*.db.gz' -mtime +$((KEEP_DAYS - 1)) -delete
echo "Yedek alındı: $FINAL"

if [ "$SEND" = "1" ]; then
  notify "🗄 MessifeBot veritabanı yedeği ($STAMP)" "$FINAL"
fi
