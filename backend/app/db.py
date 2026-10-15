from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import ADDED_COLUMNS, RLS_TABLES, Base

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)
warehouse_engine = create_engine(settings.warehouse_url, pool_pre_ping=True, pool_size=5)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def _scope(session: Session, org_id: int | None, bypass: bool = False) -> None:
    session.execute(text("SELECT set_config('app.org_id', :o, false)"), {"o": str(org_id or "")})
    session.execute(text("SELECT set_config('app.bypass', :b, false)"), {"b": "on" if bypass else "off"})


@contextmanager
def org_session(org_id: int | None, bypass: bool = False) -> Iterator[Session]:
    """A session that can only see rows of one org (enforced by Postgres row-level security)."""
    session = SessionLocal()
    try:
        _scope(session, org_id, bypass)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        _scope(session, None)
        session.commit()
        session.close()


def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("SELECT pg_advisory_xact_lock(424242)"))
        Base.metadata.create_all(conn)
        for table, column, ddl in ADDED_COLUMNS:
            exists = conn.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = :t "
                                       "AND column_name = :c"), {"t": table, "c": column}).scalar()
            if not exists:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        for table in RLS_TABLES:
            # Only take the ALTER TABLE lock when something is missing: the api and worker start together.
            done = conn.execute(text(
                "SELECT c.relforcerowsecurity AND EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename = c.relname "
                "AND p.policyname = 'org_isolation') FROM pg_class c WHERE c.relname = :t"), {"t": table}).scalar()
            if done:
                continue
            conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
            conn.execute(text(f"DROP POLICY IF EXISTS org_isolation ON {table}"))
            conn.execute(text(
                f"CREATE POLICY org_isolation ON {table} USING ("
                "current_setting('app.bypass', true) = 'on' "
                "OR org_id = NULLIF(current_setting('app.org_id', true), '')::int)"
            ))
