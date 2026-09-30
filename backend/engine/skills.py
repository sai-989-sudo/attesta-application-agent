"""Curated skill lexicon + extraction.

Each canonical skill maps to aliases. Matching is case-insensitive with word
boundaries, so "R" or "Go" only match as standalone tokens.
"""
from __future__ import annotations

import re
from functools import lru_cache

SKILLS: dict[str, dict] = {}


def _add(category: str, entries: dict[str, list[str]]):
    for canon, aliases in entries.items():
        SKILLS[canon] = {"category": category, "aliases": [canon, *aliases]}


_add("Languages", {
    "Python": ["python3"], "Java": [], "JavaScript": ["js", "ecmascript"], "TypeScript": ["ts"],
    "C++": ["cpp"], "C#": ["c sharp"], "C": [], "R": ["r programming", "rstudio"], "Go": ["golang"],
    "Rust": [], "SQL": ["t-sql", "pl/sql"], "MATLAB": [], "Scala": [], "Kotlin": [], "Swift": [],
    "PHP": [], "Ruby": [], "Bash": ["shell scripting", "shell script", "unix shell"], "HTML": ["html5"],
    "CSS": ["css3"], "SAS": [], "Julia": [],
})
_add("ML & AI", {
    "Machine Learning": ["ml", "machine-learning"], "Deep Learning": ["deep-learning", "neural networks", "neural network"],
    "NLP": ["natural language processing", "text mining", "computational linguistics"],
    "Computer Vision": ["image processing", "image analysis", "cv models"],
    "LLMs": ["llm", "large language model", "large language models", "generative ai", "genai", "gpt"],
    "RAG": ["retrieval augmented generation", "retrieval-augmented generation"],
    "AI Agents": ["ai agent", "agentic", "multi-agent", "llm agents"],
    "Prompt Engineering": [], "Reinforcement Learning": [], "Transformers": ["transformer models", "bert"],
    "Statistics": ["statistical analysis", "statistical modeling", "hypothesis testing", "regression analysis"],
    "Data Mining": [], "Feature Engineering": [], "Time Series": ["forecasting"],
    "Recommender Systems": ["recommendation systems", "recommendation engine"],
    "Classification": ["classifier", "classifiers"], "Clustering": ["k-means", "kmeans"],
    "Named Entity Recognition": ["ner"], "Sentiment Analysis": [], "Medical Imaging": ["retinal imaging", "mri", "ct scans"],
})
_add("Libraries & Frameworks", {
    "TensorFlow": ["tf", "keras"], "PyTorch": ["torch"], "scikit-learn": ["sklearn", "scikit learn"],
    "pandas": [], "NumPy": ["numpy"], "SciPy": [], "Matplotlib": [], "Seaborn": [], "Plotly": [],
    "spaCy": ["spacy"], "NLTK": [], "Hugging Face": ["huggingface", "hugging face transformers"],
    "LangChain": [], "LangGraph": [], "OpenCV": ["cv2"], "XGBoost": [], "LightGBM": [],
    "Django": [], "Flask": [], "FastAPI": [], "React": ["react.js", "reactjs"], "Node.js": ["node", "nodejs"],
    "Express": ["express.js"], "Spring Boot": ["spring"], "Angular": [], "Vue": ["vue.js"],
    "REST APIs": ["rest api", "restful", "restful api", "restful apis", "rest"], "GraphQL": [],
    "Spark": ["pyspark", "apache spark"], "Hadoop": [], "Airflow": ["apache airflow"], "dbt": [],
    "Streamlit": [], "Jupyter": ["jupyter notebook", "notebooks"],
})
_add("Data & Cloud", {
    "AWS": ["amazon web services", "ec2", "s3", "sagemaker", "lambda"], "Azure": ["microsoft azure"],
    "GCP": ["google cloud", "google cloud platform", "bigquery"], "Docker": ["containers", "containerization"],
    "Kubernetes": ["k8s"], "Git": ["github", "gitlab", "version control"], "Linux": ["unix", "ubuntu"],
    "PostgreSQL": ["postgres"], "MySQL": [], "MongoDB": ["mongo"], "SQLite": [], "Redis": [],
    "Snowflake": [], "ETL": ["data pipelines", "data pipeline", "etl pipelines"], "CI/CD": ["github actions", "jenkins"],
    "Tableau": [], "Power BI": ["powerbi"], "Excel": ["microsoft excel", "spreadsheets", "vlookup", "pivot tables"],
    "Data Visualization": ["dashboards", "dashboard", "data viz"], "Data Analysis": ["data analytics", "analytics"],
    "Data Cleaning": ["data wrangling", "data preprocessing", "preprocessing"], "Databases": ["database", "dbms"],
    "HPC": ["high performance computing", "slurm", "sol supercomputer", "gpu cluster"],
    "Cybersecurity": ["security operations", "soc", "siem", "incident response", "network security"],
})
_add("Research & Professional", {
    "Research Experience": ["research assistant", "literature review", "experimental design", "conducted research", "research project", "research projects", "undergraduate research"],
    "Technical Writing": ["documentation", "documented", "technical documentation", "technical reports", "report writing", "how-to guides", "user guides"],
    "Teaching": ["tutoring", "tutored", "tutor", "teaching assistant", "teaching", "grading", "mentoring", "instruction"],
    "Communication": ["explained", "presented", "presentations", "public speaking", "presenting", "written and verbal", "verbal communication", "written communication"], "Teamwork": ["collaboration", "collaborated", "cross-functional"],
    "Customer Service": ["front desk", "help desk", "helpdesk", "customer support"],
    "User Support": ["walk-in", "drop-in", "office hours", "answering questions", "answer questions", "supporting users", "supporting other users", "user support", "technical support"],
    "Project Management": ["agile", "scrum", "jira"], "Leadership": ["led a team", "team lead"],
    "Data Entry": [], "Microsoft Office": ["ms office", "word", "powerpoint", "outlook"],
    "Problem Solving": ["troubleshooting", "debugging"], "Time Management": [],
    "Unit Testing": ["pytest", "unittest", "testing"], "APIs": ["api", "api integration"],
    "Web Development": ["web applications", "web application", "full-stack", "full stack", "frontend", "backend"],
})

