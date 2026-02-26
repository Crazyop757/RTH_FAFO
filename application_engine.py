"""
application_engine.py
=====================
Submit and retrieve job applications stored in data/applications.json.

Storage format — each record:
{
    "id":             <uuid4 string>,
    "job_id":         <string>,
    "student_id":     <string>,          # session["user"]
    "resume_skills":  [<lowercase str>, ...],
    "github_skills":  [<lowercase str>, ...],
    "leetcode_total": <int>,
    "authenticity":   <float 0-100>,
    "readiness":      <float 0-100>,
    "role_match":     <float 0-100>,
    "applied_at":     <ISO-8601 string>
}

student_profile_dict keys (all optional with safe defaults)
-----------------------------------------------------------
Keys mirror the pipeline result dict stored in session["candidate_profile"]:
    resume_skills  : list[str]
    github_skills  : list[str]
    leetcode_stats : {"total": int, ...}   OR  leetcode_total: int
    authenticity   : float
    readiness      : float
    match          : float   (role_match)

Public API
----------
apply_to_job(job_id, student_id, student_profile_dict) -> dict | None
get_applications_for_job(job_id)                       -> list[dict]
get_applications_for_student(student_id)               -> list[dict]
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# ── Storage paths ─────────────────────────────────────────────────────────────
_DATA_DIR   = os.path.join(os.path.dirname(__file__), "data")
_APPS_FILE  = os.path.join(_DATA_DIR, "applications.json")


# ── Low-level I/O helpers (duplicated by design — no shared module dep) ───────

def _ensure_data_dir() -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)


def _read_json(path: str) -> list[dict]:
    """
    Read a JSON array from *path*.
    Returns [] if file is missing, empty, or corrupt — never raises.
    """
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read().strip()
        if not content:
            return []
        data = json.loads(content)
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.error("_read_json(%s) failed: %s", path, exc)
        return []


def _write_json(path: str, records: list[dict]) -> bool:
    """
    Atomically write *records* as a JSON array to *path*.
    Returns True on success, False on failure.
    """
    _ensure_data_dir()
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2, ensure_ascii=False)
        if os.path.exists(path):
            os.replace(tmp_path, path)
        else:
            os.rename(tmp_path, path)
        return True
    except Exception as exc:
        logger.error("_write_json(%s) failed: %s", path, exc)
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return False


# ── Normalisation helpers ─────────────────────────────────────────────────────

def _normalise_skills(skills: Any) -> list[str]:
    """Return a deduplicated, lowercase, stripped list from any skill input."""
    if not skills:
        return []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    seen: set[str] = set()
    result: list[str] = []
    for s in skills:
        normalised = str(s).strip().lower()
        if normalised and normalised not in seen:
            seen.add(normalised)
            result.append(normalised)
    return result


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce *value* to int, returning *default* on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_profile_fields(profile: dict) -> dict:
    """
    Map a student_profile_dict (pipeline result / session["candidate_profile"])
    to the flat fields required by an application record.

    Accepts both naming conventions that may appear in the session dict:
      - ``leetcode_stats.total`` (pipeline result)  OR  ``leetcode_total`` (explicit)
      - ``match``  (pipeline result label)           OR  ``role_match`` (explicit)
    """
    resume_skills = _normalise_skills(profile.get("resume_skills", []))
    github_skills = _normalise_skills(profile.get("github_skills", []))

    # leetcode_total: accept dict or flat int
    lc_stats = profile.get("leetcode_stats")
    if isinstance(lc_stats, dict):
        leetcode_total = _safe_int(lc_stats.get("total", 0))
    else:
        leetcode_total = _safe_int(profile.get("leetcode_total", 0))

    authenticity = _safe_float(profile.get("authenticity", 0.0))
    readiness    = _safe_float(profile.get("readiness",    0.0))

    # role_match: accept "match" (pipeline key) or "role_match" (explicit)
    role_match = _safe_float(
        profile.get("role_match", profile.get("match", 0.0))
    )

    return {
        "resume_skills":  resume_skills,
        "github_skills":  github_skills,
        "leetcode_total": leetcode_total,
        "authenticity":   round(authenticity, 4),
        "readiness":      round(readiness,    4),
        "role_match":     round(role_match,   4),
    }


# ── Public API ────────────────────────────────────────────────────────────────

def apply_to_job(
    job_id:              str,
    student_id:          str,
    student_profile_dict: dict,
) -> dict | None:
    """
    Submit a student's application for a job.

    Parameters
    ----------
    job_id : str
        UUID of the target job (from jobs.json).
    student_id : str
        Username of the applying student (``session["user"]``).
    student_profile_dict : dict
        Pipeline result stored in ``session["candidate_profile"]``.
        Accepted keys: resume_skills, github_skills, leetcode_stats,
        leetcode_total, authenticity, readiness, match, role_match.

    Returns
    -------
    dict
        The newly created application record.
    None
        If the student has already applied to this job (duplicate prevented)
        or if any required argument is blank.

    Notes
    -----
    Duplicate detection uses (job_id, student_id) comparison only —
    a student cannot apply twice regardless of profile changes.
    """
    job_id     = str(job_id).strip()
    student_id = str(student_id).strip()

    if not job_id or not student_id:
        logger.warning("apply_to_job: job_id or student_id is blank — aborting")
        return None

    records = _read_json(_APPS_FILE)

    # Duplicate check
    for app in records:
        if app.get("job_id") == job_id and app.get("student_id") == student_id:
            logger.info(
                "apply_to_job: duplicate — student '%s' already applied to job '%s'",
                student_id, job_id,
            )
            return None

    profile_fields = _extract_profile_fields(student_profile_dict or {})

    application: dict = {
        "id":         str(uuid4()),
        "job_id":     job_id,
        "student_id": student_id,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        **profile_fields,
    }

    records.append(application)
    if not _write_json(_APPS_FILE, records):
        logger.error(
            "apply_to_job: failed to persist application %s", application["id"]
        )

    logger.info(
        "apply_to_job: student '%s' applied to job '%s' (app id=%s)",
        student_id, job_id, application["id"],
    )
    return application


def get_applications_for_job(job_id: str) -> list[dict]:
    """
    Return all applications for *job_id*, newest first.
    Returns [] on any error or if job has no applications.
    """
    if not job_id:
        return []
    try:
        records = _read_json(_APPS_FILE)
        matches = [a for a in records if a.get("job_id") == job_id]
        return sorted(matches, key=lambda a: a.get("applied_at", ""), reverse=True)
    except Exception as exc:
        logger.error("get_applications_for_job(%s) failed: %s", job_id, exc)
        return []


def get_applications_for_student(student_id: str) -> list[dict]:
    """
    Return all applications submitted by *student_id*, newest first.
    Returns [] on any error.
    """
    if not student_id:
        return []
    try:
        records = _read_json(_APPS_FILE)
        matches = [a for a in records if a.get("student_id") == student_id]
        return sorted(matches, key=lambda a: a.get("applied_at", ""), reverse=True)
    except Exception as exc:
        logger.error("get_applications_for_student(%s) failed: %s", student_id, exc)
        return []


# ── Dev self-test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import tempfile
    import shutil

    logging.basicConfig(level=logging.DEBUG)
    print("=== application_engine self-test ===")

    # Redirect storage to temp dir
    _tmp_dir  = tempfile.mkdtemp()
    _APPS_FILE_ORIG = _APPS_FILE

    def _reset_apps():
        global _APPS_FILE
        _APPS_FILE = os.path.join(_tmp_dir, "applications.json")
        if os.path.exists(_APPS_FILE):
            os.unlink(_APPS_FILE)

    SAMPLE_PROFILE = {
        "resume_skills":  ["Python", "Flask", "SQL"],
        "github_skills":  ["python", "git"],
        "leetcode_stats": {"total": 42, "easy": 20, "medium": 18, "hard": 4},
        "authenticity":   0.78,
        "readiness":      72.5,
        "match":          85.0,
    }

    errors: list[str] = []
    JOB_ID_A = "job-aaa-111"
    JOB_ID_B = "job-bbb-222"

    # Test 1 — basic apply
    _reset_apps()
    app1 = apply_to_job(JOB_ID_A, "alice", SAMPLE_PROFILE)
    assert app1 is not None, "T1a: should have returned an application"
    assert app1["student_id"] == "alice", "T1b"
    assert app1["job_id"] == JOB_ID_A, "T1c"
    assert app1["resume_skills"] == ["python", "flask", "sql"], f"T1d: {app1['resume_skills']}"
    assert app1["leetcode_total"] == 42, "T1e"
    assert app1["role_match"] == 85.0, "T1f"
    print("  T1 apply_to_job basic     ✓")

    # Test 2 — duplicate prevention
    _reset_apps()
    apply_to_job(JOB_ID_A, "alice", SAMPLE_PROFILE)
    dup = apply_to_job(JOB_ID_A, "alice", SAMPLE_PROFILE)
    assert dup is None, "T2: duplicate should return None"
    apps = get_applications_for_job(JOB_ID_A)
    assert len(apps) == 1, f"T2b: expected 1, got {len(apps)}"
    print("  T2 duplicate prevention   ✓")

    # Test 3 — different students same job
    _reset_apps()
    apply_to_job(JOB_ID_A, "alice", SAMPLE_PROFILE)
    r2 = apply_to_job(JOB_ID_A, "bob", SAMPLE_PROFILE)
    assert r2 is not None, "T3a"
    apps = get_applications_for_job(JOB_ID_A)
    assert len(apps) == 2, f"T3b: expected 2, got {len(apps)}"
    print("  T3 multiple applicants    ✓")

    # Test 4 — get_applications_for_student
    _reset_apps()
    apply_to_job(JOB_ID_A, "alice", SAMPLE_PROFILE)
    apply_to_job(JOB_ID_B, "alice", SAMPLE_PROFILE)
    apply_to_job(JOB_ID_A, "bob",   SAMPLE_PROFILE)
    alice_apps = get_applications_for_student("alice")
    assert len(alice_apps) == 2, f"T4a: expected 2, got {len(alice_apps)}"
    bob_apps = get_applications_for_student("bob")
    assert len(bob_apps) == 1, "T4b"
    print("  T4 get_by_student         ✓")

    # Test 5 — profile with explicit leetcode_total key (not nested dict)
    _reset_apps()
    flat_profile = {
        "resume_skills":  ["java"],
        "github_skills":  [],
        "leetcode_total": 100,
        "authenticity":   0.5,
        "readiness":      60.0,
        "role_match":     70.0,
    }
    a = apply_to_job(JOB_ID_A, "carol", flat_profile)
    assert a is not None, "T5a"
    assert a["leetcode_total"] == 100, "T5b"
    assert a["role_match"] == 70.0, "T5c"
    print("  T5 flat profile dict      ✓")

    # Test 6 — blank job_id / student_id
    _reset_apps()
    assert apply_to_job("", "alice", SAMPLE_PROFILE) is None, "T6a"
    assert apply_to_job(JOB_ID_A, "", SAMPLE_PROFILE) is None, "T6b"
    print("  T6 blank id returns None  ✓")

    # Test 7 — empty / corrupt applications file
    _reset_apps()
    with open(_APPS_FILE, "w") as f:
        f.write("")
    assert get_applications_for_job(JOB_ID_A) == [], "T7a"
    with open(_APPS_FILE, "w") as f:
        f.write("not json {{")
    assert get_applications_for_student("alice") == [], "T7b"
    print("  T7 corrupt file → []      ✓")

    # Test 8 — skills normalised in stored record
    _reset_apps()
    profile_upper = dict(SAMPLE_PROFILE)
    profile_upper["resume_skills"] = ["PYTHON", "Python", "  Flask  "]
    a = apply_to_job(JOB_ID_A, "dave", profile_upper)
    assert a["resume_skills"] == ["python", "flask"], f"T8: {a['resume_skills']}"
    print("  T8 skill normalisation    ✓")

    # Cleanup
    shutil.rmtree(_tmp_dir, ignore_errors=True)

    if errors:
        print("\nFAILURES:")
        for e in errors:
            print(" ", e)
        sys.exit(1)
    else:
        print("\nAll tests passed ✓")
