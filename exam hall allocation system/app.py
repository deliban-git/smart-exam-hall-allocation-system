from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import re
import os
import db

app = Flask(__name__)
app.secret_key = "exam-hall-allocation-secret"
app.permanent_session_lifetime = timedelta(days=7)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 5


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapped


def is_strong_password(password):
    """At least 6 chars, with a letter and a number."""
    if len(password) < 6:
        return False
    return bool(re.search(r"[A-Za-z]", password)) and bool(re.search(r"\d", password))


@app.context_processor
def inject_user():
    return {"current_user": session.get("full_name") or session.get("username")}


# ---------------------------------------------------------------------
# AUTH — LOGIN / SIGNUP / LOGOUT
# ---------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip().lower()
        password = request.form["password"]
        remember = request.form.get("remember") == "on"
        conn = db.get_conn()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        # Account lockout check
        if user and user["locked_until"]:
            locked_until = user["locked_until"]
            if isinstance(locked_until, str):  # sqlite stores it as text; mysql returns datetime
                locked_until = datetime.strptime(locked_until, "%Y-%m-%d %H:%M:%S")
            if datetime.now() < locked_until:
                wait_mins = int((locked_until - datetime.now()).seconds / 60) + 1
                conn.close()
                flash(f"Account locked due to too many failed attempts. Try again in {wait_mins} min.", "error")
                return render_template("login.html")

        if user and check_password_hash(user["password_hash"], password):
            conn.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = ? WHERE id = ?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user["id"]),
            )
            conn.commit()
            conn.close()
            session.clear()
            session.permanent = remember
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["full_name"] = user["full_name"]
            next_url = request.args.get("next") or url_for("dashboard")
            return redirect(next_url)

        # Wrong password / unknown user — track failed attempts only for real accounts
        if user:
            attempts = user["failed_attempts"] + 1
            locked_until = None
            if attempts >= MAX_FAILED_ATTEMPTS:
                locked_until = (datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                (attempts, locked_until, user["id"]),
            )
            conn.commit()
        conn.close()
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip().lower()
        full_name = request.form["full_name"].strip()
        password = request.form["password"]
        confirm = request.form["confirm_password"]

        if len(username) < 3:
            flash("Username must be at least 3 characters.", "error")
            return redirect(url_for("signup"))
        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("signup"))
        if not is_strong_password(password):
            flash("Password must be at least 6 characters and include a letter and a number.", "error")
            return redirect(url_for("signup"))

        conn = db.get_conn()
        existing = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            conn.close()
            flash("That username is already taken.", "error")
            return redirect(url_for("signup"))

        conn.execute(
            "INSERT INTO users (username, full_name, password_hash) VALUES (?, ?, ?)",
            (username, full_name, generate_password_hash(password)),
        )
        conn.commit()
        conn.close()
        flash("Account created successfully. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    conn = db.get_conn()

    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        username = request.form["username"].strip().lower()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if len(username) < 3:
            conn.close()
            flash("Username must be at least 3 characters.", "error")
            return redirect(url_for("profile"))

        existing = conn.execute(
            "SELECT id FROM users WHERE username = ? AND id != ?",
            (username, session["user_id"]),
        ).fetchone()
        if existing:
            conn.close()
            flash("That username is already taken.", "error")
            return redirect(url_for("profile"))

        if new_password or confirm_password:
            if new_password != confirm_password:
                conn.close()
                flash("New passwords do not match.", "error")
                return redirect(url_for("profile"))
            if not is_strong_password(new_password):
                conn.close()
                flash("New password must be at least 6 characters and include a letter and a number.", "error")
                return redirect(url_for("profile"))
            conn.execute(
                "UPDATE users SET full_name = ?, username = ?, password_hash = ? WHERE id = ?",
                (full_name, username, generate_password_hash(new_password), session["user_id"]),
            )
        else:
            conn.execute(
                "UPDATE users SET full_name = ?, username = ? WHERE id = ?",
                (full_name, username, session["user_id"]),
            )
        conn.commit()
        conn.close()

        session["username"] = username
        session["full_name"] = full_name
        flash("Profile updated successfully.", "success")
        return redirect(url_for("profile"))

    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    conn.close()
    return render_template("profile.html", user=user)


# ---------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------
@app.route("/")
@login_required
def dashboard():
    conn = db.get_conn()
    total_students = conn.execute("SELECT COUNT(*) c FROM students").fetchone()["c"]
    total_halls = conn.execute("SELECT COUNT(*) c FROM halls").fetchone()["c"]
    total_seats = conn.execute("SELECT COUNT(*) c FROM seats").fetchone()["c"]
    total_exams = conn.execute("SELECT COUNT(*) c FROM exams").fetchone()["c"]
    occupied = conn.execute("SELECT COUNT(*) c FROM seats WHERE reg_no IS NOT NULL").fetchone()["c"]
    halls = conn.execute("SELECT * FROM halls").fetchall()
    conn.close()
    return render_template(
        "dashboard.html",
        total_students=total_students,
        total_halls=total_halls,
        total_seats=total_seats,
        total_exams=total_exams,
        occupied=occupied,
        available=total_seats - occupied,
        halls=halls,
    )


# ---------------------------------------------------------------------
# STUDENT MANAGEMENT
# ---------------------------------------------------------------------
@app.route("/students", methods=["GET", "POST"])
@login_required
def students():
    conn = db.get_conn()
    if request.method == "POST":
        try:
            department = request.form["department"].strip().upper()
            exam_name = request.form["exam_name"].strip()
            exam_date = request.form["exam_date"].strip()
            exam_time = request.form["exam_time"].strip()
            # Link to a real exams.exam_id (creating the exam row if it's new)
            # instead of only storing free-text, so the two tables stay consistent.
            exam_id = db.get_or_link_exam(conn, exam_name, department, exam_date, exam_time)
            conn.execute(
                "INSERT INTO students (reg_no, name, department, year_section, exam_id, exam_name, exam_date, exam_time) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.form["reg_no"].strip().upper(),
                    request.form["name"].strip().upper(),
                    department,
                    request.form["year_section"].strip().upper(),
                    exam_id,
                    exam_name,
                    exam_date,
                    exam_time,
                ),
            )
            conn.commit()
            flash("Student added successfully.", "success")
        except Exception as e:
            flash(f"Error: {e}", "error")
        return redirect(url_for("students"))

    all_students = conn.execute("SELECT * FROM students ORDER BY reg_no").fetchall()
    conn.close()
    return render_template("students.html", students=all_students)


