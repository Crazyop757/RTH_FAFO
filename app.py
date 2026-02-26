"""
app.py
------
Flask entry point for the AI-driven placement analysis backend.

Routes
------
GET  /                → Upload form (index.html)
POST /analyse         → Full pipeline: parse → skills → github → leetcode
                         → role → roadmap → render report.html
GET  /api/roles       → JSON list of available roles
POST /api/analyse     → Same pipeline, returns raw JSON (for API clients)
GET  /health          → Simple health-check endpoint
"""

import os
import json
import logging
import tempfile
from typing import Optional

from flask import (
    Flask, request, render_template, jsonify,
    redirect, url_for, flash
)
from werkzeug.utils import secure_filename

from resume_parser   import extract_resume_text
from skill_engine    import extract_resume_skills, merge_candidate_skills, compute_authenticity
from github_parser   import get_github_profile
from leetcode_parser import get_leetcode_stats
from role_engine     import recommend_role, get_skill_gaps, compute_readiness
from roadmap_engine  import generate_roadmap

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
#  Routes – Web UI                                                             #
# --------------------------------------------------------------------------- #

@app.route("/", methods=["GET"])
def index():
    """Render the upload form."""
    return render_template("index.html", available_roles=AVAILABLE_ROLES)


@app.route("/analyse", methods=["POST"])
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

    return render_template("report.html", result=result)


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
