"""Bro mellom Render og en EA i MT5 (f.eks. paa MetaQuotes VPS).

EA-en spoer GET /mt5/next hvert par sekund. Er det en godkjent ordre i koe,
faar den en enkel tekstlinje tilbake, utfoerer ordren i MT5 og melder
resultatet med POST /mt5/result. Resultatet sendes videre til Telegram.
"""
import logging
from datetime import datetime, timezone

from app import config, executor, telegram_bot
from app.db import SessionLocal, get_setting, set_setting
from app.models import Signal

log = logging.getLogger("smt-bot")
HEARTBEAT_KEY = "ea_last_poll"


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def last_seen_seconds() -> float | None:
    v = get_setting(HEARTBEAT_KEY)
    if not v:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(v)).total_seconds()


async def _tell(sig: Signal, text: str) -> None:
    chat = telegram_bot.owner_chat_id()
    if not (telegram_bot.enabled() and chat):
        return
    extra = {"reply_to_message_id": sig.telegram_message_id} if sig.telegram_message_id else {}
    await telegram_bot.call("sendMessage", chat_id=chat, text=text, **extra)


async def next_order(account: str = "") -> str:
    """Neste ordre som tekst, eller 'NONE'."""
    now = datetime.now(timezone.utc)
    set_setting(HEARTBEAT_KEY, now.isoformat())
    if account:
        set_setting("ea_account", account[:64])
    ok, _ = executor.state()
    if not ok:
        return "NONE"
    with SessionLocal() as s:
        rows = (s.query(Signal).filter(Signal.exec_status == "QUEUED")
                .order_by(Signal.id.asc()).limit(10).all())
        for sig in rows:
            age_min = (now - _aware(sig.received_at)).total_seconds() / 60
            if age_min > config.MAX_SIGNAL_AGE_MIN:
                sig.exec_status = "SKIPPED"
                sig.exec_message = f"⛔ Ordre #{sig.id} utloept ({age_min:.0f} min gammel) foer MT5 hentet den."
                sig.exec_at = now
                s.commit()
                await _tell(sig, sig.exec_message)
                continue
            symbol = executor.mt5_symbol(sig.instrument)
            side = (sig.signal or "").upper()
            if not symbol or side not in ("BUY", "SELL"):
                sig.exec_status = "SKIPPED"
                sig.exec_message = f"⛔ Ordre #{sig.id}: ugyldig symbol/retning."
                s.commit()
                continue
            sig.exec_status = "SENDING"
            sig.exec_at = now
            s.commit()
            log.info("EA hentet ordre #%s %s %s", sig.id, side, symbol)
            return (f"id={sig.id};symbol={symbol};side={side};lot={config.TRADE_LOT};"
                    f"sl_pct={config.STOP_LOSS_PCT};tp_pct={config.TAKE_PROFIT_PCT};"
                    f"max_pos={config.MAX_OPEN_POSITIONS}")
    return "NONE"


async def record_result(sig_id: int, ok: bool, ticket: str, price: str, sl: str, tp: str, msg: str) -> None:
    with SessionLocal() as s:
        sig = s.get(Signal, sig_id)
        if not sig:
            return
        if ok:
            sig.exec_status = "FILLED"
            sig.exec_order_id = ticket[:64] or None
            text = (f"✅ ORDRE UTFOERT #{sig.id}: {sig.signal} {config.TRADE_LOT} "
                    f"{executor.mt5_symbol(sig.instrument)} @ {price}\nSL {sl} / TP {tp}\nTicket: {ticket or '-'}")
        else:
            sig.exec_status = "FAILED" if not msg.startswith("SKIP") else "SKIPPED"
            text = f"⚠️ MT5 utfoerte ikke ordre #{sig.id}: {msg}"
        sig.exec_message = text[:500]
        sig.exec_at = datetime.now(timezone.utc)
        s.commit()
        log.info("EA-resultat #%s: %s", sig_id, text.replace("\n", " | "))
        await _tell(sig, text)
