# Smart Exam Hall Allocation System

A simple college mini-project: automated exam hall & seat allocation system.
Built with **Python Flask** (backend) + **MySQL on Aiven** (cloud database) + **HTML/CSS/JS** (frontend), deployed on **Render**.

## Features
- **Login / Sign Up** — secure admin authentication (passwords hashed with Werkzeug), animated auth screens
- **Dashboard** — animated stat cards (students, halls, exams, occupied/available seats)
- **Student Management** — add / view / delete students
- **Exam Management** — add / view / delete exams (name, department, date, time, duration)
- **Hall Management** — add halls (seat layout auto-generated: Left / Centre / Right, 3 sides x 4 seats/row)
- **Seat Allocation** — search a student, pick a hall, see the live seating layout,
  set "students per bench" (1–4), auto-allocate seats, view the occupation list, print/download
- **Allocation View** — visual overview of every hall's occupancy with animated progress bars
- **Search Student** — standalone lookup page
- **Reports** — full allocation report, printable
- **Polished UI/UX** — Google Fonts (Poppins/Inter), gradient topbar & auth screens, hover/lift
  animations on cards & buttons, animated progress bars, animated dashboard counters, fade-in
  page transitions, fully responsive (desktop/tablet/mobile with a collapsible sidebar)

## Multi-Tenant Design (one database per COE)
This system works like a small SaaS. Anyone can sign up, but a sign-up
represents one **COE (Controller of Examination)** office — one college's
exam cell — not an individual staff member. The moment someone signs up:
1. Their username is checked against a single, global registry (the
   `tenants` table in your **master** database — the one named by
   `MYSQL_DATABASE`), so **no two COEs can ever share a username**, enforced
   both in code and by a `UNIQUE` constraint in MySQL itself.
2. A brand-new, empty MySQL database is created automatically just for
   them (`db.provision_tenant_db()` in `db.py`), and the usual tables
   (`exams`, `halls`, `students`, `seats`, `allocation_batches`) are created
   inside it.
3. From then on, every page they use (dashboard, students, halls, seat
   allocation, reports, ...) reads and writes only to that COE's own
   database — another college signing up on the same deployment can never
   see or affect their halls, students or seat allocations.

Your `MYSQL_USER` needs permission to run `CREATE DATABASE` / `DROP DATABASE`
on your Aiven MySQL service for this to work (the default `avnadmin` user has
this by default).

## Tech Stack
- Backend: Flask (Python) with session-based authentication
- Database: MySQL (hosted on Aiven), multi-tenant — one **master** database
  holding the `tenants` registry, plus one isolated **tenant** database per
  COE sign-up (`exams`, `halls`, `students`, `seats`, `allocation_batches`)
- Frontend: HTML + CSS (custom animations, no framework) + vanilla JavaScript (fetch/AJAX)

## How to Run
1. Install Python 3 (3.9+) if not already installed.
2. Open a terminal in this folder and install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create an **Aiven MySQL** service (free plan works):
   - Sign up at https://aiven.io → Create service → **MySQL** → pick a free/cheap plan and region.
   - Once it's running, open the service's **Overview** tab and note: Host, Port, User (`avnadmin`), Password, Database name (`defaultdb`).
   - (Optional, more secure) Download the **CA Certificate** shown there and save it as `ca.pem` in this folder.
4. Copy `.env.example` to `.env` and fill in those Aiven values:
   ```
   cp .env.example .env
   ```
   `MYSQL_DATABASE` becomes your **master/control** database (the COE
   registry) — leave it as your Aiven default (`defaultdb`) unless you
   created a separate one. Tenant databases are created automatically later;
   you don't need to create anything else by hand.
5. (First time only) create the master `tenants` table:
   ```
   python db.py
   ```
   This is safe to re-run any time — it only creates the `tenants` table if
   it doesn't already exist, and never touches any COE's data.
6. Start the server:
   ```
   python app.py
   ```
7. Open your browser at **http://127.0.0.1:5000**, click **Create one**, and
   sign up your first COE account (see "Signing Up" below).

## Deploying to Render (with Aiven MySQL)
1. Push this project to a GitHub repo.
2. On Render.com → **New +** → **Web Service** → connect your repo.
3. Build command: `pip install -r requirements.txt`
   Start command: `gunicorn app:app`
