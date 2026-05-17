#!/usr/bin/env python3
"""
O'rnatish:
    pip install "python-telegram-bot[job-queue]==21.5" google-generativeai requests beautifulsoup4

Ishga tushirish:
    python bot.py
"""

# ──────────────────────────────────────────────────────
TELEGRAM_TOKEN = "8761493394:AAGM_dmgQdFx_s_WH9JajKswQ6lh0Yg4oGc"
GEMINI_KEY     = "AIzaSyDHy4Tx9VS4mWhur6ejI0Ny5WfwvJmPRJE"
KANAL          = "noutbuk_dunyosi_notebook_laptop"
# ──────────────────────────────────────────────────────

import re
import asyncio
import logging
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler,
)

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
genai.configure(api_key=GEMINI_KEY)
gemini = genai.GenerativeModel("gemini-1.5-flash")

# ══════════════════════════════════════════════════════
#  KANALDAN POST ID VA MA'LUMOT O'QISH
# ══════════════════════════════════════════════════════
def kanal_dan_ol():
    try:
        url = f"https://t.me/s/{KANAL}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        postlar = soup.find_all("div", class_="tgme_widget_message")
        noutbuklar = []

        for post in postlar:
            # Post ID ni olish (forward uchun kerak)
            post_id = None
            post_link = post.get("data-post", "")  # "kanal/123" formatda
            if post_link:
                post_id = post_link.split("/")[-1]

            matn_div = post.find("div", class_="tgme_widget_message_text")
            if not matn_div:
                continue
            matn = matn_div.get_text(separator="\n").strip()

            # ── SOTILGAN postlarni o'tkazib yuborish ──
            sotilgan_sozlar = [
                "сотилди", "sotildi", "sotilgan", "сотилган",
                "sold", "продано", "продан", "резерв", "rezerv",
                "band qilindi", "band", "бронь", "bron",
                "sotib olindi", "✅ sotildi", "❌", "sotilib bo'ldi",
            ]
            if any(s.lower() in matn.lower() for s in sotilgan_sozlar):
                continue

            # Narx bormi?
            narx_match = re.search(r'(\d{2,4})\s*\$', matn)
            if not narx_match:
                continue
            narx = int(narx_match.group(1))
            if narx < 50 or narx > 5000:
                continue

            # Brand aniqlash
            brand = "intel"
            if re.search(r'AMD|Ryzen', matn, re.IGNORECASE):
                brand = "amd"
            elif re.search(r'Apple|MacBook|M1|M2|M3', matn, re.IGNORECASE):
                brand = "macbook"

            # RAM aniqlash (filter uchun)
            ram_gb = 8
            ram_match = re.search(r'(\d+)\s*GB\s*(DDR|RAM|оператив)', matn, re.IGNORECASE)
            if not ram_match:
                ram_match = re.search(r'(DDR\d?\s*\d+\s*GB)', matn, re.IGNORECASE)
            if ram_match:
                digits = re.search(r'(\d+)', ram_match.group(0))
                if digits:
                    ram_gb = int(digits.group(1))

            noutbuklar.append({
                "post_id": post_id,      # Forward uchun
                "price":   narx,
                "brand":   brand,
                "ram_gb":  ram_gb,
                "matn":    matn[:300],   # AI tavsiya uchun
            })

        logging.info(f"Kanaldan {len(noutbuklar)} ta noutbuk topildi")
        return noutbuklar

    except Exception as e:
        logging.error(f"Kanal o'qish xato: {e}")
        return []

KATALOG = []

def katalog_yangilasin():
    global KATALOG
    yangi = kanal_dan_ol()
    if yangi:
        KATALOG = yangi
        logging.info(f"Katalog yangilandi: {len(KATALOG)} ta noutbuk")

# ══════════════════════════════════════════════════════
#  FILTER VA AI
# ══════════════════════════════════════════════════════
def filter_qil(mn, mx, brand):
    res = [n for n in KATALOG if mn <= n["price"] <= mx]
    if brand != "any":
        filtered = [n for n in res if n["brand"] == brand]
        if filtered:
            res = filtered
    return res[:3]

