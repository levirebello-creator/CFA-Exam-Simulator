"""
SQLite persistence layer for the CFA Exam Simulator.
All data lives in data/exam_data.db (created automatically on first run).
"""
import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "exam_data.db")


@contextmanager
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS mocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            provider TEXT,
            upload_date TEXT NOT NULL,
            num_sessions INTEGER NOT NULL DEFAULT 1,
            questions_per_session INTEGER NOT NULL DEFAULT 90,
            minutes_per_session INTEGER NOT NULL DEFAULT 135
        );

        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mock_id INTEGER NOT NULL REFERENCES mocks(id) ON DELETE CASCADE,
            session_number INTEGER NOT NULL DEFAULT 1,
            q_number INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            option_a TEXT,
            option_b TEXT,
            option_c TEXT,
            correct_answer TEXT,
            topic TEXT
        );

        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mock_id INTEGER NOT NULL REFERENCES mocks(id) ON DELETE CASCADE,
            session_number INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            status TEXT NOT NULL DEFAULT 'in_progress',
            score INTEGER,
            total_questions INTEGER
        );

        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            selected_answer TEXT,
            is_correct INTEGER,
            flagged INTEGER DEFAULT 0,
            time_spent_seconds INTEGER DEFAULT 0
        );
        """)


# ---------- Mocks ----------

def create_mock(name, provider, num_sessions, questions_per_session, minutes_per_session):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO mocks (name, provider, upload_date, num_sessions, questions_per_session, minutes_per_session)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (name, provider, datetime.now().isoformat(), num_sessions, questions_per_session, minutes_per_session),
        )
        return cur.lastrowid


def list_mocks():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM mocks ORDER BY upload_date DESC").fetchall()


def get_mock(mock_id):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM mocks WHERE id = ?", (mock_id,)).fetchone()


def delete_mock(mock_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM mocks WHERE id = ?", (mock_id,))


# ---------- Questions ----------

def bulk_insert_questions(mock_id, session_number, questions):
    """questions: list of dicts with keys q_number, question_text, option_a/b/c, correct_answer, topic"""
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO questions (mock_id, session_number, q_number, question_text, option_a, option_b, option_c, correct_answer, topic)"
            " VALUES (:mock_id, :session_number, :q_number, :question_text, :option_a, :option_b, :option_c, :correct_answer, :topic)",
            [{**q, "mock_id": mock_id, "session_number": session_number} for q in questions],
        )


def get_questions(mock_id, session_number):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM questions WHERE mock_id = ? AND session_number = ? ORDER BY q_number",
            (mock_id, session_number),
        ).fetchall()


def update_question_answer_key(question_id, correct_answer):
    with get_conn() as conn:
        conn.execute("UPDATE questions SET correct_answer = ? WHERE id = ?", (correct_answer, question_id))


def count_missing_answers(mock_id, session_number):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM questions WHERE mock_id=? AND session_number=? AND (correct_answer IS NULL OR correct_answer = '')",
            (mock_id, session_number),
        ).fetchone()
        return row["c"]


# ---------- Attempts / Sessions ----------

def start_attempt(mock_id, session_number, total_questions):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO attempts (mock_id, session_number, start_time, status, total_questions)"
            " VALUES (?, ?, ?, 'in_progress', ?)",
            (mock_id, session_number, datetime.now().isoformat(), total_questions),
        )
        return cur.lastrowid


def finish_attempt(attempt_id, score):
    with get_conn() as conn:
        conn.execute(
            "UPDATE attempts SET end_time = ?, status = 'completed', score = ? WHERE id = ?",
            (datetime.now().isoformat(), score, attempt_id),
        )


def get_attempt(attempt_id):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()


def list_attempts(mock_id=None):
    with get_conn() as conn:
        if mock_id:
            return conn.execute(
                "SELECT a.*, m.name as mock_name FROM attempts a JOIN mocks m ON a.mock_id = m.id "
                "WHERE a.mock_id = ? ORDER BY a.start_time DESC", (mock_id,)
            ).fetchall()
        return conn.execute(
            "SELECT a.*, m.name as mock_name FROM attempts a JOIN mocks m ON a.mock_id = m.id "
            "ORDER BY a.start_time DESC"
        ).fetchall()


def in_progress_attempt(mock_id, session_number):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM attempts WHERE mock_id=? AND session_number=? AND status='in_progress' "
            "ORDER BY start_time DESC LIMIT 1",
            (mock_id, session_number),
        ).fetchone()


# ---------- Responses ----------

def upsert_response(attempt_id, question_id, selected_answer, is_correct, flagged, time_spent_seconds):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM responses WHERE attempt_id=? AND question_id=?", (attempt_id, question_id)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE responses SET selected_answer=?, is_correct=?, flagged=?, time_spent_seconds=? WHERE id=?",
                (selected_answer, is_correct, int(flagged), time_spent_seconds, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO responses (attempt_id, question_id, selected_answer, is_correct, flagged, time_spent_seconds)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (attempt_id, question_id, selected_answer, is_correct, int(flagged), time_spent_seconds),
            )


def get_responses(attempt_id):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM responses WHERE attempt_id = ?", (attempt_id,)).fetchall()


def get_review_data(attempt_id):
    """Join questions + responses for the review screen."""
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT q.id as question_id, q.q_number, q.question_text, q.option_a, q.option_b, q.option_c,
                   q.correct_answer, q.topic, r.selected_answer, r.is_correct, r.flagged, r.time_spent_seconds
            FROM questions q
            LEFT JOIN responses r ON r.question_id = q.id AND r.attempt_id = ?
            WHERE q.mock_id = (SELECT mock_id FROM attempts WHERE id = ?)
              AND q.session_number = (SELECT session_number FROM attempts WHERE id = ?)
            ORDER BY q.q_number
            """,
            (attempt_id, attempt_id, attempt_id),
        ).fetchall()
