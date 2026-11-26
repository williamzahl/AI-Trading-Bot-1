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

## Ordre til MetaTrader 5 (MetaApi.cloud)
Naar du trykker APPROVE i Telegram sendes en markedsordre til MT5-kontoen via
MetaApi.cloud, og resultatet kommer som svar i Telegram. Alt kjoerer i skyen.

| Miljoevariabel | Standard | Betydning |
|---|---|---|
| `EXECUTION_ENABLED` | `off` | Noedstopp. Maa vaere `on` for at noe sendes |
| `METAAPI_TOKEN` | - | API-token fra metaapi.cloud (hemmelig) |
| `METAAPI_ACCOUNT_ID` | - | Konto-ID fra metaapi.cloud |
| `METAAPI_REGION` | auto | Settes bare hvis auto-oppslag feiler |
| `TRADE_LOT` | `0.1` | Fast lot per ordre |
| `STOP_LOSS_PCT` | `0.25` | SL-avstand i % av prisen |
| `TAKE_PROFIT_PCT` | `0.5` | TP-avstand i % av prisen |
| `MAX_OPEN_POSITIONS` | `1` | Ingen ny ordre hvis flere er aapne |
| `MAX_SIGNAL_AGE_MIN` | `15` | Ingen ordre paa gamle signaler |
| `ALLOWED_SYMBOLS` | `NAS100,US500` | Kun disse handles |
| `MT5_SYMBOL_SUFFIX` | tom | F.eks. `.a` hvis megleren bruker suffiks |

Telegram: `/status` (konto og posisjoner), `/stopp` (pause), `/handel_paa`.

## Alternativ: EA paa MetaQuotes VPS (`EXECUTION_MODE=ea`)
I stedet for MetaApi kan MT5 selv hente ordrene. EA-en `mt5/SMT_Render_Bridge.mq5`
spoer `GET /mt5/next?key=<MT5_EA_KEY>` hvert 3. sekund, utfoerer ordren med SL/TP og
melder svaret til `POST /mt5/result`. Svaret kommer i Telegram. Kjoer MT5 med EA-en paa
MetaQuotes VPS (Navigator > VPS), saa trengs ikke PC-en.

| Miljoevariabel | Betydning |
|---|---|
| `EXECUTION_MODE` | `metaapi` (standard) eller `ea` |
| `MT5_EA_KEY` | Egen hemmelig noekkel som limes inn i EA-en |

`/status` i Telegram viser naar EA-en sist kontaktet Render.

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
- `app/executor.py` - sender godkjente signaler som ordre til MT5 via MetaApi
- `app/ea_bridge.py` + `mt5/SMT_Render_Bridge.mq5` - alternativ: EA i MT5 henter ordrene
- `app/models.py` - databasetabeller
- `app/db.py`, `app/config.py` - oppsett
- `render.yaml` - oppretter web-tjeneste og database paa Render
