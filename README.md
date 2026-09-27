# Telegram Bot

This is a simple Telegram bot built with Python using the python-telegram-bot library.

## Installation

1. Clone the repository.
2. Create a virtual environment and install the dependencies:
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
3. Create a `.env` file in this folder (next to `requirements.txt`) from `.env.example`:
   - `BOT_TOKEN` – your Telegram bot token
   - `ADMIN_IDS` – comma-separated Telegram user IDs allowed to use `/admin` (send `/id` to the bot to see yours)
   - `NEWSAPI_KEY`, `GNEWS_API_KEY`, `NEWSDATA_API_KEY` – optional; at least one is needed for `/news`, `/economy`, `/cryptonews`
   - `CRYPTOCOMPARE_API_KEY` – optional, used first for `/cryptonews`
4. Run the bot from this folder:
   ```
   .venv\Scripts\python -m bot.main
   ```

Data is stored in `data/chat_stats.db`.

## Crypto assets

Coins are identified by their CoinGecko ID (e.g. `pi-network`), never by ticker alone, because tickers are not unique.
User input such as `PI`, `Pi Network` or `pi-network` is resolved by `bot/services/asset_resolver.py`:

1. normalize the input
2. look up cached aliases (per-user selections, then global auto-resolutions with a 7-day TTL)
3. exact id/name/symbol match in the local asset catalog (`crypto_assets`, synced daily from CoinGecko `/coins/list`)
4. fall back to CoinGecko `/search` for newly listed coins
5. if several coins match, pick one only when it clearly dominates by market-cap rank; otherwise ask the user to choose

Commands: `/searchcrypto PI`, `/price Pi Network`, `EKLE PI 100 [price]`, `/alert pi < 0.05`.

## Conversation

Free-text messages (not commands) are handled by a rule-based conversation layer. There is no LLM and no extra dependency.

- **Routing priority:**
  - group -1: statistics (never replies)
  - group 0: commands, inline-button callbacks, `EKLE …` portfolio syntax
  - group 1: conversation, only for messages nothing else took
- **Private chats:** the bot answers every message.
- **Groups:** it answers only when @mentioned or replied to. This also applies to `EKLE`.
- **Pipeline:** `services/text_normalizer.py` (Turkish-aware normalization) → `services/intents.py` (intent + coin/amount/target extraction) → `services/conversation_engine.py` (context + read-only actions) → `services/responses.py` (HTML replies).
- **Services:** the engine reaches app services only through `services/conversation_actions.py`, which is read-only. Data-changing requests (e.g. *btc 100000'i geçerse haber ver*) are shown with a Confirm button and executed only after confirmation. Portfolio deletion is never done from chat.
- **Context:** kept in memory per (chat, user). It lasts 10 minutes, keeps the last 6 intents, and message text is not stored. It enables follow-ups like *btc kaç?* → *24 saatte?* / *peki ethereum?* / *20 tane alsam?*
- **Anti-spam:** repeated identical messages within 30s are ignored. Limits are 6 replies per 30s per user and 10 replies per minute per group. Bot accounts are ignored.
- **Future LLM:** `ConversationEngine(fallback_provider=...)` can plug one in for unknown messages only. It gets no tool or database access.

## Tests

```
.venv\Scripts\python -m unittest discover -s tests -v
```

Set `RUN_LIVE_TESTS=1` to also run the acceptance tests against the real CoinGecko API.
