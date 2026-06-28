import os
import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN")

BJ_TZ = ZoneInfo("Asia/Shanghai")
DATA_FILE = "data.json"

GROUP_IDS = [
    -1003937059366,
    -5424509783,
]

keyboard = ReplyKeyboardMarkup(
    [
        ["上班/on", "下班/off", "吃饭/meal"],
        ["上厕所/wc", "抽烟/smoke", "其他"],
        ["回坐/back", "统计/report"]
    ],
    resize_keyboard=True
)


def now_time():
    return datetime.now(BJ_TZ)


def today_key():
    return now_time().strftime("%Y-%m-%d")


def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_name(update):
    user = update.effective_user
    return user.full_name or user.first_name or "用户"


def init_user(data, day, uid, name):
    data.setdefault(day, {})
    data[day].setdefault(uid, {
        "name": name,
        "on": None,
        "off": None,
        "meal": 0,
        "toilet": 0,
        "smoke": 0,
        "other": 0,
        "back": 0,
        "away": None
    })


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 打卡机器人已启动\n请点击下面按钮操作\n\n发送 /id 获取群ID",
        reply_markup=keyboard
    )


async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat ID: {update.effective_chat.id}")


async def timeout_notice(context: ContextTypes.DEFAULT_TYPE):
    info = context.job.data
    uid = info["uid"]
    name = info["name"]
    day = info["day"]

    data = load_data()
    away = data.get(day, {}).get(uid, {}).get("away")

    if away is None:
        return

    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=f"⚠️ {name} 已超时，请尽快回坐。"
    )


async def go_away(update, context, kind, label, mins):
    data = load_data()
    day = today_key()
    uid = str(update.effective_user.id)
    name = get_name(update)
    now = now_time()

    init_user(data, day, uid, name)

    data[day][uid][kind] += mins
    data[day][uid]["away"] = {
        "kind": kind,
        "label": label,
        "start": now.isoformat(),
        "mins": mins
    }

    save_data(data)

    for job in context.job_queue.get_jobs_by_name(f"timeout_{uid}"):
        job.schedule_removal()

    context.job_queue.run_once(
        timeout_notice,
        mins * 60,
        chat_id=update.effective_chat.id,
        data={
            "uid": uid,
            "name": name,
            "day": day
        },
        name=f"timeout_{uid}"
    )

    await update.message.reply_text(
        f"✅ {label}已记录\n"
        f"⏱ 规定时间：{mins}分钟\n"
        f"🕒 开始时间：{now.strftime('%Y-%m-%d %H:%M:%S')}",
        reply_markup=keyboard
    )


