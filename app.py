import os
import re
import hmac
import difflib
import threading

import numpy as np

from io import BytesIO
from pathlib import Path
from functools import wraps
from collections import Counter

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.utils import secure_filename

from pypdf import PdfReader
from docx import Document as WordDocument

from sklearn.feature_extraction.text import (
    TfidfVectorizer,
    ENGLISH_STOP_WORDS
)
from sklearn.metrics.pairwise import cosine_similarity


# ==================================================
# 1. FLASK CONFIGURATION
# ==================================================

app = Flask(__name__)
CORS(app)

app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

DATABASE_PATH = os.path.join(INSTANCE_DIR, "egerai.db")

app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///" + DATABASE_PATH.replace("\\", "/")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ==================================================
# 2. SETTINGS
# ==================================================

# Words that describe the REQUEST, not the TOPIC.
# (Do not add words like "mate" or "man": they can be real topics.)
QUESTION_FILLERS = {
    "define", "explain", "describe", "tell", "give", "show", "list",
    "please", "briefly", "meaning", "discuss", "outline", "state",
    "elaborate", "mean", "means", "about", "whats",
    "bro", "bruh", "dude"
}

STOP_WORD_SET = set(ENGLISH_STOP_WORDS | QUESTION_FILLERS)
STOP_WORDS = list(STOP_WORD_SET)

# Expanded ONLY when the word never appears in your documents.
ABBREVIATIONS = {
    "plf": "precision livestock farming",
}

CHUNK_WORDS = 120           # long sections are split into chunks this size
MIN_BODY_WORDS = 8          # text a section needs before a new heading
                            # may start another section
MIN_PASSAGE_WORDS = 25      # shorter passages are scored down (floor 0.5)

MINIMUM_SCORE = 0.06        # below this: no answer
CONFIDENT_SCORE = 0.20      # at or above this: confidence = "high"
SUGGESTION_FLOOR = 0.02

HEADING_BONUS = 0.35        # question words found in a section title
EXACT_HEADING_BONUS = 0.45  # ALL question words found in a section title

# Optional: explain the retrieved text in simple English using Claude.
# Active only when ANTHROPIC_API_KEY is set and `anthropic` is installed.
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "claude-haiku-5-5")


# ==================================================
# 3. ADMIN AUTHENTICATION
# ==================================================

def admin_required(route_function):

    @wraps(route_function)
    def wrapper(*args, **kwargs):

        if request.method == "OPTIONS":
            return route_function(*args, **kwargs)

        admin_password = os.environ.get("ADMIN_PASSWORD")

        if not admin_password:
            app.logger.error("ADMIN_PASSWORD is not configured.")
            return jsonify({
                "error": "Administrator authentication is not configured."
            }), 503

        authorization = request.headers.get("Authorization", "")
        supplied_password = ""

        if authorization.startswith("Bearer "):
            supplied_password = authorization[len("Bearer "):]

        if not hmac.compare_digest(supplied_password, admin_password):
            return jsonify({"error": "Unauthorized."}), 401

        return route_function(*args, **kwargs)

    return wrapper


# ==================================================
# 4. DATABASE MODELS
# ==================================================

class Knowledge(db.Model):

    __tablename__ = "knowledge"

    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(200), nullable=False)
    keywords = db.Column(db.String(500), nullable=False)
    answer = db.Column(db.Text, nullable=False)


class Document(db.Model):

    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    extracted_text = db.Column(db.Text, nullable=False)
    uploaded_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp()
    )


with app.app_context():

    db.create_all()

    print("====================================")
    print("EGER AI DATABASE INITIALIZED")
    print("====================================")
    print("Knowledge records:", Knowledge.query.count())
    print("Stored documents:", Document.query.count())


# ==================================================
# 5. TEXT HELPERS
# ==================================================

def clean_text(text):

    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_question(question):

    question = str(question or "").strip()

    question = re.sub(
        r"^(bro+|bruh+|dude|mate|man)[\s,!?]*",
        "",
        question,
        flags=re.IGNORECASE
    )

    question = re.sub(
        r"[\s,!?]+\b(bro+|bruh+|dude|mate|man)\b[.!?]*$",
        "",
        question,
        flags=re.IGNORECASE
    )

    return question.strip()


