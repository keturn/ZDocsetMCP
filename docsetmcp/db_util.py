import sqlite3
from pathlib import Path


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    # immutable is necessary to convince it to open a WAL-mode database in a read-only mount, otherwise
    # sqlite fails with "unable to open database file (14)" See https://sqlite.org/wal.html#read_only_databases
    uri = db_path.absolute().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True, autocommit=False)
    return conn


def escape_like_pattern(s: str, escape: str = "\x1b") -> str:
    """Escape special characters for SQL LIKE patterns.

    Must be used in conjunction with an ESCAPE clause in the SQL query, e.g.:
    ... LIKE ? ESCAPE char(0x1B)
    """
    return s.replace(escape, escape + escape).replace("%", escape + "%").replace("_", escape + "_")


def table_exists(cursor: sqlite3.Cursor, table_name: str) -> str | None:
    for row in cursor.execute("PRAGMA table_list"):
        if row[1] == table_name:
            return row[1]
    return None


def has_column(cursor: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    # API has no way to use string input as a safe parameter naming a table, so we check it against the current tables.
    if safe_table_name := table_exists(cursor, table_name):
        return any(
            row[1] == column_name for row in cursor.execute(f"PRAGMA table_info({safe_table_name})")
        )
    else:
        raise ValueError(f"{table_name} does not exist")


def make_unique[T](small_list: list[T]) -> list[T]:
    """Make a list unique while preserving order.

    Modifies the list in place.
    """
    for i in range(len(small_list) - 1, 1, -1):
        if small_list[i] in small_list[:i]:
            small_list.pop(i)
    return small_list
