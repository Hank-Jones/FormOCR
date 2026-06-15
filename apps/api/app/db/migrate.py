"""Lightweight SQLite migrations for existing installs."""

from sqlalchemy import inspect, text

from app.db.session import engine

_FORM_TYPES_NAME_NORM_INDEX = "ix_form_types_name_norm_unique"


def _ensure_form_type_name_index() -> None:
    with engine.begin() as conn:
        dupes = conn.execute(
            text(
                """
                SELECT
                    lower(trim(name)) AS normalized,
                    group_concat('id=' || id || ' name=' || quote(name), '; ') AS items
                FROM form_types
                GROUP BY lower(trim(name))
                HAVING count(*) > 1
                """
            )
        ).fetchall()
        if dupes:
            details = "; ".join(
                f"{row._mapping['normalized'] or '<empty>'}: {row._mapping['items']}"
                for row in dupes
            )
            raise RuntimeError(
                "Duplicate form type names differ only by case/spacing. "
                f"Rename duplicates before migration can continue: {details}"
            )
        conn.execute(
            text(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS {_FORM_TYPES_NAME_NORM_INDEX}
                ON form_types (lower(trim(name)))
                """
            )
        )


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
    _ensure_form_type_name_index()
