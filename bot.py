from telegram import (
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import sqlite3
import asyncio
from datetime import datetime

#==========================
# TOKEN
#==========================

TOKEN = "DÁN_TOKEN_MỚI_CỦA_BẠN_VÀO_ĐÂY"

#==========================
# DATABASE
#==========================

conn = sqlite3.connect(
    "records.db",
    check_same_thread=False
)

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

#==========================
# MENU
#==========================

keyboard = [
    ["🍚 吃饭 / Meal", "🚻 上厕所 / WC"],
    ["🚬 抽烟 / Smoke", "📋 其他 / Other"],
    ["↩️ 回来 / Back"],
    ["📊 统计 / Report"]
]

reply_markup = ReplyKeyboardMarkup(
    keyboard,
    resize_keyboard=True
)

#==========================
# TIME LIMIT
#==========================

LIMITS = {
    "🍚 吃饭 / Meal": 30 * 60,
    "🚻 上厕所 / WC": 15 * 60,
    "🚬 抽烟 / Smoke": 13 * 60,
}

running = {}

waiting_reason = set()

#==========================
# START
#==========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "欢迎使用\nWelcome",
        reply_markup=reply_markup
    )

#==========================
# WARNING
#==========================

async def timeout_warning(
    chat_id,
    username,
    action,
    app
):

    if action not in LIMITS:
        return

    await asyncio.sleep(LIMITS[action])

    if username in running:

        await app.bot.send_message(
            chat_id=chat_id,
            text=(
                "⚠️ 超时提醒\n\n"
                f"{username}\n"
                f"{action}\n\n"
                "已经超过规定时间，请尽快回来。"
            )
        )
      #==========================
# HANDLE
#==========================

async def handle(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text
    name = update.effective_user.full_name
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    #==========================
    # OTHER - nhập lý do
    #==========================

    if name in waiting_reason:

        waiting_reason.remove(name)

        action = f"📋 Other - {text}"

        cursor.execute(
            "INSERT INTO records(user_id,name,action,time) VALUES(?,?,?,?)",
            (user_id, name, action, now)
        )

        conn.commit()

        running[name] = action

        await update.message.reply_text(
            f"✅ 已记录\n\n{name}\n{action}\n{now}",
            reply_markup=reply_markup
        )

        return

    #==========================
    # OTHER
    #==========================

    if text == "📋 其他 / Other":

        waiting_reason.add(name)

        await update.message.reply_text(
            "请输入原因："
        )

        return

    #==========================
    # Meal / WC / Smoke
    #==========================

    if text in LIMITS:

        cursor.execute(
            "INSERT INTO records(user_id,name,action,time) VALUES(?,?,?,?)",
            (user_id, name, text, now)
        )

        conn.commit()

        running[name] = text

        context.application.create_task(
            timeout_warning(
                chat_id,
                name,
                text,
                context.application
            )
        )

        await update.message.reply_text(
            f"✅ 已记录\n\n{name}\n{text}\n{now}"
        )

        return
          #==========================
    # BACK
    #==========================

    if text == "↩️ 回来 / Back":

        if name in running:

            action = running.pop(name)

            cursor.execute(
                "INSERT INTO records(user_id,name,action,time) VALUES(?,?,?,?)",
                (user_id, name, "↩️ Back", now)
            )

            conn.commit()

            await update.message.reply_text(
                f"✅ 欢迎回来\n\n"
                f"{name}\n"
                f"结束：{action}\n"
                f"{now}"
            )

        else:

            await update.message.reply_text(
                "你目前没有外出记录。"
            )

        return

    #==========================
    # REPORT
    #==========================

    if text == "📊 统计 / Report":

        admins = await context.bot.get_chat_administrators(chat_id)

        admin_ids = [a.user.id for a in admins]

        if user_id not in admin_ids:

            await update.message.reply_text(
                "❌ Chỉ Admin mới được xem Report."
            )

            return

        cursor.execute("""
            SELECT name,action,time
            FROM records
            ORDER BY id DESC
            LIMIT 30
        """)

        rows = cursor.fetchall()

        if not rows:

            await update.message.reply_text("暂无数据")

            return

        msg = "📊 Report\n\n"

        for row in rows:

            msg += (
                f"👤 {row[0]}\n"
                f"📌 {row[1]}\n"
                f"🕒 {row[2]}\n\n"
            )

        await update.message.reply_text(msg)

        return

    await update.message.reply_text(
        "请选择菜单。"
    )
  
