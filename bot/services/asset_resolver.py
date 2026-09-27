# bot/services/asset_resolver.py
"""Kullanıcı girdisini ('PI', 'Pi Network', 'pi-network' ...) kesin bir sağlayıcı varlığına çözer.

Akış:
    girdi -> normalize -> alias/cache -> yerel katalog (tam eşleşme)
          -> sağlayıcı araması -> çakışma kontrolü -> Asset

Semboller benzersiz değildir. Birden fazla varlık aynı sembolü/ismi taşıyorsa ve
biri açıkça baskın değilse (piyasa değeri sıralamasına göre), sonuç 'ambiguous'
döner ve kullanıcıya seçenekler gösterilmelidir.
"""
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from bot.services.asset_provider import ProviderError

# Alias geçerlilik süreleri (saniye)
ALIAS_TTL = {
    'seed': None,               # süresiz
    'user': 90 * 24 * 3600,     # kullanıcının kendi seçimi
    'auto': 7 * 24 * 3600,      # otomatik çözümleme (sıralamalar değişebilir)
}
CATALOG_MAX_AGE = 24 * 3600     # yerel katalog günde bir yenilenir
CATALOG_RETRY_AFTER = 15 * 60   # başarısız yenilemeden sonra tekrar deneme aralığı
DOMINANCE_FACTOR = 10           # en iyi aday, diğerlerinden en az 10 kat daha iyi sıralı olmalı
RANK_PAGES = 4                  # yedek sıralama tablosu: ilk 4*250 = 1000 varlık
RANKS_MAX_AGE = 3 * 24 * 3600

# Sık kullanılan varlıklar için küçük başlangıç eşlemesi. Sadece hız/çevrimdışı
# dayanıklılık içindir; diğer tüm varlıklar dinamik olarak bulunur.
SEED_ALIASES = {
    'btc': 'bitcoin',
    'eth': 'ethereum',
    'usdt': 'tether',
    'usdc': 'usd-coin',
    'bnb': 'binancecoin',
    'sol': 'solana',
    'xrp': 'ripple',
}


@dataclass
class Asset:
    provider_id: str
    symbol: str
    name: str
    market_cap_rank: Optional[int] = None

    @classmethod
    def from_row(cls, row: dict) -> "Asset":
        return cls(row['provider_id'], (row.get('symbol') or '').upper(), row.get('name') or '',
                   row.get('market_cap_rank'))

    def label(self) -> str:
        return f"{self.name} ({self.symbol})"


@dataclass
class Resolution:
    status: str                         # 'resolved' | 'ambiguous' | 'not_found' | 'error'
    query: str = ''
    asset: Optional[Asset] = None
    candidates: list = field(default_factory=list)   # ambiguous: seçilebilecek Asset'ler
    suggestions: list = field(default_factory=list)  # not_found: benzer sonuçlar
    source: str = ''                    # 'alias', 'catalog', 'provider', 'selection'
    message: str = ''

    @property
    def ok(self) -> bool:
        return self.status == 'resolved'


def normalize(query: str) -> str:
    """'  Pi   Network ' -> 'pi network'. Türkçe İ/ı da 'i' olur (PI yazan klavyeler için)."""
    text = (query or '').strip().lstrip('$')
    text = text.replace('İ', 'i').replace('ı', 'i').replace('İ', 'i').lower()
    text = text.replace('i̇', 'i')
    return re.sub(r'\s+', ' ', text)


def slugify(normalized: str) -> str:
    """'pi network' -> 'pi-network' (sağlayıcı ID biçimi)"""
    return normalized.replace(' ', '-')


