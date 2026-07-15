import streamlit as st
from utils import db

st.set_page_config(page_title="Practice by Topic", page_icon="🧠", layout="wide")
db.init_db()

sets = [dict(t) for t in db.list_topic_sets()]
if not sets:
    st.info("No topic sets uploaded yet. Go to **Upload Topic Set** first.")
    st.stop()

# ---------- Selection screen ----------
if "topic_practice_attempt_id" not in st.session_state and "topic_practice_review_attempt_id" not in st.session_state:
    st.title("🧠 Practice by Topic")
    st.caption(
        "Untimed practice, organized by subject. As soon as you finish, you'll see your score and "
        "a full explanation for anything you got wrong."
    )
    choice = st.selectbox("Choose topic set", sets, format_func=lambda t: f"{t['name']} ({t['subject'] or 'n/a'})")

    questions = db.get_topic_questions(choice["id"])
    if not questions:
        st.warning("No questions found for this set. Upload it first.")
        st.stop()

    missing = sum(1 for q in questions if not q["correct_answer"])
    if missing:
        st.warning(f"{missing} question(s) in this set have no correct answer on file — "
                   "they'll show as unscored in your results.")

    if st.button("🚀 Start Practice", type="primary"):
        attempt_id = db.start_topic_attempt(choice["id"], len(questions))
        st.session_state["topic_practice_attempt_id"] = attempt_id
        st.session_state["topic_practice_set_id"] = choice["id"]
        st.session_state["topic_practice_questions"] = [dict(q) for q in questions]
        st.session_state["topic_practice_idx"] = 0
        st.session_state["topic_practice_responses"] = {}
        st.rerun()
    st.stop()

# ---------- Results (shown immediately after finishing) ----------
if "topic_practice_review_attempt_id" in st.session_state:
    attempt_id = st.session_state["topic_practice_review_attempt_id"]
    attempt = db.get_topic_attempt(attempt_id)
    review_rows = db.get_topic_review_data(attempt_id)

    st.title("✅ Practice Results")
    scored = [r for r in review_rows if r["correct_answer"]]
    correct_count = sum(1 for r in scored if r["is_correct"])
    answered_count = sum(1 for r in review_rows if r["selected_answer"])

    c1, c2, c3 = st.columns(3)
    c1.metric("Score", f"{attempt['score']}%")
    c2.metric("Correct", f"{correct_count} / {len(scored)}")
    c3.metric("Answered", f"{answered_count} / {len(review_rows)}")

    st.divider()
    filter_choice = st.radio("Show:", ["All questions", "Only wrong answers", "Only unanswered"], horizontal=True)

    for r in review_rows:
        wrong = bool(r["correct_answer"] and r["selected_answer"] and not r["is_correct"])
        if filter_choice == "Only wrong answers" and not wrong:
            continue
        if filter_choice == "Only unanswered" and r["selected_answer"]:
            continue

        if r["correct_answer"] is None:
            status = "❔ No answer key"
        elif r["selected_answer"] is None:
            status = "⬜ Not answered"
        elif r["is_correct"]:
            status = "✅ Correct"
        else:
            status = "❌ Incorrect"

        with st.expander(f"Q{r['q_number']} — {status}", expanded=wrong):
            st.write(r["question_text"])
            for letter in ["A", "B", "C"]:
                text = r[f"option_{letter.lower()}"]
                if not text:
                    continue
                tag = ""
                if letter == r["correct_answer"]:
                    tag += " ✅ **Correct answer**"
                if letter == r["selected_answer"]:
                    tag += " 👉 **Your answer**"
                st.markdown(f"**{letter}.** {text}{tag}")
            if wrong:
                if r["explanation"]:
                    st.info(f"**Explanation:** {r['explanation']}")
                else:
                    st.caption("No explanation was available in the source PDF for this question.")

    st.divider()
    cc1, cc2 = st.columns(2)
    if cc1.button("🔁 Practice this set again", use_container_width=True):
        del st.session_state["topic_practice_review_attempt_id"]
        st.rerun()
    if cc2.button("⬅ Choose a different set", use_container_width=True):
        del st.session_state["topic_practice_review_attempt_id"]
        st.rerun()
    st.stop()

# ---------- Active practice (untimed) ----------
attempt_id = st.session_state["topic_practice_attempt_id"]
topic_set = db.get_topic_set(st.session_state["topic_practice_set_id"])
questions = st.session_state["topic_practice_questions"]
responses = st.session_state["topic_practice_responses"]
idx = st.session_state["topic_practice_idx"]
current_q = questions[idx]


def submit_practice():
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
        db.upsert_topic_response(attempt_id, q["id"], selected, is_correct, bool(r and r.get("flagged")))
    score_pct = round(100 * correct / scored) if scored else 0
    db.finish_topic_attempt(attempt_id, score_pct)
    st.session_state["topic_practice_review_attempt_id"] = attempt_id
    for k in ["topic_practice_attempt_id", "topic_practice_set_id", "topic_practice_questions",
              "topic_practice_idx", "topic_practice_responses"]:
        st.session_state.pop(k, None)
    st.rerun()


answered_count = sum(1 for q in questions if responses.get(q["id"], {}).get("selected_answer"))
st.markdown(f"### 🧠 {topic_set['name']} — {answered_count}/{len(questions)} answered")
st.caption("Untimed — take your time.")

nav_col, main_col = st.columns([1, 3])

with nav_col:
    st.markdown("**Question Navigator**")
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
            if c.button(label, key=f"topic_nav_{q['id']}", type=btn_type):
                st.session_state["topic_practice_idx"] = questions.index(q)
                st.rerun()

    st.divider()
    st.caption("🟩 Answered &nbsp; ⬜ Unanswered &nbsp; 🚩 Flagged")
    st.divider()

    if st.button("✅ Finish & See Results", type="primary", use_container_width=True):
        st.session_state["topic_confirm_submit"] = True

    if st.session_state.get("topic_confirm_submit"):
        st.warning(f"You've answered {answered_count} of {len(questions)} questions. Finish anyway?")
        cc1, cc2 = st.columns(2)
        if cc1.button("Yes, finish", type="primary", use_container_width=True, key="topic_confirm_yes"):
            submit_practice()
        if cc2.button("Cancel", use_container_width=True, key="topic_confirm_no"):
            st.session_state["topic_confirm_submit"] = False
            st.rerun()

with main_col:
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

    choice = st.radio("Select your answer:", options, index=default_idx, key=f"topic_radio_{current_q['id']}")
    flagged = st.checkbox("🚩 Flag this question", value=bool(existing_r.get("flagged")), key=f"topic_flag_{current_q['id']}")

    selected_letter = option_map.get(choice) if choice else None
    responses[current_q["id"]] = {
        "question_id": current_q["id"],
        "selected_answer": selected_letter,
        "flagged": flagged,
    }
    db.upsert_topic_response(attempt_id, current_q["id"], selected_letter, None, flagged)

    nav1, nav2, nav3 = st.columns(3)
    if nav1.button("⬅ Previous", disabled=idx == 0, use_container_width=True):
        st.session_state["topic_practice_idx"] = idx - 1
        st.rerun()
    if nav3.button("Next ➡", disabled=idx == len(questions) - 1, use_container_width=True):
        st.session_state["topic_practice_idx"] = idx + 1
        st.rerun()
