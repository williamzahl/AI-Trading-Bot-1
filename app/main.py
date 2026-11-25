"""SMT-bot: webhook-mottaker for TradingView."""
import json
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from sqlalchemy import text

from app import config, telegram_bot
from app.db import engine, init_db
from app.signals import latest_signals, save_signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("smt-bot")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    log.info("Database klar. IP-allowlist=%s", config.TV_IP_ALLOWLIST)
    try:
        await telegram_bot.setup_webhook()
    except Exception:  # Telegram-feil skal aldri stoppe mottakeren
        log.exception("Kunne ikke sette opp Telegram")
    yield


app = FastAPI(title="SMT Bot", lifespan=lifespan)


def client_ip(request: Request) -> str | None:
    # Render staar bak en proxy; ekte avsender-IP er foerste i X-Forwarded-For.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def check_secret(value: str | None) -> None:
    if not config.WEBHOOK_SECRET or not value or not secrets.compare_digest(
        str(value), config.WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=401, detail="Feil eller manglende secret")


@app.get("/")
def root():
    return {"service": "smt-bot", "status": "ok"}


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request, background: BackgroundTasks):
    ip = client_ip(request)
    if config.TV_IP_ALLOWLIST and ip not in config.TRADINGVIEW_IPS:
        log.warning("Avvist IP %s", ip)
        raise HTTPException(status_code=403, detail="IP ikke tillatt")

    body = await request.body()
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        log.warning("Ugyldig JSON fra %s: %r", ip, body[:200])
        raise HTTPException(status_code=400, detail="Meldingen maa vaere gyldig JSON")

    check_secret(data.get("secret"))
    sig = save_signal(data, ip)
    background.add_task(telegram_bot.notify_signal, sig.id)
    log.info("SIGNAL #%s %s %s %s @ %s", sig.id, sig.instrument, sig.indicator, sig.signal, sig.price)
    return {"ok": True, "id": sig.id}


@app.get("/signals")
def signals(key: str = Query(...), limit: int = Query(20, ge=1, le=200)):
    check_secret(key)
    return latest_signals(limit)


@app.post(telegram_bot.WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if not telegram_bot.enabled() or not x_telegram_bot_api_secret_token or not secrets.compare_digest(
        x_telegram_bot_api_secret_token, telegram_bot.webhook_secret()
    ):
        raise HTTPException(status_code=401)
    update = await request.json()
    try:
        await telegram_bot.handle_update(update)
    except Exception:
        log.exception("Feil ved behandling av Telegram-oppdatering")
    return {"ok": True}


@app.get("/telegram/status")
async def telegram_status(key: str = Query(...)):
    """Feilsoeking: viser om Telegram er satt opp riktig (uten aa vise token)."""
    check_secret(key)
    info: dict = {
        "token_satt": telegram_bot.enabled(),
        "public_url": config.PUBLIC_URL or None,
        "forventet_webhook": (config.PUBLIC_URL + telegram_bot.WEBHOOK_PATH) if config.PUBLIC_URL else None,
        "eier_chat_id": telegram_bot.owner_chat_id(),
    }
    if telegram_bot.enabled():
        me = await telegram_bot.call("getMe")
        info["bot"] = (me.get("result") or {}).get("username") or me.get("description")
        wh = await telegram_bot.call("getWebhookInfo")
        r = wh.get("result") or {}
        info["telegram_webhook"] = {
            "url": r.get("url"),
            "ventende_meldinger": r.get("pending_update_count"),
            "siste_feil": r.get("last_error_message"),
        }
    return info


@app.post("/telegram/reset")
async def telegram_reset(key: str = Query(...)):
    """Setter Telegram-webhooken paa nytt."""
    check_secret(key)
    await telegram_bot.setup_webhook()
    return await telegram_status(key)
