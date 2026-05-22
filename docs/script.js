// Базовый URL бекенда
const API_URL = "https://ai-saas-site.onrender.com";

// Проверка email
function isValidEmail(email) {
    return email.includes("@") && email.includes(".");
}

// Показ ошибки
function showError(elementId, text) {
    const element = document.getElementById(elementId);
    if (element) {
        element.textContent = text;
    }
}

// Сохранение данных пользователя
function saveUser(userId, email) {
    localStorage.setItem("user_id", userId);
    localStorage.setItem("email", email);
}

// Выход
function logout() {
    localStorage.clear();
    window.location.href = "index.html";
}

// Проверка авторизации
function requireAuth() {
    const userId = localStorage.getItem("user_id");
    if (!userId) {
        window.location.href = "index.html";
    }
}

// Бургер меню
document.addEventListener("DOMContentLoaded", () => {
    const burger = document.getElementById("burgerBtn");
    const nav = document.getElementById("navMenu");
    if (burger && nav) {
        burger.addEventListener("click", () => {
            nav.classList.toggle("open");
        });
    }
});

// Вход
const loginForm = document.getElementById("loginForm");
if (loginForm) {
    loginForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const email = document.getElementById("loginEmail").value.trim();
        const password = document.getElementById("loginPassword").value.trim();
        showError("loginError", "");
        if (!email || !password) {
            return showError("loginError", "Все поля обязательны.");
        }
        if (!isValidEmail(email)) {
            return showError("loginError", "Введите корректный email.");
        }
        try {
            const response = await fetch(`${API_URL}/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password })
            });
            const data = await response.json();
            if (data.error) {
                return showError("loginError", data.error);
            }
            saveUser(data.user_id, data.email);
            window.location.href = "chat.html";
        } catch (error) {
            showError("loginError", "Сервер недоступен. Попробуйте позже.");
        }
    });
}

// Регистрация
const registerForm = document.getElementById("registerForm");
const verifyForm = document.getElementById("verifyForm");
let pendingEmail = "";

if (registerForm) {
    registerForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        const email = document.getElementById("registerEmail").value.trim();
        const password = document.getElementById("registerPassword").value.trim();
        const password2 = document.getElementById("registerPassword2").value.trim();

        showError("registerError", "");

        if (!email || !password || !password2) {
            return showError("registerError", "Все поля обязательны.");
        }
        if (!isValidEmail(email)) {
            return showError("registerError", "Введите корректный email.");
        }
        if (password.length < 3) {
            return showError("registerError", "Пароль должен быть минимум 3 символа.");
        }
        if (password !== password2) {
            return showError("registerError", "Пароли не совпадают.");
        }

        try {
            const response = await fetch(`${API_URL}/register`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password })
            });

            const data = await response.json();

            if (data.error) {
                return showError("registerError", data.error);
            }

            // Успешная регистрация — показываем форму верификации
            pendingEmail = email;
            registerForm.style.display = "none";
            verifyForm.style.display = "flex";
            document.getElementById("registerSuccess").textContent = "Код отправлен на почту!";

        } catch (error) {
            showError("registerError", "Сервер недоступен. Попробуйте позже.");
        }
    });
}

// Верификация
if (verifyForm) {
    verifyForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        const code = document.getElementById("verifyCode").value.trim();
        showError("verifyError", "");

        if (!code) {
            return showError("verifyError", "Введите код.");
        }

        try {
            const response = await fetch(`${API_URL}/verify`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email: pendingEmail, code })
            });

            const data = await response.json();

            if (data.error) {
                return showError("verifyError", data.error);
            }

            // Успешная верификация — автоматический вход
            const pwd = document.getElementById("registerPassword").value;
            const loginResp = await fetch(`${API_URL}/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email: pendingEmail, password: pwd })
            });

            const loginData = await loginResp.json();

            if (loginData.success) {
                saveUser(loginData.user_id, loginData.email);
                window.location.href = "chat.html";
            }

        } catch (error) {
            showError("verifyError", "Сервер недоступен. Попробуйте позже.");
        }
    });
}

// Повторная отправка кода
const resendLink = document.getElementById("resendCode");
if (resendLink) {
    resendLink.addEventListener("click", async (e) => {
        e.preventDefault();
        const pwd = document.getElementById("registerPassword").value;
        try {
            await fetch(`${API_URL}/register`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email: pendingEmail, password: pwd })
            });
            document.getElementById("registerSuccess").textContent = "Код отправлен повторно!";
        } catch (error) {
            showError("verifyError", "Не удалось отправить код.");
        }
    });
}

// Личный кабинет
if (window.location.pathname.includes("dashboard.html")) {
    requireAuth();
    const email = localStorage.getItem("email");
    const welcomeText = document.getElementById("welcomeText");
    if (welcomeText) {
        welcomeText.textContent = `Добро пожаловать, ${email}!`;
    }
}
