let micButton = document.getElementById("micButton");
let userInput = document.getElementById("userInput");

let recognition = new webkitSpeechRecognition();

recognition.continuous = false;
recognition.interimResults = false;
recognition.lang = "en-US";

recognition.onresult = function(event) {
    let speech = event.results[0][0].transcript;

    userInput.value = speech;

    console.log(speech);
};

recognition.onerror = function(event) {
    console.log("Microphone error:", event.error);
};

micButton.onclick = function() {
    recognition.start();
};
let sendButton = document.getElementById("sendButton");

sendButton.onclick = function() {
    let message = userInput.value;

    if (message.trim() === "") {
        return;
    }

    console.log("User said:", message);
};