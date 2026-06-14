"""Lightweight SQLite migrations for existing installs."""

from sqlalchemy import inspect, text

from app.db.session import engine


def run_migrations() -> None:
    insp = inspect(engine)
    if "form_types" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("form_types")}
    with engine.begin() as conn:
        if "field_styles_json" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE form_types ADD COLUMN field_styles_json TEXT"
                )
            )
