"""
github_parser.py
----------------
Fetches public GitHub repository data for a username and derives a verified
skill set from:
  - Repository primary languages
  - Repository topics
  - Repository name keywords  (docker, api, ml, web, db, ...)
  - Repository description keyword scan

Primary function
----------------
get_github_profile(username: str) -> {"verified_skills": list[str], "repo_count": int}

A backward-compatible get_github_data() wrapper is kept for app.py.
All results are normalised to lowercase.  All errors are handled gracefully.
"""

import os
import re
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_GH_API = "https://api.github.com"

# ── GitHub language name → normalised skill ──────────────────────────────────
_LANGUAGE_MAP: dict = {
    "Python":           "python",
    "JavaScript":       "javascript",
    "TypeScript":       "typescript",
    "Java":             "java",
    "C":                "c",
    "C++":              "c++",
    "C#":               "c#",
    "Go":               "go",
    "Rust":             "rust",
    "Kotlin":           "kotlin",
    "Swift":            "swift",
    "Ruby":             "ruby",
    "PHP":              "php",
    "Scala":            "scala",
    "R":                "r",
    "Dart":             "dart",
    "Elixir":           "elixir",
    "Haskell":          "haskell",
    "Perl":             "perl",
    "Shell":            "bash",
    "Dockerfile":       "docker",
    "HCL":              "terraform",
    "MATLAB":           "matlab",
    "HTML":             "html",
    "CSS":              "css",
    "SCSS":             "css",
    "Less":             "css",
    "Jupyter Notebook": "jupyter",
    "Lua":              "lua",
    "Makefile":         "make",
}

# ── Keywords (topics / descriptions) → normalised skill ──────────────────────
_KEYWORD_SKILL_MAP: dict = {
    # web frameworks
    "react":            "react",
    "reactjs":          "react",
    "angular":          "angular",
    "vue":              "vue",
    "vuejs":            "vue",
    "nextjs":           "nextjs",
    "next.js":          "nextjs",
    "nuxtjs":           "nuxtjs",
    "svelte":           "svelte",
    "django":           "django",
    "flask":            "flask",
    "fastapi":          "fastapi",
    "spring":           "spring",
    "springboot":       "springboot",
    "spring-boot":      "springboot",
    "express":          "express",
    "expressjs":        "express",
    "nestjs":           "nestjs",
    "laravel":          "laravel",
    "rails":            "rails",
    # ML / AI
    "pytorch":          "pytorch",
    "tensorflow":       "tensorflow",
    "keras":            "keras",
    "sklearn":          "scikit-learn",
    "scikit":           "scikit-learn",
    "scikit-learn":     "scikit-learn",
    "pandas":           "pandas",
    "numpy":            "numpy",
    "opencv":           "opencv",
    "nlp":              "natural language processing",
    "transformers":     "transformers",
    "huggingface":      "huggingface",
    "langchain":        "langchain",
    "llm":              "llm",
    "rag":              "rag",
    "mlops":            "mlops",
    "ml":               "machine learning",
    "machine-learning": "machine learning",
    "deep-learning":    "deep learning",
    "computer-vision":  "computer vision",
    "data-science":     "data science",
    # databases
    "mysql":            "mysql",
    "postgresql":       "postgresql",
    "postgres":         "postgresql",
    "mongodb":          "mongodb",
    "redis":            "redis",
    "elasticsearch":    "elasticsearch",
    "firebase":         "firebase",
    "sqlite":           "sqlite",
    "cassandra":        "cassandra",
    "dynamodb":         "dynamodb",
    "supabase":         "supabase",
    "prisma":           "prisma",
    # cloud / devops
    "aws":              "aws",
    "azure":            "azure",
    "gcp":              "gcp",
    "docker":           "docker",
    "kubernetes":       "kubernetes",
    "k8s":              "kubernetes",
    "terraform":        "terraform",
    "ansible":          "ansible",
    "jenkins":          "jenkins",
    "github-actions":   "github actions",
    "ci-cd":            "ci/cd",
    "cicd":             "ci/cd",
    "nginx":            "nginx",
    # api / web patterns
    "api":              "rest api",
    "rest":             "rest api",
    "restful":          "rest api",
    "graphql":          "graphql",
    "websocket":        "websockets",
    "websockets":       "websockets",
    "grpc":             "grpc",
    # frontend tooling
    "bootstrap":        "bootstrap",
    "tailwind":         "tailwind",
    "redux":            "redux",
    "webpack":          "webpack",
    "vite":             "vite",
    # testing
    "testing":          "unit testing",
    "jest":             "jest",
    "pytest":           "pytest",
    "tdd":              "tdd",
    # messaging / streaming
    "kafka":            "kafka",
    "rabbitmq":         "rabbitmq",
    "celery":           "celery",
    # data / analytics
    "spark":            "spark",
    "airflow":          "airflow",
    "dbt":              "dbt",
    "snowflake":        "snowflake",
    # security / auth
    "jwt":              "jwt",
    "oauth":            "oauth",
    # misc
    "microservices":    "microservices",
    "blockchain":       "blockchain",
    "web3":             "web3",
    "game":             "game development",
    "gamedev":          "game development",
}

