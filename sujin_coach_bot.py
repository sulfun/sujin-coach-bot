import asyncio
import json
import os
import re
from datetime import datetime, timedelta
import pytz
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ── CONFIG ──
BOT_TOKEN = "8537414013:AAEvUu8kKiJXyWAU0JA2WExA9RLY-lZWxlY"
CHAT_ID = 8290471340
ET = pytz.timezone("America/New_York")

# ── STATE FILE ──
STATE_FILE = "/app/state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {
        "streak": 0,
        "last_done_date": "",
        "today_checked": False,
        "today_task": "",
        "morning_sent": False,
        "nag_count": 0,
        "todos": {
            "비자": "🟠 진행중",
            "랜딩페이지": "🟠 진행중",
            "IR DECK": "🟡 대기",
            "자료 보내기": "🔴 긴급",
            "한정혜 계약서": "🟠 진행중",
            "제품 미팅": "🟡 대기"
        },
        "chat_history": []
    }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ── AI COACH ──
SYSTEM_PROMPT = """당신은 "팔라스 아테나 코치"입니다. 한국 창업자 이수진의 전략적 멘탈/라이프 코치.

이수진 정보:
- 한국 전통주 플랫폼 술펀(SULFUN) 창업자, 미국 법인 호니아(HONIA) 운영
- 현재 미국 뉴욕/뉴저지 롱스테이 중
- ENTP, 무기력과 미국 진출 불안 있음
- 혼김(막걸리 분말 제품) 미국 판매 준비 중
- 긴급 투두: 비자서류, 랜딩페이지(horn.style), IR DECK, 자료보내기(임하늘), 한정혜 계약서, 제품미팅(5/2 임하늘, 5/3 뉴저지)

코칭 원칙:
- 감정 인정 후 빠르게 전략으로 전환
- 절대 불쌍하게 대하지 말 것. 수진은 유능한 사람
- 구체적 실행 가능한 조언
- 직접적이고 팩폭 가능. 필요하면 세게
- 한국어로, 친한 선배/코치 느낌
- 짧고 임팩트 있게 (텔레그램이라 길면 안 읽음)
- 3줄 이내로 핵심만"""

async def ask_claude(user_msg: str, history: list) -> str:
    messages = history[-10:] + [{"role": "user", "content": user_msg}]
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"Content-Type": "application/json"},
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 300,
                    "system": SYSTEM_PROMPT,
                    "messages": messages
                }
            )
            data = resp.json()
            return data["content"][0]["text"]
    except Exception as e:
        return f"연결 오류. 다시 해봐. ({str(e)[:30]})"

# ── KEYBOARDS ──
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 했어", callback_data="done_yes"),
         InlineKeyboardButton("🔄 진행중", callback_data="done_wip"),
         InlineKeyboardButton("❌ 못 했어", callback_data="done_no")]
    ])

def todo_keyboard(todos):
    buttons = []
    for name, status in todos.items():
        buttons.append([InlineKeyboardButton(f"{status} {name}", callback_data=f"todo_{name}")])
    return InlineKeyboardMarkup(buttons)

# ── MESSAGES ──
NAG_MESSAGES = [
    None,  # index 0 unused
    "수진, 오늘 아침 체크 아직 안 했어. 지금 1분만 해.",
    "야. 아직도 안 했잖아.\n유튜브 보고 있는 거 아니지?\n지금 당장 오늘 1가지 정해.",
    "어제도 안 했고 오늘도 이러면\n그러니까 미국 사업이 막막한 거야.\n생각하는 대로 살려면 지금 시작해. 딱 1가지만."
]

EVENING_MSGS = [
    "수진, 오늘 어땠어?\n임무 완수했어?",
]

PILLAR_TASKS = {
    "honia": ["투자자 1명에게 이메일 or 팔로업", "horn.style 랜딩페이지 남은 20% 마무리", "IR DECK 섹션 1개 업데이트", "임하늘 미팅 자료 보내기", "혼김 샘플 납품처 1곳 리서치"],
    "sulfun": ["라운지 이번달 매출 숫자 확인", "한정혜 계약서 초안 검토", "팀 슬랙 체크 + 결정사항 1개", "거래처 관계 유지 연락 1건"],
    "book": ["운명책 원고 300자", "코칭 클라이언트 DM 1건", "브런치 글 초안 시작"],
    "self": ["30분 산책 (폰 없이)", "오늘 걱정 3가지 종이에 쓰고 '오늘은 패스' 선언", "좋아하는 사람 짧은 안부 문자"]
}

