import logging
import random
import requests
import unicodedata
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, JobQueue

# Cấu hình logging
logging.basicConfig(
    format='%(asctime)s – %(name)s – %(levelname)s – %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Token bot (test)
BOT_TOKEN = "8412177639:AAHvzw4Ny8LlBE2P9gl3vZ-o6Jbv9TtU6DQ"

# Hàm chuẩn hóa bỏ dấu cho việc nối từ
def strip_accents(s: str) -> str:
    s_nf = unicodedata.normalize('NFD', s)
    return ''.join(ch for ch in s_nf if unicodedata.category(ch) != 'Mn')

def normalized_first_char(s: str) -> str:
    if not s:
        return ''
    s_stripped = strip_accents(s.strip().lower())
    return s_stripped[0]

def normalized_last_char(s: str) -> str:
    if not s:
        return ''
    t = s.strip()
    # lấy ký tự cuối cùng là chữ cái
    i = len(t)-1
    while i >= 0 and not t[i].isalpha():
        i -= 1
    if i < 0:
        return ''
    ch = t[i]
    return strip_accents(ch.lower())

# Kiểm tra cụm từ có tồn tại (sử dụng Wiktionary tiếng Việt)
def word_exists_vi(word: str) -> bool:
    try:
        url = "https://vi.wiktionary.org/w/api.php"
        params = {
            "action": "query",
            "titles": word,
            "format": "json"
        }
        r = requests.get(url, params=params, timeout=5)
        r.raise_for_status()
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if 'missing' not in page:
                return True
        return False
    except Exception as e:
        logger.error(f"Error checking word {word}: {e}")
        return False

# Lưu trạng thái trò chơi theo chat_id
class Game:
    def __init__(self):
        self.active = False
        self.join_phase = False
        self.players = []           # danh sách user objects
        self.current_phrase = None  # cụm từ hiện tại
        self.turn_index = 0
        self.job_join = None        # job chờ join
        self.job_turn = None        # job chờ lượt

games = {}

# Lệnh /Batdau
async def cmd_batdau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in games and games[chat_id].active:
        await update.message.reply_text("Trò chơi đã đang diễn ra.")
        return
    game = Game()
    game.active = True
    game.join_phase = True
    games[chat_id] = game
    await update.message.reply_text("Trò chơi nối từ sẽ bắt đầu! Gõ /join để tham gia trong 30 giây.")
    # sau 30s kết thúc giai đoạn join
    game.job_join = context.job_queue.run_once(end_join_phase, when=30, chat_id=chat_id)

# Lệnh /join
async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    if chat_id not in games or not games[chat_id].active:
        await update.message.reply_text("Hiện không có trò chơi nào. Dùng /Batdau để bắt đầu.")
        return
    game = games[chat_id]
    if not game.join_phase:
        await update.message.reply_text("Đã hết thời gian tham gia.")
        return
    # kiểm tra xem user đã tham gia chưa
    if any(p.id == user.id for p in game.players):
        await update.message.reply_text(f"{user.full_name} đã tham gia rồi.")
        return
    game.players.append(user)
    await update.message.reply_text(f"{user.full_name} tham gia trò chơi!")

async def end_join_phase(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    if chat_id not in games:
        return
    game = games[chat_id]
    if not game.active or not game.join_phase:
        return
    game.join_phase = False
    if len(game.players) < 2:
        await context.bot.send_message(chat_id, "Không đủ người chơi để bắt đầu. Trò chơi kết thúc.")
        del games[chat_id]
        return
    # chọn cụm từ đầu tiên ngẫu nhiên (ví dụ dùng từ Wiktionary random hoặc cố định mẫu)
    # Ở đây ta dùng mẫu tĩnh đơn giản:
    starters = ["cái bàn", "con mèo", "chiếc ghế", "quả táo", "đồ vật"]
    phrase = random.choice(starters)
    game.current_phrase = phrase
    await context.bot.send_message(chat_id, f"🎮 Trò chơi bắt đầu! Cụm từ đầu tiên: *{phrase}*", parse_mode="Markdown")
    # bắt đầu lượt đầu tiên
    game.turn_index = 0
    await prompt_next_player(context, chat_id)

async def prompt_next_player(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    if chat_id not in games:
        return
    game = games[chat_id]
    # nếu chỉ còn 1 người → thắng
    if len(game.players) == 1:
        winner = game.players[0]
        mention = f"@{winner.username}" if winner.username else winner.full_name
        await context.bot.send_message(chat_id, f"🏆 Chúc mừng {mention}! Bạn đã chiến thắng!")
        del games[chat_id]
        return
    # xác định người kế tiếp
    game.turn_index %= len(game.players)
    player = game.players[game.turn_index]
    mention = f"@{player.username}" if player.username else player.full_name
    await context.bot.send_message(chat_id, f"{mention}, lượt của bạn! Hãy nhập cụm từ tiếp theo bắt đầu bằng *{normalized_last_char(game.current_phrase).upper()}*.", parse_mode="Markdown")
    # đặt job timeout 30s
    game.job_turn = context.job_queue.run_once(on_turn_timeout, when=30, chat_id=chat_id)

async def on_turn_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    if chat_id not in games:
        return
    game = games[chat_id]
    # user thiệt hại lượt này
    if game.turn_index < len(game.players):
        eliminated = game.players.pop(game.turn_index)
        mention = f"@{eliminated.username}" if eliminated.username else eliminated.full_name
        await context.bot.send_message(chat_id, f"{mention} đã hết thời gian và bị loại.")
    # kiểm tra kết thúc
    await prompt_next_player(context, chat_id)

# Xử lý tin nhắn (cụm từ người chơi gõ)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text.strip()
    if chat_id not in games:
        return
    game = games[chat_id]
    if not game.active or game.join_phase:
        return
    # kiểm xem có đúng người được nhắc
    if game.players and game.players[game.turn_index].id != user.id:
        return
    # hủy job timeout của lượt này
    if game.job_turn:
        game.job_turn.schedule_removal()
        game.job_turn = None
    # kiểm nối từ
    last_char = normalized_last_char(game.current_phrase)
    first_char = normalized_first_char(text)
    if first_char != last_char:
        mention = f"@{user.username}" if user.username else user.full_name
        await update.message.reply_text(f"{mention} gõ sai chữ nối. Bị loại.")
        # loại người chơi
        game.players.pop(game.turn_index)
        # kiểm kết thúc
        await prompt_next_player(context, chat_id)
        return
    # kiểm tra cụm có nghĩa
    # kiểm mỗi từ trong cụm
    words = text.split()
    for w in words:
        if not word_exists_vi(w):
            mention = f"@{user.username}" if user.username else user.full_name
            await update.message.reply_text(f"{mention} sử dụng từ \"{w}\" không có trong từ điển. Bị loại.")
            game.players.pop(game.turn_index)
            await prompt_next_player(context, chat_id)
            return
    # nếu hợp lệ
    game.current_phrase = text
    await update.message.reply_text(f"Cụm từ \"{text}\" hợp lệ!")
    # chuyển lượt
    game.turn_index += 1
    await prompt_next_player(context, chat_id)

# Lệnh /Ketthuc
async def cmd_ketthuc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in games:
        del games[chat_id]
        await update.message.reply_text("Trò chơi đã được kết thúc.")
    else:
        await update.message.reply_text("Không có trò chơi nào đang diễn ra.")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("Batdau", cmd_batdau))
    application.add_handler(CommandHandler("join", cmd_join))
    application.add_handler(CommandHandler("Ketthuc", cmd_ketthuc))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_polling()
    logger.info("Bot đã khởi động.")

if __name__ == '__main__':
    main()
