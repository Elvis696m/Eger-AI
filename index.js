let micButton = document.getElementById("micButton");
let userInput = document.getElementById("userInput");
let sendButton = document.getElementById("sendButton");

let chatArea = document.getElementById("chatArea");


/* MICROPHONE */

let recognition = new webkitSpeechRecognition();

recognition.continuous = false;
recognition.interimResults = false;
recognition.lang = "en-US";


recognition.onresult = function(event) {

    let speech = event.results[0][0].transcript;

    userInput.value = speech;

};


micButton.onclick = function() {

    recognition.start();

};


/* SEND BUTTON */

sendButton.onclick = function() {

    let message = userInput.value.trim();


    /* Don't send empty messages */

    if (message === "") {
        return;
    }


    /* Create user's message */

    let userMessage = document.createElement("div");

    userMessage.className = "user-message";

    userMessage.textContent = message;

    chatArea.appendChild(userMessage);


    /* Create Eger AI response */
fetch("http://127.0.0.1:5000/ask", {
    method: "POST",

    headers: {
        "Content-Type": "application/json"
    },

    body: JSON.stringify({
        question: message
    })
})
.then(response => response.json())
.then(data => {

    let aiMessage = document.createElement("div");

    aiMessage.className = "ai-message";

    aiMessage.textContent = data.answer;

    chatArea.appendChild(aiMessage);

})
.catch(error => {

    console.log("Error:", error);

});

    


    /* Clear input */

    userInput.value = "";

};