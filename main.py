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
ADMIN_IDS = [
    "6607594162"
]
keyboard = ReplyKeyboardMarkup(
    [
        ["上班/on", "下班/off", "吃饭/meal"],
        ["上厕所/wc", "抽烟/smoke", "其他"],
        ["回坐/back", "统计/report", "月统计/month"],
        ["管理员后台/admin"]
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
    except:
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

    if not away:
        return

    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=f"⚠️🚨 {name} 已超时，请尽快回坐。❗️❗️❗️"
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
    now = now_time()
    
    report_items = []

    # 今天完成下班的所有记录（包括跨天夜班）
    for d, day_data in data.items():
        for user_data in day_data.values():
            if user_data.get("on") and user_data.get("off"):
                off_dt = datetime.fromisoformat(user_data["off"])
                if off_dt.strftime("%Y-%m-%d") == day:
                    report_items.append(user_data)

    if not report_items:
        msg = f"📊 每日考勤统计 {day}\n\n暂无数据"
    else:
        msg = f"📊 每日考勤统计 {day}（北京时间）\n\n"

        for user_data in report_items:
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
    print(repr(text))
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
        away = data[day][uid].get("away")
        data[day][uid]["back"] += 1

        for job in context.job_queue.get_jobs_by_name(f"timeout_{uid}"):
            job.schedule_removal()

        if not away:
            save_data(data)
            await update.message.reply_text(
                f"✅ 回坐成功\n"
                f"🕒 回坐时间：{now.strftime('%Y-%m-%d %H:%M:%S')}",
                reply_markup=keyboard
            )
            return

        start = datetime.fromisoformat(away["start"])
        actual_minutes = int((now - start).total_seconds() // 60)
        allowed = away.get("mins", 0)

        data[day][uid]["away"] = None
        save_data(data)

        result = "✅ 准时回坐" if actual_minutes <= allowed else f"⚠️ 超时 {actual_minutes - allowed} 分钟"

        await update.message.reply_text(
            f"{result}\n"
            f"📌 类型：{away['label']}\n"
            f"⏱ 实际离开：{actual_minutes}分钟\n"
            f"🕒 回坐时间：{now.strftime('%Y-%m-%d %H:%M:%S')}",
            reply_markup=keyboard
        )

    elif text == "统计/report":
        report_day = day
        user_data = data[day][uid]
    
        # 如果今天没有上班记录，就查昨天夜班记录
        if not user_data.get("on"):
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    
            if uid in data.get(yesterday, {}) and data[yesterday][uid].get("on"):
                report_day = yesterday
                user_data = data[yesterday][uid]
    
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
            else:
                work_minutes = int((now - on_dt).total_seconds() // 60)
                work_text = f"进行中，已上班 {work_minutes // 60}小时{work_minutes % 60}分钟"
    
        await update.message.reply_text(
            f"📊 统计 {report_day}\n\n"
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
    
    elif text == "月统计/month":
        month = now.strftime("%Y-%m")
        is_admin = str(uid) in ADMIN_IDS
    
        total_days = 0
        total_work = 0
        total_meal = 0
        total_toilet = 0
        total_smoke = 0
        total_other = 0
        total_back = 0
    
        users_result = {}
    
        for d, day_data in data.items():
            if not d.startswith(month):
                continue
    
            for user_id, user_data in day_data.items():
                if not is_admin and user_id != uid:
                    continue
    
                name2 = user_data.get("name", "用户")
    
                if name2 not in users_result:
                    users_result[name2] = {
                        "days": 0,
                        "work": 0,
                        "meal": 0,
                        "toilet": 0,
                        "smoke": 0,
                        "other": 0,
                        "back": 0
                    }
    
                if user_data.get("on"):
                    users_result[name2]["days"] += 1
    
                if user_data.get("on") and user_data.get("off"):
                    on_dt = datetime.fromisoformat(user_data["on"])
                    off_dt = datetime.fromisoformat(user_data["off"])
                    mins = int((off_dt - on_dt).total_seconds() // 60)
                    users_result[name2]["work"] += mins
    
                users_result[name2]["meal"] += user_data.get("meal", 0)
                users_result[name2]["toilet"] += user_data.get("toilet", 0)
                users_result[name2]["smoke"] += user_data.get("smoke", 0)
                users_result[name2]["other"] += user_data.get("other", 0)
                users_result[name2]["back"] += user_data.get("back", 0)
    
        if not users_result:
            await update.message.reply_text("📊 本月暂无统计数据", reply_markup=keyboard)
            return
    
        msg = f"📊 月统计 {month}\n\n"
    
        for n, s in users_result.items():
            work = s["work"]
            away = s["meal"] + s["toilet"] + s["smoke"] + s["other"]
            real_work = max(work - away, 0)
    
            msg += (
                f"👤 {n}\n"
                f"📅 出勤：{s['days']}天\n"
                f"🕒 总工时：{work // 60}小时{work % 60}分钟\n"
                f"✅ 实际工时：{real_work // 60}小时{real_work % 60}分钟\n"
                f"🍚 吃饭：{s['meal']}分钟\n"
                f"🚽 厕所：{s['toilet']}分钟\n"
                f"🚬 抽烟：{s['smoke']}分钟\n"
                f"📌 其他：{s['other']}分钟\n"
                f"🔄 回坐：{s['back']}次\n\n"
            )
    
        await update.message.reply_text(msg, reply_markup=keyboard)

    elif text == "管理员后台/admin":
        if str(uid) not in ADMIN_IDS:
            await update.message.reply_text("❌ 你不是管理员，不能使用后台。", reply_markup=keyboard)
            return

        today_data = data.get(day, {})
    
        online_count = 0
        off_count = 0
        night_count = 0
        day_count = 0
    
        for user_data in today_data.values():
            if user_data.get("on"):
                on_dt = datetime.fromisoformat(user_data["on"])

                if on_dt.hour >= 17:
                    night_count += 1
                else:
                    day_count += 1

                if user_data.get("off"):
                    off_count += 1
                else:
                    online_count += 1

        await update.message.reply_text(
            f"👑 管理后台\n\n"
            f"👥 今日在线：{online_count}人\n"
            f"✅ 今日下班：{off_count}人\n"
            f"🔴 未下班：{online_count}人\n"
            f"🌙 夜班：{night_count}人\n"
            f"☀️ 白班：{day_count}人\n\n"
            f"👇 点击下面功能\n\n"
            f"📋 今日考勤：admin_today\n"
            f"👥 今日在线：admin_online\n"
            f"🔴 未下班：admin_unoff\n"
            f"📅 全员月统计：admin_month\n"
            f"🏆 工时排行：admin_rank",
            reply_markup=keyboard
        )
                            
    elif text == "今日考勤/admin_today":
        if str(uid) not in ADMIN_IDS:
            await update.message.reply_text("❌ 你不是管理员。", reply_markup=keyboard)
            return
    
        today = day
        today_data = {}
        
        for d, day_data in data.items():
            for user_id, user_data in day_data.items():
                if user_data.get("off"):
                    off_dt = datetime.fromisoformat(user_data["off"])
                    if off_dt.strftime("%Y-%m-%d") == today:
                        today_data[user_id] = user_data
    
        if not today_data:
            await update.message.reply_text("📋 今日暂无考勤记录", reply_markup=keyboard)
            return
    
        msg = f"📋 今日考勤 {today}\n\n"
    
        for user_id, user_data in today_data.items():
            n = user_data.get("name", "用户")
    
            if user_data.get("on") and user_data.get("off"):
                on_dt = datetime.fromisoformat(user_data["on"])
                off_dt = datetime.fromisoformat(user_data["off"])
                msg += f"✅ {n}\n上班：{on_dt.strftime('%H:%M:%S')}\n下班：{off_dt.strftime('%H:%M:%S')}\n\n"
    
            elif user_data.get("on") and not user_data.get("off"):
                on_dt = datetime.fromisoformat(user_data["on"])
                msg += f"🟢 {n}\n上班：{on_dt.strftime('%H:%M:%S')}\n状态：未下班\n\n"
    
            else:
                msg += f"🔴 {n}\n状态：未打卡\n\n"
    
        await update.message.reply_text(msg, reply_markup=keyboard)

    elif text == "今日在线/admin_online":
        if str(uid) not in ADMIN_IDS:
            await update.message.reply_text("❌ 你不是管理员。", reply_markup=keyboard)
            return
    
        today = day
        today_data = data.get(today, {})
    
        online_users = []
    
        for user_id, user_data in today_data.items():
            if user_data.get("on") and not user_data.get("off"):
                on_dt = datetime.fromisoformat(user_data["on"])
                work_minutes = int((now - on_dt).total_seconds() // 60)
                online_users.append(
                    f"🟢 {user_data.get('name', '用户')}\n"
                    f"🕘 上班：{on_dt.strftime('%H:%M:%S')}\n"
                    f"⏱ 已工作：{work_minutes // 60}小时{work_minutes % 60}分钟"
                )
    
        if not online_users:
            await update.message.reply_text("👥 当前没有在线员工。", reply_markup=keyboard)
            return
    
        msg = "👥 今日在线\n\n" + "\n\n".join(online_users)

        await update.message.reply_text(msg, reply_markup=keyboard)

    elif text == "工时排行/admin_rank":
        if str(uid) not in ADMIN_IDS:
            await update.message.reply_text("❌ 你不是管理员。", reply_markup=keyboard)
            return
    
        month = now.strftime("%Y-%m")
        ranks = {}
    
        for d, day_data in data.items():
            if not d.startswith(month):
                continue
        
            for user_id, user_data in day_data.items():
                n = user_data.get("name", "用户")
    
                if n not in ranks:
                    ranks[n] = 0
    
                if user_data.get("on") and user_data.get("off"):
                    on_dt = datetime.fromisoformat(user_data["on"])
                    off_dt = datetime.fromisoformat(user_data["off"])
                    mins = int((off_dt - on_dt).total_seconds() // 60)
    
                    away = (
                        user_data.get("meal", 0)
                        + user_data.get("toilet", 0)
                        + user_data.get("smoke", 0)
                        + user_data.get("other", 0)
                    )
    
                    ranks[n] += max(mins - away, 0)
    
        if not ranks:
            await update.message.reply_text("🏆 本月暂无排行数据。", reply_markup=keyboard)
            return
    
        sorted_ranks = sorted(ranks.items(), key=lambda x: x[1], reverse=True)
    
        msg = f"🏆 工时排行 {month}\n\n"
    
        medals = ["🥇", "🥈", "🥉"]
    
        for i, (n, mins) in enumerate(sorted_ranks, start=1):
            icon = medals[i - 1] if i <= 3 else f"{i}."
            msg += f"{icon} {n}：{mins // 60}小时{mins % 60}分钟\n"
    
        await update.message.reply_text(msg, reply_markup=keyboard)
    
    elif text == "未下班/admin_unoff":
        if str(uid) not in ADMIN_IDS:
            await update.message.reply_text("❌ 你不是管理员。", reply_markup=keyboard)
            return
    
        today_data = data.get(day, {})
        unoff_users = []
    
        for user_id, user_data in today_data.items():
            if user_data.get("on") and not user_data.get("off"):
                on_dt = datetime.fromisoformat(user_data["on"])
                work_minutes = int((now - on_dt).total_seconds() // 60)
    
                unoff_users.append(
                    f"🔴 {user_data.get('name', '用户')}\n"
                    f"🕘 上班：{on_dt.strftime('%H:%M:%S')}\n"
                    f"⏱ 已工作：{work_minutes // 60}小时{work_minutes % 60}分钟"
                )
    
        if not unoff_users:
            await update.message.reply_text("✅ 目前没有未下班员工。", reply_markup=keyboard)
            return
    
        msg = "🔴 未下班员工\n\n" + "\n\n".join(unoff_users)
    
        await update.message.reply_text(msg, reply_markup=keyboard)

    elif text == "全员月统计/admin_month":
        if str(uid) not in ADMIN_IDS:
            await update.message.reply_text("❌ 你不是管理员。", reply_markup=keyboard)
            return
    
        month = now.strftime("%Y-%m")
        users_result = {}
    
        for d, day_data in data.items():
            if not d.startswith(month):
                continue
    
            for user_id, user_data in day_data.items():
                n = user_data.get("name", "用户")
    
                if n not in users_result:
                    users_result[n] = {
                        "days": 0,
                        "work": 0,
                        "meal": 0,
                        "toilet": 0,
                        "smoke": 0,
                        "other": 0,
                        "back": 0
                    }
    
                if user_data.get("on"):
                    users_result[n]["days"] += 1
    
                if user_data.get("on") and user_data.get("off"):
                    on_dt = datetime.fromisoformat(user_data["on"])
                    off_dt = datetime.fromisoformat(user_data["off"])
                    mins = int((off_dt - on_dt).total_seconds() // 60)
                    users_result[n]["work"] += mins
    
                users_result[n]["meal"] += user_data.get("meal", 0)
                users_result[n]["toilet"] += user_data.get("toilet", 0)
                users_result[n]["smoke"] += user_data.get("smoke", 0)
                users_result[n]["other"] += user_data.get("other", 0)
                users_result[n]["back"] += user_data.get("back", 0)
    
        if not users_result:
            await update.message.reply_text("📅 本月暂无全员统计数据。", reply_markup=keyboard)
            return
    
        msg = f"📅 全员月统计 {month}\n\n"
    
        for n, s in users_result.items():
            work = s["work"]
            away = s["meal"] + s["toilet"] + s["smoke"] + s["other"]
            real_work = max(work - away, 0)
    
            msg += (
                f"👤 {n}\n"
                f"📅 出勤：{s['days']}天\n"
                f"⏰ 总工时：{work // 60}小时{work % 60}分钟\n"
                f"✅ 实际工时：{real_work // 60}小时{real_work % 60}分钟\n"
                f"🍚 吃饭：{s['meal']}分钟\n"
                f"🚽 厕所：{s['toilet']}分钟\n"
                f"🚬 抽烟：{s['smoke']}分钟\n"
                f"📌 其他：{s['other']}分钟\n"
                f"🔄 回坐：{s['back']}次\n\n"
            )
    
        await update.message.reply_text(msg, reply_markup=keyboard)

app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("id", get_id))

app.add_handler(
    MessageHandler(
        filters.Regex(
            r"^(上班/on|下班/off|吃饭/meal|上厕所/wc|抽烟/smoke|其他|回坐/back|统计/report|月统计/month|管理员后台/admin|今日考勤/admin_today|今日在线/admin_online|未下班/admin_unoff|工时排行/admin_rank|全员月统计/admin_month)$"
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
