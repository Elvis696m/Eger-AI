// =================================
// EGER AI ELEMENTS
// =================================

let micButton = document.getElementById("micButton");
let userInput = document.getElementById("userInput");
let sendButton = document.getElementById("sendButton");
let chatArea = document.getElementById("chatArea");

// =================================
// CONVERSATION MEMORY
// =================================

let conversationMemory = {
previousQuestion: sessionStorage.getItem("previousQuestion") || "",
previousAnswer: sessionStorage.getItem("previousAnswer") || ""
};

// =================================
// MICROPHONE
// =================================

let recognition = null;

if ("webkitSpeechRecognition" in window) {
recognition = new webkitSpeechRecognition();


recognition.continuous = false;
recognition.interimResults = false;
recognition.lang = "en-US";

recognition.onresult = function(event) {
    let speech = event.results[0][0].transcript;
    userInput.value = speech;
};

recognition.onerror = function(event) {
    console.log("Microphone error:", event.error);
};

micButton.onclick = function() {
    recognition.start();
};


} else {
micButton.onclick = function() {
alert("Speech recognition is not supported in this browser.");
};
}

// =================================
// DISPLAY MESSAGES
// =================================

function displayMessage(message, className) {
let messageElement = document.createElement("div");


messageElement.className = className;
messageElement.textContent = message;

chatArea.appendChild(messageElement);

chatArea.scrollTop = chatArea.scrollHeight;


}

// =================================
// SEND MESSAGE
// =================================

async function sendMessage() {


let message = userInput.value.trim();

if (message === "") return;

displayMessage(message, "user-message");

userInput.value = "";
sendButton.disabled = true;

try {

    let response = await fetch("https://eger-ai.onrender.com/ask", {

        method: "POST",

        headers: {
            "Content-Type": "application/json"
        },

        body: JSON.stringify({

            question: message,

            previousQuestion: conversationMemory.previousQuestion,

            previousAnswer: conversationMemory.previousAnswer

        })

    });

    if (!response.ok) {
        throw new Error("Server returned an error: " + response.status);
    }

    let data = await response.json();

    displayMessage(data.answer, "ai-message");

    // =================================
    // UPDATE CONVERSATION MEMORY
    // =================================

    if (data.answer) {

        conversationMemory.previousQuestion = message;

        conversationMemory.previousAnswer = data.answer;

        sessionStorage.setItem(
            "previousQuestion",
            message
        );

        sessionStorage.setItem(
            "previousAnswer",
            data.answer
        );

    }

} catch (error) {

    console.error("Error:", error);

    displayMessage(
        "Sorry, I could not connect to Eger AI. Please try again.",
        "ai-message"
    );

} finally {

    sendButton.disabled = false;

}


}

// =================================
// SEND BUTTON
// =================================

sendButton.onclick = sendMessage;

// =================================
// ENTER KEY
// =================================

userInput.addEventListener("keydown", function(event) {


if (event.key === "Enter") {

    sendMessage();

}


});
