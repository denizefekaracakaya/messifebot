# MessifeBot — 7/24 Barındırma Tasarımı

- **Tarih:** 2026-09-27
- **Durum:** Onay bekliyor (kullanıcı incelemesi)
- **Kapsam:** `telegram-bot/` uygulamasının ücretsiz bir bulut sunucuda sürekli çalışması; otomatik deploy, izleme, bildirim, yedekleme ve veri taşıma.

## 1. Amaç ve başarı ölçütleri

**Kullanıcının istedikleri**
- Bot, kullanıcının bilgisayarından bağımsız bir bulut sunucuda 7/24 çalışsın.
- Ücretsiz olsun.
- GitHub'a push edildiğinde otomatik olarak sunucuya kurulsun.
- Bot başlayınca, deploy olunca ve beklenmedik hata alınca admin'e Telegram bildirimi gelsin.
- Bot tamamen durursa dışarıdan fark edilsin ve e-posta ile uyarı gelsin.
- Veritabanı otomatik yedeklensin.
- Mevcut veriler (`data/chat_stats.db`: portföy, alarmlar, istatistikler) sunucuya taşınsın.

**Varsayımlar**
- Tek admin'li, küçük ölçekli bir bot. Deploy sırasında birkaç saniyelik kesinti kabul edilebilir.
- Veritabanı SQLite olarak kalır.

**Başarı ölçütleri**
1. Kullanıcının bilgisayarı kapalıyken bot mesajlara yanıt verir.
2. Bot süreci çökerse 10 sn içinde kendiliğinden yeniden başlar; sunucu yeniden başlarsa bot da açılışta başlar.
3. `main` dalına push → testler → deploy zinciri insan müdahalesi olmadan tamamlanır. Başarısız deploy önceki sürüme otomatik geri döner.
4. Bot 10 dakikadan uzun süre çalışmazsa admin e-posta alır.
5. Son 14 günün yedekleri sunucuda durur. En az haftada bir yedek sunucu dışına (admin'in Telegram'ına) çıkar.

## 2. Mevcut durum (tasarımı etkileyen bulgular)

- Proje henüz bir git deposu değil.
- Bot token'ı ve API anahtarları koda gömülü:
  - `bot/config.py`'de varsayılan değer olarak,
  - `.env.example` içinde,
  - kökteki eski `../messifebot.py` içinde.
  - Bu yüzden mevcut token sızmış kabul edilir.
- `ADMIN_IDS` boş; admin'e bildirim gönderilemez.
- Uygulama zaten `BOT_DATABASE_PATH` ortam değişkenini destekliyor. Veritabanı konumu değiştirilebilir.
- Yerel Windows çalıştırmasında bot sessizce durdu (PC uykusu/kapanması) ve log'da Windows'a özgü "Logging error" kayıtları görüldü.
- Mevcut test paketi 78 test içeriyor: 74 offline, 4 canlı test varsayılan olarak atlanıyor. Yerel sanal ortam Python 3.12.

## 3. Seçilen yaklaşım

Oracle Cloud **Always Free** sanal makinesi üzerinde Ubuntu 24.04 + Python venv + **systemd** servisi. Deploy için **GitHub Actions** SSH ile bağlanır.

**Değerlendirilip reddedilenler**
- **Google Cloud e2-micro:** 1 GB RAM ve sadece ABD bölgesi. Oracle kapasite sorunu çıkarırsa yedek plan olarak kalır.
- **Render / Koyeb / Railway ücretsiz katmanları:** ya uykuya geçiyorlar ya da kalıcı disk vermiyorlar. SQLite verisi kaybolur.
- **Docker:** bu ölçek için gereksiz RAM ve karmaşıklık; venv + systemd yeterli.

## 4. Tasarım

### 4.1 Güvenlik ön koşulu (koddaki değişiklikler)

- **`bot/config.py`**
  - Gömülü token varsayılanı kaldırılır.
  - `BOT_TOKEN` tanımlı değilse uygulama açık bir hata mesajıyla başlamayı reddeder.
