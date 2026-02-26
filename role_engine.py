"""
role_engine.py
--------------
Handles:
  1. Role recommendation   – ranks all roles against candidate skills
  2. Readiness score       – weighted assessment of fit for a specific role
  3. Skill gap analysis    – required skills the candidate is missing
  4. CGPA integration      – CGPA acts as a soft filter / bonus modifier
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_ROLES_JSON = os.path.join(os.path.dirname(__file__), "data", "roles.json")


def _load_roles() -> dict:
    try:
        with open(_ROLES_JSON, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.error("Could not load roles.json: %s", exc)
        return {}


_ROLES: dict = _load_roles()


# --------------------------------------------------------------------------- #
#  Internal helpers                                                            #
# --------------------------------------------------------------------------- #

def _flatten_required(role_data: dict) -> dict:
    """
    Flatten the nested required_skills dict into a single {skill: weight} map.
    """
    flat: dict = {}
    required = role_data.get("required_skills", {})
    if isinstance(required, dict):
        for group in required.values():
            if isinstance(group, dict):
                for skill, weight in group.items():
                    flat[skill.lower()] = max(flat.get(skill.lower(), 0), weight)
    return flat


def _match_score(candidate_set: set, role_flat: dict) -> tuple:
    """
    Compute weighted match score and return (score, max_possible, matched_skills).

    Score = Σ weight  for each required skill present in candidate_set
    Max   = Σ weight  for ALL required skills

    Returns (raw_score, max_score, matched_set)
    """
    raw            = 0
    max_score      = sum(role_flat.values())
    matched_skills = set()

    for skill, weight in role_flat.items():
        if skill in candidate_set:
            raw += weight
            matched_skills.add(skill)

    return raw, max_score, matched_skills


def _cgpa_multiplier(cgpa: Optional[float], min_cgpa: float) -> float:
    """
    Returns a multiplier [0.85, 1.05] based on CGPA vs role minimum.
    - Slightly boosts scores when CGPA is above minimum.
    - Applies a small penalty when below minimum.
    - Returns 1.0 when CGPA is unknown.
    """
    if cgpa is None or cgpa <= 0:
        return 1.0
    if cgpa >= min_cgpa + 1.5:
        return 1.05
    if cgpa >= min_cgpa:
        return 1.0
    if cgpa >= min_cgpa - 1.0:
        return 0.95
    return 0.85


# --------------------------------------------------------------------------- #
#  Public API – simple role recommendation (primary function)                 #
# --------------------------------------------------------------------------- #

def recommend_role(candidate_skills: list) -> tuple:
    """
    Return the single best-matching role and its match ratio.

    Algorithm
    ---------
    For every role in roles.json::

        required      = flat set of all required skill names
        match_ratio   = |intersection(candidate, required)| / |required|

    The role with the highest ``match_ratio`` is returned.

    Parameters
    ----------
    candidate_skills : list[str]
        Merged skill list produced by ``skill_engine.merge_candidate_skills()``.

    Returns
    -------
    tuple[str, float]
        ``(role_name, match_ratio)``
        ``role_name``   – name of the best-matching role (empty string when
                          roles.json is empty or candidate list is empty)
        ``match_ratio`` – fraction of required skills covered, in ``[0.0, 1.0]``

    Examples
    --------
    >>> recommend_role(["python", "flask", "sql", "docker"])
    ('Backend Developer', 0.3333...)
    """
    if not candidate_skills or not _ROLES:
        return ("", 0.0)

    candidate_set = {s.lower() for s in candidate_skills}
    best_role     = ""
    best_ratio    = -1.0

    for role_name, role_data in _ROLES.items():
        flat_req      = _flatten_required(role_data)
        required_count = len(flat_req)
        if required_count == 0:
            continue

        matched     = sum(1 for skill in flat_req if skill in candidate_set)
        match_ratio = matched / required_count

        if match_ratio > best_ratio:
            best_ratio = match_ratio
            best_role  = role_name

    return (best_role, round(best_ratio, 4))


# --------------------------------------------------------------------------- #
#  Public API – simple skill gap list (primary function)                      #
# --------------------------------------------------------------------------- #

def get_skill_gaps(candidate_skills: list, role: str) -> list:
    """
    Return the required skills the candidate is missing for *role*.

    Formula
    -------
    ``gaps = required_skills(role) − candidate_skills``

    Parameters
    ----------
    candidate_skills : list[str]
        Merged skill list from ``skill_engine.merge_candidate_skills()``.
    role : str
        Role name exactly as it appears in roles.json.  A case-insensitive
        fallback is attempted when an exact match is not found.

    Returns
    -------
    list[str]
        Sorted list of lowercase skill names the candidate lacks.
        Returns an empty list when the role is not found.

    Examples
    --------
    >>> get_skill_gaps(["python", "docker"], "Backend Developer")
    ['postgresql', 'redis', 'rest api', ...]
    """
    role_data = _ROLES.get(role)
    if not role_data:
        # case-insensitive fallback
        for rname, rdata in _ROLES.items():
            if rname.lower() == role.lower():
                role_data = rdata
                break

    if not role_data:
        logger.warning("get_skill_gaps: role '%s' not found in roles.json", role)
        return []

    candidate_set = {s.lower() for s in (candidate_skills or [])}
    flat_req      = _flatten_required(role_data)

    gaps = sorted(skill for skill in flat_req if skill not in candidate_set)
    return gaps


# --------------------------------------------------------------------------- #
#  Public API – ranked role recommendation (full version, kept for app.py)   #
# --------------------------------------------------------------------------- #

def recommend_roles(
    candidate_skills: list,
    cgpa:             Optional[float] = None,
    top_n:            int             = 5,
) -> list:
    """
    Rank all roles in roles.json by match against candidate skills.

    Parameters
    ----------
    candidate_skills : list[str]  – merged skill list from skill_engine
    cgpa             : float|None – candidate CGPA (e.g. 7.5 / 10)
    top_n            : int        – how many top roles to return

    Returns
    -------
    list of dicts (sorted by match %, descending):
        role          (str)
        match_pct     (float 0-100)
        matched_count (int)
        total_required(int)
        description   (str)
        nice_to_have_present (list[str])
    """
    candidate_set = {s.lower() for s in (candidate_skills or [])}
    results = []

    for role_name, role_data in _ROLES.items():
        flat_req   = _flatten_required(role_data)
        if not flat_req:
            continue

        raw, max_s, matched = _match_score(candidate_set, flat_req)
        min_cgpa = role_data.get("min_cgpa", 6.0)
        mult     = _cgpa_multiplier(cgpa, min_cgpa)

        match_pct = round(min((raw / max_s) * 100 * mult, 100.0), 2) if max_s else 0.0

        nice_to_have = [s.lower() for s in role_data.get("nice_to_have", [])]
        nth_present  = [s for s in nice_to_have if s in candidate_set]

        results.append({
            "role":                 role_name,
            "match_pct":            match_pct,
            "matched_count":        len(matched),
            "total_required":       len(flat_req),
            "description":          role_data.get("description", ""),
            "nice_to_have_present": nth_present,
        })

    results.sort(key=lambda x: x["match_pct"], reverse=True)
    return results[:top_n]


# --------------------------------------------------------------------------- #
#  Public API – simple readiness score (primary function)                     #
# --------------------------------------------------------------------------- #

def compute_readiness(
    match_score:     float,
    authenticity:    float,
    leetcode_total:  int,
    repo_count:      int,
    cgpa:            float,
) -> float:
    """
    Compute a 0–100 readiness score from normalised component inputs.

    Normalisation
    -------------
    * ``match_score``  – already in ``[0.0, 1.0]`` (fraction of required skills matched)
    * ``authenticity`` – already in ``[0.0, 1.0]`` (from ``compute_authenticity``)
    * ``leetcode_norm = min(1.0, leetcode_total / 300)``
    * ``repo_norm     = min(1.0, repo_count    / 10)``
    * ``cgpa_norm     = cgpa / 10``  (assumes 10-point scale)

    Weights
    -------
    =============  ======
    Component      Weight
    =============  ======
    Skill match    0.40
    Authenticity   0.20
    LeetCode DSA   0.20
    GitHub repos   0.10
    CGPA           0.10
    =============  ======

    Parameters
    ----------
    match_score    : float – fraction ``[0, 1]`` of role required skills matched
    authenticity   : float – resume-vs-github verification ratio ``[0, 1]``
    leetcode_total : int   – total accepted LeetCode submissions
    repo_count     : int   – number of public GitHub repositories
    cgpa           : float – CGPA on a 10-point scale

    Returns
    -------
    float
        Readiness percentage in ``[0.0, 100.0]``, rounded to 2 decimal places.
    """
    leetcode_norm = min(1.0, max(0.0, leetcode_total) / 300)
    repo_norm     = min(1.0, max(0.0, repo_count)     / 10)
    cgpa_norm     = min(1.0, max(0.0, cgpa)           / 10)

    # Clamp inputs that should already be in [0, 1]
    match_score   = max(0.0, min(1.0, match_score))
    authenticity  = max(0.0, min(1.0, authenticity))

    raw = (
        0.40 * match_score
        + 0.20 * authenticity
        + 0.20 * leetcode_norm
        + 0.10 * repo_norm
        + 0.10 * cgpa_norm
    )

    return round(max(0.0, min(100.0, raw * 100)), 2)


# --------------------------------------------------------------------------- #
#  Public API – detailed readiness score for a role  (kept for app.py)       #
# --------------------------------------------------------------------------- #

def compute_readiness_full(
    role_name:        str,
    candidate_skills: list,
    authenticity:     dict,
    leetcode_data:    Optional[dict] = None,
    cgpa:             Optional[float] = None,
) -> dict:
    """
    Compute a holistic readiness score (0 – 100) for a candidate vs a role.

    Components
    ----------
    Skill Match   (50%) – weighted required-skills coverage
    Authenticity  (20%) – aggregate authenticity score
    DSA / LeetCode(20%) – LeetCode activity × role's dsa_weight factor
    CGPA          (10%) – scaled vs role min CGPA

    Returns
    -------
    dict:
        role            (str)
        readiness_score (float 0-100)
        components      (dict)  – individual component scores
        grade           (str)   – A/B/C/D/F
    """
    role_data = _ROLES.get(role_name)
    if not role_data:
        # Try case-insensitive lookup
        for rname, rdata in _ROLES.items():
            if rname.lower() == role_name.lower():
                role_data = rdata
                role_name = rname
                break

    if not role_data:
        return {
            "role": role_name,
            "readiness_score": 0.0,
            "components": {},
            "grade": "N/A",
            "error": f"Role '{role_name}' not found.",
        }

    candidate_set = {s.lower() for s in (candidate_skills or [])}
    flat_req      = _flatten_required(role_data)
    min_cgpa      = role_data.get("min_cgpa", 6.0)
    dsa_weight    = role_data.get("dsa_weight", 0.2)

    # ── Component 1: Skill Match (50%) ────────────────────────────────────────
    raw, max_s, _ = _match_score(candidate_set, flat_req)
    skill_match_pct = (raw / max_s * 100) if max_s else 0.0
    skill_component = skill_match_pct * 0.50

    # ── Component 2: Authenticity (20%) ──────────────────────────────────────
    agg_auth         = (authenticity or {}).get("aggregate", 0.0)
    auth_component   = agg_auth * 100 * 0.20

    # ── Component 3: DSA / LeetCode score (20%) ───────────────────────────────
    lc = leetcode_data or {}
    lc_activity  = lc.get("activity_score", 0.0)   # 0–1
    # Scale by role's DSA weight (e.g. SDE weights DSA heavily, Frontend less)
    dsa_component = lc_activity * 100 * dsa_weight * (0.20 / max(dsa_weight, 0.01))
    dsa_component = min(dsa_component, 20.0)         # cap at 20 pts

    # ── Component 4: CGPA (10%) ────────────────────────────────────────────────
    if cgpa and cgpa > 0:
        # Score on 10-pt scale, linearly interpolated
        cgpa_score = min(cgpa / 10.0 * 100, 100.0)
        # Penalise below minimum
        if cgpa < min_cgpa:
            cgpa_score *= 0.7
        cgpa_component = cgpa_score * 0.10
    else:
        cgpa_component = 5.0  # neutral when unknown

    total = round(skill_component + auth_component + dsa_component + cgpa_component, 2)
    total = min(total, 100.0)

    # Grade
    if   total >= 80: grade = "A"
    elif total >= 65: grade = "B"
    elif total >= 50: grade = "C"
    elif total >= 35: grade = "D"
    else:             grade = "F"

    return {
        "role":            role_name,
        "readiness_score": total,
        "components": {
            "skill_match":     round(skill_component, 2),
            "authenticity":    round(auth_component,  2),
            "dsa_leetcode":    round(dsa_component,   2),
            "cgpa":            round(cgpa_component,  2),
        },
        "grade": grade,
    }


# --------------------------------------------------------------------------- #
#  Public API – skill gap analysis                                             #
# --------------------------------------------------------------------------- #

def identify_skill_gaps(
    role_name:        str,
    candidate_skills: list,
) -> dict:
    """
    Identify required skills the candidate lacks for a given role.

    Returns
    -------
    dict:
        role             (str)
        missing_skills   (list[dict])  – sorted by importance weight desc
            skill  (str)
            weight (int)  – 1=nice, 2=important, 3=core
            label  (str)  – "Critical" / "Important" / "Recommended"
        present_skills   (list[str])
        nice_to_have_gaps(list[str])
        gap_count        (int)
        coverage_pct     (float)
    """
    role_data = _ROLES.get(role_name)
    if not role_data:
        for rname, rdata in _ROLES.items():
            if rname.lower() == role_name.lower():
                role_data = rdata
                role_name = rname
                break

    if not role_data:
        return {
            "role": role_name,
            "missing_skills": [],
            "present_skills": [],
            "nice_to_have_gaps": [],
            "gap_count": 0,
            "coverage_pct": 0.0,
            "error": f"Role '{role_name}' not found.",
        }

    candidate_set = {s.lower() for s in (candidate_skills or [])}
    flat_req      = _flatten_required(role_data)

    missing = []
    present = []

    for skill, weight in flat_req.items():
        if skill in candidate_set:
            present.append(skill)
        else:
            label = "Critical" if weight >= 3 else "Important" if weight == 2 else "Recommended"
            missing.append({"skill": skill, "weight": weight, "label": label})

    # Sort: Critical first, then Important, then Recommended
    missing.sort(key=lambda x: x["weight"], reverse=True)

    nice_to_have = [s.lower() for s in role_data.get("nice_to_have", [])]
    nth_gaps     = [s for s in nice_to_have if s not in candidate_set]

    coverage = round(len(present) / max(len(flat_req), 1) * 100, 2)

    return {
        "role":              role_name,
        "missing_skills":    missing,
        "present_skills":    sorted(present),
        "nice_to_have_gaps": nth_gaps,
        "gap_count":         len(missing),
        "coverage_pct":      coverage,
    }


# --------------------------------------------------------------------------- #
#  Public API – full role analysis pipeline                                   #
# --------------------------------------------------------------------------- #

def analyse_role_fit(
    candidate_skills: list,
    authenticity:     dict,
    leetcode_data:    Optional[dict] = None,
    cgpa:             Optional[float] = None,
    target_role:      Optional[str]  = None,
    top_n:            int            = 5,
) -> dict:
    """
    Convenience wrapper that runs the full role analysis:
      - Recommend top roles
      - Use best-matched (or target) role for gap + readiness analysis

    Returns
    -------
    dict:
        recommended_roles  (list)
        primary_role       (str)
        readiness          (dict)
        skill_gaps         (dict)
    """
    recommendations = recommend_roles(candidate_skills, cgpa=cgpa, top_n=top_n)

    # Determine primary role
    if target_role and target_role in _ROLES:
        primary_role = target_role
    elif target_role:
        # Try case-insensitive
        matched = next((r for r in _ROLES if r.lower() == target_role.lower()), None)
        primary_role = matched or (recommendations[0]["role"] if recommendations else "")
    else:
        primary_role = recommendations[0]["role"] if recommendations else ""

    readiness  = compute_readiness_full(
        role_name        = primary_role,
        candidate_skills = candidate_skills,
        authenticity     = authenticity,
        leetcode_data    = leetcode_data,
        cgpa             = cgpa,
    )
    skill_gaps = identify_skill_gaps(primary_role, candidate_skills)

    return {
        "recommended_roles": recommendations,
        "primary_role":      primary_role,
        "readiness":         readiness,
        "skill_gaps":        skill_gaps,
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

    print("\n=== role_engine self-tests ===\n")

    # --- compute_readiness ---
    print("compute_readiness()")

    r = compute_readiness(0.0, 0.0, 0, 0, 0.0)
    _check("all zeros -> 0.0",  r == 0.0)

    r = compute_readiness(1.0, 1.0, 300, 10, 10.0)
    _check("perfect inputs -> 100.0",  r == 100.0)

    r = compute_readiness(0.5, 0.5, 150, 5, 5.0)
    _check("half inputs -> 50.0",  r == 50.0)

    # weight check: match (0.4) dominates
    r_high_match = compute_readiness(1.0, 0.0, 0, 0, 0.0)
    r_high_auth  = compute_readiness(0.0, 1.0, 0, 0, 0.0)
    _check("match weight 0.4 -> 40.0",  r_high_match == 40.0)
    _check("auth weight 0.2 -> 20.0",   r_high_auth  == 20.0)

    # leetcode_norm capped at 1 (600 -> norm 1.0, weight 0.2 -> 20pts)
    r = compute_readiness(0.0, 0.0, 600, 0, 0.0)
    _check("leetcode 600 capped -> 20.0",  r == 20.0)

    # repo_norm (weight 0.1)
    r = compute_readiness(0.0, 0.0, 0, 10, 0.0)
    _check("10 repos -> 10.0",  r == 10.0)

    r = compute_readiness(0.0, 0.0, 0, 20, 0.0)
    _check("20 repos capped -> 10.0",  r == 10.0)

    # cgpa_norm (weight 0.1), 10-point scale
    r = compute_readiness(0.0, 0.0, 0, 0, 10.0)
    _check("cgpa 10.0 -> 10.0",  r == 10.0)

    # clamp: negative inputs treated as 0
    r = compute_readiness(-0.5, -1.0, -10, -5, -2.0)
    _check("negative inputs clamped to 0.0",  r == 0.0)

    # return is float in [0, 100]
    r = compute_readiness(0.75, 0.6, 120, 8, 8.5)
    _check("result is float",        isinstance(r, float))
    _check("result in [0, 100]",     0.0 <= r <= 100.0)

    # --- recommend_role ---
    print("recommend_role()")

    role, ratio = recommend_role([])
    _check("empty skills -> ('', 0.0)",  role == "" and ratio == 0.0)

    role, ratio = recommend_role(["python", "react", "javascript",
                                   "html", "css", "typescript",
                                   "redux", "jest", "rest api", "git"])
    _check("frontend-heavy skills -> Frontend Developer",
           "frontend" in role.lower() or "frontend" in role.lower())
    _check("ratio in [0, 1]",             0.0 <= ratio <= 1.0)

    role, ratio = recommend_role(["python", "flask", "django",
                                   "postgresql", "redis", "rest api",
                                   "docker", "sql", "git"])
    _check("backend-heavy skills -> Backend Developer",
           "backend" in role.lower())
    _check("ratio > 0",  ratio > 0.0)

    role2, ratio2 = recommend_role(["python"])
    role3, ratio3 = recommend_role(["python", "java", "c++", "docker",
                                     "sql", "algorithms", "data structures"])
    _check("more skills -> higher or equal ratio", ratio3 >= ratio2)

    # --- get_skill_gaps ---
    print("\nget_skill_gaps()")

    gaps = get_skill_gaps([], "Frontend Developer")
    _check("no skills -> all required are gaps",  len(gaps) > 0)
    _check("gaps is a list",                      isinstance(gaps, list))
    _check("gaps are sorted",                     gaps == sorted(gaps))

    gaps = get_skill_gaps(
        ["html", "css", "javascript", "typescript",
         "react", "redux", "jest", "webpack", "vite",
         "figma", "rest api", "git", "responsive design"],
        "Frontend Developer",
    )
    _check("all required present -> gaps []",  gaps == [])

    gaps = get_skill_gaps(["python", "docker"], "Backend Developer")
    _check("docker present -> 'docker' not in gaps",  "docker" not in gaps)
    _check("python present -> 'python' not in gaps",  "python" not in gaps)
    _check("missing skills appear in gaps",           len(gaps) > 0)

    gaps = get_skill_gaps(["python"], "__nonexistent_role__")
    _check("unknown role -> []",  gaps == [])

    # case-insensitive role lookup
    gaps_exact = get_skill_gaps(["python"], "Backend Developer")
    gaps_ci    = get_skill_gaps(["python"], "backend developer")
    _check("case-insensitive role match",  gaps_exact == gaps_ci)

    # --- interaction: recommend_role then get_skill_gaps ---
    print("\nrecommend_role -> get_skill_gaps pipeline")

    candidate = ["python", "flask", "postgresql", "docker", "rest api"]
    best_role, score = recommend_role(candidate)
    gaps = get_skill_gaps(candidate, best_role)
    _check("pipeline: best role is non-empty",          bool(best_role))
    _check("pipeline: score in [0, 1]",                 0.0 <= score <= 1.0)
    _check("pipeline: gaps is a list",                  isinstance(gaps, list))
    _check("pipeline: no gap skill is in candidate",
           all(g not in {s.lower() for s in candidate} for g in gaps))

    print()
    passed = sum(_results)
    total  = len(_results)
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        raise SystemExit(1)
