from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import os
import random
import string
from datetime import datetime
import requests
import json
import psycopg2
import resend   # 🔥 ВОТ ЭТО ДОБАВИЛ

app = Flask(__name__)
CORS(app)

DATABASE_URL = os.getenv("DATABASE_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")  # 🔥 ДОБАВИЛ

if not DATABASE_URL:
    raise Exception("DATABASE_URL not found")


# ================= DB =================

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode='require')


# ================= EMAIL (RESEND) =================

resend.api_key = RESEND_API_KEY


def send_verification_email(to_email, code):
    if not RESEND_API_KEY:
        return

    try:
        resend.Emails.send({
            "from": "AI Chat <onboarding@resend.dev>",
            "to": to_email,
            "subject": "Подтверждение аккаунта — AI Chat",
            "html": f"""
            <div style="
                font-family: Inter, Arial;
                background: #0d1117;
                padding: 40px;
                color: #e5e7eb;
                border-radius: 16px;
                max-width: 500px;
                margin: auto;
            ">
                <h1 style="
                    font-size: 22px;
                    margin-bottom: 10px;
                ">
                    Подтвердите ваш аккаунт
                </h1>

                <p style="color:#9ca3af;">
                    Используйте код ниже, чтобы завершить регистрацию:
                </p>

                <div style="
                    font-size: 36px;
                    font-weight: bold;
                    letter-spacing: 6px;
                    margin: 30px 0;
                    padding: 16px;
                    text-align: center;
                    background: rgba(139,92,246,0.15);
                    border: 1px solid rgba(139,92,246,0.3);
                    border-radius: 12px;
                    color: #8b5cf6;
                ">
                    {code}
                </div>

                <p style="color:#6b7280; font-size: 13px;">
                    Если это были не вы — просто проигнорируйте это письмо.
                </p>
            </div>
            """
        })

    except Exception as e:
        print("EMAIL ERROR:", e)

# ================= REGISTER (ВАЖНО) =================

@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()

    email = data.get("email", "").strip()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({"error": "Все поля обязательны"}), 400

    code = ''.join(random.choices(string.digits, k=6))

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO pending_users (email, password, verification_code, created_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (email)
        DO UPDATE SET verification_code = EXCLUDED.verification_code
    """, (email, password, code, datetime.now().strftime("%Y-%m-%d %H:%M")))

    conn.commit()
    conn.close()

    print("VERIFICATION CODE:", code)

    # 🔥 ВОТ ЭТА СТРОКА ВКЛЮЧАЕТ EMAIL
    send_verification_email(email, code)

    return jsonify({"success": True})