async def daily_report(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    day = today_key()

    if day not in data or not data[day]:
        msg = f"📊 每日考勤统计 {day}\n\n暂无数据"
    else:
        msg = f"📊 每日考勤统计 {day}（北京时间）\n\n"

        for user_data in data[day].values():
            on_text = "未打卡"
            off_text = "未打卡"
            work_text = "未计算"

            if user_data.get("on"):
                on_dt = datetime.fromisoformat(user_data["on"])
                on_text = on_dt.strftime("%H:%M:%S")

                if user_data.get("off"):
                    off_dt = datetime.fromisoformat(user_data["off"])
                    off_text = off_dt.strftime("%H:%M:%S")
                    work_minutes = int((off_dt - on_dt).total_seconds() // 60)
                    work_text = f"{work_minutes // 60}小时{work_minutes % 60}分钟"

            msg += (
    f"👤 {user_data.get('name', '用户')}\n"
    f"🕘 上班：{on_text}\n"
    f"🕕 下班：{off_text}\n"
    f"🕒 工时：{work_text}\n"
    f"🍚 吃饭：{user_data.get('meal', 0)}分钟\n"
    f"🚽 厕所：{user_data.get('toilet', 0)}分钟\n"
    f"🚬 抽烟：{user_data.get('smoke', 0)}分钟\n"
    f"📌 其他：{user_data.get('other', 0)}分钟\n"
    f"🔄 回坐：{user_data.get('back', 0)}次\n\n"
            )

    for group_id in GROUP_IDS:
        await context.bot.send_message(chat_id=group_id, text=msg)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    data = load_data()
    day = today_key()
    uid = str(update.effective_user.id)
    name = get_name(update)
    now = now_time()

    init_user(data, day, uid, name)

    if text == "上班/on":
        data[day][uid]["on"] = now.isoformat()
        data[day][uid]["off"] = None
        save_data(data)

        await update.message.reply_text(
            f"✅ 上班打卡成功\n"
            f"🕘 上班时间：{now.strftime('%Y-%m-%d %H:%M:%S')}",
            reply_markup=keyboard
        )

    elif text == "下班/off":
        work_day = day
        on_time_str = data.get(day, {}).get(uid, {}).get("on")
    
        if not on_time_str:
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    
            if uid in data.get(yesterday, {}) and data[yesterday][uid].get("on") and not data[yesterday][uid].get("off"):
                work_day = yesterday
                on_time_str = data[work_day][uid].get("on")
    
        if not on_time_str:
            await update.message.reply_text("❌ 请先上班打卡", reply_markup=keyboard)
            return
    
        on_time = datetime.fromisoformat(on_time_str)
        total_minutes = int((now - on_time).total_seconds() // 60)
    
        data[work_day][uid]["off"] = now.isoformat()
        save_data(data)
    
        await update.message.reply_text(
            f"✅ 下班打卡成功\n"
            f"🕘 上班时间：{on_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🕕 下班时间：{now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🕒 本次工时：{total_minutes // 60}小时{total_minutes % 60}分钟",
            reply_markup=keyboard
        )
    elif text == "吃饭/meal":
        await go_away(update, context, "meal", "吃饭", 30)

    elif text == "上厕所/wc":
        await go_away(update, context, "toilet", "上厕所", 15)

    elif text == "抽烟/smoke":
        await go_away(update, context, "smoke", "抽烟", 15)

    elif text == "其他":
        await go_away(update, context, "other", "其他", 20)

    elif text == "回坐/back":
        work_day = day
        away = data[day][uid].get("away")

        if away is None:
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            if uid in data.get(yesterday, {}):
                old_away = data[yesterday][uid].get("away")
                if old_away:
                    work_day = yesterday
                    away = old_away

        data[work_day][uid]["back"] += 1

        for job in context.job_queue.get_jobs_by_name(f"timeout_{uid}"):
            job.schedule_removal()

        if away is None:
            save_data(data)
            await update.message.reply_text(
                "❌ 未找到离开记录\n\n"
                "请先点击：\n"
                "🍚 吃饭/meal\n"
                "🚽 上厕所/wc\n"
                "🚬 抽烟/smoke\n"
                "📌 其他",
                reply_markup=keyboard
            )
            return

        start = datetime.fromisoformat(away["start"])
        actual_minutes = int((now - start).total_seconds() // 60)
        allowed = away.get("mins", 0)

        data[work_day][uid]["away"] = None
        save_data(data)

        if actual_minutes <= allowed:
            msg = (
                "✅ 准时回坐\n\n"
                f"👤 {name}\n"
                f"📌 类型：{away['label']}\n"
                f"⏱ 实际离开：{actual_minutes}分钟\n"
                f"🕒 回坐时间：{now.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        else:
            overtime = actual_minutes - allowed
            msg = (
                "⚠️ 超时回坐\n\n"
                f"👤 {name}\n"
                f"📌 类型：{away['label']}\n"
                f"⏱ 实际离开：{actual_minutes}分钟\n"
                f"⌛ 超时：{overtime}分钟\n"
                f"🕒 回坐时间：{now.strftime('%Y-%m-%d %H:%M:%S')}"
            )

        await update.message.reply_text(
            msg,
            reply_markup=keyboard
        )

    elif text == "统计/report":
        user_data = data[day][uid]

        on_text = "未打卡"
        off_text = "未打卡"
        work_text = "未计算"

        if user_data.get("on"):
            on_dt = datetime.fromisoformat(user_data["on"])
            on_text = on_dt.strftime("%Y-%m-%d %H:%M:%S")

        if user_data.get("off"):
            off_dt = datetime.fromisoformat(user_data["off"])
            off_text = off_dt.strftime("%Y-%m-%d %H:%M:%S")
            work_minutes = int((off_dt - on_dt).total_seconds() // 60)
            work_text = f"{work_minutes // 60}小时{work_minutes % 60}分钟"

        await update.message.reply_text(
            f"📊 今日统计\n\n"
            f"👤 姓名：{user_data.get('name', name)}\n"
            f"🕘 上班：{on_text}\n"
            f"🕕 下班：{off_text}\n"
            f"🕒 工时：{work_text}\n\n"
            f"🍚 吃饭：{user_data.get('meal', 0)}分钟\n"
            f"🚽 厕所：{user_data.get('toilet', 0)}分钟\n"
                        f"🚬 抽烟：{user_data.get('smoke', 0)}分钟\n"
            f"📌 其他：{user_data.get('other', 0)}分钟\n"
            f"🔄 回坐：{user_data.get('back', 0)}次",
            reply_markup=keyboard
        )



if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("id", get_id))

app.add_handler(
    MessageHandler(
        filters.Regex(
            r"^(上班/on|下班/off|吃饭/meal|上厕所/wc|抽烟/smoke|其他|回坐/back|统计/report)$"
        ),
        handle_message
    )
)

app.job_queue.run_daily(
    daily_report,
    time=time(23, 55, tzinfo=BJ_TZ),
    name="daily_report"
)

print("Bot started OK")

app.run_polling()
# redeploy
