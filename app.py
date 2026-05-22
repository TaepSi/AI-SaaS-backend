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
CORS(app)

DATABASE_URL = os.getenv("DATABASE_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.rambler.ru")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

if not DATABASE_URL:
    raise Exception("DATABASE_URL not found")


def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode='require')


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            verification_code TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
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

    cur.execute("""
        INSERT INTO pending_users
        (email, password, verification_code, created_at)
        VALUES (%s, %s, %s, %s)
    """, (email, password, code, now))

    conn.commit()
    conn.close()


def verify_and_create_user(email, code):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM pending_users
        WHERE email = %s AND verification_code = %s
    """, (email, code))

    row = cur.fetchone()

    if not row:
        conn.close()
        return None

    cur.execute("""
        INSERT INTO users
        (email, password, created_at)
        VALUES (%s, %s, %s)
    """, (row[1], row[2], row[4]))

    cur.execute(
        "DELETE FROM pending_users WHERE email = %s",
        (email,)
    )

    conn.commit()

    cur.execute(
        "SELECT id FROM users WHERE email = %s",
        (email,)
    )

    user_id = cur.fetchone()[0]

    conn.close()

    return user_id


def save_message(user_id, role, content):
    conn = get_conn()
    cur = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    cur.execute("""
        INSERT INTO messages
        (user_id, role, content, created_at)
        VALUES (%s, %s, %s, %s)
    """, (user_id, role, content, now))

    conn.commit()
    conn.close()


def get_history(user_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT role, content
        FROM messages
        WHERE user_id = %s
        ORDER BY id ASC
    """, (user_id,))

    rows = cur.fetchall()

    conn.close()

    return [
        {
            "role": r[0],
            "content": r[1]
        }
        for r in rows
    ]


def send_verification_email(to_email, code):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        return

    msg = MIMEText(
        f"Ваш код верификации: {code}"
    )

    msg["Subject"] = "AI Chat Verification"
    msg["From"] = SMTP_EMAIL
    msg["To"] = to_email

    try:
        server = smtplib.SMTP_SSL(
            SMTP_HOST,
            SMTP_PORT
        )

        server.login(
            SMTP_EMAIL,
            SMTP_PASSWORD
        )

        server.sendmail(
            SMTP_EMAIL,
            to_email,
            msg.as_string()
        )

        server.quit()

    except Exception as e:
        print(e)


@app.route("/")
def home():
    return jsonify({
        "status": "ok"
    })


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()

    email = data.get("email", "").strip()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({
            "error": "Все поля обязательны"
        }), 400

    existing = get_user_by_email(email)

    if existing:
        return jsonify({
            "error": "Пользователь уже существует"
        }), 400

    code = ''.join(
        random.choices(string.digits, k=6)
    )

    pending = get_pending_user(email)

    conn = get_conn()
    cur = conn.cursor()

    if pending:
        cur.execute("""
            UPDATE pending_users
            SET verification_code = %s
            WHERE email = %s
        """, (code, email))

    else:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        cur.execute("""
            INSERT INTO pending_users
            (email, password, verification_code, created_at)
            VALUES (%s, %s, %s, %s)
        """, (email, password, code, now))

    conn.commit()
    conn.close()

    print("VERIFICATION CODE:", code)
    # send_verification_email(email, code)

    return jsonify({
        "success": True
    })


@app.route("/verify", methods=["POST"])
def verify():
    data = request.get_json()

    email = data.get("email", "").strip()
    code = data.get("code", "").strip()

    user_id = verify_and_create_user(email, code)

    if not user_id:
        return jsonify({
            "error": "Неверный код"
        }), 400

    return jsonify({
        "success": True,
        "user_id": user_id
    })


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    email = data.get("email", "").strip()
    password = data.get("password", "").strip()

    user = get_user_by_email(email)

    if not user or user[2] != password:
        return jsonify({
            "error": "Неверный email или пароль"
        }), 401

    return jsonify({
        "success": True,
        "user_id": user[0],
        "email": user[1]
    })


@app.route("/history")
def history():
    user_id = request.args.get("user_id")

    if not user_id:
        return jsonify({
            "error": "user_id required"
        }), 400

    return jsonify(
        get_history(int(user_id))
    )


@app.route("/stats")
def stats():
    user_id = request.args.get("user_id")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*)
        FROM messages
        WHERE user_id = %s
        AND role = 'user'
    """, (user_id,))

    sent = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM messages
        WHERE user_id = %s
        AND role = 'ai'
    """, (user_id,))

    received = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(DISTINCT created_at)
        FROM messages
        WHERE user_id = %s
    """, (user_id,))

    days = cur.fetchone()[0]

    conn.close()

    return jsonify({
        "sent": sent,
        "received": received,
        "days": days,
        "tokens": 0
    })


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()

    user_id = data.get("user_id")
    message = data.get("message", "")

    if not user_id or not message:
        return jsonify({"error": "message required"}), 400

    save_message(int(user_id), "user", message)

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "user", "content": message}
        ]
    }

    try:
        response = requests.post(
            GROQ_API_URL,
            headers=headers,
            json=payload,
            timeout=30
        )

        data = response.json()

        ai_text = data["choices"][0]["message"]["content"]

    except Exception as e:
        print("AI ERROR:", e)
        ai_text = "Ошибка AI сервера"

    save_message(int(user_id), "ai", ai_text)

    return jsonify({
        "reply": ai_text
    })

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
