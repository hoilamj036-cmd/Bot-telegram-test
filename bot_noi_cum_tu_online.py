BOT_TOKEN = "8412177639:AAHvzw4Ny8LlBE2P9gl3vZ-o6Jbv9TtU6DQ"

import re, unicodedata, asyncio
from datetime import datetime, timedelta
from collections import defaultdict
import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

# ====== Cấu hình ======
TURN_TIMEOUT_SECONDS = 25
IGNORE_DIACRITICS = True
MAP_D_TO_D = True

def strip(s):
    s = s.replace("Đ","D").replace("đ","d") if MAP_D_TO_D else s
    nf = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in nf if unicodedata.category(ch)!="Mn")

def norm_token(t):
    t = re.sub(r"[^\w\u00C0-\u024F]", "", t.lower())
    return strip(t) if IGNORE_DIACRITICS else t

def toks(s):
    return re.findall(r"[0-9A-Za-z_\u00C0-\u024F]+", s)

async def valid(text):
    ts = toks(text)
    if not ts: return False, "Cụm không hợp lệ."
    async with httpx.AsyncClient(http2=True) as c:
        for w in ts:
            r = await c.get(f"https://vi.wiktionary.org/api/rest_v1/page/summary/{w}", timeout=5)
            if r.status_code != 200:
                return False, f"❌ Từ '{w}' không có trên Wiktionary."
    return True, ""

class Game:
    def __init__(self):
        self.on=False
        self.need_norm=""
        self.need_disp=""
        self.used=set()
        self.score=defaultdict(int)

games={}
def g(cid):
    if cid not in games: games[cid]=Game()
    return games[cid]

async def cmd_start(u,c):
    await u.message.reply_text("🎮 /startgame [cụm]\n/score\n/stopgame")

async def cmd_startgame(u,c):
    chat=u.effective_chat.id
    gm=g(chat); gm.__init__(); gm.on=True
    text=" ".join(c.args) if c.args else ""
    if text:
        ok,err=await valid(text)
        if not ok: return await u.message.reply_text(err)
        gm.used.add(text.lower())
        last = toks(text)[-1]
        gm.need_disp = last               # giữ dấu để hiển thị
        gm.need_norm = norm_token(last)   # bỏ dấu để đối chiếu
        await u.message.reply_text(f"✅ Bắt đầu: {text}\n➡️ Nối từ bắt đầu bằng **{gm.need_disp.upper()}**",parse_mode="Markdown")
    else:
        await u.message.reply_text("Gửi cụm đầu tiên!")

async def cmd_stopgame(u,c):
    g(u.effective_chat.id).__init__()
    await u.message.reply_text("🛑 Kết thúc ván!")

async def cmd_score(u,c):
    gm=g(u.effective_chat.id)
    if not gm.score:
        return await u.message.reply_text("Chưa ai có điểm.")
    s="🏆 Điểm:\n"+"\n".join([f"{uid}: {p}" for uid,p in gm.score.items()])
    await u.message.reply_text(s)

async def on_text(u,c):
    gm=g(u.effective_chat.id)
    if not gm.on: return
    text=u.message.text
    ok,err=await valid(text)
    if not ok: return await u.message.reply_text(err)
    w=toks(text)
    if not w: return
    first = norm_token(w[0])
    if gm.need_norm and first!=gm.need_norm:
        return await u.message.reply_text(f"❌ Cụm phải bắt đầu bằng **{gm.need_disp.upper()}**",parse_mode="Markdown")
    gm.score[u.message.from_user.id]+=1
    gm.used.add(text.lower())
    gm.need_disp = w[-1]
    gm.need_norm = norm_token(w[-1])
    await u.message.reply_text(f"✅ +1\n➡️ Tiếp theo: **{gm.need_disp.upper()}**",parse_mode="Markdown")

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
