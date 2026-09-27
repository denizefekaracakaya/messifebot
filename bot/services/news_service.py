# bot/services/news_service.py
import requests
import json
import aiohttp
import asyncio
from datetime import datetime, timedelta
import os

class NewsService:
    def __init__(self):
        self.sources = {
            'borsa': {
                'name': 'Borsa Haberleri',
                'keywords': ['borsa', 'hisse', 'dolar', 'euro', 'altın', 'bitcoin', 'kripto', 'bist', 'yatırım', 'piyasa']
            },
            'ekonomi': {
                'name': 'Ekonomi Haberleri', 
                'keywords': ['ekonomi', 'finans', 'bankacılık', 'yatırım', 'şirket', 'kâr', 'zarar', 'büyüme']
            }
        }
    
    async def get_news_from_api(self, category='borsa'):
        """API'den haberleri çek"""
        try:
            # Örnek API - gerçek API key alabilirsin
            news_data = await self._get_sample_news(category)
            return news_data
            
        except Exception as e:
            print(f"❌ Haber API hatası: {e}")
            return await self._get_fallback_news(category)
    
    async def _get_sample_news(self, category):
        """Örnek haber verisi (gerçek API entegre edene kadar)"""
        # Burada gerçek API entegrasyonu yapılabilir
        # Örnek: NewsAPI, Alpha Vantage, Financial Modeling Prep vb.
        
        sample_news = {
            'borsa': [
                {
                    'title': 'BIST 100 Endeksi Rekor Kırdı',
                    'description': 'BIST 100 endeksi tarihi zirvesini güncelledi. Yatırımcılar teknoloji hisselerine yoğun ilgi gösteriyor.',
                    'source': 'Finans Haber',
                    'published_at': datetime.now().strftime('%d.%m.%Y %H:%M'),
                    'url': '#',
                    'importance': 'high'
                },
                {
                    'title': 'Dolar/TL Piyasası Hareketli',
                    'description': 'Dolar/TL kuru son 24 saatte dalgalı seyretti. Merkez Bankası faiz kararı piyasaları bekliyor.',
                    'source': 'Piyasa Takip',
                    'published_at': (datetime.now() - timedelta(hours=2)).strftime('%d.%m.%Y %H:%M'),
                    'url': '#',
                    'importance': 'medium'
                },
                {
                    'title': 'Altın Yatırımcıları Dikkat',
                    'description': 'Altın fiyatları küresel ekonomik belirsizlikle yükselişte. Analistler 1800$ seviyesini hedefliyor.',
                    'source': 'Altın Rapor',
                    'published_at': (datetime.now() - timedelta(hours=5)).strftime('%d.%m.%Y %H:%M'),
                    'url': '#',
                    'importance': 'high'
                },
                {
                    'title': 'Teknoloji Hisseleri Yükselişte',
                    'description': 'NASDAQ endeksi teknoloji hisseleriyle yükseldi. Yapay zeka şirketleri yatırımcıların gözdesi oldu.',
                    'source': 'Teknoloji Borsası',
                    'published_at': (datetime.now() - timedelta(hours=1)).strftime('%d.%m.%Y %H:%M'),
                    'url': '#',
                    'importance': 'medium'
                },
                {
                    'title': 'Kripto Piyasası Hareketlendi',
                    'description': 'Bitcoin 35.000$ seviyesini test etti. Ethereum ve diğer altcoinler de yükselişe geçti.',
                    'source': 'Kripto Gündem',
                    'published_at': (datetime.now() - timedelta(hours=3)).strftime('%d.%m.%Y %H:%M'),
                    'url': '#',
                    'importance': 'medium'
                }
            ],
            'ekonomi': [
                {
                    'title': 'Merkez Bankası Faiz Kararı Açıklandı',
                    'description': 'TCMB politika faizini beklenen seviyede tuttu. Enflasyon hedefi doğrultusunda karar alındı.',
                    'source': 'Ekonomi Bülteni',
                    'published_at': datetime.now().strftime('%d.%m.%Y %H:%M'),
                    'url': '#',
                    'importance': 'high'
                },
                {
                    'title': 'Şirket Kârları Beklentileri Aştı',
                    'description': 'Borsada işlem gören şirketlerin üçüncü çeyrek kârları analist beklentilerinin üzerinde gerçekleşti.',
                    'source': 'Şirket Haberleri',
                    'published_at': (datetime.now() - timedelta(hours=4)).strftime('%d.%m.%Y %H:%M'),
                    'url': '#',
                    'importance': 'medium'
                }
            ]
        }
        
        return sample_news.get(category, [])
    
    async def _get_fallback_news(self, category):
        """API çalışmazsa yedek haberler"""
        return [
            {
                'title': f'{self.sources[category]["name"]} - Sistem Güncellemesi',
                'description': 'Haber servisi şu anda güncelleniyor. Kısa süre içinde en güncel borsa haberleri burada olacak.',
                'source': 'Sistem',
                'published_at': datetime.now().strftime('%d.%m.%Y %H:%M'),
                'url': '#',
                'importance': 'info'
            }
        ]
    
    def format_news_message(self, news_items, category='borsa'):
        """Haberleri formatla"""
        if not news_items:
            return "📭 Şu anda haber bulunmuyor."
        
        source_name = self.sources.get(category, {}).get('name', 'Haberler')
        
        message = f"📈 **{source_name}**\n\n"
        message += f"⏰ Son Güncelleme: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        
        for i, news in enumerate(news_items[:5], 1):  # İlk 5 haber
            importance_emoji = "🔴" if news.get('importance') == 'high' else "🟡" if news.get('importance') == 'medium' else "🔵"
            
            message += f"{importance_emoji} **{news['title']}**\n"
            message += f"📝 {news['description']}\n"
            message += f"📰 Kaynak: {news['source']}\n"
            message += f"🕐 {news['published_at']}\n"
            
            if i < len(news_items[:5]):
                message += "─" * 30 + "\n\n"
        
        message += f"\n📊 Toplam {len(news_items)} haber listeleniyor."
        return message
    
    async def get_news_summary(self, category='borsa'):
        """Haber özeti oluştur"""
        news_items = await self.get_news_from_api(category)
        
        if not news_items:
            return "❌ Haberler alınamadı. Lütfen daha sonra tekrar deneyin."
        
        # Önem sırasına göre sırala
        importance_order = {'high': 3, 'medium': 2, 'low': 1, 'info': 0}
        news_items.sort(key=lambda x: importance_order.get(x.get('importance', 'low'), 0), reverse=True)
        
        return self.format_news_message(news_items, category)

# Global news service instance
news_service = NewsService()