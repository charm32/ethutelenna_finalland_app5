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
    "Physics": {
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
    "Chemistry": {
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

SUBJECT_PDF_MAP: Dict[str, List[str]] = {
    "Physics":       ["physics"],
    "Chemistry":     ["chemistry"],
    "Mathematics":   ["mathematics", "maths grade", "math grade"],
    "Math Literacy": ["maths_lit", "maths lit", "math lit", "mathematical literacy", "mathslit"],
    "Life Sciences": ["life science", "biology", "life_science"],
    "Geography":     ["geography", "geo"],
    "History":       ["history"],
    "English":       ["english"],
}

GUIDE_SUBJECTS = ["Physics", "Chemistry", "Mathematics", "Mathematics Literacy"]
PAPER_SUBJECTS = ["Physics", "Chemistry", "Mathematics", "Mathematics Literacy"]


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
    return {
        pdf.stem.replace("_", " ").replace("-", " "): str(pdf)
        for pdf in sorted(papers_dir.glob("*.pdf"))
    }


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
    """
    ✅ NEW — returns ALL PDFs for a subject from BOTH study_guides/ and previous_papers/.
    This powers the Ask AI button so it searches everything at once.
    """
    all_paths: List[str] = []
    guides  = get_available_study_guides()
    papers  = get_available_previous_papers()
    matched_guides = _filter_pdfs_by_subject(guides, subject)
    matched_papers = _filter_pdfs_by_subject(papers, subject)
    all_paths.extend(matched_guides.values())
    all_paths.extend(matched_papers.values())
    return list(set(all_paths))  # deduplicate


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
#  ✅ FIXED: load_subject_db_multi loads ALL PDFs (study guides + past papers)
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


@lru_cache(maxsize=1)
def get_embeddings():
    from langchain_huggingface import HuggingFaceEmbeddings
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


def load_subject_db(subject_name: str, pdf_path: str):
    """Load a single PDF into ChromaDB (used for quiz explanations)."""
    collection_name = f"ethute_{subject_name.replace(' ', '_').lower()}"
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
    """
    ✅ NEW — Load ALL PDFs for a subject (study guides + previous papers) into one
    ChromaDB collection. This is what powers the Ask AI button.
    The collection name uses '_multi' suffix to distinguish from single-PDF collections.
    """
    if not pdf_paths:
        return None
    collection_name = f"ethute_{subject_name.replace(' ', '_').lower()}_multi"
    chroma_path     = f"chroma_db/{collection_name}"
    try:
        embeddings = get_embeddings()
        # If already built, just load it
        if os.path.exists(chroma_path) and os.listdir(chroma_path):
            return Chroma(
                collection_name=collection_name,
                embedding_function=embeddings,
                persist_directory=chroma_path,
            )
        # Build from all PDFs
        all_chunks = []
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=AppConfig.CHUNK_SIZE,
            chunk_overlap=AppConfig.CHUNK_OVERLAP,
        )
        for pdf_path in pdf_paths:
            try:
                loader = PyPDFLoader(pdf_path)
                docs   = loader.load()
                if docs:
                    chunks = splitter.split_documents(docs)
                    for doc in chunks:
                        doc.page_content = doc.page_content[:AppConfig.MAX_CHARS]
                        # Tag each chunk with its source type
                        source = "previous_paper" if "previous_papers" in pdf_path else "study_guide"
                        doc.metadata["source_type"] = source
                    all_chunks.extend(chunks)
                    logger.info(f"Loaded {len(chunks)} chunks from {pdf_path}")
            except Exception as exc:
                logger.warning(f"Skipping {pdf_path}: {exc}")
        if not all_chunks:
            return None
        db = Chroma.from_documents(
            documents=all_chunks,
            embedding=embeddings,
            collection_name=collection_name,
            persist_directory=chroma_path,
        )
        logger.info(f"Built multi-PDF ChromaDB for {subject_name} with {len(all_chunks)} total chunks")
        return db
    except Exception as exc:
        logger.error(f"Multi-PDF ChromaDB error for {subject_name}: {exc}")
        return None


def clean_answer(text: str) -> str:
    lines   = text.splitlines()
    cleaned = [
        line for line in lines
        if not re.search(
            r"\[.*?(write|short|one |two |three |explain|heading|tip|example|summar|relevant).*?\]",
            line,
            re.IGNORECASE,
        )
    ]
    result = "\n".join(cleaned).strip()
    if len(result) < 30:
        return (
            "I could not find a clear answer in your study guide for that question. "
            "Please try rephrasing or ask something else."
        )
    return result


def answer_question_from_guide(question: str, vector_db) -> str:
    try:
        llm       = get_deepseek_llm(temperature=0)
        retriever = vector_db.as_retriever(
            search_type="similarity",
            search_kwargs={"k": AppConfig.RETRIEVAL_K},
        )
        prompt = ChatPromptTemplate.from_template(RAG_PROMPT)
        chain  = (
            {"context": retriever, "question": RunnablePassthrough()}
            | prompt | llm | StrOutputParser()
        )
        raw = chain.invoke(question)
        return clean_answer(raw)
    except Exception as exc:
        logger.error(f"RAG error: {exc}")
        raise HTTPException(status_code=500, detail=f"RAG pipeline error: {exc}")


def explain_quiz_answer(question: str, correct_answer: str,
                        fallback: str, vector_db) -> str:
    if vector_db is None:
        return fallback
    try:
        llm       = get_deepseek_llm(temperature=0)
        retriever = vector_db.as_retriever(search_type="similarity", search_kwargs={"k": 3})
        prompt    = ChatPromptTemplate.from_template(QUIZ_EXPLAIN_PROMPT)
        chain     = (
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
    answer:   str
    language: str


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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Serve static files (CSS, images, JS) from a /static folder ───────────────
# Create a static/ folder and place your logo/images there
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# =============================================================================
#  FRONTEND ROUTES — serves the HTML app
# =============================================================================

@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
def serve_landing():
    """Serve the landing page (index.html)."""
    index_path = Path("index.html")
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>eThute Lenna</h1><p>Place index.html in the project root.</p>")


@app.get("/app", response_class=HTMLResponse, tags=["Frontend"])
def serve_app():
    """Serve the main app dashboard (app.html)."""
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


@app.post("/subjects/{subject_name}/ask", tags=["Subjects"], response_model=AskResponse)
def subject_ask(subject_name: str, body: AskRequest,
                current_user: str = Depends(get_current_user)):
    """
    ✅ UPDATED — RAG Q&A searches ALL uploaded study guides AND previous papers
    for the selected subject. Answers are grounded in the student's own material.
    """
    if subject_name not in SUBJECT_CATALOGUE:
        raise HTTPException(status_code=404, detail=f"Subject '{subject_name}' not found.")

    # Get ALL PDFs for this subject (study guides + previous papers)
    all_pdf_paths = find_all_pdfs_for_subject(subject_name)

    if not all_pdf_paths:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No PDFs found for '{subject_name}'. "
                f"Please upload study guides to study_guides/ and/or previous papers to previous_papers/."
            ),
        )

    # Build or load the multi-PDF ChromaDB vector store
    vector_db = load_subject_db_multi(subject_name, all_pdf_paths)
    if not vector_db:
        raise HTTPException(
            status_code=503,
            detail="Could not build the vector store. Check that your PDF files are valid.",
        )

    answer    = answer_question_from_guide(body.question, vector_db)
    lang_code = LANGUAGES.get(body.language, LANGUAGES["English"])["trans_dest"]
    if lang_code != "en":
        answer = translate_text(answer, lang_code)
    return AskResponse(answer=answer, language=body.language)