@app.route("/students/delete/<reg_no>", methods=["POST"])
@login_required
def delete_student(reg_no):
    conn = db.get_conn()
    conn.execute("UPDATE seats SET reg_no = NULL WHERE reg_no = ?", (reg_no,))
    conn.execute("DELETE FROM students WHERE reg_no = ?", (reg_no,))
    conn.commit()
    conn.close()
    flash("Student removed.", "success")
    return redirect(url_for("students"))


# ---------------------------------------------------------------------
# EXAM MANAGEMENT
# ---------------------------------------------------------------------
@app.route("/exams", methods=["GET", "POST"])
@login_required
def exams():
    conn = db.get_conn()
    if request.method == "POST":
        try:
            conn.execute(
                "INSERT INTO exams (exam_name, department, exam_date, exam_time, duration) VALUES (?, ?, ?, ?, ?)",
                (
                    request.form["exam_name"].strip(),
                    request.form["department"].strip().upper(),
                    request.form["exam_date"].strip(),
                    request.form["exam_time"].strip(),
                    request.form["duration"].strip(),
                ),
            )
            conn.commit()
            flash("Exam added successfully.", "success")
        except db.IntegrityError:
            flash("An exam with the same name, date and time already exists.", "error")
        return redirect(url_for("exams"))

    all_exams = conn.execute("SELECT * FROM exams ORDER BY exam_id DESC").fetchall()
    conn.close()
    return render_template("exams.html", exams=all_exams)


@app.route("/exams/delete/<int:exam_id>", methods=["POST"])
@login_required
def delete_exam(exam_id):
    conn = db.get_conn()
    conn.execute("DELETE FROM exams WHERE exam_id = ?", (exam_id,))
    conn.commit()
    conn.close()
    flash("Exam removed.", "success")
    return redirect(url_for("exams"))


