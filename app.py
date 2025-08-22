from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import sqlite3, os, requests
from dotenv import load_dotenv

load_dotenv()

APP_TITLE = os.getenv("APP_TITLE", "ChatGPT Clone (Flask)")
SITE_URL = os.getenv("SITE_URL", "http://localhost:5000")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")

if not SECRET_KEY:
    SECRET_KEY = "dev-secret"

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = SECRET_KEY

DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            model TEXT NOT NULL,
            system_prompt TEXT,
            temperature REAL NOT NULL DEFAULT 0.7,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

@app.before_request
def ensure_db():
    init_db()

def current_user():
    uid = session.get("user_id")
    if not uid: return None
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return user

@app.get("/")
def index():
    if current_user():
        return redirect(url_for("chat_page"))
    return redirect(url_for("login"))

@app.get("/signup")
def signup():
    if current_user():
        return redirect(url_for("chat_page"))
    return render_template("signup.html", app_title=APP_TITLE)

@app.post("/signup")
def do_signup():
    email = request.form.get("email","").strip().lower()
    username = request.form.get("username","").strip()
    password = request.form.get("password","")
    if not (email and username and password):
        return render_template("signup.html", error="All fields are required.", app_title=APP_TITLE)
    pw_hash = generate_password_hash(password)
    conn = db()
    try:
        conn.execute("INSERT INTO users (email, username, password_hash, created_at) VALUES (?,?,?,?)",
                     (email, username, pw_hash, datetime.utcnow().isoformat()))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        session["user_id"] = user["id"]
        return redirect(url_for("chat_page"))
    except sqlite3.IntegrityError:
        return render_template("signup.html", error="Email or username already exists.", app_title=APP_TITLE)
    finally:
        conn.close()

@app.get("/login")
def login():
    if current_user():
        return redirect(url_for("chat_page"))
    return render_template("login.html", app_title=APP_TITLE)

@app.post("/login")
def do_login():
    email = request.form.get("email","").strip().lower()
    password = request.form.get("password","")
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    conn.close()
    if not user or not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error="Invalid email or password.", app_title=APP_TITLE)
    session["user_id"] = user["id"]
    return redirect(url_for("chat_page"))

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/chat")
def chat_page():
    if not current_user(): return redirect(url_for("login"))
    return render_template("chat.html", app_title=APP_TITLE)

# ====== API ======
def require_auth():
    user = current_user()
    if not user: abort(401)
    return user

@app.get("/api/me")
def api_me():
    user = require_auth()
    return jsonify({"id": user["id"], "email": user["email"], "username": user["username"]})

@app.get("/api/models")
def api_models():
    # Static list; you can expand
    models = [
        "openai/gpt-4o-mini",
        "meta-llama/llama-3.1-70b-instruct:free",
        "mistralai/mistral-large",
        "google/gemini-flash-1.5",
    ]
    return jsonify(models)

@app.get("/api/chats")
def api_chats():
    user = require_auth()
    conn = db()
    rows = conn.execute("SELECT * FROM chats WHERE user_id=? ORDER BY updated_at DESC", (user["id"],)).fetchall()
    conn.close()
    chats = [dict(r) for r in rows]
    return jsonify(chats)

@app.post("/api/chats")
def api_create_chat():
    user = require_auth()
    data = request.get_json(force=True)
    title = (data.get("title") or "New chat").strip() or "New chat"
    model = (data.get("model") or "openai/gpt-4o-mini").strip()
    system_prompt = data.get("system_prompt") or ""
    temperature = float(data.get("temperature") or 0.7)
    now = datetime.utcnow().isoformat()
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT INTO chats (user_id, title, model, system_prompt, temperature, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (user["id"], title, model, system_prompt, temperature, now, now))
    chat_id = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"id": chat_id, "title": title})

