from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
)
import logging

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

# Thay YOUR_TELEGRAM_BOT_TOKEN thành token thực tế của bạn
BOT_TOKEN = '8412177639:AAHvzw4Ny8LlBE2P9gl3vZ-o6Jbv9TtU6DQ'

# Xử lý lệnh /Batdau: Khởi động trò chơi mới
async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_data = context.chat_data
    
    # Nếu đã có trò chơi đang diễn ra
    if chat_data.get("active"):
        await context.bot.send_message(chat_id, "Trò chơi đã bắt đầu rồi. Dùng /join để tham gia.")
        return
    
    # Thiết lập trạng thái trò chơi
    chat_data.clear()
    chat_data["active"] = True
    chat_data["joining"] = True
    chat_data["players"] = []
    chat_data["current_word"] = None
    chat_data["turn_index"] = 0
    
    await context.bot.send_message(chat_id, 
        "Trò chơi mới bắt đầu! Có 30 giây để mọi người /join vào.")
    
    # Sau 30 giây, kết thúc giai đoạn join
    context.job_queue.run_once(end_joining, when=30, chat_id=chat_id)

# Xử lý lệnh /join: Tham gia trò chơi
async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_data = context.chat_data
    user = update.effective_user
    
    if not chat_data.get("active"):
        await context.bot.send_message(chat_id, "Chưa có trò chơi nào. Dùng /Batdau để bắt đầu.")
        return
    if not chat_data.get("joining"):
        await context.bot.send_message(chat_id, "Đã hết thời gian /join.")
        return
    
    players = chat_data["players"]
    if user in players:
        await context.bot.send_message(chat_id, f"{user.full_name} đã tham gia rồi!")
        return
    
    players.append(user)
    await context.bot.send_message(chat_id, f"{user.full_name} tham gia trò chơi!")

# Kết thúc giai đoạn join và bắt đầu vòng đầu tiên
async def end_joining(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    chat_data = context.dispatcher.chat_data[chat_id]
    
    if not chat_data.get("active"):
        return
    
    chat_data["joining"] = False
    players = chat_data["players"]
    if not players:
        # Không có ai tham gia
        await context.bot.send_message(chat_id, "Không có ai tham gia, kết thúc trò chơi.")
        chat_data.clear()
        return
    
    # Thông báo danh sách người chơi và bắt đầu
    names = ", ".join(p.full_name for p in players)
    await context.bot.send_message(chat_id, f"Người chơi: {names}")
    await context.bot.send_message(chat_id, 
        f"{players[0].full_name}, lượt bạn. Mời đưa từ đầu tiên!")
    
    # Khởi động bộ đếm thời gian 30 giây cho lượt chơi
    context.job_queue.run_once(turn_timeout, when=30, chat_id=chat_id)

# Xử lý lệnh /Ketthuc: Kết thúc trò chơi
async def end_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_data = context.chat_data
    if not chat_data.get("active"):
        await context.bot.send_message(chat_id, "Chưa có trò chơi đang diễn ra.")
        return
    chat_data.clear()
    await context.bot.send_message(chat_id, "Trò chơi đã được kết thúc.")

# Xử lý timeout nếu người chơi không trả lời trong 30 giây
async def turn_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    chat_data = context.dispatcher.chat_data[chat_id]
    
    # Nếu trò chơi đang diễn ra
    if not chat_data.get("active"):
        return
    
    players = chat_data["players"]
    idx = chat_data["turn_index"]
    
    # Nếu người chơi hiện tại vẫn tồn tại, loại họ
    if idx < len(players):
        eliminated = players.pop(idx)
        await context.bot.send_message(chat_id, f"{eliminated.full_name} không trả lời kịp và bị loại!")
    
    # Kiểm tra kết thúc trò chơi
    if len(players) <= 1:
        if players:
            await context.bot.send_message(chat_id, f"Người chiến thắng: {players[0].full_name}!")
        else:
            await context.bot.send_message(chat_id, "Không còn ai chơi, kết thúc.")
        chat_data.clear()
        return
    
    # Chuyển lượt cho người kế tiếp
    if idx >= len(players):
        idx = 0
    chat_data["turn_index"] = idx
    next_player = players[idx]
    await context.bot.send_message(chat_id, f"{next_player.full_name}, lượt của bạn. Từ hiện tại: \"{chat_data['current_word']}\"")
    context.job_queue.run_once(turn_timeout, when=30, chat_id=chat_id)

# Xử lý tin nhắn văn bản: Kiểm tra từ người chơi khi lượt đến
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_data = context.chat_data
    
    # Bỏ qua nếu không có trò chơi hoặc đang trong giai đoạn join
    if not chat_data.get("active") or chat_data.get("joining"):
        return
    
    user = update.effective_user
    players = chat_data["players"]
    idx = chat_data["turn_index"]
    # Nếu không phải lượt của người gửi, bỏ qua
    if idx >= len(players) or players[idx].id != user.id:
        return
    
    word = update.message.text.strip()
    current_word = chat_data.get("current_word")
    
    # Nếu đã có từ trước, kiểm tra tính hợp lệ
    if current_word:
        last_char = current_word[-1].lower()
        first_char = word[0].lower() if word else ''
        if first_char != last_char:
            # Loại người chơi nếu từ không hợp lệ
            players.pop(idx)
            await context.bot.send_message(chat_id, f"Từ \"{word}\" không hợp lệ! {user.full_name} bị loại.")
            # Kiểm tra kết thúc
            if len(players) <= 1:
                if players:
                    await context.bot.send_message(chat_id, f"Người chiến thắng: {players[0].full_name}!")
                else:
                    await context.bot.send_message(chat_id, "Không còn ai chơi, kết thúc.")
                chat_data.clear()
                return
            # Chuyển lượt
            if idx >= len(players):
                idx = 0
            chat_data["turn_index"] = idx
            next_player = players[idx]
            await context.bot.send_message(chat_id, f"{next_player.full_name}, lượt của bạn.")
            context.job_queue.run_once(turn_timeout, when=30, chat_id=chat_id)
            return
    
    # Từ hợp lệ, cập nhật từ hiện tại và chuyển lượt
    chat_data["current_word"] = word
    await context.bot.send_message(chat_id, f"Từ \"{word}\" hợp lệ!")
    
    idx += 1
    if idx >= len(players):
        idx = 0
    chat_data["turn_index"] = idx
    next_player = players[idx]
    await context.bot.send_message(chat_id, f"{next_player.full_name}, lượt của bạn.")
    context.job_queue.run_once(turn_timeout, when=30, chat_id=chat_id)

# Khởi động Bot
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("Batdau", start_game))
    app.add_handler(CommandHandler("join", join_game))
    app.add_handler(CommandHandler("Ketthuc", end_game))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Bot đang chạy...")
    app.run_polling()

if __name__ == '__main__':
    main()
