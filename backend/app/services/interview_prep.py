"""Interview prep plan for an application: the hiring process to expect, what to study (with free, reputable
resources), likely technical and behavioral questions, stories from YOUR resume to answer them with, the gaps
to close first, questions to ask, and a day-by-day plan you can tick off.

Built from the job description, your resume and your ATS match — deterministic, so it works without AI.
With an AI model connected, it adds questions written for this specific posting. Company notes are limited to
what the company publishes about its own hiring (linked), and everything else is described as typical, not
as a promise about this employer's process.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from . import ats, llm
from .textutil import pretty_skill, seniority_of

# ------------------------------------------------------------------ general resources (free, well known)
R = {
    "tih": ("Tech Interview Handbook — free guide to coding interviews, behavioral and negotiation", "https://www.techinterviewhandbook.org/"),
    "neetcode": ("NeetCode 150 — the most common coding-interview problems, by pattern, with video solutions", "https://neetcode.io/practice"),
    "lc150": ("LeetCode Top Interview 150 — study plan", "https://leetcode.com/studyplan/top-interview-150/"),
    "sdp": ("System Design Primer — free, open-source system design course", "https://github.com/donnemartin/system-design-primer"),
    "lcsql": ("LeetCode Top SQL 50 — SQL interview practice", "https://leetcode.com/studyplan/top-sql-50/"),
    "sqlbolt": ("SQLBolt — interactive SQL lessons", "https://sqlbolt.com/"),
    "star": ("Tech Interview Handbook — behavioral interviews and the STAR format", "https://www.techinterviewhandbook.org/behavioral-interview/"),
    "mlprimer": ("Google's Machine Learning Crash Course", "https://developers.google.com/machine-learning/crash-course"),
    "statquest": ("StatQuest — statistics and ML explained clearly (YouTube)", "https://www.youtube.com/@statquest"),
    "pramp": ("Pramp — free peer mock interviews", "https://www.pramp.com/"),
    "ddia": ("Designing Data-Intensive Applications (book) — the standard text for backend/system design", "https://dataintensive.net/"),
}

# ------------------------------------------------------------------ role families and the processes typical for them
FAMILIES = [
    ("ml_eng", r"machine learning|\bml\b|\bai\b engineer|applied scientist|research engineer|deep learning|\bllm\b|computer vision|nlp"),
    ("data_sci", r"data scientist|decision scientist|quantitative analyst|research scientist"),
    ("data_eng", r"data engineer|analytics engineer|etl|big data"),
    ("analyst", r"data analyst|business analyst|bi analyst|business intelligence|reporting analyst|analytics analyst"),
    ("devops", r"devops|site reliability|\bsre\b|platform engineer|infrastructure engineer|cloud engineer|production engineer"),
    ("security", r"security engineer|application security|appsec|cyber|penetration|soc analyst"),
    ("mobile", r"\bios\b|android|mobile engineer|mobile developer|react native|flutter"),
    ("qa", r"\bqa\b|quality assurance|test engineer|sdet|automation engineer"),
    ("pm", r"product manager|program manager|technical program|\btpm\b|product owner"),
    ("swe", r"software|developer|engineer|backend|back-end|frontend|front-end|full[- ]?stack|programmer|sde\b"),
]
FAMILY_NAMES = {"swe": "Software engineering", "ml_eng": "Machine learning engineering", "data_sci": "Data science",
                "data_eng": "Data engineering", "analyst": "Data / business analysis", "devops": "DevOps / SRE / platform",
                "security": "Security engineering", "mobile": "Mobile engineering", "qa": "QA / test automation",
                "pm": "Product / program management", "other": "General"}


def family_of(title: str, jd: str) -> str:
    t = (title or "").lower()
    for fam, rx in FAMILIES:
        if re.search(rx, t):
            return fam
    j = (jd or "").lower()[:3000]
    for fam, rx in FAMILIES[:-1]:
        if re.search(rx, j):
            return fam
    return "swe" if re.search(r"engineer|developer", j) else "other"


def level_of(title: str, years_required: Optional[int]) -> str:
    lvl = seniority_of(title or "")
    t = (title or "").lower()
    if re.search(r"intern|new grad|graduate|entry|junior|\bjr\b|associate|\bi\b$|engineer i\b|university", t) or (lvl is not None and lvl <= 1):
        return "entry"
    if re.search(r"senior|\bsr\b|staff|principal|lead|architect|\biii\b|\biv\b", t) or (years_required or 0) >= 5:
        return "senior"
    return "mid"


def stages_for(fam: str, level: str) -> list[dict]:
    """The rounds most companies use for this kind of role (what each tests and how to do well)."""
    recruiter = {"name": "Recruiter screen", "length": "20–30 min",
                 "what": "Your background, why this role/company, location, work authorization, salary expectations and timeline.",
                 "how": "Have a 60-second pitch tied to the posting, know your salary range, and ask about the interview steps."}
    behavioral = {"name": "Behavioral / culture interview", "length": "30–60 min (often part of every round)",
                  "what": "Past situations: teamwork, conflict, ownership, failure, ambiguity, impact.",
                  "how": "Answer with STAR (Situation, Task, Action, Result), with a number in the result. Use the stories listed below."}
    hm = {"name": "Hiring manager conversation", "length": "30–45 min",
          "what": "How you work, your projects in depth, what you'd do in the first months.",
          "how": "Go deep on 2 projects from your resume: your decisions, trade-offs and what you'd do differently."}
    if fam in ("swe", "mobile", "qa", "security", "devops", "ml_eng", "data_eng"):
        oa = {"name": "Online assessment", "length": "60–90 min, 2–3 problems",
              "what": "Timed coding problems on a platform like HackerRank or CodeSignal; sometimes multiple-choice or a debugging task.",
              "how": "Practice timed problems on arrays, strings, hash maps, two pointers, BFS/DFS. Read all problems first; pass the basic tests before optimizing."}
        phone = {"name": "Technical phone screen", "length": "45–60 min",
                 "what": "One or two coding problems in a shared editor, explained out loud.",
                 "how": "Clarify the problem, give a brute-force idea, then optimize; talk through complexity and test with an example."}
        loop = {"name": "Final round (virtual or onsite loop)", "length": "3–5 interviews of 45–60 min",
                "what": "More coding" + (", system design" if level != "entry" else "") +
                        {"devops": ", Linux/networking/troubleshooting and infrastructure design",
                         "ml_eng": ", ML fundamentals and ML system design",
                         "data_eng": ", SQL and data pipeline / data modeling design",
                         "security": ", threat modeling and security scenarios",
                         "mobile": ", mobile app architecture and platform specifics",
                         "qa": ", test strategy and automation framework design"}.get(fam, "") + ", and behavioral.",
                "how": "Treat each round as a conversation; keep solutions readable, test them, and connect design choices to scale and reliability."}
        out = [recruiter, oa, phone, loop, behavioral]
        if fam == "devops":
            out.insert(3, {"name": "Practical / troubleshooting exercise", "length": "45–90 min",
                           "what": "Debug a broken service, write a small script or Terraform/Kubernetes config, or walk through an incident.",
                           "how": "Narrate your debugging: check logs, metrics, recent changes, then narrow down. Practice on a small cluster."})
        return out
    if fam in ("data_sci", "analyst"):
        return [recruiter,
                {"name": "SQL / technical screen", "length": "45–60 min",
                 "what": "SQL queries (joins, GROUP BY, window functions), sometimes Python/pandas.",
                 "how": "Practice joins, aggregations, window functions (ROW_NUMBER, LAG) and CTEs until they're automatic."},
                {"name": "Take-home or case study", "length": "2–6 hours / 45–60 min live",
                 "what": "Analyze a dataset or a business problem and present findings" + (" and a model" if fam == "data_sci" else "") + ".",
                 "how": "State assumptions, show the metric you'd use, keep charts simple and end with a recommendation."},
                {"name": "Final round", "length": "3–4 interviews",
                 "what": ("Statistics, experiments/A-B testing, ML fundamentals, " if fam == "data_sci" else "Metrics, dashboards, ") +
                         "product sense and behavioral.",
                 "how": "Explain trade-offs in plain language; tie every analysis to a decision."},
                behavioral]
    if fam == "pm":
        return [recruiter, {"name": "Product sense / design", "length": "45 min", "what": "Design or improve a product for a user group.",
                            "how": "Users → pain points → prioritized solutions → success metrics."},
                {"name": "Execution / metrics", "length": "45 min", "what": "Define and debug metrics, prioritize, make trade-offs.",
                 "how": "Pick one north-star metric and supporting metrics; reason about causes of a metric change."},
                {"name": "Technical / estimation", "length": "45 min", "what": "How systems work, estimates, working with engineers.",
                 "how": "Explain an architecture you know at a high level; structure estimates clearly."}, behavioral, hm]
    return [recruiter, hm, {"name": "Skills interview", "length": "45–60 min", "what": "The core skills listed in the posting.",
                            "how": "Prepare examples for each requirement in the posting."}, behavioral]


# ------------------------------------------------------------------ skill-by-skill topics, questions and resources
SKILLS: dict[str, dict] = {
    "dsa": {"label": "Data structures & algorithms", "topics": ["Arrays & strings", "Hash maps & sets", "Two pointers & sliding window",
            "Stacks & queues", "Trees & BFS/DFS", "Graphs", "Heaps", "Binary search", "Dynamic programming basics", "Big-O analysis"],
            "questions": ["Two Sum / find pairs with a target sum", "Longest substring without repeating characters", "Merge intervals",
                          "Number of islands (grid BFS/DFS)", "Top K frequent elements (heap)", "LRU cache design",
                          "Validate a binary search tree", "Course schedule (topological sort)"],
            "resources": ["neetcode", "lc150", "tih"]},
    "system design": {"label": "System design", "topics": ["Requirements & estimates", "APIs & data model", "Load balancing", "Caching",
                      "Databases: SQL vs NoSQL, indexing, replication, sharding", "Queues & async processing", "Consistency & availability",
                      "Rate limiting", "Observability"],
                      "questions": ["Design a URL shortener", "Design a rate limiter", "Design a news feed", "Design a notification system",
                                    "Design a chat service", "How would you scale this service to 10× traffic?"],
                      "resources": ["sdp", "ddia"]},
    "python": {"label": "Python", "topics": ["Lists/dicts/sets & comprehensions", "Generators & iterators", "Decorators & context managers",
               "OOP & dataclasses", "Exceptions", "The GIL, threads vs async", "Testing with pytest"],
               "questions": ["Difference between a list and a tuple; when to use each?", "What does a decorator do? Write a timing decorator.",
                             "How do generators save memory?", "Explain the GIL and when to use multiprocessing vs asyncio."],
               "resources": [("Official Python tutorial", "https://docs.python.org/3/tutorial/")]},
    "java": {"label": "Java", "topics": ["OOP & SOLID", "Collections (HashMap internals)", "Exceptions", "Generics", "Streams & lambdas",
             "Concurrency (threads, ExecutorService, synchronized)", "JVM memory & GC basics"],
             "questions": ["How does HashMap work internally?", "== vs equals() and hashCode()", "Checked vs unchecked exceptions",
                           "How do you make a class thread-safe?", "What changed in Java 8+ that you use daily?"],
             "resources": [("Dev.java — official Java learning", "https://dev.java/learn/")]},
    "javascript": {"label": "JavaScript / TypeScript", "topics": ["Closures & scope", "this & prototypes", "Promises & async/await",
                   "Event loop", "TypeScript types & generics"],
                   "questions": ["Explain closures with an example", "How does the event loop handle promises vs setTimeout?",
                                 "Implement debounce", "interface vs type in TypeScript"],
                   "resources": [("MDN JavaScript Guide", "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide"),
                                 ("TypeScript Handbook", "https://www.typescriptlang.org/docs/handbook/intro.html")]},
    "react": {"label": "React", "topics": ["Components & props", "State & hooks", "Effects & data fetching", "Rendering & memoization",
              "Forms & accessibility"],
              "questions": ["When does a component re-render?", "useEffect dependencies — common bugs", "useMemo vs useCallback",
                            "How would you structure state for a large form?"],
              "resources": [("react.dev — official React docs", "https://react.dev/learn")]},
    "node.js": {"label": "Node.js", "topics": ["Event loop & non-blocking I/O", "Express/REST APIs", "Streams", "Error handling", "Scaling (cluster/workers)"],
                "questions": ["Why is Node good for I/O-heavy services?", "How do you handle errors in async middleware?",
                              "How would you stream a large file to the client?"],
                "resources": [("Node.js — Learn", "https://nodejs.org/en/learn")]},
    "sql": {"label": "SQL", "topics": ["Joins", "GROUP BY & HAVING", "Window functions", "CTEs & subqueries", "Indexes & query plans",
            "Transactions & isolation"],
            "questions": ["Second highest salary per department", "Users active 3 days in a row (window functions)",
                          "INNER vs LEFT JOIN results", "Why is this query slow, and which index would help?"],
            "resources": ["lcsql", "sqlbolt"]},
    "aws": {"label": "AWS", "topics": ["EC2, S3, IAM", "VPC basics", "RDS/DynamoDB", "Lambda & serverless", "CloudWatch", "Well-Architected pillars"],
            "questions": ["How would you deploy a web app on AWS with high availability?", "IAM roles vs users", "S3 vs EBS vs EFS",
                          "When would you choose Lambda over containers?"],
            "resources": [("AWS Well-Architected Framework", "https://aws.amazon.com/architecture/well-architected/")]},
    "azure": {"label": "Azure", "topics": ["App Service & Functions", "AKS", "Storage & Cosmos DB", "Azure DevOps pipelines", "Monitoring"],
              "questions": ["How would you set up CI/CD to AKS with Azure DevOps?", "Azure Functions vs App Service", "How do you secure secrets (Key Vault)?"],
              "resources": [("Microsoft Learn — Azure", "https://learn.microsoft.com/en-us/training/azure/")]},
    "kubernetes": {"label": "Kubernetes", "topics": ["Pods, Deployments, Services", "ConfigMaps & Secrets", "Probes", "Autoscaling",
                   "Ingress", "Debugging (kubectl logs/describe)"],
                   "questions": ["A pod is in CrashLoopBackOff — how do you debug it?", "Deployment vs StatefulSet",
                                 "Liveness vs readiness probes", "How does a Service route traffic to pods?"],
                   "resources": [("Kubernetes tutorials (official)", "https://kubernetes.io/docs/tutorials/")]},
    "docker": {"label": "Docker", "topics": ["Images vs containers", "Dockerfile best practices", "Layers & caching", "Networking & volumes", "Compose"],
               "questions": ["How do you make an image smaller?", "CMD vs ENTRYPOINT", "How do containers differ from VMs?"],
               "resources": [("Docker — Get started", "https://docs.docker.com/get-started/")]},
    "kafka": {"label": "Kafka / messaging", "topics": ["Topics, partitions, offsets", "Consumer groups", "Delivery guarantees", "Ordering", "Retention"],
              "questions": ["How does Kafka guarantee ordering?", "At-least-once vs exactly-once", "How do consumer groups scale?"],
              "resources": [("Apache Kafka documentation", "https://kafka.apache.org/documentation/")]},
    "spring boot": {"label": "Spring Boot", "topics": ["Dependency injection", "REST controllers", "Spring Data JPA", "Transactions", "Testing"],
                    "questions": ["How does dependency injection work in Spring?", "@Component vs @Bean", "How do you handle transactions?",
                                  "How do you secure a REST API in Spring?"],
                    "resources": [("Spring guides (official)", "https://spring.io/guides")]},
    "microservices": {"label": "Microservices & APIs", "topics": ["REST design", "Service boundaries", "Sync vs async communication",
                      "Idempotency & retries", "API versioning", "Distributed tracing"],
                      "questions": ["How do you design an idempotent payment API?", "Monolith vs microservices trade-offs",
                                    "How do services handle a dependency that's down?", "How would you version an API?"],
                      "resources": ["sdp"]},
    "ci/cd": {"label": "CI/CD", "topics": ["Pipelines & stages", "Testing strategy", "Blue/green & canary deploys", "Rollbacks", "Infrastructure as code"],
              "questions": ["Walk me through a pipeline you built", "How do you deploy with zero downtime?", "How do you roll back a bad release?"],
              "resources": [("GitHub Actions documentation", "https://docs.github.com/en/actions")]},
    "terraform": {"label": "Terraform", "topics": ["State & backends", "Modules", "Plan/apply workflow", "Drift"],
                  "questions": ["How do you manage Terraform state in a team?", "What happens when someone changes infra by hand?"],
                  "resources": [("Terraform tutorials (HashiCorp)", "https://developer.hashicorp.com/terraform/tutorials")]},
    "linux": {"label": "Linux & networking", "topics": ["Processes & signals", "File permissions", "Networking: DNS, TCP, HTTP", "Debugging tools"],
              "questions": ["What happens when you type a URL in the browser?", "How do you find what's using a port?", "A server is slow — where do you look?"],
              "resources": [("Linux Journey", "https://linuxjourney.com/")]},
    "machine learning": {"label": "Machine learning", "topics": ["Bias/variance", "Regularization", "Metrics (precision/recall/AUC)",
                         "Feature engineering", "Tree models vs neural nets", "Model deployment & monitoring"],
                         "questions": ["How do you handle an imbalanced dataset?", "Precision vs recall — when does each matter?",
                                       "How do you detect overfitting?", "How would you deploy and monitor a model?"],
                         "resources": ["mlprimer", "statquest"]},
    "deep learning": {"label": "Deep learning / LLMs", "topics": ["Backprop & optimizers", "CNNs/transformers", "Fine-tuning", "Embeddings & RAG", "Evaluation"],
                      "questions": ["Explain attention in transformers", "Fine-tuning vs RAG — when to use each?", "How do you evaluate an LLM feature?"],
                      "resources": [("Dive into Deep Learning (free book)", "https://d2l.ai/")]},
    "statistics": {"label": "Statistics & experiments", "topics": ["Distributions", "Hypothesis tests & p-values", "Confidence intervals", "A/B test design", "Power & sample size"],
                   "questions": ["Explain a p-value to a non-technical person", "How do you design an A/B test?", "What if the test is inconclusive?"],
                   "resources": ["statquest"]},
    "spark": {"label": "Spark & data pipelines", "topics": ["Transformations vs actions", "Partitioning & shuffles", "Joins at scale", "Batch vs streaming", "Data quality"],
              "questions": ["Why is this Spark job slow?", "How do you handle late-arriving data?", "Design a daily ETL with retries"],
              "resources": [("Apache Spark documentation", "https://spark.apache.org/docs/latest/")]},
    "git": {"label": "Git", "topics": ["Branching", "Rebase vs merge", "Resolving conflicts"], "questions": ["Rebase vs merge?", "How do you undo a pushed commit?"],
            "resources": [("Pro Git (free book)", "https://git-scm.com/book/en/v2")]},
}
ALIAS = {"typescript": "javascript", "javascript": "javascript", "node": "node.js", "nodejs": "node.js", "express": "node.js",
         "postgresql": "sql", "mysql": "sql", "sql server": "sql", "oracle": "sql", "snowflake": "sql", "bigquery": "sql",
         "gcp": "aws", "google cloud": "aws", "lambda": "aws", "k8s": "kubernetes", "helm": "kubernetes", "jenkins": "ci/cd",
         "github actions": "ci/cd", "azure devops": "ci/cd", "rest apis": "microservices", "rest": "microservices", "graphql": "microservices",
         "rabbitmq": "kafka", "sqs": "kafka", "pytorch": "deep learning", "tensorflow": "deep learning", "llm": "deep learning",
         "nlp": "deep learning", "generative ai": "deep learning", "scikit-learn": "machine learning", "pandas": "python", "numpy": "python",
         "airflow": "spark", "databricks": "spark", "hadoop": "spark", "etl": "spark", "dbt": "sql", "ansible": "terraform",
         "next.js": "react", "angular": "javascript", "vue.js": "javascript", "spring": "spring boot", "a/b testing": "statistics",
         "distributed systems": "system design", "scalability": "system design"}

BEHAVIORAL = [
    ("impact", "Tell me about a project you're most proud of.", r"\d+\s?%|\d+[kKmM]\+?\s|improv\w+ \w+ by|increas|reduc|launch|grew"),
    ("challenge", "Describe a hard technical problem you solved.", r"optimi|migrat|debug|resolv|scal|performance|latency|refactor"),
    ("ownership", "Tell me about a time you took ownership beyond your role.", r"automat|\bown|initiat|\bled\b|set up|introduc|proactive"),
    ("teamwork", "Tell me about working with people from other teams (cross-functional).", r"collaborat|cross-functional|stakeholder|partner"),
    ("mentoring", "Tell me about helping someone else grow.", r"\bmentor|\btrain(?:ed|ing)\b|\bcoach|\bonboard|knowledge sharing"),
    ("failure", "Tell me about a time something went wrong. What did you learn?", r"incident|issue|fail|bug|outage|troubleshoot|monitor"),
    ("deadline", "Tell me about working under a tight deadline.", r"release|sprint|on-time|deadline|deliver|agile"),
    ("ambiguity", "Tell me about a time requirements were unclear.", r"migrat|legacy|requirement|prototype|from scratch|end-to-end"),
    ("conflict", "Tell me about a disagreement with a teammate and how you resolved it.", r"disagree|conflict|align|negotiat|code review|feedback"),
]

ASK_THEM = [
    "What does success look like in this role after 3 and 6 months?",
    "What's the biggest challenge the team is working on right now?",
    "How does the team plan and prioritize work, and how are decisions made?",
    "How is code reviewed and deployed? How often do you release?",
    "How do you support learning and growth for people in this role?",
    "What are the next steps in the process, and when should I expect to hear back?",
]

# What companies publish about their own hiring (official pages). Only general, publicly stated points.
COMPANIES = {
    "amazon": {"name": "Amazon", "url": "https://www.amazon.jobs/content/en/how-we-hire",
               "notes": ["Amazon's interviews are built around its Leadership Principles — prepare 1–2 STAR stories for each.",
                         "Expect behavioral questions in most rounds, alongside the technical ones."]},
    "aws": {"alias": "amazon"},
    "google": {"name": "Google", "url": "https://www.google.com/about/careers/applications/interview-tips/",
               "notes": ["Google publishes interview tips for its process — read them before your first technical round."]},
    "microsoft": {"name": "Microsoft", "url": "https://careers.microsoft.com/v2/global/en/hiring-tips/interview-tips.html",
                  "notes": ["Microsoft publishes interview tips covering its process — read them before your interviews."]},
    "spotify": {"name": "Spotify", "url": "https://www.lifeatspotify.com/start-your-journey", "notes": ["Spotify describes its hiring steps on its careers site."]},
}


def _res(x) -> dict:
    t, u = R[x] if isinstance(x, str) else x
    return {"title": t, "url": u}


def _skill_key(term: str) -> Optional[str]:
    t = term.lower().strip()
    if t in SKILLS:
        return t
    return ALIAS.get(t)


def _bullets(resume_text: str) -> list[str]:
    """Bullet points from the resume text (a bullet plus its wrapped continuation lines)."""
    out, cur = [], None
    for raw in (resume_text or "").splitlines():
        line = raw.strip()
        m = re.match(r"^[•\-–▪●◦*]\s*(.+)$", line)
        if m:
            if cur:
                out.append(cur)
            cur = m.group(1)
        elif cur is not None and line and line[0].islower():
            cur += " " + line  # wrapped line of the same bullet
        else:
            if cur:
                out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    out = [re.sub(r"\s+", " ", b).strip() for b in out]
    return [b for b in out if 40 <= len(b) <= 450 and not re.search(r"technologies used|vol\.|pp\.|issue \d", b, re.I)]


def _stories(resume_text: str) -> list[dict]:
    """Bullets from your resume that make good interview stories, matched to common behavioral questions."""
    bullets = _bullets(resume_text)
    out, used = [], set()
    for theme, q, rx in BEHAVIORAL:
        cands = [b for b in bullets if re.search(rx, b, re.I) and b not in used]
        cands.sort(key=lambda b: (not re.search(r"\d", b), -len(b)))  # results with numbers first
        if cands:
            used.add(cands[0])
            out.append({"theme": theme, "question": q, "story": cands[0][:300],
                        "tip": "Situation & task in 1–2 sentences, then what YOU did (3–4 steps), then the result" +
                               (" — lead with the number." if re.search(r"\d", cands[0]) else " — add a measurable outcome if you can.")})
        else:
            out.append({"theme": theme, "question": q, "story": "", "tip": "No matching example in your resume — think of one from work, school or projects."})
    return out


def build(job, resume_text: str, assessment: Optional[dict] = None, interviews: Optional[list] = None) -> dict:
    jd = job.description_text or ""
    fam = family_of(job.title, jd)
    years = ats.required_years(jd)
    level = level_of(job.title, years)
    kws = ats.extract_keywords(jd, job.company)
    hard = [k for k in kws if k.kind == "hard"]
    have = (resume_text or "").lower()
    focus: list[dict] = []
    seen: set[str] = set()

    def add(key: str, why: str, priority: str):
        if key in seen:
            for f in focus:  # the posting asks for it explicitly: raise its priority
                if f["key"] == key and priority == "high" and f["priority"] != "high":
                    f["priority"], f["why"] = "high", why
            return
        if key not in SKILLS:
            return
        seen.add(key)
        s = SKILLS[key]
        focus.append({"key": key, "label": s["label"], "why": why, "priority": priority, "topics": s["topics"],
                      "questions": s["questions"], "resources": [_res(r) for r in s["resources"]]})

    if fam in ("swe", "mobile", "ml_eng", "data_eng", "devops", "security", "qa"):
        add("dsa", "Coding rounds and online assessments use these patterns for almost every engineering role.", "high")
    if level != "entry" and fam in ("swe", "ml_eng", "data_eng", "devops", "mobile"):
        add("system design", f"{'Senior' if level == 'senior' else 'Mid-level'} roles usually include a design round.", "high" if level == "senior" else "medium")
    for k in hard:
        key = _skill_key(k.term)
        if not key:
            continue
        missing = not ats.has_term(have, k.term)
        why = ("Required in the posting" if k.required else "Mentioned in the posting") + \
              (" — and it isn't in your resume, so review it first." if missing else " — expect questions on how you've used it.")
        add(key, why, "high" if (k.required and missing) or k.required else "medium")
    if fam in ("data_sci", "analyst", "data_eng"):
        add("sql", "Data roles almost always include a SQL round.", "high")
    if fam == "data_sci":
        add("statistics", "Data science interviews test statistics and experiment design.", "high")
        add("machine learning", "Expect ML fundamentals questions.", "medium")
    if fam == "ml_eng":
        add("machine learning", "Core of the role.", "high")
    order = {"high": 0, "medium": 1, "low": 2}
    focus.sort(key=lambda f: order[f["priority"]])

    gaps = []
    if assessment:
        for t in (assessment.get("breakdown", {}).get("_missing_required") or [])[:8]:
            gaps.append({"skill": pretty_skill(t), "advice": "Required in the posting but not in your resume. Learn the basics and be ready to "
                         "say honestly how you'd ramp up — connect it to a similar tool you've used."})

    company = COMPANIES.get(re.sub(r"[^a-z]", "", (job.company or "").lower()))
    if company and company.get("alias"):
        company = COMPANIES[company["alias"]]

    # day-by-day plan (shorter if an interview is already scheduled soon)
    days = 7
    next_iv = None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for iv in interviews or []:
        if iv.get("scheduled_at") and iv["scheduled_at"] > now:
            next_iv = min(next_iv or iv["scheduled_at"], iv["scheduled_at"])
    if next_iv:
        days = max(2, min(10, (next_iv - now).days))
    high = [f for f in focus if f["priority"] == "high"]
    med = [f for f in focus if f["priority"] != "high"]
    tasks = [("Read the posting twice; list its top 5 requirements and match each to an example from your resume.", "Understand the role"),
             ("Write your 60-second pitch: who you are, your most relevant project, why this role.", "Understand the role")]
    if company:
        tasks.append((f"Read {company['name']}'s official interview guidance (link below).", "Company"))
    for f in high[:4]:
        tasks.append((f"{f['label']}: review {', '.join(f['topics'][:4])}; answer 2 of the practice questions out loud.", f["label"]))
    if any(f["key"] == "dsa" for f in focus):
        tasks.append(("Solve 3 timed coding problems (25 min each) from NeetCode 150 — arrays, hash maps, two pointers.", "Coding"))
        tasks.append(("Solve 3 more: trees/graphs (BFS/DFS) and one heap problem. Explain complexity out loud.", "Coding"))
    for f in med[:3]:
        tasks.append((f"{f['label']}: skim the key topics and prepare one example of how you've used it.", f["label"]))
    for g in gaps[:3]:
        tasks.append((f"Close a gap: learn the basics of {g['skill']} (official tutorial) and build a tiny example.", "Gaps"))
    tasks.append(("Write STAR stories for: biggest impact, hardest problem, teamwork, a mistake — use the bullets suggested below.", "Behavioral"))
    if any(f["key"] == "system design" for f in focus):
        tasks.append(("Practice one system design end to end (45 min): requirements → API → data model → scaling.", "System design"))
    tasks.append(("Do a full mock interview (a friend, Pramp, or record yourself) and fix the weakest answer.", "Mock"))
    tasks.append(("Prepare 3 questions to ask them; test your camera, mic and coding setup.", "Logistics"))
    plan = []
    per_day = max(1, -(-len(tasks) // days))
    for i, (t, area) in enumerate(tasks):
        plan.append({"id": f"t{i + 1}", "day": min(days, i // per_day + 1), "task": t, "area": area})

    days = max(p["day"] for p in plan) if plan else days
    return {
        "version": 1, "generated_at": now.isoformat() + "Z", "source": "rules",
        "role": {"family": fam, "family_name": FAMILY_NAMES[fam], "level": level, "years_required": years},
        "stages": stages_for(fam, level),
        "focus": focus[:10],
        "gaps": gaps,
        "behavioral": _stories(resume_text),
        "behavioral_resources": [_res("star")],
        "company": company,
        "ask_them": ASK_THEM,
        "plan": plan, "plan_days": days, "next_interview": next_iv.isoformat() + "Z" if next_iv else None,
        "general_resources": [_res(x) for x in ("tih", "pramp")],
        "ai_questions": [],
    }


def ai_questions(cfg, job, resume_text: str, prep: dict) -> list[dict]:
    """Questions written for this specific posting (technical + role-specific), with what a strong answer covers."""
    schema = llm.strict_schema({"questions": {"type": "array", "items": llm.strict_schema({
        "question": {"type": "string"}, "type": {"type": "string"}, "why_likely": {"type": "string"}, "strong_answer_covers": {"type": "string"},
        "use_from_resume": {"type": "string"}})}})
    task = ("Write 10 interview questions this candidate is likely to be asked for the job in <untrusted_job_description>: "
            "mostly technical/role-specific questions tied to the posting's requirements, plus 2 behavioral ones tied to its values. "
            "For each: type (technical, design, behavioral, role-specific), why it's likely (cite the requirement), what a strong answer "
            "covers, and which experience from <candidate_facts> the candidate could use (or '' if none). Do not claim to know the "
            "employer's actual questions.")
    payload = (f"<candidate_facts>\n{(resume_text or '')[:6000]}\n</candidate_facts>\n"
               f"<role>{prep['role']['family_name']}, {prep['role']['level']} level</role>\n"
               + llm.untrusted("job_description", f"{job.title} at {job.company}\n{job.description_text or ''}", 8000))
    out = llm.complete_json(task, payload, schema, cfg=cfg, name="interview_questions")
    return [q for q in out.get("questions", []) if q.get("question")][:12]
