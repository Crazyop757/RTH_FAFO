"""
job_engine.py
=============
Create, retrieve, and count jobs stored in data/jobs.json.

Storage format — each record:
{
    "id":              <uuid4 string>,
    "title":           <string>,
    "company":         <string>,
    "description":     <string>,
    "required_skills": [<lowercase string>, ...],
    "created_by":      <string>,          # recruiter username
    "created_at":      <ISO-8601 string>
}

Public API
----------
create_job(title, company, description, required_skills, created_by) -> dict
get_all_jobs()                                                         -> list[dict]
get_job(job_id)                                                        -> dict | None
count_applications(job_id)                                             -> int
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
_JOBS_FILE  = os.path.join(_DATA_DIR, "jobs.json")

# Lazily imported to avoid circular import (application_engine imports job_engine)
def _count_applications_from_file(job_id: str) -> int:
    """Read applications.json directly to count without importing application_engine."""
    apps_file = os.path.join(_DATA_DIR, "applications.json")
    try:
        records = _read_json(apps_file)
        return sum(1 for a in records if a.get("job_id") == job_id)
    except Exception:
        return 0


# ── Low-level I/O helpers ─────────────────────────────────────────────────────

def _ensure_data_dir() -> None:
    """Create data/ directory if it doesn't exist."""
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
    Uses a temp-then-rename pattern so a crash cannot corrupt the file.
    Returns True on success, False on failure.
    """
    _ensure_data_dir()
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2, ensure_ascii=False)
        # Atomic rename (on Windows this replaces the dest if it exists)
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


# ── Public API ────────────────────────────────────────────────────────────────

def create_job(
    title:           str,
    company:         str,
    description:     str,
    required_skills: list[str] | str,
    created_by:      str,
) -> dict:
    """
    Persist a new job and return its full record.

    Parameters
    ----------
    title, company, description : str
        Basic job metadata. Stripped of leading/trailing whitespace.
    required_skills : list[str] | str
        Accepts a list or a comma-separated string; normalised to lowercase.
    created_by : str
        Recruiter username (from session["user"]).

    Returns
    -------
    dict
        The newly created job record including its generated ``id``.

    Raises
    ------
    ValueError
        If any of title, company, or created_by are blank.
    """
    title       = str(title).strip()
    company     = str(company).strip()
    description = str(description).strip()
    created_by  = str(created_by).strip()

    if not title:
        raise ValueError("Job title cannot be empty.")
    if not company:
        raise ValueError("Company name cannot be empty.")
    if not created_by:
        raise ValueError("created_by (recruiter username) cannot be empty.")

    job: dict = {
        "id":              str(uuid4()),
        "title":           title,
        "company":         company,
        "description":     description,
        "required_skills": _normalise_skills(required_skills),
        "created_by":      created_by,
        "created_at":      datetime.now(timezone.utc).isoformat(),
    }

    records = _read_json(_JOBS_FILE)
    records.append(job)
    if not _write_json(_JOBS_FILE, records):
        logger.error("create_job: failed to persist job %s", job["id"])

    logger.info("create_job: created job '%s' (%s) by '%s'", title, job["id"], created_by)
    return job


def get_all_jobs() -> list[dict]:
    """
    Return all jobs, newest first.
    Always returns a list — empty on I/O error.
    """
    records = _read_json(_JOBS_FILE)
    return sorted(records, key=lambda j: j.get("created_at", ""), reverse=True)


def get_job(job_id: str) -> dict | None:
    """
    Return the job with *job_id*, or None if not found.
    """
    if not job_id:
        return None
    records = _read_json(_JOBS_FILE)
    for job in records:
        if job.get("id") == job_id:
            return job
    return None


def count_applications(job_id: str) -> int:
    """
    Return the number of applications submitted against *job_id*.
    Returns 0 on any error.
    """
    if not job_id:
        return 0
    return _count_applications_from_file(job_id)


# ── Dev self-test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile, sys

    logging.basicConfig(level=logging.DEBUG)
    print("=== job_engine self-test ===")

    # Redirect storage to a temp directory so we don't pollute data/
    _orig_jobs_file = _JOBS_FILE
    _tmp_dir = tempfile.mkdtemp()
    _JOBS_FILE = os.path.join(_tmp_dir, "jobs.json")  # type: ignore[assignment]

    # Utility to reset between tests
    def _reset():
        global _JOBS_FILE
        _JOBS_FILE = os.path.join(_tmp_dir, "jobs.json")
        if os.path.exists(_JOBS_FILE):
            os.unlink(_JOBS_FILE)

    errors: list[str] = []

    # Test 1 — create and retrieve
    _reset()
    j = create_job("SDE Intern", "TechCorp", "Build cool stuff", ["python", "flask"], "alice")
    assert j["title"] == "SDE Intern", "T1a"
    assert j["required_skills"] == ["python", "flask"], "T1b"
    assert len(j["id"]) == 36, "T1c"
    print("  T1 create_job            ✓")

    # Test 2 — get_all_jobs
    _reset()
    create_job("A", "X", "", ["python"], "alice")
    create_job("B", "Y", "", ["java"], "bob")
    jobs = get_all_jobs()
    assert len(jobs) == 2, "T2a"
    assert jobs[0]["title"] == "B", "T2b (newest first)"
    print("  T2 get_all_jobs           ✓")

    # Test 3 — get_job
    _reset()
    created = create_job("ML Eng", "DataInc", "ML work", ["pytorch"], "carol")
    fetched = get_job(created["id"])
    assert fetched is not None, "T3a"
    assert fetched["company"] == "DataInc", "T3b"
    missing = get_job("nonexistent-id")
    assert missing is None, "T3c"
    print("  T3 get_job                ✓")

    # Test 4 — skill normalisation (uppercase, duplicates, comma-string)
    _reset()
    j = create_job("Dev", "Co", "", "Python, PYTHON, Flask , ", "user")
    assert j["required_skills"] == ["python", "flask"], f"T4 got {j['required_skills']}"
    print("  T4 skill normalisation    ✓")

    # Test 5 — blank title raises
    _reset()
    try:
        create_job("", "Co", "", [], "user")
        errors.append("T5: expected ValueError not raised")
    except ValueError:
        pass
    print("  T5 blank title raises     ✓")

    # Test 6 — empty file reads as []
    _reset()
    with open(_JOBS_FILE, "w") as f:
        f.write("")
    assert get_all_jobs() == [], "T6"
    print("  T6 empty file → []        ✓")

    # Test 7 — count_applications with no applications file
    _reset()
    j = create_job("T", "C", "", [], "u")
    assert count_applications(j["id"]) == 0, "T7"
    print("  T7 count_applications=0   ✓")

    # Cleanup
    import shutil
    shutil.rmtree(_tmp_dir, ignore_errors=True)

    if errors:
        print("\nFAILURES:")
        for e in errors:
            print(" ", e)
        sys.exit(1)
    else:
        print("\nAll tests passed ✓")