def prepare_query(text, vocabulary):

    """Turn a student's question into search terms:
    1. drop filler words ("explain", "the", "bro" ...)
    2. keep words that exist in the documents exactly as typed
    3. expand an abbreviation only if the documents never use it
    4. fix likely typos using words from the documents
    """

    vocab_words = [w for w in vocabulary if " " not in w]

    terms = []

    for word in clean_text(text).split():

        if word in STOP_WORD_SET:
            continue

        if word in vocabulary:
            terms.append(word)
            continue

        if word in ABBREVIATIONS:
            terms.extend(ABBREVIATIONS[word].split())
            continue

        if len(word) >= 4:

            close = difflib.get_close_matches(
                word,
                vocab_words,
                n=1,
                cutoff=0.75
            )

            if close:
                terms.append(close[0])
                continue

        terms.append(word)

    return " ".join(terms)


# ==================================================
# 6. FOLLOW-UP QUESTIONS
# ==================================================

def recognize_followup(question):

    cleaned = clean_text(question)

    followup_patterns = {

        "simplify": [
            "simplify", "simplify that", "simplify it",
            "make it simple", "make it easier", "explain simply",
            "in simple english", "easy english"
        ],

        "examples": [
            "examples", "give examples", "some examples",
            "show examples", "example please", "give me examples"
        ],

        "explain": [
            "explain that", "explain it", "explain further",
            "elaborate", "elaborate on that", "tell me more",
            "more details", "go deeper", "expand on that"
        ],

        "why": [
            "why", "why is that", "why is that so", "how come"
        ],

        "continue": [
            "continue", "go on", "proceed", "continue explaining"
        ],

        "summarize": [
            "summarize", "summarise", "short summary",
            "summarize that", "summarise that"
        ],

        "clarify": [
            "what do you mean", "what do you mean by that",
            "what does that mean", "clarify",
            "i dont understand", "i do not understand"
        ]
    }

    for intent, phrases in followup_patterns.items():
        if cleaned in phrases:
            return intent

    return None


def build_contextual_question(user_question, previous_question):

    intent = recognize_followup(user_question)

    if not intent or not previous_question:
        return user_question, None

    intent_keywords = {
        "simplify": "simple explanation",
        "examples": "examples applications",
        "explain": "explanation details",
        "why": "reasons causes importance",
        "continue": "further explanation",
        "summarize": "summary main points",
        "clarify": "definition explanation"
    }

    return (
        previous_question + " " + intent_keywords.get(intent, ""),
        intent
    )


# ==================================================
# 7. DOCUMENT STRUCTURE
# A document becomes pages (slides) -> sections (a heading
# plus its text). One section is one searchable passage.
# ==================================================

BULLET_RE = re.compile(r"^\s*(?:[•●▪◦‣\-\*–—]|\d+\s*[\.\)])")

HEADING_PATTERNS = [
    r"^scope of\b", r"^introduction to\b", r"^objectives? of\b",
    r"^importance of\b", r"^advantages of\b", r"^disadvantages of\b",
    r"^benefits of\b", r"^definition of\b", r"^types of\b",
    r"^classification of\b", r"^applications? of\b",
    r"^principles of\b", r"^components of\b", r"^challenges of\b",
    r"^characteristics of\b", r"^functions? of\b",
    r"^factors affecting\b", r"^methods of\b",
    r"^conclusion\b", r"^references\b"
]


def is_heading(line):

    text = line.strip()
    words = text.split()

    if not words or len(words) > 12:
        return False

    if BULLET_RE.match(text):
        return False

    if text[-1] in ".,;:!?":
        return False

    lowered = text.lower()

    if any(re.match(pattern, lowered) for pattern in HEADING_PATTERNS):
        return True

    if text.isupper():
        return True

    return text[0].isupper() and len(words) <= 7


def split_pages(text):

    text = text or ""

    if "\f" in text:
        return [page for page in text.split("\f") if page.strip()]

    return [text] if text.strip() else []


def line_key(line):

    """Normalised form used to spot running headers and footers."""

    line = re.sub(r"\d+$", "", line.strip().lower())

    return re.sub(r"\s+", " ", line).strip()


def strip_running_lines(pages):

    """Remove header/footer lines that repeat on many pages, e.g.
    'INTRODUCTION TO PRECISION LIVESTOCK FARMING1'."""

    if len(pages) < 3:
        return pages

    counts = Counter()

    for page in pages:

        keys = {
            line_key(line)
            for line in page.splitlines()
            if line.strip()
        }

        counts.update(key for key in keys if key)

    threshold = max(3, int(len(pages) * 0.4))

    repeated = {
        key for key, count in counts.items()
        if count >= threshold
    }

    cleaned_pages = []

    for page in pages:

        kept = [
            line for line in page.splitlines()
            if line.strip() and line_key(line) not in repeated
        ]

        cleaned_pages.append("\n".join(kept))

    return cleaned_pages


