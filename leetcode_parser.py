"""
leetcode_parser.py
------------------
Fetches LeetCode user statistics via the public GraphQL API.

Primary function
----------------
get_leetcode_stats(username: str) -> {"total": int, "easy": int, "medium": int, "hard": int}

A backward-compatible get_leetcode_data() wrapper is kept for app.py /
skill_engine.analyse_skills(), adding DSA skill inference and proficiency
scoring on top of the base stats.

All errors (invalid username, null data, network failure) are handled
gracefully - functions never raise and always return safe zero defaults.
"""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_LC_GRAPHQL  = "https://leetcode.com/graphql"
_LC_HOMEPAGE = "https://leetcode.com/"

_BASE_HEADERS = {
    "Content-Type": "application/json",
    "Origin":       "https://leetcode.com",
    "Referer":      "https://leetcode.com",
    "User-Agent":   (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept":        "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# Module-level session — reused across calls so the CSRF token is fetched once.
_session: requests.Session = None
_session_failures: int = 0
_MAX_SESSION_FAILURES = 3


def _get_session() -> requests.Session:
    """Return a live requests.Session with a valid LeetCode CSRF cookie."""
    global _session, _session_failures
    if _session is not None and _session_failures < _MAX_SESSION_FAILURES:
        return _session
    sess = requests.Session()
    sess.headers.update(_BASE_HEADERS)
    try:
        sess.get(_LC_HOMEPAGE, timeout=10)
        csrf = sess.cookies.get("csrftoken", "")
        if csrf:
            sess.headers.update({"x-csrftoken": csrf})
            logger.debug("LeetCode CSRF token acquired (len=%d)", len(csrf))
        else:
            logger.warning("LeetCode homepage did not return a csrftoken cookie")
    except Exception as exc:
        logger.warning("Failed to fetch LeetCode homepage for CSRF: %s", exc)
    _session = sess
    _session_failures = 0
    return _session

# GraphQL query  matchedUser -> submitStatsGlobal -> acSubmissionNum
_STATS_QUERY = """
query getUserStats($username: String!) {
  matchedUser(username: $username) {
    submitStats: submitStatsGlobal {
      acSubmissionNum {
        difficulty
        count
      }
    }
  }
}
"""

_TAG_SKILL_MAP: dict = {
    "array":               "arrays",
    "string":              "strings",
    "hash-table":          "hash table",
    "dynamic-programming": "dynamic programming",
    "math":                "math",
    "greedy":              "greedy",
    "depth-first-search":  "depth-first search",
    "breadth-first-search":"breadth-first search",
    "sorting":             "sorting",
    "binary-search":       "binary search",
    "two-pointers":        "two pointers",
    "tree":                "binary tree",
    "graph":               "graph",
    "backtracking":        "backtracking",
    "linked-list":         "linked list",
    "heap-priority-queue": "heap",
    "trie":                "trie",
    "stack":               "stack",
    "queue":               "queue",
    "union-find":          "union find",
    "sliding-window":      "sliding window",
    "bit-manipulation":    "bit manipulation",
    "recursion":           "recursion",
    "divide-and-conquer":  "divide and conquer",
    "matrix":              "matrix",
    "segment-tree":        "segment tree",
    "topological-sort":    "topological sort",
}

_EASY_PROFICIENT   = 50
_MEDIUM_PROFICIENT = 30
_HARD_PROFICIENT   = 10

# --------------------------------------------------------------------------- #
#  Internal helpers                                                            #
# --------------------------------------------------------------------------- #

def _gql_post(query: str, variables: dict, timeout: int = 12) -> Optional[dict]:
    """POST a GraphQL query using a CSRF-authenticated session.
    
    Automatically retries once with a fresh session if a 403/499 is received.
    Returns parsed JSON or None on any error.
    """
    global _session_failures
    for attempt in range(2):
        sess = _get_session()
        try:
            resp = sess.post(
                _LC_GRAPHQL,
                json={"query": query, "variables": variables},
                timeout=timeout,
            )
            if resp.status_code == 200:
                return resp.json()
            # 403/499 usually means CSRF expired — force session refresh on retry
            logger.warning(
                "LeetCode GraphQL HTTP %s (attempt %d/2)",
                resp.status_code, attempt + 1,
            )
            _session_failures += 1
            _session = None   # force re-creation on next attempt
        except requests.Timeout:
            logger.warning("LeetCode request timed out (variables=%s)", variables)
            return None
        except requests.RequestException as exc:
            logger.warning("LeetCode request failed: %s", exc)
            return None
    return None


def _parse_ac_counts(ac_list: list) -> tuple:
    """Parse acSubmissionNum list into (easy, medium, hard). Returns (0,0,0) on bad input."""
    easy = medium = hard = 0
    for entry in (ac_list or []):
        if not isinstance(entry, dict):
            continue
        diff  = (entry.get("difficulty") or "").strip()
        count = entry.get("count", 0)
        if not isinstance(count, int):
            try:
                count = int(count)
            except (TypeError, ValueError):
                count = 0
        if diff == "Easy":
            easy = count
        elif diff == "Medium":
            medium = count
        elif diff == "Hard":
            hard = count
    return easy, medium, hard


def _infer_skills(easy: int, medium: int, hard: int) -> list:
    """Infer likely DSA skills from solved-problem counts."""
    skills: set = set()
    total = easy + medium + hard
    if total >= 25:
        skills.update(["arrays", "strings", "hash table"])
    if total >= 50:
        skills.update(["sorting", "binary search", "math"])
    if medium >= 20:
        skills.update(["dynamic programming", "sliding window", "two pointers"])
    if medium >= _MEDIUM_PROFICIENT:
        skills.update(["binary tree", "graph", "recursion", "backtracking"])
    if hard >= _HARD_PROFICIENT:
        skills.update([
            "heap", "trie", "segment tree", "bit manipulation",
            "topological sort", "union find",
        ])
    return sorted(skills)


# --------------------------------------------------------------------------- #
#  Primary public function                                                     #
# --------------------------------------------------------------------------- #

def get_leetcode_stats(username: str) -> dict:
    """
    Fetch solved-problem counts for a LeetCode user.

    Uses POST https://leetcode.com/graphql with the query:
        matchedUser -> submitStatsGlobal -> acSubmissionNum

    Parameters
    ----------
    username : str
        LeetCode username.  Leading/trailing whitespace is stripped.

    Returns
    -------
    dict
        "total"  (int)
        "easy"   (int)
        "medium" (int)
        "hard"   (int)

    Returns {"total": 0, "easy": 0, "medium": 0, "hard": 0} on any error
    (invalid username, null matchedUser, network failure, malformed response).
    """
    _ZERO = {"total": 0, "easy": 0, "medium": 0, "hard": 0}

    username = (username or "").strip()
    if not username:
        logger.warning("get_leetcode_stats called with empty username")
        return _ZERO

    raw = _gql_post(_STATS_QUERY, {"username": username})

    if raw is None:
        logger.info("LeetCode API unavailable for '%s'.", username)
        return _ZERO

    if "errors" in raw:
        errs = raw["errors"]
        msg  = errs[0].get("message", "unknown") if errs else "unknown"
        logger.info("LeetCode GraphQL error for '%s': %s", username, msg)
        return _ZERO

    matched = (raw.get("data") or {}).get("matchedUser")
    if not matched:
        logger.info("LeetCode user '%s' not found or profile is private.", username)
        return _ZERO

    ac_list            = (matched.get("submitStats") or {}).get("acSubmissionNum") or []
    easy, medium, hard = _parse_ac_counts(ac_list)

    return {
        "total":  easy + medium + hard,
        "easy":   easy,
        "medium": medium,
        "hard":   hard,
    }


# --------------------------------------------------------------------------- #
#  Backward-compatible wrapper  (used by app.py / skill_engine)               #
# --------------------------------------------------------------------------- #

def get_leetcode_data(username: str) -> dict:
    """
    Wrapper around get_leetcode_stats() returning the richer dict shape
    expected by app.py and skill_engine.analyse_skills().

    Returns
    -------
    dict
        solved_total, solved_easy, solved_medium, solved_hard (int)
        dsa_skills      (list[str])
        proficiency     (str)  "none" / "beginner" / "intermediate" / "advanced"
        activity_score  (float 0-1)
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

    stats = get_leetcode_stats(username)

    if stats["total"] == 0 and stats["easy"] == 0 and stats["medium"] == 0:
        result["error"] = (
            f"LeetCode user '{username}' not found, profile is private, "
            "or API is unavailable."
        )
        return result

    easy   = stats["easy"]
    medium = stats["medium"]
    hard   = stats["hard"]
    total  = stats["total"]

    if hard >= _HARD_PROFICIENT and medium >= _MEDIUM_PROFICIENT:
        proficiency = "advanced"
    elif medium >= 15 or (easy + medium) >= 60:
        proficiency = "intermediate"
    elif total >= 10:
        proficiency = "beginner"
    else:
        proficiency = "none"

    weighted       = min(easy * 1 + medium * 2 + hard * 3, 300)
    activity_score = round(weighted / 300, 4)

    result.update({
        "solved_total":   total,
        "solved_easy":    easy,
        "solved_medium":  medium,
        "solved_hard":    hard,
        "dsa_skills":     _infer_skills(easy, medium, hard),
        "proficiency":    proficiency,
        "activity_score": activity_score,
        "success":        True,
    })
    return result


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

    print("\n=== leetcode_parser self-tests ===\n")

    print("_parse_ac_counts()")
    e, m, h = _parse_ac_counts([
        {"difficulty": "Easy",   "count": 50},
        {"difficulty": "Medium", "count": 30},
        {"difficulty": "Hard",   "count": 10},
    ])
    _check("easy=50",   e == 50)
    _check("medium=30", m == 30)
    _check("hard=10",   h == 10)

    e, m, h = _parse_ac_counts([])
    _check("empty list -> 0,0,0", (e, m, h) == (0, 0, 0))

    e, m, h = _parse_ac_counts(None)
    _check("None -> 0,0,0", (e, m, h) == (0, 0, 0))

    e, m, h = _parse_ac_counts([{"difficulty": "All", "count": 100}])
    _check("unknown difficulty ignored", (e, m, h) == (0, 0, 0))

    print("\n_infer_skills()")
    s = _infer_skills(0, 0, 0)
    _check("no solves -> no skills", s == [])

    s = _infer_skills(30, 0, 0)
    _check("30 easy -> arrays",  "arrays"  in s)
    _check("30 easy -> strings", "strings" in s)

    s = _infer_skills(60, 40, 15)
    _check("advanced -> dynamic programming", "dynamic programming" in s)
    _check("advanced -> heap",               "heap"                in s)
    _check("advanced -> trie",               "trie"                in s)
    _check("result is sorted",               s == sorted(s))

    print("\nget_leetcode_stats() safe defaults")
    d = get_leetcode_stats("")
    _check("empty username -> total 0",  d["total"]  == 0)
    _check("empty username -> easy 0",   d["easy"]   == 0)
    _check("empty username -> medium 0", d["medium"] == 0)
    _check("empty username -> hard 0",   d["hard"]   == 0)

    d = get_leetcode_stats("__nonexistent_user_xyzabc12345__")
    _check("unknown user -> total 0",  d["total"]  == 0)
    _check("unknown user -> easy 0",   d["easy"]   == 0)
    _check("unknown user -> medium 0", d["medium"] == 0)
    _check("unknown user -> hard 0",   d["hard"]   == 0)

    print("\nget_leetcode_data() wrapper shape")
    ld = get_leetcode_data("")
    for key in ("solved_total", "solved_easy", "solved_medium", "solved_hard",
                "dsa_skills", "proficiency", "activity_score", "success", "error"):
        _check(f"key '{key}' present", key in ld)
    _check("empty username -> success False",   ld["success"] is False)
    _check("empty username -> error non-empty", bool(ld["error"]))

    ld = get_leetcode_data("__nonexistent_user_xyzabc12345__")
    _check("unknown user -> success False",   ld["success"] is False)
    _check("unknown user -> solved_total 0",  ld["solved_total"] == 0)
    _check("proficiency default none",        ld["proficiency"] == "none")

    print()
    passed = sum(_results)
    total  = len(_results)
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        raise SystemExit(1)
