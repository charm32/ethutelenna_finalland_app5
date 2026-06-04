# =============================================================================
#  eThute Lenna 5.0 — FastAPI Backend + Frontend Server
#  Platform : Railway (replaces Streamlit)
#  AI API   : OpenRouter (DeepSeek V3)
#  Vector DB: ChromaDB
#  Embeds   : HuggingFace all-MiniLM-L6-v2
#
#  NEW in v5.0:
#  - Serves the full HTML frontend (no Streamlit)
#  - RAG searches BOTH study_guides/ AND previous_papers/ for selected subject
#  - Landing page (index.html) login/register buttons are now active
# =============================================================================

from __future__ import annotations

import os
from dotenv import load_dotenv
load_dotenv()

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── FastAPI ───────────────────────────────────────────────────────────────────
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── JWT ───────────────────────────────────────────────────────────────────────
from jose import JWTError, jwt

# ── Translation ───────────────────────────────────────────────────────────────
try:
    from deep_translator import GoogleTranslator
    TRANSLATE_AVAILABLE = True
except ImportError:
    TRANSLATE_AVAILABLE = False

# ── PDF reading ───────────────────────────────────────────────────────────────
try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False

# ── LangChain stack ───────────────────────────────────────────────────────────
from langchain_community.document_loaders import PyPDFLoader
try:
    from langchain_chroma import Chroma
except ImportError:
    from langchain_community.vectorstores import Chroma
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import AppConfig
from debugger import DebugLogger

# =============================================================================
#  CONSTANTS & CONFIGURATION
# =============================================================================

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEEPSEEK_CHAT_MODEL = "deepseek/deepseek-chat"

USERS_FILE        = "users.json"
TRACKING_FILE     = "tracking.json"
COINS_PER_CORRECT = 10

JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_HOURS = 24

LANGUAGES = {
    "English": {"trans_dest": "en",  "flag": "🇿🇦"},
    "isiZulu": {"trans_dest": "zu",  "flag": "🌍"},
    "Sesotho": {"trans_dest": "st",  "flag": "🌍"},
}

debug  = DebugLogger(level=logging.INFO)
logger = debug.get_logger(__name__)


def get_openrouter_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "")


def get_jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET environment variable is not set.")
    return secret


# =============================================================================
#  SUBJECT CATALOGUE
# =============================================================================

