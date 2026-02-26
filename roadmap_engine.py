"""
roadmap_engine.py
-----------------
Generates a personalised, phased skill-gap roadmap for a candidate.

Each missing skill maps to:
  - A learning phase (short-term / medium-term / long-term)
  - Curated free learning resources (courses, docs, practice sites)
  - Estimated learning time
  - Practical project ideas to build evidence of the skill

The roadmap respects skill dependency ordering and the candidate's
existing baseline so the plan is always incremental.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Resource library                                                            #
# --------------------------------------------------------------------------- #

_RESOURCES: dict = {
    # --- Languages -----------------------------------------------------------
    "python": {
        "resources": [
            {"name": "Python Official Tutorial", "url": "https://docs.python.org/3/tutorial/", "type": "docs"},
            {"name": "CS50P – Harvard Python", "url": "https://cs50.harvard.edu/python/", "type": "course"},
            {"name": "Real Python", "url": "https://realpython.com/", "type": "guide"},
        ],
        "projects": ["CLI tool", "web scraper", "data analysis notebook"],
        "hours": 40,
    },
    "javascript": {
        "resources": [
            {"name": "javascript.info", "url": "https://javascript.info/", "type": "guide"},
            {"name": "MDN Web Docs – JS", "url": "https://developer.mozilla.org/docs/Web/JavaScript", "type": "docs"},
            {"name": "freeCodeCamp JS Algorithms", "url": "https://www.freecodecamp.org/learn/javascript-algorithms-and-data-structures/", "type": "course"},
        ],
        "projects": ["To-do app", "weather dashboard", "quiz game"],
        "hours": 50,
    },
    "typescript": {
        "resources": [
            {"name": "TypeScript Official Docs", "url": "https://www.typescriptlang.org/docs/", "type": "docs"},
            {"name": "Total TypeScript", "url": "https://www.totaltypescript.com/", "type": "guide"},
        ],
        "projects": ["Type-safe REST client", "typed React component library"],
        "hours": 25,
    },
    "java": {
        "resources": [
            {"name": "Java Programming MOOC – Helsinki", "url": "https://java-programming.mooc.fi/", "type": "course"},
            {"name": "Baeldung", "url": "https://www.baeldung.com/", "type": "guide"},
        ],
        "projects": ["REST API with Spring Boot", "multi-threaded file processor"],
        "hours": 60,
    },
    "c++": {
        "resources": [
            {"name": "learncpp.com", "url": "https://www.learncpp.com/", "type": "guide"},
            {"name": "cppreference", "url": "https://en.cppreference.com/", "type": "docs"},
        ],
        "projects": ["Data structures library", "game engine prototype"],
        "hours": 60,
    },
    "go": {
        "resources": [
            {"name": "Tour of Go", "url": "https://go.dev/tour/", "type": "guide"},
            {"name": "Go by Example", "url": "https://gobyexample.com/", "type": "guide"},
        ],
        "projects": ["HTTP microservice", "concurrent web crawler"],
        "hours": 35,
    },
    "rust": {
        "resources": [
            {"name": "The Rust Book", "url": "https://doc.rust-lang.org/book/", "type": "docs"},
            {"name": "Rustlings", "url": "https://github.com/rust-lang/rustlings", "type": "practice"},
        ],
        "projects": ["CLI utility", "key-value store"],
        "hours": 60,
    },
    # --- Frontend ------------------------------------------------------------
    "html": {
        "resources": [
            {"name": "MDN HTML", "url": "https://developer.mozilla.org/docs/Web/HTML", "type": "docs"},
            {"name": "freeCodeCamp Responsive Web", "url": "https://www.freecodecamp.org/learn/2022/responsive-web-design/", "type": "course"},
        ],
        "projects": ["Portfolio page", "HTML email template"],
        "hours": 15,
    },
    "css": {
        "resources": [
            {"name": "CSS-Tricks", "url": "https://css-tricks.com/", "type": "guide"},
            {"name": "Flexbox Froggy", "url": "https://flexboxfroggy.com/", "type": "practice"},
        ],
        "projects": ["Pixel-perfect landing page", "animated UI components"],
        "hours": 20,
    },
    "react": {
        "resources": [
            {"name": "React Official Docs", "url": "https://react.dev/", "type": "docs"},
            {"name": "Full Stack Open – React", "url": "https://fullstackopen.com/en/", "type": "course"},
        ],
        "projects": ["Blog platform SPA", "real-time chat with WebSockets"],
        "hours": 45,
    },
    "nextjs": {
        "resources": [
            {"name": "Next.js Docs", "url": "https://nextjs.org/docs", "type": "docs"},
            {"name": "Vercel Learn Next.js", "url": "https://nextjs.org/learn", "type": "course"},
        ],
        "projects": ["SSR e-commerce site", "blog with MDX"],
        "hours": 30,
    },
    "vue": {
        "resources": [
            {"name": "Vue 3 Docs", "url": "https://vuejs.org/guide/introduction.html", "type": "docs"},
        ],
        "projects": ["Dashboard UI", "real-time todo with Pinia"],
        "hours": 35,
    },
    "tailwind": {
        "resources": [
            {"name": "Tailwind CSS Docs", "url": "https://tailwindcss.com/docs", "type": "docs"},
        ],
        "projects": ["Redesign a site with Tailwind", "component library"],
        "hours": 10,
    },
    # --- Backend frameworks --------------------------------------------------
    "django": {
        "resources": [
            {"name": "Django Official Tutorial", "url": "https://docs.djangoproject.com/en/stable/intro/tutorial01/", "type": "docs"},
            {"name": "Django for Beginners – Learndjango", "url": "https://learndjango.com/", "type": "guide"},
        ],
        "projects": ["Blog CMS", "e-commerce backend with DRF"],
        "hours": 40,
    },
    "flask": {
        "resources": [
            {"name": "Flask Docs", "url": "https://flask.palletsprojects.com/", "type": "docs"},
            {"name": "The Flask Mega-Tutorial", "url": "https://blog.miguelgrinberg.com/post/the-flask-mega-tutorial-part-i-hello-world", "type": "guide"},
        ],
        "projects": ["REST API", "JWT-auth microservice"],
        "hours": 25,
    },
    "fastapi": {
        "resources": [
            {"name": "FastAPI Docs", "url": "https://fastapi.tiangolo.com/", "type": "docs"},
        ],
        "projects": ["Async REST API", "ML model serving endpoint"],
        "hours": 20,
    },
    "springboot": {
        "resources": [
            {"name": "Spring Boot Guides", "url": "https://spring.io/guides", "type": "docs"},
            {"name": "Baeldung Spring Boot", "url": "https://www.baeldung.com/spring-boot", "type": "guide"},
        ],
        "projects": ["Microservice with Spring Cloud", "REST API with JPA"],
        "hours": 50,
    },
    "express": {
        "resources": [
            {"name": "Express Docs", "url": "https://expressjs.com/", "type": "docs"},
            {"name": "Full Stack Open – Node", "url": "https://fullstackopen.com/en/part3", "type": "course"},
        ],
        "projects": ["RESTful API server", "auth middleware library"],
        "hours": 25,
    },
    # --- Databases -----------------------------------------------------------
    "sql": {
        "resources": [
            {"name": "SQLZoo", "url": "https://sqlzoo.net/", "type": "practice"},
            {"name": "Mode SQL Tutorial", "url": "https://mode.com/sql-tutorial/", "type": "guide"},
        ],
        "projects": ["Design e-commerce schema", "analytics queries on open dataset"],
        "hours": 20,
    },
    "postgresql": {
        "resources": [
            {"name": "PostgreSQL Tutorial", "url": "https://www.postgresqltutorial.com/", "type": "guide"},
            {"name": "PostgreSQL Docs", "url": "https://www.postgresql.org/docs/", "type": "docs"},
        ],
        "projects": ["Multi-tenant SaaS schema", "full-text search feature"],
        "hours": 20,
    },
    "mongodb": {
        "resources": [
            {"name": "MongoDB University", "url": "https://university.mongodb.com/", "type": "course"},
            {"name": "MongoDB Docs", "url": "https://www.mongodb.com/docs/", "type": "docs"},
        ],
        "projects": ["Social-media data model", "aggregation pipeline analytics"],
        "hours": 20,
    },
    "redis": {
        "resources": [
            {"name": "Redis University", "url": "https://university.redis.io/", "type": "course"},
            {"name": "Redis Docs", "url": "https://redis.io/docs/", "type": "docs"},
        ],
        "projects": ["Session store", "leaderboard / pub-sub"],
        "hours": 15,
    },
    # --- Cloud & DevOps -------------------------------------------------------
    "docker": {
        "resources": [
            {"name": "Docker Docs – Getting Started", "url": "https://docs.docker.com/get-started/", "type": "docs"},
            {"name": "Play with Docker", "url": "https://labs.play-with-docker.com/", "type": "practice"},
        ],
        "projects": ["Containerise a Flask app", "multi-container compose setup"],
        "hours": 20,
    },
    "kubernetes": {
        "resources": [
            {"name": "Kubernetes Docs", "url": "https://kubernetes.io/docs/home/", "type": "docs"},
            {"name": "KillerCoda – K8s", "url": "https://killercoda.com/kubernetes", "type": "practice"},
        ],
        "projects": ["Deploy microservices on local cluster", "Helm chart for web app"],
        "hours": 40,
    },
    "aws": {
        "resources": [
            {"name": "AWS Skill Builder (Free)", "url": "https://skillbuilder.aws/", "type": "course"},
            {"name": "AWS Cloud Practitioner Essentials", "url": "https://aws.amazon.com/training/learn-about/cloud-practitioner/", "type": "course"},
        ],
        "projects": ["Host static site on S3 + CloudFront", "serverless API with Lambda"],
        "hours": 50,
    },
    "terraform": {
        "resources": [
            {"name": "HashiCorp Learn – Terraform", "url": "https://developer.hashicorp.com/terraform/tutorials", "type": "course"},
        ],
        "projects": ["Provision VPC + EC2 with Terraform", "multi-environment IaC"],
        "hours": 25,
    },
    "ci/cd": {
        "resources": [
            {"name": "GitHub Actions Docs", "url": "https://docs.github.com/en/actions", "type": "docs"},
            {"name": "CircleCI Learn", "url": "https://circleci.com/blog/learn-iac-part1/", "type": "guide"},
        ],
        "projects": ["CI/CD pipeline for a Python app", "auto-deploy to cloud on merge"],
        "hours": 20,
    },
    "linux": {
        "resources": [
            {"name": "The Linux Command Line (free PDF)", "url": "https://linuxcommand.org/tlcl.php", "type": "guide"},
            {"name": "OverTheWire – Bandit", "url": "https://overthewire.org/wargames/bandit/", "type": "practice"},
        ],
        "projects": ["Automate server setup with shell script", "cron job manager"],
        "hours": 25,
    },
    # --- Machine Learning / AI -----------------------------------------------
    "machine learning": {
        "resources": [
            {"name": "Andrew Ng – ML Specialization (Coursera)", "url": "https://www.coursera.org/specializations/machine-learning-introduction", "type": "course"},
            {"name": "fast.ai Practical ML", "url": "https://course.fast.ai/", "type": "course"},
        ],
        "projects": ["House price predictor", "sentiment analysis classifier"],
        "hours": 80,
    },
    "deep learning": {
        "resources": [
            {"name": "Deep Learning Specialization – Coursera", "url": "https://www.coursera.org/specializations/deep-learning", "type": "course"},
            {"name": "fast.ai Deep Learning", "url": "https://course.fast.ai/", "type": "course"},
        ],
        "projects": ["Image classifier with CNN", "text generator with LSTM"],
        "hours": 80,
    },
    "natural language processing": {
        "resources": [
            {"name": "HuggingFace NLP Course", "url": "https://huggingface.co/learn/nlp-course/", "type": "course"},
            {"name": "Stanford CS224N (free lectures)", "url": "https://web.stanford.edu/class/cs224n/", "type": "course"},
        ],
        "projects": ["Named-entity recognition API", "document summariser"],
        "hours": 60,
    },
    "pytorch": {
        "resources": [
            {"name": "PyTorch Tutorials (Official)", "url": "https://pytorch.org/tutorials/", "type": "docs"},
            {"name": "Deep Learning with PyTorch – freeCodeCamp", "url": "https://www.youtube.com/watch?v=GIsg-ZUy0MY", "type": "course"},
        ],
        "projects": ["Custom neural net for classification", "fine-tune BERT"],
        "hours": 45,
    },
    "tensorflow": {
        "resources": [
            {"name": "TensorFlow Tutorials (Official)", "url": "https://www.tensorflow.org/tutorials", "type": "docs"},
        ],
        "projects": ["Image recognition with Keras", "time series forecast"],
        "hours": 40,
    },
    "scikit-learn": {
        "resources": [
            {"name": "Scikit-learn User Guide", "url": "https://scikit-learn.org/stable/user_guide.html", "type": "docs"},
        ],
        "projects": ["Churn prediction pipeline", "feature selection experiment"],
        "hours": 20,
    },
    "mlops": {
        "resources": [
            {"name": "MLOps Specialization – Coursera", "url": "https://www.coursera.org/specializations/machine-learning-engineering-for-production-mlops", "type": "course"},
            {"name": "Made With ML – MLOps", "url": "https://madewithml.com/", "type": "guide"},
        ],
        "projects": ["Model registry with MLflow", "automated retraining pipeline"],
        "hours": 50,
    },
    "llm": {
        "resources": [
            {"name": "Andrej Karpathy – Let's build GPT", "url": "https://www.youtube.com/watch?v=kCc8FmEb1nY", "type": "course"},
            {"name": "LangChain Docs", "url": "https://python.langchain.com/docs/get_started/introduction", "type": "docs"},
        ],
        "projects": ["RAG chatbot over custom documents", "LLM-powered code reviewer"],
        "hours": 60,
    },
    # --- Data Engineering ----------------------------------------------------
    "spark": {
        "resources": [
            {"name": "Spark Official Docs", "url": "https://spark.apache.org/docs/latest/", "type": "docs"},
            {"name": "Databricks Academy (Free)", "url": "https://www.databricks.com/learn/training", "type": "course"},
        ],
        "projects": ["Batch ETL pipeline", "Spark streaming word count"],
        "hours": 50,
    },
    "kafka": {
        "resources": [
            {"name": "Kafka Quickstart", "url": "https://kafka.apache.org/quickstart", "type": "docs"},
            {"name": "Confluent Developer Courses", "url": "https://developer.confluent.io/learn-kafka/", "type": "course"},
        ],
        "projects": ["Real-time event pipeline", "Kafka + Spark streaming"],
        "hours": 35,
    },
    "airflow": {
        "resources": [
            {"name": "Airflow Official Docs", "url": "https://airflow.apache.org/docs/", "type": "docs"},
            {"name": "Astronomer Learn Airflow", "url": "https://docs.astronomer.io/learn", "type": "guide"},
        ],
        "projects": ["Scheduled data pipeline DAG", "ETL with retries and alerts"],
        "hours": 30,
    },
    # --- CS Fundamentals & DSA ----------------------------------------------
    "algorithms": {
        "resources": [
            {"name": "Algorithms – Princeton (Coursera)", "url": "https://www.coursera.org/learn/algorithms-part1", "type": "course"},
            {"name": "NeetCode DSA Roadmap", "url": "https://neetcode.io/roadmap", "type": "practice"},
        ],
        "projects": ["Implement sorting algorithms from scratch", "solve 50 LeetCode medium problems"],
        "hours": 60,
    },
    "data structures": {
        "resources": [
            {"name": "Visualgo", "url": "https://visualgo.net/", "type": "practice"},
            {"name": "MIT OpenCourseWare 6.006", "url": "https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/", "type": "course"},
        ],
        "projects": ["Build a binary search tree library", "implement LRU cache"],
        "hours": 40,
    },
    "dynamic programming": {
        "resources": [
            {"name": "Dynamic Programming Patterns – LeetCode", "url": "https://leetcode.com/discuss/general-discussion/458695/dynamic-programming-patterns", "type": "guide"},
            {"name": "Aditya Verma DP Playlist", "url": "https://www.youtube.com/playlist?list=PL_z_8CaSLPWekqhdCPmFohncHwz8TY2Go", "type": "course"},
        ],
        "projects": ["Solve 30 DP problems on LeetCode", "implement knapsack variants"],
        "hours": 30,
    },
    "system design": {
        "resources": [
            {"name": "System Design Primer – GitHub", "url": "https://github.com/donnemartin/system-design-primer", "type": "guide"},
            {"name": "Gaurav Sen System Design (YouTube)", "url": "https://www.youtube.com/c/GauravSensei", "type": "course"},
            {"name": "ByteByteGo Newsletter", "url": "https://bytebytego.com/", "type": "guide"},
        ],
        "projects": ["Design URL shortener", "design Twitter feed system"],
        "hours": 50,
    },
    "microservices": {
        "resources": [
            {"name": "Microservices.io", "url": "https://microservices.io/", "type": "guide"},
            {"name": "Sam Newman – Building Microservices (O'Reilly)", "url": "https://www.oreilly.com/library/view/building-microservices-2nd/9781492034018/", "type": "guide"},
        ],
        "projects": ["Decompose a monolith into 3 services", "inter-service communication demo"],
        "hours": 40,
    },
    "graphql": {
        "resources": [
            {"name": "HowToGraphQL", "url": "https://www.howtographql.com/", "type": "course"},
            {"name": "GraphQL Official Docs", "url": "https://graphql.org/learn/", "type": "docs"},
        ],
        "projects": ["GraphQL API for blog", "replace REST with GraphQL layer"],
        "hours": 20,
    },
    "rest api": {
        "resources": [
            {"name": "REST API Tutorial", "url": "https://restfulapi.net/", "type": "guide"},
            {"name": "Postman Learning Centre", "url": "https://learning.postman.com/", "type": "guide"},
        ],
        "projects": ["Design and document a REST API", "versioned API with rate limiting"],
        "hours": 15,
    },
    "git": {
        "resources": [
            {"name": "Pro Git Book (free)", "url": "https://git-scm.com/book/en/v2", "type": "guide"},
            {"name": "Learn Git Branching", "url": "https://learngitbranching.js.org/", "type": "practice"},
        ],
        "projects": ["Contribute to an open-source repo", "maintain changelog with git tags"],
        "hours": 10,
    },
    "unit testing": {
        "resources": [
            {"name": "pytest Docs", "url": "https://docs.pytest.org/", "type": "docs"},
            {"name": "TDD with Python – Harry Percival", "url": "https://www.obeythetestinggoat.com/", "type": "guide"},
        ],
        "projects": ["Achieve 80%+ coverage on a project", "test suite for a REST API"],
        "hours": 15,
    },
    "authentication": {
        "resources": [
            {"name": "OWASP Authentication Cheat Sheet", "url": "https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html", "type": "guide"},
            {"name": "Auth0 Blog", "url": "https://auth0.com/blog/", "type": "guide"},
        ],
        "projects": ["JWT auth system", "OAuth2 integration with GitHub"],
        "hours": 15,
    },
    "caching": {
        "resources": [
            {"name": "Redis Caching Patterns", "url": "https://redis.io/docs/manual/patterns/", "type": "docs"},
        ],
        "projects": ["Cache database queries with Redis", "CDN edge-cache strategy"],
        "hours": 10,
    },
}

# Default resource for skills not in the library
_DEFAULT_RESOURCE = {
    "resources": [
        {"name": "Google search", "url": "https://www.google.com/search?q=learn+{skill}", "type": "search"},
        {"name": "YouTube search", "url": "https://www.youtube.com/results?search_query=learn+{skill}", "type": "video"},
    ],
    "projects": ["Build a small demo project using {skill}"],
    "hours": 20,
}


# --------------------------------------------------------------------------- #
#  Phase assignment                                                            #
# --------------------------------------------------------------------------- #

def _assign_phase(weight: int, estimated_hours: int) -> dict:
    """
    Short-term : Critical skills (weight 3) with ≤25 h  OR
                 any skill with ≤15 h
    Medium-term: Important skills (weight 2) OR ≤60 h
    Long-term  : Complex/deep skills (>60 h) or nice-to-have
    """
    if weight >= 3 and estimated_hours <= 25:
        return {"phase": "short-term",  "label": "Start within 2–4 weeks",  "order": 1}
    elif weight >= 3:
        return {"phase": "medium-term", "label": "Target within 1–3 months", "order": 2}
    elif estimated_hours <= 15:
        return {"phase": "short-term",  "label": "Start within 2–4 weeks",  "order": 1}
    elif estimated_hours <= 60:
        return {"phase": "medium-term", "label": "Target within 1–3 months", "order": 2}
    else:
        return {"phase": "long-term",   "label": "Plan for 3–6 months",      "order": 3}


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def generate_roadmap(
    skill_gaps:       dict,
    candidate_skills: list,
    role_name:        str            = "",
    leetcode_data:    Optional[dict] = None,
) -> dict:
    """
    Generate a personalised skill-gap roadmap.

    Parameters
    ----------
    skill_gaps       : dict  – output of role_engine.identify_skill_gaps()
    candidate_skills : list  – current candidate skills (to avoid duplicates)
    role_name        : str   – target role label for context
    leetcode_data    : dict  – LeetCode stats (used to skip already-proven DSA)

    Returns
    -------
    dict:
        role            (str)
        phases          (dict)  – {"short-term": [...], "medium-term": [...], "long-term": [...]}
        total_items     (int)
        total_hours     (int)
        nice_to_have    (list)
        summary         (str)
    """
    missing_skills  = skill_gaps.get("missing_skills",    [])
    nth_gaps        = skill_gaps.get("nice_to_have_gaps",  [])
    candidate_set   = {s.lower() for s in (candidate_skills or [])}
    lc_data         = leetcode_data or {}
    lc_skills       = set(lc_data.get("dsa_skills", []))

    phases: dict = {"short-term": [], "medium-term": [], "long-term": []}
    total_hours  = 0

    for gap_item in missing_skills:
        skill  = gap_item["skill"]
        weight = gap_item["weight"]

        # Skip if candidate already has this via LeetCode
        if skill in lc_skills:
            continue

        # Look up resource entry
        entry = _RESOURCES.get(skill)
        if entry is None:
            entry = {
                "resources": [
                    {
                        "name": f"Search: learn {skill}",
                        "url": f"https://www.google.com/search?q=learn+{skill.replace(' ', '+')}",
                        "type": "search",
                    }
                ],
                "projects": [f"Build a small project demonstrating {skill}"],
                "hours": 20,
            }

        hours   = entry.get("hours", 20)
        phase_info = _assign_phase(weight, hours)
        total_hours += hours

        roadmap_item = {
            "skill":       skill,
            "priority":    gap_item["label"],
            "weight":      weight,
            "hours":       hours,
            "resources":   entry.get("resources", []),
            "projects":    entry.get("projects", []),
            "phase":       phase_info["phase"],
            "phase_label": phase_info["label"],
        }

        phases[phase_info["phase"]].append(roadmap_item)

    # Sort within each phase: Critical first, then by hours ascending
    for phase_name in phases:
        phases[phase_name].sort(key=lambda x: (-x["weight"], x["hours"]))

    # Nice-to-have section (lightweight)
    nth_items = []
    for skill in nth_gaps[:10]:
        entry = _RESOURCES.get(skill, {})
        nth_items.append({
            "skill":     skill,
            "resources": entry.get("resources", []),
            "hours":     entry.get("hours", 20),
        })

    total_items = sum(len(v) for v in phases.values())

    # Summary sentence
    st = len(phases["short-term"])
    mt = len(phases["medium-term"])
    lt = len(phases["long-term"])
    summary = (
        f"Your roadmap for '{role_name}' has {total_items} skill gaps: "
        f"{st} short-term, {mt} medium-term, {lt} long-term. "
        f"Estimated effort: ~{total_hours} hours."
    )

    return {
        "role":        role_name,
        "phases":      phases,
        "total_items": total_items,
        "total_hours": total_hours,
        "nice_to_have": nth_items,
        "summary":     summary,
    }
