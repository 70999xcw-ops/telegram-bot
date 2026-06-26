from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import sqlite3
from datetime import datetime

# ==========================
# 8637437061:AAGM-gbf9YXjfixLszRU0lsdLbDOFTx6v_k
# ==========================
TOKEN = "8637437061:AAGM-gbf9YXjfixLszRU0lsdLbDOFTx6v_k"


# ==========================
# DATABASE
# ==========================
conn = sqlite3.connect("records.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS records(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    action TEXT,
    time TEXT
)
""")

conn.commit()


# ==========================
# MENU
# ==========================
keyboard = [
    ["🍚 吃饭 / Meal", "🚻 上厕所 / WC"],
    ["🚬 抽烟 / Smoke", "📋 其他 / Other"],
    ["📊 统计 / Report"]
]

reply_markup = ReplyKeyboardMarkup(
    keyboard,
    resize_keyboard=True
)


# ==========================
# START
# ==========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "欢迎使用\nWelcome",
        reply_markup=reply_markup
    )


# ==========================
# SAVE DATA
# ==========================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text

    name = update.effective_user.full_name

    user_id = update.effective_user.id

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if text == "📊 统计 / Report":

        cursor.execute("SELECT name,action,time FROM records ORDER BY id DESC LIMIT 20")

        rows = cursor.fetchall()

        if len(rows) == 0:
            await update.message.reply_text("暂无数据")
            return

        msg = "📊 Report\n\n"

        for r in rows:
            msg += f"{r[2]}\n{r[0]} - {r[1]}\n\n"

        await update.message.reply_text(msg)

        return

    cursor.execute(
        "INSERT INTO records(user_id,name,action,time) VALUES(?,?,?,?)",
        (user_id, name, text, now)
    )

    conn.commit()

    await update.message.reply_text(
        f"✅ 已记录\n\n{name}\n{text}\n{now}"
    )


# ==========================
# RUN
# ==========================
app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))

app.add_handler(MessageHandler(filters.TEXT, handle))

print("Bot Running...")

app.run_polling()
