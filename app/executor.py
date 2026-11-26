"""Sender godkjente signaler som ordre til MT5 via MetaApi.cloud (100 % sky).

Flyt: TradingView -> Render -> Telegram APPROVE -> denne modulen -> MetaApi -> MT5.

Sikkerhet (alt styres med miljoevariabler i Render):
- EXECUTION_ENABLED=on maa vaere satt, ellers sendes ingenting (noedstopp).
- /stopp i Telegram slaar av handel umiddelbart, /handel_paa slaar paa igjen.
- Fast lotstoerrelse (TRADE_LOT), SL/TP paa hver ordre, kun tillatte symboler,
  maks antall aapne posisjoner og maks alder paa signalet.
"""
import logging
from datetime import datetime, timezone

import httpx

from app import config
from app.db import SessionLocal, get_setting, set_setting
from app.models import Signal

log = logging.getLogger("smt-bot")

PROVISIONING = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"
CLIENT = "https://mt-client-api-v1.{region}.agiliumtrade.ai"
KILL_KEY = "trading_paused"

_region_cache: str | None = None


class ExecError(Exception):
    pass


# ---------- noedstopp ----------

def paused() -> bool:
    return get_setting(KILL_KEY) == "1"


def set_paused(value: bool) -> None:
    set_setting(KILL_KEY, "1" if value else "0")


def configured() -> bool:
    return bool(config.METAAPI_TOKEN and config.METAAPI_ACCOUNT_ID)


def state() -> tuple[bool, str]:
    """(kan handle, forklaring)."""
    if not config.EXECUTION_ENABLED:
        return False, "AV (EXECUTION_ENABLED er ikke 'on' i Render)"
    if not configured():
        return False, "AV (METAAPI_TOKEN eller METAAPI_ACCOUNT_ID mangler)"
    if paused():
        return False, "PAUSET (/stopp i Telegram). Skriv /handel_paa for aa starte igjen"
    return True, "PAA"


# ---------- MetaApi ----------

def _headers() -> dict:
    return {"auth-token": config.METAAPI_TOKEN, "Content-Type": "application/json"}


async def _region(client: httpx.AsyncClient) -> str:
    global _region_cache
    if config.METAAPI_REGION:
        return config.METAAPI_REGION
    if _region_cache:
        return _region_cache
    r = await client.get(f"{PROVISIONING}/users/current/accounts/{config.METAAPI_ACCOUNT_ID}",
                         headers=_headers())
    if r.status_code != 200:
        raise ExecError(f"MetaApi-konto ikke funnet ({r.status_code}): {r.text[:200]}")
    data = r.json()
    if data.get("state") != "DEPLOYED":
        raise ExecError(f"MetaApi-kontoen er ikke startet (state={data.get('state')}). Trykk Deploy i MetaApi.")
    _region_cache = data.get("region") or "new-york"
    return _region_cache


async def _api(method: str, path: str, json: dict | None = None):
    async with httpx.AsyncClient(timeout=30) as client:
        base = CLIENT.format(region=await _region(client))
        url = f"{base}/users/current/accounts/{config.METAAPI_ACCOUNT_ID}{path}"
        r = await client.request(method, url, headers=_headers(), json=json)
    if r.status_code != 200:
        raise ExecError(f"MetaApi svarte {r.status_code}: {r.text[:300]}")
    return r.json()


async def account_info() -> dict:
    return await _api("GET", "/account-information")


async def open_positions() -> list[dict]:
    return await _api("GET", "/positions")


# ---------- ordre ----------

def mt5_symbol(instrument: str | None) -> str | None:
    """'PEPPERSTONE:NAS100' / 'NAS100.P' -> 'NAS100' (+ evt. suffiks fra Render)."""
    if not instrument:
        return None
    sym = instrument.split(":")[-1].upper()
    if sym.endswith(".P"):
        sym = sym[:-2]
    sym = config.SYMBOL_MAP.get(sym, sym)
    if sym not in config.ALLOWED_SYMBOLS:
        return None
    return sym + config.MT5_SYMBOL_SUFFIX