# ---------------------------------------------------------------------
# HALL MANAGEMENT
# ---------------------------------------------------------------------
@app.route("/halls", methods=["GET", "POST"])
@login_required
def halls():
    conn = db.get_conn()
    if request.method == "POST":
        capacity = int(request.form["capacity"])
        if capacity % 12 != 0:
            flash("Capacity must be a multiple of 12 (3 sides x 4 seats per row).", "error")
            return redirect(url_for("halls"))
        try:
            cur = conn.execute(
                "INSERT INTO halls (hall_no, capacity, floor, building, per_bench) VALUES (?, ?, ?, ?, 2)",
                (
                    request.form["hall_no"].strip().upper(),
                    capacity,
                    request.form["floor"].strip(),
                    request.form["building"].strip().upper(),
                ),
            )
            db.generate_seats_for_hall(conn, cur.lastrowid, capacity)
            flash("Hall added and seats generated.", "success")
        except db.IntegrityError:
            flash("A hall with that hall number already exists.", "error")
        return redirect(url_for("halls"))

    all_halls = conn.execute("SELECT * FROM halls").fetchall()
    conn.close()
    return render_template("halls.html", halls=all_halls)


@app.route("/halls/delete/<int:hall_id>", methods=["POST"])
@login_required
def delete_hall(hall_id):
    conn = db.get_conn()
    conn.execute("DELETE FROM seats WHERE hall_id = ?", (hall_id,))
    conn.execute("DELETE FROM halls WHERE hall_id = ?", (hall_id,))
    conn.commit()
    conn.close()
    flash("Hall removed.", "success")
    return redirect(url_for("halls"))


# ---------------------------------------------------------------------
# ALLOCATION VIEW (overview of every hall's occupancy)
# ---------------------------------------------------------------------
@app.route("/allocation-view")
@login_required
def allocation_view():
    conn = db.get_conn()
    halls_rows = conn.execute("SELECT * FROM halls").fetchall()
    hall_cards = []
    for h in halls_rows:
        total = conn.execute("SELECT COUNT(*) c FROM seats WHERE hall_id = ?", (h["hall_id"],)).fetchone()["c"]
        occ = conn.execute(
            "SELECT COUNT(*) c FROM seats WHERE hall_id = ? AND reg_no IS NOT NULL", (h["hall_id"],)
        ).fetchone()["c"]
        pct = round((occ / total) * 100) if total else 0
        hall_cards.append({"hall": h, "total": total, "occupied": occ, "available": total - occ, "pct": pct})
    conn.close()
    return render_template("allocation_view.html", hall_cards=hall_cards)


# ---------------------------------------------------------------------
# SEAT ALLOCATION PAGE (main screen)
# ---------------------------------------------------------------------
@app.route("/seat-allocation")
@login_required
def seat_allocation():
    conn = db.get_conn()
    halls_list = conn.execute("SELECT * FROM halls").fetchall()
    hall_id = request.args.get("hall_id", type=int)
    if not hall_id and halls_list:
        hall_id = halls_list[0]["hall_id"]
    conn.close()
    return render_template("seat_allocation.html", halls=halls_list, selected_hall_id=hall_id)


# ---------------------------------------------------------------------
# JSON APIs used by the seat-allocation page (fetch/AJAX)
# ---------------------------------------------------------------------
@app.route("/api/student/<reg_no>")
@login_required
def api_student(reg_no):
    conn = db.get_conn()
    s = conn.execute("SELECT * FROM students WHERE reg_no = ?", (reg_no.upper(),)).fetchone()
    if not s:
        conn.close()
        return jsonify({"found": False})
    seat = conn.execute(
        "SELECT seats.seat_no, seats.side, halls.hall_no FROM seats "
        "JOIN halls ON halls.hall_id = seats.hall_id WHERE seats.reg_no = ?",
        (reg_no.upper(),),
    ).fetchone()
    conn.close()
    result = dict(s)
    result["found"] = True
    result["seat"] = dict(seat) if seat else None
    return jsonify(result)


@app.route("/api/hall/<int:hall_id>")
@login_required
def api_hall(hall_id):
    conn = db.get_conn()
    hall = conn.execute("SELECT * FROM halls WHERE hall_id = ?", (hall_id,)).fetchone()
    if not hall:
        conn.close()
        return jsonify({"found": False}), 404

    seats = conn.execute(
        "SELECT seats.seat_no, seats.side, seats.row_no, seats.reg_no, students.name "
        "FROM seats LEFT JOIN students ON students.reg_no = seats.reg_no "
        "WHERE seats.hall_id = ? ORDER BY seats.seat_no",
        (hall_id,),
    ).fetchall()

    occupied = sum(1 for s in seats if s["reg_no"])
    conn.close()

    return jsonify(
        {
            "found": True,
            "hall": dict(hall),
            "seats": [dict(s) for s in seats],
            "occupied": occupied,
            "available": len(seats) - occupied,
            "total": len(seats),
        }
    )


