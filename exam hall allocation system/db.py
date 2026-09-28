"""
Database layer - MySQL (built for Aiven, works with any managed MySQL 8.x).

Connection settings come from environment variables so nothing is hardcoded:
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE
    MYSQL_SSL_CA (optional - path to Aiven's downloaded ca.pem for verified TLS)

For local development, put these in a `.env` file (see .env.example) -
python-dotenv loads it automatically. On Render, set them as Environment
Variables in the service's dashboard instead of a .env file.

`MySQLConn` below is a thin wrapper so the rest of the app (app.py) can keep
calling `conn.execute(query, params).fetchone()/.fetchall()` exactly like it
did with sqlite3, using `?` placeholders - the wrapper translates them to
MySQL's `%s` style under the hood.
"""

import os
import pymysql
import pymysql.cursors
import pymysql.err

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

# Re-exported so app.py can catch db.IntegrityError without importing pymysql itself.
IntegrityError = pymysql.err.IntegrityError


class ExecResult:
    """Wraps a pymysql cursor so callers get sqlite3-style .fetchone()/.fetchall()/.lastrowid."""

    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = cursor.lastrowid
        self.rowcount = cursor.rowcount

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class MySQLConn:
    """Thin sqlite3-like wrapper around a pymysql connection."""

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, query, params=()):
        cur = self._conn.cursor()
        cur.execute(query.replace("?", "%s"), params)
        return ExecResult(cur)

    def executemany(self, query, seq_of_params):
        cur = self._conn.cursor()
        cur.executemany(query.replace("?", "%s"), list(seq_of_params))
        return ExecResult(cur)

    def executescript(self, script):
        """Runs a .sql file's statements one by one (MySQL has no native executescript)."""
        cur = self._conn.cursor()
        for statement in script.split(";"):
            stmt = statement.strip()
            if stmt:
                cur.execute(stmt)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_conn():
    ssl_ca = os.environ.get("MYSQL_SSL_CA")
    ssl_opts = {"ca": ssl_ca} if ssl_ca else {"ssl": {}}  # Aiven requires TLS

    raw = pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", 3306)),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        cursorclass=pymysql.cursors.DictCursor,
        ssl=ssl_opts,
        autocommit=False,
    )
    return MySQLConn(raw)


def init_db(with_sample_data=True):
    """Creates tables fresh. Run once manually: `python db.py`."""
    conn = get_conn()
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()

    if with_sample_data:
        seed_sample_data(conn)

    conn.close()


def get_or_link_exam(conn, exam_name, department, exam_date, exam_time, duration=""):
    """
    Finds an existing exam row matching (name, date, time) and returns its id.
    If none exists yet, creates one. This is how the free-text exam fields on
    the student form get linked to a real exams.exam_id behind the scenes,
    without changing the UI.
    """
    row = conn.execute(
        "SELECT exam_id FROM exams WHERE exam_name = ? AND exam_date = ? AND exam_time = ?",
        (exam_name, exam_date, exam_time),
    ).fetchone()
    if row:
        return row["exam_id"]
    cur = conn.execute(
        "INSERT INTO exams (exam_name, department, exam_date, exam_time, duration) VALUES (?, ?, ?, ?, ?)",
        (exam_name, department, exam_date, exam_time, duration),
    )
    return cur.lastrowid


def generate_seats_for_hall(conn, hall_id, capacity):
    """
    Recreates the seat layout for a hall based on capacity.
    Capacity is split into 3 equal sides: LEFT, CENTRE, RIGHT (4 columns each).
    Numbering matches the reference UI:
      LEFT   -> 1 .. capacity/3
      CENTRE -> capacity/3+1 .. 2*capacity/3
      RIGHT  -> 2*capacity/3+1 .. capacity
    """
    conn.execute("DELETE FROM seats WHERE hall_id = ?", (hall_id,))

    per_side = capacity // 3
    rows = per_side // 4  # 4 seats per row per side

    sides = [("LEFT", 0), ("CENTRE", per_side), ("RIGHT", 2 * per_side)]

    for side_name, offset in sides:
        for r in range(1, rows + 1):
            for c in range(1, 5):
                seat_no = offset + (r - 1) * 4 + c
                conn.execute(
                    "INSERT INTO seats (hall_id, seat_no, side, row_no, reg_no) "
                    "VALUES (?, ?, ?, ?, NULL)",
                    (hall_id, seat_no, side_name, r),
                )
    conn.commit()


def seed_sample_data(conn):
    from werkzeug.security import generate_password_hash

    # Default admin login (username: admin / password: admin123)
    conn.execute(
        "INSERT INTO users (username, full_name, password_hash) VALUES (?, ?, ?)",
        ("admin", "Administrator", generate_password_hash("admin123")),
    )

    dbms_exam_id = get_or_link_exam(conn, "DBMS - Internal Test", "CSE", "30-05-2025", "10:00 AM", "3 hrs")
    get_or_link_exam(conn, "Operating Systems - Model Exam", "CSE", "02-06-2025", "01:00 PM", "3 hrs")

    # Sample hall matching the reference screenshot
    cur = conn.execute(
        "INSERT INTO halls (hall_no, capacity, floor, building, per_bench) "
        "VALUES (?, ?, ?, ?, ?)",
        ("HALL - 02", 72, "Ground Floor", "Block A", 2),
    )
    hall_id = cur.lastrowid
    generate_seats_for_hall(conn, hall_id, 72)

    # A second sample hall
    cur2 = conn.execute(
        "INSERT INTO halls (hall_no, capacity, floor, building, per_bench) "
        "VALUES (?, ?, ?, ?, ?)",
        ("HALL - 01", 60, "First Floor", "Block A", 2),
    )
    generate_seats_for_hall(conn, cur2.lastrowid, 60)

    # Sample students
    students = [
        ("23CSE078", "PRITHVI AMIR", "CSE", "IV / A", "DBMS - Internal Test", "30-05-2025", "10:00 AM"),
        ("23CSE101", "KARTHIK RAJ", "CSE", "IV / A", "DBMS - Internal Test", "30-05-2025", "10:00 AM"),
        ("23CSE045", "GOKUL S", "CSE", "IV / B", "DBMS - Internal Test", "30-05-2025", "10:00 AM"),
        ("23CSE067", "SANTHOSH M", "CSE", "IV / B", "DBMS - Internal Test", "30-05-2025", "10:00 AM"),
        ("23CSE032", "VIGNESH V", "CSE", "IV / A", "DBMS - Internal Test", "30-05-2025", "10:00 AM"),
        ("23CSE050", "ARUN KUMAR", "CSE", "IV / A", "DBMS - Internal Test", "30-05-2025", "10:00 AM"),
        ("23CSE055", "DEEPAK S", "CSE", "IV / B", "DBMS - Internal Test", "30-05-2025", "10:00 AM"),
        ("23CSE060", "MOHAMMED ALI", "CSE", "IV / A", "DBMS - Internal Test", "30-05-2025", "10:00 AM"),
    ]
    conn.executemany(
        "INSERT INTO students (reg_no, name, department, year_section, exam_id, exam_name, exam_date, exam_time) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(r, n, d, y, dbms_exam_id, en, ed, et) for (r, n, d, y, en, ed, et) in students],
    )
    conn.commit()


if __name__ == "__main__":
    init_db()
    print("MySQL database initialised on", os.environ.get("MYSQL_HOST"))