- **`.env.example`**
  - Gerçek anahtarlar silinir, yerlerine yer tutucular konur.
  - `ADMIN_IDS`, `HEALTHCHECK_URL`, `BOT_DATABASE_PATH`, `BOT_VERSION` açıklamalarıyla eklenir.
- **Repo yapısı**
  - Git deposu `telegram-bot/` kökünde oluşturulur.
  - Kökteki `../messifebot.py` repo dışında kalır.
- **`.gitignore`**
  - `.env`, `.venv/`, `bot_env/`, `data/`, `__pycache__/`, `*.pyc` hariç tutulur.
- **Kullanıcının yapacakları**
  - BotFather'da `/revoke` ile yeni bir token alır.
  - Yerel geliştirme için ayrı bir test botu oluşturur. Canlı token sadece sunucuda bulunur.

### 4.2 Sunucu yapısı

| Öğe | Değer |
|---|---|
| Makine | Oracle `VM.Standard.A1.Flex` (1 OCPU / 6 GB). Kapasite yoksa `VM.Standard.E2.1.Micro` (1 GB) + 2 GB swap |
| İşletim sistemi | Ubuntu 24.04 LTS (Python 3.12), saat dilimi `Europe/Istanbul` |
| Uygulama kullanıcısı | `messifebot` (sistem kullanıcısı, oturum açamaz) |
| Deploy kullanıcısı | `deploy` (SSH anahtarıyla giriş; sudo yetkisi sadece `deploy.sh` için) |
| Kod | `/opt/messifebot` — git checkout, `.venv` burada |
| Veri | `/var/lib/messifebot/chat_stats.db`, yedekler `/var/lib/messifebot/backups/` |
| Sırlar | `/etc/messifebot.env` (sahibi root, grubu `messifebot`, izin `0640`) |
| Erişim | Gelen trafikte sadece SSH (anahtarla; parola girişi kapalı). Bot yalnızca dışarı bağlanır |
| Loglar | journald; toplam 200 MB sınırı |

**systemd servisi (`deploy/messifebot.service`)**
- `User=messifebot`, `WorkingDirectory=/opt/messifebot`
- `EnvironmentFile=/etc/messifebot.env`
- `ExecStart=/opt/messifebot/.venv/bin/python -m bot.main`
- `Restart=always`, `RestartSec=10`
- `RestartSteps=5`, `RestartMaxDelaySec=300`, `StartLimitIntervalSec=0`: art arda çökmelerde yeniden başlatma gecikmesi kademeli olarak 5 dakikaya kadar büyür; systemd asla yeniden başlatmayı bırakmaz. Bot uzun süre ayakta kalamazsa bu durum healthcheck üzerinden e-posta ile fark edilir.
- `TimeoutStopSec=30` (python-telegram-bot SIGTERM ile düzgün kapanır)
- Temel sertleştirme: `NoNewPrivileges=true`, `ProtectSystem=full`, `ReadWritePaths=/var/lib/messifebot`

**Kurulum betiği (`deploy/setup_server.sh`)**
- Tekrar çalıştırılabilir (idempotent). Kullanıcı sunucuda root olarak bir kez çalıştırır.
- Yaptıkları:
  - paketleri kurar (python3-venv, git, sqlite3, curl),
  - kullanıcıları ve dizinleri oluşturur,
  - gerekiyorsa swap açar,
  - saat dilimini ve journald sınırını ayarlar,
  - `messifebot` kullanıcısı için salt-okunur GitHub deploy anahtarını üretir ve açık anahtarını ekrana yazar,
  - repoyu klonlar, venv'i kurar,
  - systemd servis ve zamanlayıcı dosyalarını yükler,
  - `deploy` kullanıcısının sudoers kuralını ekler,
  - `/etc/messifebot.env` yoksa şablondan oluşturur.
- Sırları kendisi yazmaz; kullanıcı `/etc/messifebot.env` dosyasını doldurur.

### 4.3 Otomatik deploy

