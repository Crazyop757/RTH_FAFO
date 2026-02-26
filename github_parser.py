"""
github_parser.py
----------------
Fetches public GitHub activity for a username and derives a set of verified
skills from:
  - Repository primary languages
  - Repository topics / tags
  - README keyword scanning
  - Detected framework / tool mentions in repo descriptions

Returns a structured dict with verified skills, language stats, and
repository metadata.  All external failures are handled gracefully.
"""

import re
import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)

# GitHub REST API v3 base
_GH_API = "https://api.github.com"

# Maps GitHub language names → normalised skill names used in skills.json
_LANGUAGE_MAP = {
    "Python":       "python",
    "JavaScript":   "javascript",
    "TypeScript":   "typescript",
    "Java":         "java",
    "C":            "c",
    "C++":          "c++",
    "C#":           "c#",
    "Go":           "go",
    "Rust":         "rust",
    "Kotlin":       "kotlin",
    "Swift":        "swift",
    "Ruby":         "ruby",
    "PHP":          "php",
    "Scala":        "scala",
    "R":            "r",
    "Dart":         "dart",
    "Elixir":       "elixir",
    "Haskell":      "haskell",
    "Perl":         "perl",
    "Shell":        "bash",
    "Dockerfile":   "docker",
    "HCL":          "terraform",
    "MATLAB":       "matlab",
    "HTML":         "html",
    "CSS":          "css",
    "SCSS":         "css",
    "Less":         "css",
    "Jupyter Notebook": "jupyter",
}

# Keywords that appear in topics/descriptions → skills
_KEYWORD_SKILL_MAP = {
    # Frameworks / libraries
    "react":           "react",
    "reactjs":         "react",
    "angular":         "angular",
    "vue":             "vue",
    "vuejs":           "vue",
    "nextjs":          "nextjs",
    "next.js":         "nextjs",
    "nuxtjs":          "nuxtjs",
    "svelte":          "svelte",
    "django":          "django",
    "flask":           "flask",
    "fastapi":         "fastapi",
    "spring":          "spring",
    "springboot":      "springboot",
    "spring-boot":     "springboot",
    "express":         "express",
    "expressjs":       "express",
    "nestjs":          "nestjs",
    "laravel":         "laravel",
    "rails":           "rails",
    "pytorch":         "pytorch",
    "tensorflow":      "tensorflow",
    "keras":           "keras",
    "sklearn":         "scikit-learn",
    "scikit":          "scikit-learn",
    "pandas":          "pandas",
    "numpy":           "numpy",
    "opencv":          "opencv",
    "nlp":             "natural language processing",
    "transformers":    "transformers",
    "huggingface":     "huggingface",
    "langchain":       "langchain",
    "bootstrap":       "bootstrap",
    "tailwind":        "tailwind",
    "redux":           "redux",
    "graphql":         "graphql",
    # Databases
    "mysql":           "mysql",
    "postgresql":      "postgresql",
    "postgres":        "postgresql",
    "mongodb":         "mongodb",
    "redis":           "redis",
    "elasticsearch":   "elasticsearch",
    "firebase":        "firebase",
    "sqlite":          "sqlite",
    "cassandra":       "cassandra",
    "dynamodb":        "dynamodb",
    "supabase":        "supabase",
    # Cloud / DevOps
    "aws":             "aws",
    "azure":           "azure",
    "gcp":             "gcp",
    "docker":          "docker",
    "kubernetes":      "kubernetes",
    "k8s":             "kubernetes",
    "terraform":       "terraform",
    "ansible":         "ansible",
    "jenkins":         "jenkins",
    "github-actions":  "github actions",
    "ci-cd":           "ci/cd",
    "cicd":            "ci/cd",
    # ML / AI
    "machine-learning":"machine learning",
    "deep-learning":   "deep learning",
    "llm":             "llm",
    "rag":             "rag",
    "mlops":           "mlops",
    "computer-vision": "computer vision",
    "data-science":    "data science",
    # Concepts
    "microservices":   "microservices",
    "rest":            "rest api",
    "restful":         "rest api",
    "api":             "rest api",
    "websocket":       "websockets",
    "testing":         "unit testing",
    "tdd":             "tdd",
    "jwt":             "jwt",
    "oauth":           "oauth",
    "kafka":           "kafka",
    "celery":          "celery",
    "rabbitmq":        "rabbitmq",
    "spark":           "spark",
    "airflow":         "airflow",
    "dbt":             "dbt",
    "snowflake":       "snowflake",
}


# --------------------------------------------------------------------------- #
#  Internal helpers                                                            #
# --------------------------------------------------------------------------- #

def _get_headers(token: Optional[str]) -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _safe_get(url: str, headers: dict, timeout: int = 8) -> Optional[dict]:
    """GET request with error handling; returns parsed JSON or None."""
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            return response.json()
        logger.warning("GitHub API %s → %s", url, response.status_code)
        return None
    except requests.RequestException as exc:
        logger.warning("GitHub request failed: %s", exc)
        return None


def _extract_skills_from_text(text: str) -> set:
    """Scan arbitrary text for skill keywords."""
    found = set()
    text_lower = text.lower()
    for kw, skill in _KEYWORD_SKILL_MAP.items():
        # Word-boundary match to avoid partial matches
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, text_lower):
            found.add(skill)
    return found