SUBJECT_CATALOGUE: Dict[str, Any] = {
    "Physical Sciences (Physics)": {
        "emoji": "⚡", "color": "#3b82f6",
        "units": [
            {"title": "Mechanics & Motion",     "video": "https://www.youtube.com/watch?v=ZM8ECpBuQYE", "duration": "12 min"},
            {"title": "Waves & Sound",           "video": "https://www.youtube.com/watch?v=dN2-jRBzMCM", "duration": "10 min"},
            {"title": "Electricity & Magnetism", "video": "https://www.youtube.com/watch?v=ruNrdlGpPoQ", "duration": "14 min"},
        ],
        "quiz": [
            {"q": "What is Newton's First Law?",
             "options": ["Objects at rest stay at rest unless acted on", "F = ma", "Every action has a reaction", "Energy is conserved"],
             "answer": 0,
             "explanation": "Newton's First Law states that an object at rest stays at rest, and an object in motion stays in motion, unless acted on by an external force."},
            {"q": "What is the unit of electric current?",
             "options": ["Volt", "Watt", "Ampere", "Ohm"],
             "answer": 2,
             "explanation": "Electric current is measured in Amperes (A). Voltage is in Volts, power in Watts, and resistance in Ohms."},
            {"q": "What type of wave is sound?",
             "options": ["Transverse", "Longitudinal", "Electromagnetic", "Surface"],
             "answer": 1,
             "explanation": "Sound is a longitudinal wave — particles vibrate parallel to the direction the wave travels."},
        ],
        "tips": ["Review Newton's Laws with diagrams", "Practice past exam calculations daily", "Watch slow-motion videos for wave behaviour"],
    },
    "Physical Sciences (Chemistry)": {
        "emoji": "🧪", "color": "#10b981",
        "units": [
            {"title": "Atomic Structure",     "video": "https://www.youtube.com/watch?v=rz8fHOPGDuI", "duration": "11 min"},
            {"title": "Chemical Bonding",      "video": "https://www.youtube.com/watch?v=QqjcCvzWwww", "duration": "13 min"},
            {"title": "Reactions & Equations", "video": "https://www.youtube.com/watch?v=AXAiLFMjFSc", "duration": "10 min"},
        ],
        "quiz": [
            {"q": "How many electrons does Carbon have?",
             "options": ["4", "6", "8", "12"],
             "answer": 1,
             "explanation": "Carbon (C) has atomic number 6, meaning 6 protons and 6 electrons in a neutral atom."},
            {"q": "What bond involves sharing electrons?",
             "options": ["Ionic", "Metallic", "Covalent", "Hydrogen"],
             "answer": 2,
             "explanation": "Covalent bonds form when atoms share electrons. Ionic bonds transfer electrons between atoms."},
            {"q": "What is the pH of pure water?",
             "options": ["6", "7", "8", "9"],
             "answer": 1,
             "explanation": "Pure water is neutral with pH 7. Below 7 is acidic; above 7 is alkaline/basic."},
        ],
        "tips": ["Draw atomic diagrams by hand", "Balance 5 equations per day", "Make flashcards for the periodic table"],
    },
    "Mathematics": {
        "emoji": "📐", "color": "#8b5cf6",
        "units": [
            {"title": "Algebra & Functions", "video": "https://www.youtube.com/watch?v=NybHckSEQBI", "duration": "15 min"},
            {"title": "Trigonometry",         "video": "https://www.youtube.com/watch?v=PUB0TaZ7bhA", "duration": "12 min"},
            {"title": "Calculus Basics",      "video": "https://www.youtube.com/watch?v=WUvTyaaNkzM", "duration": "16 min"},
        ],
        "quiz": [
            {"q": "What is the derivative of x²?",
             "options": ["x", "2x", "x²", "2"],
             "answer": 1,
             "explanation": "Power rule: d/dx of xⁿ = n·xⁿ⁻¹. So d/dx of x² = 2x."},
            {"q": "What does sin(90°) equal?",
             "options": ["0", "0.5", "1", "-1"],
             "answer": 2,
             "explanation": "sin(90°) = 1. On the unit circle, 90° points straight up giving a y-value of 1."},
            {"q": "What is the quadratic formula used for?",
             "options": ["Finding gradients", "Solving quadratic equations", "Integration", "Geometry"],
             "answer": 1,
             "explanation": "x = (-b ± √(b²-4ac)) / 2a solves ax²+bx+c=0."},
        ],
        "tips": ["Redo exercises without looking at solutions", "Time yourself on past papers", "Show all working steps clearly"],
    },
    "Math Literacy": {
        "emoji": "🔢", "color": "#06b6d4",
        "units": [
            {"title": "Finance & Interest", "video": "https://www.youtube.com/watch?v=XNtu55Dh5w0", "duration": "9 min"},
            {"title": "Data & Statistics",  "video": "https://www.youtube.com/watch?v=xxpc-HPKN28", "duration": "11 min"},
            {"title": "Measurement & Maps", "video": "https://www.youtube.com/watch?v=r9NUMbEb0F8", "duration": "8 min"},
        ],
        "quiz": [
            {"q": "What is the simple interest formula?",
             "options": ["P × r × t", "P(1+r)^t", "P/r×t", "P+r+t"],
             "answer": 0,
             "explanation": "Simple Interest = Principal × rate × time (SI = Prt)."},
            {"q": "What does the median represent?",
             "options": ["Most common value", "Middle value", "Average value", "Largest value"],
             "answer": 1,
             "explanation": "The median is the middle value when data is in order."},
            {"q": "What is 25% of 200?",
             "options": ["25", "40", "50", "75"],
             "answer": 2,
             "explanation": "25% = 0.25. 0.25 × 200 = 50."},
        ],
        "tips": ["Apply concepts to real life budgets", "Practice reading graphs and charts", "Use a calculator to verify mental estimates"],
    },
    "Life Sciences": {
        "emoji": "🌱", "color": "#22c55e",
        "units": [
            {"title": "Cells & Genetics",    "video": "https://www.youtube.com/watch?v=URUJD5NEXC8", "duration": "12 min"},
            {"title": "Evolution & Ecology", "video": "https://www.youtube.com/watch?v=GcjgWov7mTM", "duration": "10 min"},
            {"title": "Human Body Systems",  "video": "https://www.youtube.com/watch?v=Ae4MadKPJC0", "duration": "13 min"},
        ],
        "quiz": [
            {"q": "What is the powerhouse of the cell?",
             "options": ["Nucleus", "Ribosome", "Mitochondria", "Golgi body"],
             "answer": 2,
             "explanation": "Mitochondria produce ATP through cellular respiration."},
            {"q": "What does DNA stand for?",
             "options": ["Deoxyribonucleic Acid", "Double Nucleic Acid", "Dynamic Nucleotide Array", "Dual Nitrogen Acid"],
             "answer": 0,
             "explanation": "DNA = Deoxyribonucleic Acid. It carries genetic information in all living organisms."},
            {"q": "What is natural selection?",
             "options": ["Random mutation", "Survival of the fittest", "Artificial breeding", "Genetic engineering"],
             "answer": 1,
             "explanation": "Organisms better adapted to their environment tend to survive and reproduce more."},
        ],
        "tips": ["Draw diagrams of cell organelles", "Make timelines of evolutionary events", "Use mnemonics for body system functions"],
    },
    "Geography": {
        "emoji": "🌍", "color": "#f59e0b",
        "units": [
            {"title": "Climate & Weather",   "video": "https://www.youtube.com/watch?v=x1SgmFa0r04", "duration": "10 min"},
            {"title": "Geomorphology",       "video": "https://www.youtube.com/watch?v=1oCBGCpgqiI", "duration": "11 min"},
            {"title": "Population & Cities", "video": "https://www.youtube.com/watch?v=FACK2knC08E", "duration": "9 min"},
        ],
        "quiz": [
            {"q": "What causes the seasons?",
             "options": ["Distance from the Sun", "Earth's tilt on its axis", "Moon's gravity", "Solar flares"],
             "answer": 1,
             "explanation": "Seasons are caused by Earth's 23.5° axial tilt."},
            {"q": "What is erosion?",
             "options": ["Building up of land", "Wearing away of land", "Volcanic activity", "Tectonic shift"],
             "answer": 1,
             "explanation": "Erosion is the wearing away and removal of rock or soil by water, wind, ice, or gravity."},
            {"q": "What is urbanisation?",
             "options": ["Rural farming growth", "Movement of people to cities", "City population decline", "Industrial pollution"],
             "answer": 1,
             "explanation": "Urbanisation is the process by which people move from rural to urban areas."},
        ],
        "tips": ["Sketch climate graphs from memory", "Study SA city case studies", "Memorise geomorphological processes"],
    },
    "History": {
        "emoji": "📜", "color": "#a78bfa",
        "units": [
            {"title": "Cold War Era",   "video": "https://www.youtube.com/watch?v=I79TpDe3t2g", "duration": "13 min"},
            {"title": "Apartheid & SA", "video": "https://www.youtube.com/watch?v=SVW3OU-UBvE", "duration": "11 min"},
            {"title": "World War II",   "video": "https://www.youtube.com/watch?v=fo2Rb9h788s", "duration": "14 min"},
        ],
        "quiz": [
            {"q": "When did the Cold War begin?",
             "options": ["1939", "1945", "1947", "1950"],
             "answer": 2,
             "explanation": "The Cold War began in 1947, marked by the Truman Doctrine."},
            {"q": "What year did apartheid end in South Africa?",
             "options": ["1990", "1994", "1996", "2000"],
             "answer": 1,
             "explanation": "Apartheid ended in 1994 with South Africa's first democratic elections."},
            {"q": "Who was SA's first democratically elected president?",
             "options": ["F.W. de Klerk", "Desmond Tutu", "Nelson Mandela", "Walter Sisulu"],
             "answer": 2,
             "explanation": "Nelson Mandela became South Africa's first democratically elected president in 1994."},
        ],
        "tips": ["Create timelines of major events", "Practise essay structure", "Link causes and effects for each event"],
    },
    "English": {
        "emoji": "📖", "color": "#ec4899",
        "units": [
            {"title": "Literature & Poetry", "video": "https://www.youtube.com/watch?v=JwhouCNq-Fc", "duration": "10 min"},
            {"title": "Writing Skills",      "video": "https://www.youtube.com/watch?v=JrU1ADCiRH4", "duration": "9 min"},
            {"title": "Language & Grammar",  "video": "https://www.youtube.com/watch?v=vFQlWCJ1Mm4", "duration": "8 min"},
        ],
        "quiz": [
            {"q": "What is a metaphor?",
             "options": ["A comparison using 'like' or 'as'", "An indirect comparison without 'like' or 'as'", "A repeated sound", "An exaggeration"],
             "answer": 1,
             "explanation": "A metaphor directly compares two things by saying one IS the other (e.g. 'Life is a journey')."},
            {"q": "What is the purpose of a topic sentence?",
             "options": ["To conclude a paragraph", "To introduce the main idea of a paragraph", "To give examples", "To add detail"],
             "answer": 1,
             "explanation": "A topic sentence introduces the main idea of a paragraph."},
            {"q": "What tense describes past actions still relevant now?",
             "options": ["Simple past", "Past perfect", "Present perfect", "Future tense"],
             "answer": 2,
             "explanation": "Present perfect (e.g. 'I have studied') describes past actions still relevant to the present."},
        ],
        "tips": ["Read a passage aloud every day", "Practise introductions and conclusions", "Keep a vocabulary journal"],
    },
}