@app.post("/subjects/{subject_name}/quiz/explain", tags=["Subjects"])
def subject_quiz_explain(subject_name: str, body: QuizExplainRequest,
                         current_user: str = Depends(get_current_user)):
    if subject_name not in SUBJECT_CATALOGUE:
        raise HTTPException(status_code=404, detail=f"Subject '{subject_name}' not found.")
    pdf_path  = find_guide_for_subject(subject_name)
    vector_db = load_subject_db(subject_name, pdf_path) if pdf_path else None
    explanation = explain_quiz_answer(body.question, body.correct_answer, body.fallback, vector_db)
    lang_code   = LANGUAGES.get(body.language, LANGUAGES["English"])["trans_dest"]
    if lang_code != "en":
        explanation = translate_text(explanation, lang_code)
    return {"explanation": explanation, "language": body.language}


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
    all_guides = get_available_study_guides()
    filtered   = _filter_pdfs_by_subject(all_guides, subject) if subject else all_guides
    guides_list = []
    for name, path in filtered.items():
        try:
            size_mb = round(os.path.getsize(path) / 1_048_576, 2)
        except Exception:
            size_mb = None
        guides_list.append({"name": name, "path": path, "size_mb": size_mb})
    return {"subject": subject, "guides": guides_list, "count": len(guides_list)}


@app.get("/study-guides/{subject}/page", tags=["Study Guides"], response_model=PDFPageResponse)
def study_guide_page(subject: str, guide_name: Optional[str] = None, page: int = 1,
                     language: str = "English", current_user: str = Depends(get_current_user)):
    all_guides = get_available_study_guides()
    filtered   = _filter_pdfs_by_subject(all_guides, subject)
    if not filtered:
        raise HTTPException(status_code=404, detail=f"No study guides found for '{subject}'.")
    path      = filtered[guide_name] if guide_name and guide_name in filtered else next(iter(filtered.values()))
    lang_code = LANGUAGES.get(language, LANGUAGES["English"])["trans_dest"]
    total_pages = count_pdf_pages(path)
    text        = extract_pdf_page(path, page, lang_code)
    return PDFPageResponse(text=text, page=page, total_pages=total_pages, language=language)


# =============================================================================
#  PREVIOUS PAPERS ROUTES
# =============================================================================

@app.get("/previous-papers", tags=["Previous Papers"])
def list_previous_papers(subject: Optional[str] = None,
                         current_user: str = Depends(get_current_user)):
    all_papers       = get_available_previous_papers()
    subjects_to_scan = [subject] if subject else PAPER_SUBJECTS
    result: Dict[str, Any] = {}
    for subj in subjects_to_scan:
        filtered: Dict[str, str] = _filter_pdfs_by_subject(all_papers, subj)
        year_map: Dict[str, str] = {}
        for name, path in filtered.items():
            year_map[_extract_year(name)] = path
        result[subj] = {"years": sorted(year_map.keys(), reverse=True), "year_paths": year_map}
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
