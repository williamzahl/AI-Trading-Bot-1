"""Signalbehandling: gjoer om et TradingView-varsel til en lagret Signal-rad.

Nye indikatorer trenger ingen kodeendring saa lenge varselet sender JSON med
feltene under. Ekstra felt lagres uansett i `raw`.
"""
from app import config
from app.db import SessionLocal
from app.models import Signal


import re

_BUY = re.compile(r"\b(buy|long|bull|bullish)\b", re.I)
_SELL = re.compile(r"\b(sell|short|bear|bearish)\b", re.I)


_BIAS = re.compile(r"bias=(UP|DOWN|NONE)", re.I)
_CHG = re.compile(r"24t:\s*([+-]?\d+(?:\.\d+)?)%")
_PRICE = re.compile(r"[–-]\s*(\d+(?:\.\d+)?)\s*(?:\||$)")


def parse_text(text: str) -> dict:
    """Hent retning, pris og 24t-trend fra en tekstmelding fra en indikator."""
    out = {"message": text, "signal": parse_side(text), "format": "text"}
    if m := _PRICE.search(text):
        out["price"] = m.group(1)
    if m := _CHG.search(text):
        out["change_24h_pct"] = float(m.group(1))
    if m := _BIAS.search(text):
        bias = m.group(1).upper()
        out["bias"] = bias
        side = out["signal"]
        out["trend_aligned"] = (side == "BUY" and bias == "UP") or (side == "SELL" and bias == "DOWN")
    return out


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


def normalize(data: dict) -> dict:
    """Fyll inn trend-felt som noen indikatorversjoner sender under andre navn.

    Uten `trend_aligned` ville et signal mot trenden faatt APPROVE/REJECT-knapper,
    saa den regnes ut fra `bias` og retningen naar den mangler.
    """
    if "change_24h_pct" not in data and "bias_24h_pct" in data:
        data["change_24h_pct"] = _to_float(data["bias_24h_pct"])
    elif "change_24h_pct" in data:
        data["change_24h_pct"] = _to_float(data["change_24h_pct"])
    bias = str(data.get("bias") or "").upper()
    if bias and "trend_aligned" not in data:
        side = str(_first(data, "signal", "action", "side") or "").upper()
        data["bias"] = bias
        data["trend_aligned"] = (side == "BUY" and bias == "UP") or (side == "SELL" and bias == "DOWN")
    elif isinstance(data.get("trend_aligned"), str):
        data["trend_aligned"] = data["trend_aligned"].strip().lower() in ("true", "1", "yes")
    return data


def is_test_1m(data: dict) -> bool:
    """Signal fra 1M-testindikatoren (f.eks. SMT_PEPPERSTONE_1M_TEST, timeframe 1)."""
    ind = str(_first(data, "indicator", "strategy") or "").upper()
    tf = str(_first(data, "timeframe", "interval") or "").strip()
    return "1M_TEST" in ind or (tf == "1" and "TEST" in ind)


def _initial_status(data: dict) -> str:
    """NEW = faar APPROVE/REJECT-knapper. INFO = bare informasjon."""
    if str(_first(data, "signal", "action", "side") or "").upper() == "INFO":
        return "INFO"
    if data.get("trend_aligned") is False:  # signal mot trend / ingen trend
        if config.TEST_IGNORE_TREND_1M and is_test_1m(data):
            data["test_ignore_trend"] = True
            return "NEW"
        return "INFO"
    return "NEW"


def save_signal(data: dict, source_ip: str | None) -> Signal:
    data = normalize(data)
    status = _initial_status(data)  # kan legge til test_ignore_trend i data
    clean = {k: v for k, v in data.items() if k != "secret"}  # lagre aldri noekkelen
    sig = Signal(
        instrument=_first(data, "instrument", "ticker", "symbol"),
        indicator=_first(data, "indicator", "strategy"),
        signal=_first(data, "signal", "action", "side"),
        price=_to_float(_first(data, "price", "close")),
        timeframe=_first(data, "timeframe", "interval"),
        bar_time=_first(data, "time", "bar_time"),
        source_ip=source_ip,
        status=status,
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
