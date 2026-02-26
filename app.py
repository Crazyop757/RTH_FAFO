"""
app.py
------
Flask entry point for the AI-driven placement analysis backend.

Routes
------
GET  /login           → Login page
POST /login           → Authenticate and set session
GET  /logout          → Clear session
GET  /                → Upload form (index.html)          [requires student]
GET  /analyze         → Alias for /                       [requires student]
POST /analyse         → Full pipeline → render report.html [requires student]
GET  /jobs            → Browse all job postings           [requires student]
POST /jobs/apply/<id> → Apply to a job                   [requires student]
GET  /recruiter/jobs                   → Recruiter dashboard          [requires recruiter]
GET  /recruiter/jobs/new               → New job form                  [requires recruiter]
POST /recruiter/jobs/new               → Create job                    [requires recruiter]
GET  /recruiter/jobs/<id>/applicants   → Applicants for a job          [requires recruiter]
GET  /api/roles       → JSON list of available roles
POST /api/analyse     → Same pipeline, returns raw JSON (for API clients)
GET  /health          → Simple health-check endpoint
"""

import os
import json
import logging
import tempfile
from functools import wraps
from typing import Optional

from flask import (
    Flask, request, render_template, jsonify,
    redirect, url_for, flash, session
)
from werkzeug.utils import secure_filename

from resume_parser   import extract_resume_text
from skill_engine    import extract_resume_skills, merge_candidate_skills, compute_authenticity
from github_parser   import get_github_profile
from leetcode_parser import get_leetcode_stats
from role_engine     import recommend_role, get_skill_gaps, compute_readiness
from roadmap_engine     import generate_roadmap
from job_engine         import create_job, get_all_jobs, get_job, count_applications
from application_engine import (
    apply_to_job,
    get_applications_for_job,
    get_applications_for_student,
)

# Minimum non-empty text length considered a valid extraction
_MIN_RESUME_CHARS = 40

# --------------------------------------------------------------------------- #
#  App configuration                                                           #
# --------------------------------------------------------------------------- #

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-in-prod")

# File upload settings
ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "txt"}
MAX_CONTENT_LENGTH = 5 * 1024 * 1024   # 5 MB
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Optional GitHub token for higher API rate limits
GITHUB_TOKEN: Optional[str] = os.environ.get("GITHUB_TOKEN")

# Load available roles for the dropdown
_ROLES_JSON = os.path.join(os.path.dirname(__file__), "data", "roles.json")
try:
    with open(_ROLES_JSON, "r", encoding="utf-8") as _fh:
        AVAILABLE_ROLES: list = list(json.load(_fh).keys())
except Exception:
    AVAILABLE_ROLES = []


# --------------------------------------------------------------------------- #
#  Auth                                                                        #
# --------------------------------------------------------------------------- #

_VALID_ROLES = {"student", "recruiter"}