ALL_SUBJECT_NAMES = list(SUBJECT_CATALOGUE.keys())

# FIX: Split into two correct keys matching the catalogue exactly
SUBJECT_PDF_MAP: Dict[str, List[str]] = {
    "Physical Sciences (Physics)":   ["physics", "physical science", "physical_science"],
    "Physical Sciences (Chemistry)": ["chemistry", "chemical"],
    "Mathematics":                   ["mathematics", "maths grade", "math grade"],
    "Math Literacy":                 ["maths_lit", "maths lit", "math lit", "mathematical literacy"],
    "Life Sciences":                 ["life science", "biology", "life_science"],
    "Geography":                     ["geography", "geo"],
    "History":                       ["history"],
    "English":                       ["english"],
}

# FIX: Corrected subject names (previously had doubled/wrong names)
GUIDE_SUBJECTS = ["Physical Sciences (Physics)", "Physical Sciences (Chemistry)", "Mathematics", "Math Literacy"]
PAPER_SUBJECTS = ["Physical Sciences (Physics)", "Physical Sciences (Chemistry)", "Mathematics", "Math Literacy"]


# =============================================================================
#  FILE PERSISTENCE HELPERS
# =============================================================================

def load_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


def save_json(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


# =============================================================================
#  USER MANAGEMENT
# =============================================================================

def register_user(username: str, password: str, dob: str = "", school: str = "") -> bool:
    users = load_json(USERS_FILE)
    if username in users:
        return False
    users[username] = {
        "password": hash_password(password),
        "dob":      dob,
        "school":   school,
        "created":  str(datetime.now()),
        "subjects": [],
        "coins":    0,
    }
    save_json(USERS_FILE, users)
    return True


def login_user(username: str, password: str) -> bool:
    users = load_json(USERS_FILE)
    if username not in users:
        return False
    return users[username]["password"] == hash_password(password)


def get_user_subjects(username: str) -> List[str]:
    return load_json(USERS_FILE).get(username, {}).get("subjects", [])


def save_user_subjects(username: str, subjects: List[str]) -> None:
    users = load_json(USERS_FILE)
    if username in users:
        users[username]["subjects"] = subjects
        save_json(USERS_FILE, users)


def get_user_coins(username: str) -> int:
    return load_json(USERS_FILE).get(username, {}).get("coins", 0)


def add_user_coins(username: str, amount: int) -> None:
    users = load_json(USERS_FILE)
    if username in users:
        users[username]["coins"] = users[username].get("coins", 0) + amount
        save_json(USERS_FILE, users)


# =============================================================================
#  QUIZ TRACKING
# =============================================================================

def save_tracking(username: str, subject: str, unit: str, score: int,
                  tips: list, total_questions: int = 3) -> int:
    data = load_json(TRACKING_FILE)
    if username not in data:
        data[username] = []
    coins_earned = score * COINS_PER_CORRECT
    data[username].append({
        "subject":         subject,
        "unit":            unit,
        "score":           score,
        "total_questions": total_questions,
        "tips":            tips,
        "timestamp":       datetime.now().strftime("%d %b %Y %H:%M"),
        "coins_earned":    coins_earned,
    })
    save_json(TRACKING_FILE, data)
    add_user_coins(username, coins_earned)
    return coins_earned


def get_tracking(username: str) -> list:
    return load_json(TRACKING_FILE).get(username, [])


# =============================================================================
#  JWT AUTH
# =============================================================================

def create_access_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> str:
    try:
        payload  = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        username = payload.get("sub", "")
        if not username:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
        return username
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")


security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    return decode_token(credentials.credentials)


# =============================================================================
#  TRANSLATION (cached)
# =============================================================================

@lru_cache(maxsize=512)
def translate_text(text: str, dest_lang: str) -> str:
    if dest_lang == "en" or not TRANSLATE_AVAILABLE:
        return text
    try:
        translated = GoogleTranslator(source="auto", target=dest_lang).translate(text[:4500])
        return translated if translated else text
    except Exception:
        return text


# =============================================================================
#  PDF HELPERS
# =============================================================================

def get_available_study_guides() -> Dict[str, str]:
    guides_dir = Path("study_guides")
    guides_dir.mkdir(exist_ok=True)
    return {
        pdf.stem.replace("_", " ").replace("-", " "): str(pdf)
        for pdf in sorted(guides_dir.glob("*.pdf"))
    }


def get_available_previous_papers() -> Dict[str, str]:
    papers_dir = Path("previous_papers")
    papers_dir.mkdir(exist_ok=True)
    pdfs = {
        pdf.stem.replace("_", " ").replace("-", " "): str(pdf)
        for pdf in sorted(papers_dir.rglob("*.pdf"))
    }
    print("=" * 60)
    print("PREVIOUS PAPERS FOUND:")
    for name, path in pdfs.items():
        print(f"{name} -> {path}")
    print("=" * 60)
    return pdfs


def _resolve_subject_lookup(subject: str) -> str:
    return "Math Literacy" if subject == "Mathematics Literacy" else subject


def _filter_pdfs_by_subject(pdf_dict: Dict[str, str], subject: str) -> Dict[str, str]:
    lookup   = _resolve_subject_lookup(subject)
    keywords = SUBJECT_PDF_MAP.get(lookup, [subject.lower()])
    return {
        name: path
        for name, path in pdf_dict.items()
        if any(kw in name.lower().replace("_", " ").replace("-", " ") for kw in keywords)
        or subject.lower() in name.lower()
    }


def find_guide_for_subject(subject: str) -> Optional[str]:
    keywords = SUBJECT_PDF_MAP.get(subject, [subject.lower()])
    guides   = get_available_study_guides()
    for name, path in guides.items():
        name_lower = name.lower().replace("_", " ").replace("-", " ")
        for kw in keywords:
            if kw in name_lower or name_lower in kw:
                return path
    for name, path in guides.items():
        if subject.lower() in name.lower():
            return path
    return None


def find_all_pdfs_for_subject(subject: str) -> List[str]:
    all_paths: List[str] = []
    guides         = get_available_study_guides()
    papers         = get_available_previous_papers()
    matched_guides = _filter_pdfs_by_subject(guides, subject)
    matched_papers = _filter_pdfs_by_subject(papers, subject)
    all_paths.extend(matched_guides.values())
    all_paths.extend(matched_papers.values())
    return list(set(all_paths))


def _extract_year(name: str) -> str:
    m = re.search(r"(20\d{2}|19\d{2})", name)
    return m.group(1) if m else name


def count_pdf_pages(path: str) -> int:
    if not PYPDF2_AVAILABLE:
        raise HTTPException(status_code=500, detail="PyPDF2 is not installed.")
    try:
        with open(path, "rb") as f:
            return len(PyPDF2.PdfReader(f).pages)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read PDF: {exc}")


def extract_pdf_page(path: str, page_num: int, lang_code: str = "en") -> str:
    if not PYPDF2_AVAILABLE:
        raise HTTPException(status_code=500, detail="PyPDF2 is not installed.")
    try:
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            total  = len(reader.pages)
            if page_num < 1 or page_num > total:
                raise HTTPException(
                    status_code=400,
                    detail=f"Page {page_num} out of range. PDF has {total} pages.",
                )
            raw = (reader.pages[page_num - 1].extract_text() or "").strip()
        if not raw:
            return ""
        if lang_code != "en":
            return translate_text(raw[:1500], lang_code)
        return raw
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"PDF read error ({path}): {exc}")
        raise HTTPException(status_code=500, detail=f"Could not read PDF: {exc}")


