# SMT Bot

Webhook-mottaker for TradingView-varsler. Kjoerer paa Render (Oregon) med PostgreSQL.

## Endepunkter
- `GET /health` - sjekker at tjenesten og databasen lever
- `POST /webhook/tradingview` - tar imot JSON fra TradingView
- `GET /signals?key=<WEBHOOK_SECRET>` - viser siste lagrede signaler
- `POST /telegram/webhook` - tar imot knappetrykk og kommandoer fra Telegram

## Telegram
Sett `TELEGRAM_BOT_TOKEN` i Render. Foerste chat som sender `/start` til boten blir eier
(eller sett `TELEGRAM_CHAT_ID`). Hvert signal sendes dit med APPROVE/REJECT; valget lagres
i `status` og `decided_at`. `/siste` viser de 5 siste signalene.

## JSON-format fra TradingView
```json
{
  "secret": "<WEBHOOK_SECRET>",
  "instrument": "{{ticker}}",
  "indicator": "SMT-test",
  "signal": "BUY",
  "price": "{{close}}",
  "timeframe": "{{interval}}",
  "time": "{{timenow}}"
}
```

## Struktur
- `app/main.py` - API og sikkerhet (secret, IP-allowlist)
- `app/signals.py` - signalbehandling og lagring
- `app/telegram_bot.py` - Telegram-varsler og APPROVE/REJECT
- `app/models.py` - databasetabeller
- `app/db.py`, `app/config.py` - oppsett
- `render.yaml` - oppretter web-tjeneste og database paa Render