# ── Category signals in repo *name* tokens ────────────────────────────────────
# Repo names are split on [-_\s] and each token is checked here.
_NAME_CATEGORY_MAP: dict = {
    # docker / containerisation
    "docker":      "docker",
    "container":   "docker",
    "compose":     "docker",
    # APIs / backend
    "api":         "rest api",
    "backend":     "rest api",
    "server":      "rest api",
    # ML / AI
    "ml":          "machine learning",
    "ai":          "machine learning",
    "model":       "machine learning",
    "predict":     "machine learning",
    "classify":    "machine learning",
    "nlp":         "natural language processing",
    "bot":         "natural language processing",
    "chatbot":     "natural language processing",
    "vision":      "computer vision",
    "detection":   "computer vision",
    "segmentation":"computer vision",
    # web / frontend
    "web":         "html",
    "frontend":    "html",
    "portfolio":   "html",
    "website":     "html",
    "dashboard":   "html",
    # database
    "db":          "sql",
    "database":    "sql",
    "crud":        "sql",
    "store":       "sql",
    # CI / devops
    "pipeline":    "ci/cd",
    "deploy":      "ci/cd",
    "infra":       "ci/cd",
    "k8s":         "kubernetes",
    "helm":        "kubernetes",
    # data science
    "data":        "data science",
    "analysis":    "data science",
    "analytics":   "data science",
    "notebook":    "jupyter",
    "eda":         "data science",
}


# --------------------------------------------------------------------------- #
#  Internal helpers                                                            #
# --------------------------------------------------------------------------- #

def _safe_get(url: str, headers: dict, timeout: int = 8):
    """
    GET *url* and return parsed JSON, or ``None`` on any error.

    Handles: network timeout, rate-limit (403), not-found (404), other HTTP
    errors, and unexpected exceptions without raising.
    """
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 403:
            logger.warning("GitHub API rate-limited (403): %s", url)
        elif resp.status_code == 404:
            logger.warning("GitHub API not found (404): %s", url)
        else:
            logger.warning("GitHub API %s -> HTTP %s", url, resp.status_code)
        return None
    except requests.Timeout:
        logger.warning("GitHub request timed out: %s", url)
        return None
    except requests.RequestException as exc:
        logger.warning("GitHub request failed: %s", exc)
        return None


