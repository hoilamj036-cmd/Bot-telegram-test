# --- TOKEN (bạn sẽ đổi sau khi test xong) ---
BOT_TOKEN = "8412177639:AAHvzw4Ny8LlBE2P9gl3vZ-o6Jbv9TtU6DQ"

import re, unicodedata, asyncio
from datetime import datetime, timedelta
from collections import defaultdict
import httpx
from urllib.parse import quote
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

# ===== Cấu hình =====
TURN_TIMEOUT_SECONDS = 25
IGNORE_DIACRITICS = True
MAP_D_TO_D = True
CHECK_ALL_TOKENS = False   # <<< CHỈ kiểm tra từ ĐẦU & CUỐI
HTTP2 = False              # Railway khỏi cần gói h2

# ===== Tiện ích tiếng Việt =====
def strip(s):
    s = s.replace("Đ","D").replace("đ","d") if MAP_D_TO_D else s
    nf = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in nf if unicodedata.category(ch)!="Mn")

def norm_token(t):
    t = re.sub(r"[^\w\u00C0-\u024F\u1E00-\u1EFF]", "", t.lower())
    return strip(t) if IGNORE_DIACRITICS else t

def toks(s):
    return re.findall(r"[0-9A-Za-z_\u00C0-\u024F\u1E00-\u1EFF]+", s)

# ===== Kiểm tra từ online (có fallback) =====
async def _exists_wiki(client, word: str) -> bool:
    # 1) thử summary với từ nguyên bản
    url1 = f"https://vi.wiktionary.org/api/rest_v1/page/summary/{quote(word)}"
    r1 = await client.get(url1, timeout=6)
    if r1.status_code == 200:
        return True
    # 2) thử opensearch (gần đúng)
    url2 = "https://vi.wiktionary.org/w/api.php"
    r2 = await client.get(url2, params={
        "action": "opensearch",
        "search": word,
        "limit": 3,
        "namespace": 0,
        "format": "json",
    }, timeout=6)
    if r2.status_code == 200:
        data = r2.json()
        if isinstance(data, list) and len(data) > 1:
            sugg = [s.strip().lower() for s in data[1]]
            if word.strip().lower() in sugg:
                return True
    return False

async def check_word(word: str) -> bool:
    # Thử bản có dấu, rồi bản bỏ dấu
    async with httpx.AsyncClient(http2=HTTP2) as c:
        try:
            if await _exists_wiki(c, word):
                return True
            nd = strip(word.lower())
            if nd != word.lower():
                return await _exists_wiki(c, nd)
        except Exception:
            return True  # đừng làm game dừng vì lỗi mạng -> tạm cho qua
    return False

async def valid(phrase: str):
    ts = toks(phrase)
    if not ts:
        return False, "Cụm không hợp lệ."
    to_check = ts if CHECK_ALL_TOKENS else [ts[0], ts[-1]]
    for w in to_check:
        ok = await check_word(w)
        if not ok:
            return False, f"❌ Từ “{w}” không có trên Wiktionary."
    return True, ""

# ===== Trạng thái game =====
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
        "🎮 /startgame [cụm] để bắt đầu\n"
        "/score để xem điểm\n"
        "/stopgame để kết thúc"
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
        gm.need_disp = last                 # hiển thị có dấu
        gm.need_norm = norm_token(last)     # so khớp bỏ dấu
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
