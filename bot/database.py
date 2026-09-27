import sqlite3
import os
from datetime import datetime
from bot.config import DATABASE_PATH, DEFAULT_TIMEZONE

# Eski sürümün sabit sembol -> CoinGecko ID tablosu. Sadece migration sırasında,
# daha önce eklenmiş kayıtların anlamını korumak için kullanılır. Yeni varlıklar
# AssetResolver ile dinamik olarak çözülür.
LEGACY_SYMBOL_IDS = {
    'BTC': 'bitcoin', 'ETH': 'ethereum', 'BNB': 'binancecoin', 'XRP': 'ripple',
    'ADA': 'cardano', 'SOL': 'solana', 'DOT': 'polkadot', 'DOGE': 'dogecoin',
    'AVAX': 'avalanche-2', 'MATIC': 'matic-network', 'LTC': 'litecoin', 'LINK': 'chainlink',
    'ATOM': 'cosmos', 'ETC': 'ethereum-classic', 'XLM': 'stellar', 'BCH': 'bitcoin-cash',
    'FIL': 'filecoin', 'EOS': 'eos', 'XTZ': 'tezos', 'AAVE': 'aave',
}

class Database:
    def __init__(self, db_path: str = None):
        # Eğer db_path verilmezse, config'deki yol kullanılır
        self.db_path = db_path or DATABASE_PATH
        
        # Veritabanı dizinini oluştur
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.init_db()
    
    def init_db(self):
        """Veritabanını ve tabloları oluşturur"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Kullanıcı mesaj istatistikleri tablosu
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_messages (
                        user_id INTEGER,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        message_count INTEGER DEFAULT 0,
                        last_message_date TEXT,
                        PRIMARY KEY (user_id)
                    )
                ''')
                
                # Grup mesaj istatistikleri tablosu
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS group_messages (
                        group_id INTEGER,
                        group_title TEXT,
                        message_count INTEGER DEFAULT 0,
                        last_message_date TEXT,
                        PRIMARY KEY (group_id)
                    )
                ''')
                
                # Global istatistikler tablosu
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS global_stats (
                        key TEXT PRIMARY KEY,
                        value INTEGER DEFAULT 0
                    )
                ''')
                
                # Portföy tablosu
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS portfolio (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        coin_symbol TEXT,
                        amount REAL,
                        buy_price REAL,
                        notes TEXT,
                        added_date TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Alarm tablosu
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS price_alerts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        coin_symbol TEXT,
                        alert_type TEXT,  -- 'above', 'below', 'change'
                        target_price REAL,
                        current_price REAL,
                        is_active INTEGER DEFAULT 1,
                        created_date TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Portföy geçmişi tablosu (raporlar için)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS portfolio_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        total_value REAL,
                        profit_loss REAL,
                        date TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Rapor ayarları tablosu
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS report_settings (
                        user_id INTEGER PRIMARY KEY,
                        daily_report INTEGER DEFAULT 0,
                        weekly_report INTEGER DEFAULT 0,
                        report_time TEXT DEFAULT '09:00',
                        timezone TEXT DEFAULT 'Europe/Istanbul'
                    )
                ''')

                # Kripto varlık kataloğu (sağlayıcıdan senkronize edilir)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS crypto_assets (
                        provider_id TEXT PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        name TEXT NOT NULL,
                        symbol_lc TEXT NOT NULL,
                        name_lc TEXT NOT NULL,
                        market_cap_rank INTEGER,
                        last_updated TEXT NOT NULL
                    )
                ''')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_crypto_assets_symbol ON crypto_assets(symbol_lc)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_crypto_assets_name ON crypto_assets(name_lc)')

                # Çözümlenmiş sorgu -> sağlayıcı ID eşlemeleri (user_id=0: herkes için)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS asset_aliases (
                        alias TEXT NOT NULL,
                        user_id INTEGER NOT NULL DEFAULT 0,
                        provider_id TEXT NOT NULL,
                        source TEXT NOT NULL,  -- 'seed', 'auto', 'user'
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (alias, user_id)
                    )
                ''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS meta (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                ''')

                self._migrate_asset_columns(cursor)

                conn.commit()
                print(f"✅ Veritabanı başlatıldı: {self.db_path}")
        except Exception as e:
            print(f"❌ Veritabanı başlatma hatası: {e}")

    def _migrate_asset_columns(self, cursor):
        """portfolio ve price_alerts tablolarına sağlayıcı ID kolonlarını ekler (veri kaybı olmadan).

        Eski kayıtlar sadece sembol içerir. Eski kodun sabit sembol tablosunda bulunan
        semboller aynı ID ile doldurulur (davranış korunur); diğerleri NULL kalır ve
        ilk kullanımda AssetResolver ile çözülür.
        """
        def columns(table):
            cursor.execute(f'PRAGMA table_info({table})')
            return {row[1] for row in cursor.fetchall()}

        if 'provider_id' not in columns('portfolio'):
            cursor.execute('ALTER TABLE portfolio ADD COLUMN provider_id TEXT')
        if 'asset_name' not in columns('portfolio'):
            cursor.execute('ALTER TABLE portfolio ADD COLUMN asset_name TEXT')
        if 'provider_id' not in columns('price_alerts'):
            cursor.execute('ALTER TABLE price_alerts ADD COLUMN provider_id TEXT')

        for table in ('portfolio', 'price_alerts'):
            for symbol, provider_id in LEGACY_SYMBOL_IDS.items():
                cursor.execute(
                    f'UPDATE {table} SET provider_id = ? WHERE provider_id IS NULL AND UPPER(coin_symbol) = ?',
                    (provider_id, symbol)
                )

    # KRİPTO VARLIK KATALOĞU
    def upsert_assets(self, assets: list, replace_rank: bool = False):
        """Varlıkları ekler/günceller. assets: [{'provider_id','symbol','name', 'market_cap_rank'?}]"""
        now = datetime.now().isoformat()
        rows = [
            (a['provider_id'], a['symbol'].upper(), a['name'], a['symbol'].lower(), a['name'].lower(),
             a.get('market_cap_rank'), now)
            for a in assets if a.get('provider_id') and a.get('symbol') and a.get('name')
        ]
        rank_update = "excluded.market_cap_rank" if replace_rank else \
            "COALESCE(excluded.market_cap_rank, crypto_assets.market_cap_rank)"
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(f'''
                INSERT INTO crypto_assets (provider_id, symbol, name, symbol_lc, name_lc, market_cap_rank, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET
                    symbol = excluded.symbol,
                    name = excluded.name,
                    symbol_lc = excluded.symbol_lc,
                    name_lc = excluded.name_lc,
                    market_cap_rank = {rank_update},
                    last_updated = excluded.last_updated
            ''', rows)
            conn.commit()
        return len(rows)

    def set_ranks(self, ranks: dict):
        """Tüm sıralamaları verilen {provider_id: rank} ile değiştirir (listede olmayanlar NULL olur)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('UPDATE crypto_assets SET market_cap_rank = NULL WHERE market_cap_rank IS NOT NULL')
            conn.executemany('UPDATE crypto_assets SET market_cap_rank = ? WHERE provider_id = ?',
                             [(rank, pid) for pid, rank in ranks.items()])
            conn.commit()

    def _asset_rows(self, cursor):
        return [
            {'provider_id': r[0], 'symbol': r[1], 'name': r[2], 'market_cap_rank': r[3]}
            for r in cursor.fetchall()
        ]

    def get_asset(self, provider_id: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT provider_id, symbol, name, market_cap_rank FROM crypto_assets WHERE provider_id = ?',
                (provider_id,)
            )
            rows = self._asset_rows(cursor)
            return rows[0] if rows else None

    def find_assets_exact(self, provider_id: str, name_lc: str, symbol_lc: str, limit: int = 50):
        """ID, isim veya sembolü tam eşleşen varlıklar (ID eşleşmesi önce)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT provider_id, symbol, name, market_cap_rank FROM crypto_assets
                WHERE provider_id = ? OR name_lc = ? OR symbol_lc = ?
                ORDER BY (provider_id = ?) DESC, (name_lc = ?) DESC,
                         market_cap_rank IS NULL, market_cap_rank
                LIMIT ?
            ''', (provider_id, name_lc, symbol_lc, provider_id, name_lc, limit))
            return self._asset_rows(cursor)

    def count_assets(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute('SELECT COUNT(*) FROM crypto_assets').fetchone()[0]

    # ALIAS (sorgu -> sağlayıcı ID) METODLARI
    def get_aliases(self, alias: str, user_id: int = 0):
        """Önce kullanıcıya özel, sonra genel alias kayıtları"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, provider_id, source, updated_at FROM asset_aliases
                WHERE alias = ? AND user_id IN (?, 0)
                ORDER BY user_id DESC
            ''', (alias, user_id or 0))
            return [
                {'user_id': r[0], 'provider_id': r[1], 'source': r[2], 'updated_at': r[3]}
                for r in cursor.fetchall()
            ]

    def set_alias(self, alias: str, provider_id: str, source: str, user_id: int = 0):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO asset_aliases (alias, user_id, provider_id, source, updated_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (alias, user_id or 0, provider_id, source, datetime.now().isoformat()))
            conn.commit()

    def delete_alias(self, alias: str, user_id: int = 0):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM asset_aliases WHERE alias = ? AND user_id = ?', (alias, user_id or 0))
            conn.commit()

    # META (anahtar/değer)
    def get_meta(self, key: str):
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute('SELECT value FROM meta WHERE key = ?', (key,)).fetchone()
            return row[0] if row else None

    def set_meta(self, key: str, value: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', (key, str(value)))
            conn.commit()

    def add_user(self, user_id: int, username: str, first_name: str, last_name: str):
        """Kullanıcıyı ekler veya bilgilerini günceller (mesaj sayısını değiştirmez)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO user_messages (user_id, username, first_name, last_name, message_count, last_message_date)
                VALUES (?, ?, ?, ?, 0, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name
            ''', (user_id, username or "", first_name or "", last_name or "", datetime.now().isoformat()))
            conn.commit()

    def get_all_user_ids(self) -> list:
        """Tüm kullanıcı ID'lerini getirir"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM user_messages')
            return [row[0] for row in cursor.fetchall()]

    def get_bot_summary(self) -> dict:
        """Admin paneli için genel sayılar"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            today = datetime.now().date().isoformat()

            def scalar(query, params=()):
                cursor.execute(query, params)
                row = cursor.fetchone()
                return (row[0] or 0) if row else 0

            return {
                'total_users': scalar('SELECT COUNT(*) FROM user_messages'),
                'active_today': scalar('SELECT COUNT(*) FROM user_messages WHERE substr(last_message_date, 1, 10) = ?', (today,)),
                'total_messages': scalar("SELECT value FROM global_stats WHERE key = 'total_messages'"),
                'total_groups': scalar('SELECT COUNT(*) FROM group_messages'),
                'portfolio_items': scalar('SELECT COUNT(*) FROM portfolio'),
                'active_alerts': scalar('SELECT COUNT(*) FROM price_alerts WHERE is_active = 1'),
            }

    def get_recent_users(self, limit: int = 10) -> list:
        """Son aktif kullanıcıları getirir"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, first_name, username, message_count
                FROM user_messages
                ORDER BY last_message_date DESC
                LIMIT ?
            ''', (limit,))
            return cursor.fetchall()

    def add_message(self, user_id: int, username: str, first_name: str, last_name: str, 
                   group_id: int = None, group_title: str = None):
        """Mesaj istatistiklerini günceller"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            current_date = datetime.now().isoformat()
            
            # Kullanıcı istatistiklerini güncelle
            cursor.execute('''
                INSERT OR REPLACE INTO user_messages 
                (user_id, username, first_name, last_name, message_count, last_message_date)
                VALUES (?, ?, ?, ?, 
                        COALESCE((SELECT message_count FROM user_messages WHERE user_id = ?), 0) + 1,
                        ?)
            ''', (user_id, username, first_name, last_name, user_id, current_date))
            
            # Grup istatistiklerini güncelle (eğer grup mesajı ise)
            if group_id and group_title:
                cursor.execute('''
                    INSERT OR REPLACE INTO group_messages 
                    (group_id, group_title, message_count, last_message_date)
                    VALUES (?, ?, 
                            COALESCE((SELECT message_count FROM group_messages WHERE group_id = ?), 0) + 1,
                            ?)
                ''', (group_id, group_title, group_id, current_date))
            
            # Global mesaj sayacını güncelle
            cursor.execute('''
                INSERT OR REPLACE INTO global_stats (key, value)
                VALUES ('total_messages', 
                        COALESCE((SELECT value FROM global_stats WHERE key = 'total_messages'), 0) + 1)
            ''')
            
            conn.commit()

    def get_user_stats(self, user_id: int) -> dict:
        """Kullanıcı istatistiklerini getirir"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT message_count, last_message_date FROM user_messages WHERE user_id = ?',
                (user_id,)
            )
            result = cursor.fetchone()
            
            if result:
                return {
                    'message_count': result[0],
                    'last_message_date': result[1]
                }
            return {'message_count': 0, 'last_message_date': None}

    def get_group_stats(self, group_id: int) -> dict:
        """Grup istatistiklerini getirir"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT message_count, last_message_date FROM group_messages WHERE group_id = ?',
                (group_id,)
            )
            result = cursor.fetchone()
            
            if result:
                return {
                    'message_count': result[0],
                    'last_message_date': result[1]
                }
            return {'message_count': 0, 'last_message_date': None}

    def get_global_stats(self) -> dict:
        """Global istatistikleri getirir"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT key, value FROM global_stats')
            results = cursor.fetchall()
            
            stats = {}
            for key, value in results:
                stats[key] = value
            
            return stats

    def get_top_users(self, limit: int = 10) -> list:
        """En aktif kullanıcıları getirir"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, username, first_name, message_count 
                FROM user_messages 
                ORDER BY message_count DESC 
                LIMIT ?
            ''', (limit,))
            
            return cursor.fetchall()

    # PORTFÖY METODLARI
    def get_user_portfolio(self, user_id: int):
        """Kullanıcının portföyünü getirir"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, coin_symbol, amount, buy_price, notes, provider_id, asset_name FROM portfolio WHERE user_id = ?',
                (user_id,)
            )
            
            portfolio = []
            for row in cursor.fetchall():
                portfolio.append({
                    'id': row[0],
                    'coin_symbol': row[1],
                    'amount': row[2],
                    'buy_price': row[3],
                    'notes': row[4],
                    'provider_id': row[5],
                    'asset_name': row[6]
                })
            return portfolio

    def add_to_portfolio(self, user_id: int, coin_symbol: str, amount: float, buy_price: float, notes: str = "",
                         provider_id: str = None, asset_name: str = None):
        """Portföye coin ekler (provider_id: sağlayıcının kesin varlık ID'si, ör. 'pi-network')"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO portfolio (user_id, coin_symbol, amount, buy_price, notes, provider_id, asset_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, coin_symbol.upper(), amount, buy_price, notes, provider_id, asset_name))
            conn.commit()
            return cursor.lastrowid

    def set_portfolio_asset(self, portfolio_id: int, provider_id: str, symbol: str, asset_name: str):
        """Eski (sadece sembollü) kaydı çözümlenen varlığa bağlar"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                'UPDATE portfolio SET provider_id = ?, coin_symbol = ?, asset_name = ? WHERE id = ?',
                (provider_id, symbol.upper(), asset_name, portfolio_id)
            )
            conn.commit()

    def remove_from_portfolio(self, user_id: int, portfolio_id: int):
        """Portföyden coin çıkarır"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM portfolio WHERE id = ? AND user_id = ?', (portfolio_id, user_id))
            conn.commit()
            return cursor.rowcount > 0

    def update_portfolio(self, portfolio_id: int, amount: float = None, buy_price: float = None, notes: str = None):
        """Portföy öğesini günceller"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if amount is not None:
                updates.append("amount = ?")
                params.append(amount)
            if buy_price is not None:
                updates.append("buy_price = ?")
                params.append(buy_price)
            if notes is not None:
                updates.append("notes = ?")
                params.append(notes)
            
            if updates:
                params.append(portfolio_id)
                cursor.execute(f'UPDATE portfolio SET {", ".join(updates)} WHERE id = ?', params)
                conn.commit()
                return cursor.rowcount > 0
            return False

    # ALARM METODLARI
    def create_alert(self, user_id: int, coin_symbol: str, alert_type: str, target_price: float, current_price: float,
                     provider_id: str = None):
        """Yeni alarm oluşturur"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO price_alerts 
                (user_id, coin_symbol, alert_type, target_price, current_price, provider_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, coin_symbol.upper(), alert_type, target_price, current_price, provider_id))
            conn.commit()
            return cursor.lastrowid

    def get_user_alerts(self, user_id: int):
        """Kullanıcının alarmlarını getirir"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, coin_symbol, alert_type, target_price, is_active, created_date, provider_id
                FROM price_alerts 
                WHERE user_id = ?
                ORDER BY created_date DESC
            ''', (user_id,))
            
            alerts = []
            for row in cursor.fetchall():
                alerts.append({
                    'id': row[0],
                    'coin_symbol': row[1],
                    'alert_type': row[2],
                    'target_price': row[3],
                    'is_active': bool(row[4]),
                    'created_date': row[5],
                    'provider_id': row[6]
                })
            return alerts

    def get_active_alerts(self):
        """Aktif tüm alarmları getirir"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, user_id, coin_symbol, alert_type, target_price, current_price, provider_id
                FROM price_alerts 
                WHERE is_active = 1
            ''')
            
            alerts = []
            for row in cursor.fetchall():
                alerts.append({
                    'id': row[0],
                    'user_id': row[1],
                    'coin_symbol': row[2],
                    'alert_type': row[3],
                    'target_price': row[4],
                    'current_price': row[5],
                    'provider_id': row[6]
                })
            return alerts

    def set_alert_asset(self, alert_id: int, provider_id: str):
        """Eski (sadece sembollü) alarmı çözümlenen varlığa bağlar"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('UPDATE price_alerts SET provider_id = ? WHERE id = ?', (provider_id, alert_id))
            conn.commit()

    def deactivate_alert(self, alert_id: int):
        """Alarmı pasif yapar"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE price_alerts 
                SET is_active = 0 
                WHERE id = ?
            ''', (alert_id,))
            conn.commit()

    def delete_alert(self, alert_id: int, user_id: int):
        """Alarmı siler"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM price_alerts WHERE id = ? AND user_id = ?', (alert_id, user_id))
            conn.commit()
            return cursor.rowcount > 0

    def delete_all_alerts(self, user_id: int):
        """Kullanıcının tüm alarmlarını siler"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM price_alerts WHERE user_id = ?', (user_id,))
            conn.commit()
            return cursor.rowcount

    # RAPORLAMA METODLARI
    def save_portfolio_history(self, user_id: int, total_value: float, profit_loss: float):
        """Portföy geçmişini kaydeder"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO portfolio_history 
                (user_id, total_value, profit_loss)
                VALUES (?, ?, ?)
            ''', (user_id, total_value, profit_loss))
            conn.commit()

    def get_portfolio_history(self, user_id: int, days: int = 7):
        """Portföy geçmişini getirir"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT date, total_value, profit_loss 
                FROM portfolio_history 
                WHERE user_id = ? 
                AND date >= datetime('now', ?)
                ORDER BY date DESC
            ''', (user_id, f'-{days} days'))
            
            history = []
            for row in cursor.fetchall():
                history.append({
                    'date': row[0],
                    'total_value': row[1],
                    'profit_loss': row[2]
                })
            return history

    def get_value_before(self, user_id: int, hours: int):
        """En az `hours` saat önce kaydedilmiş en yeni portföy değerini getirir"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT total_value
                FROM portfolio_history
                WHERE user_id = ?
                AND date <= datetime('now', ?)
                ORDER BY date DESC
                LIMIT 1
            ''', (user_id, f'-{hours} hours'))
            row = cursor.fetchone()
            return row[0] if row else None

    def get_report_settings(self, user_id: int):
        """Rapor ayarlarını getirir"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT daily_report, weekly_report, report_time, timezone
                FROM report_settings 
                WHERE user_id = ?
            ''', (user_id,))
            
            result = cursor.fetchone()
            if result:
                return {
                    'daily_report': bool(result[0]),
                    'weekly_report': bool(result[1]),
                    'report_time': result[2],
                    'timezone': result[3]
                }
            
            # Eğer ayar yoksa, varsayılan değerlerle kaydet
            cursor.execute('''
                INSERT INTO report_settings 
                (user_id, daily_report, weekly_report, report_time, timezone)
                VALUES (?, 0, 0, '09:00', ?)
            ''', (user_id, DEFAULT_TIMEZONE))
            conn.commit()
            
            return {
                'daily_report': False,
                'weekly_report': False, 
                'report_time': '09:00',
                'timezone': DEFAULT_TIMEZONE
            }

    def update_report_settings(self, user_id: int, daily_report: bool = None, weekly_report: bool = None, 
                             report_time: str = None, timezone: str = None):
        """Rapor ayarlarını günceller"""
        # Mevcut ayarları al (ayrı bağlantıda, varsayılanları oluşturur)
        current = self.get_report_settings(user_id)

        if daily_report is not None:
            current['daily_report'] = daily_report
        if weekly_report is not None:
            current['weekly_report'] = weekly_report
        if report_time is not None:
            current['report_time'] = report_time
        if timezone is not None:
            current['timezone'] = timezone

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO report_settings 
                (user_id, daily_report, weekly_report, report_time, timezone)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, int(current['daily_report']), int(current['weekly_report']), 
                  current['report_time'], current['timezone']))
            conn.commit()
        return current

    def get_users_with_daily_reports(self):
        """Günlük rapor aktif olan kullanıcıları getirir"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, report_time, timezone
                FROM report_settings 
                WHERE daily_report = 1
            ''')
            
            users = []
            for row in cursor.fetchall():
                users.append({
                    'user_id': row[0],
                    'report_time': row[1],
                    'timezone': row[2]
                })
            return users

    def get_users_with_weekly_reports(self):
        """Haftalık rapor aktif olan kullanıcıları getirir"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, report_time, timezone
                FROM report_settings 
                WHERE weekly_report = 1
            ''')
            
            users = []
            for row in cursor.fetchall():
                users.append({
                    'user_id': row[0],
                    'report_time': row[1],
                    'timezone': row[2]
                })
            return users

# Global database instance
db = Database()