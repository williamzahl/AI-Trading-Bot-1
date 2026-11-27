"""All konfigurasjon leses fra miljoevariabler (settes i Render)."""
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")
# Render gir "postgres://..." / "postgresql://..."; SQLAlchemy trenger driver-navn.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
TV_IP_ALLOWLIST = os.getenv("TV_IP_ALLOWLIST", "off").lower() in ("on", "true", "1")

# Offisielle TradingView webhook-IP-er:
# https://www.tradingview.com/support/solutions/43000529348
TRADINGVIEW_IPS = {"52.89.214.238", "34.212.75.30", "54.218.53.128", "52.32.178.7"}

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
# Valgfritt: laas boten til én chat. Hvis tom, blir foerste som sender /start eier.
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
# Render setter RENDER_EXTERNAL_URL automatisk (f.eks. https://smt-webhook-xxxx.onrender.com)
PUBLIC_URL = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")


# ---------- Ordre til MT5 via MetaApi.cloud ----------
def _num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


# AUTO_TRADE=on: trend-signaler sendes rett til MT5 uten APPROVE/REJECT i Telegram
AUTO_TRADE = os.getenv("AUTO_TRADE", "on").strip().lower() in ("on", "true", "1")
# Navnet paa aktiv strategi, vises i /status. Endres i Render (STRATEGY).
STRATEGY = os.getenv("STRATEGY", "").strip() or "5M SMT (NAS100) + 24t trendfilter"
# TEST: signaler fra 1M-testindikatoren handles selv uten trend (kun for aa teste kjeden).
# Sett TEST_IGNORE_TREND_1M=off i Render naar testingen er ferdig.
TEST_IGNORE_TREND_1M = os.getenv("TEST_IGNORE_TREND_1M", "on").strip().lower() in ("on", "true", "1")
# Noedstopp: ingen ordre sendes uten EXECUTION_ENABLED=on
EXECUTION_ENABLED = os.getenv("EXECUTION_ENABLED", "off").strip().lower() in ("on", "true", "1")
# "metaapi" = Render sender ordren via MetaApi.cloud
# "ea"      = en EA i MT5 (f.eks. paa MetaQuotes VPS) henter ordren fra Render
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "metaapi").strip().lower()
MT5_EA_KEY = os.getenv("MT5_EA_KEY", "").strip()  # egen noekkel for EA-en
METAAPI_TOKEN = os.getenv("METAAPI_TOKEN", "").strip()
METAAPI_ACCOUNT_ID = os.getenv("METAAPI_ACCOUNT_ID", "").strip()
METAAPI_REGION = os.getenv("METAAPI_REGION", "").strip()  # tom = finn automatisk

TRADE_LOT = _num("TRADE_LOT", 0.1)                 # fast lotstoerrelse per ordre
STOP_LOSS_PCT = _num("STOP_LOSS_PCT", 0.25)        # SL-avstand i % av prisen
TAKE_PROFIT_PCT = _num("TAKE_PROFIT_PCT", 0.5)     # TP-avstand i % av prisen
# Risiko per trade i USD. Lot regnes ut av EA-en fra SL-avstanden.
# 0 = bruk fast TRADE_LOT i stedet.
RISK_USD = _num("RISK_USD", 250)
RISK_REWARD = _num("RISK_REWARD", 3)               # TP = 3 x SL-avstand
SL_LOOKBACK_BARS = int(_num("SL_LOOKBACK_BARS", 6))  # reserve hvis varselet mangler smt_level
SL_BUFFER_POINTS = _num("SL_BUFFER_POINTS", 7)     # reserve-buffer for symboler som ikke staar i SL_BUFFER


def _buffer_map(raw: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in raw.split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            try:
                out[k.strip().upper()] = float(v)
            except ValueError:
                pass
    return out


# Ekstra avstand (i pris/punkter) under SMT-low / over SMT-high, per symbol.
# Endres i Render uten aa bytte EA, f.eks. SL_BUFFER=NAS100:10
SL_BUFFER = _buffer_map(os.getenv("SL_BUFFER", "") or "NAS100:7")


def sl_buffer(symbol: str) -> float:
    sym = symbol.upper()
    if MT5_SYMBOL_SUFFIX and sym.endswith(MT5_SYMBOL_SUFFIX.upper()):
        sym = sym[: -len(MT5_SYMBOL_SUFFIX)]
    return SL_BUFFER.get(sym, SL_BUFFER_POINTS)
MAX_LOT = _num("MAX_LOT", 20)                      # sikkerhetstak paa lot
MAX_SL_PCT = _num("MAX_SL_PCT", 1.0)               # hopp over trade hvis SL er lenger unna enn dette (%)
MAX_OPEN_POSITIONS = int(_num("MAX_OPEN_POSITIONS", 1))
MAX_SIGNAL_AGE_MIN = _num("MAX_SIGNAL_AGE_MIN", 15)
ALLOWED_SYMBOLS = [x.strip().upper() for x in os.getenv("ALLOWED_SYMBOLS", "NAS100").split(",") if x.strip()]
MT5_SYMBOL_SUFFIX = os.getenv("MT5_SYMBOL_SUFFIX", "").strip()
# TradingView-navn -> MT5-navn
SYMBOL_MAP = {"US100": "NAS100", "USTEC": "NAS100", "SPX500": "US500"}
