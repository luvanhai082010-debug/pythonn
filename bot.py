import logging
import os
import subprocess
import shutil
import asyncio 
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from telegram.constants import ChatAction

# --- 1. Cấu hình & Thiết lập ---

# !!! QUAN TRỌNG: Thay thế bằng cách đọc từ biến môi trường trên Render !!!
# Ví dụ: BOT_TOKEN = os.environ.get("BOT_TOKEN")
# Nếu chạy cục bộ trên Termux, bạn có thể giữ nguyên như cũ để kiểm tra nhanh.
# Khi triển khai lên Render, hãy dùng os.environ.get
BOT_TOKEN = "8551008920:AAHtuB-HLR8xq3l3_atqVf1EGssr5oox92w" 

# Thiết lập Logger (ĐÃ SỬA LỖI NAMEERROR: INFO)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Thư mục làm việc
TEMP_DIR = 'temp_files'
OUTPUT_DIR = 'output_tracks'
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- 2. Hàm Phụ Trợ (Tách, Chuyển đổi, Dọn dẹp) ---

def separate_audio(input_path, output_dir_base):
    """Sử dụng Spleeter để tách nhạc (lời và nhạc nền)."""
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    result_folder = os.path.join(output_dir_base, base_name)
    
    if os.path.exists(result_folder):
        shutil.rmtree(result_folder)

    try:
        # Lệnh Spleeter
        subprocess.run(
            ['spleeter', 'separate', '-i', input_path, '-p', 'spleeter:2stems', '-o', output_dir_base],
            check=True, capture_output=True, text=True
        )
        return (
            os.path.join(result_folder, 'vocals.wav'), 
            os.path.join(result_folder, 'accompaniment.wav')
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Lỗi khi chạy Spleeter: {e.stderr}")
        return None, None

def convert_to_mp3(input_wav_path, output_mp3_path):
    """Sử dụng FFmpeg để chuyển đổi tệp WAV sang MP3."""
    try:
        # Lệnh FFmpeg: -acodec libmp3lame (codec MP3), -q:a 2 (chất lượng cao)
        subprocess.run(
            ['ffmpeg', '-i', input_wav_path, '-acodec', 'libmp3lame', '-q:a', '2', output_mp3_path],
            check=True, capture_output=True, text=True
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Lỗi khi chuyển đổi sang MP3: {e.stderr}")
        return False

def cleanup_files(input_path, mp3_path_1, mp3_path_2):
    """Xóa tất cả các tệp tạm thời."""
    try:
        if os.path.exists(input_path): os.remove(input_path)
            
        if mp3_path_1 and os.path.exists(mp3_path_1):
            cleanup_folder = os.path.dirname(mp3_path_1)
            # Xóa toàn bộ thư mục chứa các file WAV và MP3
            if os.path.exists(cleanup_folder):
                shutil.rmtree(cleanup_folder)
        
        logger.info("Đã dọn dẹp các tệp tạm thời.")
    except Exception as e:
        logger.error(f"Lỗi dọn dẹp: {e}")

# --- 3. Hàm Xử lý Hiệu ứng Loading ---

async def display_processing_animation(message, duration=300):
    """Hiển thị hiệu ứng 'Đang Tách...' với dấu ba chấm chạy liên tục."""
    base_text = "Đang Tách nhạc"
    dots = ["", ".", "..", "..."]
    
    start_time = asyncio.get_event_loop().time()
    
    for i in range(duration * 2): 
        if asyncio.get_event_loop().time() - start_time > duration:
            break
            
        current_dots = dots[i % len(dots)]
        
        try:
            await message.edit_text(f"{base_text}{current_dots}")
        except Exception:
            break

        await asyncio.sleep(0.7)
        
    try:
        await message.edit_text("Hoàn thành quá trình tách. Đang tải lên kết quả...")
    except Exception:
        pass


# --- 4. Hàm Xử lý Lệnh và Tin nhắn ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trả lời lệnh /start và giới thiệu về bot."""
    
    welcome_message = (
        "🎶 Chào Mừng Đến Với Bot Tách Nhạc & Lời Vhai Vip! 🎤\n\n"
        "Tôi có thể tách lời bài hát (Vocals) và nhạc nền (Instrumental) ra khỏi tệp âm thanh của bạn.\n\n"
        "### Hướng Dẫn Sử Dụng:\n"
        "1. Gửi Tệp: Vui lòng gửi một tệp âm thanh hoặc video có chứa nhạc.\n"
        "2. Chờ xử lý: Bot sẽ tự động tải xuống, tách nhạc (thường mất vài phút).\n"
        "3. Nhận Kết Quả: Tôi sẽ gửi lại 2 tệp MP3 (Vocals và Instrumental) với tên của bạn.\n\n"
        "### Hỗ trợ định dạng tệp như:\n"
        "• MP3, M4A, WAV, FLAC\n"
        "• Video (MP4, MKV - bot sẽ trích xuất âm thanh)\n\n"
        "LƯU Ý: Quá trình xử lý và tải lên MP3 có thể mất thời gian. Xin vui lòng chờ đợi."
    )
    
    await update.message.reply_text(
        welcome_message, 
        parse_mode='Markdown'
    )


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý tệp được gửi, tải xuống, tách, chuyển đổi và gửi lại."""
    
    # 1. Lấy thông tin người dùng (Tên người tách)
    user = update.message.from_user
    requester_name = user.username if user.username else user.first_name
    # Làm sạch tên để đảm bảo an toàn cho tên file
    requester_name = ''.join(c for c in requester_name if c.isalnum() or c in (' ', '_')).strip() or "User"
    
    if update.message.audio:
        file_to_process = update.message.audio
    elif update.message.document:
        if not update.message.document.mime_type.startswith('audio/'):
            await update.message.reply_text("Vui lòng gửi tệp âm thanh (như MP3, WAV, M4A) hoặc video. Tệp tài liệu này không phải là âm thanh.")
            return
        file_to_process = update.message.document
    else:
        await update.message.reply_text("Vui lòng gửi tệp âm thanh (như MP3, WAV, M4A) hoặc video.")
        return
        
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    # 2. Tải File
    input_extension = os.path.splitext(file_to_process.file_name or "input.mp3")[1]
    input_filename = f"input_{file_to_process.file_unique_id}{input_extension}"
    input_path = os.path.join(TEMP_DIR, input_filename)
    
    try:
        new_file = await context.bot.get_file(file_to_process.file_id)
        await new_file.download_to_drive(input_path)
    except Exception as e:
        await update.message.reply_text(f"Lỗi tải file: {e}")
        return

    # 3. Bắt đầu Hiệu ứng Loading
    initial_message = await update.message.reply_text("Đang Tách nhạc...")
    animation_task = context.application.create_task(
        display_processing_animation(initial_message, duration=300)
    )

    # 4. Tách nhạc (WAV)
    vocals_path_wav, accompaniment_path_wav = separate_audio(input_path, OUTPUT_DIR)
    
    # Hủy task animation
    animation_task.cancel()

    # 5. Chuyển đổi sang MP3 và Gửi Kết quả
    vocals_path_mp3 = None
    accompaniment_path_mp3 = None
    
    if vocals_path_wav and accompaniment_path_wav:
        base_name_folder = os.path.dirname(vocals_path_wav)
        vocals_path_mp3 = os.path.join(base_name_folder, 'vocals.mp3')
        accompaniment_path_mp3 = os.path.join(base_name_folder, 'instruments.mp3')

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_AUDIO)
        
        try:
             await initial_message.edit_text("Hoàn thành quá trình tách. Đang chuyển đổi sang MP3 và tải lên kết quả...")
        except Exception:
             pass

        is_vocals_converted = convert_to_mp3(vocals_path_wav, vocals_path_mp3)
        is_accomp_converted = convert_to_mp3(accompaniment_path_wav, accompaniment_path_mp3)
        
        if is_vocals_converted and is_accomp_converted:
            await update.message.reply_text("Tách nhạc hoàn tất! Đây là kết quả:")
            
            # Gửi File Vocals MP3
            with open(vocals_path_mp3, 'rb') as f_v:
                await update.message.reply_audio(
                    f_v, 
                    title="Lời bài hát (Vocals)",
                    caption=f"Vocals tách bởi {requester_name}",
                    file_name=f"[{requester_name}] - vocals.mp3" 
                )
                
            # Gửi File Instrumental MP3
            with open(accompaniment_path_mp3, 'rb') as f_a:
                await update.message.reply_audio(
                    f_a, 
                    title="Nhạc nền (Instrumental)", 
                    caption=f"Instrumental tách bởi {requester_name}",
                    file_name=f"[{requester_name}] - instruments.mp3"
                )
            
        else:
            await update.message.reply_text("Xin lỗi, lỗi trong quá trình chuyển đổi sang MP3. Tệp đầu ra bị hủy.")
            
    else:
        await update.message.reply_text("Xin lỗi, quá trình tách nhạc đã thất bại. Vui lòng kiểm tra file và thử lại.")


    # 6. Dọn dẹp (Xóa tất cả file tạm thời)
    cleanup_files(input_path, vocals_path_mp3, accompaniment_path_mp3)

# --- 7. Hàm Main để Chạy Bot ---
def main() -> None:
    """Bắt đầu chạy bot."""
    
    # Cần đảm bảo rằng BOT_TOKEN đã được cập nhật
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE" or not BOT_TOKEN:
        logger.error("VUI LÒNG CẬP NHẬT BOT_TOKEN VỚI TOKEN THỰC CỦA BẠN HOẶC THIẾT LẬP BIẾN MÔI TRƯỜNG!")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Thêm Command Handler cho lệnh /start
    application.add_handler(CommandHandler("start", start))

    # Xử lý các tệp âm thanh hoặc tệp gửi dưới dạng document
    # ĐÃ SỬA LỖI NAMEERROR: INFO VÀ ATTRIBUTEERROR: MIMETYPE
    media_filter = filters.AUDIO | (filters.Document.ALL & filters.Document.MimeType("audio/")) 
    application.add_handler(MessageHandler(media_filter, handle_media))

    logger.info("Bot đang khởi động...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
