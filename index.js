
let userName = localStorage.getItem("userName");
const welcomeMessage = document.getElementById("welcomeMessage");

// Ask for username only if one has not been saved
if (!userName || !userName.trim()) {
    userName = prompt("Enter your username:");

    if (!userName || !userName.trim()) {
        userName = "Player";
    }

    userName = userName.trim();
    localStorage.setItem("userName", userName);
}

// Display welcome message
welcomeMessage.textContent = `Welcome back, ${userName}!`;

const results = document.querySelectorAll('input[type="radio"]');

const totalWins = document.querySelector("#totalWins");
const totalLosses = document.querySelector("#totalLosses");
const winRate = document.querySelector("#winRate");

// Restore saved results when the page loads
results.forEach(function (radio) {
    const savedResult = localStorage.getItem(radio.name);

    if (savedResult === radio.value) {
        radio.checked = true;
    }
});

// Calculate and display trading statistics
const updateStatistics = function () {
    let wins = 0;
    let losses = 0;

    // Count selected wins and losses
    results.forEach(function (radio) {
        if (radio.checked) {
            if (radio.value === "win") {
                wins++;
            } else if (radio.value === "loss") {
                losses++;
            }
        }
    });

    // Calculate total recorded trades
    let totalTrades = wins + losses;

    // Calculate win rate safely
    let winRateValue = 0;

    if (totalTrades > 0) {
        winRateValue = (wins / totalTrades) * 100;
    }

    // Display statistics on the webpage
    totalWins.textContent = wins;
    totalLosses.textContent = losses;
    winRate.textContent = Math.floor(winRateValue.toFixed(1))+ "%";
};

// Save a result and update statistics whenever a result changes
results.forEach(function (radio) {
    radio.addEventListener("change", function () {
        localStorage.setItem(radio.name, radio.value);
        updateStatistics();
    });
});

// Display correct statistics immediately when the page loads
updateStatistics();