def split_page_into_sections(page):

    """Returns a list of (heading, [lines])."""

    lines = [line.strip() for line in page.splitlines() if line.strip()]

    sections = []
    current_heading = ""
    current_lines = []
    body_words = 0

    for line in lines:

        heading_like = is_heading(line)

        if heading_like and current_lines and body_words >= MIN_BODY_WORDS:

            sections.append((current_heading, current_lines))

            current_heading = line
            current_lines = [line]
            body_words = 0
            continue

        if heading_like and not current_heading:
            current_heading = line

        if not heading_like:
            body_words += len(line.split())

        current_lines.append(line)

    if current_lines:
        sections.append((current_heading, current_lines))

    return sections


def chunk_lines(lines, size):

    """Group lines into chunks of at most `size` words."""

    chunks = []
    current = []
    count = 0

    for line in lines:

        words = line.split()

        pieces = [
            " ".join(words[i:i + size])
            for i in range(0, len(words), size)
        ] or [line]

        for piece in pieces:

            n = len(piece.split())

            if current and count + n > size:
                chunks.append(current)
                current = []
                count = 0

            current.append(piece)
            count += n

    if current:
        chunks.append(current)

    return chunks


# ==================================================
# 8. SEARCH INDEX (no database access in this section)
# ==================================================

def make_index(rows):

    """rows: list of dicts with id, title, category, text."""

    sections = []

    for row in rows:

        pages = strip_running_lines(split_pages(row["text"]))

        for page_number, page in enumerate(pages, start=1):

            for heading, lines in split_page_into_sections(page):

                heading = heading or (lines[0] if lines else "")

                heading_terms = (
                    set(clean_text(heading).split()) - STOP_WORD_SET
                )

                for position, chunk in enumerate(
                    chunk_lines(lines, CHUNK_WORDS)
                ):

                    text = "\n".join(chunk)

                    sections.append({
                        "document_id": row["id"],
                        "title": row["title"],
                        "category": row["category"],
                        "page": page_number,
                        "heading": heading,
                        "text": text,
                        "continued": position > 0,
                        "heading_terms": heading_terms,
                        "search_text": clean_text(heading + " " + text)
                    })

    index = {
        "sections": sections,
        "vectorizer": None,
        "matrix": None,
        "length_factor": None
    }

    if not sections:
        return index

    try:

        vectorizer = TfidfVectorizer(
            stop_words=STOP_WORDS,
            ngram_range=(1, 2),
            sublinear_tf=True
        )

        matrix = vectorizer.fit_transform(
            [section["search_text"] for section in sections]
        )

    except ValueError:
        app.logger.warning("Could not build the document search index.")
        return index

    index["vectorizer"] = vectorizer
    index["matrix"] = matrix
    index["length_factor"] = np.array([
        min(
            1.0,
            max(0.5, len(section["text"].split()) / MIN_PASSAGE_WORDS)
        )
        for section in sections
    ])

    return index


def query_index(index, question):

    """Returns {"best": section or None, "suggestions": [...]}."""

    empty = {"best": None, "suggestions": []}

    if index["vectorizer"] is None:
        return empty

    terms = prepare_query(question, index["vectorizer"].vocabulary_)

    if not terms:
        return empty

    question_vector = index["vectorizer"].transform([terms])

    if question_vector.nnz == 0:
        return empty

    term_set = set(terms.split())

    tfidf_scores = cosine_similarity(
        question_vector,
        index["matrix"]
    ).flatten()

    sections = index["sections"]

    scores = np.zeros(len(sections))

    for i, section in enumerate(sections):

        heading_terms = section["heading_terms"]

        heading_share = len(term_set & heading_terms) / len(term_set)

        exact_heading = (
            1.0 if heading_terms and term_set <= heading_terms else 0.0
        )

        scores[i] = (
            tfidf_scores[i]
            + HEADING_BONUS * heading_share
            + EXACT_HEADING_BONUS * exact_heading
        ) * index["length_factor"][i]

    ranked = scores.argsort()[::-1]
    best_index = int(ranked[0])
    best_score = float(scores[best_index])

    # Nothing relevant enough: offer the closest sections instead.
    if best_score < MINIMUM_SCORE:

        suggestions = []

        for i in ranked[:3]:

            score = float(scores[int(i)])

            if score < SUGGESTION_FLOOR:
                break

            item = sections[int(i)]

            suggestions.append({
                "document_title": item["title"],
                "page": item["page"],
                "heading": item["heading"],
                "similarity": round(score, 4),
                "preview": item["text"][:300]
            })

        return {"best": None, "suggestions": suggestions}

    best = dict(sections[best_index])
    best["similarity"] = round(best_score, 4)
    best["confidence"] = "high" if best_score >= CONFIDENT_SCORE else "low"

    # A long section was split into chunks: add the following ones.
    answer_parts = [best["text"]]

    next_index = best_index + 1

    while (
        next_index < len(sections)
        and len(answer_parts) < 3
        and sections[next_index]["continued"]
        and sections[next_index]["document_id"] == best["document_id"]
        and sections[next_index]["page"] == best["page"]
        and sections[next_index]["heading"] == best["heading"]
    ):
        answer_parts.append(sections[next_index]["text"])
        next_index += 1

    best["answer_text"] = "\n".join(answer_parts)

    return {"best": best, "suggestions": []}


