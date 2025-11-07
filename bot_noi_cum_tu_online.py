#!/usr/bin/env python3
import logging
import requests
import random
import unicodedata

from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# Kích hoạt ghi log
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "8412177639:AAHvzw4Ny8LlBE2P9gl3vZ-o6Jbv9TtU6DQ"  # Thay bằng token của bạn

def unaccent(text):
    """Loại bỏ dấu tiếng Việt để so sánh ký tự."""
    nkfd_form = unicodedata.normalize('NFD', text)
    return ''.join([c for c in nkfd_form if not unicodedata.category(c).startswith('M')])

def is_valid_word(word):
    """
    Kiểm tra từ trong Wiktionary tiếng Việt.
    Sử dụng MediaWiki API: nếu trang bài viết tồn tại thì coi như có nghĩa.
    """
    try:
        url = "https://vi.wiktionary.org/w/api.php"
        params = {"action": "query", "titles": word, "format": "json"}
        res = requests.get(url, params=params, timeout=5)
        res.raise_for_status()
        data = res.json()
        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if 'missing' not in page:
                return True  # Trang có tồn tại
        return False
    except Exception as e:
        logger.error(f"Error checking word {word}: {e}")
        return False

class Game:
    def __init__(self):
        self.players = []         # Danh sách người chơi (lưu user object)
        self.current_phrase = None
        self.current_index = 0    # Chỉ số người chơi hiện tại trong vòng chơi
        self.join_job = None      # Job đếm giờ 30s chờ join
        self.turn_job = None      # Job đếm giờ 30s cho lượt
        self.game_active = False  # Cờ đang chơi
        self.waiting_for = None   # user_id người chơi đang chờ trả lời

games = {}  # Lưu trạng thái game theo chat_id

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Chào! Dùng /Batdau để bắt đầu trò chơi nối từ.")

