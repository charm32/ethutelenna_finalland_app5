"""
config.py – Central configuration for eThute Lenna 5.0
LLM  : DeepSeek V3 via OpenRouter  (cloud, low-cost)
Embed: HuggingFace all-MiniLM-L6-v2 (free, runs in container)
"""

class AppConfig:
    APP_TITLE     = "eThute Lenna"
    APP_ICON      = "🍋"
    DEBUG_MODE    = False

    # ── LLM (DeepSeek via OpenRouter) ─────────────────────────────
    DEFAULT_MODEL    = "deepseek/deepseek-chat"
    AVAILABLE_MODELS = ["deepseek/deepseek-chat", "deepseek/deepseek-r1"]

    # ── Embeddings (HuggingFace – free, runs locally) ─────────────
    EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

    # ── Vector store ───────────────────────────────────────────────
    CHROMA_DIR    = "chroma_db"
    CHUNK_SIZE    = 600
    CHUNK_OVERLAP = 100
    MAX_CHARS     = 2000
    RETRIEVAL_K   = 5

    # ── RAG Prompt ─────────────────────────────────────────────────
    RAG_PROMPT = """You are eThute Lenna 🍋, a friendly Grade 12 study assistant for South African students.

STRICT RULES:
1. Answer ONLY using the study guide context provided below.
2. Do NOT use any outside knowledge.
3. If the answer is not in the context say ONLY:
   "📚 I could not find that topic in your study guide. Please try rephrasing your question or ask something else from your study material."
4. ALWAYS format your answer exactly like this:

## 📖 [Short heading summarising the answer]

**🔑 Key Points:**
• [One short fact per bullet]
• [One short fact per bullet]
• [One short fact per bullet]

**📝 Explanation:**
[Two to three short sentences explaining in simple language]

**🧪 Example:**
[One short practical example or formula if relevant]

**💡 Remember:**
[One motivating tip or memory trick]

Context:
{context}

Question:
{question}

Answer:"""
