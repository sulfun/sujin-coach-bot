import asyncio
import json
import os
import random
from datetime import datetime
import pytz
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = int(os.environ.get("CHAT_ID", "0") or 0)
ET = pytz.timezone("America/New_York")
STATE_FILE = "/app/state.json"

# ── METIS BRIDGE ──
BRIDGE_URL = os.environ.get("METIS_BRIDGE_URL", "")
BRIDGE_TOKEN = os.environ.get("METIS_BRIDGE_TOKEN", "")

WEEKDAY_THEME = {
    0: "월 — HOrN/혼 (미국)",
    1: "화 — 운명책/코칭 (서브스택 발행)",
    2: "수 — 술펀/미팅",
    3: "목 — 외부미팅 (서브스택 발행)",
    4: "금 — 혼/자유",
    5: "토 — 휴식",
    6: "일 — 밀린일+준비 (서브스택 2편 예약)",
}

# ── STATE ──
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {
        "streak": 0,
        "last_done_date": "",
        "today_checked": False,
        "today_task": "",
        "nag_count": 0,
        "todos": [
            {"id": 1, "text": "비자 나머지 20%", "status": "🟠", "tag": "호니아"},
            {"id": 2, "text": "랜딩페이지 horn.style 마무리", "status": "🟠", "tag": "호니아"},
            {"id": 3, "text": "IR DECK 업데이트", "status": "🟡", "tag": "호니아"},
            {"id": 4, "text": "임하늘 자료 보내기", "status": "🔴", "tag": "호니아"},
            {"id": 5, "text": "한정혜 계약서", "status": "🟠", "tag": "술펀"},
            {"id": 6, "text": "제품 미팅 준비", "status": "🟡", "tag": "호니아"},
        ],
        "next_id": 7,
        "chat_history": [],
        "waiting_for": None
    }

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True) if os.path.dirname(STATE_FILE) else None
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ── AI ──
SYSTEM_PROMPT = """당신은 "팔라스 아테나 코치". 한국 창업자 이수진의 전략적 멘탈/라이프 코치.

이수진: 술펀(한국 전통주 플랫폼) + 호니아(미국 법인) 창업자. 뉴욕 롱스테이 중. ENTP.
현재 미국 진출 불안, 무기력 있음. 혼김(막걸리 분말) 미국 판매 준비.
긴급 일정: 5/2 임하늘 미팅, 5/3 뉴저지 미팅.

원칙: 감정 인정 후 전략으로 전환. 불쌍하게 대하지 말 것. 직접적 팩폭 가능.
말투: 친한 선배/코치. 한국어. 3줄 이내로 핵심만."""

async def ask_claude(user_msg, history):
    messages = history[-10:] + [{"role": "user", "content": user_msg}]
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01"
                },
                json={"model": "claude-sonnet-4-20250514", "max_tokens": 300,
                      "system": SYSTEM_PROMPT, "messages": messages}
            )
            data = resp.json()
            if "content" in data:
                return data["content"][0]["text"]
            else:
                return f"API 오류: {data.get('error', {}).get('message', '알 수 없음')}"
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
            return resp.status_code == 200, resp.text[:160]
    except Exception as e:
        return False, str(e)[:160]

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
                return resp.json().get("events", []) or []
    except Exception:
        pass
    return []

# ── TODO HELPERS ──
STATUS_CYCLE = ["🔴", "🟠", "🟡", "✅"]
STATUS_LABEL = {"🔴": "긴급", "🟠": "진행중", "🟡": "대기", "✅": "완료"}

def todos_text(todos):
    if not todos:
        return "투두가 없어. /add 로 추가해봐."
    lines = []
    for t in todos:
        label = STATUS_LABEL.get(t["status"], "")
        lines.append(f"{t['status']} [{t['id']}] {t['text']} ({t['tag']}) — {label}")
    return "\n".join(lines)

def todos_keyboard(todos):
    buttons = []
    for t in todos:
        buttons.append([InlineKeyboardButton(
            f"{t['status']} {t['text'][:20]}",
            callback_data=f"td_{t['id']}"
        )])
    buttons.append([
        InlineKeyboardButton("➕ 추가", callback_data="td_add"),
        InlineKeyboardButton("🗑 삭제", callback_data="td_del_menu")
    ])
    return InlineKeyboardMarkup(buttons)

def morning_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 각성됨", callback_data="state_clear"),
         InlineKeyboardButton("😶‍🌫️ 불안·무거움", callback_data="state_anxious")],
        [InlineKeyboardButton("📺 무기력·멍함", callback_data="state_flat"),
         InlineKeyboardButton("🌀 머릿속 시끄러움", callback_data="state_noise")]
    ])

