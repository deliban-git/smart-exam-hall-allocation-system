-- Smart Exam Hall Allocation System - Database Schema (MySQL / Aiven)
-- Run this once (via `python db.py`) after your Aiven MySQL service is ready.

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS allocation_batches;
DROP TABLE IF EXISTS seats;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS halls;
DROP TABLE IF EXISTS exams;
DROP TABLE IF EXISTS users;
SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE users (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(50) UNIQUE NOT NULL,
    full_name       VARCHAR(120),
    password_hash   VARCHAR(255) NOT NULL,
    role            ENUM('admin', 'staff') NOT NULL DEFAULT 'admin',
    failed_attempts INT NOT NULL DEFAULT 0,
    locked_until    DATETIME NULL,
    last_login_at   DATETIME NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE exams (
    exam_id     INT AUTO_INCREMENT PRIMARY KEY,
    exam_name   VARCHAR(150) NOT NULL,
    department  VARCHAR(50),
    exam_date   VARCHAR(20) NOT NULL,
    exam_time   VARCHAR(20) NOT NULL,
    duration    VARCHAR(30),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_exam (exam_name, exam_date, exam_time)
) ENGINE=InnoDB;

CREATE TABLE halls (
    hall_id     INT AUTO_INCREMENT PRIMARY KEY,
    hall_no     VARCHAR(50) UNIQUE NOT NULL,
    capacity    INT NOT NULL,
    floor       VARCHAR(50),
    building    VARCHAR(50),
    per_bench   INT NOT NULL DEFAULT 2,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_capacity  CHECK (capacity > 0 AND capacity % 12 = 0),
    CONSTRAINT chk_per_bench CHECK (per_bench BETWEEN 1 AND 4)
) ENGINE=InnoDB;

CREATE TABLE students (
    reg_no       VARCHAR(20) PRIMARY KEY,
    name         VARCHAR(120) NOT NULL,
    department   VARCHAR(50),
    year_section VARCHAR(30),
    -- Point-in-time snapshot columns kept alongside the real FK (see notes
    -- from the earlier SQLite version) so old records stay readable.
    exam_id      INT NULL,
    exam_name    VARCHAR(150),
    exam_date    VARCHAR(20),
    exam_time    VARCHAR(20),
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_students_exam FOREIGN KEY (exam_id) REFERENCES exams(exam_id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE seats (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    hall_id   INT NOT NULL,
    seat_no   INT NOT NULL,
    side      ENUM('LEFT', 'CENTRE', 'RIGHT') NOT NULL,
    row_no    INT NOT NULL,
    reg_no    VARCHAR(20) NULL,
    CONSTRAINT fk_seats_hall FOREIGN KEY (hall_id) REFERENCES halls(hall_id) ON DELETE CASCADE,
    CONSTRAINT fk_seats_student FOREIGN KEY (reg_no) REFERENCES students(reg_no) ON DELETE SET NULL,
    UNIQUE KEY uniq_hall_seat (hall_id, seat_no)
) ENGINE=InnoDB;

CREATE TABLE allocation_batches (
    batch_id     INT AUTO_INCREMENT PRIMARY KEY,
    hall_id      INT NOT NULL,
    exam_id      INT NULL,
    per_bench    INT NOT NULL,
    seats_filled INT NOT NULL,
    comment      VARCHAR(200),
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_batches_hall FOREIGN KEY (hall_id) REFERENCES halls(hall_id) ON DELETE CASCADE,
    CONSTRAINT fk_batches_exam FOREIGN KEY (exam_id) REFERENCES exams(exam_id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE INDEX idx_seats_hall        ON seats(hall_id);
CREATE INDEX idx_seats_regno       ON seats(reg_no);
CREATE INDEX idx_students_exam     ON students(exam_id);
CREATE INDEX idx_students_dept     ON students(department);
CREATE INDEX idx_exams_date        ON exams(exam_date);
CREATE INDEX idx_batches_hall_exam ON allocation_batches(hall_id, exam_id);
