"""
leetcode_parser.py
------------------
Fetches LeetCode user statistics via the public GraphQL API.

Returns problem-solving activity broken down by difficulty, plus a list of
inferred skills (data structures & algorithms) derived from the topics of
solved problems when accessible.

Gracefully handles missing users, private profiles, and API errors.
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)

_LC_GRAPHQL = "https://leetcode.com/graphql"

# Maps LeetCode problem topic tags → skill names used in data/skills.json
_TAG_SKILL_MAP = {
    "array":              "arrays",
    "string":             "strings",
    "hash-table":         "hash table",
    "dynamic-programming":"dynamic programming",
    "math":               "math",
    "greedy":             "greedy",
    "depth-first-search": "depth-first search",
    "breadth-first-search":"breadth-first search",
    "sorting":            "sorting",
    "binary-search":      "binary search",
    "two-pointers":       "two pointers",
    "tree":               "binary tree",
    "graph":              "graph",
    "backtracking":       "backtracking",
    "linked-list":        "linked list",
    "heap-priority-queue":"heap",
    "trie":               "trie",
    "stack":              "stack",
    "queue":              "queue",
    "union-find":         "union find",
    "sliding-window":     "sliding window",
    "bit-manipulation":   "bit manipulation",
    "recursion":          "recursion",
    "divide-and-conquer": "divide and conquer",
    "matrix":             "matrix",
    "segment-tree":       "segment tree",
    "topological-sort":   "topological sort",
}

# DSA proficiency thresholds
_EASY_PROFICIENT   = 50
_MEDIUM_PROFICIENT = 30
_HARD_PROFICIENT   = 10


# --------------------------------------------------------------------------- #
#  GraphQL query helpers                                                       #
# --------------------------------------------------------------------------- #

_USER_STATS_QUERY = """
query getUserProfile($username: String!) {
  matchedUser(username: $username) {
    username
    submitStats: submitStatsGlobal {
      acSubmissionNum {
        difficulty
        count
        submissions
      }
    }
    tagProblemCounts {
      advanced {
        tagName
        tagSlug
        problemsSolved
      }
      intermediate {
        tagName
        tagSlug
        problemsSolved
      }
      fundamental {
        tagName
        tagSlug
        problemsSolved
      }
    }
  }
}
"""

_HEADERS = {
    "Content-Type":  "application/json",
    "Referer":       "https://leetcode.com",
    "User-Agent":    "Mozilla/5.0 (compatible; PlacementBot/1.0)",
}


def _gql_request(query: str, variables: dict, timeout: int = 10) -> Optional[dict]:
    """Execute a GraphQL query against LeetCode."""
    try:
        response = requests.post(
            _LC_GRAPHQL,
            json={"query": query, "variables": variables},
            headers=_HEADERS,
            timeout=timeout,
        )
        if response.status_code == 200:
            return response.json()
        logger.warning("LeetCode GraphQL returned %s", response.status_code)
        return None
    except requests.RequestException as exc:
        logger.warning("LeetCode request failed: %s", exc)
        return None


# --------------------------------------------------------------------------- #
#  Skill inference from solved counts                                          #
# --------------------------------------------------------------------------- #

def _infer_skills_from_stats(easy: int, medium: int, hard: int) -> list:
    """
    Infer likely DSA skills based purely on solved counts (used when
    tag-level data is unavailable / private).
    """
    skills = []
    total = easy + medium + hard
    if total >= 25:
        skills += ["arrays", "strings", "hash table"]
    if total >= 50:
        skills += ["sorting", "binary search", "math"]
    if medium >= 20:
        skills += ["dynamic programming", "sliding window", "two pointers"]
    if medium >= _MEDIUM_PROFICIENT:
        skills += ["binary tree", "graph", "recursion", "backtracking"]
    if hard >= _HARD_PROFICIENT:
        skills += ["heap", "trie", "segment tree", "bit manipulation",
                   "topological sort", "union find"]
    return list(set(skills))


def _infer_skills_from_tags(tag_groups: list) -> list:
    """Extract skills from LeetCode's tagProblemCounts response."""
    skills = set()
    for group in tag_groups:
        if not isinstance(group, list):
            continue
        for item in group:
            slug   = (item.get("tagSlug") or "").lower()
            solved = item.get("problemsSolved", 0)
            if solved >= 1 and slug in _TAG_SKILL_MAP:
                skills.add(_TAG_SKILL_MAP[slug])
    return list(skills)


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def get_leetcode_data(username: str) -> dict:
    """
    Fetch LeetCode statistics for a user.

    Parameters
    ----------
    username : str – LeetCode username

    Returns
    -------
    dict:
        solved_total    (int)
        solved_easy     (int)
        solved_medium   (int)
        solved_hard     (int)
        dsa_skills      (list[str])  – inferred DSA skill names
        proficiency     (str)        – "beginner" / "intermediate" / "advanced"
        activity_score  (float 0-1)  – normalised activity level
        success         (bool)
        error           (str)
    """
    result = {
        "solved_total":   0,
        "solved_easy":    0,
        "solved_medium":  0,
        "solved_hard":    0,
        "dsa_skills":     [],
        "proficiency":    "none",
        "activity_score": 0.0,
        "success":        False,
        "error":          "",
    }

    username = (username or "").strip()
    if not username:
        result["error"] = "LeetCode username is empty."
        return result

    # ── 1. Fetch data ─────────────────────────────────────────────────────────
    data = _gql_request(_USER_STATS_QUERY, {"username": username})

    if data is None:
        result["error"] = "LeetCode API unavailable."
        return result

    if "errors" in data:
        errs = data["errors"]
        msg  = errs[0].get("message", "Unknown error") if errs else "Unknown error"
        result["error"] = f"LeetCode API error: {msg}"
        return result

    matched = (data.get("data") or {}).get("matchedUser")
    if not matched:
        result["error"] = f"LeetCode user '{username}' not found or profile is private."
        return result

    # ── 2. Parse submission stats ─────────────────────────────────────────────
    solved_by_diff = {"Easy": 0, "Medium": 0, "Hard": 0, "All": 0}
    submit_stats = (matched.get("submitStats") or {}).get("acSubmissionNum", [])
    for entry in submit_stats:
        diff  = entry.get("difficulty", "")
        count = entry.get("count", 0)
        if diff in solved_by_diff:
            solved_by_diff[diff] = count

    easy   = solved_by_diff["Easy"]
    medium = solved_by_diff["Medium"]
    hard   = solved_by_diff["Hard"]
    total  = easy + medium + hard         # use arithmetic sum (more reliable)

    # ── 3. Extract DSA skills ─────────────────────────────────────────────────
    tag_data = matched.get("tagProblemCounts") or {}
    tag_groups = [
        tag_data.get("fundamental") or [],
        tag_data.get("intermediate") or [],
        tag_data.get("advanced") or [],
    ]
    tag_skills  = _infer_skills_from_tags(tag_groups)
    stat_skills = _infer_skills_from_stats(easy, medium, hard)

    dsa_skills = list(set(tag_skills + stat_skills))

    # ── 4. Proficiency level ──────────────────────────────────────────────────
    if hard >= _HARD_PROFICIENT and medium >= _MEDIUM_PROFICIENT:
        proficiency = "advanced"
    elif medium >= 15 or (easy + medium) >= 60:
        proficiency = "intermediate"
    elif total >= 10:
        proficiency = "beginner"
    else:
        proficiency = "none"

    # ── 5. Normalised activity score (0 – 1) ──────────────────────────────────
    # Weights: Easy×1, Medium×2, Hard×3, capped at 300 weighted points
    weighted = min(easy * 1 + medium * 2 + hard * 3, 300)
    activity_score = round(weighted / 300, 4)

    result.update({
        "solved_total":   total,
        "solved_easy":    easy,
        "solved_medium":  medium,
        "solved_hard":    hard,
        "dsa_skills":     sorted(dsa_skills),
        "proficiency":    proficiency,
        "activity_score": activity_score,
        "success":        True,
    })
    return result