def _fetch_readme(owner: str, repo: str, headers: dict) -> str:
    """Fetch README content (base64-decoded) for a repository."""
    url = f"{_GH_API}/repos/{owner}/{repo}/readme"
    data = _safe_get(url, headers)
    if data and data.get("encoding") == "base64":
        import base64
        try:
            return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
        except Exception:
            pass
    return ""


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def get_github_data(
    username: str,
    token: Optional[str] = None,
    max_repos: int = 30,
    scan_readmes: bool = False,          # set True for deeper scanning (slower)
) -> dict:
    """
    Fetch GitHub profile data and derive verified skills.

    Parameters
    ----------
    username   : str           – GitHub username
    token      : str, optional – Personal access token (avoids rate limits)
    max_repos  : int           – Max repositories to inspect
    scan_readmes : bool        – Also scan README files (slower but richer)

    Returns
    -------
    dict:
        verified_skills  (list[str]) – normalised skill names
        languages        (dict)      – {language: byte_count}
        top_languages    (list[str]) – top 5 languages by bytes
        repo_count       (int)
        total_stars      (int)
        topics           (list[str]) – all unique repo topics
        repos            (list[dict]) – brief info per repo
        success          (bool)
        error            (str)
    """
    result = {
        "verified_skills": [],
        "languages":       {},
        "top_languages":   [],
        "repo_count":      0,
        "total_stars":     0,
        "topics":          [],
        "repos":           [],
        "success":         False,
        "error":           "",
    }

    username = (username or "").strip()
    if not username:
        result["error"] = "GitHub username is empty."
        return result

    headers = _get_headers(token)

    # ── 1. Validate user exists ──────────────────────────────────────────────
    user_data = _safe_get(f"{_GH_API}/users/{username}", headers)
    if not user_data:
        result["error"] = f"GitHub user '{username}' not found or API unavailable."
        return result

    # ── 2. Fetch repositories ────────────────────────────────────────────────
    repos_url = (
        f"{_GH_API}/users/{username}/repos"
        f"?per_page={min(max_repos, 100)}&sort=updated&type=owner"
    )
    repos_raw = _safe_get(repos_url, headers)
    if not repos_raw:
        result["error"] = "Could not fetch repositories."
        return result

    if not isinstance(repos_raw, list):
        result["error"] = "Unexpected API response for repositories."
        return result

    # ── 3. Aggregate skills ──────────────────────────────────────────────────
    skill_set:     set  = set()
    language_map:  dict = {}
    all_topics:    list = []
    total_stars:   int  = 0
    repo_summaries: list = []

    for repo in repos_raw[:max_repos]:
        if not isinstance(repo, dict):
            continue

        repo_name  = repo.get("name", "")
        repo_desc  = repo.get("description") or ""
        language   = repo.get("language")      # primary language
        topics     = repo.get("topics", [])
        stars      = repo.get("stargazers_count", 0)
        is_fork    = repo.get("fork", False)

        total_stars += stars

        repo_summaries.append({
            "name":     repo_name,
            "language": language,
            "stars":    stars,
            "topics":   topics,
            "fork":     is_fork,
        })

        # Primary language
        if language and language in _LANGUAGE_MAP:
            norm = _LANGUAGE_MAP[language]
            skill_set.add(norm)
            language_map[language] = language_map.get(language, 0) + 1

        # Topics
        for topic in topics:
            topic_lower = topic.lower().replace(" ", "-")
            if topic_lower in _KEYWORD_SKILL_MAP:
                skill_set.add(_KEYWORD_SKILL_MAP[topic_lower])
            all_topics.append(topic_lower)

        # Description keywords
        skill_set.update(_extract_skills_from_text(repo_desc))

        # README scanning (optional – adds latency)
        if scan_readmes and not is_fork:
            readme_text = _fetch_readme(username, repo_name, headers)
            if readme_text:
                skill_set.update(_extract_skills_from_text(readme_text))

    # ── 4. Language byte counts (detailed) ───────────────────────────────────
    # Use the aggregated primary-language counts already built above.
    # Retrieve per-repo language bytes for top-language ranking
    byte_totals: dict = {}
    for repo in repos_raw[:max_repos]:
        if isinstance(repo, dict) and not repo.get("fork"):
            lang = repo.get("language")
            if lang:
                byte_totals[lang] = byte_totals.get(lang, 0) + repo.get("size", 0)

    top_languages = sorted(byte_totals, key=byte_totals.get, reverse=True)[:5]
    top_languages_norm = [_LANGUAGE_MAP.get(l, l.lower()) for l in top_languages]

    # Add top languages to skill_set
    skill_set.update(top_languages_norm)

    # ── 5. Populate result ───────────────────────────────────────────────────
    result.update({
        "verified_skills": sorted(skill_set),
        "languages":       byte_totals,
        "top_languages":   top_languages_norm,
        "repo_count":      len(repos_raw),
        "total_stars":     total_stars,
        "topics":          sorted(set(all_topics)),
        "repos":           repo_summaries,
        "success":         True,
    })
    return result
