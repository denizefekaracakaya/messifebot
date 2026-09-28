#!/usr/bin/env bash
# backup.sh ve notify.sh için test (Linux + sqlite3 gerektirir; CI'da çalışır)
set -euo pipefail
DEPLOY_DIR=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export MESSIFEBOT_DATA="$TMP" MESSIFEBOT_ENV="$TMP/empty.env"
: > "$MESSIFEBOT_ENV"

fail() { echo "FAIL: $*"; exit 1; }

sqlite3 "$TMP/chat_stats.db" "CREATE TABLE t(x); INSERT INTO t VALUES (42);"
mkdir -p "$TMP/backups"
touch -d '20 days ago' "$TMP/backups/chat_stats-20000101-0000.db.gz"
touch -d '3 days ago' "$TMP/backups/chat_stats-20000102-0000.db.gz"

bash "$DEPLOY_DIR/backup.sh" --send

[ ! -e "$TMP/backups/chat_stats-20000101-0000.db.gz" ] || fail "14 günden eski yedek silinmedi"
[ -e "$TMP/backups/chat_stats-20000102-0000.db.gz" ] || fail "yeni yedek yanlışlıkla silindi"
new=$(ls "$TMP"/backups/chat_stats-2*.db.gz | grep -v 2000010 || true)
[ "$(echo "$new" | grep -c . )" = 1 ] || fail "tam olarak 1 yeni yedek bekleniyordu: $new"
gunzip -c "$new" > "$TMP/restored.db"
[ "$(sqlite3 "$TMP/restored.db" 'SELECT x FROM t')" = 42 ] || fail "yedekten geri yüklenen veri yanlış"
! ls -A "$TMP/backups" | grep -q '^\.tmp' || fail "geçici dosya kaldı"
! ls -A "$TMP/backups" | grep -q '\.part$' || fail ".part dosyası kaldı"

# Bozuk veritabanı: yedek alınmamalı, çıkış kodu 1 olmalı
printf 'bu bir sqlite dosyası değil' > "$TMP/chat_stats.db"
if bash "$DEPLOY_DIR/backup.sh"; then fail "bozuk veritabanında backup.sh başarılı döndü"; fi

# Veritabanı dosyası yok: yedek alınmamalı, çıkış kodu 1 olmalı, yeni dosya oluşmamalı
rm -f "$TMP/chat_stats.db"
before=$(ls "$TMP/backups" | wc -l)
if bash "$DEPLOY_DIR/backup.sh"; then fail "eksik veritabanında backup.sh başarılı döndü"; fi
after=$(ls "$TMP/backups" | wc -l)
[ "$before" = "$after" ] || fail "eksik veritabanında yeni yedek dosyası oluştu"

# notify.sh: boş env ile sessizce 0 döner; tırnaklı/boşluklu değerleri okuyabilir
bash "$DEPLOY_DIR/notify.sh" "test" || fail "notify.sh boş env ile hata verdi"
printf 'BOT_TOKEN=" 123:ABC "\nADMIN_IDS=1, 2\n' > "$TMP/quoted.env"
out=$(MESSIFEBOT_ENV="$TMP/quoted.env" NOTIFY_DRY_RUN=1 bash "$DEPLOY_DIR/notify.sh" "merhaba")
[ "$out" = "DRY-RUN token=123:ABC admins=1 2" ] || fail "notify.sh env ayrıştırma: '$out'"

echo "backup/notify tests OK"