def require_role(role_name: str):
    """
    Decorator that enforces a specific session role.
    Redirects unauthenticated or mismatched users to /login.

    Usage::
        @app.route("/some-page")
        @require_role("student")
        def some_page(): ...
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if session.get("role") != role_name:
                flash("Please log in to access that page.", "error")
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return wrapped
    return decorator


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _allowed_file(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def _parse_cgpa(raw: str) -> tuple:
    """
    Parse and clamp CGPA from a raw string.
    Returns (cgpa_float_or_None, warning_str_or_None).
    Never raises.
    """
    raw = raw.strip()
    if not raw:
        return None, None
    try:
        val = float(raw)
    except ValueError:
        return None, f"CGPA '{raw}' is not a valid number — ignored."
    if val < 0.0:
        return 0.0, f"CGPA {val} is below 0 — clamped to 0.0."
    if val > 10.0:
        return 10.0, f"CGPA {val} exceeds 10 — clamped to 10.0."
    return val, None


def _run_pipeline(
    resume_bytes:    bytes,
    resume_filename: str,
    github_user:     str,
    leetcode_user:   str,
    cgpa:            Optional[float],
    target_role:     Optional[str],
    pre_warnings:    Optional[list] = None,
) -> dict:
    """
    Execute the flat 10-step analysis pipeline.
    Every step is individually guarded; failures produce safe defaults.
    Accumulates human-readable warnings so the report can surface them.
    Always returns a complete result dict — never raises.
    """
    warnings: list = list(pre_warnings or [])

    # ── Step 1: Save resume to temp file & extract text ─────────────────────
    logger.info("Extracting text from resume: %s", resume_filename)
    suffix   = os.path.splitext(resume_filename)[1] or ".tmp"
    tmp_path = None
    text     = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(resume_bytes)
            tmp_path = tmp.name
        text = extract_resume_text(tmp_path)
    except Exception as exc:
        logger.warning("extract_resume_text failed: %s", exc)
        warnings.append(f"Resume text extraction failed ({exc}). Results may be incomplete.")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    if not text or len(text.strip()) < _MIN_RESUME_CHARS:
        warnings.append(
            "Resume text is very short or empty — skill extraction may be limited. "
            "Try a text-selectable PDF or a DOCX file."
        )

    # ── Step 2: Resume skills ────────────────────────────────────────────────
    logger.info("Extracting resume skills")
    try:
        resume_skills = extract_resume_skills(text)
    except Exception as exc:
        logger.warning("extract_resume_skills failed: %s", exc)
        warnings.append("Could not extract skills from resume text.")
        resume_skills = []

    if not resume_skills:
        warnings.append("No recognisable skills found in the resume.")

    # ── Step 3: GitHub profile ───────────────────────────────────────────────
    logger.info("Fetching GitHub profile: %s", github_user or "(none)")
    if not github_user:
        warnings.append("No GitHub username provided — GitHub skills and repo count will be 0.")
        github = {"verified_skills": [], "repo_count": 0}
    else:
        try:
            github = get_github_profile(github_user)
            if not github.get("verified_skills") and github.get("repo_count", 0) == 0:
                warnings.append(
                    f"GitHub profile '{github_user}' returned no data. "
                    "The account may be private, not found, or rate-limited."
                )
        except Exception as exc:
            logger.warning("get_github_profile failed: %s", exc)
            warnings.append(f"GitHub API call failed ({exc}). Continuing without GitHub data.")
            github = {"verified_skills": [], "repo_count": 0}

    github_skills = github.get("verified_skills") or []
    repo_count    = github.get("repo_count") or 0

    # ── Step 4: LeetCode stats ───────────────────────────────────────────────
    logger.info("Fetching LeetCode stats: %s", leetcode_user or "(none)")
    _lc_zero = {"total": 0, "easy": 0, "medium": 0, "hard": 0}
    if not leetcode_user:
        warnings.append("No LeetCode username provided — coding activity score will be 0.")
        leetcode_stats = _lc_zero
    else:
        try:
            leetcode_stats = get_leetcode_stats(leetcode_user)
            if leetcode_stats.get("total", 0) == 0:
                warnings.append(
                    f"LeetCode profile '{leetcode_user}' returned 0 solved problems. "
                    "The username may be incorrect or the account has no accepted submissions."
                )
        except Exception as exc:
            logger.warning("get_leetcode_stats failed: %s", exc)
            warnings.append(f"LeetCode API call failed ({exc}). Continuing without LeetCode data.")
            leetcode_stats = _lc_zero

    # ── Step 5: Merge candidate skills ───────────────────────────────────────
    logger.info("Merging candidate skills")
    try:
        candidate_skills = merge_candidate_skills(resume_skills, github_skills)
    except Exception as exc:
        logger.warning("merge_candidate_skills failed: %s", exc)
        candidate_skills = sorted(set(s.lower() for s in (resume_skills + github_skills) if s))

    # ── Step 6: Authenticity score ───────────────────────────────────────────
    try:
        authenticity = compute_authenticity(resume_skills, github_skills)
    except Exception as exc:
        logger.warning("compute_authenticity failed: %s", exc)
        authenticity = 0.0

    # ── Step 7: Role recommendation ──────────────────────────────────────────
    logger.info("Recommending role")
    _fallback_role = target_role or "Software Development Engineer"
    try:
        if candidate_skills:
            role, match = recommend_role(candidate_skills)
        else:
            role  = _fallback_role
            match = 0.0
            warnings.append("No candidate skills found — role recommendation defaulted.")
    except Exception as exc:
        logger.warning("recommend_role failed: %s", exc)
        role  = _fallback_role
        match = 0.0

    # If caller supplied a target_role override, respect it for gaps/roadmap
    effective_role = target_role if target_role else role

    # ── Step 8: Skill gaps ───────────────────────────────────────────────────
    try:
        gaps = get_skill_gaps(candidate_skills, effective_role)
    except Exception as exc:
        logger.warning("get_skill_gaps failed: %s", exc)
        gaps = []

    # ── Step 9: Readiness score ──────────────────────────────────────────────
    try:
        readiness = compute_readiness(
            match,
            authenticity,
            leetcode_stats.get("total", 0),
            repo_count,
            cgpa if cgpa is not None else 0.0,
        )
    except Exception as exc:
        logger.warning("compute_readiness failed: %s", exc)
        readiness = 0.0

    if cgpa is None:
        warnings.append("No CGPA provided — readiness score calculated with CGPA = 0.")

    # ── Step 10: Roadmap ─────────────────────────────────────────────────────
    logger.info("Generating roadmap")
    try:
        roadmap = generate_roadmap(gaps, effective_role)
    except Exception as exc:
        logger.warning("generate_roadmap failed: %s", exc)
        roadmap = []

    return {
        "resume_skills":  resume_skills,
        "github_skills":  github_skills,
        "repo_count":     repo_count,
        "leetcode_stats": leetcode_stats,
        "authenticity":   authenticity,
        "role":           effective_role,
        "match":          match,
        "readiness":      readiness,
        "gaps":           gaps,
        "roadmap":        roadmap,
        "warnings":       warnings,
        # input echo for the report header
        "meta": {
            "resume_filename": resume_filename,
            "github_user":     github_user or None,
            "leetcode_user":   leetcode_user or None,
            "cgpa":            cgpa,
            "target_role":     target_role,
        },
    }


# --------------------------------------------------------------------------- #
#  Public home route                                                           #
# --------------------------------------------------------------------------- #

@app.route("/home", methods=["GET"])
def home():
    """Public marketing homepage — no auth required."""
    return render_template("home.html")


# --------------------------------------------------------------------------- #
#  Auth routes                                                                 #
# --------------------------------------------------------------------------- #

@app.route("/login", methods=["GET", "POST"])
def login():
    """Show login form (GET) or authenticate user (POST)."""
    # Already logged in → bounce to the right dashboard
    if session.get("role") == "student":
        return redirect(url_for("index"))
    if session.get("role") == "recruiter":
        return redirect(url_for("recruiter_jobs"))

    if request.method == "GET":
        return render_template("login.html")

    # POST — validate and set session
    username = request.form.get("username", "").strip()
    role     = request.form.get("role", "").strip()

    if not username:
        flash("Username is required.", "error")
        return render_template("login.html")

    if role not in _VALID_ROLES:
        flash("Please select a valid role.", "error")
        return render_template("login.html")

    session["user"] = username
    session["role"] = role
    logger.info("Login: user=%s role=%s", username, role)

    if role == "recruiter":
        return redirect(url_for("recruiter_jobs"))
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    """Clear the session and return to login."""
    user = session.get("user", "")
    session.clear()
    logger.info("Logout: user=%s", user)
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# --------------------------------------------------------------------------- #
#  Recruiter routes                                                            #
# --------------------------------------------------------------------------- #

@app.route("/recruiter/jobs", methods=["GET"])
@require_role("recruiter")
def recruiter_jobs():
    """Recruiter dashboard — list jobs created by this recruiter."""
    user     = session.get("user", "")
    all_jobs = get_all_jobs()
    my_jobs  = [j for j in all_jobs if j.get("created_by") == user]
    for j in my_jobs:
        j["_applicant_count"] = count_applications(j["id"])
    return render_template("recruiter_jobs.html", user=user, jobs=my_jobs)


@app.route("/recruiter/jobs/new", methods=["GET", "POST"])
@require_role("recruiter")
def job_new():
    """Render the new-job form (GET) or create a job posting (POST)."""
    user = session.get("user", "")
    if request.method == "GET":
        return render_template("job_form.html", user=user)

    title           = request.form.get("title",           "").strip()
    company         = request.form.get("company",         "").strip()
    description     = request.form.get("description",     "").strip()
    required_skills = request.form.get("required_skills", "").strip()

    if not title or not company:
        flash("Job title and company are required.", "error")
        return render_template("job_form.html", user=user)

    try:
        job = create_job(
            title           = title,
            company         = company,
            description     = description,
            required_skills = required_skills,
            created_by      = user,
        )
        flash(f"Job \u2018{title}\u2019 posted successfully!", "success")
        logger.info("job_new: created job %s by %s", job["id"], user)
    except ValueError as exc:
        flash(str(exc), "error")
        return render_template("job_form.html", user=user)
    except Exception as exc:
        logger.exception("job_new: unexpected error: %s", exc)
        flash("An unexpected error occurred. Please try again.", "error")
        return render_template("job_form.html", user=user)

    return redirect(url_for("recruiter_jobs"))


@app.route("/recruiter/jobs/<job_id>/applicants", methods=["GET"])
@require_role("recruiter")
def job_applicants(job_id: str):
    """Show applicants for *job_id*, sorted by readiness descending."""
    user = session.get("user", "")
    job  = get_job(job_id)

    if job is None:
        flash("Job not found.", "error")
        return redirect(url_for("recruiter_jobs"))

    if job.get("created_by") != user:
        flash("You don\u2019t have permission to view this job\u2019s applicants.", "error")
        return redirect(url_for("recruiter_jobs"))

    apps = get_applications_for_job(job_id)
    apps = sorted(apps, key=lambda a: a.get("readiness", 0.0), reverse=True)

    return render_template(
        "job_applicants.html",
        user=user,
        job=job,
        applications=apps,
    )


# --------------------------------------------------------------------------- #
#  Routes – Web UI                                                             #
# --------------------------------------------------------------------------- #

@app.route("/", methods=["GET"])
@require_role("student")
def index():
    """Render the upload form (student only).
    Also surface the 'Browse Jobs' link if the student has a profile.
    """
    has_profile = bool(session.get("candidate_profile"))
    return render_template("index.html", available_roles=AVAILABLE_ROLES, has_profile=has_profile)


@app.route("/analyze", methods=["GET"])
@require_role("student")
def analyze_alias():
    """American-spelling alias for the upload form."""
    return redirect(url_for("index"))


@app.route("/analyse", methods=["POST"])
@require_role("student")
def analyse():
    """Handle form submission and always render a report, even on partial data."""
    pre_warnings: list = []

    # ── Hard-fail only: no file at all, or wrong type ────────────────────────
    if "resume" not in request.files or request.files["resume"].filename == "":
        flash("Please select a resume file to upload.", "error")
        return redirect(url_for("index"))

    file = request.files["resume"]
    if not _allowed_file(file.filename):
        flash("Unsupported file type. Please upload a PDF, DOCX, or TXT file.", "error")
        return redirect(url_for("index"))

    filename  = secure_filename(file.filename)
    raw_bytes = file.read()

    if not raw_bytes:
        flash("The uploaded file appears to be empty.", "error")
        return redirect(url_for("index"))

    # ── Form fields (soft-fail everything else) ──────────────────────────────
    github_user   = request.form.get("github_username",   "").strip()
    leetcode_user = request.form.get("leetcode_username", "").strip()
    target_role   = request.form.get("target_role",       "").strip() or None

    cgpa, cgpa_warn = _parse_cgpa(request.form.get("cgpa", ""))
    if cgpa_warn:
        pre_warnings.append(cgpa_warn)

    # ── Run pipeline — always produces a report ──────────────────────────────
    try:
        result = _run_pipeline(
            resume_bytes    = raw_bytes,
            resume_filename = filename,
            github_user     = github_user,
            leetcode_user   = leetcode_user,
            cgpa            = cgpa,
            target_role     = target_role,
            pre_warnings    = pre_warnings,
        )
    except Exception as exc:
        # Absolute last-resort fallback — should never be reached
        logger.exception("Unhandled pipeline error: %s", exc)
        result = {
            "resume_skills": [], "github_skills": [], "repo_count": 0,
            "leetcode_stats": {"total": 0, "easy": 0, "medium": 0, "hard": 0},
            "authenticity": 0.0, "role": target_role or "Unknown",
            "match": 0.0, "readiness": 0.0, "gaps": [], "roadmap": [],
            "warnings": pre_warnings + [f"An unexpected error occurred: {exc}"],
            "meta": {
                "resume_filename": filename, "github_user": github_user or None,
                "leetcode_user": leetcode_user or None, "cgpa": cgpa,
                "target_role": target_role,
            },
        }

    # ── Persist profile in session for job browsing / application ─────────────
    lc = result.get("leetcode_stats") or {}
    session["candidate_profile"] = {
        "resume_skills":  result.get("resume_skills", []),
        "github_skills":  result.get("github_skills", []),
        "leetcode_total": lc.get("total", 0) if isinstance(lc, dict) else 0,
        "authenticity":   result.get("authenticity", 0.0),
        "readiness":      result.get("readiness",    0.0),
        "role_match":     result.get("match",        0.0),
    }
    logger.info("analyse: stored candidate_profile in session for user=%s", session.get("user"))

    return render_template("report.html", result=result)


# --------------------------------------------------------------------------- #
#  Routes – Student – Job browsing                                            #
# --------------------------------------------------------------------------- #

@app.route("/jobs", methods=["GET"])
@require_role("student")
def job_list():
    """Browse all open jobs with an AI-computed skill-match ratio."""
    user    = session.get("user", "")
    profile = session.get("candidate_profile") or {}

    candidate_skills = set(
        [s.lower() for s in (profile.get("resume_skills") or [])]
        + [s.lower() for s in (profile.get("github_skills") or [])]
    )

    jobs = get_all_jobs()

    # Annotate each job with computed match ratio and whether already applied
    apps_for_student = {a["job_id"] for a in get_applications_for_student(user)}

    enriched: list[dict] = []
    for job in jobs:
        required = [s.lower() for s in (job.get("required_skills") or [])]
        if required and candidate_skills:
            match_ratio = len(candidate_skills & set(required)) / len(required)
        elif not required:
            match_ratio = 1.0          # no requirements → anyone qualifies
        else:
            match_ratio = 0.0          # no candidate skills yet
        enriched.append({
            **job,
            "_match_ratio":   round(match_ratio * 100, 1),
            "_already_applied": job["id"] in apps_for_student,
        })

    # Sort: unapplied first, then by match ratio descending
    enriched.sort(key=lambda j: (j["_already_applied"], -j["_match_ratio"]))

    has_profile = bool(candidate_skills)
    return render_template(
        "job_list.html",
        user=user,
        jobs=enriched,
        has_profile=has_profile,
    )


@app.route("/jobs/apply/<job_id>", methods=["POST"])
@require_role("student")
def job_apply(job_id: str):
    """Submit an application for *job_id* using the session candidate profile."""
    user    = session.get("user", "")
    profile = session.get("candidate_profile")

    if not profile:
        flash(
            "Please complete a resume analysis first — "
            "your profile is needed to apply.",
            "error",
        )
        return redirect(url_for("index"))

    job = get_job(job_id)
    if job is None:
        flash("That job no longer exists.", "error")
        return redirect(url_for("job_list"))

    result = apply_to_job(
        job_id               = job_id,
        student_id           = user,
        student_profile_dict = profile,
    )

    if result is None:
        flash(f"You have already applied to \u2018{job['title']}\u2019.", "info")
    else:
        flash(
            f"Application to \u2018{job['title']}\u2019 at {job['company']} submitted!",
            "success",
        )
        logger.info("job_apply: student=%s job=%s app=%s", user, job_id, result["id"])

    return redirect(url_for("job_list"))


# --------------------------------------------------------------------------- #
#  Routes – JSON API                                                           #
# --------------------------------------------------------------------------- #

@app.route("/api/roles", methods=["GET"])
def api_roles():
    """Return the list of available roles."""
    return jsonify({"roles": AVAILABLE_ROLES})


@app.route("/api/analyse", methods=["POST"])
def api_analyse():
    """
    JSON/multipart API endpoint.

    Form fields:
        resume           – file (required)
        github_username  – string
        leetcode_username– string
        cgpa             – float string
        target_role      – string
    """
    if "resume" not in request.files or request.files["resume"].filename == "":
        return jsonify({"error": "No resume file uploaded."}), 400

    file = request.files["resume"]
    if not _allowed_file(file.filename):
        return jsonify({"error": "Unsupported file type. Use PDF, DOCX, or TXT."}), 400

    filename  = secure_filename(file.filename)
    raw_bytes = file.read()

    if not raw_bytes:
        return jsonify({"error": "Uploaded file is empty."}), 400

    github_user   = request.form.get("github_username",   "").strip()
    leetcode_user = request.form.get("leetcode_username", "").strip()
    target_role   = request.form.get("target_role",       "").strip() or None

    cgpa, cgpa_warn = _parse_cgpa(request.form.get("cgpa", ""))
    pre_warnings = [cgpa_warn] if cgpa_warn else []

    try:
        result = _run_pipeline(
            resume_bytes    = raw_bytes,
            resume_filename = filename,
            github_user     = github_user,
            leetcode_user   = leetcode_user,
            cgpa            = cgpa,
            target_role     = target_role,
            pre_warnings    = pre_warnings,
        )
    except Exception as exc:
        logger.exception("API pipeline error: %s", exc)
        return jsonify({"error": str(exc)}), 500

    return jsonify(result)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "placement-analysis-backend"})


# --------------------------------------------------------------------------- #
#  Error handlers                                                              #
# --------------------------------------------------------------------------- #

@app.errorhandler(413)
def too_large(e):
    flash("File is too large. Maximum allowed size is 5 MB.", "error")
    return redirect(url_for("index"))


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found."}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error."}), 500


# --------------------------------------------------------------------------- #
#  Entry point                                                                 #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