# =============================================================================
#  LANGCHAIN / RAG STACK
# =============================================================================

RAG_PROMPT = AppConfig.RAG_PROMPT

QUIZ_EXPLAIN_PROMPT = """You are eThute Lenna, a Grade 12 study assistant.
Using ONLY the context from the study guide below, explain in 3-5 short bullet points why the correct answer is correct.
Keep each bullet to one sentence. Start with "## Why {correct_answer} is correct".
If the study guide does not cover this, use this pre-written explanation: {fallback}

Study Guide Context: {context}
Question: {question}
Correct Answer: {correct_answer}
Explanation (bullet points only):"""


def sanitize_collection_name(name: str) -> str:
    """
    Sanitize a string for use as a ChromaDB collection name.
    ChromaDB only allows [a-zA-Z0-9._-], must start/end with alphanumeric,
    and must be 3-512 characters long.
    """
    # Replace any illegal character (including parentheses) with underscore
    sanitized = re.sub(r'[^a-zA-Z0-9._-]', '_', name)
    # Collapse multiple consecutive underscores into one
    sanitized = re.sub(r'_+', '_', sanitized)
    # Strip leading/trailing underscores, dots, hyphens (must start/end with alphanumeric)
    sanitized = sanitized.strip('_.-')
    # Ensure minimum length of 3 characters
    if len(sanitized) < 3:
        sanitized = sanitized + '_db'
    # Truncate to 512 characters max
    sanitized = sanitized[:512]
    return sanitized.lower()


@lru_cache(maxsize=1)
def get_embeddings():
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError:
        from langchain_community.embeddings import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")


def get_deepseek_llm(temperature: float = 0) -> ChatOpenAI:
    api_key = get_openrouter_key()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENROUTER_API_KEY is not configured on this server.",
        )
    return ChatOpenAI(
        model=DEEPSEEK_CHAT_MODEL,
        openai_api_key=api_key,
        openai_api_base=OPENROUTER_BASE_URL,
        temperature=temperature,
        default_headers={
            "HTTP-Referer": "https://ethutelenna.com",
            "X-Title":      "eThute Lenna",
        },
    )


def clean_answer(text: str) -> str:
    """Strip leading/trailing whitespace and normalize blank lines."""
    text = text.strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def load_subject_db(subject_name: str, pdf_path: str):
    """Load a single PDF into ChromaDB (used for quiz explanations)."""
    collection_name = sanitize_collection_name(f"ethute_{subject_name}_single")
    chroma_path     = f"chroma_db/{collection_name}"
    try:
        embeddings = get_embeddings()
        if os.path.exists(chroma_path) and os.listdir(chroma_path):
            return Chroma(
                collection_name=collection_name,
                embedding_function=embeddings,
                persist_directory=chroma_path,
            )
        loader = PyPDFLoader(pdf_path)
        docs   = loader.load()
        if not docs:
            return None
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=AppConfig.CHUNK_SIZE,
            chunk_overlap=AppConfig.CHUNK_OVERLAP,
        )
        chunks = splitter.split_documents(docs)
        for doc in chunks:
            doc.page_content = doc.page_content[:AppConfig.MAX_CHARS]
        db = Chroma.from_documents(
            documents=chunks,
            embedding=embeddings,
            collection_name=collection_name,
            persist_directory=chroma_path,
        )
        return db
    except Exception as exc:
        logger.error(f"ChromaDB error for {subject_name}: {exc}")
        return None


def load_subject_db_multi(subject_name: str, pdf_paths: List[str]):
    """Load ALL PDFs for a subject into ONE ChromaDB collection."""
    if not pdf_paths:
        logger.error(f"No PDF paths found for subject: {subject_name}")
        return None

    collection_name = sanitize_collection_name(f"ethute_{subject_name}_multi")
    chroma_path     = f"chroma_db/{collection_name}"

    try:
        embeddings = get_embeddings()

        # ── Load existing database ────────────────────────────────
        if os.path.exists(chroma_path) and os.listdir(chroma_path):
            logger.info(f"Loading existing ChromaDB for {subject_name}")
            return Chroma(
                collection_name=collection_name,
                embedding_function=embeddings,
                persist_directory=chroma_path,
            )

        logger.info(f"Building NEW ChromaDB for {subject_name}")

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=AppConfig.CHUNK_SIZE,
            chunk_overlap=AppConfig.CHUNK_OVERLAP,
        )

        all_chunks = []

        for pdf_path in pdf_paths:
            print("=" * 60)
            print(f"Loading PDF: {pdf_path}")
            try:
                if not os.path.exists(pdf_path):
                    print(f"FILE DOES NOT EXIST: {pdf_path}")
                    continue

                loader = PyPDFLoader(pdf_path)
                docs   = loader.load()

                if not docs:
                    print(f"NO DOCUMENTS FOUND IN: {pdf_path}")
                    continue

                print(f"Loaded {len(docs)} pages")
                chunks = splitter.split_documents(docs)
                print(f"Created {len(chunks)} chunks")

                valid_chunks = []
                for doc in chunks:
                    if not doc.page_content.strip():
                        continue
                    doc.page_content = doc.page_content[:AppConfig.MAX_CHARS]
                    doc.metadata["source_type"] = (
                        "previous_paper" if "previous_papers" in pdf_path else "study_guide"
                    )
                    doc.metadata["pdf_path"] = pdf_path
                    valid_chunks.append(doc)

                print(f"Valid chunks added: {len(valid_chunks)}")
                all_chunks.extend(valid_chunks)
                logger.info(f"Loaded {len(valid_chunks)} chunks from {pdf_path}")

            except Exception as e:
                print(f"FAILED TO LOAD PDF: {pdf_path}")
                print(f"ERROR: {str(e)}")
                logger.warning(f"Skipping broken PDF {pdf_path}: {e}")

        print("=" * 60)
        print(f"TOTAL CHUNKS LOADED: {len(all_chunks)}")

        if not all_chunks:
            logger.error(f"No chunks could be loaded for {subject_name}")
            print("NO VALID PDF CONTENT COULD BE LOADED")
            return None

        print("Creating ChromaDB vector store...")
        db = Chroma.from_documents(
            documents=all_chunks,
            embedding=embeddings,
            collection_name=collection_name,
            persist_directory=chroma_path,
        )
        print("ChromaDB created successfully")
        logger.info(f"Built ChromaDB for {subject_name} with {len(all_chunks)} chunks")
        return db

    except Exception as e:
        logger.error(f"Multi-PDF ChromaDB error for {subject_name}: {e}")
        print(f"VECTOR DATABASE ERROR: {str(e)}")
        return None