def pillar_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇸 호니아·미국", callback_data="pillar_honia")],
        [InlineKeyboardButton("🍶 술펀·한국", callback_data="pillar_sulfun")],
        [InlineKeyboardButton("📖 운명책·코칭", callback_data="pillar_book")],
        [InlineKeyboardButton("🧠 오늘은 나 챙기기", callback_data="pillar_self")]
    ])

def done_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ 했어", callback_data="done_yes"),
        InlineKeyboardButton("🔄 진행중", callback_data="done_wip"),
        InlineKeyboardButton("❌ 못 했어", callback_data="done_no")
    ]])

PILLAR_TASKS = {
    "honia": ["투자자 1명 이메일/팔로업", "horn.style 랜딩페이지 남은 부분 마무리", "IR DECK 섹션 1개 업데이트", "임하늘 미팅 자료 보내기", "혼김 납품처 1곳 리서치"],
    "sulfun": ["라운지 이번달 매출 확인", "한정혜 계약서 검토", "팀 슬랙 체크 + 결정 1개", "거래처 관계 유지 연락"],
    "book": ["운명책 원고 300자", "코칭 클라이언트 DM 1건", "브런치 글 초안 시작"],
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
        "스케줄(ET): 06:30 모닝 · 08:00 브리핑 · 12:00 요가 · 21:00 저녁 · 00:00 자정체크\n\n"
        "그냥 말 걸어도 돼."
    )

async def cmd_morning(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await ctx.bot.send_message(CHAT_ID, "수진, 지금 상태는?", reply_markup=morning_keyboard())

async def cmd_todos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    todos = state["todos"]
    active = [t for t in todos if t["status"] != "✅"]
    done = [t for t in todos if t["status"] == "✅"]
    text = f"📋 *투두 현황* ({len(active)}개 진행중, {len(done)}개 완료)\n\n"
    text += todos_text(todos)
    text += "\n\n탭하면 상태 변경 → 🔴긴급 → 🟠진행중 → 🟡대기 → ✅완료"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=todos_keyboard(todos))

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    state["waiting_for"] = "add_text"
    save_state(state)
    await update.message.reply_text(
        "추가할 투두를 입력해줘.\n\n형식: `할 일 내용 #태그`\n예: `IR 덱 executive summary 작성 #호니아`\n태그 없으면 그냥 내용만 써도 돼.",
        parse_mode="Markdown"
    )

async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    task = state.get("today_task", "오늘의 임무")
    await ctx.bot.send_message(CHAT_ID, f"오늘 임무: *{task}*\n\n어떻게 됐어?",
                                parse_mode="Markdown", reply_markup=done_keyboard())

