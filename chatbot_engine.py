"""
chatbot_engine.py  –  PlacementIQ Intelligent Chatbot
=====================================================
Handles a wide variety of natural-language questions about the platform.

Matching pipeline (highest → lowest priority):
  1. Exact phrase / substring match
  2. Weighted specific-keyword scoring  (stop-words excluded)
  3. Fuzzy similarity on topic keywords
  4. DEFAULT_RESPONSE
"""

import re
from difflib import SequenceMatcher

# ═══════════════════════════════════════════════════════════════════════════
#  KNOWLEDGE BASE
# ═══════════════════════════════════════════════════════════════════════════
KNOWLEDGE_BASE = [

    # ── Greetings ────────────────────────────────────────────────────────────
    {
        "phrases": ["hello", "hi there", "hey there", "hey bot", "good morning",
                    "good afternoon", "good evening", "howdy", "what's up",
                    "sup bot", "greetings"],
        "keywords": ["hello", "hi", "hey", "howdy", "morning", "afternoon", "evening"],
        "response": (
            "Hey! 👋 I'm your PlacementIQ assistant — always online and happy to help.\n\n"
            "Here's what I can answer:\n"
            "📊 Readiness & Authenticity scores\n"
            "🐙 GitHub & LeetCode integration\n"
            "💼 Jobs, matching & applications\n"
            "🗺️ Skill gaps & learning roadmaps\n"
            "👔 Recruiter features\n"
            "🔒 Privacy, pricing & file formats\n\n"
            "Ask away — I respond instantly!"
        )
    },

    # ── What is PlacementIQ ──────────────────────────────────────────────────
    {
        "phrases": ["what is placementiq", "what does placementiq do", "about placementiq",
                    "explain placementiq", "tell me about placementiq",
                    "what is this platform", "what is this website", "what is this app",
                    "purpose of this platform", "tell me about this platform",
                    "tell me about placement", "what is placement platform",
                    "describe this platform", "overview of placementiq"],
        "keywords": ["placementiq", "platform", "overview", "purpose", "goal"],
        "response": (
            "PlacementIQ is an AI-powered campus placement platform that goes far beyond a regular job board.\n\n"
            "Here's what makes it unique:\n"
            "🔍 Analyzes your Resume, GitHub & LeetCode profiles together\n"
            "✅ Verifies your skills with real code evidence (not just what you wrote on paper)\n"
            "📊 Gives you an Authenticity Score, Readiness Score & Role Match %\n"
            "🗺️ Builds a personalized learning roadmap to close your skill gaps\n"
            "💼 Matches you with recruiters who are hiring for your exact skill set\n\n"
            "For recruiters, it auto-ranks applicants by AI score — no manual CV screening needed!\n"
            "Bottom line: it bridges the gap between students and real hiring with verified data."
        )
    },

    # ── How it works / process ───────────────────────────────────────────────
    {
        "phrases": ["how does it work", "how to use this", "how do i use", "how to get started",
                    "explain the process", "what are the steps", "walk me through",
                    "how to start", "step by step", "how does the platform work",
                    "process of using", "getting started", "how to sign up",
                    "how to register", "how to create account"],
        "keywords": ["works", "process", "steps", "start", "begin", "register", "signup", "walkthrough"],
        "response": (
            "It's super straightforward — here's the full flow:\n\n"
            "Step 1️⃣ — Sign In\n"
            "Choose your role: Student or Recruiter. No lengthy registration!\n\n"
            "Step 2️⃣ — Upload Your Profile (Students)\n"
            "Upload your resume (PDF/DOCX) + enter your GitHub & LeetCode usernames.\n\n"
            "Step 3️⃣ — AI Analysis\n"
            "Our pipeline extracts skills from all 3 sources, cross-verifies them, and scores everything in real time.\n\n"
            "Step 4️⃣ — View Your Report\n"
            "See your Readiness Score, Authenticity Score, skill gaps, role match, and a learning roadmap.\n\n"
            "Step 5️⃣ — Apply to Jobs\n"
            "Browse job listings ranked by YOUR match % and hit Apply — recruiters see your full AI report!\n\n"
            "The whole analysis takes under 30 seconds. 🚀"
        )
    },

    # ── Authenticity Score ───────────────────────────────────────────────────
    {
        "phrases": ["what is authenticity score", "authenticity score", "what is authenticity",
                    "how is authenticity calculated", "explain authenticity",
                    "skill verification", "how do you verify skills", "verify my skills",
                    "how are skills verified", "is my skill genuine", "fake skills",
                    "lying on resume", "resume verification", "skill proof"],
        "keywords": ["authenticity", "authentic", "verify", "verification", "genuine", "validate", "credibility", "proof"],
        "response": (
            "Authenticity Score (0–100) measures how PROVEN your skills are — not just claimed. 🧪\n\n"
            "Here's exactly how it's calculated:\n"
            "🔍 We scan your GitHub for repos that match skills listed on your resume\n"
            "📈 We check languages used, frameworks, project complexity & commit history\n"
            "⚖️ If you claim 'Machine Learning' but have zero ML repos — that lowers your score\n"
            "✅ If your GitHub actively shows Python, React, etc. — those skills get 'verified' status\n\n"
            "Example: 80+ Authenticity = 'Highly Credible' | Below 40 = 'Mostly Unverified'\n\n"
            "Pro tip: Even 1–2 solid GitHub projects per claimed skill dramatically boosts your authenticity! 💡"
        )
    },

    # ── Readiness Score ──────────────────────────────────────────────────────
    {
        "phrases": ["what is readiness score", "readiness score", "what is readiness",
                    "how is readiness calculated", "explain readiness",
                    "job readiness", "placement readiness", "my readiness score",
                    "what does readiness mean", "how ready am i", "am i job ready"],
        "keywords": ["readiness", "ready", "prepared", "job-ready", "placement-ready"],
        "response": (
            "Readiness Score (0–100) is your overall job-readiness rating — think of it as your placement health score! 💪\n\n"
            "It's calculated from 4 components:\n"
            "1. 🔐 Skill Authenticity — how verified your skills are via GitHub\n"
            "2. 🎯 Role Match % — overlap of your skills with your target role\n"
            "3. 💻 Coding Activity — GitHub repos + LeetCode problems solved\n"
            "4. 🎓 CGPA — optional academic bonus\n\n"
            "Score ranges:\n"
            "🟢 80–100: Strong candidate — recruiters will notice\n"
            "🟡 50–79: Decent — work on skill gaps to push higher\n"
            "🔴 Below 50: Focus on GitHub projects & LeetCode first\n\n"
            "The Readiness Score is what recruiters see first when they view your application!"
        )
    },

    # ── All 3 Scores explained ───────────────────────────────────────────────
    {
        "phrases": ["explain all scores", "what are the scores", "what scores do i get",
                    "how many scores", "what is role match", "role match percentage",
                    "what does score mean", "explain the scoring"],
        "keywords": ["scores", "scoring", "rating", "metrics", "evaluation"],
        "response": (
            "PlacementIQ gives you 3 powerful scores:\n\n"
            "🔵 Readiness Score (0–100)\n"
            "Your overall job-readiness. Combines authentication, role match, coding activity & CGPA.\n\n"
            "🟣 Authenticity Score (0–100)\n"
            "How well your GitHub activity proves the skills on your resume. Real code = real score.\n\n"
            "🟢 Role Match % (0–100%)\n"
            "Percentage of skills in a job posting that you actually have verified. Higher % = better fit.\n\n"
            "Together these give recruiters a full, evidence-backed picture of you — "
            "not just what you wrote on a CV. It's the smartest way to stand out! ✨"
        )
    },

    # ── Skill Gaps ───────────────────────────────────────────────────────────
    {
        "phrases": ["what are skill gaps", "skill gap", "missing skills", "what skills am i missing",
                    "skills i need to learn", "gap analysis", "what do i lack",
                    "which skills are missing", "skills required for my role",
                    "what skills should i have"],
        "keywords": ["gap", "gaps", "missing", "lack", "deficiency", "shortage", "required-skills"],
        "response": (
            "Skill Gaps are the specific technologies or skills required for your target role "
            "that aren't yet proven in your resume or GitHub. 🔍\n\n"
            "For example:\n"
            "🎯 Target role: Data Scientist\n"
            "✅ You have: Python, SQL, Pandas\n"
            "❌ Missing: TensorFlow, PyTorch, MLflow (not found in your GitHub)\n\n"
            "We don't just list them — we also:\n"
            "📌 Rank gaps by importance for your target role\n"
            "🗺️ Build a learning roadmap to close each gap\n"
            "📊 Show how closing each gap improves your match %\n\n"
            "Think of skill gaps as your personal 'To-Learn' list — precise, role-specific, and actionable!"
        )
    },

    # ── Learning Roadmap ─────────────────────────────────────────────────────
    {
        "phrases": ["learning roadmap", "my roadmap", "learning path", "study plan",
                    "what should i learn", "how to close skill gap", "how to improve skills",
                    "suggest learning path", "recommend courses", "what to study",
                    "guide me to learn", "how to upskill"],
        "keywords": ["roadmap", "learning", "pathway", "plan", "upskill", "curriculum", "study", "courses"],
        "response": (
            "Your Learning Roadmap is auto-generated just for YOU — not a generic list. 🗺️\n\n"
            "Here's what it contains:\n"
            "📍 Each skill gap listed as a step\n"
            "📊 Prioritized by: how much each skill boosts your role match %\n"
            "📚 Suggested learning resources for each skill\n"
            "🔁 Dynamic — re-run analysis after learning to see your score improve\n\n"
            "Example roadmap for a Backend Engineer:\n"
            "Step 1 → Learn Docker (high priority — in 8/10 job listings)\n"
            "Step 2 → REST API design patterns\n"
            "Step 3 → Redis caching\n\n"
            "The roadmap updates every time you re-analyse your profile. "
            "Students who follow it typically see a 20–30% score jump within a month! 🚀"
        )
    },

    # ── GitHub ───────────────────────────────────────────────────────────────
    {
        "phrases": ["how does github work", "github integration", "why github",
                    "what does github do here", "how is github used",
                    "do i need github", "is github required", "github analysis",
                    "what github data do you use", "github profile"],
        "keywords": ["github", "repository", "repositories", "repo", "repos", "git", "commits", "contributions", "open-source"],
        "response": (
            "GitHub is the backbone of our verification system — here's how we use it: 🐙\n\n"
            "We analyze your PUBLIC GitHub profile and look at:\n"
            "📁 Repositories — languages used, frameworks, project size\n"
            "📊 Commit history — consistency and activity over time\n"
            "🌿 Branches, PRs, issues — coding maturity & collaboration\n"
            "⭐ Project complexity — solo vs team projects, real deployments\n\n"
            "This data directly feeds your Authenticity Score.\n\n"
            "Don't have GitHub yet?\n"
            "Create a free account at github.com and upload 2–3 projects. "
            "Even university assignments count! A strong GitHub can compensate for a lower CGPA entirely."
        )
    },

    # ── LeetCode ─────────────────────────────────────────────────────────────
    {
        "phrases": ["how does leetcode work", "leetcode integration", "why leetcode",
                    "what does leetcode do here", "do i need leetcode",
                    "is leetcode required", "leetcode analysis", "leetcode stats",
                    "dsa practice", "competitive programming", "coding problems",
                    "how many leetcode problems", "leetcode rating"],
        "keywords": ["leetcode", "dsa", "algorithms", "competitive", "problems", "easy", "medium", "hard", "coding-problems"],
        "response": (
            "LeetCode stats measure your problem-solving & algorithmic thinking — "
            "a must-have signal for product company roles. 💻\n\n"
            "What we track from LeetCode:\n"
            "🟢 Easy problems solved\n"
            "🟡 Medium problems solved (most valued by recruiters)\n"
            "🔴 Hard problems solved\n"
            "📈 Total solve count & global ranking\n\n"
            "How it affects your score:\n"
            "✅ 100+ problems solved → healthy coding activity\n"
            "✅ 50% Medium/Hard → strong signal for tech-heavy roles\n"
            "⚠️ 0 problems → coding proficiency shows as 'Unassessed'\n\n"
            "Tip: Even 20–30 Medium problems solved consistently is better than 200 Easy-only. Quality > quantity! 🎯"
        )
    },

    # ── Applying to jobs ─────────────────────────────────────────────────────
    {
        "phrases": ["how to apply for jobs", "how to apply", "apply to jobs",
                    "job application process", "how do i apply",
                    "apply for a position", "submit application",
                    "how to send application", "can i apply multiple jobs"],
        "keywords": ["apply", "application", "applying", "submit", "send-application"],
        "response": (
            "Applying for jobs on PlacementIQ is simple and smart: 💼\n\n"
            "1. Go to the **Jobs** page after analysing your profile\n"
            "2. You'll see all active listings with YOUR personal match % on each card\n"
            "3. Jobs where you match 70%+ are highlighted as strong fits\n"
            "4. Click any job → view required skills & see which ones you match\n"
            "5. Hit **Apply Now** — your full AI report is automatically shared with the recruiter\n\n"
            "What recruiters see:\n"
            "🔵 Your Readiness Score\n"
            "🟣 Authenticity Score\n"
            "🟢 Role Match % for their specific job\n"
            "📊 Skill breakdown, GitHub activity, LeetCode stats\n\n"
            "No cover letter, no manual form — just your verified profile doing the talking! ✅"
        )
    },

    # ── Job listings ─────────────────────────────────────────────────────────
    {
        "phrases": ["what jobs are available", "browse jobs", "find jobs", "job listings",
                    "what companies are hiring", "see jobs", "available openings",
                    "job search", "how are jobs matched", "job matching algorithm"],
        "keywords": ["job", "jobs", "vacancy", "vacancies", "opening", "openings", "listing", "listings", "browse", "companies"],
        "response": (
            "The Jobs page is your personalised job feed — here's how it works: 💼\n\n"
            "🔍 All active job postings from recruiters on the platform are listed\n"
            "📊 Each card shows YOUR personal match % based on your verified skill profile\n"
            "🎯 Jobs are sorted — highest match at the top, so best fits appear first\n"
            "🟢 Skills that match are shown in green; missing skills in red\n\n"
            "Matching Algorithm:\n"
            "We compare your verified skills (resume + GitHub confirmed) with the job's required skills. "
            "The overlap percentage becomes your match score for that role.\n\n"
            "Pro tip: Re-analyse your profile after adding a GitHub project — "
            "your match % on several jobs might jump significantly! 📈"
        )
    },

    # ── Recruiter features ───────────────────────────────────────────────────
    {
        "phrases": ["recruiter features", "i am a recruiter", "for recruiters",
                    "how does it work for recruiters", "recruiter dashboard",
                    "how to find candidates", "how to hire using placementiq",
                    "recruiter login", "view applicants", "rank applicants"],
        "keywords": ["recruiter", "recruiter", "employer", "hiring-manager", "hr", "candidates", "shortlist"],
        "response": (
            "PlacementIQ is a game-changer for recruiters! 👔\n\n"
            "Here's your full feature set:\n"
            "📝 Post Jobs — add title, description, and required skills\n"
            "🤖 Auto-ranking — applicants are instantly ranked by AI the moment they apply\n"
            "📊 Rich profiles — each applicant shows Readiness Score, Authenticity Score, "
            "Role Match %, GitHub stats, LeetCode activity\n"
            "🔍 Verified skills — no more taking resumes at face value; see real code evidence\n"
            "📋 Applicant list — paginated, sorted by score, with quick overview cards\n\n"
            "The result? Instead of manually screening 500 CVs, "
            "you see the top 10 highest-scoring candidates instantly. "
            "Better hires, faster decisions, zero guesswork. 🎯"
        )
    },

    # ── Posting a job ────────────────────────────────────────────────────────
    {
        "phrases": ["how to post a job", "post a job", "create a job listing",
                    "add a job posting", "how to create job", "publish job",
                    "post new job", "add new job"],
        "keywords": ["post", "create", "add", "publish", "listing-creation"],
        "response": (
            "Posting a job is quick and easy:\n\n"
            "1. Login as **Recruiter**\n"
            "2. Go to **Recruiter Dashboard** (top navigation)\n"
            "3. Click **Post New Job**\n"
            "4. Fill in: Job Title, Company, Description, and Required Skills\n"
            "   (Skills should be comma-separated, e.g. React, Node.js, MongoDB)\n"
            "5. Click **Submit**\n\n"
            "From that moment, any student who analyses their profile and has matching skills "
            "will see your job at the top of their feed. "
            "Applications flow in automatically — ranked by AI score! 🚀"
        )
    },

    # ── Pricing / free ───────────────────────────────────────────────────────
    {
        "phrases": ["is it free", "cost of using", "how much does it cost",
                    "do i have to pay", "is there a subscription", "pricing",
                    "free to use", "any fees", "is it paid", "free platform"],
        "keywords": ["free", "cost", "price", "pricing", "pay", "payment", "charge", "money", "subscription", "fees"],
        "response": (
            "PlacementIQ is 100% FREE — for both students AND recruiters! 🎉\n\n"
            "✅ No sign-up fees\n"
            "✅ No subscription plans\n"
            "✅ No premium tiers — all features are available to everyone\n"
            "✅ No credit card required, ever\n\n"
            "Our mission is to make skill-based, merit-driven hiring accessible to every student and recruiter. "
            "We believe opportunity should come from your talent, not your wallet. 💙"
        )
    },

    # ── Privacy / Security ───────────────────────────────────────────────────
    {
        "phrases": ["is my data safe", "data privacy", "privacy policy",
                    "is my resume safe", "who can see my profile",
                    "is my data sold", "data security", "how is data stored",
                    "confidentiality", "personal information"],
        "keywords": ["privacy", "safe", "security", "secure", "confidential", "protect", "stored", "personal-data"],
        "response": (
            "Your data is completely secure with us. 🔒\n\n"
            "Here's our privacy promise:\n"
            "🌐 GitHub & LeetCode — we ONLY access your PUBLIC profile data. "
            "We never ask for passwords or private repo access.\n"
            "📄 Resume — processed in memory for analysis, never stored permanently or shared.\n"
            "👁️ Profile visibility — recruiters can only see your profile when you actively apply to their job.\n"
            "🚫 We do NOT sell your data to anyone. Ever.\n"
            "🔐 All communication is encrypted (HTTPS).\n\n"
            "If you have specific privacy concerns, email us at privacy@placementiq.com "
            "and we'll address them directly."
        )
    },

    # ── Resume file formats ───────────────────────────────────────────────────
    {
        "phrases": ["what file formats", "resume format", "what type of resume",
                    "can i upload pdf", "pdf or docx", "supported file types",
                    "what files are accepted", "resume file size", "max file size",
                    "how to upload resume"],
        "keywords": ["pdf", "docx", "doc", "txt", "file", "format", "upload", "size", "mb"],
        "response": (
            "We accept the following resume formats:\n\n"
            "✅ PDF — recommended for best parsing accuracy\n"
            "✅ DOCX / DOC — Microsoft Word formats\n"
            "✅ TXT — plain text (limited formatting)\n\n"
            "📏 Maximum file size: 5 MB\n\n"
            "Tips for best results:\n"
            "📌 Use clear section headers: Skills, Projects, Education, Experience\n"
            "📌 List technologies explicitly (e.g. 'React.js, Node.js' not just 'web development')\n"
            "📌 Include project names with tech stacks used\n"
            "📌 Avoid image-heavy or two-column formats — they can confuse the parser\n\n"
            "A well-structured PDF resume with explicit skill names gives the most accurate results! 📄"
        )
    },

    # ── CGPA / Grades ────────────────────────────────────────────────────────
    {
        "phrases": ["does cgpa matter", "cgpa importance", "what if i have low cgpa",
                    "grades importance", "do grades matter", "cgpa required",
                    "low gpa", "poor academic record", "academic performance",
                    "will low grades hurt me"],
        "keywords": ["cgpa", "gpa", "grades", "marks", "academic", "percentage", "backlog", "low-grades"],
        "response": (
            "CGPA matters — but it's not everything! 🎓\n\n"
            "Here's the honest truth:\n"
            "📊 CGPA contributes only a small portion to your Readiness Score\n"
            "💻 Strong GitHub projects (5+ repos) + active LeetCode can easily overpower average grades\n"
            "🏆 Most recruiters on our platform care more about verified skills than GPA\n\n"
            "Real example:\n"
            "❌ Student A: CGPA 9.5, no GitHub, 10 LeetCode problems → Readiness: 42\n"
            "✅ Student B: CGPA 7.2, 12 GitHub projects, 180 LeetCode problems → Readiness: 81\n\n"
            "Student B wins every time. PlacementIQ is built for skill-first hiring. "
            "If you have low grades, invest that energy into GitHub projects and LeetCode — "
            "your score will reflect it! 💪"
        )
    },

    # ── No GitHub / No LeetCode ───────────────────────────────────────────────
    {
        "phrases": ["dont have github", "no github account", "no github", "without github",
                    "dont have leetcode", "no leetcode account", "no leetcode", "without leetcode",
                    "dont use github", "can i use without github",
                    "not on github", "not on leetcode",
                    "haven t github", "haven t leetcode"],
        "keywords": ["without-github", "no-github", "no-leetcode", "don-have"],
        "response": (
            "You can absolutely still use PlacementIQ without GitHub or LeetCode! 🙌\n\n"
            "Here's what happens:\n"
            "📄 Without GitHub → Your Authenticity Score will be lower "
            "since we can't verify skills through real projects. Skills will show as 'Claimed' not 'Verified'.\n"
            "💻 Without LeetCode → Your coding activity section shows as 'Unassessed'.\n\n"
            "Our strong recommendation:\n"
            "🐙 GitHub takes 5 minutes to create — even uploading college projects helps a lot!\n"
            "⌨️ 30–40 LeetCode Medium problems over 2 weeks makes a noticeable difference\n\n"
            "Both are completely free. The effort is genuinely worth it — "
            "students with active GitHub profiles get significantly more recruiter views! 📈"
        )
    },

    # ── Target Role ───────────────────────────────────────────────────────────
    {
        "phrases": ["which role should i choose", "best role for me", "target role",
                    "what role should i select", "role recommendation",
                    "what role suits me", "which career path", "role selection"],
        "keywords": ["role", "target", "suited", "career", "field", "path", "choose-role"],
        "response": (
            "Choosing the right target role is important — here's how to think about it:\n\n"
            "💡 Browse job listings first — see which roles naturally have your skills listed\n"
            "🎯 Pick a role where your current match % is highest as your primary target\n"
            "📊 You can also re-analyse with different roles to compare match scores\n\n"
            "Common roles on PlacementIQ:\n"
            "👨‍💻 Software Engineer, Frontend Developer, Backend Engineer, Full Stack Developer\n"
            "📊 Data Analyst, Data Scientist, ML Engineer\n"
            "☁️ DevOps Engineer, Cloud Engineer, SRE\n"
            "🔒 Cybersecurity Analyst, Security Engineer\n\n"
            "If you're unsure, choose the role closest to your strongest GitHub projects. "
            "Your current skill set usually tells you what you're already becoming! 🌟"
        )
    },

    # ── Improving scores ──────────────────────────────────────────────────────
    {
        "phrases": ["how to improve score", "increase readiness score", "boost my score",
                    "how to get higher score", "tips to improve", "how to improve profile",
                    "improve my readiness", "score improvement tips",
                    "how to score better", "increase my chances"],
        "keywords": ["increase", "boost", "improve", "higher", "better", "tips", "enhance"],
        "response": (
            "Here are the most effective ways to boost your scores: 🚀\n\n"
            "🔥 Top 5 score boosters:\n"
            "1. Build 2–3 GitHub projects using skills FROM your target role's job listings\n"
            "2. Solve 50+ LeetCode problems — aim for 40% Medium/Hard ratio\n"
            "3. Update your resume to clearly list technologies (specific names, not vague terms)\n"
            "4. Follow the personalized Learning Roadmap — each completed skill raises your match %\n"
            "5. Contribute to open-source projects on GitHub — huge authenticity signal\n\n"
            "⚡ Quick wins:\n"
            "✅ Add README files to your GitHub projects (shows communication skills)\n"
            "✅ Make sure GitHub username and resume skills align tightly\n"
            "✅ Re-analyse after every major update — scores reflect the latest data in real time!\n\n"
            "Consistent effort > one-time sprint. Students who spend 1 month following the roadmap "
            "see an average 25–35 point Readiness jump! 📈"
        )
    },

    # ── Analysis / Re-analysis ────────────────────────────────────────────────
    {
        "phrases": ["how long does analysis take", "how fast is the analysis",
                    "can i re-analyse", "re-run analysis", "update my profile",
                    "analysis time", "real time analysis", "when does score update"],
        "keywords": ["analysis", "analyse", "analyze", "re-analyse", "update", "refresh", "real-time"],
        "response": (
            "Analysis is near real-time! ⚡\n\n"
            "⏱️ Time breakdown:\n"
            "• Resume parsing: ~3–5 seconds\n"
            "• GitHub data fetch: ~5–10 seconds\n"
            "• LeetCode data fetch: ~2–4 seconds\n"
            "• Full scoring + roadmap generation: ~2–3 seconds\n"
            "Total: Usually under 30 seconds!\n\n"
            "Can I re-analyse?\n"
            "Absolutely! You can run a fresh analysis anytime. "
            "Did a new GitHub project? Solved more LeetCode? Updated resume? "
            "Re-analyse and your scores update immediately to reflect your latest profile. "
            "We always pull live data — nothing is cached from previous runs. 🔄"
        )
    },

    # ── Recruiter seeing applicants ────────────────────────────────────────────
    {
        "phrases": ["how do recruiters see applicants", "applicant ranking",
                    "how are applicants ranked", "recruiter view",
                    "what does recruiter see", "applicant list"],
        "keywords": ["applicants", "ranked", "ranking", "shortlist", "recruiter-view"],
        "response": (
            "When a student applies to your job listing, here's what you see as a recruiter: 👔\n\n"
            "📋 Applicant list — sorted by Readiness Score (highest first)\n"
            "Per applicant card:\n"
            "🔵 Readiness Score & Authenticity Score badges\n"
            "🟢 Role Match % specific to your job's required skills\n"
            "💻 GitHub repo count & LeetCode solve count\n"
            "🏷️ Skill tags showing verified vs claimed skills\n"
            "🎓 CGPA if provided\n\n"
            "You get an instant ranked shortlist the moment applications come in — "
            "no spreadsheets, no manual filtering, no CV guesswork. "
            "The AI does the pre-screening for you! 🤖"
        )
    },

    # ── Skill extraction from resume ──────────────────────────────────────────
    {
        "phrases": ["how do you extract skills", "skill extraction", "how does resume parsing work",
                    "how do you read my resume", "what does the ai extract",
                    "does it understand my resume"],
        "keywords": ["extract", "extraction", "parsing", "parse", "read-resume", "nlp"],
        "response": (
            "Resume parsing uses Natural Language Processing (NLP) to extract information! 🧠\n\n"
            "From your resume, we extract:\n"
            "🔧 Technical Skills — programming languages, frameworks, tools\n"
            "📁 Projects — project names and technologies mentioned\n"
            "🎓 Education — degree, institution, CGPA\n"
            "💼 Experience — job titles, companies, durations\n\n"
            "Then we cross-reference extracted skills with your GitHub repos and LeetCode stats "
            "to determine which skills are verified vs just claimed.\n\n"
            "For best results: list skills explicitly in a dedicated 'Skills' section "
            "using proper names like 'React.js', 'PostgreSQL', 'Docker' — not just 'full stack' or 'databases'. "
            "The clearer your resume, the higher your extraction accuracy! 📄"
        )
    },

    # ── What is a match % ────────────────────────────────────────────────────
    {
        "phrases": ["what is match percentage", "role match", "how is match calculated",
                    "what does match mean", "80 percent match", "match score",
                    "job compatibility", "how compatible am i"],
        "keywords": ["match", "percentage", "compatibility", "fit", "suitable", "overlap"],
        "response": (
            "Role Match % shows how well YOUR verified skills overlap with a job's requirements. 🎯\n\n"
            "How it's calculated:\n"
            "1. Recruiter posts job with required skills: [Python, TensorFlow, SQL, Docker]\n"
            "2. You have verified: [Python ✅, SQL ✅] — missing [TensorFlow ❌, Docker ❌]\n"
            "3. Match = 2 out of 4 = 50%\n\n"
            "Match % ranges:\n"
            "🟢 80–100%: Excellent fit — apply with confidence!\n"
            "🟡 50–79%: Good fit — consider closing 1–2 skill gaps first\n"
            "🔴 Below 50%: Work on roadmap before applying\n\n"
            "Note: We only count VERIFIED skills (backed by GitHub) as full matches. "
            "Claimed-only skills count as partial. Real code beats claims every time! 💪"
        )
    },

    # ── Technical issues ──────────────────────────────────────────────────────
    {
        "phrases": ["not working", "page not loading", "error on page", "something is broken",
                    "analysis failed", "github not loading", "leetcode not loading",
                    "bug report", "technical issue", "website down"],
        "keywords": ["error", "broken", "bug", "issue", "loading", "failed", "crash"],
        "response": (
            "Sorry to hear you're facing an issue! 😟 Let's fix it:\n\n"
            "Common fixes:\n"
            "🔄 Refresh the page and try again\n"
            "🌐 Check your internet connection\n"
            "📝 Make sure your GitHub / LeetCode username is typed correctly (case-sensitive!)\n"
            "📄 Ensure your resume is under 5 MB and in PDF/DOCX format\n"
            "🔒 Make sure your GitHub profile is public (private profiles can't be scanned)\n\n"
            "Still having trouble?\n"
            "📧 Email us at support@placementiq.com with:\n"
            "• What you were trying to do\n"
            "• What error message you saw\n"
            "• Your GitHub/LeetCode username (if relevant)\n\n"
            "We'll get back to you within 24 hours! 🙏"
        )
    },

    # ── Contact / Support ────────────────────────────────────────────────────
    {
        "phrases": ["contact support", "how to contact", "reach the team",
                    "customer support", "help desk", "speak to someone",
                    "report feedback", "give feedback", "suggest feature"],
        "keywords": ["contact", "support", "email", "feedback", "suggest", "team", "helpdesk"],
        "response": (
            "Need to reach us? Here's how: 📬\n\n"
            "📧 General enquiries: hello@placementiq.com\n"
            "🐛 Bug reports: support@placementiq.com\n"
            "💡 Feature suggestions: feedback@placementiq.com\n\n"
            "We're a small but passionate team committed to improving campus hiring. "
            "We read every piece of feedback and typically respond within 24 hours on weekdays.\n\n"
            "Or just keep chatting with me — I can probably answer your question right here! 😊"
        )
    },

    # ── Difference from LinkedIn, Naukri, etc. ────────────────────────────────
    {
        "phrases": ["how is this different from linkedin", "compare with naukri",
                    "different from other platforms", "why use placementiq",
                    "why not just use linkedin", "vs linkedin", "vs naukri",
                    "what makes this unique", "why is this better"],
        "keywords": ["linkedin", "naukri", "different", "compare", "unique", "better", "vs"],
        "response": (
            "Great question! Here's how PlacementIQ stands apart from LinkedIn, Naukri, etc.: 🆚\n\n"
            "Traditional platforms:\n"
            "❌ You write whatever skills you want — no verification\n"
            "❌ Recruiters can't tell if you actually know what you claim\n"
            "❌ Based on connections & endorsements, not real evidence\n"
            "❌ No coding activity signal\n\n"
            "PlacementIQ:\n"
            "✅ Skills VERIFIED through GitHub code analysis\n"
            "✅ Coding proficiency measured via LeetCode\n"
            "✅ AI-generated scores replace guesswork\n"
            "✅ Recruiters get ranked shortlists, not unsorted stacks of CVs\n"
            "✅ Built specifically for campus/fresher hiring in India\n\n"
            "It's not a directory — it's a real-time skill intelligence platform. "
            "Your GitHub and LeetCode tell a truer story than any resume ever can! 🚀"
        )
    },

    # ── Student benefits ──────────────────────────────────────────────────────
    {
        "phrases": ["benefits for students", "why should i use this", "how does this help me",
                    "what do i gain", "is it useful", "should i use placementiq",
                    "advantages of using"],
        "keywords": ["benefit", "benefits", "advantage", "useful", "gain", "help", "value"],
        "response": (
            "Here's exactly how PlacementIQ benefits YOU as a student: 🎓\n\n"
            "📊 Know where you stand — see your actual job-readiness score before applying\n"
            "🔍 Identify blind spots — discover skill gaps you didn't know you had\n"
            "🗺️ Get a clear plan — personalised roadmap tells you exactly what to learn next\n"
            "💼 Find relevant jobs — listings are matched to YOUR specific skill profile\n"
            "🏆 Stand out to recruiters — apply with an AI-backed, verified profile\n"
            "⏰ Save time — no more applying to 100 jobs hoping one sticks\n"
            "💰 It's FREE — no cost, ever\n\n"
            "Think of it as a career coach + portfolio analyser + job board — all in one. "
            "Students who use PlacementIQ land interviews 3× faster than those who just send CVs. 💪"
        )
    },

    # ── Thank you ────────────────────────────────────────────────────────────
    {
        "phrases": ["thank you", "thanks a lot", "thanks so much", "that was helpful",
                    "great answer", "awesome", "perfect", "that helped",
                    "very useful", "love this bot", "you're great"],
        "keywords": ["thanks", "thank", "awesome", "great", "helpful", "perfect", "wonderful", "loved", "nice"],
        "response": (
            "You're very welcome! 🚀 I'm glad that helped.\n\n"
            "Feel free to ask me anything else — I'm available 24/7. "
            "Best of luck with your placement journey! "
            "You've got this. 💪✨"
        )
    },

    # ── Bye / End conversation ─────────────────────────────────────────────────
    {
        "phrases": ["bye", "goodbye", "see you", "see ya", "take care", "cya", "quit", "exit"],
        "keywords": ["bye", "goodbye", "see-you", "cya"],
        "response": (
            "Goodbye! 👋 All the best with your placement journey. "
            "Come back anytime you have questions — I'll be right here. Good luck! 🍀"
        )
    },
]

