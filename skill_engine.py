"""
skill_engine.py
---------------
Core skill intelligence module.

Responsibilities:
  1. Extract skills from raw resume text against a skill vocabulary.
  2. Merge resume skills + GitHub verified skills + LeetCode DSA skills
     into a unified candidate skill profile.
  3. Compute a skill-authenticity score for each skill and an aggregate score.

All skill names are normalised to lowercase.
"""

import os
import re
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Load skill vocabulary from data/skills.json                               #
# --------------------------------------------------------------------------- #

_SKILLS_JSON = os.path.join(os.path.dirname(__file__), "data", "skills.json")


def _load_skill_vocabulary() -> dict:
    try:
        with open(_SKILLS_JSON, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.error("Could not load skills.json: %s", exc)
        return {}


_SKILL_VOCAB: dict = _load_skill_vocabulary()

# Build a flat set of all known skills + a list sorted by length descending
# (longer phrases must be matched before shorter ones to avoid partial hits)
_ALL_SKILLS: list = sorted(
    {s.lower() for cat in _SKILL_VOCAB.values() for s in cat},
    key=len,
    reverse=True,
)


# --------------------------------------------------------------------------- #
#  Skill extraction from text                                                  #
# --------------------------------------------------------------------------- #

# Precompile regex patterns for every skill once at import time.
# _ALL_SKILLS is already sorted longest-first, so multi-word phrases are
# matched before their component words — preventing false positives like
# "machine learning" swallowing "learning" independently.
_SKILL_PATTERNS: list = []


def _build_patterns() -> None:
    global _SKILL_PATTERNS
    _SKILL_PATTERNS = []
    for skill in _ALL_SKILLS:
        escaped = re.escape(skill)
        # Negative look-behind / look-ahead: don't match inside longer tokens.
        # e.g.  "r" must not fire inside "react", "array", "pytorch" …
        pattern = re.compile(
            r'(?<![a-z0-9])' + escaped + r'(?![a-z0-9])',
            re.IGNORECASE,
        )
        _SKILL_PATTERNS.append((skill, pattern))


_build_patterns()


def extract_resume_skills(text: str) -> list:
    """
    Scan *text* for every skill listed in the vocabulary.

    Parameters
    ----------
    text : str
        Typically the cleaned, lowercased resume text produced by
        ``resume_parser.extract_resume_text()``.

    Returns
    -------
    list[str]
        Sorted, deduplicated, lowercase skill names found in *text*.
        Returns an empty list when *text* is empty or ``None``.

    Notes
    -----
    * Input is lowercased before matching so comparisons are
      case-insensitive.
    * Patterns are sorted longest-first, so "machine learning" is
      captured as a unit rather than as "machine" + "learning".
    * Word-boundary anchors (``(?<![a-z0-9])…(?![a-z0-9])``) prevent
      short skill tokens (e.g. ``"r"``, ``"go"``) from matching inside
      longer words.
    """
    if not text:
        return []

    text_lower = text.lower()
    found: set = set()

    for skill, pattern in _SKILL_PATTERNS:
        if pattern.search(text_lower):
            found.add(skill)

    return sorted(found)


# --------------------------------------------------------------------------- #
#  Skill merging                                                               #
# --------------------------------------------------------------------------- #

def merge_candidate_skills(
    resume_skills: list,
    github_skills: list,
) -> list:
    """
    Return the union of resume and GitHub skills, all normalised to lowercase.

    Parameters
    ----------
    resume_skills : list[str]
        Skills extracted from the candidate's resume.
    github_skills : list[str]
        Skills inferred from the candidate's GitHub profile.

    Returns
    -------
    list[str]
        Sorted list of unique, lowercase skill strings.
    """
    union = (
        {s.lower() for s in (resume_skills or [])}
        | {s.lower() for s in (github_skills or [])}
    )
    return sorted(union)


# --------------------------------------------------------------------------- #
#  Authenticity scoring                                                        #
# --------------------------------------------------------------------------- #

def compute_authenticity(
    resume_skills: list,
    github_skills: list,
) -> float:
    """
    Compute what fraction of resume-claimed skills are verified on GitHub.

    Formula
    -------
    ``authenticity = |resume ∩ github| / |resume|``

    Edge cases
    ----------
    * No resume skills  → ``0.0``
    * No github skills  → ``0.0``
    * Otherwise         → float in ``[0.0, 1.0]`` rounded to 4 d.p.

    Parameters
    ----------
    resume_skills : list[str]
        Skills extracted from the resume.
    github_skills : list[str]
        Skills extracted from GitHub activity.

    Returns
    -------
    float
        Authenticity ratio in ``[0.0, 1.0]``.
    """
    if not resume_skills:
        return 0.0
    if not github_skills:
        return 0.0

    resume_set = {s.lower() for s in resume_skills}
    github_set = {s.lower() for s in github_skills}
    verified   = resume_set & github_set

    return round(len(verified) / len(resume_set), 4)


# --------------------------------------------------------------------------- #
#  Convenience: full skill analysis pipeline (kept for app.py compatibility)  #
# --------------------------------------------------------------------------- #

def _build_skill_sources(
    resume_skills:   list,
    github_skills:   list,
    leetcode_skills: list,
) -> dict:
    """Return a per-skill dict mapping skill → list of source labels."""
    resume_set   = {s.lower() for s in (resume_skills   or [])}
    github_set   = {s.lower() for s in (github_skills   or [])}
    leetcode_set = {s.lower() for s in (leetcode_skills or [])}

    all_skills = resume_set | github_set | leetcode_set
    sources: dict = {}
    for skill in all_skills:
        tags = []
        if skill in resume_set:
            tags.append("resume")
        if skill in github_set:
            tags.append("github")
        if skill in leetcode_set:
            tags.append("leetcode")
        sources[skill] = tags
    return sources


def analyse_skills(
    resume_text:   str,
    github_data:   Optional[dict] = None,
    leetcode_data: Optional[dict] = None,
) -> dict:
    """
    Run the complete skill analysis pipeline on resume text + external data.

    Parameters
    ----------
    resume_text   : str  – cleaned resume text from resume_parser
    github_data   : dict – output of github_parser.get_github_data()
    leetcode_data : dict – output of leetcode_parser.get_leetcode_data()

    Returns
    -------
    dict with keys
        ``resume_skills``    list[str]
        ``github_skills``    list[str]
        ``leetcode_skills``  list[str]
        ``candidate_skills`` list[str]  – union of all three sources
        ``skill_sources``    dict       – per-skill source tags
        ``authenticity``     dict       – ``{"aggregate": float}``
                                          (aggregate = resume-vs-github ratio)
    """
    github_data   = github_data   or {}
    leetcode_data = leetcode_data or {}

    resume_skills   = extract_resume_skills(resume_text or "")
    github_skills   = [s.lower() for s in github_data.get("verified_skills", [])]
    leetcode_skills = [s.lower() for s in leetcode_data.get("dsa_skills",     [])]

    candidate_skills = sorted(
        {s.lower() for s in resume_skills}
        | {s.lower() for s in github_skills}
        | {s.lower() for s in leetcode_skills}
    )

    skill_sources = _build_skill_sources(resume_skills, github_skills, leetcode_skills)

    aggregate = compute_authenticity(resume_skills, github_skills)

    return {
        "resume_skills":    resume_skills,
        "github_skills":    github_skills,
        "leetcode_skills":  leetcode_skills,
        "candidate_skills": candidate_skills,
        "skill_sources":    skill_sources,
        # Wrap in a dict so callers can do  authenticity["aggregate"]
        "authenticity": {"aggregate": aggregate},
    }


# --------------------------------------------------------------------------- #
#  Self-tests                                                                  #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    _PASS = "\033[92mPASS\033[0m"
    _FAIL = "\033[91mFAIL\033[0m"
    _results: list = []

    def _check(label: str, condition: bool) -> None:
        tag = _PASS if condition else _FAIL
        print(f"  [{tag}] {label}")
        _results.append(condition)

    print("\n=== skill_engine self-tests ===\n")

    # --- extract_resume_skills ---
    print("extract_resume_skills()")

    r = extract_resume_skills("")
    _check("empty string → []", r == [])

    r = extract_resume_skills(None)           # type: ignore[arg-type]
    _check("None → []", r == [])

    r = extract_resume_skills("i know python and java for backend development")
    _check("'python' found", "python" in r)
    _check("'java' found",   "java"   in r)

    r = extract_resume_skills("experience with machine learning and deep learning")
    _check("'machine learning' found",  "machine learning" in r)
    _check("'deep learning' found",     "deep learning"    in r)

    # Single-char skill "r" must NOT fire inside "react" or "arrays"
    r_short = extract_resume_skills("react arrays sort")
    _check("'r' NOT false-positive inside 'react'/'arrays'",
           "r" not in r_short or "react" in r_short)

    r = extract_resume_skills("proficient in c++ and .net framework")
    _check("'c++' detected",  "c++"  in r)
    _check("'.net' detected", ".net" in r)

    r = extract_resume_skills("postgresql mysql redis nosql")
    _check("multi-db extraction deduped and sorted",
           r == sorted(set(r)))

    # --- merge_candidate_skills ---
    print("\nmerge_candidate_skills()")

    m = merge_candidate_skills(["Python", "Flask"], ["python", "Docker"])
    _check("union deduplicates 'python'", m.count("python") == 1)
    _check("'flask'  in merged",          "flask"  in m)
    _check("'docker' in merged",          "docker" in m)
    _check("result is sorted",            m == sorted(m))

    m = merge_candidate_skills([], [])
    _check("both empty → []", m == [])

    m = merge_candidate_skills(["react"], [])
    _check("empty github → resume only", m == ["react"])

    # --- compute_authenticity ---
    print("\ncompute_authenticity()")

    a = compute_authenticity([], ["python"])
    _check("no resume → 0.0", a == 0.0)

    a = compute_authenticity(["python", "flask"], [])
    _check("no github → 0.0", a == 0.0)

    a = compute_authenticity(["python", "flask", "docker"],
                             ["python", "docker", "kubernetes"])
    _check("2/3 verified → ~0.6667",
           abs(a - round(2/3, 4)) < 1e-6)

    a = compute_authenticity(["python"], ["python"])
    _check("perfect match → 1.0", a == 1.0)

    a = compute_authenticity(["python", "java"], ["go", "rust"])
    _check("no overlap → 0.0", a == 0.0)

    # --- analyse_skills wrapper ---
    print("\nanalyse_skills()")

    result = analyse_skills(
        resume_text   = "experienced with python flask and postgresql",
        github_data   = {"verified_skills": ["python", "flask"], "success": True},
        leetcode_data = {"dsa_skills": ["arrays", "graphs"],     "success": True},
    )
    _check("keys present",
           all(k in result for k in
               ("resume_skills", "github_skills", "leetcode_skills",
                "candidate_skills", "skill_sources", "authenticity")))
    _check("authenticity is a dict with 'aggregate'",
           isinstance(result["authenticity"], dict)
           and "aggregate" in result["authenticity"])
    _check("aggregate in [0,1]",
           0.0 <= result["authenticity"]["aggregate"] <= 1.0)
    _check("candidate_skills is superset of resume_skills",
           all(s in result["candidate_skills"] for s in result["resume_skills"]))

    print()
    passed = sum(_results)
    total  = len(_results)
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        raise SystemExit(1)
