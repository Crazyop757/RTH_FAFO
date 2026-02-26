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

# Precompile patterns for performance
_SKILL_PATTERNS: list = []


def _build_patterns():
    global _SKILL_PATTERNS
    _SKILL_PATTERNS = []
    for skill in _ALL_SKILLS:
        escaped = re.escape(skill)
        # Allow optional dots/plusses around c++, .net etc.
        pattern = re.compile(r'(?<![a-z0-9])' + escaped + r'(?![a-z0-9])',
                              re.IGNORECASE)
        _SKILL_PATTERNS.append((skill, pattern))


_build_patterns()


def extract_skills_from_text(text: str) -> list:
    """
    Scan *text* for all skills present in the vocabulary.

    Parameters
    ----------
    text : str – typically cleaned resume text

    Returns
    -------
    list[str] – sorted, unique, lowercase skill names found in the text.
    """
    if not text:
        return []

    found = set()
    text_check = text.lower()

    for skill, pattern in _SKILL_PATTERNS:
        if pattern.search(text_check):
            found.add(skill)

    # Post-process: if a skill contains another (e.g. "deep learning" vs "learning"),
    # only keep the more specific one
    filtered = set()
    found_list = sorted(found, key=len, reverse=True)
    for skill in found_list:
        # Skip if a longer skill containing this word is already captured
        # Only suppress very short (≤4 char) tokens that are sub-strings
        if len(skill) <= 4:
            dominated = any(
                skill in longer and longer != skill
                for longer in found_list
                if len(longer) > len(skill)
            )
            if dominated:
                continue
        filtered.add(skill)

    return sorted(filtered)


# --------------------------------------------------------------------------- #
#  Skill merging                                                               #
# --------------------------------------------------------------------------- #

def merge_skills(
    resume_skills:   list,
    github_skills:   list,
    leetcode_skills: list,
) -> dict:
    """
    Merge skills from all three sources into a unified set with source tags.

    Returns
    -------
    dict:
        all_skills (list[str]) – sorted union of all skills
        sources    (dict)      – { skill: [source, ...] }  where source ∈
                                  {'resume', 'github', 'leetcode'}
    """
    resume_set   = {s.lower() for s in (resume_skills   or [])}
    github_set   = {s.lower() for s in (github_skills   or [])}
    leetcode_set = {s.lower() for s in (leetcode_skills or [])}

    all_skills = resume_set | github_set | leetcode_set

    sources: dict = {}
    for skill in all_skills:
        s_list = []
        if skill in resume_set:
            s_list.append("resume")
        if skill in github_set:
            s_list.append("github")
        if skill in leetcode_set:
            s_list.append("leetcode")
        sources[skill] = s_list

    return {
        "all_skills": sorted(all_skills),
        "sources":    sources,
    }


# --------------------------------------------------------------------------- #
#  Authenticity scoring                                                        #
# --------------------------------------------------------------------------- #

def compute_authenticity(
    resume_skills:   list,
    github_skills:   list,
    leetcode_skills: list,
    github_success:  bool = False,
    leetcode_success: bool = False,
) -> dict:
    """
    Assign an authenticity score (0.0 – 1.0) to each skill and compute an
    aggregate score for the whole profile.

    Scoring logic
    -------------
    Each skill starts at a base of 0.0 and accumulates:
      +0.40  if found on resume
      +0.35  if verified on GitHub  (only credited when GitHub fetch succeeded)
      +0.25  if verified on LeetCode (only credited when LC fetch succeeded)

    The aggregate score is the mean of all individual scores, clipped to [0,1].

    If external sources are unavailable (API failure), the score is scaled
    down to reflect that verification was impossible.

    Returns
    -------
    dict:
        per_skill  (dict)  – { skill: float score }
        aggregate  (float) – overall profile authenticity
        breakdown  (dict)  – counts by source, coverage %
    """
    resume_set   = {s.lower() for s in (resume_skills   or [])}
    github_set   = {s.lower() for s in (github_skills   or [])}
    leetcode_set = {s.lower() for s in (leetcode_skills or [])}

    all_skills = resume_set | github_set | leetcode_set
    if not all_skills:
        return {
            "per_skill": {},
            "aggregate": 0.0,
            "breakdown": {"resume_only": 0, "verified_github": 0,
                          "verified_leetcode": 0, "total": 0,
                          "verification_coverage": 0.0},
        }

    per_skill: dict = {}
    verified_github   = 0
    verified_leetcode = 0

    for skill in all_skills:
        score = 0.0
        if skill in resume_set:
            score += 0.40

        if github_success and skill in github_set:
            score += 0.35
            if skill in resume_set:
                verified_github += 1

        if leetcode_success and skill in leetcode_set:
            score += 0.25
            if skill in resume_set:
                verified_leetcode += 1

        # Bonus: verified by BOTH external sources
        if github_success and leetcode_success:
            if skill in github_set and skill in leetcode_set:
                score = min(score + 0.10, 1.0)

        per_skill[skill] = round(min(score, 1.0), 4)

    # Skills only found externally (not on resume) get a 0.40 presence bonus
    # since external evidence is itself meaningful
    for skill in (github_set | leetcode_set) - resume_set:
        per_skill[skill] = round(min(per_skill.get(skill, 0) + 0.40, 1.0), 4)

    # Aggregate
    aggregate = round(sum(per_skill.values()) / max(len(per_skill), 1), 4)

    resume_only = len(resume_set - github_set - leetcode_set)
    coverage = 0.0
    if resume_set:
        covered = len(resume_set & (github_set | leetcode_set))
        coverage = round(covered / len(resume_set), 4)

    return {
        "per_skill": per_skill,
        "aggregate": aggregate,
        "breakdown": {
            "resume_only":          resume_only,
            "verified_github":      verified_github,
            "verified_leetcode":    verified_leetcode,
            "total":                len(all_skills),
            "verification_coverage": coverage,
        },
    }


# --------------------------------------------------------------------------- #
#  Convenience: full skill analysis pipeline                                   #
# --------------------------------------------------------------------------- #

def analyse_skills(
    resume_text:     str,
    github_data:     Optional[dict] = None,
    leetcode_data:   Optional[dict] = None,
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
    dict:
        resume_skills     (list[str])
        github_skills     (list[str])
        leetcode_skills   (list[str])
        candidate_skills  (list[str])  – merged union
        skill_sources     (dict)       – per-skill source tags
        authenticity      (dict)       – per_skill scores + aggregate
    """
    github_data   = github_data   or {}
    leetcode_data = leetcode_data or {}

    resume_skills   = extract_skills_from_text(resume_text)
    github_skills   = github_data.get("verified_skills", [])
    leetcode_skills = leetcode_data.get("dsa_skills", [])

    merged = merge_skills(resume_skills, github_skills, leetcode_skills)

    authenticity = compute_authenticity(
        resume_skills   = resume_skills,
        github_skills   = github_skills,
        leetcode_skills = leetcode_skills,
        github_success  = bool(github_data.get("success")),
        leetcode_success= bool(leetcode_data.get("success")),
    )

    return {
        "resume_skills":    resume_skills,
        "github_skills":    github_skills,
        "leetcode_skills":  leetcode_skills,
        "candidate_skills": merged["all_skills"],
        "skill_sources":    merged["sources"],
        "authenticity":     authenticity,
    }