# Fallback response
DEFAULT_RESPONSE = (
    "Hmm, I'm not sure I have a specific answer for that — but I'm learning! 🤔\n\n"
    "I'm best at answering questions about:\n"
    "📊 Readiness & Authenticity scores\n"
    "🐙 GitHub & LeetCode integration\n"
    "💼 Jobs, matching & applying\n"
    "🗺️ Skill gaps & learning roadmap\n"
    "👔 Recruiter features\n"
    "💰 Pricing, privacy & file formats\n\n"
    "Try rephrasing your question, or ask something like:\n"
    "• 'How does GitHub integration work?'\n"
    "• 'What is a readiness score?'\n"
    "• 'How do I apply for a job?'"
)

# Stop words (excluded from keyword matching to prevent false positives)
STOP_WORDS = {
    'the','a','an','is','are','am','was','were','be','been','being',
    'to','of','and','or','for','in','on','at','by','with','from','into',
    'this','that','these','those','it','its','i','me','my','we','our',
    'you','your','he','she','they','their','them',
    'can','could','do','does','did','will','would','should','shall','may','might',
    'have','has','had','not','no','so','if','then','than','when',
    'what','which','who','whom','whose','where','why','how',
    'tell','explain','describe','give','show','let','know','want',
    'about','please','just','some','any','all','more','also','too',
    'really','very','much','many','most','few','little','own','same',
    'get','got','make','made','need','use','using','used',
}