def answer_question_from_guide(question: str, vector_db) -> tuple:
    """Returns (answer_text, source_page_int_or_None, pdf_path_or_None)"""
    try:
        llm       = get_deepseek_llm(temperature=0)
        retriever = vector_db.as_retriever(
            search_type="similarity",
            search_kwargs={"k": AppConfig.RETRIEVAL_K},
        )
        # Get source docs so we can extract page number
        source_docs = retriever.invoke(question)
        source_page = None
        source_pdf  = None
        if source_docs:
            meta = source_docs[0].metadata
            # LangChain loaders store page as 0-based int
            raw_page = meta.get("page")
            if raw_page is not None:
                source_page = int(raw_page) + 1   # convert to 1-based
            source_pdf = meta.get("source") or meta.get("pdf_path")

        prompt = ChatPromptTemplate.from_template(RAG_PROMPT)
        chain  = (
            {"context": retriever, "question": RunnablePassthrough()}
            | prompt | llm | StrOutputParser()
        )
        raw = chain.invoke(question)
        return clean_answer(raw), source_page, source_pdf
    except Exception as exc:
        logger.error(f"RAG error: {exc}")
        raise HTTPException(status_code=500, detail=f"RAG pipeline error: {exc}")


def explain_quiz_answer(question: str, correct_answer: str,
                        fallback: str, vector_db) -> str:
    if vector_db is None:
        return fallback
    try:
        llm       = get_deepseek_llm(temperature=0)
        retriever = vector_db.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 3},
        )
        prompt = ChatPromptTemplate.from_template(QUIZ_EXPLAIN_PROMPT)
        chain  = (
            {
                "context":        retriever,
                "question":       lambda _: question,
                "correct_answer": lambda _: correct_answer,
                "fallback":       lambda _: fallback,
            }
            | prompt | llm | StrOutputParser()
        )
        return chain.invoke(question)
    except Exception:
        return fallback



# =============================================================================
#  AI QUIZ GENERATION FROM PDF CONTENT
# =============================================================================

AI_QUIZ_GEN_PROMPT = """You are eThute Lenna, a South African Grade 12 study assistant.
Using ONLY the context extracted from the student's study guides and previous exam papers below,
generate exactly {num_questions} multiple-choice quiz questions.

STRICT RULES:
1. Every question MUST be based directly on the context provided — no general knowledge.
2. Each question must have exactly 4 options labelled A, B, C, D.
3. Do NOT repeat or rephrase any of these already-used questions: {used_questions}
4. If context_topics are provided, prioritise questions on those topics: {context_topics}
5. Questions must vary in difficulty — mix easy recall, application, and analysis.
6. Return ONLY valid JSON — no markdown fences, no extra text, no preamble.

Context from study material:
{context}

Return a JSON array of exactly {num_questions} objects with this structure:
[
  {{
    "q": "Full question text here?",
    "options": ["Option A text", "Option B text", "Option C text", "Option D text"],
    "answer": 0,
    "explanation": "One clear sentence explaining why this answer is correct.",
    "topic": "Short topic name e.g. Newton's Laws"
  }}
]

The "answer" field is the zero-based index (0,1,2,3) of the correct option.
Return ONLY the JSON array. No other text whatsoever."""


def generate_ai_quiz(subject_name: str, vector_db, num_questions: int,
                     context_topics: List[str], used_questions: List[str]) -> List[dict]:
    """Use RAG vector store + LLM to generate fresh quiz questions from PDF content."""
    import json as _json
    try:
        llm = get_deepseek_llm(temperature=0.7)

        # Build retrieval query from subject + user-explored topics
        if context_topics:
            retrieval_query = f"{subject_name}: " + ", ".join(context_topics[:5])
        else:
            retrieval_query = f"{subject_name} key concepts definitions formulas examples"

        retriever = vector_db.as_retriever(
            search_type="similarity",
            search_kwargs={"k": min(12, num_questions * 2)},
        )
        docs = retriever.invoke(retrieval_query)
        context_text = "\n\n".join(
            f"[Source: {doc.metadata.get('source_type', 'study material')}]\n{doc.page_content}".strip()
            for doc in docs
            if doc.page_content.strip()
        )[:6000]

        if not context_text:
            logger.error(f"No context retrieved for quiz generation: {subject_name}")
            return []

        used_str   = "; ".join(used_questions[:20]) if used_questions else "None"
        topics_str = ", ".join(context_topics[:10]) if context_topics else "any relevant topics"

        prompt_text = AI_QUIZ_GEN_PROMPT.format(
            num_questions=num_questions,
            used_questions=used_str,
            context_topics=topics_str,
            context=context_text,
        )

        response = llm.invoke(prompt_text)
        raw_text = response.content if hasattr(response, "content") else str(response)

        # Strip accidental markdown fences
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        raw_text = raw_text.strip().rstrip("```").strip()

        questions = _json.loads(raw_text)

        # Validate each question
        validated = []
        for item in questions:
            if not all(k in item for k in ("q", "options", "answer", "explanation", "topic")):
                continue
            if not isinstance(item["options"], list) or len(item["options"]) != 4:
                continue
            if not isinstance(item["answer"], int) or not (0 <= item["answer"] <= 3):
                continue
            # Skip if too similar to an already-used question
            q_lower = item["q"].lower()
            if any(q_lower[:40] in uq.lower() for uq in used_questions):
                continue
            validated.append(item)

        logger.info(f"Generated {len(validated)} valid AI quiz questions for {subject_name}")
        return validated[:num_questions]

    except Exception as exc:
        logger.error(f"AI quiz generation error for {subject_name}: {exc}")
        return []

# =============================================================================
#  PYDANTIC REQUEST / RESPONSE MODELS
# =============================================================================

class RegisterRequest(BaseModel):
    username: str
    password: str
    dob:      str = ""
    school:   str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    username:     str


class SubjectsUpdateRequest(BaseModel):
    subjects: List[str]


class AskRequest(BaseModel):
    question: str
    language: str = "English"


class AskResponse(BaseModel):
    answer:      str
    language:    str
    source_page: Optional[int] = None   # PDF page the answer came from
    pdf_path:    Optional[str] = None   # which PDF file


class QuizExplainRequest(BaseModel):
    question:       str
    correct_answer: str
    fallback:       str
    language:       str = "English"


class QuizSubmitRequest(BaseModel):
    subject:         str
    unit:            str
    score:           int
    total_questions: int = 3


class QuizSubmitResponse(BaseModel):
    coins_earned: int
    total_coins:  int