def ai_tavsiya(mn, mx, brand, use, picks):
    if not picks:
        return "Hozircha kanalda bu parametrlarga mos noutbuk topilmadi."
    noutbuk_txt = "\n\n".join([
        f"Narx: ${n['price']}, Brand: {n['brand']}, RAM: {n['ram_gb']}GB\n{n['matn'][:150]}"
        for n in picks
    ])
    prompt = (
        f"Sen noutbuk savdo maslahatchisin. Quyidagi noutbuklar real kanaldan olingan:\n\n"
        f"{noutbuk_txt}\n\n"
        f"Foydalanuvchi: byudjet ${mn}–${mx}, platforma {brand}, maqsad {use}\n\n"
        f"O'zbek tilida 2-3 jumlada qisqa va do'stona tavsiya yoz. Boshqa hech narsa yozma."
    )
    try:
        response = gemini.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logging.error(f"Gemini xato: {e}")
        return "Sizning tanlovingizga mos noutbuklar topildi! 🎉"

# ══════════════════════════════════════════════════════
#  BOSQICHLAR
# ══════════════════════════════════════════════════════
BUDGET, BRAND, USE, DONE = range(4)

BRAND_LABEL = {
    "intel": "🔵 Intel", "amd": "🔴 AMD",
    "macbook": "🍎 MacBook", "any": "🤷 Farqi yo'q",
}
USE_LABEL = {
    "o'qish": "📚 O'qish/Ofis", "dasturlash": "💻 Dasturlash",
    "dizayn": "🎨 Dizayn/Video", "o'yin": "🎮 O'yin",
    "ish": "🏢 Ish/Biznes", "multimedia": "🎬 Multimedia",
}

def kb_budget():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 100 – 200 $",   callback_data="b|100|200")],
        [InlineKeyboardButton("💵 200 – 350 $",   callback_data="b|200|350")],
        [InlineKeyboardButton("💵 350 – 500 $",   callback_data="b|350|500")],
        [InlineKeyboardButton("💵 500 – 800 $",   callback_data="b|500|800")],
        [InlineKeyboardButton("💵 800 – 1200 $",  callback_data="b|800|1200")],
        [InlineKeyboardButton("💵 1200 – 1500 $", callback_data="b|1200|1500")],
    ])

def kb_brand():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 Intel",      callback_data="r|intel"),
         InlineKeyboardButton("🔴 AMD",        callback_data="r|amd")],
        [InlineKeyboardButton("🍎 MacBook",     callback_data="r|macbook")],
        [InlineKeyboardButton("🤷 Farqi yo'q", callback_data="r|any")],
    ])

def kb_use():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 O'qish / Ofis",  callback_data="u|o'qish"),
         InlineKeyboardButton("💻 Dasturlash",      callback_data="u|dasturlash")],
        [InlineKeyboardButton("🎨 Dizayn / Video",  callback_data="u|dizayn"),
         InlineKeyboardButton("🎮 O'yin (Gaming)",  callback_data="u|o'yin")],
        [InlineKeyboardButton("🏢 Ish / Biznes",    callback_data="u|ish"),
         InlineKeyboardButton("🎬 Multimedia",       callback_data="u|multimedia")],
    ])

def kb_restart():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Qaytadan boshlash", callback_data="restart")]
    ])

def summary(ud):
    return (
        f"✅ Byudjet: *{ud.get('budget_label','—')}*\n"
        f"✅ Platforma: *{ud.get('brand_label','—')}*\n"
        f"✅ Maqsad: *{ud.get('use_label','—')}*"
    )

# ══════════════════════════════════════════════════════
#  HANDLERLAR
# ══════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "👋 Asalomu alaykum ! Men *Noutbuk Dunyosi* kanalidan\n"
        "real postlarni topib sizga tavsiya qilaman! 🎯\n\n"
        "*1-qadam:* Byudjetingizni tanlang 👇",
        parse_mode="Markdown",
        reply_markup=kb_budget(),
    )
    return BUDGET

