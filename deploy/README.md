# MessifeBot — Sunucu Kurulum ve İşletim Rehberi

Bu rehber botu Oracle Cloud Always Free sunucuda 7/24 çalıştırmak içindir.
Tasarım: `docs/superpowers/specs/2026-09-27-7-24-hosting-design.md`.

## 1. Telegram token'ları
1. BotFather → `/revoke` → canlı bot → **yeni token**. Bu token sadece sunucudaki `/etc/messifebot.env`'e yazılır.
2. BotFather → `/newbot` → **test botu**. Yerel `telegram-bot/.env` dosyasında bunun token'ını kullanın.
   Aynı token'la iki bot aynı anda çalışırsa "Conflict" hatası alınır.
3. Canlı bota `/id` yazıp Telegram ID'nizi not edin (ADMIN_IDS için).

## 2. Oracle Cloud sunucusu
1. https://cloud.oracle.com → ücretsiz hesap (kart doğrulaması istenir, ücret alınmaz). Ev bölgesi olarak size yakın bir bölge seçin (ör. Frankfurt). Bölge sonradan değişmez.
2. Compute → Instances → Create instance:
   - Image: **Canonical Ubuntu 24.04**
   - Shape: **VM.Standard.A1.Flex** (1 OCPU, 6 GB). "Out of capacity" hatası verirse **VM.Standard.E2.1.Micro**.
   - SSH keys: kendi bilgisayarınızdaki açık anahtarı yükleyin (yoksa PowerShell: `ssh-keygen -t ed25519`).
3. Oluşunca Public IP'yi not edin. Bağlanın: `ssh ubuntu@IP`
4. Önerilen: hesabı "Pay As You Go"ya yükseltin. Always Free kaynaklar yine ücretsizdir; bu, boşta kalan ücretsiz VM'lerin geri alınmasını engeller.

## 3. GitHub
1. GitHub'da **private** repo oluşturun (ör. `messifebot`).
2. Yerelde (`telegram-bot/` klasöründe):
   `git remote add origin git@github.com:KULLANICI/messifebot.git` → `git push -u origin main`
3. GitHub Actions için deploy anahtarı üretin (yerelde):
   `ssh-keygen -t ed25519 -N "" -C "github-actions" -f messifebot_actions`
   (Oluşan iki dosyayı repoya EKLEMEYİN.)

## 4. Sunucu kurulumu
1. Kurulum betiğini ve Actions açık anahtarını sunucuya kopyalayın (yerelde):
   `scp deploy/setup_server.sh messifebot_actions.pub ubuntu@IP:~/`
2. Sunucuda: `sudo bash setup_server.sh git@github.com:KULLANICI/messifebot.git messifebot_actions.pub`
3. Betik bir anahtar gösterip bekler: GitHub → repo → Settings → Deploy keys → Add deploy key → yapıştırın (**Allow write access kapalı**) → Enter.

## 5. Ortam dosyası
`sudo nano /etc/messifebot.env` → `BOT_TOKEN`, `ADMIN_IDS`, `NEWSAPI_KEY`, `HEALTHCHECK_URL` doldurun.
Sonra: `sudo systemctl restart messifebot`. Telegram'a "✅ Bot başladı" gelmeli.

## 6. GitHub Secrets
Repo → Settings → Secrets and variables → Actions → New repository secret:
- `SERVER_HOST` = sunucu IP'si
- `SSH_PRIVATE_KEY` = `messifebot_actions` dosyasının tamamı
- `SSH_KNOWN_HOSTS` = yerelde `ssh-keyscan -t ed25519 IP` çıktısı.
  Doğrulama: sunucuda `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` ile yerelde `ssh-keyscan -t ed25519 IP | ssh-keygen -lf -` aynı parmak izini vermeli.

## 7. healthchecks.io
1. https://healthchecks.io → ücretsiz hesap → Add Check.
2. Period: **5 minutes**, Grace: **10 minutes**. Integrations → e-posta açık olsun.
3. Ping URL'sini `/etc/messifebot.env` içindeki `HEALTHCHECK_URL=`'e yazın → `sudo systemctl restart messifebot`.

## 8. Mevcut verileri taşıma (tek seferlik)
1. Bilgisayarınızda çalışan bot varsa durdurun (PowerShell):
   `Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -like '*bot.main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`
2. Yerel kopya alın: `Copy-Item data\chat_stats.db data\chat_stats.before-server.db`
3. Kopyalayın: `scp data/chat_stats.db ubuntu@IP:/tmp/chat_stats.db`
4. Sunucuda:
       sudo systemctl stop messifebot
       sqlite3 /tmp/chat_stats.db "PRAGMA integrity_check;"   # "ok" yazmalı
       sudo install -o messifebot -g messifebot -m 640 /tmp/chat_stats.db /var/lib/messifebot/chat_stats.db
       sudo systemctl start messifebot
Not: Windows'ta bot zorla kapatıldıysa ilk sunucu açılışında "önceki çalışma düzgün kapanmadı" uyarısı gelir; bu beklenen bir durumdur.

## 9. Kabul testleri
1. Küçük bir değişiklik commit + push → GitHub → Actions yeşil → Telegram'a yeni sürümle "✅ Bot başladı".
2. Açılışta hata veren bir commit (ör. `bot/main.py` başına `raise SystemExit(1)`) push → Actions kırmızı → "⚠️ Deploy başarısız" mesajı → düzeltme commit'i push.
3. `sudo systemctl kill -s KILL messifebot` → 10 sn içinde yeniden başlar, "düzgün kapanmadı" notu gelir.
4. `sudo systemctl stop messifebot` → 10+ dk bekle → healthchecks.io e-postası → `sudo systemctl start messifebot`.
5. `sudo -u messifebot bash /opt/messifebot/deploy/backup.sh --send` → Telegram'a yedek dosyası gelir.
6. `sudo reboot` → birkaç dakika sonra bot kendiliğinden çalışıyor ("düzgün kapanmadı" notu olmadan).

## 10. Günlük işlemler
- Durum: `systemctl status messifebot`
- Canlı log: `journalctl -u messifebot -f`
- Yeniden başlat: `sudo systemctl restart messifebot`
- Elle deploy: `sudo /usr/local/sbin/messifebot-deploy`
- Yedekler: `ls -lh /var/lib/messifebot/backups/`
- Geri yükleme:
      sudo systemctl stop messifebot
      gunzip -c /var/lib/messifebot/backups/chat_stats-YYYYMMDD-HHMM.db.gz | sudo -u messifebot tee /var/lib/messifebot/chat_stats.db >/dev/null
      sudo systemctl start messifebot
- `deploy/deploy.sh` veya systemd dosyaları değişirse: `sudo bash /opt/messifebot/deploy/setup_server.sh git@github.com:KULLANICI/messifebot.git`