**GitHub Actions (`.github/workflows/deploy.yml`)**
- Tetikleyici: `main` dalına push ve `workflow_dispatch` (elle başlatma).
- `concurrency: deploy` ile aynı anda tek deploy çalışır.
- **Job `test`** (ubuntu-latest, Python 3.12):
  1. `pip install -r requirements.txt`
  2. `python -m unittest discover -s tests` (canlı testler kendiliğinden atlanır)
  3. `bash -n deploy/*.sh` ile betiklerin sözdizimi kontrol edilir.
- **Job `deploy`** (`needs: test`):
  1. `SSH_PRIVATE_KEY` ve `SSH_KNOWN_HOSTS` sırlarıyla `deploy@SERVER_HOST`'a bağlanır.
  2. `sudo /usr/local/sbin/messifebot-deploy` çalıştırır.
  3. Betiğin çıkış kodu job sonucunu belirler.
- GitHub Secrets'ta yalnızca şunlar bulunur: `SERVER_HOST`, `SSH_PRIVATE_KEY` (sadece deploy için), `SSH_KNOWN_HOSTS`. Bot sırları GitHub'a girmez.

**Sunucu betiği (`deploy/deploy.sh`, root olarak çalışır, tek örnek kilidiyle)**

Güvenlik notu: Repo dizini `messifebot` kullanıcısına aittir. Bot süreci ele geçirilse bile root yetkisi kazanılmasın diye root, repodaki dosyaları doğrudan çalıştırmaz:
- `setup_server.sh`, `deploy.sh`'ı root'a ait `/usr/local/sbin/messifebot-deploy` olarak kurar; sudoers kuralı sadece bu yolu kapsar.
- Git, pip ve bildirim betiği `messifebot` kullanıcısıyla çalıştırılır.
- `deploy.sh` veya systemd dosyaları değişirse `setup_server.sh` yeniden çalıştırılır.

1. `PREV=$(git rev-parse HEAD)`
2. Kodu `messifebot` kullanıcısıyla çeker: `git fetch origin main && git reset --hard origin/main`.
3. `requirements.txt` değiştiyse `.venv/bin/pip install -r requirements.txt` çalıştırır.
4. `BOT_VERSION` değerini (kısa commit hash) `/var/lib/messifebot/version` dosyasına yazar.
5. `systemctl restart messifebot`, ardından 20 sn bekler.
6. `systemctl is-active messifebot` başarılıysa ve servisin ana süreç kimliği (MainPID) 20 sn boyunca değişmediyse (yani bu sürede çöküp yeniden başlamadıysa) çıkış kodu 0.
7. Aksi halde:
   - `git reset --hard $PREV` yapar, gerekirse bağımlılıkları yeniden kurar ve servisi yeniden başlatır,
   - admin'e "⚠️ Deploy başarısız, `$PREV` ile devam ediliyor" mesajını gönderir (Telegram Bot API'ye `curl`, token `/etc/messifebot.env`'den okunur),
   - çıkış kodu 1 döner.
- Deploy sırasındaki kesinti birkaç saniyedir. Telegram bekleyen güncellemeleri saklar ve bot açılınca işler.
- Elle deploy: `ssh deploy@sunucu sudo /usr/local/sbin/messifebot-deploy`.

### 4.4 İzleme ve bildirimler

**Yeni modül `bot/services/admin_notify.py`**
- `AdminNotifier(bot, admin_ids, clock)` sınıfı; `ADMIN_IDS` boşsa sessizce devre dışı kalır.
- `notify_startup(version, unclean_previous: bool)` şu mesajı gönderir: "✅ Bot başladı: sürüm `abc1234`". `unclean_previous` doğruysa mesaja "⚠️ Önceki çalışma düzgün kapanmadı" satırı eklenir.
- `notify_error(error_type, where)` kısa bir özet gönderir. Kullanıcı mesaj içeriği, token veya anahtar içermez; tam traceback sadece log'a yazılır.
- Hız sınırı:
  - aynı `(hata türü, yer)` için 30 dakikada en fazla 1 bildirim,
  - toplamda saatte en fazla 10 bildirim.
