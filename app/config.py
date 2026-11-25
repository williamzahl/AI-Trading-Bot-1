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
