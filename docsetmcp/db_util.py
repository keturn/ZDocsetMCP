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


def make_unique[T](small_list: list[T]) -> list[T]:
    """Make a list unique while preserving order.

    Modifies the list in place.
    """
    for i in range(len(small_list) - 1, 1, -1):
        if small_list[i] in small_list[:i]:
            small_list.pop(i)
    return small_list
