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

## Tech Stack
- Backend: Flask (Python) with session-based authentication
- Database: MySQL (hosted on Aiven) — tables: `users`, `halls`, `students`, `exams`, `seats`, `allocation_batches`
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
5. (First time only) create the tables + sample data on your Aiven database:
   ```
   python db.py
   ```
6. Start the server:
   ```
   python app.py
   ```
7. Open your browser at **http://127.0.0.1:5000** and log in with the demo credentials below.

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
   tables. Before (or right after) your first deploy, run `python db.py` once
   from your own machine (with the same `.env` pointed at Aiven) so the schema
   and sample data exist in the cloud database. You only do this once; Render
   restarts won't wipe it because the data now lives on Aiven, not on Render's disk.
6. Once live, your Render URL serves the app and every request reads/writes
   straight to your Aiven MySQL — no local file involved at all.

## Default Login
```
Username: admin
Password: admin123
```
Or click "Create one" on the login page to sign up a new admin account
(username ≥ 3 chars, password ≥ 6 chars with a letter and a number).

If you ever want to reset all data, just re-run `python db.py` — it drops and recreates every table on your Aiven database.

## Project Structure
```
exam_hall_system/
├── app.py              # Flask routes, auth, + JSON APIs
├── db.py                # Database connection + seat-generation logic
├── schema.sql            # Table definitions
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
│   └── reports.html
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
- Why MySQL on Aiven? Managed, always-on cloud database that survives redeploys & restarts — unlike a local SQLite file, which gets wiped on most free hosting platforms.
- Why 5 tables? Keeps it normalized: users (auth), halls, students, exams and the
  seat/allocation mapping are all separate concerns.
- Authentication: passwords are never stored in plain text — `werkzeug.security.generate_password_hash`
  is used, and every page/API route is protected with a `login_required` decorator.
- Extendability: could add role-based access (admin vs staff), PDF export, or an
  Excel import for bulk student upload.
