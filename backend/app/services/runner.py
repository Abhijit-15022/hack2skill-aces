"""Runs SQL models from ./pipelines/models against the warehouse database (called by the pipeline runner or an external orchestrator)."""
from pathlib import Path

from sqlalchemy import text

from .. import models as m
from ..config import get_settings
from ..db import SessionLocal, warehouse_engine

settings = get_settings()


def model_path(name: str) -> Path:
    path = (Path(settings.pipelines_dir) / "models" / f"{name}.sql").resolve()
    if path.parent != (Path(settings.pipelines_dir) / "models").resolve():
        raise ValueError("Invalid model name.")
    return path


def run_model(name: str, execution_id: str | None = None) -> tuple[bool, str | None]:
    sql = model_path(name).read_text()
    error = None
    try:
        with warehouse_engine.begin() as conn:
            conn.execute(text(sql))
    except Exception as exc:
        error = str(getattr(exc, "orig", exc)).strip()
    with SessionLocal() as db:
        db.add(m.RunnerRun(model=name, status="failed" if error else "success", error=error, sql=sql,
                           execution_id=execution_id))
        db.commit()
    return error is None, error


def table_columns(schema: str, table: str) -> list[str]:
    with warehouse_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=:s AND table_name=:t "
            "ORDER BY ordinal_position"), {"s": schema, "t": table})
        return [r[0] for r in rows]


def row_count(schema: str, table: str) -> int | None:
    try:
        with warehouse_engine.connect() as conn:
            return conn.execute(text(f'SELECT count(*) FROM "{schema}"."{table}"')).scalar()
    except Exception:
        return None