async def on_budget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, mn, mx = q.data.split("|")
    mn, mx = int(mn), int(mx)
    ctx.user_data.update(budget=(mn, mx), budget_label=f"${mn}–${mx}")
    await q.edit_message_text(
        f"{summary(ctx.user_data)}\n\n*2-qadam:* Qaysi platforma? 👇",
        parse_mode="Markdown", reply_markup=kb_brand(),
    )
    return BRAND

async def on_brand(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    brand = q.data.split("|")[1]
    ctx.user_data.update(brand=brand, brand_label=BRAND_LABEL[brand])
    await q.edit_message_text(
        f"{summary(ctx.user_data)}\n\n*3-qadam:* Nima uchun ishlatisiz? 👇",
        parse_mode="Markdown", reply_markup=kb_use(),
    )
    return USE

async def on_use(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    use = q.data.split("|")[1]
    ctx.user_data.update(use=use, use_label=USE_LABEL[use])
    await q.edit_message_text(
        f"{summary(ctx.user_data)}\n\n⏳ Kanaldan qidirilmoqda...",
        parse_mode="Markdown",
    )

    mn, mx = ctx.user_data["budget"]
    brand   = ctx.user_data["brand"]
    picks   = filter_qil(mn, mx, brand)

    if not picks:
        await q.message.reply_text(
            "😔 Hozircha kanalda bu parametrlarga mos noutbuk topilmadi.\n"
            "Kanal yangilanishini kuting yoki boshqa parametr tanlang.",
            reply_markup=kb_restart(),
        )
        return DONE

    # AI tavsiya
    ai_text = ai_tavsiya(mn, mx, brand, use, picks)
    await q.message.reply_text(
        f"📋 *Sizning tanlovingiz:*\n"
        f"💰 {ctx.user_data['budget_label']}  |  "
        f"{ctx.user_data['brand_label']}  |  "
        f"{ctx.user_data['use_label']}\n\n"
        f"🤖 *AI tavsiya:*\n{ai_text}\n"
        f"{'─' * 28}\n"
        f"📢 Kanal postlari:",
        parse_mode="Markdown",
    )

    # Har bir postni FORWARD qilish
    chat_id = update.effective_chat.id
    for nb in picks:
        if nb.get("post_id"):
            try:
                await ctx.bot.forward_message(
                    chat_id=chat_id,
                    from_chat_id=f"@{KANAL}",
                    message_id=int(nb["post_id"]),
                )
            except Exception as e:
                logging.error(f"Forward xato: {e}")
                # Forward ishlamasa link yuborish
                await q.message.reply_text(
                    f"🔗 t.me/{KANAL}/{nb['post_id']}"
                )

    await q.message.reply_text(
        "Boshqa noutbuk qidirmoqchimisiz? 👇",
        reply_markup=kb_restart(),
    )
    return DONE

async def on_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data.clear()
    await q.message.reply_text(
        "🔄 Qaytadan boshlaymiz!\n\n*1-qadam:* Byudjetingizni tanlang 👇",
        parse_mode="Markdown", reply_markup=kb_budget(),
    )
    return BUDGET

async def yangilasin_job(context):
    katalog_yangilasin()

# ══════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════
async def run():
    print("📡 Kanaldan ma'lumot olinmoqda...")
    katalog_yangilasin()
    print(f"✅ {len(KATALOG)} ta noutbuk topildi!")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.job_queue.run_repeating(yangilasin_job, interval=1800, first=1800)

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            BUDGET: [CallbackQueryHandler(on_budget,  pattern=r"^b\|")],
            BRAND:  [CallbackQueryHandler(on_brand,   pattern=r"^r\|")],
            USE:    [CallbackQueryHandler(on_use,      pattern=r"^u\|")],
            DONE:   [CallbackQueryHandler(on_restart,  pattern="^restart$")],
        },
        fallbacks=[
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(on_restart, pattern="^restart$"),
        ],
    )
    app.add_handler(conv)
    print("🤖 Bot ishga tushdi! To'xtatish uchun Ctrl+C bosing.")

    async with app:
        await app.start()
        await app.updater.start_polling()
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(run())