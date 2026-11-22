"""SQLite project storage and atomic transactions."""

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3

from .contracts import HarnessError, ROOT

DDL = """
CREATE TABLE project (id TEXT PRIMARY KEY, revision INTEGER NOT NULL);
CREATE TABLE evidence (
    field TEXT NOT NULL, revision INTEGER NOT NULL, value TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (field, revision)
);
CREATE TABLE runs (
    id TEXT PRIMARY KEY, registry TEXT NOT NULL, execution TEXT NOT NULL,
    decision_id INTEGER REFERENCES decisions(id)
);
CREATE TABLE decisions (
    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), data TEXT NOT NULL
);
CREATE TABLE artifacts (
    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
    kind TEXT NOT NULL, stale INTEGER NOT NULL DEFAULT 0, data TEXT NOT NULL
);
CREATE UNIQUE INDEX active_artifact ON artifacts(run_id, kind) WHERE stale = 0;
CREATE TABLE tasks (
    run_id TEXT NOT NULL REFERENCES runs(id), stage TEXT NOT NULL, status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0, detail TEXT,
    PRIMARY KEY(run_id, stage)
);
PRAGMA user_version = 1;
"""


class Store:
    def __init__(self, path):
        path = Path(path).resolve()
        if path.is_relative_to(ROOT) or any(
            (p / ".git").exists() for p in path.parents
        ):
            raise HarnessError("keep the project database outside the repository")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        self.db = sqlite3.connect(path, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        try:
            with self.transaction():
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    if self.db.execute(
                        "SELECT name FROM sqlite_master LIMIT 1"
                    ).fetchone():
                        raise HarnessError("unrecognized unversioned database")
                    for statement in DDL.split(";"):
                        if statement.strip():
                            self.db.execute(statement)
                elif version not in (1, 2, 3):
                    raise HarnessError("unsupported database version")
                if version < 2:
                    self.db.execute("ALTER TABLE runs ADD COLUMN plan TEXT")
                    self.db.execute("""CREATE TABLE events (
                        id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                        stage TEXT NOT NULL, attempt INTEGER NOT NULL, data TEXT NOT NULL
                    )""")
                    self.db.execute("PRAGMA user_version = 2")
                if version < 3:
                    self.db.execute("""CREATE TABLE approvals (
                        id TEXT PRIMARY KEY, actor TEXT NOT NULL, operation_digest TEXT NOT NULL,
                        expires INTEGER NOT NULL, state TEXT NOT NULL
                    )""")
                    self.db.execute("""CREATE TABLE tool_events (
                        id INTEGER PRIMARY KEY, operation_id TEXT NOT NULL, event TEXT NOT NULL,
                        data TEXT NOT NULL
                    )""")
                    self.db.execute("PRAGMA user_version = 3")
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