def build_order(sig: Signal, symbol: str, ref_price: float) -> dict:
    side = (sig.signal or "").upper()
    if side not in ("BUY", "SELL"):
        raise ExecError(f"Ukjent retning '{sig.signal}'")
    sl = round(ref_price * config.STOP_LOSS_PCT / 100, 2)
    tp = round(ref_price * config.TAKE_PROFIT_PCT / 100, 2)
    if sl <= 0 or tp <= 0:
        raise ExecError("SL/TP maa vaere stoerre enn 0")
    return {
        "actionType": "ORDER_TYPE_BUY" if side == "BUY" else "ORDER_TYPE_SELL",
        "symbol": symbol,
        "volume": config.TRADE_LOT,
        # Avstand i pris fra inngangskurs, f.eks. 0.25 % av 21 000 = 52.5 punkter
        "stopLoss": sl,
        "stopLossUnits": "RELATIVE_PRICE",
        "takeProfit": tp,
        "takeProfitUnits": "RELATIVE_PRICE",
        "comment": f"SMT #{sig.id}"[:18],
        "clientId": f"smt{sig.id}",
    }


async def execute_signal(sig_id: int) -> str:
    """Sender ordren og lagrer resultatet. Returnerer tekst til Telegram."""
    with SessionLocal() as s:
        sig = s.get(Signal, sig_id)
        if not sig:
            return "Fant ikke signalet."
        if sig.exec_status in ("SENDING", "FILLED"):
            return f"Ordre for #{sig.id} er allerede {sig.exec_status}."
        sig.exec_status = "SENDING"
        s.commit()

        status, text = "SKIPPED", ""
        try:
            ok, why = state()
            if not ok:
                raise ExecError(f"Handel er {why}. Ingen ordre sendt.")

            symbol = mt5_symbol(sig.instrument)
            if not symbol:
                raise ExecError(f"{sig.instrument} er ikke i ALLOWED_SYMBOLS ({', '.join(config.ALLOWED_SYMBOLS)}).")

            received = sig.received_at
            if received.tzinfo is None:  # SQLite lagrer uten tidssone
                received = received.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - received).total_seconds() / 60
            if age_min > config.MAX_SIGNAL_AGE_MIN:
                raise ExecError(f"Signalet er {age_min:.0f} min gammelt (maks {config.MAX_SIGNAL_AGE_MIN}). Ingen ordre.")

            positions = await open_positions()
            if len(positions) >= config.MAX_OPEN_POSITIONS:
                raise ExecError(f"Har allerede {len(positions)} aapne posisjoner (maks {config.MAX_OPEN_POSITIONS}).")

            price = await _api("GET", f"/symbols/{symbol}/current-price")
            ref = price.get("ask") if (sig.signal or "").upper() == "BUY" else price.get("bid")
            ref = ref or sig.price
            if not ref:
                raise ExecError("Fant ingen pris aa regne SL/TP fra.")

            order = build_order(sig, symbol, float(ref))
            status = "FAILED"
            res = await _api("POST", "/trade", json=order)
            code = res.get("stringCode", "")
            sig.exec_order_id = str(res.get("orderId") or res.get("positionId") or "") or None
            if code in ("TRADE_RETCODE_DONE", "TRADE_RETCODE_PLACED", "TRADE_RETCODE_DONE_PARTIAL"):
                status = "FILLED"
                text = (f"✅ ORDRE SENDT #{sig.id}: {order['actionType'][11:]} {order['volume']} {symbol} "
                        f"@ ~{ref}\nSL {order['stopLoss']} / TP {order['takeProfit']} punkter unna\n"
                        f"Ordre-ID: {sig.exec_order_id or '-'}")
            else:
                text = f"⚠️ MT5 avviste ordre #{sig.id}: {code} {res.get('message', '')}"
        except ExecError as e:
            text = ("⛔ " if status == "SKIPPED" else "⚠️ ") + str(e)
        except Exception as e:  # nettverk o.l.
            log.exception("Ordre for signal #%s feilet", sig_id)
            status, text = "FAILED", f"⚠️ Teknisk feil ved ordre #{sig_id}: {type(e).__name__}: {e}"[:400]

        sig.exec_status = status
        sig.exec_message = text[:500]
        sig.exec_at = datetime.now(timezone.utc)
        s.commit()
        log.info("Ordre #%s: %s %s", sig_id, status, text.replace("\n", " | "))
        return text