async def cmd_streak(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    await update.message.reply_text(
        f"🔥 스트릭: *{state['streak']}일 연속*\n마지막 완료: {state['last_done_date'] or '아직 없음'}",
        parse_mode="Markdown"
    )

async def _process_memo(update, raw_text):
    text = (raw_text or "").strip()
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
    if not text:
        await update.message.reply_text("메모 내용이 비어있어.")
        return
    ok, info = await bridge_push_task(text, tag)
    if ok:
        await update.message.reply_text(f"📝 대시보드 푸시됨\n• {text} ({tag})")
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

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    state = load_state()

    # 상태 선택
    if data.startswith("state_"):
        s = data[6:]
        msgs = {
            "clear": "맑고 각성된 상태.\n지금 가장 중요한 거 먼저 쳐. 이 상태 오래 안 가.",
            "anxious": "불안은 불확실한 미래 때문이야.\n작은 행동 1개가 처방이야.",
            "flat": "무기력은 방향 부족이야.\n딱 1개만 정하면 돼.",
            "noise": "머릿속 시끄러운 거 종이에 다 쏟아내.\n그 다음 딱 하나만 골라."
        }
        await q.edit_message_text(
            f"*{msgs[s]}*\n\n오늘 어디에 집중할 거야?",
            parse_mode="Markdown", reply_markup=pillar_keyboard()
        )

    # 축 선택
    elif data.startswith("pillar_"):
        p = data[7:]
        task = random.choice(PILLAR_TASKS.get(p, ["오늘 할 일 1가지 정하기"]))
        state["today_task"] = task
        state["today_checked"] = False
        state["nag_count"] = 0
        save_state(state)
        names = {"honia": "🇺🇸 호니아·미국", "sulfun": "🍶 술펀·한국",
                 "book": "📖 운명책·코칭", "self": "🧠 나 챙기기"}
        await q.edit_message_text(
            f"*오늘의 단 1가지*\n\n{names[p]}\n\n➤ {task}\n\n이것만 해. 저녁에 확인할게.",
            parse_mode="Markdown"
        )

    # 완료 체크
    elif data.startswith("done_"):
        result = data[5:]
        today = datetime.now(ET).strftime("%Y-%m-%d")
        if result == "yes":
            if state["last_done_date"] != today:
                state["streak"] += 1
                state["last_done_date"] = today
            state["today_checked"] = True
            save_state(state)
            await q.edit_message_text(
                f"✅ *완료.*\n\n🔥 {state['streak']}일 연속.\n오늘도 생각하는 대로 살았어.",
                parse_mode="Markdown"
            )
        elif result == "wip":
            state["today_checked"] = True
            save_state(state)
            await q.edit_message_text("🔄 진행중이구나.\n자기 전에 /done 으로 완료 체크해줘.")
        else:
            state["today_checked"] = True
            save_state(state)
            reply = await ask_claude(f"수진이 오늘 임무 '{state.get('today_task','?')}'를 못 했어. 팩폭 한마디.", [])
            await q.edit_message_text(f"❌\n\n{reply}")

    # 투두 상태 변경
    elif data.startswith("td_") and data[3:].isdigit():
        tid = int(data[3:])
        for t in state["todos"]:
            if t["id"] == tid:
                idx = STATUS_CYCLE.index(t["status"]) if t["status"] in STATUS_CYCLE else 0
                t["status"] = STATUS_CYCLE[(idx + 1) % len(STATUS_CYCLE)]
                break
        save_state(state)
        todos = state["todos"]
        active = [t for t in todos if t["status"] != "✅"]
        text = f"📋 *투두 현황* ({len(active)}개 진행중)\n\n" + todos_text(todos)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=todos_keyboard(todos))

    # 투두 추가 버튼
    elif data == "td_add":
        state["waiting_for"] = "add_text"
        save_state(state)
        await q.edit_message_text(
            "추가할 투두 입력해줘.\n\n예: `IR 덱 마무리 #호니아`\n태그(#호니아 #술펀 #운명책 #기타) 붙이면 분류돼.",
            parse_mode="Markdown"
        )

    # 삭제 메뉴
    elif data == "td_del_menu":
        todos = state["todos"]
        buttons = []
        for t in todos:
            buttons.append([InlineKeyboardButton(
                f"🗑 {t['text'][:25]}", callback_data=f"td_del_{t['id']}"
            )])
        buttons.append([InlineKeyboardButton("← 취소", callback_data="td_del_cancel")])
        await q.edit_message_text("어떤 투두 삭제할 거야?", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("td_del_") and data[7:].isdigit():
        tid = int(data[7:])
        removed = next((t for t in state["todos"] if t["id"] == tid), None)
        state["todos"] = [t for t in state["todos"] if t["id"] != tid]
        save_state(state)
        todos = state["todos"]
        text = f"🗑 삭제됨: {removed['text'] if removed else '?'}\n\n📋 *남은 투두*\n\n" + todos_text(todos)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=todos_keyboard(todos))

    elif data == "td_del_cancel":
        todos = state["todos"]
        text = "📋 *투두 현황*\n\n" + todos_text(todos)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=todos_keyboard(todos))

    # 닥달 버튼
    elif data == "nag_start":
        await q.edit_message_text("좋아. 지금 뭐부터 할 거야?", reply_markup=pillar_keyboard())
    elif data == "nag_skip":
        state["today_checked"] = True
        save_state(state)
        await q.edit_message_text("알겠어. 오늘은 패스.\n근데 내일은 해.")

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    state = load_state()
    waiting = state.get("waiting_for")

    # "메모:" 프리픽스 → 대시보드 푸시
    lower = text.lower()
    for prefix in ("메모:", "메모 :", "memo:", "memo :"):
        if lower.startswith(prefix):
            await _process_memo(update, text[len(prefix):])
            return

    # 투두 추가 대기 중
    if waiting == "add_text":
        tag = "기타"
        content = text
        if "#" in text:
            parts = text.rsplit("#", 1)
            content = parts[0].strip()
            tag_raw = parts[1].strip()
            tag_map = {"호니아": "호니아", "honia": "호니아", "술펀": "술펀", "sulfun": "술펀",
                       "운명책": "운명책", "book": "운명책", "기타": "기타"}
            tag = tag_map.get(tag_raw.lower(), tag_raw)

        new_todo = {"id": state["next_id"], "text": content, "status": "🟡", "tag": tag}
        state["todos"].append(new_todo)
        state["next_id"] += 1
        state["waiting_for"] = None
        save_state(state)

        todos = state["todos"]
        await update.message.reply_text(
            f"✅ 추가됨: *{content}* ({tag})\n\n📋 *현재 투두*\n\n" + todos_text(todos),
            parse_mode="Markdown",
            reply_markup=todos_keyboard(todos)
        )
        return

    # 일반 대화 → AI 코치
    history = state.get("chat_history", [])
    reply = await ask_claude(text, history)
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    state["chat_history"] = history[-20:]
    save_state(state)
    await update.message.reply_text(reply)