import random

# ── HANDLERS ──
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "수진의 아침 코치 봇 세팅 완료.\n\n"
        "매일 오전 6:30 ET에 내가 먼저 말 걸게.\n"
        "체크 안 하면 닥달할 거야.\n\n"
        "지금 바로 시작할래?\n/morning — 오늘 아침 체크\n/todos — 투두 현황\n/streak — 스트릭 확인"
    )

async def cmd_morning(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    await ctx.bot.send_message(
        CHAT_ID,
        "수진, 지금 이 순간 상태는?",
        reply_markup=morning_keyboard()
    )

async def cmd_todos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    todos = state["todos"]
    text = "📋 *현재 투두 현황*\n\n"
    for name, status in todos.items():
        text += f"{status} {name}\n"
    text += "\n항목 탭하면 상태 변경 가능해."
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=todo_keyboard(todos))

async def cmd_streak(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    streak = state["streak"]
    last = state["last_done_date"]
    await update.message.reply_text(
        f"🔥 현재 스트릭: *{streak}일 연속*\n마지막 완료: {last or '아직 없음'}",
        parse_mode="Markdown"
    )

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    state = load_state()

    # ── STATE 선택 ──
    if data.startswith("state_"):
        s = data.replace("state_", "")
        msgs = {
            "clear": "맑고 각성된 상태.\n지금 가장 중요한 거 먼저 쳐. 이 상태 오래 안 가.",
            "anxious": "불안은 불확실한 미래 때문이야.\n처방은 하나 — 지금 당장 작은 행동 1개.\n뭘 할지 골라봐.",
            "flat": "무기력은 방향 부족이야.\n딱 1개만 정하면 돼. 1개 완수 = 오늘 이긴 거.",
            "noise": "머릿속 시끄러운 거 지금 종이에 다 쏟아내.\n그 다음 딱 하나만 골라."
        }
        await query.edit_message_text(
            f"*{msgs[s]}*\n\n오늘 어디에 집중할 거야?",
            parse_mode="Markdown",
            reply_markup=pillar_keyboard()
        )

    # ── PILLAR 선택 ──
    elif data.startswith("pillar_"):
        p = data.replace("pillar_", "")
        tasks = PILLAR_TASKS.get(p, [])
        task = random.choice(tasks)
        state["today_task"] = task
        state["today_checked"] = False
        state["morning_sent"] = True
        state["nag_count"] = 0
        save_state(state)

        pillar_names = {"honia": "🇺🇸 호니아·미국", "sulfun": "🍶 술펀·한국", "book": "📖 운명책·코칭", "self": "🧠 나 챙기기"}
        await query.edit_message_text(
            f"*오늘의 단 1가지*\n\n{pillar_names[p]}\n\n➤ {task}\n\n이것만 해. 오늘 저녁에 확인할게.",
            parse_mode="Markdown"
        )

    # ── DONE 체크 ──
    elif data.startswith("done_"):
        result = data.replace("done_", "")
        today = datetime.now(ET).strftime("%Y-%m-%d")

        if result == "yes":
            if state["last_done_date"] != today:
                state["streak"] += 1
                state["last_done_date"] = today
            state["today_checked"] = True
            save_state(state)
            await query.edit_message_text(
                f"✅ *완료.*\n\n🔥 스트릭 {state['streak']}일 연속.\n\n오늘도 생각하는 대로 살았어.",
                parse_mode="Markdown"
            )
        elif result == "wip":
            state["today_checked"] = True
            save_state(state)
            await query.edit_message_text("🔄 진행중이구나.\n오늘 자기 전에 완료 처리 해줘.\n/done 으로 체크할 수 있어.")
        else:
            state["today_checked"] = True  # 닥달 멈춤
            save_state(state)
            ai_reply = await ask_claude(
                f"수진이 오늘 임무 '{state.get('today_task', '알 수 없음')}'를 못 했다고 했어. 팩폭으로 짧게 한마디 해줘.",
                []
            )
            await query.edit_message_text(f"❌ *못 했구나.*\n\n{ai_reply}", parse_mode="Markdown")

    # ── TODO 상태 변경 ──
    elif data.startswith("todo_"):
        name = data.replace("todo_", "")
        if name in state["todos"]:
            current = state["todos"][name]
            cycle = ["🔴 긴급", "🟠 진행중", "🟡 대기", "✅ 완료"]
            idx = cycle.index(current) if current in cycle else 0
            state["todos"][name] = cycle[(idx + 1) % len(cycle)]
            save_state(state)
            todos = state["todos"]
            text = "📋 *투두 현황 업데이트*\n\n"
            for n, s in todos.items():
                text += f"{s} {n}\n"
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=todo_keyboard(todos))

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    state = load_state()

    # 히스토리 관리
    history = state.get("chat_history", [])
    reply = await ask_claude(text, history)

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    state["chat_history"] = history[-20:]
    save_state(state)

    await update.message.reply_text(reply)