class PDFPageResponse(BaseModel):
    text:        str
    page:        int
    total_pages: int
    language:    str


class AIQuizGenerateRequest(BaseModel):
    subject:          str
    num_questions:    int = 5
    context_topics:   List[str] = []   # topics the user explored (AI chat / study units)
    used_questions:   List[str] = []   # question texts already seen — never repeat these
    language:         str = "English"


class AIQuizQuestion(BaseModel):
    q:           str
    options:     List[str]
    answer:      int          # index of correct option
    explanation: str
    topic:       str


class AIQuizGenerateResponse(BaseModel):
    questions: List[AIQuizQuestion]
    language:  str


# =============================================================================
#  FASTAPI APPLICATION
# =============================================================================

app = FastAPI(
    title="eThute Lenna API",
    description=(
        "Grade 12 Study Assistant — REST API + Frontend\n\n"
        "**Stack**: FastAPI · DeepSeek (OpenRouter) · ChromaDB · HuggingFace Embeddings\n\n"
        "All protected routes require `Authorization: Bearer <token>` from `/auth/login`."
    ),
    version="5.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ethutelenna-finalland-app5.onrender.com",   # Render (same-server requests)
        "https://ethutelenna-finalland-app5.pages.dev",      # Cloudflare Pages default domain
        # Add your custom domain below if you connect one in Cloudflare:
        # "https://www.yourdomain.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# =============================================================================
#  FRONTEND ROUTES
# =============================================================================

@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
def serve_landing():
    index_path = Path("index.html")
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>eThute Lenna</h1><p>Place index.html in the project root.</p>")


@app.get("/app", response_class=HTMLResponse, tags=["Frontend"])
def serve_app():
    app_path = Path("app.html")
    if app_path.exists():
        return HTMLResponse(content=app_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>App not found</h1><p>Place app.html in the project root.</p>")


# =============================================================================
#  HEALTH CHECK
# =============================================================================

@app.get("/health", tags=["System"])
def health_check():
    return {
        "status":    "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "model":     DEEPSEEK_CHAT_MODEL,
        "version":   "5.0.0",
    }


# =============================================================================
#  AUTH ROUTES
# =============================================================================

@app.post("/auth/register", tags=["Auth"], status_code=201)
def auth_register(body: RegisterRequest):
    if not body.username.strip() or not body.password:
        raise HTTPException(status_code=400, detail="Username and password are required.")
    if not register_user(body.username.strip(), body.password, body.dob, body.school):
        raise HTTPException(status_code=409, detail="Username already taken. Please choose another.")
    token = create_access_token(body.username.strip())
    return TokenResponse(access_token=token, username=body.username.strip())


@app.post("/auth/login", tags=["Auth"], response_model=TokenResponse)
def auth_login(body: LoginRequest):
    if not login_user(body.username, body.password):
        raise HTTPException(status_code=401, detail="Incorrect username or password.")
    token = create_access_token(body.username)
    return TokenResponse(access_token=token, username=body.username)


# =============================================================================
#  USER PROFILE ROUTES
# =============================================================================

@app.get("/user/subjects", tags=["User"])
def user_get_subjects(current_user: str = Depends(get_current_user)):
    return {"username": current_user, "subjects": get_user_subjects(current_user)}


@app.put("/user/subjects", tags=["User"])
def user_set_subjects(body: SubjectsUpdateRequest,
                      current_user: str = Depends(get_current_user)):
    invalid = [s for s in body.subjects if s not in SUBJECT_CATALOGUE]
    if invalid:
        raise HTTPException(status_code=400,
                            detail=f"Unknown subjects: {invalid}. Valid: {ALL_SUBJECT_NAMES}")
    save_user_subjects(current_user, body.subjects)
    return {"username": current_user, "subjects": body.subjects}


@app.get("/user/coins", tags=["User"])
def user_get_coins(current_user: str = Depends(get_current_user)):
    return {"username": current_user, "coins": get_user_coins(current_user)}


@app.get("/user/tracking", tags=["User"])
def user_get_tracking(current_user: str = Depends(get_current_user)):
    records = get_tracking(current_user)
    coins   = get_user_coins(current_user)
    total   = len(records)
    avg     = (
        round(sum(r["score"] / max(r.get("total_questions", 3), 1) for r in records) / total * 100)
        if total else 0
    )
    return {
        "username":          current_user,
        "coins":             coins,
        "quizzes_done":      total,
        "average_score_pct": avg,
        "records":           records,
    }


# =============================================================================
#  SUBJECT CATALOGUE ROUTES
# =============================================================================

@app.get("/subjects", tags=["Subjects"])
def list_subjects(current_user: str = Depends(get_current_user)):
    return {
        "subjects": [
            {
                "name":       name,
                "emoji":      data["emoji"],
                "color":      data["color"],
                "unit_count": len(data["units"]),
                "quiz_count": len(data["quiz"]),
                "units":      data["units"],
                "quiz":       data["quiz"],
                "tips":       data["tips"],
            }
            for name, data in SUBJECT_CATALOGUE.items()
        ]
    }


@app.get("/subjects/{subject_name}", tags=["Subjects"])
def get_subject(subject_name: str, current_user: str = Depends(get_current_user)):
    data = SUBJECT_CATALOGUE.get(subject_name)
    if not data:
        raise HTTPException(status_code=404, detail=f"Subject '{subject_name}' not found.")
    return {"name": subject_name, **data}


@app.get("/subjects/{subject_name}/guide-page", tags=["Subjects"],
         response_model=PDFPageResponse)
def subject_guide_page(subject_name: str, page: int = 1, language: str = "English",
                       current_user: str = Depends(get_current_user)):
    if subject_name not in SUBJECT_CATALOGUE:
        raise HTTPException(status_code=404, detail=f"Subject '{subject_name}' not found.")
    pdf_path = find_guide_for_subject(subject_name)
    if not pdf_path:
        raise HTTPException(status_code=404,
                            detail=f"No study guide PDF found for '{subject_name}'. Add a PDF to study_guides/.")
    lang_code   = LANGUAGES.get(language, LANGUAGES["English"])["trans_dest"]
    total_pages = count_pdf_pages(pdf_path)
    text        = extract_pdf_page(pdf_path, page, lang_code)
    return PDFPageResponse(text=text, page=page, total_pages=total_pages, language=language)


# FIX: Restored correct indentation — all lines now inside the function body

def _render_page_png(pdf_path: str, page_num: int, dpi: int = 150) -> tuple:
    """Render PDF page to PNG using PyMuPDF. Returns (png_bytes, total_pages)."""
    try:
        import fitz
    except ImportError:
        raise RuntimeError("PyMuPDF not installed. Run: pip install pymupdf")
    doc = fitz.open(pdf_path)
    total = len(doc)
    if page_num < 1 or page_num > total:
        doc.close()
        raise ValueError(f"Page {page_num} out of range (1-{total}).")
    page = doc[page_num - 1]
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72), alpha=False)
    png = pix.tobytes("png")
    doc.close()
    return png, total


