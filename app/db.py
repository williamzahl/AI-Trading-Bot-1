"""Databasetilkobling. Bytt database ved aa endre DATABASE_URL, ikke koden."""
import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL

log = logging.getLogger("smt-bot")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _add_missing_columns() -> None:
    """Enkel migrering: legg til nye kolonner i eksisterende tabeller."""
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            col_type = col.type.compile(dialect=engine.dialect)
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}'))
            log.info("La til kolonne %s.%s", table.name, col.name)


def init_db() -> None:
    from app import models  # noqa: F401  (registrerer tabellene)
    Base.metadata.create_all(engine)
    _add_missing_columns()


def get_setting(key: str) -> str | None:
    from app.models import Setting
    with SessionLocal() as s:
        row = s.get(Setting, key)
        return row.value if row else None


def set_setting(key: str, value: str) -> None:
    from app.models import Setting
    with SessionLocal() as s:
        row = s.get(Setting, key)
        if row:
            row.value = value
        else:
            s.add(Setting(key=key, value=value))
        s.commit()