@app.get("/api/chats/<int:chat_id>")
def api_get_chat(chat_id):
    user = require_auth()
    conn = db()
    chat = conn.execute("SELECT * FROM chats WHERE id=? AND user_id=?", (chat_id, user["id"])).fetchone()
    if not chat: 
        conn.close()
        abort(404)
    msgs = conn.execute("SELECT role, content, created_at FROM messages WHERE chat_id=? ORDER BY id ASC", (chat_id,)).fetchall()
    conn.close()
    return jsonify({"chat": dict(chat), "messages": [dict(m) for m in msgs]})

@app.post("/api/chats/<int:chat_id>/message")
def api_send_message(chat_id):
    user = require_auth()
    data = request.get_json(force=True)
    user_text = (data.get("content") or "").strip()
    if not user_text: return jsonify({"error":"content required"}), 400

    conn = db()
    chat = conn.execute("SELECT * FROM chats WHERE id=? AND user_id=?", (chat_id, user["id"])).fetchone()
    if not chat:
        conn.close()
        abort(404)

    # Insert user message
    now = datetime.utcnow().isoformat()
    conn.execute("INSERT INTO messages (chat_id, role, content, created_at) VALUES (?,?,?,?)",
                 (chat_id, "user", user_text, now))
    conn.commit()

    # Build conversation for OpenRouter
    msgs = conn.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY id ASC", (chat_id,)).fetchall()
    conn.close()

    messages = []
    if chat["system_prompt"]:
        messages.append({"role":"system","content":chat["system_prompt"]})
    for m in msgs:
        messages.append({"role": m["role"], "content": m["content"]})

    # Call OpenRouter (non-streaming)
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": SITE_URL,
        "X-Title": APP_TITLE,
    }
    payload = {
        "model": chat["model"],
        "temperature": float(chat["temperature"] or 0.7),
        "messages": messages
    }

    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        reply = data.get("choices",[{}])[0].get("message",{}).get("content","")
    except Exception as e:
        reply = f"⚠️ OpenRouter error: {e}"

    # Save assistant message and update chat
    conn = db()
    now2 = datetime.utcnow().isoformat()
    conn.execute("INSERT INTO messages (chat_id, role, content, created_at) VALUES (?,?,?,?)",
                 (chat_id, "assistant", reply, now2))
    # If first turn, update title based on first user message
    first_user = messages[1]["content"] if len(messages) >= 2 and messages[1]["role"] == "user" else None
    new_title = chat["title"]
    if first_user and chat["title"] == "New chat":
        new_title = (first_user[:40] + ("…" if len(first_user)>40 else ""))
    conn.execute("UPDATE chats SET updated_at=?, title=? WHERE id=?", (now2, new_title, chat_id))
    conn.commit()
    conn.close()

    return jsonify({"reply": reply, "title": new_title})

@app.post("/api/chats/<int:chat_id>/config")
def api_update_chat_config(chat_id):
    user = require_auth()
    data = request.get_json(force=True)
    model = data.get("model")
    system_prompt = data.get("system_prompt")
    temperature = data.get("temperature")
    conn = db()
    chat = conn.execute("SELECT * FROM chats WHERE id=? AND user_id=?", (chat_id, user["id"])).fetchone()
    if not chat:
        conn.close()
        abort(404)
    if model is not None:
        conn.execute("UPDATE chats SET model=? WHERE id=?", (model, chat_id))
    if system_prompt is not None:
        conn.execute("UPDATE chats SET system_prompt=? WHERE id=?", (system_prompt, chat_id))
    if temperature is not None:
        conn.execute("UPDATE chats SET temperature=? WHERE id=?", (float(temperature), chat_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.delete("/api/chats/<int:chat_id>")
def api_delete_chat(chat_id):
    user = require_auth()
    conn = db()
    chat = conn.execute("SELECT * FROM chats WHERE id=? AND user_id=?", (chat_id, user["id"])).fetchone()
    if not chat:
        conn.close()
        abort(404)
    conn.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
    conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(debug=True)
