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
# 2. ADMIN AUTHENTICATION
# ==================================================

def admin_required(route_function):

    @wraps(route_function)
    def wrapper(*args, **kwargs):

        if request.method == "OPTIONS":
            return route_function(*args, **kwargs)

        admin_password = os.environ.get("ADMIN_PASSWORD")

        if not admin_password:

            app.logger.error(
                "ADMIN_PASSWORD is not configured."
            )

            return jsonify({
                "error": (
                    "Administrator authentication "
                    "is not configured."
                )
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
                "error": (
                    "Unauthorized. A valid administrator "
                    "password is required."
                )
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
# 6. TEXT CLEANING
# ==================================================

def clean_text(text):

    text = (text or "").lower()

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
# 7. BUILD SEARCHABLE PASSAGES
# ==================================================

def build_passages(text):

    normalized_text = (text or "").replace(
        "\r\n",
        "\n"
    )

    normalized_text = normalized_text.replace(
        "\r",
        "\n"
    )

    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in normalized_text.split("\n")
    ]

    lines = [
        line for line in lines if line
    ]

    if not lines:
        return []

    passages = []
    seen = set()

    # Combine consecutive lines so headings and their
    # explanations have a better chance of being matched.
    for start in range(len(lines)):

        for window_size in (1, 2, 3, 5):

            end = min(
                start + window_size,
                len(lines)
            )

            passage = " ".join(
                lines[start:end]
            ).strip()

            if passage and passage not in seen:

                passages.append(passage)
                seen.add(passage)

    # Keep the full text available for longer matches.
    full_text = " ".join(lines).strip()

    if full_text and full_text not in seen:
        passages.append(full_text)

    return passages


# ==================================================
# 8. SCORE A TEXT PASSAGE
# ==================================================

def score_passage(
    question_words,
    cleaned_question,
    passage
):

    cleaned_passage = clean_text(passage)

    passage_words = set(
        cleaned_passage.split()
    )

    matches = len(
        question_words & passage_words
    )

    score = matches * 3

    if cleaned_question and cleaned_question in cleaned_passage:
        score += 5

    return score


# ==================================================
# 9. HOME ROUTE
# ==================================================

@app.route("/", methods=["GET"])
def home():

    return jsonify({
        "message": "Eger AI Flask server is working!",
        "status": "online"
    })


# ==================================================
# 10. ASK EGER AI
# SEARCH KNOWLEDGE AND DOCUMENTS
# ==================================================

@app.route("/ask", methods=["POST", "OPTIONS"])
def ask():

    if request.method == "OPTIONS":
        return "", 204

    data = request.get_json(silent=True) or {}

    user_question = data.get(
        "question",
        ""
    )

    if not isinstance(user_question, str):

        return jsonify({
            "error": "Question must be text.",
            "status": "error"
        }), 400

    user_question = user_question.strip()

    if not user_question:

        return jsonify({
            "error": "Please provide a question.",
            "status": "error"
        }), 400

    cleaned_question = clean_text(user_question)

    stop_words = {
        "what", "is", "the", "a", "an", "of", "in",
        "for", "to", "and", "how", "does", "do",
        "are", "can", "explain", "tell", "me", "about",
        "from", "my", "your", "it", "on", "with",
        "please", "i", "want", "know", "define",
        "describe", "give", "did", "was", "were",
        "be", "as", "at", "by", "this", "that"
    }

    question_words = (
        set(cleaned_question.split()) - stop_words
    )

    if not question_words:
        question_words = set(cleaned_question.split())

    best_answer = None
    highest_score = 0

    # --------------------------------------------------
    # A. SEARCH MANUALLY ADDED KNOWLEDGE
    # --------------------------------------------------

    for item in Knowledge.query.all():

        stored_question = clean_text(item.question)
        stored_keywords = clean_text(item.keywords)

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

    # --------------------------------------------------
    # B. SEARCH UPLOADED DOCUMENTS
    # --------------------------------------------------

    for document in Document.query.all():

        original_text = document.extracted_text or ""

        if not original_text.strip():
            continue

        title_words = set(
            clean_text(document.title).split()
        )

        category_words = set(
            clean_text(document.category).split()
        )

        title_matches = len(
            question_words & title_words
        )

        category_matches = len(
            question_words & category_words
        )

        passages = build_passages(original_text)

        best_paragraph = ""
        best_paragraph_score = 0

        for paragraph in passages:

            paragraph_score = score_passage(
                question_words,
                cleaned_question,
                paragraph
            )

            if paragraph_score > best_paragraph_score:

                best_paragraph_score = paragraph_score
                best_paragraph = paragraph

        if not best_paragraph:
            continue

        document_score = (
            best_paragraph_score
            + title_matches * 2
            + category_matches
        )

        if document_score > highest_score:

            highest_score = document_score

            best_answer = (
                f"According to {document.title} "
                f"({document.category}):\n\n"
                f"{best_paragraph[:3000]}"
            )

    # --------------------------------------------------
    # C. RETURN THE BEST MATCH
    # --------------------------------------------------

    if best_answer and highest_score >= 5:

        return jsonify({
            "answer": best_answer,
            "status": "success"
        })

    return jsonify({
        "answer": (
            "I'm sorry, I don't have enough information "
            "to answer that question yet. Please contact "
            "the relevant Egerton University office or "
            "try asking in a different way."
        ),
        "status": "not_found"
    })


# ==================================================
# 11. ADD KNOWLEDGE
# ADMIN PASSWORD REQUIRED
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
                "Question must not exceed 200 characters."
            )
        }), 400

    if len(keywords) > 500:

        return jsonify({
            "error": (
                "Keywords must not exceed 500 characters."
            )
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

        app.logger.exception(
            "Failed to save knowledge."
        )

        return jsonify({
            "error": "Failed to save knowledge."
        }), 500


# ==================================================
# 12. EXTRACT PDF TEXT
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

            extracted_pages.append(page_text)

    return "\n".join(extracted_pages)


# ==================================================
# 13. EXTRACT DOCX TEXT
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

                extracted_parts.append(row_text)

    return "\n".join(extracted_parts)


# ==================================================
# 14. EXTRACT TXT TEXT
# ==================================================

def extract_txt_text(file_bytes):

    return file_bytes.decode("utf-8-sig")


# ==================================================
# 15. UPLOAD UNIVERSITY DOCUMENT
# ADMIN PASSWORD REQUIRED
# ==================================================

@app.route("/upload", methods=["POST", "OPTIONS"])
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

    uploaded_file = request.files.get("document")

    if not title or not category or not uploaded_file:

        return jsonify({
            "error": (
                "Title, category, and document "
                "are all required."
            )
        }), 400

    if len(title) > 200:

        return jsonify({
            "error": (
                "Title must not exceed 200 characters."
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
                "Only PDF, DOCX, and TXT files "
                "are supported."
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

        db.session.add(new_document)
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

    except ValueError as error:

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
# 16. FILE SIZE ERROR
# ==================================================

@app.errorhandler(413)
def file_too_large(error):

    return jsonify({
        "error": (
            "File too large. Maximum size is 10 MB."
        )
    }), 413


# ==================================================
# 17. RUN APPLICATION LOCALLY
# ==================================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )