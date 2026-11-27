"""Telegram: sender signaler med APPROVE/REJECT-knapper og tar imot svarene."""
import asyncio
import hashlib
import html
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from app import config, executor
from app.db import SessionLocal, get_setting, set_setting
from app.models import Signal

log = logging.getLogger("smt-bot")
_tasks: set = set()  # holder bakgrunnsjobber i live

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


OSLO = ZoneInfo("Europe/Oslo")


def oslo(dt: datetime | None, fmt: str = "%d.%m.%Y %H:%M:%S") -> str:
    """Vis tid i norsk tid (tar hensyn til sommertid)."""
    if not dt:
        return "-"
    if dt.tzinfo is None:  # databasen lagrer UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(OSLO).strftime(fmt)


def _fmt_price(p) -> str:
    return f"{p:,.2f}".replace(",", " ") if isinstance(p, (int, float)) else "-"


def signal_text(sig: Signal) -> str:
    side = (sig.signal or "").upper()
    icon = "🟢" if side in ("BUY", "LONG") else "🔴" if side in ("SELL", "SHORT") else "ℹ️"
    t = oslo(sig.received_at)
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
    raw = sig.raw if isinstance(sig.raw, dict) else {}
    if "bias" in raw:
        trend = {"UP": "OPP 📈", "DOWN": "NED 📉"}.get(raw["bias"], "INGEN ➖")
        chg = raw.get("change_24h_pct")
        chg_txt = f" ({chg:+.2f}% 24t)" if isinstance(chg, (int, float)) else ""
        lines.append(f"Trend: {trend}{chg_txt}")
        if raw.get("trend_aligned") is False:
            lines.append("⚠️ Mot trend / ingen trend: kun info, ingen trade")
    if sig.status not in ("NEW", "INFO"):
        d = oslo(sig.decided_at, "%H:%M:%S") if sig.decided_at else ""
        if sig.status == "APPROVED" and config.AUTO_TRADE:
            lines.append("\n🤖 <b>Auto-handel:</b> sendes til MT5")
        else:
            mark = "✅ GODKJENT" if sig.status == "APPROVED" else "❌ AVVIST"
            lines.append(f"\n<b>{mark}</b> {d}")
    return "\n".join(lines)


def mode_text() -> str:
    if config.AUTO_TRADE:
        return "Modus: 🤖 Automatisk"
    return "Modus: ✋ Manuell (APPROVE)"


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
        auto = sig.status == "NEW" and config.AUTO_TRADE
        if auto:
            sig.status = "APPROVED"
            sig.decided_at = datetime.now(timezone.utc)
            s.commit()
        extra = {"reply_markup": _keyboard(sig.id)} if sig.status == "NEW" else {}
        res = await call("sendMessage", chat_id=chat, text=signal_text(sig),
                         parse_mode="HTML", **extra)
        if res.get("ok"):
            sig.telegram_message_id = res["result"]["message_id"]
            s.commit()
    if auto:
        await _execute_and_report(sig_id, chat, sig.telegram_message_id)


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
            await call("sendMessage", chat_id=chat_id, text="Boten er aktiv. Du er eier.\n/siste - siste signaler\n/status - handel og MT5-konto\n/stopp - nødstopp\n/handel_paa - start handel igjen")
        else:
            log.warning("Ukjent chat %s proevde /start", chat_id)
            await call("sendMessage", chat_id=chat_id, text="Ingen tilgang.")
        return

    if owner != chat_id:
        return

    if text.startswith("/stopp"):
        executor.set_paused(True)
        await call("sendMessage", chat_id=chat_id,
                   text="⛔ Handel PAUSET. Ingen nye ordre sendes. Åpne posisjoner beholder sin SL/TP.\n"
                        "Skriv /handel_paa for å starte igjen.")
        return

    if text.startswith("/handel_paa"):
        executor.set_paused(False)
        ok, why = executor.state()
        await call("sendMessage", chat_id=chat_id, text=f"Handel: {why}\n{mode_text()}")
        return

    if text.startswith("/status"):
        ok, why = executor.state()
        handel = "PÅ ✅" if ok else f"⛔ {why}"
        modus = "🤖 Automatisk" if config.AUTO_TRADE else "✋ Manuell (APPROVE)"
        lines = [f"Handel: {handel}", f"Modus: {modus}", ""]
        if executor.ea_mode() and config.RISK_USD > 0:
            minutes = config.SL_LOOKBACK_BARS * 5
            lines += [f"Risiko: {config.RISK_USD:g} $ → Mål: {config.RISK_USD * config.RISK_REWARD:g} $ "
                      f"(1:{config.RISK_REWARD:g})",
                      f"SL: {config.SL_BUFFER_POINTS:g} pkt bak siste {minutes} min low/high",
                      "Lot: regnes ut automatisk"]
        else:
            lines += [f"Lot: {config.TRADE_LOT:g}",
                      f"SL: {config.STOP_LOSS_PCT:g} %  |  TP: {config.TAKE_PROFIT_PCT:g} %"]
        lines += ["", f"Symboler: {', '.join(config.ALLOWED_SYMBOLS)}",
                  f"Maks åpne: {config.MAX_OPEN_POSITIONS}", ""]
        if executor.ea_mode():
            from app import ea_bridge
            seen = ea_bridge.last_seen_seconds()
            if seen is None:
                lines.append("MT5-EA: 🔴 aldri sett")
            elif seen < 60:
                lines.append(f"MT5-EA: 🟢 ({seen:.0f} sek siden)")
            else:
                ago = f"{seen / 60:.0f} min" if seen < 3600 else f"{seen / 3600:.1f} t"
                lines.append(f"MT5-EA: 🔴 ({ago} siden)")
        elif executor.configured():
            try:
                acc = await executor.account_info()
                pos = await executor.open_positions()
                lines.append(f"MT5: {acc.get('balance')} {acc.get('currency', '')}  |  Åpne: {len(pos)}")
            except Exception as e:
                lines.append(f"MT5: 🔴 ingen kontakt ({e})"[:200])
        await call("sendMessage", chat_id=chat_id, text="\n".join(lines).strip())
        return

    if text.startswith("/siste"):
        with SessionLocal() as s:
            rows = s.query(Signal).order_by(Signal.id.desc()).limit(5).all()
        if not rows:
            body = "Ingen signaler enda."
        else:
            body = "\n".join(
                f"#{r.id} {oslo(r.received_at, '%d.%m %H:%M')} {r.instrument} {r.signal} "
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
        approved = sig.status == "APPROVED"

    if approved:
        task = asyncio.create_task(_execute_and_report(sig_id, chat_id, cq["message"]["message_id"]))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


async def _execute_and_report(sig_id: int, chat_id: str, reply_to: int | None) -> None:
    try:
        text = await executor.execute_signal(sig_id)
    except Exception as e:
        log.exception("Ordre for #%s krasjet", sig_id)
        text = f"⚠️ Ordre for #{sig_id} feilet: {e}"[:400]
    with SessionLocal() as s:
        sig = s.get(Signal, sig_id)
        if sig and sig.exec_status == "QUEUED":
            return  # EA-en henter ordren; resultatet meldes naar den er utfoert
    extra = {"reply_to_message_id": reply_to} if reply_to else {}
    await call("sendMessage", chat_id=chat_id, text=text, **extra)