async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await ctx.bot.send_message(CHAT_ID, "오늘 임무 어떻게 됐어?", reply_markup=done_keyboard())

# ── SCHEDULED JOBS ──
async def morning_job(app):
    state = load_state()
    today = datetime.now(ET).strftime("%Y-%m-%d")
    state["morning_sent"] = False
    state["today_checked"] = False
    state["nag_count"] = 0
    save_state(state)
    await app.bot.send_message(
        CHAT_ID,
        "수진, 좋은 아침.\n\n지금 이 순간 상태는?",
        reply_markup=morning_keyboard()
    )

async def nag_job(app):
    state = load_state()
    if state.get("today_checked", False):
        return
    nag_count = state.get("nag_count", 0) + 1
    state["nag_count"] = nag_count
    save_state(state)

    if nag_count <= 3:
        msg = NAG_MESSAGES[min(nag_count, 3)]
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("지금 할게", callback_data="nag_start"),
            InlineKeyboardButton("오늘은 패스", callback_data="nag_skip")
        ]])
        await app.bot.send_message(CHAT_ID, msg, reply_markup=kb)

async def evening_job(app):
    state = load_state()
    task = state.get("today_task", "오늘의 임무")
    await app.bot.send_message(
        CHAT_ID,
        f"수진, 오늘 저녁.\n\n임무: *{task}*\n\n어떻게 됐어?",
        parse_mode="Markdown",
        reply_markup=done_keyboard()
    )

# ── NIGHTLY RESET ──
async def reset_job(app):
    state = load_state()
    today = datetime.now(ET).strftime("%Y-%m-%d")
    if state.get("last_done_date") != today and state.get("streak", 0) > 0:
        # 어제 체크 안 했으면 스트릭 리셋
        last = state.get("last_done_date", "")
        if last:
            last_date = datetime.strptime(last, "%Y-%m-%d")
            diff = (datetime.now(ET).replace(tzinfo=None) - last_date).days
            if diff >= 2:
                state["streak"] = 0
                save_state(state)

# ── MAIN ──
async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("morning", cmd_morning))
    app.add_handler(CommandHandler("todos", cmd_todos))
    app.add_handler(CommandHandler("streak", cmd_streak))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 나그 핸들러 (콜백)
    async def nag_callback(update, ctx):
        q = update.callback_query
        await q.answer()
        if q.data == "nag_start":
            await q.edit_message_text("좋아. 지금 뭐부터 할 거야?", reply_markup=pillar_keyboard())
        else:
            state = load_state()
            state["today_checked"] = True
            save_state(state)
            await q.edit_message_text("알겠어. 오늘은 패스.\n근데 내일은 해.")

    app.add_handler(CallbackQueryHandler(nag_callback, pattern="^nag_"))

    scheduler = AsyncIOScheduler(timezone=ET)
    # 아침 6:30 ET
    scheduler.add_job(morning_job, "cron", hour=6, minute=30, args=[app])
    # 닥달: 8:00, 10:00, 12:00 ET (체크 안 했을 때만)
    scheduler.add_job(nag_job, "cron", hour=8, minute=0, args=[app])
    scheduler.add_job(nag_job, "cron", hour=10, minute=0, args=[app])
    scheduler.add_job(nag_job, "cron", hour=12, minute=0, args=[app])
    # 저녁 9:00 ET
    scheduler.add_job(evening_job, "cron", hour=21, minute=0, args=[app])
    # 자정 리셋
    scheduler.add_job(reset_job, "cron", hour=0, minute=1, args=[app])

    scheduler.start()
    print("✅ 수진 코치 봇 시작됨")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