def _skills_from_repo(repo: dict) -> set:
    """
    Extract normalised skill strings from a single repository dict.

    Sources checked in order:
    1. ``language``   – primary GitHub language field
    2. ``topics``     – curated topic tags
    3. ``name``       – repo name split into tokens
    4. ``description``– free-form text keyword scan
    """
    found: set = set()

    # 1. Primary language
    language = (repo.get("language") or "").strip()
    if language in _LANGUAGE_MAP:
        found.add(_LANGUAGE_MAP[language])

    # 2. Topics
    for topic in (repo.get("topics") or []):
        token = topic.lower().replace(" ", "-")
        if token in _KEYWORD_SKILL_MAP:
            found.add(_KEYWORD_SKILL_MAP[token])

    # 3. Repo name tokens  (e.g. "my-ml-api-project" -> ["my","ml","api","project"])
    name_tokens = re.split(r"[-_\s]+", (repo.get("name") or "").lower())
    for token in name_tokens:
        if token in _NAME_CATEGORY_MAP:
            found.add(_NAME_CATEGORY_MAP[token])
        if token in _KEYWORD_SKILL_MAP:
            found.add(_KEYWORD_SKILL_MAP[token])

    # 4. Description free-text
    desc = (repo.get("description") or "").lower()
    for kw, skill in _KEYWORD_SKILL_MAP.items():
        if re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", desc):
            found.add(skill)

    return found


# --------------------------------------------------------------------------- #
#  Primary public function                                                     #
# --------------------------------------------------------------------------- #

def get_github_profile(username: str) -> dict:
    """
    Fetch public repos for *username* and derive a verified skill set.

    API used
    --------
    ``GET https://api.github.com/users/{username}/repos``

    Skill detection (per repo)
    --------------------------
    * Primary language  -> language skill  (e.g. "Python" -> "python")
    * Topics list       -> framework / tool skills
    * Repo name tokens  -> category signals (docker, api, ml, web, db, ...)
    * Description text  -> keyword scan

    Parameters
    ----------
    username : str
        GitHub username.  Leading/trailing whitespace is stripped.

    Returns
    -------
    dict
        ``verified_skills`` (list[str]) - sorted, deduplicated, lowercase
        ``repo_count``      (int)       - number of public repos returned

    On any error (user not found, API rate-limit, network failure, empty
    username, empty repos) the function returns safe defaults and never raises.
    """
    _DEFAULT = {"verified_skills": [], "repo_count": 0}

    username = (username or "").strip()
    if not username:
        logger.warning("get_github_profile called with empty username")
        return _DEFAULT

    token   = os.getenv("GITHUB_TOKEN", "")
    headers: dict = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # ── 1. Verify user exists ─────────────────────────────────────────────────
    if not _safe_get(f"{_GH_API}/users/{username}", headers):
        logger.info("GitHub user '%s' not found or API unavailable.", username)
        return _DEFAULT

    # ── 2. Fetch repos ────────────────────────────────────────────────────────
    repos = _safe_get(
        f"{_GH_API}/users/{username}/repos"
        "?per_page=100&sort=updated&type=owner",
        headers,
    )

    if not repos:                         # rate-limited or network error
        logger.info("Could not fetch repos for '%s'.", username)
        return _DEFAULT

    if not isinstance(repos, list):       # unexpected payload shape
        logger.warning("Unexpected repos payload for '%s': %s", username, type(repos))
        return _DEFAULT

    if len(repos) == 0:                   # user has no public repos
        return _DEFAULT

    # ── 3. Aggregate skills ───────────────────────────────────────────────────
    skill_set: set = set()
    for repo in repos:
        if isinstance(repo, dict):
            skill_set.update(_skills_from_repo(repo))

    return {
        "verified_skills": sorted(skill_set),
        "repo_count":      len(repos),
    }


# --------------------------------------------------------------------------- #
#  Backward-compatible wrapper  (used by app.py / skill_engine.analyse_skills) #
# --------------------------------------------------------------------------- #

