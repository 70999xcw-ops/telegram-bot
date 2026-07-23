import os, sys, csv, shutil, sqlite3, asyncio, logging
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup
from telegram.error import BadRequest, Forbidden
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

VERSION = "Shift Reset DailyReport NoEarly 1.3"

TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.strip().isdigit()]
TZ = ZoneInfo(os.getenv("TZ", "Asia/Shanghai"))
DB = os.getenv("DB_PATH", "attendance.db")

ACTIONS = ["吃饭", "上厕所", "抽烟", "其他"]
LIMITS = {"吃饭": 30 * 60, "上厕所": 15 * 60, "抽烟": 15 * 60, "其他": 20 * 60}
EMOJI = {"上班": "🟢", "下班": "🔴", "吃饭": "🍚", "上厕所": "🚻", "抽烟": "🚬", "其他": "📌", "回坐": "💺"}

MENU = ReplyKeyboardMarkup([
    ["🟢 上班 / Start Work", "🔴 下班 / End Work"],
    ["🍚 吃饭 / Meal", "🚻 上厕所 / Toilet"],
    ["🚬 抽烟 / Smoke", "💺 回坐 / Back"],
    ["📌 其他 / Other", "📊 今日记录 / Today"],
    ["👑 管理员 / Admin", "📈 月统计 / Month"],
], resize_keyboard=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bot")


# ---------- time ----------
def now_ts():
    return int(datetime.now(timezone.utc).astimezone(TZ).timestamp())

def ev_ts(update):
    msg = update.effective_message
    return int(msg.date.astimezone(TZ).timestamp()) if msg and msg.date else now_ts()

def dt(x):
    return datetime.fromtimestamp(int(x), TZ)

def dstr(x):
    return dt(x).strftime("%Y-%m-%d")

def tstr(x):
    return dt(x).strftime("%H:%M:%S")

def fstr(x):
    return dt(x).strftime("%Y-%m-%d %H:%M:%S")

def mstr():
    return datetime.now(timezone.utc).astimezone(TZ).strftime("%Y-%m")

def hms(x):
    x = max(0, int(x or 0))
    return f"{x//3600:02d}:{(x%3600)//60:02d}:{x%60:02d}"


# ---------- helpers ----------
def uname(u):
    return f"{u.full_name} (@{u.username})" if getattr(u, "username", None) else u.full_name

def lab(a):
    return f"{EMOJI.get(a, '📌')} {a}"

def admin(uid):
    return True if not ADMIN_IDS else uid in ADMIN_IDS

def con():
    return sqlite3.connect(DB)


# ---------- database ----------
def init_db():
    with con() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            username TEXT,
            first_seen TEXT,
            last_seen TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS works(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            username TEXT,
            start_ts INTEGER,
            end_ts INTEGER,
            break_seconds INTEGER DEFAULT 0,
            online_seconds INTEGER DEFAULT 0,
            real_seconds INTEGER DEFAULT 0,
            date TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS states(
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            username TEXT,
            status TEXT,
            start_ts INTEGER,
            chat_id INTEGER,
            date TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS records(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            username TEXT,
            action TEXT,
            start_ts INTEGER,
            end_ts INTEGER,
            duration INTEGER DEFAULT 0,
            date TEXT
        )""")
        c.commit()

def save_user(u, ts):
    with con() as c:
        c.execute("INSERT OR IGNORE INTO users VALUES(?,?,?,?,?)", (u.id, u.full_name, u.username or "", fstr(ts), fstr(ts)))
        c.execute("UPDATE users SET name=?, username=?, last_seen=? WHERE user_id=?", (u.full_name, u.username or "", fstr(ts), u.id))
        c.commit()

def record(u, action, start, end=None, duration=0):
    end = start if end is None else end
    with con() as c:
        c.execute("""INSERT INTO records(user_id,name,username,action,start_ts,end_ts,duration,date)
                     VALUES(?,?,?,?,?,?,?,?)""",
                  (u.id, u.full_name, u.username or "", action, int(start), int(end), int(duration or 0), dstr(start)))
        c.commit()

def get_state(uid):
    with con() as c:
        return c.execute("SELECT status,start_ts,chat_id,date FROM states WHERE user_id=?", (uid,)).fetchone()

def set_state(u, action, chat_id, ts):
    with con() as c:
        c.execute("INSERT OR REPLACE INTO states VALUES(?,?,?,?,?,?,?)",
                  (u.id, u.full_name, u.username or "", action, int(ts), chat_id, dstr(ts)))
        c.commit()

def clear_state(uid):
    with con() as c:
        c.execute("DELETE FROM states WHERE user_id=?", (uid,))
        c.commit()

def open_work(uid):
    with con() as c:
        return c.execute("SELECT id,start_ts,break_seconds FROM works WHERE user_id=? AND end_ts IS NULL ORDER BY id DESC LIMIT 1", (uid,)).fetchone()

def start_work(u, ts):
    with con() as c:
        c.execute("INSERT INTO works(user_id,name,username,start_ts,date) VALUES(?,?,?,?,?)",
                  (u.id, u.full_name, u.username or "", int(ts), dstr(ts)))
        c.commit()

def end_work(uid, ts):
    row = open_work(uid)
    if not row:
        return None
    wid, start, br = row
    br = int(br or 0)
    online = max(0, int(ts) - int(start))
    real = max(0, online - br)
    with con() as c:
        c.execute("UPDATE works SET end_ts=?, online_seconds=?, real_seconds=? WHERE id=?",
                  (int(ts), online, real, wid))
        c.commit()
    return int(start), int(ts), br, online, real

def add_break(uid, sec):
    row = open_work(uid)
    if not row:
        return False
    wid, _, old = row
    with con() as c:
        c.execute("UPDATE works SET break_seconds=? WHERE id=?", (int(old or 0) + int(sec or 0), wid))
        c.commit()
    return True


# ---------- calculations ----------
def shift_stats(uid, start_ts, end_ts):
    """
    Tính theo MỘT CA duy nhất.
    Không lấy dữ liệu ca trước.
    Mỗi lần 上班 -> 下班 là một ca độc lập.
    """
    totals = {a: 0 for a in ACTIONS}
    counts = {a: 0 for a in ACTIONS}

    with con() as c:
        rows = c.execute("""
            SELECT action,duration FROM records
            WHERE user_id=?
              AND action LIKE '回坐-结束%'
              AND start_ts>=?
              AND end_ts<=?
            ORDER BY id
        """, (uid, int(start_ts), int(end_ts))).fetchall()

    for action, dur in rows:
        for a in ACTIONS:
            if a in action:
                counts[a] += 1
                totals[a] += int(dur or 0)
    return totals, counts

def current_shift(uid):
    row = open_work(uid)
    if not row:
        return None
    _, start, br = row
    end = now_ts()
    online = max(0, end - int(start))
    real = max(0, online - int(br or 0))
    totals, counts = shift_stats(uid, int(start), end)
    return int(start), end, int(br or 0), online, real, totals, counts

def state_text(uid):
    s = get_state(uid)
    return "无" if not s else f"{lab(s[0])} {hms(now_ts() - int(s[1]))}"

def activity_lines(counts, totals):
    return (
        f"🍚 {counts['吃饭']}次 {hms(totals['吃饭'])}\n"
        f"🚻 {counts['上厕所']}次 {hms(totals['上厕所'])}\n"
        f"🚬 {counts['抽烟']}次 {hms(totals['抽烟'])}\n"
        f"📌 {counts['其他']}次 {hms(totals['其他'])}"
    )

def off_message(u, start, end, br, online, real):
    totals, counts = shift_stats(u.id, start, end)
    return (
        f"🔴 下班成功\n\n"
        f"👤 {uname(u)}\n\n"
        f"🟢 上班 {tstr(start)}\n"
        f"🔴 下班 {tstr(end)}\n\n"
        f"⏰ 在线时长：{hms(online)}\n"
        f"💼 实际工作：{hms(real)}\n\n"
        f"{activity_lines(counts, totals)}"
    )

def today_message(u, ts):
    cur = current_shift(u.id)
    if cur:
        start, end, br, online, real, totals, counts = cur
        return (
            f"📊 当前班次\n"
            f"👤 {uname(u)}\n\n"
            f"🟢 上班 {tstr(start)}\n"
            f"🔴 下班 --\n\n"
            f"⏰ 在线时长：{hms(online)}\n"
            f"💼 实际工作：{hms(real)}\n\n"
            f"{activity_lines(counts, totals)}\n"
            f"状态：{state_text(u.id)}"
        )

    # Nếu không đang上班, chỉ hiển thị ca gần nhất hôm nay, không cộng dồn nhiều ca.
    with con() as c:
        row = c.execute("""
            SELECT start_ts,end_ts,break_seconds,online_seconds,real_seconds
            FROM works WHERE user_id=? AND date=?
            ORDER BY id DESC LIMIT 1
        """, (u.id, dstr(ts))).fetchone()

    if not row:
        return f"📊 当前班次\n👤 {uname(u)}\n\n暂无上班记录\n状态：{state_text(u.id)}"

    start, end, br, online, real = row
    totals, counts = shift_stats(u.id, start, end or ts)
    return (
        f"📊 最近班次\n"
        f"👤 {uname(u)}\n\n"
        f"🟢 上班 {tstr(start)}\n"
        f"🔴 下班 {tstr(end) if end else '--'}\n\n"
        f"⏰ 在线时长：{hms(online)}\n"
        f"💼 实际工作：{hms(real)}\n\n"
        f"{activity_lines(counts, totals)}\n"
        f"状态：{state_text(u.id)}"
    )


# ---------- notifications ----------
async def notify_admins(context, text):
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, text)
        except Exception:
            pass

async def warn(context, u, action, start, chat_id):
    limit = LIMITS.get(action)
    if not limit:
        return

    # Không báo trước. Đến đúng giới hạn mới gửi 超时提醒 3 lần.
    await asyncio.sleep(limit)

    for i in range(1, 4):
        s = get_state(u.id)
        if not s or s[0] != action or int(s[1]) != int(start):
            return

        text = (
            f"🚨 超时提醒\n"
            f"👤 {uname(u)}\n"
            f"状态：{lab(action)}\n"
            f"已离开：{hms(now_ts() - int(start))}\n"
            f"请尽快回坐\n"
            f"第 {i}/3 次"
        )

        try:
            await context.bot.send_message(chat_id, text)
        except Exception:
            pass

        await notify_admins(context, f"🚨 员工超时\n{text}")
        await asyncio.sleep(2)


# ---------- daily report ----------
def all_users_today_report(report_day, current_ts):
    with con() as c:
        rows = c.execute("""
            SELECT DISTINCT user_id,name,username FROM works
            WHERE date=? OR end_ts IS NULL
            ORDER BY name
        """, (report_day,)).fetchall()

    if not rows:
        return f"📊 每日考勤统计 {report_day}\n\n今天暂无考勤记录。"

    parts = []
    for uid, n, usern in rows:
        cur = current_shift(uid)
        if cur:
            st, en, br, online, real, totals, counts = cur
            off = "--"
        else:
            with con() as c:
                row = c.execute("""
                    SELECT start_ts,end_ts,break_seconds,online_seconds,real_seconds
                    FROM works
                    WHERE user_id=? AND date=?
                    ORDER BY id DESC LIMIT 1
                """, (uid, report_day)).fetchone()
            if not row:
                continue
            st, en, br, online, real = row
            off = tstr(en) if en else "--"
            totals, counts = shift_stats(uid, st, en or current_ts)

        display = f"{n} (@{usern})" if usern else n
        parts.append(
            f"👤 {display}\n"
            f"🟢 上班 {tstr(st)}\n"
            f"🔴 下班 {off}\n"
            f"⏰ 在线时长：{hms(online)}\n"
            f"💼 实际工作：{hms(real)}\n"
            f"{activity_lines(counts, totals)}"
        )

    return (f"📊 每日考勤统计 {report_day}\n\n" + "\n\n".join(parts))[:4000]


async def daily_report_job(context):
    t = now_ts()
    report_day = dstr(t)
    msg = all_users_today_report(report_day, t)

    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, msg)
        except Exception:
            pass



# ---------- commands ----------
HELP = f"""🤖 Attendance Bot {VERSION}
🕒 北京时间

核心规则：\n🍚 吃饭30分钟，🚻 上厕所15分钟，🚬 抽烟15分钟，📌 其他20分钟\n到点后超时提醒3次，每天23:55自动发送 每日考勤统计
🚻 上厕所 / Toilet：15分钟提醒
每次 上班 → 下班 是一个独立班次。
下次上班时，吃饭/厕所/抽烟/其他全部重新计算，不继承上一班。

⏰ 在线时长 = 下班 - 上班
💼 实际工作 = 在线 - 休息

按钮：
🟢 上班 / Start Work
🔴 下班 / End Work
🍚 吃饭 / Meal
🚻 上厕所 / Toilet
🚬 抽烟 / Smoke
📌 其他 / Other
💺 回坐 / Back
📊 今日记录 / Today

管理员：
/online /top /users /export /backup /restart /del /clean
"""

async def start_cmd(update, context):
    u, t = update.effective_user, ev_ts(update)
    save_user(u, t)
    await update.message.reply_text("欢迎使用考勤机器人\n🕒 北京时间\n请选择操作：", reply_markup=MENU)

async def help_cmd(update, context):
    await update.message.reply_text(HELP, reply_markup=MENU)

async def myid_cmd(update, context):
    await update.message.reply_text(f"你的 Telegram ID：\n{update.effective_user.id}", reply_markup=MENU)

async def ping_cmd(update, context):
    await update.message.reply_text(f"🟢 Online\n{VERSION}\n北京时间：{fstr(ev_ts(update))}", reply_markup=MENU)

async def status_cmd(update, context):
    u, t = update.effective_user, ev_ts(update)
    await update.message.reply_text(today_message(u, t), reply_markup=MENU)

async def restart_cmd(update, context):
    if not admin(update.effective_user.id):
        await update.message.reply_text("⛔ 只有管理员可以重启。", reply_markup=MENU)
        return
    await update.message.reply_text("🔄 Bot 正在重启...", reply_markup=MENU)
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)

async def del_cmd(update, context):
    if not admin(update.effective_user.id):
        await update.message.reply_text("⛔ 只有管理员可以删除。", reply_markup=MENU)
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("用法：回复要删除的消息，然后发送 /del", reply_markup=MENU)
        return
    try:
        await context.bot.delete_message(update.effective_chat.id, update.message.reply_to_message.message_id)
        await context.bot.delete_message(update.effective_chat.id, update.message.message_id)
    except (BadRequest, Forbidden) as e:
        await update.message.reply_text(f"❌ 删除失败：{e}", reply_markup=MENU)

async def clean_cmd(update, context):
    if not admin(update.effective_user.id):
        await update.message.reply_text("⛔ 只有管理员可以清理。", reply_markup=MENU)
        return
    n = int(context.args[0]) if context.args and context.args[0].isdigit() else 5
    n = max(1, min(50, n))
    cur, ok = update.message.message_id, 0
    for mid in range(cur, max(0, cur - n - 1), -1):
        try:
            await context.bot.delete_message(update.effective_chat.id, mid)
            ok += 1
        except Exception:
            pass
    msg = await context.bot.send_message(update.effective_chat.id, f"🧹 清理：{ok}/{n}")
    await asyncio.sleep(3)
    try:
        await context.bot.delete_message(update.effective_chat.id, msg.message_id)
    except Exception:
        pass

async def users_cmd(update, context):
    if not admin(update.effective_user.id):
        await update.message.reply_text("你没有管理员权限。", reply_markup=MENU)
        return
    with con() as c:
        rows = c.execute("SELECT user_id,name,username FROM users ORDER BY last_seen DESC").fetchall()
    msg = "👥 用户\n\n" + "\n".join([f"{n} (@{u or '-'}) | {uid}" for uid, n, u in rows[:80]])
    await update.message.reply_text(msg[:4000] if rows else "暂无用户。", reply_markup=MENU)

async def backup_cmd(update, context):
    if not admin(update.effective_user.id):
        await update.message.reply_text("你没有管理员权限。", reply_markup=MENU)
        return
    if not Path(DB).exists():
        await update.message.reply_text("暂无数据库。", reply_markup=MENU)
        return
    fn = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy(DB, fn)
    await update.message.reply_document(open(fn, "rb"), filename=fn, caption="💾 DB Backup")

async def export_cmd(update, context):
    if not admin(update.effective_user.id):
        await update.message.reply_text("你没有管理员权限。", reply_markup=MENU)
        return
    m = datetime.now(timezone.utc).astimezone(TZ).strftime("%Y-%m")
    fn = f"attendance_{m}.csv"
    with con() as c, open(fn, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["name", "username", "shift_start", "shift_end", "online", "real"])
        rows = c.execute("""
            SELECT name,username,start_ts,end_ts,online_seconds,real_seconds
            FROM works WHERE date LIKE ? ORDER BY start_ts
        """, (m + "%",)).fetchall()
        for n, u, st, en, online, real in rows:
            w.writerow([n, u, fstr(st), fstr(en) if en else "", hms(online), hms(real)])
    await update.message.reply_document(open(fn, "rb"), filename=fn, caption=f"📄 Export {m}")

async def online_cmd(update, context):
    if not admin(update.effective_user.id):
        await update.message.reply_text("你没有管理员权限。", reply_markup=MENU)
        return
    t = ev_ts(update)
    with con() as c:
        rows = c.execute("SELECT user_id,name,username,start_ts,break_seconds FROM works WHERE end_ts IS NULL").fetchall()
    lines = []
    for uid, n, u, st, br in rows:
        online = max(0, t - int(st))
        real = max(0, online - int(br or 0))
        lines.append(f"👤 {n} (@{u or '-'})\n⏰ {hms(online)} | 💼 {hms(real)} | 状态：{state_text(uid)}")
    await update.message.reply_text((f"🟢 在线人员 {len(lines)}\n\n" + "\n\n".join(lines))[:4000] if lines else "当前无人上班。", reply_markup=MENU)

async def top_cmd(update, context):
    if not admin(update.effective_user.id):
        await update.message.reply_text("你没有管理员权限。", reply_markup=MENU)
        return
    t, today = ev_ts(update), dstr(ev_ts(update))
    scores = {}
    with con() as c:
        rows = c.execute("SELECT name,username,start_ts,end_ts,break_seconds,real_seconds FROM works WHERE date=? OR end_ts IS NULL", (today,)).fetchall()
    for n, u, st, en, br, real_saved in rows:
        key = f"{n} (@{u})" if u else n
        sec = int(real_saved or 0) if en else max(0, t - int(st) - int(br or 0))
        scores[key] = scores.get(key, 0) + sec
    rows = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
    msg = "🏆 今日实际工作榜\n\n" + "\n\n".join([f"{i+1}. {n}\n💼 {hms(s)}" for i, (n, s) in enumerate(rows)])
    await update.message.reply_text(msg[:4000] if rows else "暂无排行。", reply_markup=MENU)


# ---------- button actions ----------
async def act_start(update, context):
    u, t = update.effective_user, ev_ts(update)
    if get_state(u.id):
        await update.message.reply_text(f"⚠️ 当前：{lab(get_state(u.id)[0])}\n请先回坐。", reply_markup=MENU)
        return
    if open_work(u.id):
        await update.message.reply_text("⚠️ 已经上班中。", reply_markup=MENU)
        return

    # New shift starts clean automatically. Old closed shift data is history only.
    start_work(u, t)
    record(u, "上班", t)
    msg = f"🟢 上班成功\n👤 {uname(u)}\n🕒 {tstr(t)}（北京时间）"
    await update.message.reply_text(msg, reply_markup=MENU)
    await notify_admins(context, "🟢 上班\n" + msg)

async def act_end(update, context):
    u, t = update.effective_user, ev_ts(update)
    if get_state(u.id):
        await update.message.reply_text(f"⚠️ 当前：{lab(get_state(u.id)[0])}\n请先回坐。", reply_markup=MENU)
        return
    ended = end_work(u.id, t)
    if not ended:
        await update.message.reply_text("⚠️ 还没有上班。", reply_markup=MENU)
        return
    record(u, "下班", t)
    msg = off_message(u, *ended)
    await update.message.reply_text(msg, reply_markup=MENU)
    await notify_admins(context, "🔴 下班\n" + msg)

async def act_break(update, context, action):
    u, t = update.effective_user, ev_ts(update)
    if get_state(u.id):
        await update.message.reply_text(f"⚠️ 当前：{lab(get_state(u.id)[0])}\n请先回坐。", reply_markup=MENU)
        return
    has_work = bool(open_work(u.id))
    set_state(u, action, update.effective_chat.id, t)
    record(u, f"开始{action}", t)
    msg = f"{lab(action)} 已开始\n👤 {uname(u)}\n🕒 {tstr(t)}（北京时间）\n{'计入休息' if has_work else '仅记录'}"
    await update.message.reply_text(msg, reply_markup=MENU)
    await notify_admins(context, "📌 状态\n" + msg)
    asyncio.create_task(warn(context, u, action, t, update.effective_chat.id))

async def act_back(update, context):
    u, t = update.effective_user, ev_ts(update)
    s = get_state(u.id)
    if not s:
        await update.message.reply_text("当前没有需要回坐的状态。", reply_markup=MENU)
        return
    action, start, _, _ = s
    duration = max(0, t - int(start))
    clear_state(u.id)
    add_break(u.id, duration)
    record(u, f"回坐-结束{action}", int(start), t, duration)

    cur = current_shift(u.id)
    if cur:
        st, en, br, online, real, totals, counts = cur
        msg = (
            f"💺 回坐成功\n"
            f"👤 {uname(u)}\n"
            f"📍 {lab(action)} | {hms(duration)}\n"
            f"⏰ 在线时长：{hms(online)}\n"
            f"💼 实际工作：{hms(real)}"
        )
    else:
        msg = f"💺 回坐成功\n👤 {uname(u)}\n📍 {lab(action)} | {hms(duration)}"

    await update.message.reply_text(msg, reply_markup=MENU)
    await notify_admins(context, "💺 回坐\n" + msg)

async def admin_today(update, context):
    if not admin(update.effective_user.id):
        await update.message.reply_text("你没有管理员权限。", reply_markup=MENU)
        return
    t, today = ev_ts(update), dstr(ev_ts(update))
    with con() as c:
        rows = c.execute("SELECT DISTINCT user_id,name,username FROM works WHERE date=? OR end_ts IS NULL", (today,)).fetchall()

    parts = []
    for uid, n, u in rows:
        cur = current_shift(uid)
        if cur:
            st, en, br, online, real, totals, counts = cur
        else:
            with con() as c:
                row = c.execute("""SELECT start_ts,end_ts,break_seconds,online_seconds,real_seconds
                                   FROM works WHERE user_id=? AND date=? ORDER BY id DESC LIMIT 1""", (uid, today)).fetchone()
            if not row:
                continue
            st, en, br, online, real = row
            totals, counts = shift_stats(uid, st, en or t)

        display = f"{n} (@{u})" if u else n
        parts.append(
            f"👤 {display}\n"
            f"🟢 上班 {tstr(st)}\n"
            f"🔴 下班 {tstr(en) if en else '--'}\n"
            f"⏰ 在线时长：{hms(online)}\n"
            f"💼 实际工作：{hms(real)}\n\n"
            f"{activity_lines(counts, totals)}"
        )

    msg = f"👑 今日统计 {today}\n\n" + "\n\n".join(parts)
    await update.message.reply_text(msg[:4000] if parts else "今天暂无员工记录。", reply_markup=MENU)

async def month_report(update, context):
    if not admin(update.effective_user.id):
        await update.message.reply_text("你没有管理员权限。", reply_markup=MENU)
        return
    m = datetime.now(timezone.utc).astimezone(TZ).strftime("%Y-%m")
    data = {}
    with con() as c:
        rows = c.execute("SELECT name,username,date,online_seconds,real_seconds FROM works WHERE date LIKE ?", (m + "%",)).fetchall()
    for n, u, d, online, real in rows:
        key = f"{n} (@{u})" if u else n
        data.setdefault(key, {"days": set(), "online": 0, "real": 0})
        data[key]["days"].add(d)
        data[key]["online"] += int(online or 0)
        data[key]["real"] += int(real or 0)

    msg = f"📈 月统计 {m}\n\n"
    for n, x in data.items():
        msg += f"👤 {n}\n天数 {len(x['days'])} | ⏰ {hms(x['online'])} | 💼 {hms(x['real'])}\n\n"
    await update.message.reply_text(msg[:4000] if data else "本月暂无统计。", reply_markup=MENU)

async def handle(update, context):
    u, t = update.effective_user, ev_ts(update)
    save_user(u, t)
    text = update.message.text

    if text in ["🟢 上班 / Start Work", "🟢 上班"]: await act_start(update, context)
    elif text in ["🔴 下班 / End Work", "🔴 下班"]: await act_end(update, context)
    elif text in ["🍚 吃饭 / Meal", "🍚 吃饭"]: await act_break(update, context, "吃饭")
    elif text in ["🚻 上厕所 / Toilet", "🚻 上厕所"]: await act_break(update, context, "上厕所")
    elif text in ["🚬 抽烟 / Smoke", "🚬 抽烟"]: await act_break(update, context, "抽烟")
    elif text in ["📌 其他 / Other", "📌 其他"]: await act_break(update, context, "其他")
    elif text in ["💺 回坐 / Back", "💺 回坐"]: await act_back(update, context)
    elif text in ["📊 今日记录 / Today", "📊 今日记录"]: await update.message.reply_text(today_message(u, t), reply_markup=MENU)
    elif text in ["👑 管理员 / Admin", "👑 管理员"]: await admin_today(update, context)
    elif text in ["📈 月统计 / Month", "📈 月统计"]: await month_report(update, context)
    else: await update.message.reply_text("请选择菜单按钮。\n/help 查看帮助。", reply_markup=MENU)

async def error_handler(update, context):
    log.exception("Update error: %s", context.error)

def main():
    if not TOKEN:
        raise RuntimeError("Missing BOT_TOKEN Railway Variable.")
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    for cmd, fn in {
        "start": start_cmd, "help": help_cmd, "myid": myid_cmd, "ping": ping_cmd,
        "status": status_cmd, "restart": restart_cmd, "del": del_cmd, "clean": clean_cmd,
        "users": users_cmd, "backup": backup_cmd, "export": export_cmd,
        "online": online_cmd, "top": top_cmd,
    }.items():
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.add_error_handler(error_handler)
    # 每天 23:55 北京时间自动发送每日考勤统计给管理员
    app.job_queue.run_daily(
        daily_report_job,
        time=datetime.strptime("23:55", "%H:%M").time().replace(tzinfo=TZ),
        name="daily_attendance_report"
    )

    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