@app.get("/subjects/{subject_name}/page-image", tags=["Subjects"])
def subject_page_image(subject_name: str, page: int = 1,
                       current_user: str = Depends(get_current_user)):
    """
    Render a single PDF page from the subject's study guide as a PNG image.
    Returns the image as a StreamingResponse so the browser can display it directly.
    No external API needed — uses pdftoppm (poppler-utils) installed on the server.
    """
    import subprocess, tempfile, glob
    from fastapi.responses import StreamingResponse
    import io

    if subject_name not in SUBJECT_CATALOGUE:
        raise HTTPException(status_code=404, detail=f"Subject '{subject_name}' not found.")
    pdf_path = find_guide_for_subject(subject_name)
    if not pdf_path:
        raise HTTPException(status_code=404,
                            detail=f"No study guide PDF found for '{subject_name}'.")
    total = count_pdf_pages(pdf_path)
    if page < 1 or page > total:
        raise HTTPException(status_code=400,
                            detail=f"Page {page} out of range (1–{total}).")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            # pdftoppm renders page N to {tmp}/pg-N.png (1-indexed via -f/-l)
            out_prefix = f"{tmp}/pg"
            subprocess.run(
                ["pdftoppm", "-r", "150", "-png", "-f", str(page), "-l", str(page),
                 pdf_path, out_prefix],
                check=True, capture_output=True
            )
            # Find the generated file
            matches = glob.glob(f"{out_prefix}*.png")
            if not matches:
                raise HTTPException(status_code=500, detail="Could not render PDF page.")
            with open(matches[0], "rb") as f:
                image_bytes = f.read()
        return StreamingResponse(io.BytesIO(image_bytes), media_type="image/png",
                                 headers={"Cache-Control": "public, max-age=3600"})
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500,
                            detail=f"pdftoppm error: {e.stderr.decode()[:200]}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Image render error: {exc}")


@app.post("/subjects/{subject_name}/ask", tags=["Subjects"], response_model=AskResponse)
def subject_ask(subject_name: str, body: AskRequest,
                current_user: str = Depends(get_current_user)):
    if subject_name not in SUBJECT_CATALOGUE:
        raise HTTPException(status_code=404, detail=f"Subject '{subject_name}' not found.")
    all_pdf_paths = find_all_pdfs_for_subject(subject_name)
    if not all_pdf_paths:
        all_guides = get_available_study_guides()
        all_papers = get_available_previous_papers()
        raise HTTPException(
            status_code=404,
            detail=(
                f"No PDFs found for '{subject_name}'. "
                f"Available study guides: {list(all_guides.keys())}. "
                f"Available previous papers: {list(all_papers.keys())}. "
                f"Rename your PDF files to include a keyword like 'physics' in the filename."
            ),
        )
    vector_db = load_subject_db_multi(subject_name, all_pdf_paths)
    if not vector_db:
        raise HTTPException(
            status_code=503,
            detail="Could not build the vector store. Check that your PDF files are valid.",
        )
    answer, source_page, source_pdf = answer_question_from_guide(body.question, vector_db)
    lang_code = LANGUAGES.get(body.language, LANGUAGES["English"])["trans_dest"]
    if lang_code != "en":
        answer = translate_text(answer, lang_code)
    return AskResponse(answer=answer, language=body.language,
                       source_page=source_page, pdf_path=source_pdf)


@app.post("/subjects/{subject_name}/quiz/explain", tags=["Subjects"])
def subject_quiz_explain(subject_name: str, body: QuizExplainRequest,
                         current_user: str = Depends(get_current_user)):
    if subject_name not in SUBJECT_CATALOGUE:
        raise HTTPException(status_code=404, detail=f"Subject '{subject_name}' not found.")
    pdf_path    = find_guide_for_subject(subject_name)
    vector_db   = load_subject_db(subject_name, pdf_path) if pdf_path else None
    explanation = explain_quiz_answer(body.question, body.correct_answer, body.fallback, vector_db)
    lang_code   = LANGUAGES.get(body.language, LANGUAGES["English"])["trans_dest"]
    if lang_code != "en":
        explanation = translate_text(explanation, lang_code)
    return {"explanation": explanation, "language": body.language}



# =============================================================================
#  AI QUIZ GENERATION ENDPOINT
# =============================================================================

@app.post("/subjects/{subject_name}/quiz/generate", tags=["Quiz"],
          response_model=AIQuizGenerateResponse)
def generate_quiz(subject_name: str, body: AIQuizGenerateRequest,
                  current_user: str = Depends(get_current_user)):
    """
    Generate fresh, non-repeating quiz questions from uploaded PDFs.
    Pass context_topics (what the student studied/asked about) so questions
    are relevant to their session. Pass used_questions to avoid repetition.
    """
    if subject_name not in SUBJECT_CATALOGUE:
        raise HTTPException(status_code=404, detail=f"Subject '{subject_name}' not found.")

    all_pdf_paths = find_all_pdfs_for_subject(subject_name)
    if not all_pdf_paths:
        raise HTTPException(
            status_code=404,
            detail=f"No PDFs found for '{subject_name}'. Upload study guides or previous papers.",
        )

    vector_db = load_subject_db_multi(subject_name, all_pdf_paths)
    if not vector_db:
        raise HTTPException(
            status_code=503,
            detail="Could not build the vector store. Check that your PDF files are valid.",
        )

    num_q = max(3, min(body.num_questions, 15))  # clamp between 3 and 15
    questions = generate_ai_quiz(
        subject_name=subject_name,
        vector_db=vector_db,
        num_questions=num_q,
        context_topics=body.context_topics,
        used_questions=body.used_questions,
    )

    if not questions:
        raise HTTPException(
            status_code=500,
            detail="Could not generate quiz questions. The PDF content may be insufficient.",
        )

    lang_code = LANGUAGES.get(body.language, LANGUAGES["English"])["trans_dest"]
    if lang_code != "en":
        for item in questions:
            item["q"]           = translate_text(item["q"], lang_code)
            item["explanation"] = translate_text(item["explanation"], lang_code)
            item["options"]     = [translate_text(o, lang_code) for o in item["options"]]

    return AIQuizGenerateResponse(questions=questions, language=body.language)

# =============================================================================
#  QUIZ SUBMISSION ROUTE
# =============================================================================

@app.post("/quiz/submit", tags=["Quiz"], response_model=QuizSubmitResponse)
def quiz_submit(body: QuizSubmitRequest, current_user: str = Depends(get_current_user)):
    if body.subject not in SUBJECT_CATALOGUE:
        raise HTTPException(status_code=400, detail=f"Unknown subject: '{body.subject}'.")
    if not (0 <= body.score <= body.total_questions):
        raise HTTPException(status_code=400,
                            detail=f"Score ({body.score}) must be between 0 and {body.total_questions}.")
    tips         = SUBJECT_CATALOGUE[body.subject].get("tips", [])
    coins_earned = save_tracking(current_user, body.subject, body.unit,
                                 body.score, tips, body.total_questions)
    return QuizSubmitResponse(coins_earned=coins_earned,
                              total_coins=get_user_coins(current_user))


