# --- TOKEN (đang hardcode để bạn test; nhớ đổi sau) ---
BOT_TOKEN = "8412177639:AAHvzw4Ny8LlBE2P9gl3vZ-o6Jbv9TtU6DQ"

import re, unicodedata, asyncio
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
CHECK_ALL_TOKENS = False  # kiểm tra từ đầu & cuối (hợp lệ cho nối CỤM TỪ)

# ===== Tiện ích TV =====
def strip(s: str) -> str:
    s = s.replace("Đ","D").replace("đ","d") if MAP_D_TO_D else s
    nf = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in nf if unicodedata.category(ch) != "Mn")

def norm_token(t: str) -> str:
    t = re.sub(r"[^\w\u00C0-\u024F\u1E00-\u1EFF]", "", t.lower())
    return strip(t) if IGNORE_DIACRITICS else t

def toks(s: str):
    return re.findall(r"[0-9A-Za-z_\u00C0-\u024F\u1E00-\u1EFF]+", s)

# ===== Kiểm tra từ: đa nguồn (không bỏ qua "cái", "con", ...) =====
async def wiki_summary_exists(c: httpx.AsyncClient, word: str) -> bool:
    r = await c.get(f"https://vi.wiktionary.org/api/rest_v1/page/summary/{quote(word)}", timeout=6)
    return r.status_code == 200

async def wiki_html_exists(c: httpx.AsyncClient, word: str) -> bool:
    # lấy trang HTML, theo redirect; 200 và có nội dung chính là ok
    r = await c.get(f"https://vi.wiktionary.org/wiki/{quote(word)}", follow_redirects=True, timeout=6)
    if r.status_code != 200:
        return False
    # một vài kiểm heuristics đơn giản
    txt = r.text.lower()
    return ("mw-content-text" in txt) or ("ns-0" in txt) or ("wiktionary" in txt)

async def wiki_opensearch_match(c: httpx.AsyncClient, word: str) -> bool:
    r = await c.get("https://vi.wiktionary.org/w/api.php",
                    params={"action": "opensearch", "search": word, "limit": 5, "namespace": 0, "format": "json"},
                    timeout=6)
    if r.status_code != 200:
        return False
    data = r.json()
    if isinstance(data, list) and len(data) > 1:
        cands = [s.strip().lower() for s in data[1]]
        w = word.strip().lower()
        if w in cands:
            return True
        # gần đúng: hình thức không dấu khớp ứng viên
        nd = strip(w)
        return any(nd == strip(x) for x in cands)
    return False

async def wikipedia_opensearch_match(c: httpx.AsyncClient, word: str) -> bool:
    r = await c.get("https://vi.wikipedia.org/w/api.php",
                    params={"action": "opensearch", "search": word, "limit": 5, "namespace": 0, "format": "json"},
                    timeout=6)
    if r.status_code != 200:
        return False
    data = r.json()
    if isinstance(data, list) and len(data) > 1:
        cands = [s.strip().lower() for s in data[1]]
        w = word.strip().lower()
        if w in cands:
            return True
        nd = strip(w)
        return any(nd == strip(x) for x in cands)
    return False

async def check_word_strict(word: str) -> bool:
    # kiểm tra theo chuỗi fallback mạnh
    async with httpx.AsyncClient(http2=HTTP2) as c:
        try:
            if await wiki_summary_exists(c, word): return True
            if await wiki_html_exists(c, word):    return True
            if await wiki_opensearch_match(c, word): return True
            # bản không dấu
            nd = strip(word.lower())
            if nd != word.lower():
                if await wiki_summary_exists(c, nd): return True
                if await wiki_html_exists(c, nd):    return True
                if await wiki_opensearch_match(c, nd): return True
            # fallback cuối: Wikipedia có entry/từ vựng thông dụng
            if await wikipedia_opensearch_match(c, word): return True
            if nd != word.lower() and await wikipedia_opensearch_match(c, nd): return True
        except Exception:
            # nếu mạng lỗi: cho qua để không chặn cuộc chơi
            return True
    return False

async def valid(phrase: str):
    ts = toks(phrase)
    if not ts:
        return False, "Cụm không hợp lệ."
    to_check = ts if CHECK_ALL_TOKENS else [ts[0], ts[-1]]
    for w in to_check:
        ok = await check_word_strict(w)
        if not ok:
            return False, f"❌ Từ “{w}” không có trong từ điển."
    return True, ""

# ===== Game state =====
class Game:
    def __init__(self):
        self.on=False
        self.need_norm=""
        self.need_disp=""
        self.used=set()
        self.score=defaultdict(int)
        self.deadline=None

games={}
def g(cid):
    if cid not in games: games[cid]=Game()
    return games[cid]

# ===== Handlers =====
async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "🎮 /startgame [cụm] để bắt đầu\n/score để xem điểm\n/stopgame để kết thúc"
    )

async def cmd_startgame(u: Update, c: ContextTypes.DEFAULT_TYPE):
    chat=u.effective_chat.id
    gm=g(chat)
    if gm.on:
        return await u.message.reply_text("⚠️ Game đang diễn ra! Gõ /stopgame để kết thúc trước.")
    gm.__init__(); gm.on=True

    text=" ".join(c.args) if c.args else ""
    if text:
        ok,err=await valid(text)
        if not ok:
            gm.on=False
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
    gm=g(u.effective_chat.id)
    if not gm.score:
        return await u.message.reply_text("Chưa ai có điểm.")
    s="🏆 Điểm:\n"+"\n".join([f"{uid}: {p}" for uid,p in gm.score.items()])
    await u.message.reply_text(s)

async def on_text(u: Update, c: ContextTypes.DEFAULT_TYPE):
    gm=g(u.effective_chat.id)
    if not gm.on: return
    text=u.message.text

    ok,err=await valid(text)
    if not ok: return await u.message.reply_text(err)

    ts=toks(text)
    first = norm_token(ts[0])
    if gm.need_norm and first!=gm.need_norm:
        return await u.message.reply_text(
            f"❌ Cụm phải bắt đầu bằng **{gm.need_disp.upper()}**",
            parse_mode="Markdown"
        )

    uid = u.message.from_user.id
    gm.score[uid]+=1
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
    app.add_handler(CommandHandler("start",cmd_start))
    app.add_handler(CommandHandler("startgame",cmd_startgame))
    app.add_handler(CommandHandler("stopgame",cmd_stopgame))
    app.add_handler(CommandHandler("score",cmd_score))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,on_text))
    print("✅ BOT ĐANG CHẠY…")
    app.run_polling()

if __name__=="__main__":
    main()
