"""
Turns raw OCR/extracted text into a list of question dicts.

Because Kaplan / Wiley / CFAI mocks all format questions slightly
differently, this is intentionally a "best effort" parser. It is expected
that you will fix a handful of rows in the review table after parsing -
that's faster and safer than trying to build a perfect universal parser.
"""
import re

# Matches a question number at the start of a line, e.g. "1.", "Q1.", "Question 1."
Q_NUM_PATTERN = re.compile(
    r"^\s*(?:Q(?:uestion)?\.?\s*)?(\d{1,3})[\.\)]\s+", re.MULTILINE
)

# Matches an option line, e.g. "A. text", "(A) text", "A) text"
OPTION_PATTERN = re.compile(r"^\s*\(?([ABC])\)?[\.\)]\s+(.*)", re.MULTILINE)

# Matches answer key lines like "1. B", "1) B", "1 - B", "1: B"
ANSWER_KEY_LINE = re.compile(r"^\s*(\d{1,3})[\.\)\-:]?\s*([ABC])\s*$", re.MULTILINE)
ANSWER_KEY_LINE_LOOSE = re.compile(r"(\d{1,3})\s*[\.\)\-:]\s*([ABC])\b")


def parse_questions(raw_text: str):
    """
    Splits raw text into a list of question dicts:
    {q_number, question_text, option_a, option_b, option_c, correct_answer: None, topic: None}
    """
    matches = list(Q_NUM_PATTERN.finditer(raw_text))
    questions = []

    for idx, m in enumerate(matches):
        q_num = int(m.group(1))
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw_text)
        block = raw_text[start:end].strip()

        # Split block into stem + options
        option_matches = list(OPTION_PATTERN.finditer(block))
        if option_matches:
            stem = block[: option_matches[0].start()].strip()
            opts = {"A": "", "B": "", "C": ""}
            for oi, om in enumerate(option_matches):
                letter = om.group(1)
                opt_start = om.end()
                opt_end = option_matches[oi + 1].start() if oi + 1 < len(option_matches) else len(block)
                opts[letter] = block[opt_start:opt_end].strip() if opt_start == om.end() else om.group(2).strip()
            # cleaner re-extraction of option text (handles multi-line options)
            opts = _extract_options(block, option_matches)
        else:
            stem = block
            opts = {"A": "", "B": "", "C": ""}

        questions.append({
            "q_number": q_num,
            "question_text": stem,
            "option_a": opts.get("A", ""),
            "option_b": opts.get("B", ""),
            "option_c": opts.get("C", ""),
            "correct_answer": None,
            "topic": None,
        })

    # Sort and dedupe by q_number, keep first occurrence
    seen = {}
    for q in questions:
        if q["q_number"] not in seen:
            seen[q["q_number"]] = q
    return [seen[k] for k in sorted(seen.keys())]


def _extract_options(block, option_matches):
    opts = {"A": "", "B": "", "C": ""}
    for oi, om in enumerate(option_matches):
        letter = om.group(1)
        opt_start = om.start()
        opt_end = option_matches[oi + 1].start() if oi + 1 < len(option_matches) else len(block)
        full_opt = block[opt_start:opt_end]
        # strip the leading "A." / "(A)" marker
        text = re.sub(r"^\s*\(?[ABC]\)?[\.\)]\s+", "", full_opt).strip()
        opts[letter] = text
    return opts


def parse_answer_key(raw_text: str):
    """
    Returns a dict {q_number: 'A'/'B'/'C'} parsed from an answer-key style text
    (either a standalone answer key PDF, or the tail section of a mock PDF).
    """
    answers = {}
    for m in ANSWER_KEY_LINE.finditer(raw_text):
        answers[int(m.group(1))] = m.group(2)
    if len(answers) < 5:  # fall back to a looser pattern if strict one found almost nothing
        for m in ANSWER_KEY_LINE_LOOSE.finditer(raw_text):
            q = int(m.group(1))
            answers.setdefault(q, m.group(2))
    return answers


def merge_answer_key(questions, answer_map):
    for q in questions:
        if q["q_number"] in answer_map:
            q["correct_answer"] = answer_map[q["q_number"]]
    return questions