def get_github_data(
    username: str,
    token: Optional[str] = None,
    max_repos: int = 100,
    scan_readmes: bool = False,
) -> dict:
    """
    Thin wrapper around :func:`get_github_profile` that returns the richer
    dict shape expected by ``app.py`` and ``skill_engine.analyse_skills()``.

    Returns
    -------
    dict
        ``verified_skills``, ``repo_count``, ``success``, ``error``
        (plus stub keys kept for forward-compatibility:
        ``languages``, ``top_languages``, ``total_stars``, ``topics``, ``repos``)
    """
    if token:
        os.environ.setdefault("GITHUB_TOKEN", token)

    profile = get_github_profile(username)
    success = bool(profile["verified_skills"] or profile["repo_count"])

    return {
        "verified_skills": profile["verified_skills"],
        "repo_count":      profile["repo_count"],
        "languages":       {},
        "top_languages":   [],
        "total_stars":     0,
        "topics":          [],
        "repos":           [],
        "success":         success,
        "error":           "" if success else f"No data returned for '{username}'.",
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

    print("\n=== github_parser self-tests ===\n")

    # --- _skills_from_repo (no network required) ---
    print("_skills_from_repo()")

    r = _skills_from_repo({
        "name": "my-docker-api",
        "language": "Python",
        "topics": ["flask", "docker"],
        "description": "A REST API with Docker deployment",
    })
    _check("python from language",  "python"   in r)
    _check("flask from topic",      "flask"    in r)
    _check("docker from topic",     "docker"   in r)
    _check("rest api from desc",    "rest api" in r)
    _check("docker from name token","docker"   in r)

    r = _skills_from_repo({
        "name": "ml-classifier",
        "language": "Jupyter Notebook",
        "topics": ["scikit-learn", "data-science"],
        "description": "Image classification using pytorch",
    })
    _check("jupyter from language",       "jupyter"          in r)
    _check("scikit-learn from topic",     "scikit-learn"     in r)
    _check("data science from topic",     "data science"     in r)
    _check("pytorch from description",    "pytorch"          in r)
    _check("machine learning from name",  "machine learning" in r)

    r = _skills_from_repo({
        "name": "k8s-infra-pipeline",
        "language": None,
        "topics": ["kubernetes", "ci-cd"],
        "description": "",
    })
    _check("kubernetes from topic",       "kubernetes" in r)
    _check("ci/cd from topic",            "ci/cd"      in r)
    _check("ci/cd from name token",       "ci/cd"      in r)

    r = _skills_from_repo({
        "name": "web-dashboard",
        "language": "JavaScript",
        "topics": [],
        "description": "PostgreSQL database backend with REST API",
    })
    _check("javascript from language",    "javascript" in r)
    _check("postgresql from desc",        "postgresql" in r)
    _check("rest api from desc",          "rest api"   in r)
    _check("html from name (web token)",  "html"       in r)

    r = _skills_from_repo({"name": "", "language": None, "topics": [], "description": ""})
    _check("all-empty repo -> empty set", len(r) == 0)

    # --- safe defaults (no network for nonexistent user) ---
    print("\nget_github_profile() safe defaults")

    d = get_github_profile("")
    _check("empty username -> repo_count 0",      d["repo_count"]      == 0)
    _check("empty username -> verified_skills []", d["verified_skills"] == [])

    d = get_github_profile("__nonexistent_user_xyzabc12345__")
    _check("unknown user -> repo_count 0",         d["repo_count"]      == 0)
    _check("unknown user -> verified_skills []",   d["verified_skills"] == [])

    # --- wrapper shape ---
    print("\nget_github_data() wrapper shape")

    gd = get_github_data("__nonexistent_user_xyzabc12345__")
    for key in ("success", "error", "verified_skills", "repo_count",
                "languages", "top_languages", "topics", "repos"):
        _check(f"key '{key}' present",  key in gd)
    _check("failed user -> success False",    gd["success"] is False)
    _check("failed user -> error non-empty",  bool(gd["error"]))

    print()
    passed = sum(_results)
    total  = len(_results)
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        raise SystemExit(1)
