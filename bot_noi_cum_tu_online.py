# --- TOKEN (đang hardcode để bạn test; nhớ đổi sau) ---
BOT_TOKEN = "8412177639:AAHvzw4Ny8LlBE2P9gl3vZ-o6Jbv9TtU6DQ"

import re, unicodedata
from datetime import datetime, timedelta
from collections import defaultdict
from urllib.parse import quote

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

# ===== Cấu hình =====
TURN_TIMEOUT_SECONDS = 25
IGNORE_DIACRITICS = True
MAP_D_TO_D = True
HTTP2 = False              # dùng HTTP/1.1 cho gọn trên Railway

# ===== Tiện ích tiếng Việt =====
def strip(s: str) -> str:
    s = s.replace("Đ", "D").replace("đ", "d") if MAP_D_TO_D else s
    nf = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in nf if unicodedata.category(ch) != "Mn")

def norm_token(t: str) -> str:
    t = re.sub(r"[^\w\u00C0-\u024F\u1E00-\u1EFF]", "", t.lower())
    return strip(t) if IGNORE_DIACRITICS else t

def toks(s: str):
    # tách từ để lấy từ đầu/cuối cho luật nối
    return re.findall(r"[0-9A-Za-z_\u00C0-\u024F\u1E00-\u1EFF]+", s)

# ===== KIỂM TRA CỤM TỪ (không kiểm từng từ) =====
async def wiki_phrase_vi_exists(c: httpx.AsyncClient, phrase: str) -> bool:
    # Phải tồn tại trang và có mục "Tiếng Việt"
    r = await c.get(f"https://vi.wiktionary.org/wiki/{quote(phrase)}",
                    follow_redirects=True, timeout=8)
    if r.status_code != 200:
        return False
    tl = r.text.lower()
    return ("mw-content-text" in tl) and (
        "tiếng việt" in tl or "#tiếng_việt" in tl or 'id="tiếng_việt"' in tl
    )

async def wikipedia_phrase_exists(c: httpx.AsyncClient, phrase: str) -> bool:
    # Nhiều cụm danh từ phổ biến có trên Wikipedia (vd: "bàn phím")
    r = await c.get(f"https://vi.wikipedia.org/api/rest_v1/page/summary/{quote(phrase)}",
                    follow_redirects=True, timeout=8)
    return r.status_code == 200

async def phrase_has_meaning(phrase: str) -> bool:
    # Thử cụm gốc, rồi bản không dấu
    async with httpx.AsyncClient(http2=HTTP2) as c:
        for p in (phrase, strip(phrase)):
            try:
                if await wiki_phrase_vi_exists(c, p): return True
                if await wikipedia_phrase_exists(c, p): return True
            except Exception:
                # nghiêm ngặt: lỗi mạng -> coi là không hợp lệ (đỡ lọt rác)
                return False
    return False

async def valid(phrase: str):
    phrase_clean = " ".join(toks(phrase)).strip()
    if not phrase_clean:
        return False, "Cụm không hợp lệ."
    ok = await phrase_has_meaning(phrase_clean)
    if not ok:
        return False, f"❌ Cụm “{phrase_clean}” không có nghĩa trong từ điển/bách khoa tiếng Việt."
    return True, ""

# ===== Trạng thái game =====
class Game:
    def __init__(self):
        self.on = False
        self.need_norm = ""   # chữ nối (bỏ dấu) để so khớp
        self.need_disp = ""   # chữ nối hiển thị (giữ dấu)
        self.used = set()
        self.score = defaultdict(int)
        self.deadline = None

games = {}
def g(cid):
    if cid not in games:
        games[cid] = Game()
    return games[cid]

# ===== Handlers =====
async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "🎮 /startgame [cụm] để bắt đầu\n"
        "/score để xem điểm\n"
        "/stopgame để kết thúc"
    )

async def cmd_startgame(u: Update, c: ContextTypes.DEFAULT_TYPE):
    chat = u.effective_chat.id
    gm = g(chat)
    if gm.on:
        return await u.message.reply_text("⚠️ Game đang diễn ra! Gõ /stopgame để kết thúc trước.")
    gm.__init__(); gm.on = True

    text = " ".join(c.args) if c.args else ""
    if text:
        ok, err = await valid(text)
        if not ok:
            gm.on = False
            return await u.message.reply_text(err)
        gm.used.add(text.lower())
        last = toks(text)[-1]
        gm.need_disp = last
        gm.need_norm = norm_token(last)
        gm.deadline = datetime.utcnow() + timedelta(seconds=TURN_TIMEOUT_SECONDS)
        await u.message.reply_text(
            f"✅ Bắt đầu: {text}\n➡️ Nối từ bắt đầu bằng **{gm.need_disp.upper()}**",
            parse_mode="Markdown"
        )
    else:
        await u.message.reply_text("Gửi cụm đầu tiên!")

async def cmd_stopgame(u: Update, c: ContextTypes.DEFAULT_TYPE):
    g(u.effective_chat.id).__init__()
    await u.message.reply_text("🛑 Kết thúc ván!")

async def cmd_score(u: Update, c: ContextTypes.DEFAULT_TYPE):
    gm = g(u.effective_chat.id)
    if not gm.score:
        return await u.message.reply_text("Chưa ai có điểm.")
    s = "🏆 Điểm:\n" + "\n".join([f"{uid}: {p}" for uid, p in gm.score.items()])
    await u.message.reply_text(s)

async def on_text(u: Update, c: ContextTypes.DEFAULT_TYPE):
    gm = g(u.effective_chat.id)
    if not gm.on:
        return
    text = u.message.text

    # kiểm tra NGHĨA của CỤM
    ok, err = await valid(text)
    if not ok:
        return await u.message.reply_text(err)

    # kiểm tra luật nối theo từ đầu / cuối
    ts = toks(text)
    first = norm_token(ts[0])
    if gm.need_norm and first != gm.need_norm:
        return await u.message.reply_text(
            f"❌ Cụm phải bắt đầu bằng **{gm.need_disp.upper()}**",
            parse_mode="Markdown"
        )

    uid = u.message.from_user.id
    gm.score[uid] += 1
    gm.used.add(text.lower())
    gm.need_disp = ts[-1]
    gm.need_norm = norm_token(ts[-1])
    gm.deadline = datetime.utcnow() + timedelta(seconds=TURN_TIMEOUT_SECONDS)

    await u.message.reply_text(
        f"✅ +1\n➡️ Tiếp theo: **{gm.need_disp.upper()}**",
        parse_mode="Markdown"
    )

def main():
    app = Application.builder().token(BOT_TOKEN).request(HTTPXRequest()).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("startgame", cmd_startgame))
    app.add_handler(CommandHandler("stopgame", cmd_stopgame))
    app.add_handler(CommandHandler("score", cmd_score))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("✅ BOT ĐANG CHẠY…")
    app.run_polling()

if __name__ == "__main__":
    main()
