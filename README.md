# FindOut – AI-Powered Campus Placement Platform

FindOut is a full-stack Flask web application that goes beyond a traditional job board. It analyses a student's **resume**, **GitHub profile**, and **LeetCode activity** together to produce verified skill scores, role recommendations, skill-gap roadmaps, and job matching — all backed by an AI chatbot.

---

## Table of Contents

- [Features](#features)
- [Project Structure](#project-structure)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Running the App](#running-the-app)
- [Environment Variables](#environment-variables)
- [Usage](#usage)
  - [Student Flow](#student-flow)
  - [Recruiter Flow](#recruiter-flow)
- [API Reference](#api-reference)
- [Module Overview](#module-overview)
- [Data Files](#data-files)

---

## Features

| Feature | Description |
|---|---|
| **Resume Parsing** | Extracts skills from PDF, DOCX, and TXT resumes |
| **GitHub Integration** | Derives verified skills from repository languages, topics, and descriptions |
| **LeetCode Integration** | Infers DSA proficiency from solved problem counts (easy / medium / hard) |
| **Authenticity Score** | Quantifies how well GitHub/LeetCode evidence backs up resume claims |
| **Readiness Score** | Weighted fit percentage for a chosen target role |
| **Role Recommendation** | Auto-ranks all available roles against the candidate's skill set |
| **Skill Gap Analysis** | Lists missing skills required for the target role |
| **Learning Roadmap** | Phased (short / medium / long-term) plan with curated free resources and project ideas |
| **Job Board** | Students browse and apply; recruiters post jobs and view ranked applicant lists |
| **AI Chatbot** | Instant Q&A about the platform, scores, and career advice |
| **Dual Roles** | Separate dashboards for `student` and `recruiter` users |

---

## Project Structure

```
RTH_hackathon/
├── app.py                  # Flask application & all route handlers
├── resume_parser.py        # PDF / DOCX / TXT text extraction
├── skill_engine.py         # Skill extraction, merging & authenticity scoring
├── github_parser.py        # GitHub API – verified skill derivation
├── leetcode_parser.py      # LeetCode GraphQL API – DSA stats & proficiency
├── role_engine.py          # Role recommendation, readiness score, skill gaps
├── roadmap_engine.py       # Personalised phased learning roadmap generator
├── job_engine.py           # Job CRUD and listing helpers
├── application_engine.py   # Job application tracking
├── chatbot_engine.py       # Rule-based NLP chatbot (FindOut assistant)
├── requirements.txt        # Python dependencies
├── data/
│   ├── skills.json         # Skill vocabulary by category
│   ├── roles.json          # Role definitions with weighted required skills
│   ├── jobs.json           # Persisted job postings
│   └── applications.json   # Persisted student applications
└── templates/
    ├── index.html          # Student upload form
    ├── report.html         # Analysis report page
    ├── login.html          # Login / role selection
    ├── home.html           # Landing page
    ├── job_list.html       # Browse jobs (student)
    ├── job_form.html       # Create job (recruiter)
    ├── recruiter_jobs.html # Recruiter dashboard
    └── job_applicants.html # Applicant list (recruiter)
```

---

## Tech Stack

- **Backend:** Python 3.10+, Flask 3, Werkzeug
- **PDF Parsing:** pdfplumber (primary), PyPDF2 (fallback)
- **DOCX Parsing:** python-docx
- **External APIs:** GitHub REST API v3, LeetCode GraphQL API
- **Production Server:** Gunicorn
- **Frontend:** Jinja2 templates, HTML/CSS

---

## Getting Started

### Prerequisites

- Python 3.10 or higher
- `pip` package manager
- (Optional) A GitHub Personal Access Token for higher API rate limits

### Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/<your-username>/RTH_hackathon.git
   cd RTH_hackathon
   ```

2. **Create and activate a virtual environment**

   ```bash
   # Windows
   python -m venv .venv
   .venv\Scripts\activate

   # macOS / Linux
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

### Running the App

**Development**

```bash
python app.py
```

The server starts at `http://127.0.0.1:5000` by default.

**Production (Gunicorn)**

```bash
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `FLASK_SECRET` | No | `dev-secret-change-in-prod` | Flask session secret key — **change this in production** |
| `GITHUB_TOKEN` | No | *(none)* | GitHub Personal Access Token for higher API rate limits (60 → 5000 req/hr) |

Set them in your shell or a `.env` file:

```bash
export FLASK_SECRET="your-strong-secret-key"
export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
```

---

## Usage

### Student Flow

1. Navigate to `/login` and sign in as **Student**.
2. On the upload page (`/`), provide:
   - Your resume file (PDF, DOCX, DOC, or TXT — max 5 MB)
   - Your GitHub username
   - Your LeetCode username
   - Your target role (selected from the dropdown)
   - Your CGPA (optional — used as a soft modifier)
3. Click **Analyse**. The pipeline runs in real time and redirects to `/report`.
4. The report shows:
   - **Authenticity Score** — how much of your resume is backed by real GitHub/LeetCode evidence
   - **Readiness Score** — fit percentage for your chosen role
   - **Matched Skills** — skills confirmed across all three sources
   - **Skill Gaps** — what you still need to learn
   - **Learning Roadmap** — phased plan with free resources and project ideas
5. Browse open jobs at `/jobs` and apply with one click.

### Recruiter Flow

1. Navigate to `/login` and sign in as **Recruiter**.
2. Post a new job at `/recruiter/jobs/new` — fill in the title, description, and required skills.
3. View all your postings at `/recruiter/jobs`.
4. Click any job to see its applicant list at `/recruiter/jobs/<id>/applicants`. Applicants are ranked by their AI readiness score.

---

## API Reference

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/` | student | Upload form |
| `POST` | `/analyse` | student | Run full pipeline, render HTML report |
| `POST` | `/api/analyse` | — | Run full pipeline, return JSON |
| `GET` | `/api/roles` | — | List all available roles as JSON |
| `GET` | `/jobs` | student | Browse all job postings |
| `POST` | `/jobs/apply/<id>` | student | Apply to a job |
| `GET` | `/recruiter/jobs` | recruiter | Recruiter dashboard |
| `GET POST` | `/recruiter/jobs/new` | recruiter | Create a new job |
| `GET` | `/recruiter/jobs/<id>/applicants` | recruiter | View ranked applicants |
| `GET` | `/health` | — | Health check — returns `{"status": "ok"}` |
| `GET` | `/login` | — | Login page |
| `POST` | `/login` | — | Authenticate and set session |
| `GET` | `/logout` | — | Clear session and redirect to login |

### `POST /api/analyse` — Request Body (multipart/form-data)

| Field | Type | Required | Description |
|---|---|---|---|
| `resume` | file | Yes | Resume file (PDF / DOCX / TXT) |
| `github_username` | string | No | GitHub username |
| `leetcode_username` | string | No | LeetCode username |
| `role` | string | No | Target role name |
| `cgpa` | float | No | CGPA (0.0 – 10.0) |

### `POST /api/analyse` — Response (JSON)

```json
{
  "resume_skills": ["python", "flask", "sql"],
  "github_skills": ["python", "docker"],
  "leetcode_skills": ["arrays", "dynamic programming"],
  "all_skills": ["python", "flask", "sql", "docker", "arrays", "dynamic programming"],
  "authenticity_score": 82,
  "recommended_role": "Backend Developer",
  "readiness_score": 74,
  "skill_gaps": ["kubernetes", "redis"],
  "roadmap": { ... }
}
```

---

## Module Overview

| Module | Responsibility |
|---|---|
| `app.py` | Flask routes, auth decorators, request validation, pipeline orchestration |
| `resume_parser.py` | Text extraction from PDF (pdfplumber → PyPDF2 fallback), DOCX, TXT; whitespace normalisation |
| `skill_engine.py` | Regex-based skill extraction against `skills.json` vocabulary; merges resume + GitHub + LeetCode skills; computes per-skill and aggregate authenticity scores |
| `github_parser.py` | Calls GitHub REST API; maps repository languages, topics, and description keywords to normalised skill names |
| `leetcode_parser.py` | Calls LeetCode GraphQL API with CSRF session management; maps problem counts to DSA skill proficiency levels |
| `role_engine.py` | Loads `roles.json`; computes weighted match scores; selects best-fit role; calculates readiness percentage; lists skill gaps; applies CGPA modifier |
| `roadmap_engine.py` | Maps each missing skill to a learning phase, curated free resources, estimated hours, and project ideas |
| `job_engine.py` | Creates and retrieves job postings persisted in `data/jobs.json` |
| `application_engine.py` | Records applications in `data/applications.json`; retrieves per-job and per-student application history |
| `chatbot_engine.py` | Rule-based NLP chatbot with exact-phrase matching, weighted keyword scoring, and fuzzy similarity fallback |

---

## Data Files

| File | Description |
|---|---|
| `data/skills.json` | Flat skill vocabulary grouped by category (languages, frameworks, databases, cloud, etc.) |
| `data/roles.json` | Role definitions — each role lists required skills with weights used for readiness scoring |
| `data/jobs.json` | Auto-generated; stores recruiter-posted jobs |
| `data/applications.json` | Auto-generated; stores student applications |

---

> Built for the RTH Hackathon. All external API calls degrade gracefully — the platform remains functional even if GitHub or LeetCode is unreachable.
