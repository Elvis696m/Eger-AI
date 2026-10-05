from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS, cross_origin


app = Flask(__name__)

CORS(app)


# Test route
@app.route("/")
def home():
    return "Eger AI Flask server is working!"


# Database
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///egerai.db"

db = SQLAlchemy(app)


# Knowledge table
class Knowledge(db.Model):

    id = db.Column(db.Integer, primary_key=True)

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


# Create database
with app.app_context():
    db.create_all()


# Ask Eger AI
@app.route("/ask", methods=["POST"])
@cross_origin()
def ask():

    data = request.get_json()

    question = data["question"].lower()


    knowledge = Knowledge.query.filter(
        Knowledge.question.ilike(f"%{question}%")
    ).first()


    if not knowledge:

        knowledge = Knowledge.query.filter(
            Knowledge.keywords.ilike(f"%{question}%")
        ).first()


    if knowledge:

        answer = knowledge.answer

    else:

        answer = (
            "I don't know that yet. "
            "My knowledge base is still being built."
        )


    return jsonify({
        "answer": answer
    })


# Add knowledge
@app.route("/add", methods=["POST", "OPTIONS"])
@cross_origin()
def add_knowledge():

    if request.method == "OPTIONS":
        return "", 204


    data = request.get_json()


    new_knowledge = Knowledge(

        question=data["question"],

        keywords=data["keywords"],

        answer=data["answer"]

    )


    db.session.add(new_knowledge)

    db.session.commit()


    return jsonify({
        "message": "Knowledge added successfully"
    })


# Start Flask
if __name__ == "__main__":

    app.run(debug=True)