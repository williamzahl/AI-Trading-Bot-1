"""Bro mellom Render og en EA i MT5 (f.eks. paa MetaQuotes VPS).

EA-en spoer GET /mt5/next hvert par sekund. Er det en godkjent ordre i koe,
faar den en enkel tekstlinje tilbake, utfoerer ordren i MT5 og melder
resultatet med POST /mt5/result. Resultatet sendes videre til Telegram.
"""
import logging
import re
from datetime import datetime, timezone

from app import config, executor, telegram_bot
from app.db import SessionLocal, get_setting, set_setting
from app.models import Signal

log = logging.getLogger("smt-bot")
HEARTBEAT_KEY = "ea_last_poll"
ALGO_KEY = "ea_algo_trading"


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


def _smt_level(sig: Signal) -> str:
    """Low (kjoep) / high (salg) paa lyset som dannet SMT-en, sendt fra TradingView."""
    raw = sig.raw if isinstance(sig.raw, dict) else {}
    v = _f(raw.get("smt_level"))
    return repr(v) if v else ""


def algo_state() -> str | None:
    """'1' = Algo Trading på i MT5, '0' = av, None = ukjent (eldre EA)."""
    return get_setting(ALGO_KEY) or None


async def next_order(account: str = "", algo: str = "") -> str:
    """Neste ordre som tekst, eller 'NONE'."""
    now = datetime.now(timezone.utc)
    set_setting(HEARTBEAT_KEY, now.isoformat())
    if account:
        set_setting("ea_account", account[:64])
    if algo in ("0", "1"):
        set_setting(ALGO_KEY, algo)
    ok, _ = executor.state()
    if not ok or algo == "0":
        # Algo Trading av i MT5: ordren blir liggende i køen til den slås på
        # (eller går ut på tid), i stedet for å feile.
        return "NONE"
    with SessionLocal() as s:
        rows = (s.query(Signal).filter(Signal.exec_status == "QUEUED")
                .order_by(Signal.id.asc()).limit(10).all())
        for sig in rows:
            age_min = (now - _aware(sig.received_at)).total_seconds() / 60
            if age_min > config.MAX_SIGNAL_AGE_MIN:
                sig.exec_status = "SKIPPED"
                sig.exec_message = f"⛔ Ordre #{sig.id} utløpt ({age_min:.0f} min gammel) før MT5 hentet den."
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
                    f"max_pos={config.MAX_OPEN_POSITIONS};risk_usd={config.RISK_USD};"
                    f"rr={config.RISK_REWARD};lookback={config.SL_LOOKBACK_BARS};"
                    f"buffer={config.sl_buffer(symbol):g};max_lot={config.MAX_LOT};"
                    f"max_sl_pct={config.MAX_SL_PCT};smt_level={_smt_level(sig)}")
    return "NONE"


_NO = {"aapne": "åpne", "slaatt": "slått", "utfoert": "utført", "maa": "må", "paa": "på", "naermere": "nærmere"}


def _norsk(text: str) -> str:
    """EA-en sender ren ASCII; bytt til æ/ø/å foer det vises i Telegram."""
    return re.sub(r"\b(" + "|".join(_NO) + r")\b", lambda m: _NO[m.group(1)], text)


def _f(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def record_result(sig_id: int, ok: bool, ticket: str, price: str, sl: str, tp: str, msg: str,
                        lot: str = "", risk: str = "") -> None:
    with SessionLocal() as s:
        sig = s.get(Signal, sig_id)
        if not sig:
            return
        symbol = executor.mt5_symbol(sig.instrument) or sig.instrument
        if ok:
            sig.exec_status = "FILLED"
            sig.exec_order_id = ticket[:64] or None
            sig.exec_price, sig.exec_sl, sig.exec_tp = _f(price), _f(sl), _f(tp)
            icon = "🟢" if (sig.signal or "").upper() == "BUY" else "🔴"
            sig.exec_lot = _f(lot) or config.TRADE_LOT
            r = _f(risk)
            risk_line = (f"Risiko: {r:.0f} $  ->  Mål: {r * config.RISK_REWARD:.0f} $ "
                         f"(1:{config.RISK_REWARD:g})\n") if r else ""
            text = (f"✅ TRADE TATT #{sig.id}\n"
                    f"{icon} {sig.signal} {sig.exec_lot:g} lot {symbol}\n"
                    f"Entry: {price}\nSL: {sl}\nTP: {tp}\n{risk_line}"
                    f"Ticket: {ticket or '-'}")
        else:
            sig.exec_status = "SKIPPED" if msg.startswith("SKIP") else "FAILED"
            reason = _norsk(msg[5:].strip() if msg.startswith("SKIP") else msg)
            head = "⏭ INGEN TRADE" if sig.exec_status == "SKIPPED" else "⚠️ TRADE FEILET"
            text = f"{head} #{sig.id} ({sig.signal} {symbol})\nGrunn: {reason}"
        sig.exec_message = text[:500]
        sig.exec_at = datetime.now(timezone.utc)
        s.commit()
        log.info("EA-resultat #%s: %s", sig_id, text.replace("\n", " | "))
        await _tell(sig, text)


REASONS = {"TP": "Take profit 🎯", "SL": "Stop loss 🛑", "MANUAL": "Lukket manuelt",
           "EA": "Lukket av EA", "SO": "Stop out (margin)", "OTHER": "Lukket"}


async def record_close(sig_id: int, price: str, profit: str, reason: str) -> None:
    with SessionLocal() as s:
        sig = s.get(Signal, sig_id)
        if not sig:
            return
        if sig.closed_at:  # allerede meldt
            return
        sig.close_price, sig.close_profit = _f(price), _f(profit)
        sig.close_reason = reason[:32]
        sig.closed_at = datetime.now(timezone.utc)
        s.commit()
        symbol = executor.mt5_symbol(sig.instrument) or sig.instrument
        p = sig.close_profit
        icon = "💰" if p is not None and p > 0 else "📉" if p is not None and p < 0 else "➖"
        opened = sig.exec_at or sig.received_at
        mins = (sig.closed_at - _aware(opened)).total_seconds() / 60 if opened else None
        lines = [f"{icon} TRADE LUKKET #{sig.id}",
                 f"{sig.signal} {(sig.exec_lot or config.TRADE_LOT):g} lot {symbol}",
                 f"Entry: {sig.exec_price if sig.exec_price is not None else '-'} -> Exit: {price}",
                 f"Resultat: {p:+.2f} USD" if p is not None else "Resultat: -",
                 f"Grunn: {REASONS.get(reason.upper(), reason)}"]
        if mins is not None:
            lines.append(f"Varighet: {mins:.0f} min")
        text = "\n".join(lines)
        log.info("Lukket #%s: %s", sig_id, text.replace("\n", " | "))
        await _tell(sig, text)
