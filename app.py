import os
import re
import hmac

from io import BytesIO
from pathlib import Path
from functools import wraps

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.utils import secure_filename

from pypdf import PdfReader
from docx import Document as WordDocument

from sklearn.feature_extraction.text import TfidfVectorizer
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

DATABASE_PATH = os.path.join(
    INSTANCE_DIR,
    "egerai.db"
)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///" + DATABASE_PATH.replace("\\", "/")
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ==================================================
# 2. ADMIN AUTHENTICATION
# ==================================================

def admin_required(route_function):

    @wraps(route_function)
    def wrapper(*args, **kwargs):

        if request.method == "OPTIONS":
            return route_function(*args, **kwargs)

        admin_password = os.environ.get(
            "ADMIN_PASSWORD"
        )

        if not admin_password:

            app.logger.error(
                "ADMIN_PASSWORD is not configured."
            )

            return jsonify({
                "error": "Administrator authentication is not configured."
            }), 503

        authorization = request.headers.get(
            "Authorization",
            ""
        )

        supplied_password = ""

        if authorization.startswith("Bearer "):

            supplied_password = authorization[
                len("Bearer "):
            ]

        if not hmac.compare_digest(
            supplied_password,
            admin_password
        ):

            return jsonify({
                "error": "Unauthorized."
            }), 401

        return route_function(*args, **kwargs)

    return wrapper


# ==================================================
# 3. KNOWLEDGE DATABASE MODEL
# ==================================================

class Knowledge(db.Model):

    __tablename__ = "knowledge"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    question = db.Column(
        db.String(200),
        nullable=False
    )

    keywords = db.Column(
        db.String(500),
        nullable=False
    )

    answer = db.Column(
        db.Text,
        nullable=False
    )


# ==================================================
# 4. DOCUMENT DATABASE MODEL
# ==================================================

class Document(db.Model):

    __tablename__ = "documents"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    title = db.Column(
        db.String(200),
        nullable=False
    )

    category = db.Column(
        db.String(100),
        nullable=False
    )

    filename = db.Column(
        db.String(255),
        nullable=False
    )

    extracted_text = db.Column(
        db.Text,
        nullable=False
    )

    uploaded_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp()
    )


# ==================================================
# 5. INITIALIZE DATABASE
# ==================================================

with app.app_context():

    db.create_all()

    print("====================================")
    print("EGER AI DATABASE INITIALIZED")
    print("====================================")

    print(
        "Knowledge records:",
        Knowledge.query.count()
    )

    print(
        "Stored documents:",
        Document.query.count()
    )


# ==================================================
# 6. CLEAN TEXT
# ==================================================

def clean_text(text):

    text = str(text or "").lower()

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ==================================================
# 7. REMOVE CONVERSATIONAL FILLERS
# ==================================================

def normalize_question(question):

    question = str(question or "").strip()

    # Remove common forms of address at the beginning.
    # Only removes them when they are being used as
    # conversational fillers.

    question = re.sub(
        r"^(bro|bruh|dude|mate|man|girl|bitch)\b[\s,!?]*",
        "",
        question,
        flags=re.IGNORECASE
    )

    # Remove common forms of address at the end.

    question = re.sub(
        r"[\s,!?]+\b(bro|bruh|dude|mate|man)\b[.!?]*$",
        "",
        question,
        flags=re.IGNORECASE
    )

    return question.strip()


# ==================================================
# 8. RECOGNIZE FOLLOW-UP INTENT
# ==================================================

def recognize_followup(question):

    cleaned = clean_text(question)

    followup_patterns = {

        "simplify": [
            "simplify",
            "simplify that",
            "in simple english",
            "explain simply",
            "make it simple",
            "make it easier",
            "easy english"
        ],

        "examples": [
            "give examples",
            "examples",
            "some examples",
            "show examples",
            "example please"
        ],

        "explain": [
            "explain",
            "explain that",
            "elaborate",
            "tell me more",
            "more details",
            "go deeper",
            "expand on that"
        ],

        "why": [
            "why",
            "why is that",
            "why is that so",
            "how come"
        ],

        "continue": [
            "continue",
            "go on",
            "proceed",
            "continue explaining"
        ],

        "summarize": [
            "summarize",
            "summarise",
            "short summary",
            "briefly explain",
            "summarise that"
        ],

        "clarify": [
            "what do you mean",
            "what does that mean",
            "clarify",
            "i dont understand",
            "i do not understand"
        ]

    }

    for intent, phrases in followup_patterns.items():

        for phrase in phrases:

            if cleaned == phrase:

                return intent

            if cleaned.startswith(phrase + " "):

                return intent

    return None


# ==================================================
# 9. BUILD CONTEXTUAL QUESTION
# ==================================================

def build_contextual_question(
    user_question,
    previous_question,
    previous_answer
):

    intent = recognize_followup(
        user_question
    )

    if not intent or not previous_question:

        return user_question, None

    # The previous question identifies the topic.
    # The follow-up intent provides additional context.

    intent_keywords = {

        "simplify": "simple explanation",

        "examples": "examples applications",

        "explain": "explanation details",

        "why": "reasons causes importance",

        "continue": "further explanation",

        "summarize": "summary main points",

        "clarify": "definition explanation"

    }

    contextual_question = (
        previous_question
        + " "
        + intent_keywords.get(intent, "")
    )

    return contextual_question, intent


# ==================================================
# 10. SPLIT DOCUMENTS INTO PASSAGES
# ==================================================

def split_into_passages(
    text,
    chunk_size=180,
    overlap=40
):

    words = (text or "").split()

    if not words:
        return []

    if (
        chunk_size <= 0
        or overlap < 0
        or overlap >= chunk_size
    ):

        raise ValueError(
            "Invalid passage chunk size or overlap."
        )

    passages = []

    step = chunk_size - overlap

    for start in range(
        0,
        len(words),
        step
    ):

        passage_words = words[
            start:start + chunk_size
        ]

        if not passage_words:
            break

        passage = " ".join(
            passage_words
        ).strip()

        if passage:

            passages.append(passage)

        if start + chunk_size >= len(words):

            break

    return passages


# ==================================================
# 11. SEARCH UNIVERSITY DOCUMENTS
# ==================================================

def search_documents(
    user_question,
    minimum_score=0.08
):

    documents = Document.query.all()

    if not documents:

        return None

    passages = []

    for document in documents:

        document_passages = split_into_passages(
            document.extracted_text
        )

        for passage_number, passage in enumerate(
            document_passages
        ):

            cleaned_passage = clean_text(
                passage
            )

            if not cleaned_passage:

                continue

            passages.append({

                "document_id": document.id,

                "title": document.title,

                "category": document.category,

                "passage_number": passage_number + 1,

                "text": passage,

                "cleaned_text": cleaned_passage

            })

    if not passages:

        return None

    cleaned_question = clean_text(
        user_question
    )

    if not cleaned_question:

        return None

    corpus = [
        item["cleaned_text"]
        for item in passages
    ]

    try:

        vectorizer = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            sublinear_tf=True
        )

        matrix = vectorizer.fit_transform(
            corpus + [cleaned_question]
        )

        document_matrix = matrix[:-1]

        question_vector = matrix[-1]

        similarities = cosine_similarity(
            question_vector,
            document_matrix
        ).flatten()

    except ValueError:

        return None

    best_index = int(
        similarities.argmax()
    )

    best_score = float(
        similarities[best_index]
    )

    if best_score < minimum_score:

        return None

    best_match = passages[best_index].copy()

    best_match["similarity"] = round(
        best_score,
        4
    )

    return best_match


# ==================================================
# 12. SEARCH KNOWLEDGE DATABASE
# ==================================================

def search_knowledge(user_question):

    cleaned_question = clean_text(
        user_question
    )

    question_words = set(
        cleaned_question.split()
    )

    if not question_words:

        return None

    best_answer = None

    highest_score = 0

    knowledge_records = Knowledge.query.all()

    for item in knowledge_records:

        stored_question = clean_text(
            item.question
        )

        stored_keywords = clean_text(
            item.keywords
        )

        stored_question_words = set(
            stored_question.split()
        )

        stored_keyword_words = set(
            stored_keywords.split()
        )

        question_matches = len(
            question_words & stored_question_words
        )

        keyword_matches = len(
            question_words & stored_keyword_words
        )

        score = (
            question_matches * 2
            + keyword_matches * 3
        )

        if (
            stored_question
            and stored_question in cleaned_question
        ):

            score += 5

        if score > highest_score:

            highest_score = score

            best_answer = item.answer

    if best_answer and highest_score >= 5:

        return {

            "answer": best_answer,

            "score": highest_score

        }

    return None


# ==================================================
# 13. HOME ROUTE
# ==================================================

@app.route("/", methods=["GET"])
def home():

    return jsonify({

        "message": "Eger AI Flask server is working!",

        "status": "online",

        "document_search": "TF-IDF + cosine similarity",

        "conversation_memory": "enabled"

    })


# ==================================================
# 14. ASK EGER AI
# ==================================================

