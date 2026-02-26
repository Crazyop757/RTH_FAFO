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
from typing import Optional

from flask import (
    Flask, request, render_template, jsonify,
    redirect, url_for, flash
)
from werkzeug.utils import secure_filename

from resume_parser  import parse_resume_from_bytes
from skill_engine   import analyse_skills
from github_parser  import get_github_data
from leetcode_parser import get_leetcode_data
from role_engine    import analyse_role_fit
from roadmap_engine import generate_roadmap

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


def _run_pipeline(
    resume_bytes:   bytes,
    resume_filename: str,
    github_user:    str,
    leetcode_user:  str,
    cgpa:           Optional[float],
    target_role:    Optional[str],
) -> dict:
    """
    Execute the full analysis pipeline and return a structured result dict.
    All steps handle missing / failed data gracefully.
    """
    pipeline_log = []

    # ── Step 1: Parse Resume ─────────────────────────────────────────────────
    logger.info("Parsing resume: %s", resume_filename)
    resume_result = parse_resume_from_bytes(resume_bytes, resume_filename)
    pipeline_log.append({
        "step":    "resume_parser",
        "success": resume_result["success"],
        "detail":  resume_result.get("error", ""),
    })
    raw_text = resume_result.get("raw_text", "")

    # ── Step 2: GitHub data ──────────────────────────────────────────────────
    github_data = {}
    if github_user:
        logger.info("Fetching GitHub data for: %s", github_user)
        github_data = get_github_data(github_user, token=GITHUB_TOKEN)
        pipeline_log.append({
            "step":    "github_parser",
            "success": github_data.get("success", False),
            "detail":  github_data.get("error", ""),
        })
    else:
        pipeline_log.append({"step": "github_parser", "success": False, "detail": "No username provided"})

    # ── Step 3: LeetCode data ────────────────────────────────────────────────
    leetcode_data = {}
    if leetcode_user:
        logger.info("Fetching LeetCode data for: %s", leetcode_user)
        leetcode_data = get_leetcode_data(leetcode_user)
        pipeline_log.append({
            "step":    "leetcode_parser",
            "success": leetcode_data.get("success", False),
            "detail":  leetcode_data.get("error", ""),
        })
    else:
        pipeline_log.append({"step": "leetcode_parser", "success": False, "detail": "No username provided"})

    # ── Step 4: Skill Analysis ───────────────────────────────────────────────
    logger.info("Analysing skills")
    skill_analysis = analyse_skills(
        resume_text   = raw_text,
        github_data   = github_data,
        leetcode_data = leetcode_data,
    )
    pipeline_log.append({"step": "skill_engine", "success": True, "detail": ""})

    # ── Step 5: Role Fit & Gaps ──────────────────────────────────────────────
    logger.info("Analysing role fit")
    role_analysis = analyse_role_fit(
        candidate_skills = skill_analysis["candidate_skills"],
        authenticity     = skill_analysis["authenticity"],
        leetcode_data    = leetcode_data,
        cgpa             = cgpa,
        target_role      = target_role,
        top_n            = 5,
    )
    pipeline_log.append({"step": "role_engine", "success": True, "detail": ""})

    # ── Step 6: Roadmap ──────────────────────────────────────────────────────
    logger.info("Generating roadmap")
    roadmap = generate_roadmap(
        skill_gaps       = role_analysis["skill_gaps"],
        candidate_skills = skill_analysis["candidate_skills"],
        role_name        = role_analysis["primary_role"],
        leetcode_data    = leetcode_data,
    )
    pipeline_log.append({"step": "roadmap_engine", "success": True, "detail": ""})

    return {
        # Input echo
        "input": {
            "resume_filename": resume_filename,
            "github_user":     github_user,
            "leetcode_user":   leetcode_user,
            "cgpa":            cgpa,
            "target_role":     target_role,
        },
        # Raw parsers
        "resume":      resume_result,
        "github":      github_data,
        "leetcode":    leetcode_data,
        # Derived analytics
        "skills":      skill_analysis,
        "role":        role_analysis,
        "roadmap":     roadmap,
        # Meta
        "pipeline_log": pipeline_log,
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
    """Handle form submission and render the report."""
    # ── Validate file ────────────────────────────────────────────────────────
    if "resume" not in request.files:
        flash("No file uploaded.", "error")
        return redirect(url_for("index"))

    file = request.files["resume"]
    if file.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("index"))

    if not _allowed_file(file.filename):
        flash("Unsupported file type. Upload a PDF, DOCX, or TXT.", "error")
        return redirect(url_for("index"))

    filename  = secure_filename(file.filename)
    raw_bytes = file.read()

    # ── Form fields ──────────────────────────────────────────────────────────
    github_user   = request.form.get("github_username",   "").strip()
    leetcode_user = request.form.get("leetcode_username", "").strip()
    target_role   = request.form.get("target_role",       "").strip() or None

    cgpa_raw = request.form.get("cgpa", "").strip()
    try:
        cgpa = float(cgpa_raw) if cgpa_raw else None
        if cgpa is not None and not (0.0 <= cgpa <= 10.0):
            flash("CGPA must be between 0 and 10.", "error")
            return redirect(url_for("index"))
    except ValueError:
        flash("Invalid CGPA value.", "error")
        return redirect(url_for("index"))

    # ── Run pipeline ──────────────────────────────────────────────────────────
    try:
        result = _run_pipeline(
            resume_bytes    = raw_bytes,
            resume_filename = filename,
            github_user     = github_user,
            leetcode_user   = leetcode_user,
            cgpa            = cgpa,
            target_role     = target_role,
        )
    except Exception as exc:
        logger.exception("Pipeline error: %s", exc)
        flash(f"An internal error occurred: {exc}", "error")
        return redirect(url_for("index"))

    if not result["resume"]["success"]:
        flash(
            f"Resume parsing failed: {result['resume']['error']}",
            "error",
        )
        return redirect(url_for("index"))

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
    if "resume" not in request.files:
        return jsonify({"error": "No resume file uploaded."}), 400

    file = request.files["resume"]
    if not file or not _allowed_file(file.filename):
        return jsonify({"error": "Unsupported or missing file."}), 400

    filename  = secure_filename(file.filename)
    raw_bytes = file.read()

    github_user   = request.form.get("github_username",   "").strip()
    leetcode_user = request.form.get("leetcode_username", "").strip()
    target_role   = request.form.get("target_role",       "").strip() or None

    cgpa_raw = request.form.get("cgpa", "").strip()
    try:
        cgpa = float(cgpa_raw) if cgpa_raw else None
    except ValueError:
        return jsonify({"error": "Invalid CGPA."}), 400

    try:
        result = _run_pipeline(
            resume_bytes    = raw_bytes,
            resume_filename = filename,
            github_user     = github_user,
            leetcode_user   = leetcode_user,
            cgpa            = cgpa,
            target_role     = target_role,
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