@app.route("/api/allocate", methods=["POST"])
@login_required
def api_allocate():
    """
    Auto-allocate every student (in register-number order) into consecutive
    seat groups of size `per_bench` within the selected hall.
    Clears any previous allocation for that hall first.
    """
    data = request.get_json()
    hall_id = data["hall_id"]
    per_bench = max(1, min(4, int(data.get("per_bench", 2))))
    comment = data.get("comment", "")

    conn = db.get_conn()
    conn.execute("UPDATE halls SET per_bench = ? WHERE hall_id = ?", (per_bench, hall_id))
    conn.execute("UPDATE seats SET reg_no = NULL WHERE hall_id = ?", (hall_id,))

    seats = conn.execute(
        "SELECT id, seat_no FROM seats WHERE hall_id = ? ORDER BY seat_no", (hall_id,)
    ).fetchall()
    students_list = conn.execute("SELECT reg_no FROM students ORDER BY reg_no").fetchall()

    # Build bench groups of `per_bench` consecutive seats, then fill one student per seat.
    seat_ids = [row["id"] for row in seats]
    benches = [seat_ids[i : i + per_bench] for i in range(0, len(seat_ids), per_bench)]

    allocated = 0
    student_idx = 0
    for bench in benches:
        for seat_id in bench:
            if student_idx >= len(students_list):
                break
            reg_no = students_list[student_idx]["reg_no"]
            conn.execute("UPDATE seats SET reg_no = ? WHERE id = ?", (reg_no, seat_id))
            student_idx += 1
            allocated += 1
        if student_idx >= len(students_list):
            break

    # Audit trail: record this allocation run instead of leaving no history at all.
    conn.execute(
        "INSERT INTO allocation_batches (hall_id, exam_id, per_bench, seats_filled, comment) "
        "VALUES (?, ?, ?, ?, ?)",
        (hall_id, data.get("exam_id"), per_bench, allocated, comment),
    )

    conn.commit()
    conn.close()

    return jsonify(
        {
            "success": True,
            "allocated": allocated,
            "total_students": len(students_list),
            "comment": comment,
        }
    )


@app.route("/api/clear/<int:hall_id>", methods=["POST"])
@login_required
def api_clear(hall_id):
    conn = db.get_conn()
    conn.execute("UPDATE seats SET reg_no = NULL WHERE hall_id = ?", (hall_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/occupation-list/<int:hall_id>")
@login_required
def api_occupation_list(hall_id):
    conn = db.get_conn()
    hall = conn.execute("SELECT * FROM halls WHERE hall_id = ?", (hall_id,)).fetchone()
    per_bench = hall["per_bench"] if hall else 2

    seats = conn.execute(
        "SELECT seats.seat_no, seats.reg_no, students.name FROM seats "
        "LEFT JOIN students ON students.reg_no = seats.reg_no "
        "WHERE seats.hall_id = ? ORDER BY seats.seat_no",
        (hall_id,),
    ).fetchall()
    conn.close()

    rows = []
    for i in range(0, len(seats), per_bench):
        group = seats[i : i + per_bench]
        occupied_seats = [g for g in group if g["reg_no"]]
        if not occupied_seats:
            continue
        seat_range = f"{group[0]['seat_no']}-{group[-1]['seat_no']}" if len(group) > 1 else str(group[0]["seat_no"])
        for g in occupied_seats:
            rows.append({"seat_range": seat_range, "reg_no": g["reg_no"], "name": g["name"]})

    return jsonify({"rows": rows, "per_bench": per_bench})


# ---------------------------------------------------------------------
# SEARCH STUDENT (standalone page, same search box logic reused)
# ---------------------------------------------------------------------
@app.route("/search-student")
@login_required
def search_student():
    return render_template("search_student.html")


# ---------------------------------------------------------------------
# REPORTS
# ---------------------------------------------------------------------
@app.route("/reports")
@login_required
def reports():
    conn = db.get_conn()
    data = conn.execute(
        "SELECT halls.hall_no, halls.building, seats.seat_no, seats.reg_no, students.name, "
        "students.department, students.exam_name "
        "FROM seats "
        "JOIN halls ON halls.hall_id = seats.hall_id "
        "LEFT JOIN students ON students.reg_no = seats.reg_no "
        "WHERE seats.reg_no IS NOT NULL "
        "ORDER BY halls.hall_no, seats.seat_no"
    ).fetchall()
    conn.close()
    return render_template("reports.html", rows=data)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)