# =============================================================================
#  STUDY GUIDES ROUTES
# =============================================================================

@app.get("/study-guides", tags=["Study Guides"])
def list_study_guides(subject: Optional[str] = None,
                      current_user: str = Depends(get_current_user)):
    all_guides  = get_available_study_guides()
    filtered    = _filter_pdfs_by_subject(all_guides, subject) if subject else all_guides
    guides_list = []
    for name, path in filtered.items():
        try:
            size_mb = round(os.path.getsize(path) / 1_048_576, 2)
            total_pages = count_pdf_pages(path)
        except Exception:
            size_mb = None
            total_pages = 0
        guides_list.append({"name": name, "path": path, "size_mb": size_mb, "total_pages": total_pages})
    return {"subject": subject, "guides": guides_list, "count": len(guides_list)}




@app.get("/study-guides/page-image", tags=["Study Guides"])
def study_guide_page_image(path: str, page: int = 1,
                            current_user: str = Depends(get_current_user)):
    """Render study guide page as PNG using PyMuPDF."""
    from fastapi.responses import StreamingResponse
    import io
    safe = os.path.normpath(path)
    if not safe.startswith("study_guides"):
        raise HTTPException(status_code=403, detail="Access denied.")
    if not os.path.isfile(safe):
        raise HTTPException(status_code=404, detail=f"File not found: {safe}")
    try:
        png, total = _render_page_png(safe, page)
        return StreamingResponse(io.BytesIO(png), media_type="image/png",
                                 headers={"X-Total-Pages": str(total), "Cache-Control": "public, max-age=3600"})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render error: {e}")


@app.get("/previous-papers/page-image", tags=["Previous Papers"])
def previous_paper_page_image(path: str, page: int = 1,
                               current_user: str = Depends(get_current_user)):
    """Render previous paper page as PNG using PyMuPDF."""
    from fastapi.responses import StreamingResponse
    import io
    safe = os.path.normpath(path)
    if not safe.startswith("previous_papers"):
        raise HTTPException(status_code=403, detail="Access denied.")
    if not os.path.isfile(safe):
        raise HTTPException(status_code=404, detail=f"File not found: {safe}")
    try:
        png, total = _render_page_png(safe, page)
        return StreamingResponse(io.BytesIO(png), media_type="image/png",
                                 headers={"X-Total-Pages": str(total), "Cache-Control": "public, max-age=3600"})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render error: {e}")


@app.get("/study-guides/{subject}/page", tags=["Study Guides"], response_model=PDFPageResponse)
def study_guide_page(subject: str, guide_name: Optional[str] = None, page: int = 1,
                     language: str = "English", current_user: str = Depends(get_current_user)):
    all_guides = get_available_study_guides()
    filtered   = _filter_pdfs_by_subject(all_guides, subject)
    if not filtered:
        raise HTTPException(status_code=404, detail=f"No study guides found for '{subject}'.")
    path        = filtered[guide_name] if guide_name and guide_name in filtered else next(iter(filtered.values()))
    lang_code   = LANGUAGES.get(language, LANGUAGES["English"])["trans_dest"]
    total_pages = count_pdf_pages(path)
    text        = extract_pdf_page(path, page, lang_code)
    return PDFPageResponse(text=text, page=page, total_pages=total_pages, language=language)


# =============================================================================
#  PREVIOUS PAPERS ROUTES
# =============================================================================

@app.get("/previous-papers", tags=["Previous Papers"])
def list_previous_papers(subject: Optional[str] = None,
                         current_user: str = Depends(get_current_user)):
    """
    Return all previous papers grouped by subject, each as a flat list
    with year, month, paper number (P1/P2), and file path.
    """
    all_papers       = get_available_previous_papers()
    subjects_to_scan = [subject] if subject else PAPER_SUBJECTS
    result: Dict[str, Any] = {}

    months_re = re.compile(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', re.IGNORECASE)
    paper_re  = re.compile(r'[/\\][Pp](\d)[/\\]')       # matches /p1/ or \p2\
    paper_fn  = re.compile(r'\b[Pp]\s*(\d)\b')           # matches P1 or P2 in filename

    for subj in subjects_to_scan:
        filtered = _filter_pdfs_by_subject(all_papers, subj)
        papers_list = []
        for name, path in filtered.items():
            year = _extract_year(name)

            # Extract paper number from folder path first, then filename
            pm = paper_re.search(path) or paper_fn.search(path) or paper_fn.search(name)
            paper_num = f"P{pm.group(1)}" if pm else ""

            # Extract month from path or filename
            mm = months_re.search(path) or months_re.search(name)
            month = mm.group(1).capitalize()[:3] if mm else ""

            # Build clean label: "Physical Sciences (Physics) (P2, Nov, 2025)"
            parts = [p for p in [paper_num, month, year] if p]
            label = f"{subj} ({', '.join(parts)})" if parts else f"{subj} ({name})"

            papers_list.append({
                "label":  label,
                "path":   path,
                "year":   year,
                "month":  month,
                "paper":  paper_num,
            })

        # Sort: newest year first, then month (Nov before Jun), then P2 before P1
        month_order = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
                       "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12,"":0}
        papers_list.sort(key=lambda p: (
            -int(p["year"]) if p["year"].isdigit() else 0,
            -month_order.get(p["month"], 0),
            p["paper"]
        ))
        result[subj] = papers_list

    return {"papers": result}


@app.get("/previous-papers/{subject}/{year}/page", tags=["Previous Papers"],
         response_model=PDFPageResponse)
def previous_paper_page(subject: str, year: str, page: int = 1, language: str = "English",
                        current_user: str = Depends(get_current_user)):
    all_papers = get_available_previous_papers()
    filtered   = _filter_pdfs_by_subject(all_papers, subject)
    if not filtered:
        raise HTTPException(status_code=404, detail=f"No previous papers found for '{subject}'.")
    year_map: Dict[str, str] = {_extract_year(n): p for n, p in filtered.items()}
    if year not in year_map:
        available = sorted(year_map.keys(), reverse=True)
        raise HTTPException(status_code=404,
                            detail=f"No paper for {subject} — {year}. Available: {available}")
    path        = year_map[year]
    lang_code   = LANGUAGES.get(language, LANGUAGES["English"])["trans_dest"]
    total_pages = count_pdf_pages(path)
    text        = extract_pdf_page(path, page, lang_code)
    return PDFPageResponse(text=text, page=page, total_pages=total_pages, language=language)


# =============================================================================
#  ENTRY POINT
#  Railway: uvicorn main:app --host 0.0.0.0 --port $PORT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
