
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

BOT_TOKEN = "8537414013:AAEvUu8kKiJXyWAU0JA2WExA9RLY-lZWxlY"
CHAT_ID = 8290471340
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
ET = pytz.timezone("America/New_York")
STATE_FILE = "/app/state.json"

BRIDGE_URL = os.environ.get("METIS_BRIDGE_URL", "")
BRIDGE_TOKEN = os.environ.get("METIS_BRIDGE_TOKEN", "")

# ── STATE ──
def load_state():
    if os.path.exists(STATE_FILE):
    except Exception as e:
        return f"연결 오류: {str(e)[:50]}"

# ── METIS BRIDGE (Netlify) ──
async def bridge_push_task(text, tag="기타"):
    if not BRIDGE_URL or not BRIDGE_TOKEN:
        return False, "bridge not configured"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BRIDGE_URL}?action=push_task",
                headers={"X-Bridge-Token": BRIDGE_TOKEN, "Content-Type": "application/json"},
                json={"text": text, "tag": tag},
            )
            return resp.status_code == 200, resp.text[:120]
    except Exception as e:
        return False, str(e)[:120]

async def bridge_pull_events():
    if not BRIDGE_URL or not BRIDGE_TOKEN:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BRIDGE_URL}?action=bot_pull",
                headers={"X-Bridge-Token": BRIDGE_TOKEN},
            )
            if resp.status_code == 200:
                return resp.json().get("events", [])
    except Exception:
        pass
    return []

# ── TODO HELPERS ──
STATUS_CYCLE = ["🔴", "🟠", "🟡", "✅"]
STATUS_LABEL = {"🔴": "긴급", "🟠": "진행중", "🟡": "대기", "✅": "완료"}
    "self": ["30분 산책 (폰 없이)", "걱정 3가지 쓰고 오늘은 패스 선언", "좋아하는 사람 안부 문자"]
}

NAG_MSGS = [
    "수진, 오늘 아침 체크 아직 안 했어. 지금 1분만.",
    "야. 아직도 안 했잖아.\n유튜브 보고 있는 거 아니지?\n지금 당장 1가지 정해.",
    "어제도 안 했고 오늘도 이러면\n그러니까 미국 사업이 막막한 거야.\n생각하는 대로 살려면 지금 시작해."
]

# ── HANDLERS ──
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "수진의 아침 코치 봇 ✅\n\n"
        "매일 06:30 ET 알림 시작.\n\n"
        "/morning — 아침 체크\n"
        "/todos — 투두 관리\n"
        "/add — 투두 추가\n"
        "/memo — 대시보드 푸시 (또는 '메모: ...')\n"
        "/done — 오늘 완료 체크\n"
        "/streak — 스트릭 확인\n\n"
        "스케줄(ET): 06:30 모닝체크 · 08:00 브리핑 · 12:00 요가 · 21:00 저녁 · 22:00 미완료\n\n"
        "그냥 말 걸어도 돼."
    )

    await ctx.bot.send_message(CHAT_ID, f"오늘 임무: *{task}*\n\n어떻게 됐어?",
                                parse_mode="Markdown", reply_markup=done_keyboard())

async def _process_memo(update, text):
    text = text.strip()
    if not text:
        await update.message.reply_text("메모 내용이 비어있어.")
        return
    tag = "기타"
    if "#" in text:
        parts = text.rsplit("#", 1)
        text = parts[0].strip()
        tag_raw = parts[1].strip()
        tag_map = {"호니아": "호니아", "honia": "호니아", "술펀": "술펀", "sulfun": "술펀",
                   "운명책": "운명책", "book": "운명책", "기타": "기타"}
        tag = tag_map.get(tag_raw.lower(), tag_raw)
    ok, info = await bridge_push_task(text, tag)
    if ok:
        await update.message.reply_text(f"📝 대시보드에 푸시됨\n• {text} ({tag})")
    else:
        await update.message.reply_text(f"⚠️ 푸시 실패: {info}")

async def cmd_memo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "형식: `/memo IR 덱 마무리 #호니아`\n또는 `메모: IR 덱 마무리 #호니아`",
            parse_mode="Markdown"
        )
        return
    await _process_memo(update, " ".join(ctx.args))

async def cmd_streak(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    await update.message.reply_text(
    state = load_state()
    waiting = state.get("waiting_for")

    # 메모: 프리픽스 → 대시보드 푸시
    lower = text.lower()
    for prefix in ("메모:", "메모 :", "memo:", "memo :"):
        if lower.startswith(prefix):
            await _process_memo(update, text[len(prefix):])
            return

    # 투두 추가 대기 중
    if waiting == "add_text":
        tag = "기타"
    save_state(state)
    await app.bot.send_message(CHAT_ID, "수진, 좋은 아침.\n\n지금 상태는?", reply_markup=morning_keyboard())

async def nag_job(app):
async def morning_brief_job(app):
    state = load_state()
    todos = state.get("todos", [])
    active = [t for t in todos if t["status"] != "✅"]
    today_task = state.get("today_task") or "아직 미정 — /morning 으로 정해"
    lines = ["☀️ *아침 브리핑*", "", f"오늘 임무: *{today_task}*", f"활성 투두: {len(active)}개"]
    for t in active[:6]:
        lines.append(f"  {t['status']} {t['text']} ({t['tag']})")
    await app.bot.send_message(CHAT_ID, "\n".join(lines), parse_mode="Markdown")

async def yoga_reminder_job(app):
    await app.bot.send_message(CHAT_ID, "🧘 요가 시간이야. 30분만 매트 위에.")

async def midnight_check_job(app):
    state = load_state()
    if state.get("today_checked"):
        return
    nag_count = state.get("nag_count", 0) + 1
    state["nag_count"] = nag_count
    save_state(state)
    if nag_count <= 3:
        msg = NAG_MSGS[min(nag_count - 1, 2)]
        kb = InlineKeyboardMarkup([[
