from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import random
import string
from datetime import datetime
import psycopg2
import requests
import resend

app = Flask(__name__)
CORS(app)

DATABASE_URL = os.getenv("DATABASE_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

if not DATABASE_URL:
    raise Exception("DATABASE_URL not found")

# ================= RESEND =================

resend.api_key = RESEND_API_KEY


def send_verification_email(to_email, code):
    if not RESEND_API_KEY:
        return

    try:
        resend.Emails.send({
            "from": "AI Chat <onboarding@resend.dev>",
            "to": to_email,
            "subject": "Код подтверждения",
            "html": f"""
            <div style="font-family:Arial;padding:20px">
                <h2>Ваш код</h2>
                <h1 style="color:#8b5cf6">{code}</h1>
            </div>
            """
        })
    except Exception as e:
        print("EMAIL ERROR:", e)


# ================= DB =================

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_users (
            email TEXT PRIMARY KEY,
            password TEXT,
            verification_code TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE,
            password TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ================= REGISTER =================

@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()

    email = data.get("email", "").strip()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({"error": "empty fields"}), 400

    code = "".join(random.choices(string.digits, k=6))

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO pending_users (email, password, verification_code, created_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (email)
        DO UPDATE SET verification_code=%s, password=%s
    """, (email, password, code, datetime.now().isoformat(), code, password))

    conn.commit()
    conn.close()

    send_verification_email(email, code)

    return jsonify({"success": True})


# ================= VERIFY (ВАЖНЫЙ ФИКС) =================

@app.route("/verify", methods=["POST"])
def verify():
    data = request.get_json()

    email = data.get("email", "").strip()
    code = data.get("code", "").strip()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT email, password FROM pending_users
        WHERE email=%s AND verification_code=%s
    """, (email, code))

    row = cur.fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "wrong code"}), 400

    # создаём пользователя
    cur.execute("""
        INSERT INTO users (email, password, created_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (email) DO NOTHING
    """, (row[0], row[1], datetime.now().isoformat()))

    # удаляем pending
    cur.execute("DELETE FROM pending_users WHERE email=%s", (email,))

    # получаем user_id
    cur.execute("SELECT id FROM users WHERE email=%s", (email,))
    user_id = cur.fetchone()[0]

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "user_id": user_id,
        "email": email
    })


# ================= LOGIN =================

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    email = data.get("email", "").strip()
    password = data.get("password", "").strip()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, email FROM users
        WHERE email=%s AND password=%s
    """, (email, password))

    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "invalid login"}), 400

    return jsonify({
        "user_id": row[0],
        "email": row[1]
    })


# ================= CHAT =================

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()

    message = data.get("message", "")

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
        r = requests.post(GROQ_API_URL, headers=headers, json=payload)
        ai = r.json()["choices"][0]["message"]["content"]
    except:
        ai = "AI error"

    return jsonify({"reply": ai})


@app.route("/")
def root():
    return "OK", 200


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
