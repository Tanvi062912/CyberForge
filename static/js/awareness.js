// =======================================
// CYBERFORGE CYBER SAFETY AWARENESS ENGINE
// static/js/awareness.js
// =======================================

function checkPassword() {
    let password = document.getElementById("password").value;
    let result = document.getElementById("result");

    if (!result) return;

    if (password.length < 6) {
        result.innerHTML = "Weak Password";
        result.style.color = "red";
    }
    else if (
        password.match(/[A-Z]/) &&
        password.match(/[0-9]/) &&
        password.match(/[^A-Za-z0-9]/)
    ) {
        result.innerHTML = "Strong Password";
        result.style.color = "green";
    }
    else {
        result.innerHTML = "Medium Password";
        result.style.color = "orange";
    }
}

function showAnswer(correct) {
    let result = document.getElementById("quiz-result");
    if (!result) return;

    if (correct) {
        result.innerHTML = "Correct! Never share OTP.";
        result.style.color = "green";
    }
    else {
        result.innerHTML = "Wrong! OTP should never be shared.";
        result.style.color = "red";
    }
}

function toggleMode() {
    // Toggles the custom target framework variables handled by your CSS class rules
    document.body.classList.toggle("light-mode");
}