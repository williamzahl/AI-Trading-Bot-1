"""Databasetabeller."""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    instrument: Mapped[str | None] = mapped_column(String(64), index=True)
    indicator: Mapped[str | None] = mapped_column(String(128), index=True)
    signal: Mapped[str | None] = mapped_column(String(64))
    price: Mapped[float | None] = mapped_column(Float)
    timeframe: Mapped[str | None] = mapped_column(String(16))
    bar_time: Mapped[str | None] = mapped_column(String(64))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    # Status brukes senere av Telegram-godkjenning: NEW -> APPROVED / REJECTED
    status: Mapped[str] = mapped_column(String(16), default="NEW", index=True)
    raw: Mapped[dict] = mapped_column(JSON)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "instrument": self.instrument,
            "indicator": self.indicator,
            "signal": self.signal,
            "price": self.price,
            "timeframe": self.timeframe,
            "bar_time": self.bar_time,
            "status": self.status,
            "source_ip": self.source_ip,
        }
