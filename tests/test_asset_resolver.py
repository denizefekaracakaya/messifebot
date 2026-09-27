"""Kripto varlık çözümleme testleri.

Çalıştırma (telegram-bot/ klasöründen):
    .venv\\Scripts\\python -m unittest discover -s tests -v

Gerçek CoinGecko'ya karşı kabul testleri için:
    set RUN_LIVE_TESTS=1  (PowerShell: $env:RUN_LIVE_TESTS=1)
"""
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# Testler gerçek veritabanına dokunmasın
os.environ["BOT_DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "global_test.db")

from bot.database import Database  # noqa: E402
from bot.services.asset_provider import ProviderError, CoinGeckoProvider  # noqa: E402
from bot.services.asset_resolver import AssetResolver, normalize  # noqa: E402

# (id, symbol, name, market_cap_rank, in_catalog)
FAKE_COINS = [
    ("bitcoin", "btc", "Bitcoin", 1, True),
    ("wrapped-fake-btc", "btc", "Wrapped Fake BTC", 1500, True),
    ("btc-meme", "btc", "BTC Meme", None, True),
    ("ethereum", "eth", "Ethereum", 2, True),
    ("ethereum-meme", "eth", "Ethereum Meme", None, True),
    ("solana", "sol", "Solana", 7, True),
    ("sol-wormhole-fake", "sol", "Wrapped SOL Fake", 2500, True),
    ("pi-network", "pi", "Pi Network", 79, True),
    ("pchain", "pi", "Plian", 4363, True),
    ("pi-network-iou", "pi", "Pi Network [IOU]", None, True),
    ("pi-network-dog", "pidog", "Pi Network Dog", None, True),
    # Sembol çakışması: sıralamaları birbirine yakın iki farklı proje
    ("abc-one", "abc", "Alpha Beta Coin", 300, True),
    ("abc-two", "abc", "Another Blockchain", 450, True),
    # Katalog senkronizasyonundan sonra listelenmiş yeni coin (sadece aramada var)
    ("fresh-coin", "fresh", "Fresh Coin", 900, False),
]
FAKE_PRICES = {"bitcoin": 84000.0, "ethereum": 2700.0, "solana": 120.0, "pi-network": 0.0919,
               "pchain": 0.00032, "abc-one": 1.0, "abc-two": 2.0, "fresh-coin": 3.0}


class FakeProvider:
    """CoinGeckoProvider ile aynı arayüz, sabit veri; çağrı sayılarını tutar"""

    def __init__(self):
        self.calls = {"list_assets": 0, "search": 0, "market_data": 0, "prices": 0, "top_ranks": 0}
        self.down = False
        self.market_down = False  # sadece /coins/markets (ör. rate limit)

    def _check(self, name):
        self.calls[name] += 1
        if self.down or (self.market_down and name in ("market_data", "top_ranks")):
            raise ProviderError("sağlayıcı kapalı (test)")

    def top_ranks(self, pages=4):
        self._check("top_ranks")
        return {c[0]: c[3] for c in FAKE_COINS if c[3] and c[3] <= pages * 250}

    def list_assets(self):
        self._check("list_assets")
        return [{"provider_id": i, "symbol": s, "name": n} for i, s, n, _, cat in FAKE_COINS if cat]

    def search(self, query):
        self._check("search")
        q = query.lower()
        hits = [c for c in FAKE_COINS if q in c[2].lower() or q in c[1] or q in c[0]]
        hits.sort(key=lambda c: (c[3] is None, c[3] or 0))
        return [{"provider_id": i, "symbol": s.upper(), "name": n, "market_cap_rank": r}
                for i, s, n, r, _ in hits]

    def market_data(self, ids):
        self._check("market_data")
        ranks = {c[0]: c[3] for c in FAKE_COINS}
        return {i: {"id": i, "market_cap_rank": ranks[i], "current_price": FAKE_PRICES.get(i)}
                for i in ids if i in ranks and i in FAKE_PRICES}

    def prices(self, ids):
        self._check("prices")
        return {i: FAKE_PRICES[i] for i in ids if i in FAKE_PRICES}


class Clock:
    def __init__(self):
        import time
        self.t = time.time()

    def __call__(self):
        return self.t


def make_resolver(seeds=True):
    db = Database(os.path.join(tempfile.mkdtemp(), "test.db"))
    provider = FakeProvider()
    clock = Clock()
    resolver = AssetResolver(db, provider, now=clock)
    if not seeds:
        resolver._seeded = True  # başlangıç alias'larını devre dışı bırak: tamamen dinamik çözümleme
    return resolver, provider, db, clock


class PiNetworkAcceptanceTests(unittest.TestCase):
    PI_INPUTS = ["PI", "pi", "Pi", "Pi Network", "pi network", "pi-network", "  Pi   Network ", "Pİ", "$PI"]

    def test_all_pi_inputs_resolve_to_pi_network(self):
        for text in self.PI_INPUTS:
            with self.subTest(input=text):
                resolver, _, _, _ = make_resolver()  # her girdi için temiz cache
                result = resolver.resolve(text)
                self.assertEqual(result.status, "resolved", result)
                self.assertEqual(result.asset.provider_id, "pi-network")
                self.assertEqual(result.asset.symbol, "PI")
                self.assertEqual(result.asset.name, "Pi Network")

    def test_pi_collision_is_detected_but_pi_network_is_dominant(self):
        resolver, _, _, _ = make_resolver()
        result = resolver.resolve("PI")
        ids = {c.provider_id for c in result.candidates}
        self.assertTrue({"pi-network", "pchain", "pi-network-iou"} <= ids)
        self.assertEqual(result.asset.provider_id, "pi-network")

    def test_searchcrypto_pi_lists_pi_network_first(self):
        resolver, _, _, _ = make_resolver()
        result = resolver.search("PI")
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.candidates[0].provider_id, "pi-network")
        self.assertEqual(result.candidates[0].symbol, "PI")