# ==================================================
# 9. DATABASE-BACKED INDEX (cached)
# ==================================================

_index_cache = {"key": None, "index": None}
_index_lock = threading.Lock()


def invalidate_index():

    with _index_lock:
        _index_cache["key"] = None
        _index_cache["index"] = None


def get_index():

    with _index_lock:

        # Cheap check first: never load document text on every request.
        count, latest_id = db.session.query(
            db.func.count(Document.id),
            db.func.max(Document.id)
        ).one()

        key = (count, latest_id or 0)

        if (
            _index_cache["key"] == key
            and _index_cache["index"] is not None
        ):
            return _index_cache["index"]

        rows = [
            {
                "id": document.id,
                "title": document.title,
                "category": document.category,
                "text": document.extracted_text
            }
            for document in Document.query.order_by(Document.id).all()
        ]

        _index_cache["index"] = make_index(rows)
        _index_cache["key"] = key

        return _index_cache["index"]


def search_documents(user_question):

    return query_index(get_index(), user_question)


# ==================================================
# 10. SEARCH KNOWLEDGE DATABASE
# ==================================================

def search_knowledge(user_question):

    cleaned_question = clean_text(user_question)
    question_words = set(cleaned_question.split())

    if not question_words:
        return None

    best_answer = None
    highest_score = 0

    for item in Knowledge.query.all():

        stored_question = clean_text(item.question)
        stored_keywords = clean_text(item.keywords)

        question_matches = len(
            question_words & set(stored_question.split())
        )

        keyword_matches = len(
            question_words & set(stored_keywords.split())
        )

        score = question_matches * 2 + keyword_matches * 3

        if stored_question and stored_question in cleaned_question:
            score += 5

        if score > highest_score:
            highest_score = score
            best_answer = item.answer

    if best_answer and highest_score >= 5:
        return {"answer": best_answer, "score": highest_score}

    return None


# ==================================================
# 11. OPTIONAL: EXPLAIN THE RETRIEVED TEXT WITH CLAUDE
# Uses ONLY the retrieved course text. If anything fails,
# the app falls back to showing the original excerpt.
# ==================================================

EXPLAIN_SYSTEM_PROMPT = (
    "You are Eger AI, a study assistant for Egerton University students. "
    "Answer the student's question using ONLY the course material provided. "
    "If the material does not answer the question, say so briefly. "
    "Explain clearly in simple English. Use short bullet points when the "
    "material is a list. Do not add facts that are not in the material."
)


def generate_explanation(question, excerpt, document_title):

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None

    try:

        import anthropic

        client = anthropic.Anthropic(timeout=20.0)

        response = client.messages.create(
            model=ANSWER_MODEL,
            max_tokens=600,
            system=EXPLAIN_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    "Course material (" + document_title + "):\n"
                    + excerpt
                    + "\n\nStudent question: " + question
                )
            }]
        )

        text = "".join(
            block.text for block in response.content
            if getattr(block, "type", "") == "text"
        ).strip()

        return text or None

    except Exception:

        app.logger.exception("Explanation generation failed.")
        return None


# ==================================================
# 12. HOME ROUTE
# ==================================================

@app.route("/", methods=["GET"])
def home():

    return jsonify({
        "message": "Eger AI Flask server is working!",
        "status": "online",
        "document_search": (
            "section-aware TF-IDF + heading matching + typo correction"
        ),
        "conversation_memory": "enabled"
    })


# ==================================================
# 13. ASK EGER AI
# ==================================================

@app.route("/ask", methods=["POST", "OPTIONS"])
def ask():

    if request.method == "OPTIONS":
        return "", 204

    data = request.get_json(silent=True) or {}

    user_question = data.get("question", "")
    previous_question = data.get("previousQuestion", "")
    previous_answer = data.get("previousAnswer", "")

    if not isinstance(user_question, str):
        return jsonify({"error": "Question must be text."}), 400

    if not isinstance(previous_question, str):
        previous_question = ""

    if not isinstance(previous_answer, str):
        previous_answer = ""

    user_question = user_question.strip()

    if not user_question:
        return jsonify({"error": "Please provide a question."}), 400

    normalized_question = normalize_question(user_question) or user_question

    contextual_question, followup_intent = build_contextual_question(
        normalized_question,
        previous_question
    )

    is_followup = followup_intent is not None

    # ---- A. Search the uploaded documents

    search = search_documents(contextual_question)
    best = search["best"]

    app.logger.info(
        "Question: %s | Follow-up: %s | Score: %s | Section: %s",
        normalized_question,
        followup_intent,
        best["similarity"] if best else None,
        best["heading"] if best else None
    )

    if best:

        excerpt = best["answer_text"]

        generated = generate_explanation(
            normalized_question,
            excerpt,
            best["title"]
        )

        response = {
            "answer": generated or excerpt,
            "answer_type": "generated" if generated else "excerpt",
            "status": "success",
            "source": "document",
            "document_id": best["document_id"],
            "document_title": best["title"],
            "category": best["category"],
            "page": best["page"],
            "section": best["heading"],
            "similarity": best["similarity"],
            "confidence": best["confidence"],
            "followup": is_followup,
            "intent": followup_intent
        }

        if generated:
            response["excerpt"] = excerpt

        return jsonify(response)

    # ---- B. Search the knowledge database

    knowledge_result = search_knowledge(contextual_question)

    if knowledge_result:

        return jsonify({
            "answer": knowledge_result["answer"],
            "status": "success",
            "source": "knowledge",
            "followup": is_followup,
            "intent": followup_intent
        })

    # ---- C. Follow-up with nothing new: reuse the previous answer

    if is_followup and previous_answer:

        fallback_messages = {
            "simplify": (
                "I don't have another passage to simplify. "
                "Here is the explanation I found:"
            ),
            "examples": (
                "I couldn't find a separate examples section. "
                "Here is the information available:"
            ),
            "explain": (
                "I couldn't find additional information in the "
                "uploaded documents. Here is the previous explanation:"
            ),
            "why": (
                "I couldn't find further information explaining why. "
                "Here is the previous answer:"
            ),
            "continue": (
                "I couldn't find another relevant passage. "
                "Here is the information available:"
            ),
            "summarize": (
                "Here is the information available to summarize:"
            ),
            "clarify": (
                "Let me refer back to the previous answer:"
            )
        }

        return jsonify({
            "answer": (
                fallback_messages.get(
                    followup_intent,
                    "Here is the previous answer:"
                )
                + "\n\n"
                + previous_answer
            ),
            "status": "success",
            "source": "conversation_memory",
            "followup": True,
            "intent": followup_intent
        })

    # ---- D. Nothing found (return the closest sections, if any)

    return jsonify({
        "answer": (
            "I'm sorry, I couldn't find a sufficiently relevant answer "
            "in the university documents or knowledge base. Please try "
            "different wording or contact the relevant Egerton "
            "University office."
        ),
        "status": "not_found",
        "source": None,
        "followup": is_followup,
        "intent": followup_intent,
        "suggestions": search["suggestions"]
    })


# ==================================================
# 14. ADD KNOWLEDGE (ADMIN PASSWORD REQUIRED)
# ==================================================

@app.route("/add", methods=["POST", "OPTIONS"])
@admin_required
def add_knowledge():

    if request.method == "OPTIONS":
        return "", 204

    data = request.get_json(silent=True) or {}

    question = data.get("question", "")
    keywords = data.get("keywords", "")
    answer = data.get("answer", "")

    if not all(
        isinstance(value, str)
        for value in (question, keywords, answer)
    ):
        return jsonify({"error": "All fields must contain text."}), 400

    question = question.strip()
    keywords = keywords.strip()
    answer = answer.strip()

    if not question or not keywords or not answer:
        return jsonify({
            "error": "Question, keywords, and answer are all required."
        }), 400

    if len(question) > 200:
        return jsonify({
            "error": "Question must not exceed 200 characters."
        }), 400

    if len(keywords) > 500:
        return jsonify({
            "error": "Keywords must not exceed 500 characters."
        }), 400

    try:

        new_knowledge = Knowledge(
            question=question,
            keywords=keywords,
            answer=answer
        )

        db.session.add(new_knowledge)
        db.session.commit()

        return jsonify({
            "message": "Knowledge added successfully!",
            "id": new_knowledge.id
        }), 201

    except Exception:

        db.session.rollback()
        app.logger.exception("Failed to save knowledge.")

        return jsonify({"error": "Failed to save knowledge."}), 500


