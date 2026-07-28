"""Shared helpers for migrations — guard against duplicate columns/tables."""
import sqlalchemy as sa
from alembic import op


def add_column_safe(table: str, col: sa.Column):
    """Add a column only if it doesn't already exist."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if table not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns(table)]
    if col.name not in columns:
        op.add_column(table, col)


def drop_column_safe(table: str, column: str):
    """Drop a column only if it exists."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if table not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns(table)]
    if column in columns:
        op.drop_column(table, column)


def index_exists(table: str, index: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if table not in inspector.get_table_names():
        return False
    return index in [idx["name"] for idx in inspector.get_indexes(table)]


def table_exists(table: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return table in inspector.get_table_names()