class MajorAssetTests(unittest.TestCase):
    CASES = {
        "BTC": "bitcoin", "Bitcoin": "bitcoin", "bitcoin": "bitcoin",
        "ETH": "ethereum", "Ethereum": "ethereum",
        "SOL": "solana", "Solana": "solana",
    }

    def test_major_assets_resolve(self):
        for seeds in (True, False):
            for text, expected in self.CASES.items():
                with self.subTest(input=text, seeds=seeds):
                    resolver, _, _, _ = make_resolver(seeds=seeds)
                    result = resolver.resolve(text)
                    self.assertEqual(result.status, "resolved", result)
                    self.assertEqual(result.asset.provider_id, expected)


class EdgeCaseTests(unittest.TestCase):
    def test_unknown_asset_returns_not_found(self):
        resolver, _, _, _ = make_resolver()
        result = resolver.resolve("THISCOINDOESNOTEXIST")
        self.assertEqual(result.status, "not_found")
        self.assertIsNone(result.asset)
        self.assertEqual(resolver.search("THISCOINDOESNOTEXIST").status, "not_found")

    def test_empty_input(self):
        resolver, _, _, _ = make_resolver()
        self.assertEqual(resolver.resolve("   ").status, "not_found")

    def test_symbol_collision_requires_user_choice(self):
        resolver, _, _, _ = make_resolver()
        result = resolver.resolve("ABC")
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual([c.provider_id for c in result.candidates], ["abc-one", "abc-two"])
        self.assertIsNone(result.asset)

    def test_user_selection_is_remembered_per_user(self):
        resolver, provider, _, _ = make_resolver()
        choice = resolver.resolve("ABC", user_id=1).candidates[1]
        resolver.remember_selection("ABC", choice, user_id=1)

        mine = resolver.resolve("abc", user_id=1)
        self.assertEqual(mine.status, "resolved")
        self.assertEqual(mine.asset.provider_id, "abc-two")
        self.assertEqual(mine.source, "alias")
        # Başka bir kullanıcının seçimi etkilenmez
        self.assertEqual(resolver.resolve("ABC", user_id=2).status, "ambiguous")

    def test_resolution_is_cached(self):
        resolver, provider, _, _ = make_resolver(seeds=False)
        self.assertEqual(resolver.resolve("pi network").asset.provider_id, "pi-network")
        before = dict(provider.calls)
        again = resolver.resolve("Pi Network")
        self.assertEqual(again.asset.provider_id, "pi-network")
        self.assertEqual(again.source, "alias")
        self.assertEqual(provider.calls, before, "önbellekten çözülmeli, sağlayıcı çağrılmamalı")

    def test_auto_alias_expires(self):
        resolver, provider, _, clock = make_resolver(seeds=False)
        resolver.resolve("PI")
        clock.t += 8 * 24 * 3600  # auto alias TTL = 7 gün
        market_calls = provider.calls["market_data"]
        result = resolver.resolve("PI")
        self.assertEqual(result.asset.provider_id, "pi-network")
        self.assertNotEqual(result.source, "alias")
        self.assertGreater(provider.calls["market_data"], market_calls)

    def test_catalog_is_downloaded_once(self):
        resolver, provider, _, _ = make_resolver()
        for text in ["PI", "ABC", "Solana", "THISCOINDOESNOTEXIST"]:
            resolver.resolve(text)
        self.assertEqual(provider.calls["list_assets"], 1)

    def test_newly_listed_coin_is_discovered_via_provider_search(self):
        resolver, _, db, _ = make_resolver()
        result = resolver.resolve("FRESH")
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.asset.provider_id, "fresh-coin")
        self.assertIsNotNone(db.get_asset("fresh-coin"), "keşfedilen varlık kataloğa eklenmeli")

    def test_provider_down_with_empty_catalog_is_clean_error(self):
        resolver, provider, _, _ = make_resolver(seeds=False)
        provider.down = True
        result = resolver.resolve("PI")
        self.assertEqual(result.status, "error")
        self.assertEqual(resolver.search("PI").status, "error")

    def test_provider_down_uses_local_catalog(self):
        resolver, provider, _, _ = make_resolver()
        resolver.ensure_catalog()
        provider.down = True
        # Sağlayıcı kapalıyken arama/sıralama yapılamaz ama yerel katalog aday bulmaya devam eder
        result = resolver.resolve("Pi Network")
        self.assertIn(result.status, ("resolved", "ambiguous"))
        self.assertIn("pi-network", [c.provider_id for c in result.candidates] +
                      ([result.asset.provider_id] if result.asset else []))

    def test_rate_limited_ranking_falls_back_to_cached_top_ranks(self):
        resolver, provider, _, _ = make_resolver(seeds=False)
        resolver.ensure_catalog()  # katalog + top-1000 sıralamaları kaydedilir
        provider.market_down = True
        result = resolver.resolve("PI")
        self.assertEqual(result.status, "resolved", result)
        self.assertEqual(result.asset.provider_id, "pi-network")
        # Yakın sıralı çakışma yine de kullanıcıya sorulur
        self.assertEqual(resolver.resolve("ABC").status, "ambiguous")

    def test_no_rank_information_means_ask_user(self):
        resolver, provider, _, _ = make_resolver(seeds=False)
        provider.market_down = True  # ne canlı ne kayıtlı sıralama var
        result = resolver.resolve("PI")
        self.assertEqual(result.status, "ambiguous")
        self.assertIn("pi-network", [c.provider_id for c in result.candidates])

    def test_normalize(self):
        self.assertEqual(normalize("  Pi   Network "), "pi network")
        self.assertEqual(normalize("Pİ"), "pi")
        self.assertEqual(normalize("$BTC"), "btc")


