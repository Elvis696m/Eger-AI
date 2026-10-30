// ==================================================
// EGER AI CHATBOT
// ==================================================

const API_URL = "https://eger-ai.onrender.com";

const micButton = document.getElementById("micButton");
const userInput = document.getElementById("userInput");
const sendButton = document.getElementById("sendButton");
const chatArea = document.getElementById("chatArea");


// ==================================================
// MICROPHONE / SPEECH RECOGNITION
// ==================================================

const SpeechRecognition =
    window.SpeechRecognition ||
    window.webkitSpeechRecognition;

let recognition = null;
let isListening = false;


if (SpeechRecognition) {
    recognition = new SpeechRecognition();

    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-US";

    recognition.onstart = function () {
        isListening = true;

        if (micButton) {
            micButton.textContent = "LISTENING...";
            micButton.disabled = true;
        }
    };

    recognition.onresult = function (event) {
        const speech = event.results[0][0].transcript;

        userInput.value = speech;
        userInput.focus();
    };

    recognition.onerror = function (event) {
        console.error(
            "Speech recognition error:",
            event.error
        );

        showMessage(
            "ai-message",
            "Sorry, I couldn't recognize your speech. Please try typing instead."
        );
    };

    recognition.onend = function () {
        isListening = false;

        if (micButton) {
            micButton.textContent = "🎤";
            micButton.disabled = false;
        }
    };
} else if (micButton) {
    micButton.disabled = true;
    micButton.title =
        "Speech recognition is not supported in this browser.";
}


// ==================================================
// DISPLAY CHAT MESSAGES
// ==================================================

function showMessage(className, text) {
    const messageElement = document.createElement("div");

    messageElement.className = className;

    // Use textContent so server responses are displayed as
    // text rather than interpreted as HTML.
    messageElement.textContent = text;

    chatArea.appendChild(messageElement);

    // Keep the latest message visible.
    chatArea.scrollTop = chatArea.scrollHeight;

    return messageElement;
}


// ==================================================
// MICROPHONE BUTTON
// ==================================================

if (micButton) {
    micButton.addEventListener("click", function () {
        if (!recognition || isListening) {
            return;
        }

        try {
            recognition.start();
        } catch (error) {
            console.error(
                "Could not start speech recognition:",
                error
            );
        }
    });
}


// ==================================================
// SEND A QUESTION TO EGER AI
// ==================================================

let isSending = false;


async function sendMessage() {
    const message = userInput.value.trim();

    // Don't send empty messages or duplicate requests.
    if (!message || isSending) {
        return;
    }

    // Display the user's question.
    showMessage("user-message", message);

    // Clear the input immediately.
    userInput.value = "";

    isSending = true;
    sendButton.disabled = true;

    // Display a temporary loading message.
    const loadingMessage = showMessage(
        "ai-message",
        "Thinking..."
    );

    try {
        const response = await fetch(
            `${API_URL}/ask`,
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({
                    question: message
                })
            }
        );

        const responseText = await response.text();

        let data;

        try {
            data = JSON.parse(responseText);
        } catch {
            throw new Error(
                "The server returned an unexpected response."
            );
        }

        // Handle HTTP errors and backend errors.
        if (!response.ok) {
            throw new Error(
                data.answer ||
                data.error ||
                data.message ||
                `Request failed (${response.status}).`
            );
        }

        // Display the answer returned by the backend.
        // Do not invent a replacement answer if retrieval fails.
        loadingMessage.textContent =
            data.answer ||
            "I couldn't find an answer in the available study notes.";

    } catch (error) {
        console.error(
            "Eger AI request failed:",
            error
        );

        loadingMessage.textContent =
            "I couldn't connect to Eger AI. Please check your connection and try again.";

    } finally {
        isSending = false;
        sendButton.disabled = false;

        chatArea.scrollTop = chatArea.scrollHeight;

        userInput.focus();
    }
}


// ==================================================
// SEND BUTTON
// ==================================================

if (sendButton) {
    sendButton.addEventListener(
        "click",
        sendMessage
    );
}


// ==================================================
// PRESS ENTER TO SEND
// ==================================================

if (userInput) {
    userInput.addEventListener(
        "keydown",
        function (event) {
            if (
                event.key === "Enter" &&
                !event.shiftKey
            ) {
                event.preventDefault();

                sendMessage();
            }
        }
    );
}
// =========================================
// EGER AI USER WELCOME SYSTEM
// =========================================

function initializeWelcome() {

    const savedName = localStorage.getItem("egerUserName");

    let userName = savedName;

    if (!savedName) {

        const enteredName = prompt(
            "Welcome to Eger AI! Please enter your username"
        );

        if (enteredName && enteredName.trim() !== "") {

            userName = enteredName.trim();

            localStorage.setItem(
                "egerUserName",
                userName
            );

        }
    }

    if (userName) {

        const greeting = savedName
            ? `Welcome back, ${userName}! `
            : `Welcome to Eger AI, ${userName}! 🎓`;

        showMessage("ai-message", greeting);

    } else {

        showMessage(
            "ai-message",
            "Welcome to Eger AI! "
        );

    }

}

initializeWelcome();