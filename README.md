# SMT Bot

Webhook-mottaker for TradingView-varsler. Kjoerer paa Render (Oregon) med PostgreSQL.

## Endepunkter
- `GET /health` - sjekker at tjenesten og databasen lever
- `POST /webhook/tradingview` - tar imot JSON fra TradingView
- `GET /signals?key=<WEBHOOK_SECRET>` - viser siste lagrede signaler

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
- `app/models.py` - databasetabeller
- `app/db.py`, `app/config.py` - oppsett
- `render.yaml` - oppretter web-tjeneste og database paa Render