class AssetResolver:
    def __init__(self, db, provider, now=time.time):
        self.db = db
        self.provider = provider
        self._now = now
        self._catalog_lock = threading.Lock()
        self._catalog_failed_at = 0.0
        self._ranks_failed_at = 0.0
        self._seeded = False

    # --- Katalog -----------------------------------------------------------

    def ensure_catalog(self, force: bool = False) -> bool:
        """Yerel varlık kataloğunu gerekirse sağlayıcıdan yeniler. Başarılıysa True."""
        with self._catalog_lock:
            last = float(self.db.get_meta('asset_catalog_refreshed_at') or 0)
            fresh = self.db.count_assets() > 0 and self._now() - last < CATALOG_MAX_AGE
            if fresh and not force:
                # Katalog güncel; yedek sıralama tablosu eskidiyse onu da yenile
                if self._rank_floor() is None and self._now() - self._ranks_failed_at >= CATALOG_RETRY_AFTER:
                    self._refresh_ranks()
                return True
            if not force and self._now() - self._catalog_failed_at < CATALOG_RETRY_AFTER:
                return False
            try:
                assets = self.provider.list_assets()
            except ProviderError as e:
                print(f"❌ Varlık kataloğu yenilenemedi: {e}")
                self._catalog_failed_at = self._now()
                return False
            count = self.db.upsert_assets(assets)
            self.db.set_meta('asset_catalog_refreshed_at', self._now())
            print(f"✅ Varlık kataloğu güncellendi: {count} varlık")
            self._refresh_ranks()
            return True

    def _refresh_ranks(self):
        """İlk RANK_PAGES*250 varlığın sıralamasını kaydet (canlı sıralama alınamazsa yedek olarak kullanılır)"""
        try:
            ranks = self.provider.top_ranks(RANK_PAGES)
        except ProviderError as e:
            print(f"⚠️ Sıralamalar alınamadı: {e}")
            self._ranks_failed_at = self._now()
            return
        self.db.set_ranks(ranks)
        self.db.set_meta('asset_ranks_refreshed_at', self._now())

    def _rank_floor(self) -> Optional[int]:
        """Kayıtlı sıralamalar güncelse, listede olmayan bir varlığın sıralaması bundan kötüdür"""
        refreshed = float(self.db.get_meta('asset_ranks_refreshed_at') or 0)
        if refreshed and self._now() - refreshed < RANKS_MAX_AGE:
            return RANK_PAGES * 250 + 1
        return None

    def _ensure_seeds(self):
        if self._seeded:
            return
        for alias, provider_id in SEED_ALIASES.items():
            if not self.db.get_aliases(alias):
                self.db.set_alias(alias, provider_id, 'seed')
        self._seeded = True

    # --- Alias -------------------------------------------------------------

    def _alias_hit(self, key: str, user_id: int) -> Optional[Asset]:
        for row in self.db.get_aliases(key, user_id):
            ttl = ALIAS_TTL.get(row['source'], ALIAS_TTL['auto'])
            if ttl is not None:
                age = self._now() - datetime.fromisoformat(row['updated_at']).timestamp()
                if age > ttl:
                    self.db.delete_alias(key, row['user_id'])
                    continue
            asset_row = self.db.get_asset(row['provider_id'])
            if asset_row:
                return Asset.from_row(asset_row)
            # Katalog henüz senkronize edilmemiş olabilir (ör. çevrimdışı ilk açılış): ID ile yetin
            return Asset(row['provider_id'], key.upper(), row['provider_id'])
        return None

    def remember_selection(self, query: str, asset: Asset, user_id: int):
        """Kullanıcının belirsiz bir sorgu için yaptığı seçimi hatırla"""
        key = normalize(query)
        if key:
            self.db.upsert_assets([vars(asset)])
            self.db.set_alias(key, asset.provider_id, 'user', user_id)

    # --- Çözümleme ---------------------------------------------------------

    @staticmethod
    def _is_exact(asset: dict, key: str) -> bool:
        return (asset['provider_id'] == slugify(key)
                or (asset.get('name') or '').lower() == key
                or (asset.get('symbol') or '').lower() == key)

    def _rank_candidates(self, candidates: list, offline: bool = False):
        """Adaylara güncel piyasa sıralamasını ekler (tek istek).

        Dönüş: (adaylar, sıralanmamış bir adayın en iyi olası sıralaması).
        Canlı veri alındıysa sıralaması olmayan aday gerçekten sıralamasızdır (sonsuz).
        Alınamadıysa kayıtlı top-1000 tablosu kullanılır: listede olmayan aday >1000'dir.
        Hiçbir bilgi yoksa None döner (sıralamasız adaylar hakkında hüküm verilemez).
        """
        if len(candidates) < 2:
            return candidates, float('inf')
        if offline:
            return candidates, self._rank_floor()
        try:
            market = self.provider.market_data([c.provider_id for c in candidates])
        except ProviderError as e:
            print(f"⚠️ Aday sıralaması alınamadı, kayıtlı sıralamalar kullanılıyor: {e}")
            return candidates, self._rank_floor()
        for c in candidates:
            info = market.get(c.provider_id)
            c.market_cap_rank = info.get('market_cap_rank') if info else None
        self.db.upsert_assets([vars(c) for c in candidates], replace_rank=True)
        return candidates, float('inf')

    @staticmethod
    def _sort_key(asset: Asset):
        return (asset.market_cap_rank is None, asset.market_cap_rank or 0, asset.name.lower())

    @staticmethod
    def _dominant(candidates: list, unranked_floor=float('inf')) -> Optional[Asset]:
        """Tek bir aday açıkça baskınsa onu döndür, yoksa None.

        unranked_floor: sıralaması bilinmeyen bir adayın alabileceği en iyi sıralama
        (None: bilinmiyor -> sıralamasız rakip varsa karar verilmez).
        """
        if len(candidates) == 1:
            return candidates[0]
        ranked = sorted(candidates, key=AssetResolver._sort_key)
        best, others = ranked[0], ranked[1:]
        if best.market_cap_rank is None:
            return None
        threshold = best.market_cap_rank * DOMINANCE_FACTOR
        for other in others:
            rank = other.market_cap_rank
            if rank is None:
                if unranked_floor is None or unranked_floor < threshold:
                    return None
            elif rank < threshold:
                return None
        return best

    def _provider_search(self, key: str) -> Optional[list]:
        try:
            results = self.provider.search(key)
        except ProviderError as e:
            print(f"⚠️ Sağlayıcı araması başarısız: {e}")
            return None
        if results:
            self.db.upsert_assets(results)
        return results

    def resolve(self, query: str, user_id: int = 0, offline: bool = False) -> Resolution:
        """Girdiyi tek bir varlığa çözer (bloklayan çağrı - handler'larda to_thread ile kullanın).

        offline=True: ağ çağrısı yapmaz; sadece alias ve yerel katalog/kayıtlı sıralamalar kullanılır
        (sohbette bir kelimenin coin olup olmadığını ucuzca yoklamak için)."""
        key = normalize(query)
        if not key:
            return Resolution('not_found', query, message="Boş sorgu")

        self._ensure_seeds()

        # 1) Alias / cache
        hit = self._alias_hit(key, user_id)
        if hit:
            return Resolution('resolved', query, asset=hit, source='alias')

        # 2) Yerel katalogda tam eşleşme
        catalog_ok = True if offline else self.ensure_catalog()
        rows = self.db.find_assets_exact(slugify(key), key, key)
        source = 'catalog'
        search_results = None

        # 3) Katalogda yoksa (yeni listelenmiş olabilir) sağlayıcıda ara
        if not rows and not offline:
            search_results = self._provider_search(key)
            if search_results:
                rows = [r for r in search_results if self._is_exact(r, key)]
                source = 'provider'

        if not rows:
            if search_results is None and not catalog_ok:
                return Resolution('error', query, message="Kripto veri sağlayıcısına ulaşılamadı")
            suggestions = [Asset.from_row(r) for r in (search_results or [])[:5]]
            return Resolution('not_found', query, suggestions=suggestions)

        candidates = [Asset.from_row(r) for r in rows]
        candidates, unranked_floor = self._rank_candidates(candidates, offline)
        best = self._dominant(candidates, unranked_floor)
        if best:
            self.db.set_alias(key, best.provider_id, 'auto')
            return Resolution('resolved', query, asset=best, source=source,
                              candidates=sorted(candidates, key=self._sort_key))

        return Resolution('ambiguous', query, candidates=sorted(candidates, key=self._sort_key)[:10],
                          source=source)

    def search(self, query: str, limit: int = 8) -> Resolution:
        """/searchcrypto için: tam eşleşmeler önce, ardından sağlayıcının bulanık sonuçları.
        status: 'resolved' (en az bir sonuç), 'not_found' veya 'error'."""
        key = normalize(query)
        if not key:
            return Resolution('not_found', query)

        self._ensure_seeds()
        catalog_ok = self.ensure_catalog()
        exact = [Asset.from_row(r) for r in self.db.find_assets_exact(slugify(key), key, key)]
        search_results = self._provider_search(key)

        seen, results = set(), []
        for asset in sorted(self._rank_candidates(exact)[0], key=self._sort_key) + \
                [Asset.from_row(r) for r in (search_results or [])]:
            if asset.provider_id not in seen:
                seen.add(asset.provider_id)
                results.append(asset)

        if not results:
            if search_results is None and not catalog_ok:
                return Resolution('error', query, message="Kripto veri sağlayıcısına ulaşılamadı")
            return Resolution('not_found', query)
        return Resolution('resolved', query, candidates=results[:limit], source='search')

    def asset_for_id(self, provider_id: str) -> Asset:
        row = self.db.get_asset(provider_id)
        return Asset.from_row(row) if row else Asset(provider_id, '', provider_id)
