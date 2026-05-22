from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import os
import random
import string
from datetime import datetime
import requests
import json
import psycopg2
import smtplib
from email.mime.text import MIMEText

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response

DATABASE_URL = os.getenv("DATABASE_URL", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.rambler.ru")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS messages CASCADE")
    cur.execute("DROP TABLE IF EXISTS users CASCADE")
    cur.execute("DROP TABLE IF EXISTS pending_users CASCADE")
    cur.execute("""
        CREATE TABLE pending_users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            verification_code TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE messages (
            id SERIAL PRIMARY KEY,
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
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    conn.close()
    return row

def get_pending_user(email):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM pending_users WHERE email = %s", (email,))
    row = cur.fetchone()
    conn.close()
    return row

def create_pending_user(email, password, code):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cur.execute("INSERT INTO pending_users (email, password, verification_code, created_at) VALUES (%s, %s, %s, %s)", (email, password, code, now))
    conn.commit()
    conn.close()

def verify_and_create_user(email, code):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM pending_users WHERE email = %s AND verification_code = %s", (email, code))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    # Переносим в основную таблицу
    cur.execute("INSERT INTO users (email, password, created_at) VALUES (%s, %s, %s)", (row[1], row[2], row[3]))
    user_id = cur.fetchone()[0] if hasattr(cur, 'fetchone') else None
    # Удаляем из pending
    cur.execute("DELETE FROM pending_users WHERE email = %s", (email,))
    conn.commit()
    conn.close()
    # Получаем id созданного пользователя
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
    user_id = cur.fetchone()[0]
    conn.close()
    return user_id

def save_message(user_id, role, content):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cur.execute("INSERT INTO messages (user_id, role, content, created_at) VALUES (%s, %s, %s, %s)", (user_id, role, content, now))
    conn.commit()
    conn.close()

def get_history(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT role, content FROM messages WHERE user_id = %s ORDER BY id ASC", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]

def send_verification_email(to_email, code):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        return
    msg = MIMEText(f"Ваш код верификации: {code}\n\nЭто демо-проект портфолио. Пожалуйста, не создавайте лишние аккаунты.")
    msg["Subject"] = "AI SaaS — Код верификации"
    msg["From"] = SMTP_EMAIL
    msg["To"] = to_email
    try:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        server.quit()
    except:
        pass

# --- Маршруты ---

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "ok", "ai": "Groq", "db": "Neon"})

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

    pending = get_pending_user(email)
    if pending:
        # Уже есть неверифицированный — генерируем новый код
        code = ''.join(random.choices(string.digits, k=6))
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE pending_users SET verification_code = %s WHERE email = %s", (code, email))
        conn.commit()
        conn.close()
        send_verification_email(email, code)
        return jsonify({"success": True, "message": f"Новый код отправлен. Ваш код: {code}"})

    code = ''.join(random.choices(string.digits, k=6))
    create_pending_user(email, password, code)
    send_verification_email(email, code)
    return jsonify({"success": True, "message": f"Код отправлен. Ваш код: {code}"})

@app.route("/verify", methods=["POST", "OPTIONS"])
def verify():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    data = request.get_json()
    email = data.get("email", "").strip()
    code = data.get("code", "").strip()
    if not email or not code:
        return jsonify({"error": "Email и код обязательны"}), 400
    user_id = verify_and_create_user(email, code)
    if user_id:
        return jsonify({"success": True, "user_id": user_id})
    return jsonify({"error": "Неверный код"}), 400

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

@app.route("/stats", methods=["GET"])
def stats():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id обязателен"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM messages WHERE user_id = %s AND role = 'user'", (user_id,))
    sent = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM messages WHERE user_id = %s AND role = 'ai'", (user_id,))
    received = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT created_at::date) FROM messages WHERE user_id = %s", (user_id,))
    days = cur.fetchone()[0]
    conn.close()
    return jsonify({"sent": sent, "received": received, "days": days, "tokens": 0})

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
    save_message(int(user_id), "user", message)
    if not GROQ_API_KEY:
        fallback = f"Привет! Я демо-версия Groq. Вы написали: «{message}»."
        save_message(int(user_id), "ai", fallback)
        return Response(f"data: {fallback}\n\n", mimetype="text/event-stream")
    try:
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": message}], "stream": True}
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
