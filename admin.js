let addButton = document.getElementById("addButton");

let question = document.getElementById("question");

let keywords = document.getElementById("keywords");

let answer = document.getElementById("answer");

let message = document.getElementById("message");


addButton.onclick = function() {

    let questionText = question.value.trim();

    let keywordsText = keywords.value.trim();

    let answerText = answer.value.trim();


    if (
        questionText === "" ||
        keywordsText === "" ||
        answerText === ""
    ) {

        message.textContent = "Please fill in all fields.";

        return;
    }


    fetch("http://127.0.0.1:5000/add", {

        method: "POST",

        headers: {
            "Content-Type": "application/json"
        },

        body: JSON.stringify({

            question: questionText,

            keywords: keywordsText,

            answer: answerText

        })

    })

    .then(response => response.json())

    .then(data => {

        message.textContent = data.message;

        question.value = "";

        keywords.value = "";

        answer.value = "";

    })

    .catch(error => {

        console.log("Error:", error);

        message.textContent = "Something went wrong.";

    });

};