@app.route(
    "/ask",
    methods=["POST", "OPTIONS"]
)
def ask():

    if request.method == "OPTIONS":

        return "", 204

    data = request.get_json(
        silent=True
    ) or {}

    user_question = data.get(
        "question",
        ""
    )

    previous_question = data.get(
        "previousQuestion",
        ""
    )

    previous_answer = data.get(
        "previousAnswer",
        ""
    )

    # ------------------------------------------
    # A. VALIDATE INPUT
    # ------------------------------------------

    if not isinstance(user_question, str):

        return jsonify({
            "error": "Question must be text."
        }), 400

    if not isinstance(previous_question, str):

        previous_question = ""

    if not isinstance(previous_answer, str):

        previous_answer = ""

    user_question = user_question.strip()

    if not user_question:

        return jsonify({
            "error": "Please provide a question."
        }), 400

    # ------------------------------------------
    # B. NORMALIZE QUESTION
    # ------------------------------------------

    normalized_question = normalize_question(
        user_question
    )

    if not normalized_question:

        normalized_question = user_question

    # ------------------------------------------
    # C. RECOGNIZE FOLLOW-UP
    # ------------------------------------------

    contextual_question, followup_intent = (
        build_contextual_question(
            normalized_question,
            previous_question,
            previous_answer
        )
    )

    is_followup = (
        followup_intent is not None
    )

    app.logger.info(
        "Question: %s | Follow-up: %s",
        normalized_question,
        followup_intent
    )

    # ------------------------------------------
    # D. SEARCH DOCUMENTS
    # ------------------------------------------

    document_result = search_documents(
        contextual_question
    )

    if document_result:

        return jsonify({

            "answer": document_result["text"],

            "status": "success",

            "source": "document",

            "document_id": document_result["document_id"],

            "document_title": document_result["title"],

            "category": document_result["category"],

            "passage_number": document_result["passage_number"],

            "similarity": document_result["similarity"],

            "followup": is_followup,

            "intent": followup_intent

        })

    # ------------------------------------------
    # E. SEARCH KNOWLEDGE DATABASE
    # ------------------------------------------

    knowledge_result = search_knowledge(
        contextual_question
    )

    if knowledge_result:

        return jsonify({

            "answer": knowledge_result["answer"],

            "status": "success",

            "source": "knowledge",

            "followup": is_followup,

            "intent": followup_intent

        })

    # ------------------------------------------
    # F. PREVIOUS ANSWER FALLBACK
    # ------------------------------------------

    if is_followup and previous_answer:

        fallback_messages = {

            "simplify": (
                "I don't have another passage to simplify "
                "right now. Here is the explanation I found:"
            ),

            "examples": (
                "I couldn't find a separate examples section. "
                "Here is the information available:"
            ),

            "explain": (
                "I couldn't find additional information "
                "in the uploaded documents. Here is the "
                "previous explanation:"
            ),

            "why": (
                "I couldn't find further information "
                "explaining why. Here is the previous answer:"
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

    # ------------------------------------------
    # G. NO ANSWER FOUND
    # ------------------------------------------

    return jsonify({

        "answer": (
            "I'm sorry, I couldn't find a sufficiently "
            "relevant answer in the university documents "
            "or knowledge base. Please try different "
            "wording or contact the relevant Egerton "
            "University office."
        ),

        "status": "not_found",

        "source": None,

        "followup": False

    })


# ==================================================
# 15. ADD KNOWLEDGE
# ADMIN PASSWORD REQUIRED
# ==================================================

@app.route(
    "/add",
    methods=["POST", "OPTIONS"]
)
@admin_required
def add_knowledge():

    if request.method == "OPTIONS":

        return "", 204

    data = request.get_json(
        silent=True
    ) or {}

    question = data.get(
        "question",
        ""
    )

    keywords = data.get(
        "keywords",
        ""
    )

    answer = data.get(
        "answer",
        ""
    )

    if not all(
        isinstance(value, str)
        for value in (question, keywords, answer)
    ):

        return jsonify({
            "error": "All fields must contain text."
        }), 400

    question = question.strip()

    keywords = keywords.strip()

    answer = answer.strip()

    if not question or not keywords or not answer:

        return jsonify({
            "error": (
                "Question, keywords, and answer "
                "are all required."
            )
        }), 400

    if len(question) > 200:

        return jsonify({
            "error": (
                "Question must not exceed "
                "200 characters."
            )
        }), 400

    if len(keywords) > 500:

        return jsonify({
            "error": (
                "Keywords must not exceed "
                "500 characters."
            )
        }), 400

    try:

        new_knowledge = Knowledge(
            question=question,
            keywords=keywords,
            answer=answer
        )

        db.session.add(
            new_knowledge
        )

        db.session.commit()

        return jsonify({

            "message": "Knowledge added successfully!",

            "id": new_knowledge.id

        }), 201

    except Exception:

        db.session.rollback()

        app.logger.exception(
            "Failed to save knowledge."
        )

        return jsonify({
            "error": "Failed to save knowledge."
        }), 500


# ==================================================
# 16. EXTRACT PDF TEXT
# ==================================================

def extract_pdf_text(file_bytes):

    pdf = PdfReader(
        BytesIO(file_bytes)
    )

    if pdf.is_encrypted:

        raise ValueError(
            "This PDF is password-protected."
        )

    extracted_pages = []

    for page in pdf.pages:

        page_text = page.extract_text() or ""

        if page_text.strip():

            extracted_pages.append(
                page_text
            )

    return "\n".join(
        extracted_pages
    )


# ==================================================
# 17. EXTRACT DOCX TEXT
# ==================================================

def extract_docx_text(file_bytes):

    document = WordDocument(
        BytesIO(file_bytes)
    )

    extracted_parts = []

    for paragraph in document.paragraphs:

        if paragraph.text.strip():

            extracted_parts.append(
                paragraph.text
            )

    for table in document.tables:

        for row in table.rows:

            row_text = " | ".join(
                cell.text.strip()
                for cell in row.cells
            )

            if row_text.strip():

                extracted_parts.append(
                    row_text
                )

    return "\n".join(
        extracted_parts
    )


# ==================================================
# 18. EXTRACT TXT TEXT
# ==================================================

def extract_txt_text(file_bytes):

    return file_bytes.decode(
        "utf-8-sig"
    )


# ==================================================
# 19. UPLOAD UNIVERSITY DOCUMENT
# ADMIN PASSWORD REQUIRED
# ==================================================

@app.route(
    "/upload",
    methods=["POST", "OPTIONS"]
)
@admin_required
def upload_document():

    if request.method == "OPTIONS":

        return "", 204

    title = request.form.get(
        "title",
        ""
    ).strip()

    category = request.form.get(
        "category",
        ""
    ).strip()

    uploaded_file = request.files.get(
        "document"
    )

    if (
        not title
        or not category
        or not uploaded_file
    ):

        return jsonify({
            "error": (
                "Title, category, and document "
                "are all required."
            )
        }), 400

    if len(title) > 200:

        return jsonify({
            "error": (
                "Title must not exceed "
                "200 characters."
            )
        }), 400

    if len(category) > 100:

        return jsonify({
            "error": (
                "Category must not exceed "
                "100 characters."
            )
        }), 400

    original_filename = secure_filename(
        uploaded_file.filename or ""
    )

    if not original_filename:

        return jsonify({
            "error": "Please select a valid filename."
        }), 400

    extension = Path(
        original_filename
    ).suffix.lower()

    allowed_extensions = {
        ".pdf",
        ".docx",
        ".txt"
    }

    if extension not in allowed_extensions:

        return jsonify({
            "error": (
                "Only PDF, DOCX, and TXT "
                "files are supported."
            )
        }), 400

    try:

        file_bytes = uploaded_file.read()

        if not file_bytes:

            return jsonify({
                "error": "The uploaded file is empty."
            }), 400

        if extension == ".pdf":

            extracted_text = extract_pdf_text(
                file_bytes
            )

        elif extension == ".docx":

            extracted_text = extract_docx_text(
                file_bytes
            )

        else:

            extracted_text = extract_txt_text(
                file_bytes
            )

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

        db.session.add(
            new_document
        )

        db.session.commit()

        return jsonify({

            "message": (
                "Document text extracted "
                "and saved successfully!"
            ),

            "document_id": new_document.id,

            "title": new_document.title,

            "category": new_document.category,

            "characters_extracted": len(extracted_text)

        }), 201

    except (ValueError, UnicodeDecodeError) as error:

        db.session.rollback()

        return jsonify({
            "error": str(error)
        }), 400

    except Exception:

        db.session.rollback()

        app.logger.exception(
            "Document upload failed."
        )

        return jsonify({
            "error": (
                "The document could not be processed. "
                "Check the file and try again."
            )
        }), 500


# ==================================================
# 20. FILE SIZE ERROR
# ==================================================

@app.errorhandler(413)
def file_too_large(error):

    return jsonify({
        "error": (
            "File too large. Maximum size is 10 MB."
        )
    }), 413


# ==================================================
# 21. RUN THE APPLICATION
# ==================================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )