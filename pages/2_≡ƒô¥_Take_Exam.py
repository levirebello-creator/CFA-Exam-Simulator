import streamlit as st
from datetime import datetime
from streamlit_autorefresh import st_autorefresh
from utils import db
from utils.timer import seconds_remaining, format_hms

st.set_page_config(page_title="Take Exam", page_icon="📝", layout="wide")
db.init_db()

# ---------- Exam-like styling ----------
st.markdown("""
<style>
.exam-header {
    background-color: #1a1a2e; color: white; padding: 14px 20px; border-radius: 6px;
    display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px;
}
.exam-timer { font-size: 28px; font-weight: 700; font-family: monospace; }
.exam-timer.warning { color: #ff4b4b; }
.qnav-grid button { width: 100%; }
.question-box { background-color: #fafafa; border: 1px solid #ddd; border-radius: 8px; padding: 24px; }
</style>
""", unsafe_allow_html=True)


def reset_exam_state():
    for k in list(st.session_state.keys()):
        if k.startswith("exam_"):
            del st.session_state[k]


mocks = [dict(m) for m in db.list_mocks()]
if not mocks:
    st.info("No mocks uploaded yet. Go to **Upload Mock** first.")
    st.stop()

# ---------- Selection screen (only if no exam in progress) ----------
if "exam_attempt_id" not in st.session_state:
    st.title("📝 Take a Mock Exam")
    mock_choice = st.selectbox("Choose mock", mocks, format_func=lambda m: f"{m['name']} ({m['provider'] or 'n/a'})")
    session_number = st.number_input("Session", min_value=1, max_value=int(mock_choice["num_sessions"]), value=1)

    questions = db.get_questions(mock_choice["id"], session_number)
    if not questions:
        st.warning("No questions found for this mock/session. Upload it first.")
        st.stop()

    missing = db.count_missing_answers(mock_choice["id"], session_number)
    if missing:
        st.warning(f"{missing} question(s) in this session have no correct answer on file — "
                   "they'll show as unscored in your review. You can fix this in Upload Mock.")

    resumable = db.in_progress_attempt(mock_choice["id"], session_number)

    st.markdown("### Exam Instructions")
    st.markdown(f"""
    - This session has **{len(questions)} questions**
    - You will have **{mock_choice['minutes_per_session']} minutes**
    - You may navigate between questions and flag questions for review
    - **The exam will auto-submit when time runs out** — just like the real thing
    - Once submitted, you'll see your score and a full review of right/wrong answers
    """)

    c1, c2 = st.columns(2)
    if resumable:
        if c1.button("▶ Resume in-progress attempt", type="primary"):
            st.session_state["exam_attempt_id"] = resumable["id"]
            st.session_state["exam_mock_id"] = mock_choice["id"]
            st.session_state["exam_session_number"] = session_number
            st.session_state["exam_questions"] = [dict(q) for q in questions]
            st.session_state["exam_idx"] = 0
            existing = {r["question_id"]: dict(r) for r in db.get_responses(resumable["id"])}
            st.session_state["exam_responses"] = existing
            st.rerun()
        if c2.button("🔁 Discard it & start fresh"):
            db.finish_attempt(resumable["id"], score=None)
    else:
        if c1.button("🚀 Start Exam", type="primary"):
            attempt_id = db.start_attempt(mock_choice["id"], session_number, len(questions))
            st.session_state["exam_attempt_id"] = attempt_id
            st.session_state["exam_mock_id"] = mock_choice["id"]
            st.session_state["exam_session_number"] = session_number
            st.session_state["exam_questions"] = [dict(q) for q in questions]
            st.session_state["exam_idx"] = 0
            st.session_state["exam_responses"] = {}
            st.rerun()
    st.stop()

# ---------- Active exam ----------
attempt_id = st.session_state["exam_attempt_id"]
mock = db.get_mock(st.session_state["exam_mock_id"])
questions = st.session_state["exam_questions"]
attempt = db.get_attempt(attempt_id)

remaining = seconds_remaining(attempt["start_time"], mock["minutes_per_session"])
st_autorefresh(interval=1000, key="exam_clock_refresh")

responses = st.session_state["exam_responses"]
idx = st.session_state["exam_idx"]
current_q = questions[idx]


def submit_exam():
    total = len(questions)
    correct = 0
    scored = 0
    for q in questions:
        r = responses.get(q["id"])
        selected = r["selected_answer"] if r else None
        is_correct = None
        if q["correct_answer"] and selected:
            is_correct = int(selected == q["correct_answer"])
            scored += 1
            correct += is_correct
        db.upsert_response(
            attempt_id, q["id"], selected,
            is_correct, bool(r and r.get("flagged")), int(r["time_spent_seconds"]) if r else 0,
        )
    score_pct = round(100 * correct / scored) if scored else 0
    db.finish_attempt(attempt_id, score_pct)
    st.session_state["last_completed_attempt_id"] = attempt_id
    reset_exam_state()
    st.rerun()


# Auto-submit when time is up
if remaining <= 0:
    st.warning("⏰ Time is up! Auto-submitting your exam...")
    submit_exam()

# ---------- Header ----------
answered_count = sum(1 for q in questions if responses.get(q["id"], {}).get("selected_answer"))
timer_class = "warning" if remaining < 300 else ""
st.markdown(f"""
<div class="exam-header">
    <div><b>{mock['name']}</b> — Session {st.session_state['exam_session_number']} &nbsp;|&nbsp; {answered_count}/{len(questions)} answered</div>
    <div class="exam-timer {timer_class}">⏱ {format_hms(remaining)}</div>
</div>
""", unsafe_allow_html=True)

nav_col, main_col = st.columns([1, 3])

with nav_col:
    st.markdown("**Question Navigator**")
    st.markdown('<div class="qnav-grid">', unsafe_allow_html=True)
    cols_per_row = 5
    for row_start in range(0, len(questions), cols_per_row):
        row_qs = questions[row_start:row_start + cols_per_row]
        cols = st.columns(len(row_qs))
        for c, q in zip(cols, row_qs):
            r = responses.get(q["id"])
            answered = bool(r and r.get("selected_answer"))
            flagged = bool(r and r.get("flagged"))
            label = f"🚩{q['q_number']}" if flagged else (f"✓{q['q_number']}" if answered else str(q["q_number"]))
            btn_type = "primary" if q["q_number"] == current_q["q_number"] else "secondary"
            if c.button(label, key=f"nav_{q['id']}", type=btn_type):
                st.session_state["exam_idx"] = questions.index(q)
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    st.divider()
    legend = "🟩 Answered &nbsp; ⬜ Unanswered &nbsp; 🚩 Flagged"
    st.caption(legend)

    st.divider()
    if st.button("✅ Submit Exam", type="primary", use_container_width=True):
        st.session_state["confirm_submit"] = True

    if st.session_state.get("confirm_submit"):
        st.warning(f"You've answered {answered_count} of {len(questions)} questions. Submit anyway?")
        cc1, cc2 = st.columns(2)
        if cc1.button("Yes, submit", type="primary", use_container_width=True):
            submit_exam()
        if cc2.button("Cancel", use_container_width=True):
            st.session_state["confirm_submit"] = False
            st.rerun()

with main_col:
    st.markdown('<div class="question-box">', unsafe_allow_html=True)
    st.markdown(f"#### Question {current_q['q_number']} of {len(questions)}")
    st.write(current_q["question_text"])

    existing_r = responses.get(current_q["id"], {})
    options = []
    option_map = {}
    for letter in ["A", "B", "C"]:
        text = current_q.get(f"option_{letter.lower()}")
        if text:
            label = f"{letter}. {text}"
            options.append(label)
            option_map[label] = letter

    current_selected = existing_r.get("selected_answer")
    default_idx = None
    if current_selected:
        for i, label in enumerate(options):
            if option_map[label] == current_selected:
                default_idx = i

    choice = st.radio("Select your answer:", options, index=default_idx, key=f"radio_{current_q['id']}")

    flagged = st.checkbox("🚩 Flag this question for review", value=bool(existing_r.get("flagged")), key=f"flag_{current_q['id']}")

    selected_letter = option_map.get(choice) if choice else None
    responses[current_q["id"]] = {
        "question_id": current_q["id"],
        "selected_answer": selected_letter,
        "flagged": flagged,
        "time_spent_seconds": existing_r.get("time_spent_seconds", 0),
    }
    db.upsert_response(attempt_id, current_q["id"], selected_letter, None, flagged, existing_r.get("time_spent_seconds", 0))

    st.markdown('</div>', unsafe_allow_html=True)

    nav1, nav2, nav3 = st.columns(3)
    if nav1.button("⬅ Previous", disabled=idx == 0, use_container_width=True):
        st.session_state["exam_idx"] = idx - 1
        st.rerun()
    if nav3.button("Next ➡", disabled=idx == len(questions) - 1, use_container_width=True):
        st.session_state["exam_idx"] = idx + 1
        st.rerun()
