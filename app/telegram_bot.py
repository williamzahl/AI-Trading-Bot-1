"""Telegram: sender signaler med APPROVE/REJECT-knapper og tar imot svarene."""
import hashlib
import html
import logging
from datetime import datetime, timezone

import httpx

from app import config
from app.db import SessionLocal, get_setting, set_setting
from app.models import Signal

log = logging.getLogger("smt-bot")

API = "https://api.telegram.org/bot{token}/{method}"
WEBHOOK_PATH = "/telegram/webhook"


def enabled() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN)


def webhook_secret() -> str:
    """Hemmelighet Telegram sender i headeren, avledet fra WEBHOOK_SECRET."""
    return hashlib.sha256(("tg:" + config.WEBHOOK_SECRET).encode()).hexdigest()


async def call(method: str, **payload) -> dict:
    url = API.format(token=config.TELEGRAM_BOT_TOKEN, method=method)
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, json=payload)
    data = r.json()
    if not data.get("ok"):
        log.warning("Telegram %s feilet: %s", method, data.get("description"))
    return data


def owner_chat_id() -> str | None:
    return config.TELEGRAM_CHAT_ID or get_setting("telegram_owner_chat_id")


async def setup_webhook() -> None:
    if not enabled():
        log.info("Telegram ikke konfigurert (TELEGRAM_BOT_TOKEN mangler)")
        return
    if not config.PUBLIC_URL:
        log.warning("PUBLIC_URL/RENDER_EXTERNAL_URL mangler; kan ikke sette Telegram-webhook")
        return
    res = await call(
        "setWebhook",
        url=config.PUBLIC_URL + WEBHOOK_PATH,
        secret_token=webhook_secret(),
        allowed_updates=["message", "callback_query"],
    )
    log.info("Telegram-webhook satt: %s", res.get("ok"))


def _fmt_price(p) -> str:
    return f"{p:,.2f}".replace(",", " ") if isinstance(p, (int, float)) else "-"


def signal_text(sig: Signal) -> str:
    side = (sig.signal or "").upper()
    icon = "🟢" if side in ("BUY", "LONG") else "🔴" if side in ("SELL", "SHORT") else "ℹ️"
    t = sig.received_at.strftime("%Y-%m-%d %H:%M:%S UTC") if sig.received_at else "-"
    lines = [
        f"{icon} <b>{side or '?'}</b> {html.escape(sig.instrument or '?')}",
        f"Indikator: {html.escape(sig.indicator or '-')}",
        f"Pris: {_fmt_price(sig.price)}",
        f"Timeframe: {sig.timeframe or '-'}",
        f"Tid: {t}",
        f"Signal #{sig.id}",
    ]
    msg = (sig.raw or {}).get("message") if isinstance(sig.raw, dict) else None
    if msg:
        lines.insert(2, f"Melding: {html.escape(msg[:500])}")
    if sig.status not in ("NEW", "INFO"):
        d = sig.decided_at.strftime("%H:%M:%S UTC") if sig.decided_at else ""
        mark = "✅ GODKJENT" if sig.status == "APPROVED" else "❌ AVVIST"
        lines.append(f"\n<b>{mark}</b> {d}")
    return "\n".join(lines)


def _keyboard(sig_id: int) -> dict:
    return {"inline_keyboard": [[
        {"text": "✅ APPROVE", "callback_data": f"approve:{sig_id}"},
        {"text": "❌ REJECT", "callback_data": f"reject:{sig_id}"},
    ]]}


async def notify_signal(sig_id: int) -> None:
    """Kjoeres i bakgrunnen etter at TradingView har faatt svar."""
    if not enabled():
        return
    chat = owner_chat_id()
    if not chat:
        log.warning("Ingen Telegram-eier registrert enda; send /start til boten")
        return
    with SessionLocal() as s:
        sig = s.get(Signal, sig_id)
        if not sig:
            return
        extra = {} if sig.status == "INFO" else {"reply_markup": _keyboard(sig.id)}
        res = await call("sendMessage", chat_id=chat, text=signal_text(sig),
                         parse_mode="HTML", **extra)
        if res.get("ok"):
            sig.telegram_message_id = res["result"]["message_id"]
            s.commit()


async def handle_update(update: dict) -> None:
    if "callback_query" in update:
        await _handle_callback(update["callback_query"])
    elif "message" in update:
        await _handle_message(update["message"])


async def _handle_message(msg: dict) -> None:
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip()
    owner = owner_chat_id()

    if text.startswith("/start"):
        if not owner:
            set_setting("telegram_owner_chat_id", chat_id)
            await call("sendMessage", chat_id=chat_id,
                       text=f"✅ Du er registrert som eier av SMT-boten.\nChat-ID: {chat_id}\n"
                            "Nye TradingView-signaler kommer hit med APPROVE/REJECT.")
            log.info("Telegram-eier registrert: %s", chat_id)
        elif owner == chat_id:
            await call("sendMessage", chat_id=chat_id, text="Boten er aktiv. Du er eier. Skriv /siste for de siste signalene.")
        else:
            log.warning("Ukjent chat %s proevde /start", chat_id)
            await call("sendMessage", chat_id=chat_id, text="Ingen tilgang.")
        return

    if owner != chat_id:
        return

    if text.startswith("/siste"):
        with SessionLocal() as s:
            rows = s.query(Signal).order_by(Signal.id.desc()).limit(5).all()
        if not rows:
            body = "Ingen signaler enda."
        else:
            body = "\n".join(
                f"#{r.id} {r.received_at:%d.%m %H:%M} {r.instrument} {r.signal} "
                f"{_fmt_price(r.price)} [{r.status}]" for r in rows)
        await call("sendMessage", chat_id=chat_id, text=body)


async def _handle_callback(cq: dict) -> None:
    chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
    if chat_id != owner_chat_id():
        await call("answerCallbackQuery", callback_query_id=cq["id"], text="Ingen tilgang")
        return
    try:
        action, sid = cq.get("data", "").split(":", 1)
        sig_id = int(sid)
    except ValueError:
        return

    with SessionLocal() as s:
        sig = s.get(Signal, sig_id)
        if not sig:
            await call("answerCallbackQuery", callback_query_id=cq["id"], text="Fant ikke signalet")
            return
        if sig.status != "NEW":
            await call("answerCallbackQuery", callback_query_id=cq["id"],
                       text=f"Allerede {sig.status}")
            return
        sig.status = "APPROVED" if action == "approve" else "REJECTED"
        sig.decided_at = datetime.now(timezone.utc)
        s.commit()
        log.info("Signal #%s %s via Telegram", sig.id, sig.status)
        await call("answerCallbackQuery", callback_query_id=cq["id"],
                   text="Godkjent ✅" if sig.status == "APPROVED" else "Avvist ❌")
        await call("editMessageText", chat_id=chat_id, message_id=cq["message"]["message_id"],
                   text=signal_text(sig), parse_mode="HTML")