4. Under the service's **Environment** tab, add the same keys as `.env.example`
   (`MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`,
   and `MYSQL_SSL_CA` if you're using a CA file — upload it as a **Secret File** in
   Render and point `MYSQL_SSL_CA` to its mounted path).
5. Deploy. Render only builds and runs `app.py` — it does **not** create your
   master table. Before (or right after) your first deploy, run `python db.py` once
   from your own machine (with the same `.env` pointed at Aiven) so the `tenants`
   table exists in the cloud database. You only do this once; every COE that
   signs up afterwards gets their tenant database created automatically by the
   running app itself — no further manual steps, ever.
6. Once live, your Render URL serves the app and every request reads/writes
   straight to your Aiven MySQL — no local file involved at all.

## Signing Up (COE accounts)
Sign-up is open to anyone, but each sign-up should represent one COE
(Controller of Examination) office for one college — enter your college /
COE's name, pick a username (must be at least 3 characters, and **must be
globally unique** — the system will not let two sign-ups share one), and a
password (≥ 6 chars with a letter and a number). Signing up immediately
provisions that COE's own isolated database — there is no shared default
login any more; every COE starts from a clean, empty account.

If you ever want to wipe **one specific COE's** data, drop that COE's tenant
database directly on Aiven (its name is the `db_name` column on that row of
the master `tenants` table) — this will never affect any other COE.
Re-running `python db.py` only touches the master `tenants` table and is
safe at any time; it will never delete a COE's data or account.

## Project Structure
```
exam_hall_system/
├── app.py              # Flask routes, auth, + JSON APIs
├── db.py                # Master + tenant DB connections, provisioning, seat-generation logic
├── master_schema.sql     # Master DB: `tenants` registry (one row per COE)
├── schema.sql            # Tenant DB: exams/halls/students/seats/allocation_batches
├── requirements.txt
├── templates/            # HTML pages (Jinja2)
│   ├── base.html
│   ├── login.html
│   ├── signup.html
│   ├── dashboard.html
│   ├── students.html
│   ├── exams.html
│   ├── halls.html
│   ├── seat_allocation.html
│   ├── allocation_view.html
│   ├── search_student.html
│   ├── reports.html
│   └── profile.html
└── static/
    └── css/style.css     # theme, animations, responsive breakpoints
```

## How Seat Numbering Works
For a hall of capacity C:
- Left side gets seats `1 .. C/3`
- Centre gets seats `C/3+1 .. 2C/3`
- Right side gets seats `2C/3+1 .. C`
- Each side is arranged in rows of 4 seats.

So capacity must be a multiple of 12 (3 sides × 4 seats/row).

## How Auto-Allocation Works
1. All students are fetched in register-number order.
2. Seats in the chosen hall are grouped into "benches" of size = *students per bench* (1–4),
   taken as consecutive seat numbers.
3. Students are filled into these benches in order until either all seats or all students
   run out.
4. The **Occupation List** groups seat numbers by bench and shows who is sitting where —
   this is what you'd print and stick outside the hall.

## Possible Viva Talking Points
- Why multi-tenant (database-per-COE)? Stronger isolation than a shared `tenant_id` column — a bug in a WHERE clause can leak data across tenants in a shared-table design, but cannot do so at all when each COE's data lives in an entirely separate MySQL database.
- Why MySQL on Aiven? Managed, always-on cloud database that survives redeploys & restarts — unlike a local SQLite file, which gets wiped on most free hosting platforms.
- Why 6 tables across 2 databases? Keeps it normalized: the master `tenants` table (auth + tenant registry) is separate from each COE's own `halls`, `students`, `exams`, `seats` and `allocation_batches`.
- Uniqueness: `tenants.username` has a MySQL `UNIQUE` constraint, so two COEs can never share a username even under concurrent sign-ups — the app also pre-checks it and cleans up (drops) the tenant database it had just created if a race condition is caught as `db.IntegrityError`.
- Authentication: passwords are never stored in plain text — `werkzeug.security.generate_password_hash`
  is used, and every page/API route is protected with a `login_required` decorator.
- Extendability: could add role-based access (admin vs staff) *within* a COE, PDF export, or an
  Excel import for bulk student upload.