class MigrationTests(unittest.TestCase):
    def test_old_symbol_only_rows_are_preserved_and_migrated(self):
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        with sqlite3.connect(path) as conn:
            conn.execute('''CREATE TABLE portfolio (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                            coin_symbol TEXT, amount REAL, buy_price REAL, notes TEXT,
                            added_date TEXT DEFAULT CURRENT_TIMESTAMP)''')
            conn.executemany('INSERT INTO portfolio (user_id, coin_symbol, amount, buy_price) VALUES (?,?,?,?)',
                             [(1, 'BTC', 0.5, 35000), (1, 'ETH', 2, 1800), (1, 'SOL', 10, 100), (1, 'PI', 1600, 0.1)])
        db = Database(path)
        rows = {r['coin_symbol']: r for r in db.get_user_portfolio(1)}
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows['BTC']['provider_id'], 'bitcoin')
        self.assertEqual(rows['ETH']['provider_id'], 'ethereum')
        self.assertEqual(rows['SOL']['provider_id'], 'solana')
        self.assertIsNone(rows['PI']['provider_id'], "eski sabit tabloda olmayanlar çözümleyiciye bırakılır")
        self.assertEqual((rows['PI']['amount'], rows['PI']['buy_price']), (1600, 0.1))

        # Migration tekrar çalıştırılabilir olmalı
        Database(path)

        resolver = AssetResolver(db, FakeProvider())
        self.assertEqual(resolver.resolve(rows['PI']['coin_symbol']).asset.provider_id, 'pi-network')


