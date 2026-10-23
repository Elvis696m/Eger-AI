
import os
import re

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS, cross_origin


# =========================
# FLASK APPLICATION
# =========================

app = Flask(__name__)
CORS(app)


# =========================
# DATABASE CONFIGURATION
# =========================

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

DATABASE_PATH = os.path.join(INSTANCE_DIR, "egerai.db")

app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///" + DATABASE_PATH.replace("\\", "/")
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# =========================
# KNOWLEDGE TABLE
# =========================

class Knowledge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(200), nullable=False)
    keywords = db.Column(db.String(500), nullable=False)
    answer = db.Column(db.Text, nullable=False)


# =========================
# DATABASE INITIALIZATION
# =========================

with app.app_context():
    db.create_all()

    print("DATABASE PATH:", db.engine.url)
    print("KNOWLEDGE RECORDS:", Knowledge.query.count())


# =========================
# TEXT CLEANING
# =========================

def clean_text(text):
    text = text.lower()

    replacements = {
        "didn't": "did not",
        "didnt": "did not",
        "doesn't": "does not",
        "doesnt": "does not",
        "don't": "do not",
        "dont": "do not",
        "can't": "cannot",
        "cant": "cannot",
        "i'm": "i am",
        "im": "i am",
        "what's": "what is",
        "whats": "what is"
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


# =========================
# HOME
# =========================

@app.route("/")
def home():
    return "Eger AI Flask server is working!"


# =========================
# ASK EGER AI
# =========================

@app.route("/ask", methods=["POST"])
@cross_origin()
def ask():

    data = request.get_json(silent=True)

    if not data or "question" not in data:
        return jsonify({
            "answer": "Please ask me a question."
        }), 400

    user_question = clean_text(str(data["question"]))

    if not user_question:
        return jsonify({
            "answer": "Please ask me a question."
        }), 400

    # Words that normally don't identify the topic
    stop_words = {
        "what", "is", "are", "the", "a", "an", "of",
        "do", "does", "did", "tell", "me", "about",
        "can", "you", "please", "explain", "define",
        "give", "information", "on", "to", "for", "and",
        "in", "how", "why", "where", "when", "who",
        "i", "my", "this", "that", "will", "would",
        "could", "should"
    }

    user_words = [
        word
        for word in user_question.split()
        if word not in stop_words
    ]

    knowledge_items = Knowledge.query.all()

    best_match = None
    best_score = 0

    # =========================
    # MATCH EACH KNOWLEDGE ITEM
    # =========================

    for knowledge in knowledge_items:

        score = 0

        stored_question = clean_text(knowledge.question)

        # 1. EXACT QUESTION
        if user_question == stored_question:
            score += 100

        # 2. KEYWORD PHRASES
        raw_keywords = knowledge.keywords.split(",")

        keyword_phrases = []

        for keyword in raw_keywords:
            keyword = clean_text(keyword)

            if keyword:
                keyword_phrases.append(keyword)

        for keyword in keyword_phrases:

            keyword_words = keyword.split()

            # Exact phrase appears in user's question
            if keyword in user_question:
                score += 20
                score += len(keyword_words) * 5

            # Individual keyword words
            matching_words = 0

            for word in keyword_words:
                if word in user_words:
                    matching_words += 1

            if matching_words > 0:
                score += matching_words * 3

                if matching_words == len(keyword_words):
                    score += 10

        # 3. STORED QUESTION MATCHING
        stored_question_words = set(stored_question.split())

        matching_question_words = 0

        for word in user_words:
            if word in stored_question_words:
                matching_question_words += 1

        score += matching_question_words * 2

        # 4. SPECIAL PROTECTION: RESIT
        if "resit" in user_words:

            if (
                "resit" in stored_question
                or "resit" in knowledge.keywords.lower()
            ):
                score += 30
            else:
                score -= 15

        # 5. SPECIAL PROTECTION: CAT
        if "cat" in user_words:

            if (
                "cat" in stored_question
                or "cat" in knowledge.keywords.lower()
            ):
                score += 30
            else:
                score -= 10

        # 6. EXAM MATCHING
        if "exam" in user_words:
            if "exam" in stored_question:
                score += 5

        # 7. SAVE BEST MATCH
        if score > best_score:
            best_score = score
            best_match = knowledge

    # =========================
    # RETURN ANSWER
    # =========================

    if best_match and best_score >= 5:
        return jsonify({
            "answer": best_match.answer
        })

    return jsonify({
        "answer": (
            "I don't know that yet. "
            "My knowledge base is still being built."
        )
    })


# =========================
# ADD KNOWLEDGE
# =========================

@app.route("/add", methods=["POST", "OPTIONS"])
@cross_origin()
def add_knowledge():

    if request.method == "OPTIONS":
        return "", 204

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "message": "No data received."
        }), 400

    if (
        "question" not in data
        or "keywords" not in data
        or "answer" not in data
    ):
        return jsonify({
            "message": (
                "question, keywords and answer are required."
            )
        }), 400

    new_knowledge = Knowledge(
        question=data["question"],
        keywords=data["keywords"],
        answer=data["answer"]
    )

    db.session.add(new_knowledge)
    db.session.commit()

    return jsonify({
        "message": "Knowledge added successfully",
        "id": new_knowledge.id
    })


# =========================
# START SERVER
# =========================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )

