# CFA Level I Mock Exam Simulator

A Streamlit app that lets you upload CFA Level I mock PDFs (text-based or scanned),
sit them under real exam conditions (timed, auto-locking, question navigator), and
review your right/wrong answers afterward — plus track progress across every mock
you've solved.

## Features
- **Upload any mock PDF** — Kaplan, Wiley, CFAI, or scanned copies. Scanned pages
  are automatically detected and run through OCR (Tesseract).
- **Answer key handling** — works whether your answer key is a separate PDF or
  embedded at the end of the mock PDF.
- **Manual correction step** — because providers format questions differently,
  extracted questions are shown in an editable table before saving, so you can fix
  any OCR/parsing mistakes in seconds.
- **Real exam simulation** — countdown timer, question navigator grid (like the
  real CFA exam), flag-for-review, auto-submit when time runs out.
- **Review mode** — after each session, see your score and go question-by-question
  with your answer vs. the correct answer, filterable to "only wrong" or "only
  flagged".
- **Dashboard** — score trends over time, which mocks are fully solved, best/average
  scores per mock.

## Project structure
```
cfa_exam_simulator/
├── app.py                       # Landing page / overview dashboard
├── pages/
│   ├── 1_📄_Upload_Mock.py      # Upload + OCR + parse + fix + save
│   ├── 2_📝_Take_Exam.py        # Timed exam simulation
│   ├── 3_✅_Review.py           # Post-exam review
│   └── 4_📊_Dashboard.py        # Progress tracking + backup/restore
├── utils/
│   ├── db.py                    # SQLite schema + all data access
│   ├── ocr_extract.py           # PDF text extraction with OCR fallback
│   ├── parser.py                # Raw text -> structured questions/answers
│   └── timer.py                 # Countdown helpers
├── data/                        # SQLite DB lives here (created automatically)
├── requirements.txt
├── packages.txt                 # apt packages needed for OCR (tesseract, poppler)
└── .streamlit/config.toml       # Theme
```

## Running locally
```bash
pip install -r requirements.txt
# You'll also need Tesseract + poppler installed locally for OCR to work:
#   Mac:   brew install tesseract poppler
#   Ubuntu: sudo apt-get install tesseract-ocr poppler-utils
#   Windows: install Tesseract from https://github.com/UB-Mannheim/tesseract/wiki
#            and poppler from https://github.com/oschwartz10612/poppler-windows

streamlit run app.py
```

## Deploying to Streamlit Community Cloud
1. Push this folder to a new GitHub repo (see below).
2. Go to https://share.streamlit.io → **New app** → pick your repo → set
   **Main file path** to `app.py` → Deploy.
3. Streamlit Cloud automatically reads `packages.txt` and installs Tesseract +
   poppler for you — no extra config needed.

### ⚠️ Important: data persistence
Streamlit Community Cloud's filesystem is **ephemeral** — it resets whenever the
app restarts (sleeps from inactivity) or you push new code. This means your
uploaded mocks and exam history can be wiped.

**Workaround built into the app:** go to the **Dashboard** page → "Backup / Restore"
section → download a `.db` backup after each study session. After a redeploy or
restart, upload that file back in the same section to restore everything.
(If this becomes a hassle, the longer-term fix is switching the DB to a hosted
service like Turso/LibSQL or Supabase Postgres — happy to help with that migration
later if you outgrow the backup/restore flow.)

## Pushing to GitHub from your phone
Since you deploy via GitHub mobile:
1. Create a new repo (e.g. `cfa-exam-simulator`) — don't initialize with a README
   since one's included here.
2. Add all these files to the repo (GitHub mobile app → your repo → "+" → upload
   files, or use the "Add file" web flow if easier from a laptop for the initial
   bulk upload — after that, GitHub mobile works fine for edits).
3. Connect the repo in Streamlit Community Cloud as above.

## A note on the parser
CFA mocks from different providers (CFAI, Kaplan, Wiley) are not laid out
identically, and OCR on scanned pages is never 100% perfect — especially around
numbers, formulas and tables. The **Upload Mock** page is deliberately designed
around this: it does a best-effort auto-extraction, then hands you an editable
table to fix anything before it's saved. Spend a minute reviewing that table
each time you upload a new mock — it's much faster than building a "perfect"
per-provider parser and it means your data is always accurate for scoring.
