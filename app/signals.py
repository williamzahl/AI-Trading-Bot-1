"""Signalbehandling: gjoer om et TradingView-varsel til en lagret Signal-rad.

Nye indikatorer trenger ingen kodeendring saa lenge varselet sender JSON med
feltene under. Ekstra felt lagres uansett i `raw`.
"""
from app.db import SessionLocal
from app.models import Signal


import re

_BUY = re.compile(r"\b(buy|long|bull|bullish)\b", re.I)
_SELL = re.compile(r"\b(sell|short|bear|bearish)\b", re.I)


def parse_side(text: str) -> str:
    """Finn retning i en tekstmelding. INFO hvis ingen/begge retninger nevnes."""
    b, s = bool(_BUY.search(text)), bool(_SELL.search(text))
    if b and not s:
        return "BUY"
    if s and not b:
        return "SELL"
    return "INFO"


def _first(data: dict, *keys):
    for k in keys:
        if data.get(k) not in (None, ""):
            return data[k]
    return None


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def save_signal(data: dict, source_ip: str | None) -> Signal:
    clean = {k: v for k, v in data.items() if k != "secret"}  # lagre aldri noekkelen
    sig = Signal(
        instrument=_first(data, "instrument", "ticker", "symbol"),
        indicator=_first(data, "indicator", "strategy"),
        signal=_first(data, "signal", "action", "side"),
        price=_to_float(_first(data, "price", "close")),
        timeframe=_first(data, "timeframe", "interval"),
        bar_time=_first(data, "time", "bar_time"),
        source_ip=source_ip,
        status="INFO" if str(_first(data, "signal", "action", "side") or "").upper() == "INFO" else "NEW",
        raw=clean,
    )
    with SessionLocal() as s:
        s.add(sig)
        s.commit()
    return sig


def latest_signals(limit: int = 20) -> list[dict]:
    with SessionLocal() as s:
        rows = s.query(Signal).order_by(Signal.id.desc()).limit(limit).all()
        return [r.to_dict() for r in rows]