# Words that look like skills but are too ambiguous to count on their own.
AMBIGUOUS = {"word", "spring", "rest", "node", "lambda", "testing", "api", "analytics", "notebooks",
             "tf", "ts", "js", "soc", "containers", "gpt", "unix", "express", "tutor", "instruction"}


@lru_cache(maxsize=1)
def _patterns():
    pats = []
    for canon, info in SKILLS.items():
        for a in info["aliases"]:
            esc = re.escape(a.lower())
            # custom boundaries so C++ / C# / .NET / Node.js work
            pats.append((canon, a.lower(), re.compile(r"(?<![a-z0-9+#])" + esc + r"(?![a-z0-9+#])")))
    # longer aliases first so "machine learning" wins over "learning"
    pats.sort(key=lambda t: -len(t[1]))
    return pats


def extract_skills(text: str, strict: bool = False) -> list[str]:
    """Return canonical skills mentioned in text (order of first appearance)."""
    low = (text or "").lower()
    found: dict[str, int] = {}
    occupied: list[range] = []
    for canon, alias, pat in _patterns():
        if strict and alias in AMBIGUOUS:
            continue
        # single-letter languages need a case-sensitive, list-like context
        if canon in ("R", "C") and alias == canon.lower():
            m = re.search(r"(?:^|[\s,(/])" + canon + r"(?=$|[\s,)/;.])", text or "")
            if not m or not re.search(r"(?i)(language|program|python|java|sql|matlab|statistic|software|studio|(with|in|using|or|and) " + canon + r"\b|,\s*" + canon + r"\b|\b" + canon + r"\s*,)", text or ""):
                continue
            found.setdefault(canon, m.start())
            continue
        if canon in found:
            continue
        for m in pat.finditer(low):
            span = range(m.start(), m.end())
            if any(set(span) & set(o) for o in occupied):
                continue  # inside a longer skill already matched (e.g. "APIs" in "REST APIs")
            occupied.append(span)
            found[canon] = m.start()
            break
    return [k for k, _ in sorted(found.items(), key=lambda kv: kv[1])]


def category(skill: str) -> str:
    return SKILLS.get(skill, {}).get("category", "Other")


def extract_skill_spans(text: str) -> list[tuple[str, int, int]]:
    """Like extract_skills but returns (skill, start, end) for grouping alternatives."""
    low = (text or "").lower()
    out = []
    for sk in extract_skills(text):
        for alias in SKILLS[sk]["aliases"]:
            if sk in ("R", "C"):
                m = re.search(r"(?:^|[\s,(/])(" + sk + r")(?=$|[\s,)/;.])", text or "")
                if m:
                    out.append((sk, m.start(1), m.end(1)))
                    break
                continue
            m = re.search(r"(?<![a-z0-9+#])" + re.escape(alias.lower()) + r"(?![a-z0-9+#])", low)
            if m:
                out.append((sk, m.start(), m.end()))
                break
    return sorted(out, key=lambda t: t[1])


def skill_groups(text: str) -> list[list[str]]:
    """Group skills joined by 'or' / '/' into alternatives: 'Python or R, and SQL' -> [[Python, R], [SQL]]."""
    spans = extract_skill_spans(text)
    groups: list[list[str]] = []
    prev_end = None
    for sk, st, en in spans:
        between = text[prev_end:st] if prev_end is not None else ""
        if groups and re.fullmatch(r"\s*(,?\s*or\s*|/\s*|,\s*)", between) and re.search(r"(?i)\bor\b|/", text[prev_end:st] + text[en:en + 12] + between) and "and" not in between:
            groups[-1].append(sk)
        else:
            groups.append([sk])
        prev_end = en
    return groups