# ==================================================
# 15. TEXT EXTRACTION
# PDF pages are joined with a form-feed character so the
# search index knows where each slide/page starts and ends.
# ==================================================

def extract_pdf_text(file_bytes):

    pdf = PdfReader(BytesIO(file_bytes))

    if pdf.is_encrypted:
        raise ValueError("This PDF is password-protected.")

    pages = []

    for page in pdf.pages:

        page_text = page.extract_text() or ""

        # pypdf inserts blank lines inside a page; remove them.
        page_text = re.sub(r"\n\s*\n+", "\n", page_text.strip())

        if page_text:
            pages.append(page_text)

    return "\f".join(pages)


def extract_docx_text(file_bytes):

    document = WordDocument(BytesIO(file_bytes))

    parts = []

    for paragraph in document.paragraphs:

        if paragraph.text.strip():
            parts.append(paragraph.text)

    for table in document.tables:

        for row in table.rows:

            row_text = " | ".join(
                cell.text.strip() for cell in row.cells
            )

            if row_text.strip():
                parts.append(row_text)

    return "\n".join(parts)


def extract_txt_text(file_bytes):

    return file_bytes.decode("utf-8-sig")


# ==================================================
# 16. UPLOAD UNIVERSITY DOCUMENT (ADMIN PASSWORD REQUIRED)
# ==================================================

@app.route("/upload", methods=["POST", "OPTIONS"])
@admin_required
def upload_document():

    if request.method == "OPTIONS":
        return "", 204

    title = request.form.get("title", "").strip()
    category = request.form.get("category", "").strip()
    uploaded_file = request.files.get("document")

    if not title or not category or not uploaded_file:
        return jsonify({
            "error": "Title, category, and document are all required."
        }), 400

    if len(title) > 200:
        return jsonify({
            "error": "Title must not exceed 200 characters."
        }), 400

    if len(category) > 100:
        return jsonify({
            "error": "Category must not exceed 100 characters."
        }), 400

    original_filename = secure_filename(uploaded_file.filename or "")

    if not original_filename:
        return jsonify({"error": "Please select a valid filename."}), 400

    extension = Path(original_filename).suffix.lower()

    if extension not in {".pdf", ".docx", ".txt"}:
        return jsonify({
            "error": "Only PDF, DOCX, and TXT files are supported."
        }), 400

    try:

        file_bytes = uploaded_file.read()

        if not file_bytes:
            return jsonify({"error": "The uploaded file is empty."}), 400

        if extension == ".pdf":
            extracted_text = extract_pdf_text(file_bytes)
        elif extension == ".docx":
            extracted_text = extract_docx_text(file_bytes)
        else:
            extracted_text = extract_txt_text(file_bytes)

        extracted_text = extracted_text.strip()

        if not extracted_text:
            return jsonify({
                "error": (
                    "No readable text was found. "
                    "Scanned PDFs may require OCR."
                )
            }), 400

        new_document = Document(
            title=title,
            category=category,
            filename=original_filename,
            extracted_text=extracted_text
        )

        db.session.add(new_document)
        db.session.commit()

        invalidate_index()

        return jsonify({
            "message": "Document text extracted and saved successfully!",
            "document_id": new_document.id,
            "title": new_document.title,
            "category": new_document.category,
            "characters_extracted": len(extracted_text)
        }), 201

    except (ValueError, UnicodeDecodeError) as error:

        db.session.rollback()

        return jsonify({"error": str(error)}), 400

    except Exception:

        db.session.rollback()
        app.logger.exception("Document upload failed.")

        return jsonify({
            "error": (
                "The document could not be processed. "
                "Check the file and try again."
            )
        }), 500


# ==================================================
# 17. FILE SIZE ERROR
# ==================================================

@app.errorhandler(413)
def file_too_large(error):

    return jsonify({
        "error": "File too large. Maximum size is 10 MB."
    }), 413


# ==================================================
# 18. RUN THE APPLICATION
# ==================================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )