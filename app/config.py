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


# Noedstopp: ingen ordre sendes uten EXECUTION_ENABLED=on
EXECUTION_ENABLED = os.getenv("EXECUTION_ENABLED", "off").strip().lower() in ("on", "true", "1")
METAAPI_TOKEN = os.getenv("METAAPI_TOKEN", "").strip()
METAAPI_ACCOUNT_ID = os.getenv("METAAPI_ACCOUNT_ID", "").strip()
METAAPI_REGION = os.getenv("METAAPI_REGION", "").strip()  # tom = finn automatisk

TRADE_LOT = _num("TRADE_LOT", 0.1)                 # fast lotstoerrelse per ordre
STOP_LOSS_PCT = _num("STOP_LOSS_PCT", 0.25)        # SL-avstand i % av prisen
TAKE_PROFIT_PCT = _num("TAKE_PROFIT_PCT", 0.5)     # TP-avstand i % av prisen
MAX_OPEN_POSITIONS = int(_num("MAX_OPEN_POSITIONS", 1))
MAX_SIGNAL_AGE_MIN = _num("MAX_SIGNAL_AGE_MIN", 15)
ALLOWED_SYMBOLS = [x.strip().upper() for x in os.getenv("ALLOWED_SYMBOLS", "NAS100,US500").split(",") if x.strip()]
MT5_SYMBOL_SUFFIX = os.getenv("MT5_SYMBOL_SUFFIX", "").strip()
# TradingView-navn -> MT5-navn
SYMBOL_MAP = {"US100": "NAS100", "USTEC": "NAS100", "SPX500": "US500"}