class AddCommandParsingTests(unittest.TestCase):
    def test_parse(self):
        from bot.handlers.portfolio import parse_add_command
        self.assertEqual(parse_add_command("ekle PI 100"), ("PI", 100, None))
        self.assertEqual(parse_add_command("EKLE KRİPTO BTC 0.5 35000"), ("BTC", 0.5, 35000))
        self.assertEqual(parse_add_command("ekle kripto btc 0,5 35000"), ("btc", 0.5, 35000))
        self.assertEqual(parse_add_command("ekle Pi Network 100 0.08"), ("Pi Network", 100, 0.08))
        self.assertEqual(parse_add_command("ekle pi-network 100"), ("pi-network", 100, None))
        self.assertIsInstance(parse_add_command("ekle btc"), str)
        self.assertIsInstance(parse_add_command("ekle 100"), str)
        self.assertIsInstance(parse_add_command("ekle btc -1"), str)


@unittest.skipUnless(os.getenv("RUN_LIVE_TESTS") == "1", "RUN_LIVE_TESTS=1 ile gerçek CoinGecko'ya karşı çalışır")
class LiveCoinGeckoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = Database(os.path.join(tempfile.mkdtemp(), "live.db"))
        cls.resolver = AssetResolver(cls.db, CoinGeckoProvider())

    def test_pi_variants_live(self):
        for text in ["PI", "pi", "Pi", "Pi Network", "pi network", "pi-network"]:
            with self.subTest(input=text):
                result = self.resolver.resolve(text)
                self.assertEqual(result.status, "resolved", result)
                self.assertEqual((result.asset.name, result.asset.symbol, result.asset.provider_id),
                                 ("Pi Network", "PI", "pi-network"))

    def test_majors_live(self):
        for text, expected in MajorAssetTests.CASES.items():
            with self.subTest(input=text):
                self.assertEqual(self.resolver.resolve(text).asset.provider_id, expected)

    def test_unknown_live(self):
        self.assertEqual(self.resolver.resolve("THISCOINDOESNOTEXIST").status, "not_found")

    def test_pi_price_live(self):
        prices = CoinGeckoProvider().prices(["pi-network"])
        self.assertGreater(prices.get("pi-network", 0), 0)


if __name__ == "__main__":
    unittest.main()