def batdau(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if chat_id in games and games[chat_id].game_active:
        update.message.reply_text("Đã có trò chơi đang diễn ra.")
        return
    game = Game()
    games[chat_id] = game
    update.message.reply_text("Trò chơi nối từ sẽ bắt đầu sau 30 giây! Dùng /join để tham gia.")
    # Lập lịch bắt đầu trò chơi sau 30 giây
    game.join_job = context.job_queue.run_once(start_game, 30, context=chat_id)

def join(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user = update.effective_user
    if chat_id not in games:
        update.message.reply_text("Trò chơi chưa bắt đầu. Dùng /Batdau để bắt đầu.")
        return
    game = games[chat_id]
    if game.game_active:
        update.message.reply_text("Trò chơi đã bắt đầu, không thể tham gia nữa.")
        return
    if any(p.id == user.id for p in game.players):
        update.message.reply_text("Bạn đã tham gia rồi!")
        return
    game.players.append(user)
    update.message.reply_text(f"{user.first_name} đã tham gia trò chơi!")

def start_game(context: CallbackContext):
    chat_id = context.job.context
    game = games.get(chat_id)
    if not game:
        return
    players = game.players
    if len(players) < 2:
        context.bot.send_message(chat_id, "Không đủ người chơi để bắt đầu. Trò chơi kết thúc.")
        games.pop(chat_id, None)
        return
    # Lấy cụm từ đầu tiên ngẫu nhiên từ Wiktionary (random page)
    try:
        res = requests.get("https://vi.wiktionary.org/w/api.php", params={
            "action": "query", "list": "random", "rnnamespace": "0",
            "rnlimit": "1", "format": "json"
        }, timeout=5)
        data = res.json()
        rand_page = data.get("query", {}).get("random", [{}])[0].get("title", "xin chào")
    except Exception as e:
        logger.error(f"Error getting random word: {e}")
        rand_page = "xin chào"
    game.current_phrase = rand_page
    game.game_active = True
    context.bot.send_message(chat_id,
                             f"Trò chơi bắt đầu! Cụm từ đầu tiên: *{game.current_phrase}*",
                             parse_mode=ParseMode.MARKDOWN)
    # Bắt đầu lượt đầu tiên
    game.current_index = 0
    prompt_next_turn(context, chat_id)

def prompt_next_turn(context: CallbackContext, chat_id):
    game = games.get(chat_id)
    if not game or not game.game_active:
        return
    # Nếu chỉ còn 1 người thì họ thắng
    if len(game.players) == 1:
        winner = game.players[0]
        mention = f"@{winner.username}" if winner.username else winner.first_name
        context.bot.send_message(chat_id, f"Chúc mừng {mention}! Bạn đã chiến thắng!")
        games.pop(chat_id, None)
        return
    game.current_index %= len(game.players)
    player = game.players[game.current_index]
    mention = f"@{player.username}" if player.username else player.first_name
    context.bot.send_message(chat_id, f"{mention}, đến lượt bạn! Nhập cụm từ tiếp theo...")
    game.waiting_for = player.id
    # Lập lịch timeout sau 30 giây cho lượt này
    game.turn_job = context.job_queue.run_once(turn_timeout, 30, context=chat_id)

def turn_timeout(context: CallbackContext):
    chat_id = context.job.context
    game = games.get(chat_id)
    if not game or not game.game_active:
        return
    if game.current_index < len(game.players):
        timed_out_player = game.players[game.current_index]
    else:
        return
    mention = f"@{timed_out_player.username}" if timed_out_player.username else timed_out_player.first_name
    context.bot.send_message(chat_id, f"{mention} đã hết thời gian và bị loại.")
    game.players.pop(game.current_index)
    # Kiểm tra kết thúc
    if len(game.players) <= 1:
        if game.players:
            winner = game.players[0]
            mention = f"@{winner.username}" if winner.username else winner.first_name
            context.bot.send_message(chat_id, f"Chúc mừng {mention}! Bạn đã chiến thắng.")
        else:
            context.bot.send_message(chat_id, "Không còn người chơi nào. Trò chơi kết thúc.")
        games.pop(chat_id, None)
        return
    prompt_next_turn(context, chat_id)

def message_handler(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text.strip()
    if chat_id not in games:
        return
    game = games[chat_id]
    if not game.game_active:
        return
    # Chỉ xử lý nếu đúng người được nhắc trả lời
    if user.id != game.waiting_for:
        return
    # Hủy bỏ công việc timeout nếu có
    if game.turn_job:
        game.turn_job.schedule_removal()
        game.turn_job = None
    phrase = text
    # Lấy chữ cái cuối của cụm từ hiện tại (đã loại bỏ ký tự không phải chữ)
    last_char = game.current_phrase.strip()[-1]
    while last_char and not last_char.isalpha():
        game.current_phrase = game.current_phrase[:-1]
        last_char = game.current_phrase.strip()[-1] if game.current_phrase else ''
    first_char = phrase.strip()[0] if phrase else ''
    if first_char:
        first_norm = unaccent(first_char.lower())
        last_norm = unaccent(last_char.lower()) if last_char else ''
    else:
        first_norm = ''
        last_norm = ''
    valid_chain = (first_norm == last_norm and first_char != '')
    # Kiểm tra từng từ trong cụm có trong từ điển không
    valid_phrase = True
    for word in phrase.split():
        if not is_valid_word(word):
            valid_phrase = False
            break
    if not valid_chain or not valid_phrase:
        mention = f"@{user.username}" if user.username else user.first_name
        update.message.reply_text(f"{mention} đã bị loại vì cụm từ không hợp lệ.")
        # Loại người chơi
        for i, p in enumerate(game.players):
            if p.id == user.id:
                game.players.pop(i)
                break
        game.current_index %= len(game.players) if game.players else 0
        if len(game.players) <= 1:
            if game.players:
                winner = game.players[0]
                mention_win = f"@{winner.username}" if winner.username else winner.first_name
                update.message.reply_text(f"Chúc mừng {mention_win}! Bạn đã chiến thắng.")
            else:
                update.message.reply_text("Không còn người chơi nào. Trò chơi kết thúc.")
            games.pop(chat_id, None)
        else:
            prompt_next_turn(context, chat_id)
        return
    # Nếu hợp lệ, cập nhật và chuyển lượt
    game.current_phrase = phrase
    update.message.reply_text("Cụm từ hợp lệ! Tiếp tục nào...")
    game.current_index = (game.current_index + 1) % len(game.players)
    prompt_next_turn(context, chat_id)

def ketthuc(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if chat_id in games:
        games.pop(chat_id, None)
        update.message.reply_text("Trò chơi đã được kết thúc.")
    else:
        update.message.reply_text("Chưa có trò chơi nào đang diễn ra.")

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("Batdau", batdau))
    dp.add_handler(CommandHandler("join", join))
    dp.add_handler(CommandHandler("Ketthuc", ketthuc))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, message_handler))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
