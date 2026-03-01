import streamlit as st
import sqlite3
import requests
import json
import uuid
import datetime
import re

# =========================================
# CONFIG
# =========================================
st.set_page_config(page_title="AI Car Advisor", layout="wide")

# =========================================
# DATABASE
# =========================================
conn = sqlite3.connect("database.db", check_same_thread=False)
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS users(
    username TEXT PRIMARY KEY,
    password TEXT,
    plan TEXT,
    daily_count INTEGER,
    last_reset TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS chats(
    chat_id TEXT,
    username TEXT,
    role TEXT,
    message TEXT
)
""")

conn.commit()

# =========================================
# SECURITY FILTER
# =========================================
def clean_text(text):
    pattern = r"[^\u0600-\u06FFa-zA-Z0-9\s\.\,\!\?\:\;\-\(\)\/]"
    return re.sub(pattern, "", text)

# =========================================
# AI STREAM (مع ربط السياق)
# =========================================
def chat_stream(prompt):

    system_prompt = """
أنت مستشار سيارات محترف.
يجب الرد باللغة العربية فقط.
إذا كان المستخدم يكمل على نفس الموضوع أكمل معه.
إذا بدأ موضوع جديد تعامل معه كسؤال مستقل.
استخدم تنسيق Markdown منظم.
"""

    # أخذ آخر 6 رسائل من المحادثة للسياق
    history = st.session_state.messages[-6:]

    conversation = system_prompt + "\n\n"

    for msg in history:
        if msg["role"] == "user":
            conversation += f"المستخدم: {msg['content']}\n"
        else:
            conversation += f"المساعد: {msg['content']}\n"

    payload = {
        "model": "qwen2.5:latest",
        "prompt": conversation,
        "stream": True,
        "temperature": 0.3
    }

    response = requests.post(
        "http://localhost:11434/api/generate",
        json=payload,
        stream=True
    )

    output = ""
    for line in response.iter_lines():
        if line:
            data = json.loads(line.decode("utf-8"))
            if "response" in data:
                output += data["response"]
                yield clean_text(output)

# =========================================
# SESSION INIT
# =========================================
if "logged" not in st.session_state:
    st.session_state.logged = False

if "messages" not in st.session_state:
    st.session_state.messages = []

if "chat_id" not in st.session_state:
    st.session_state.chat_id = str(uuid.uuid4())

# =========================================
# LOGIN / REGISTER
# =========================================
if not st.session_state.logged:

    st.title("🚗 AI Car Advisor")

    tab1, tab2 = st.tabs(["تسجيل دخول", "إنشاء حساب"])

    with tab1:
        user = st.text_input("اسم المستخدم")
        pwd = st.text_input("كلمة المرور", type="password")

        if st.button("دخول"):
            c.execute("SELECT * FROM users WHERE username=? AND password=?", (user, pwd))
            if c.fetchone():
                st.session_state.logged = True
                st.session_state.username = user
                st.rerun()
            else:
                st.error("بيانات غير صحيحة")

    with tab2:
        new_user = st.text_input("اسم مستخدم جديد")
        new_pwd = st.text_input("كلمة مرور جديدة", type="password")

        if st.button("إنشاء حساب"):
            try:
                c.execute("INSERT INTO users VALUES (?,?,?,?,?)",
                          (new_user, new_pwd, "Pro", 0, str(datetime.date.today())))
                conn.commit()
                st.success("تم إنشاء الحساب بنجاح")
            except:
                st.error("المستخدم موجود بالفعل")

# =========================================
# MAIN APP
# =========================================
else:

    c.execute("SELECT daily_count,last_reset,plan FROM users WHERE username=?",
              (st.session_state.username,))
    user_data = c.fetchone()

    today = str(datetime.date.today())

    if user_data[1] != today:
        c.execute("UPDATE users SET daily_count=?,last_reset=? WHERE username=?",
                  (0, today, st.session_state.username))
        conn.commit()
        user_data = (0, today, user_data[2])

    st.sidebar.title("💎 AI Car Advisor")
    st.sidebar.markdown(f"المستخدم: **{st.session_state.username}**")
    st.sidebar.markdown(f"الخطة: **{user_data[2]}**")
    st.sidebar.markdown(f"الاستخدام اليومي: {user_data[0]}")

    if st.sidebar.button("➕ محادثة جديدة"):
        st.session_state.chat_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()

    st.sidebar.markdown("### 📂 المحادثات السابقة")

    c.execute("SELECT DISTINCT chat_id FROM chats WHERE username=?",
              (st.session_state.username,))
    chats = c.fetchall()

    for chat in chats:
        if st.sidebar.button(chat[0][:6], key=chat[0]):
            st.session_state.chat_id = chat[0]
            c.execute("SELECT role,message FROM chats WHERE chat_id=? AND username=?",
                      (chat[0], st.session_state.username))
            st.session_state.messages = [
                {"role": r, "content": m} for r, m in c.fetchall()
            ]
            st.rerun()

    if st.sidebar.button("تسجيل خروج"):
        st.session_state.logged = False
        st.session_state.messages = []
        st.rerun()

    st.title("💬 مستشارك الذكي للسيارات")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("اسأل عن أي سيارة...")

    if user_input:

        st.session_state.messages.append({"role": "user", "content": user_input})
        c.execute("INSERT INTO chats VALUES (?,?,?,?)",
                  (st.session_state.chat_id,
                   st.session_state.username,
                   "user",
                   user_input))
        conn.commit()

        with st.chat_message("assistant"):
            placeholder = st.empty()
            full_response = ""

            for chunk in chat_stream(user_input):
                full_response = chunk
                placeholder.markdown(full_response)

        st.session_state.messages.append({"role": "assistant", "content": full_response})
        c.execute("INSERT INTO chats VALUES (?,?,?,?)",
                  (st.session_state.chat_id,
                   st.session_state.username,
                   "assistant",
                   full_response))
        conn.commit()

        c.execute("UPDATE users SET daily_count=daily_count+1 WHERE username=?",
                  (st.session_state.username,))
        conn.commit()

        st.rerun()