- Gönderim hataları yutulur ve loglanır; bildirim sistemi botu asla düşürmez.

**Temiz kapanış işareti**
- Açılışta:
  1. `meta.clean_shutdown` okunur.
  2. Değer `"0"` ise önceki çalışma beklenmedik şekilde bitmiş demektir.
  3. Değer tekrar `"0"` yapılır.
- `Application.post_shutdown` içinde `"1"` yazılır.
- İlk kurulumda (anahtar yoksa) "beklenmedik" sayılmaz.

**Hata yakalama**
- `main.py`'deki mevcut `error_handler` hatayı loglamaya devam eder.
- Ek olarak `AdminNotifier.notify_error` çağrılır.
- Handler ve JobQueue hataları python-telegram-bot tarafından zaten bu handler'a yönlendirilir.

**Sürüm bilgisi**
- Önce `BOT_VERSION` ortam değişkenine bakılır, sonra `/var/lib/messifebot/version` dosyasına.
- İkisi de yoksa `git rev-parse --short HEAD` denenir; o da olmazsa `"dev"` kullanılır.

**Dış kontrol (healthchecks.io)**
- `HEALTHCHECK_URL` tanımlıysa JobQueue her 5 dakikada bir `heartbeat_job` çalıştırır:
  - `bot.get_me()` başarılıysa `GET HEALTHCHECK_URL`,
  - başarısızsa `GET HEALTHCHECK_URL/fail`.
  - Zaman aşımı 10 sn; hatalar loglanır ve yutulur.
- İstek bloklamaması için `asyncio.to_thread` + `requests` kullanılır.
- healthchecks.io ayarı: periyot 5 dk, tolerans 10 dk, bildirim kanalı e-posta. Kullanıcı ücretsiz hesap açar, URL'yi `/etc/messifebot.env`'e yazar.
- `HEALTHCHECK_URL` boşsa özellik kapalıdır. Yerel geliştirme etkilenmez.

### 4.5 Yedekleme

**`deploy/backup.sh`**
- `messifebot` kullanıcısıyla çalışır. `messifebot-backup.timer` onu her gün 03:30'da (`Persistent=true`) başlatır.
1. `sqlite3 chat_stats.db ".backup tmp.db"`: bot çalışırken tutarlı çevrimiçi yedek alır.
2. `PRAGMA integrity_check`. Sonuç `ok` değilse yedek silinir, admin'e "❗ Yedek bozuk" bildirimi gönderilir ve betik 1 ile çıkar.
3. `gzip` ile `backups/chat_stats-YYYYMMDD-HHMM.db.gz` dosyası üretilir.
4. 14 günden eski yedekler silinir.
5. Pazar günleri (veya `--send` bayrağıyla) en son yedek admin'e Telegram `sendDocument` ile sessiz bildirimle gönderilir.

**Geri yükleme (rehberde belgelenir)**
1. `systemctl stop messifebot`
2. `gunzip` ile yedek açılır ve `chat_stats.db`'nin yerine konur.
3. Sahiplik düzeltilir: `chown messifebot:`.
4. `systemctl start messifebot`

### 4.6 Veri taşıma (tek seferlik, rehberde adım adım)

1. Yerelde çalışan tüm bot süreçleri durdurulur. Aynı token'la iki örnek "Conflict" hatası üretir.
2. Yerel `data/chat_stats.db` dosyasının tarihli bir kopyası alınır.
3. Dosya `scp data/chat_stats.db deploy@sunucu:/tmp/` ile sunucuya kopyalanır.
4. Sunucuda sırasıyla:
   1. `integrity_check` çalıştırılır,
   2. dosya `/var/lib/messifebot/` altına taşınır,
   3. sahiplik `messifebot` yapılır, izin `0640` ayarlanır.
