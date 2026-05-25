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

# ================= ENV =================

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
        print("NO RESEND KEY")
        return

    try:
        resend.Emails.send({
            "from": "AI Chat <onboarding@resend.dev>",
            "to": to_email,
            "subject": "AI Chat — код подтверждения",
            "html": f"""
            <div style="font-family:Arial;padding:20px">
                <h2>Код подтверждения</h2>
                <p>Ваш код:</p>
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
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE,
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ================= AUTH =================

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
        DO UPDATE SET verification_code = EXCLUDED.verification_code
    """, (email, password, code, datetime.now().isoformat()))

    conn.commit()
    conn.close()

    print("CODE:", code)

    send_verification_email(email, code)

    return jsonify({"success": True})


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
        return jsonify({"error": "wrong code"}), 400

    cur.execute("""
        INSERT INTO users (email, password, created_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (email) DO NOTHING
    """, (row[0], row[1], datetime.now().isoformat()))

    cur.execute("DELETE FROM pending_users WHERE email=%s", (email,))

    conn.commit()
    conn.close()

    return jsonify({"success": True})


# ================= CHAT =================

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()

    user_id = data.get("user_id")
    message = data.get("message", "")

    if not user_id or not message:
        return jsonify({"error": "bad request"}), 400

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
    except Exception as e:
        print(e)
        ai = "AI error"

    return jsonify({"reply": ai})


@app.route("/")
def root():
    return "OK", 200


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


# ================= START =================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
