# bot/services/assets.py
"""Uygulama genelinde kullanılan varlık çözümleyici örneği"""
from bot.database import db
from bot.services.asset_resolver import AssetResolver
from bot.services.crypto_service import crypto_service

asset_resolver = AssetResolver(db, crypto_service.provider)
