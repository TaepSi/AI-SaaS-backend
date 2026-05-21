from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime
import requests
import json

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response

DB = "ai_saas.db"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# --- База данных ---

def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- Вспомогательные функции ---

def get_user_by_email(email):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()
    return row

def create_user(email, password):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cur.execute("INSERT INTO users (email, password, created_at) VALUES (?, ?, ?)", (email, password, now))
    conn.commit()
    user_id = cur.lastrowid
    conn.close()
    return user_id

def save_message(user_id, role, content):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cur.execute("INSERT INTO messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)", (user_id, role, content, now))
    conn.commit()
    conn.close()

def get_history(user_id):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT role, content FROM messages WHERE user_id = ? ORDER BY id ASC", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]

# --- Маршруты ---

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "ok", "ai": "Groq (Llama 3)"})

@app.route("/register", methods=["POST", "OPTIONS"])
def register():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    data = request.get_json()
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()
    if not email or not password:
        return jsonify({"error": "Email и пароль обязательны"}), 400
    if len(password) < 3:
        return jsonify({"error": "Пароль минимум 3 символа"}), 400
    existing = get_user_by_email(email)
    if existing:
        return jsonify({"error": "Пользователь с таким email уже существует"}), 400
    user_id = create_user(email, password)
    return jsonify({"success": True, "user_id": user_id})

@app.route("/login", methods=["POST", "OPTIONS"])
def login():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    data = request.get_json()
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()
    if not email or not password:
        return jsonify({"error": "Email и пароль обязательны"}), 400
    user = get_user_by_email(email)
    if not user or user[2] != password:
        return jsonify({"error": "Неверный email или пароль"}), 401
    return jsonify({"success": True, "user_id": user[0], "email": user[1]})

@app.route("/history", methods=["GET"])
def history():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id обязателен"}), 400
    return jsonify(get_history(int(user_id)))

@app.route("/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    data = request.get_json()
    user_id = data.get("user_id")
    message = data.get("message", "").strip()

    if not user_id or not message:
        return jsonify({"error": "user_id и message обязательны"}), 400

    # Сохраняем сообщение пользователя
    save_message(int(user_id), "user", message)

    # Если API-ключ не задан — возвращаем заглушку
    if not GROQ_API_KEY:
        fallback = f"Привет! Я демо-версия Groq (Llama 3). Вы написали: «{message}». Добавьте GROQ_API_KEY в Render."
        save_message(int(user_id), "ai", fallback)
        return Response(f"data: {fallback}\n\n", mimetype="text/event-stream")

    # Реальный запрос к Groq
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": message}],
            "stream": True
        }

        response = requests.post(GROQ_API_URL, headers=headers, json=payload, stream=True, timeout=30)

        if response.status_code != 200:
            error_msg = f"Ошибка Groq API: {response.status_code}"
            save_message(int(user_id), "ai", error_msg)
            return Response(f"data: {error_msg}\n\n", mimetype="text/event-stream")

        def generate():
            full_response = ""
            for line in response.iter_lines():
                if line:
                    line = line.decode("utf-8")
                    if line.startswith("data: "):
                        json_str = line[6:]
                        if json_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(json_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                full_response += content
                                yield f"data: {content}\n\n"
                        except:
                            pass
            if full_response:
                save_message(int(user_id), "ai", full_response)
            else:
                save_message(int(user_id), "ai", "Groq не ответил.")

        return Response(generate(), mimetype="text/event-stream")

    except Exception as e:
        error_msg = f"Ошибка AI: {str(e)}"
        save_message(int(user_id), "ai", error_msg)
        return Response(f"data: {error_msg}\n\n", mimetype="text/event-stream")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
