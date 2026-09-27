#!/usr/bin/env bash
# MessifeBot sunucu kurulumu (Ubuntu 24.04). Tekrar çalıştırılabilir.
# Kullanım: sudo bash setup_server.sh git@github.com:KULLANICI/REPO.git [deploy_actions_key.pub]
set -euo pipefail

REPO_URL=${1:?Kullanım: sudo bash setup_server.sh git@github.com:KULLANICI/REPO.git [actions_key.pub]}
DEPLOY_PUBKEY_FILE=${2:-}
APP_USER=messifebot
APP_DIR=/opt/messifebot
DATA_DIR=/var/lib/messifebot
ENV_FILE=/etc/messifebot.env
# GitHub'ın yayımladığı ed25519 host anahtarı parmak izi (docs.github.com: GitHub's SSH key fingerprints)
GITHUB_ED25519_FP='SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU'

[ "$(id -u)" = 0 ] || { echo "root olarak çalıştırın: sudo bash $0 ..."; exit 1; }
step() { echo; echo "==> $*"; }

step "Paketler"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip git sqlite3 curl

step "Saat dilimi: Europe/Istanbul"
timedatectl set-timezone Europe/Istanbul

step "Swap (RAM 2 GB'tan azsa)"
if [ "$(awk '/MemTotal/ {print $2}' /proc/meminfo)" -lt 2000000 ] && ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "2 GB swap açıldı"
else
  echo "gerekmiyor / zaten var"
fi

step "journald sınırı (200 MB)"
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=200M\n' > /etc/systemd/journald.conf.d/messifebot.conf
systemctl restart systemd-journald

step "Kullanıcılar ve dizinler"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA_DIR" --create-home --shell /usr/sbin/nologin "$APP_USER"
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$DATA_DIR" "$DATA_DIR/backups"
install -d -o "$APP_USER" -g "$APP_USER" -m 755 "$APP_DIR"
install -d -o deploy -g deploy -m 700 /home/deploy/.ssh
touch /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys && chmod 600 /home/deploy/.ssh/authorized_keys
if [ -n "$DEPLOY_PUBKEY_FILE" ]; then
  grep -qxF "$(cat "$DEPLOY_PUBKEY_FILE")" /home/deploy/.ssh/authorized_keys \
    || cat "$DEPLOY_PUBKEY_FILE" >> /home/deploy/.ssh/authorized_keys
  echo "GitHub Actions anahtarı deploy kullanıcısına eklendi"
fi

step "GitHub erişimi (salt-okunur deploy anahtarı)"
install -d -o "$APP_USER" -g "$APP_USER" -m 700 "$DATA_DIR/.ssh"
if [ ! -f "$DATA_DIR/.ssh/id_ed25519" ]; then
  sudo -u "$APP_USER" ssh-keygen -q -t ed25519 -N '' -C "messifebot-server" -f "$DATA_DIR/.ssh/id_ed25519"
fi
KEY=$(ssh-keyscan -t ed25519 github.com 2>/dev/null)
FP=$(echo "$KEY" | ssh-keygen -lf - | awk '{print $2}')
[ "$FP" = "$GITHUB_ED25519_FP" ] || { echo "GitHub host anahtarı doğrulanamadı ($FP). Durduruldu."; exit 1; }
echo "$KEY" > "$DATA_DIR/.ssh/known_hosts"
chown "$APP_USER:$APP_USER" "$DATA_DIR/.ssh/known_hosts"

step "Repo"
if [ ! -d "$APP_DIR/.git" ]; then
  echo "Aşağıdaki anahtarı GitHub > repo > Settings > Deploy keys'e ekleyin (Allow write access KAPALI):"
  echo
  cat "$DATA_DIR/.ssh/id_ed25519.pub"
  echo
  read -r -p "Ekledikten sonra Enter'a basın..." _
  sudo -u "$APP_USER" -H git clone --quiet "$REPO_URL" "$APP_DIR"
else
  echo "zaten klonlanmış"
fi

step "Python sanal ortamı"
[ -d "$APP_DIR/.venv" ] || sudo -u "$APP_USER" -H python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" -H "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" -H "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
sudo -u "$APP_USER" -H git -C "$APP_DIR" rev-parse --short HEAD | sudo -u "$APP_USER" tee "$DATA_DIR/version" >/dev/null

step "Ortam dosyası"
if [ ! -f "$ENV_FILE" ]; then
  install -o root -g "$APP_USER" -m 640 "$APP_DIR/deploy/messifebot.env.example" "$ENV_FILE"
  echo "$ENV_FILE oluşturuldu — doldurmanız gerekiyor"
else
  chown root:"$APP_USER" "$ENV_FILE" && chmod 640 "$ENV_FILE"
  echo "mevcut (dokunulmadı)"
fi

step "Deploy betiği ve sudo yetkisi"
install -o root -g root -m 755 "$APP_DIR/deploy/deploy.sh" /usr/local/sbin/messifebot-deploy
echo 'deploy ALL=(root) NOPASSWD: /usr/local/sbin/messifebot-deploy' > /etc/sudoers.d/messifebot-deploy
chmod 440 /etc/sudoers.d/messifebot-deploy
visudo -cf /etc/sudoers.d/messifebot-deploy >/dev/null

step "systemd birimleri"
install -m 644 "$APP_DIR/deploy/messifebot.service" /etc/systemd/system/messifebot.service
install -m 644 "$APP_DIR/deploy/messifebot-backup.service" /etc/systemd/system/messifebot-backup.service
install -m 644 "$APP_DIR/deploy/messifebot-backup.timer" /etc/systemd/system/messifebot-backup.timer
systemctl daemon-reload
systemctl enable --now messifebot-backup.timer
systemctl enable messifebot

if grep -qE '^BOT_TOKEN=.+' "$ENV_FILE"; then
  systemctl restart messifebot
  echo "Bot başlatıldı: systemctl status messifebot"
else
  echo
  echo "!! $ENV_FILE içinde BOT_TOKEN boş. Doldurun: sudo nano $ENV_FILE"
  echo "   Sonra: sudo systemctl start messifebot"
fi
echo
echo "Kurulum tamamlandı."
