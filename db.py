"""
Database layer - MySQL (built for Aiven, works with any managed MySQL 8.x).

MULTI-TENANT DESIGN
--------------------
This system now works like a small SaaS: every college / exam cell that
signs up (a "COE" - Controller of Examination - account) gets its own,
completely separate MySQL database. One COE's halls, students, exams and
seats can never be read or affected by another COE using the same
deployment.

Two kinds of database are involved:

1. The MASTER (control) database - this is the single database named by
   MYSQL_DATABASE in your environment / .env file. It holds exactly one
   table, `tenants` (see master_schema.sql), which is the registry of every
   COE account: username, hashed password, institution name, and - most
   importantly - `db_name`, the name of that COE's own tenant database.

2. TENANT databases - one per COE, created automatically the moment someone
   signs up (see provision_tenant_db() below). Each tenant database has the
   same schema as before (schema.sql): exams, halls, students, seats,
   allocation_batches. There is no `users` table inside a tenant database
   any more - login now happens against the master `tenants` registry, and
   the tenant database is only ever touched *after* that login has already
   resolved which db_name to use.

Connection settings come from environment variables so nothing is hardcoded:
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE
    MYSQL_SSL_CA (optional - path to Aiven's downloaded ca.pem for verified TLS)

The MYSQL_USER above must be allowed to run CREATE DATABASE / DROP DATABASE
on your Aiven MySQL service (the default `avnadmin` user can). That is how
provision_tenant_db() is able to give every new sign-up its own database
without you doing anything by hand.

For local development, put these in a `.env` file - python-dotenv loads it
automatically. On Render, set them as Environment Variables in the
service's dashboard instead of a .env file.

`MySQLConn` below is a thin wrapper so the rest of the app (app.py) can keep
calling `conn.execute(query, params).fetchone()/.fetchall()` exactly like it
did with sqlite3, using `?` placeholders - the wrapper translates them to
MySQL's `%s` style under the hood.
"""

import os
import re
import uuid
import pymysql
import pymysql.cursors
import pymysql.err

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = os.path.dirname(__file__)
TENANT_SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")
MASTER_SCHEMA_PATH = os.path.join(BASE_DIR, "master_schema.sql")

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


def _connect(database=None):
    """
    Low-level connector. `database=None` connects to the MySQL *server*
    without selecting any database - only used for CREATE DATABASE / DROP
    DATABASE while provisioning or removing a tenant.
    """
    ssl_ca = os.environ.get("MYSQL_SSL_CA")
    ssl_opts = {"ca": ssl_ca} if ssl_ca else {"ssl": {}}  # Aiven requires TLS

    kwargs = dict(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", 3306)),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        cursorclass=pymysql.cursors.DictCursor,
        ssl=ssl_opts,
        autocommit=False,
    )
    if database:
        kwargs["database"] = database

    raw = pymysql.connect(**kwargs)
    return MySQLConn(raw)


def get_master_conn():
    """Connects to the master/control database (the tenant registry)."""
    return _connect(os.environ["MYSQL_DATABASE"])


def get_conn():
    """
    Connects to the *current* COE's own tenant database, resolved from the
    logged-in user's Flask session (session["db_name"], set at login time).

    This is a drop-in replacement for the old single-tenant get_conn(), so
    every existing route in app.py (dashboard, students, exams, halls,
    seat-allocation, reports, ...) keeps working completely unchanged -
    each one automatically talks to the correct tenant's isolated database
    without being rewritten.

    Falls back to the master database if called outside of a logged-in
    request (e.g. from a script) - harmless, since those callers never
    touch tenant-only tables like `students` or `halls`.
    """
    db_name = None
    try:
        from flask import session, has_request_context
        if has_request_context():
            db_name = session.get("db_name")
    except Exception:
        db_name = None
    return _connect(db_name or os.environ["MYSQL_DATABASE"])


# ---------------------------------------------------------------------
# TENANT PROVISIONING
# ---------------------------------------------------------------------
def slugify(text):
    """institution_name -> a safe fragment for a MySQL database name."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:20] or "coe"


def provision_tenant_db(institution_name):
    """
    Creates a brand-new, empty, isolated MySQL database for a newly
    signed-up COE, and runs the tenant schema (schema.sql) against it.
    Returns the generated database name, to be stored on the tenant's row
    in the master `tenants` table.
    """
    db_name = f"tenant_{slugify(institution_name)}_{uuid.uuid4().hex[:6]}"

    admin_conn = _connect(None)
    try:
        admin_conn.execute(
            f"CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        admin_conn.commit()
    finally:
        admin_conn.close()

    tenant_conn = _connect(db_name)
    try:
        with open(TENANT_SCHEMA_PATH, "r") as f:
            tenant_conn.executescript(f.read())
        tenant_conn.commit()
    finally:
        tenant_conn.close()

    return db_name


def drop_tenant_db(db_name):
    """
    Best-effort cleanup: removes a tenant database that was just created
    but whose sign-up could not be completed (e.g. a duplicate username
    slipped in at the last moment). Never raises - this is a safety net,
    not something the request should fail on.
    """
    try:
        admin_conn = _connect(None)
        admin_conn.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
        admin_conn.commit()
        admin_conn.close()
    except Exception:
        pass


def init_master_db():
    """
    Creates the master `tenants` table if it doesn't exist yet. Safe to run
    any number of times - master_schema.sql uses CREATE TABLE IF NOT
    EXISTS, so it will NEVER drop or wipe already-registered COE accounts.
    Run once manually: `python db.py`.
    """
    conn = get_master_conn()
    with open(MASTER_SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------
# TENANT-SIDE HELPERS (unchanged - operate on whichever conn is passed in)
# ---------------------------------------------------------------------
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
    """
    Optional demo data for ONE tenant database - no longer called
    automatically during sign-up (a real COE should start from a clean,
    empty database). Useful for manual testing:

        tenant_conn = db._connect(some_tenant_db_name)
        db.seed_sample_data(tenant_conn)
    """
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
    init_master_db()
    print("Master/control database ready on", os.environ.get("MYSQL_HOST"))
    print("The 'tenants' table now holds one row per COE sign-up.")
    print("Tenant databases are created automatically the moment someone signs up -")
    print("there is nothing else to run by hand.")
