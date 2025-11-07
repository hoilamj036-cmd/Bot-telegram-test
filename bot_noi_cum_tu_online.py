BOT_TOKEN = "8412177639:AAHvzw4Ny8LlBE2P9gl3vZ-o6Jbv9TtU6DQ"

import re, unicodedata
from datetime import datetime, timedelta
from collections import defaultdict
from urllib.parse import quote
import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

IGNORE_DIACRITICS = True
MAP_D_TO_D = True

def strip(s):
    s = s.replace("Đ","D").replace("đ","d") if MAP_D_TO_D else s
    nf = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in nf if unicodedata.category(ch)!="Mn")

def norm_token(t):
    t = re.sub(r"[^\w\u00C0-\u024F\u1E00-\u1EFF]", "", t.lower())
    return strip(t) if IGNORE_DIACRITICS else t

def toks(s):
    return re.findall(r"[0-9A-Za-z_\u00C0-\u024F\u1E00-\u1EFF]+", s)

async def word_exists(word):
    async with httpx.AsyncClient() as c:
        url = f"https://vi.wiktionary.org/api/rest_v1/page/summary/{quote(word)}"
        r = await c.get(url, timeout=6)
        return r.status_code == 200

async def valid(phrase):
    ts = toks(phrase)
    if not ts:
        return False, "❌ Cụm không hợp lệ."
    last = ts[-1]
    if not await word_exists(last):
        return False, f"❌ Từ cuối “{last}” không có trong từ điển."
    return True, ""

class Game:
    def __init__(self):
        self.on = False
        self.need_norm = ""
        self.need_disp = ""
        self.used = set()
        self.score = defaultdict(int)

games = {}
def g(cid):
    if cid not in games: games[cid]=Game()
    return games[cid]

async def cmd_start(u,c):
    await u.message.reply_text("🎮 /startgame [cụm]\n/score\n/stopgame")

async def cmd_startgame(u,c):
    gm=g(u.effective_chat.id)
    gm.__init__(); gm.on=True
    text=" ".join(c.args) if c.args else ""
    if text:
        ok,err=await valid(text)
        if not ok: return await u.message.reply_text(err)
        ts=toks(text)
        gm.need_disp=ts[-1]
        gm.need_norm=norm_token(ts[-1])
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
    await u.message.reply_text("\n".join([f"{uid}: {p}" for uid,p in gm.score.items()]))

async def on_text(u,c):
    gm=g(u.effective_chat.id)
    if not gm.on: return
    text=u.message.text

    ok,err=await valid(text)
    if not ok: return await u.message.reply_text(err)

    ts=toks(text)
    first=norm_token(ts[0])
    if gm.need_norm and first!=gm.need_norm:
        return await u.message.reply_text(f"❌ Cụm phải bắt đầu bằng **{gm.need_disp.upper()}**",parse_mode="Markdown")

    uid=u.message.from_user.id
    gm.score[uid]+=1
    gm.need_disp=ts[-1]
    gm.need_norm=norm_token(ts[-1])
    await u.message.reply_text(f"✅ +1\n➡️ Tiếp theo: **{gm.need_disp.upper()}**",parse_mode="Markdown")

def main():
    app=Application.builder().token(BOT_TOKEN).request(HTTPXRequest()).build()
    app.add_handler(CommandHandler("start",cmd_start))
    app.add_handler(CommandHandler("startgame",cmd_startgame))
    app.add_handler(CommandHandler("stopgame",cmd_stopgame))
    app.add_handler(CommandHandler("score",cmd_score))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,on_text))
    app.run_polling()

if __name__=="__main__":
    main()