# ── SCHEDULED ──
async def morning_job(app):
    state = load_state()
    state["today_checked"] = False
    state["nag_count"] = 0
    save_state(state)
    await app.bot.send_message(CHAT_ID, "수진, 좋은 아침.\n\n지금 상태는?", reply_markup=morning_keyboard())

async def nag_job(app):
    state = load_state()
    if state.get("today_checked"):
        return
    nag_count = state.get("nag_count", 0) + 1
    state["nag_count"] = nag_count
    save_state(state)
    if nag_count <= 3:
        msg = NAG_MSGS[min(nag_count - 1, 2)]
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("지금 할게", callback_data="nag_start"),
            InlineKeyboardButton("오늘은 패스", callback_data="nag_skip")
        ]])
        await app.bot.send_message(CHAT_ID, msg, reply_markup=kb)

async def evening_job(app):
    state = load_state()
    task = state.get("today_task", "오늘의 임무")
    await app.bot.send_message(
        CHAT_ID, f"수진, 저녁.\n\n임무: *{task}*\n\n어떻게 됐어?",
        parse_mode="Markdown", reply_markup=done_keyboard()
    )

async def morning_brief_job(app):
    state = load_state()
    now = datetime.now(ET)
    today_str = now.strftime("%Y-%m-%d (%a)")
    theme = WEEKDAY_THEME.get(now.weekday(), "")
    todos = state.get("todos", [])
    carried = [t for t in todos if t["status"] != "✅"]
    lines = ["☀️ *아침 브리핑*", "", f"📅 {today_str}", f"🎯 {theme}", ""]
    if carried:
        lines.append(f"이월된 미완료: {len(carried)}개")
        for t in carried[:8]:
            lines.append(f"  {t['status']} {t['text']} ({t['tag']})")
    else:
        lines.append("이월된 미완료 없음. 깔끔.")
    await app.bot.send_message(CHAT_ID, "\n".join(lines), parse_mode="Markdown")

async def yoga_reminder_job(app):
    await app.bot.send_message(CHAT_ID, "🧘 요가 시간! ET 12:00")

async def midnight_check_job(app):
    state = load_state()
    todos = state.get("todos", [])
    incomplete = [t for t in todos if t["status"] != "✅"]
    if not incomplete:
        return
    lines = ["🌙 *자정 체크* — 미완료 태스크 있어:", ""]
    for t in incomplete[:8]:
        lines.append(f"  {t['status']} {t['text']} ({t['tag']})")
    await app.bot.send_message(CHAT_ID, "\n".join(lines), parse_mode="Markdown")

async def bridge_poll_job(app):
    events = await bridge_pull_events()
    for ev in events:
        try:
            etype = ev.get("type")
            if etype == "task_saved":
                tasks = ev.get("tasks", []) or []
                t_time = ev.get("time", "")
                lines = ["📋 *대시보드 태스크 저장됨*"]
                if t_time:
                    lines.append(f"⏰ {t_time}")
                for t in tasks[:10]:
                    if isinstance(t, dict):
                        line = f"• {t.get('text','')}"
                        if t.get("tag"):
                            line += f" #{t['tag']}"
                        lines.append(line)
                    elif isinstance(t, str):
                        lines.append(f"• {t}")
                await app.bot.send_message(CHAT_ID, "\n".join(lines), parse_mode="Markdown")
            elif etype == "tg_send":
                text = ev.get("text", "")
                if text:
                    await app.bot.send_message(CHAT_ID, text)
        except Exception:
            pass

async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("morning", cmd_morning))
    app.add_handler(CommandHandler("todos", cmd_todos))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("memo", cmd_memo))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("streak", cmd_streak))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = AsyncIOScheduler(timezone=ET)
    scheduler.add_job(morning_job, "cron", hour=6, minute=30, args=[app])
    scheduler.add_job(morning_brief_job, "cron", hour=8, minute=0, args=[app])
    scheduler.add_job(yoga_reminder_job, "cron", hour=12, minute=0, args=[app])
    scheduler.add_job(evening_job, "cron", hour=21, minute=0, args=[app])
    scheduler.add_job(midnight_check_job, "cron", hour=0, minute=0, args=[app])
    scheduler.add_job(bridge_poll_job, "interval", minutes=1, args=[app])
    scheduler.start()

    print("✅ 수진 코치 봇 v3 (Metis 연동) 시작됨")
    await app.initialize()
    # 다른 인스턴스/웹훅이 getUpdates 점유 중이면 Conflict — 웹훅 제거 + pending 폐기로 독점 확보
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        print("🔒 webhook 제거 + pending updates 폐기 완료 (getUpdates 독점)")
    except Exception as e:
        print(f"⚠️ delete_webhook 실패 (계속 진행): {e}")
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
