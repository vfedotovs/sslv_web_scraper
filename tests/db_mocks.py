"""Shared fake psycopg2 connection/cursor for db_worker tests.

Emulates just enough SQL for the queries db_worker issues:
- CREATE TABLE IF NOT EXISTS (no-op)
- SELECT COUNT(*) FROM listed_ads / removed_ads
- SELECT 1 FROM listed_ads LIMIT 1  (emptiness probe)
- SELECT url_hash FROM listed_ads ORDER BY url_hash
- SELECT <cols> FROM listed_ads WHERE url_hash = ANY(%s)
- DELETE FROM listed_ads WHERE url_hash = ANY(%s)
- executemany (recorded only)

Table rows use the listed_ads column order:
(url_hash, room_count, house_floors, apt_floor, price, sqm, sqm_price,
 apt_address, list_date, days_listed)
"""


class FakeCursor:
    def __init__(self, table_rows):
        self.table = list(table_rows)
        self.executed = []           # list of (sql, params)
        self.executemany_calls = []  # list of (sql, rows)
        self._result = []
        self._idx = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._idx = 0
        s = " ".join(sql.split())
        if s.startswith("CREATE TABLE"):
            self._result = []
        elif "COUNT(*) FROM listed_ads" in s:
            self._result = [(len(self.table),)]
        elif "COUNT(*) FROM removed_ads" in s:
            self._result = [(0,)]
        elif s.startswith("SELECT 1 FROM listed_ads"):
            self._result = [(1,)] if self.table else []
        elif "WHERE url_hash = ANY" in s:
            matching = [r for r in self.table if r[0] in set(params[0])]
            if s.startswith("SELECT url_hash, list_date, days_listed"):
                self._result = [(r[0], r[8], r[9]) for r in matching]
            else:
                self._result = matching
        elif s.startswith("SELECT url_hash FROM listed_ads"):
            self._result = [(r[0],) for r in sorted(self.table)]
        else:
            self._result = list(self.table)

    def executemany(self, sql, rows):
        self.executemany_calls.append((sql, list(rows)))

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        if self._idx < len(self._result):
            row = self._result[self._idx]
            self._idx += 1
            return row
        return None

    def close(self):
        pass


class FakeConn:
    def __init__(self, table_rows):
        self.cur = FakeCursor(table_rows)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def mock_db(monkeypatch, db_worker_module, table_rows):
    """Patch config + psycopg2.connect so every connect returns the same
    FakeConn preloaded with table_rows; returns that FakeConn."""
    conn = FakeConn(table_rows)
    monkeypatch.setattr(db_worker_module, "config", lambda: {})
    monkeypatch.setattr(
        db_worker_module.psycopg2, "connect", lambda **kw: conn
    )
    return conn