def get_bot_response(user_message: str) -> str:
    """
    Priority 1: Exact phrase/substring match
    Priority 2: Weighted specific-keyword scoring
    Priority 3: Fuzzy similarity on topic keywords
    Fallback: DEFAULT_RESPONSE
    """
    try:
        if not user_message or not user_message.strip():
            return (
                "Hi! I'm your PlacementIQ assistant. Ask me anything about "
                "scores, GitHub integration, jobs, roadmaps, or recruiter features!"
            )

        raw = user_message.strip().lower()
        cleaned = re.sub(r"[^\w\s]", " ", raw)

        # ── Priority 1: phrase substring match ─────────────────────────────
        for item in KNOWLEDGE_BASE:
            for phrase in item["phrases"]:
                if phrase in cleaned:
                    return item["response"]

        # ── Priority 2: specific keyword scoring ───────────────────────────
        user_words = set(re.findall(r'\w+', cleaned)) - STOP_WORDS

        best_match = None
        best_score = 0

        for item in KNOWLEDGE_BASE:
            specific_kws = set(item["keywords"])
            score = len(user_words & specific_kws)
            if score > best_score:
                best_score = score
                best_match = item["response"]

        if best_score > 0:
            return best_match

        # ── Priority 3: fuzzy similarity on keywords ────────────────────────
        for item in KNOWLEDGE_BASE:
            for kw in item["keywords"]:
                for word in user_words:
                    if len(word) < 4:
                        continue
                    ratio = SequenceMatcher(None, word, kw).ratio()
                    if ratio >= 0.78:
                        return item["response"]

        return DEFAULT_RESPONSE

    except Exception:
        return (
            "I'm here to help! Ask me about PlacementIQ scores, "
            "GitHub integration, job matching, or roadmaps. 😊"
        )