5. Ardından `systemctl start messifebot`.
6. Eski şema kolonları (`provider_id` vb.) uygulamanın mevcut migration mantığıyla açılışta eklenir.

### 4.7 Rehber

`deploy/README.md` (Türkçe) sırayla şunları içerir:
1. BotFather token yenileme ve test botu oluşturma
2. Oracle hesabı ve VM oluşturma (şekil, imaj, SSH anahtarı, güvenlik listesi)
3. GitHub private repo ve ilk push
4. `setup_server.sh` çalıştırma ve deploy anahtarının GitHub'a eklenmesi
5. `/etc/messifebot.env` doldurma
6. GitHub Secrets
7. healthchecks.io
8. Veri taşıma
9. Kabul testleri
10. Günlük işlemler: log görme, yeniden başlatma, elle deploy, geri yükleme

## 5. Test

**Otomatik (CI'da ve yerelde, offline)**
- `AdminNotifier`:
  - `ADMIN_IDS` boşken hiçbir şey göndermez,
  - açılış mesajında sürüm ve "düzgün kapanmadı" notu yer alır,
  - hata bildirimlerinde 30 dk tekrar ve saatlik 10 sınırı uygulanır (sahte saat ile),
  - gönderim hatası exception fırlatmaz,
  - mesajlar geçerli HTML'dir ve sır içermez.
- Temiz kapanış işareti: ilk kurulum, temiz kapanış ve kirli kapanış senaryoları.
- Heartbeat:
  - `get_me` başarılıysa URL'ye, başarısızsa `/fail`'e istek atılır (sahte HTTP),
  - URL boşsa job hiç kaydedilmez.
- Config: `BOT_TOKEN` yoksa açık hata verir.
- Mevcut 78 testin hepsi geçmeye devam eder.
- CI'da `bash -n deploy/*.sh` çalışır.

**Kabul testleri (kurulum sonrası, kullanıcıyla)**
1. Küçük bir değişiklik push'lanır → CI yeşil → Telegram'a yeni sürümle "✅ Bot başladı" gelir.
2. Açılışta hata veren bir commit push'lanır → otomatik geri dönüş + "⚠️ Deploy başarısız" mesajı. Ardından düzeltme commit'i atılır.
3. `sudo systemctl kill -s KILL messifebot` → 10 sn içinde yeniden başlar ve "düzgün kapanmadı" notu gelir.
4. `sudo systemctl stop messifebot` ile 10+ dk beklenir → healthchecks.io e-postası gelir → servis başlatılır.
5. `sudo -u messifebot /opt/messifebot/deploy/backup.sh --send` → yedek dosyası oluşur ve Telegram'a gönderilir.
6. `sudo reboot` → bot kendiliğinden geri gelir.

## 6. Kapsam dışı (YAGNI)

- Docker/Kubernetes, çoklu sunucu, yük dengeleme.
- PostgreSQL'e geçiş.
- Sunucu dışı otomatik yedek depolama (S3 vb.); haftalık Telegram kopyası yeterli.
- Web paneli / metrik panosu.
- Staging ortamı; yerel test botu bu ihtiyacı karşılar.

## 7. Riskler

| Risk | Önlem |
|---|---|
| Oracle ARM kapasitesi yok | E2.1.Micro + swap. Bot ~100–150 MB RAM kullanıyor |
| Oracle boşta kalan Always Free VM'leri geri alabiliyor (düşük CPU kullanımı) | Hesap "Pay As You Go"ya yükseltilirse (Always Free kaynaklar yine ücretsiz) bu politika uygulanmaz; rehberde seçenek olarak anlatılır. VM geri alınırsa haftalık yedek + kurulum betiği ile yeniden kurulum dakikalar sürer |
| Yanlış commit botu bozar | CI testleri + otomatik geri dönüş |
| Sırların sızması | Sırlar sadece `/etc/messifebot.env`'de (0640); repo ve GitHub Secrets'ta bot sırrı yok; eski token iptal edilir |
| Yerel geliştirmede canlı token kullanımı (Conflict) | Ayrı test botu |
