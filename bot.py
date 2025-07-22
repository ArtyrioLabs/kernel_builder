#!/usr/bin/env python3
import os
import subprocess
import logging
import shutil
from datetime import datetime
from telegram import Update, InputFile, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from dotenv import load_dotenv
import requests
import psutil
import tempfile
import zipfile

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ESP_IP = os.getenv("ESP_IP")
MAX_LOG_FILES = 10

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(PROJECT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

def cleanup_old_logs():
    try:
        logs = sorted(os.listdir(LOG_DIR))
        while len(logs) > MAX_LOG_FILES:
            os.remove(os.path.join(LOG_DIR, logs.pop(0)))
    except Exception as e:
        logger.error(f"Error cleaning logs: {e}")

def send_to_esp8266(message: str):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            url = f"http://{ESP_IP}/display?text={requests.utils.quote(message)}"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                logger.info(f"Sent to ESP8266: {message}")
                return True
        except Exception as e:
            logger.warning(f"ESP8266 send attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                logger.error(f"Failed to send to ESP8266 after {max_retries} attempts")
    return False

async def setup_commands(application):
    commands = [
        BotCommand("start", "Запустить бота"),
        BotCommand("build", "Запустить сборку ядра"),
        BotCommand("status", "Проверить статус системы"),
        BotCommand("logs", "Получить список логов"),
        BotCommand("clean", "Очистить старые логи"),
        BotCommand("help", "Показать справку"),
        BotCommand("restart", "Перезапустить бота")  
    ]
    await application.bot.set_my_commands(commands)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "🔧 *Build Monitor Bot*\n\n"
        "Доступные команды:\n"
        "/build - Запустить сборку ядра\n"
        "/status - Проверить статус системы\n"
        "/logs - Получить список логов\n"
        "/clean - Очистить старые логи\n"
        "/restart - Перезапустить бота\n"  
        "/help - Показать справку"
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')
    send_to_esp8266("Bot Ready")

# --- Глобальная переменная для процесса сборки ---
build_process = None

async def build_kernel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global build_process
    user = update.effective_user
    logger.info(f"Build requested by {user.full_name} (ID: {user.id})")
    
    await update.message.reply_text("⚙️ *Запускаю сборку ядра...*", parse_mode='Markdown')
    send_to_esp8266("Build Started")

    log_filename = f"build_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_path = os.path.join(LOG_DIR, log_filename)
    kernel_name = None
    image_path = None
    try:
        with open(log_path, 'w') as log_file:
            build_process = subprocess.Popen(
                ["./build.sh"],
                cwd=PROJECT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            while True:
                output = build_process.stdout.readline()
                if output == '' and build_process.poll() is not None:
                    break
                if output:
                    log_file.write(output)
                    logger.info(output.strip())
                    if output.startswith("Using kernel name:"):
                        kernel_name = output.strip().split(":",1)[-1].strip()
                    elif output.strip().startswith("Kernel image:"):
                        image_path = output.strip().split(":",1)[-1].strip()
        if build_process.returncode == 0:
            await update.message.reply_text("✅ *Сборка завершена успешно!*", parse_mode='Markdown')
            send_to_esp8266("Build Success")
            # --- Отправка архива прошивки ядра ---
            zip_msg = await pack_and_send_zip(context, update, kernel_name, image_path)
            await update.message.reply_text(zip_msg, parse_mode='Markdown')
            send_to_esp8266("Zip OK")
            with open(log_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=InputFile(f, filename=log_filename),
                    caption=f"Лог сборки: {log_filename}"
                )
        else:
            await update.message.reply_text("❌ *Сборка завершилась с ошибкой!*", parse_mode='Markdown')
            send_to_esp8266("Build Failed")
            with open(log_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=InputFile(f, filename=log_filename),
                    caption=f"Лог ошибки: {log_filename}"
                )
    except subprocess.TimeoutExpired:
        error_msg = "🕒 *Превышено время ожидания сборки (30 минут)*"
        await update.message.reply_text(error_msg, parse_mode='Markdown')
        send_to_esp8266("Timeout Error")
    except Exception as e:
        error_msg = f"⚠️ *Критическая ошибка:* {str(e)}"
        await update.message.reply_text(error_msg, parse_mode='Markdown')
        send_to_esp8266("Critical Error")
        logger.exception("Build failed")
    finally:
        build_process = None
        cleanup_old_logs()

async def pack_and_send_zip(context, update, kernel_name, image_path):
    try:
        anykernel_dir = os.path.join(PROJECT_DIR, "AnyKernel")
        zips_dir = os.path.join(PROJECT_DIR, "zips")
        os.makedirs(zips_dir, exist_ok=True)
        date_str = datetime.now().strftime('%Y%m%d_%H%M')
        zip_name = f"kernel-flashable-{kernel_name}_{date_str}.zip"
        zip_path = os.path.join(zips_dir, zip_name)
        with tempfile.TemporaryDirectory() as tmpdir:
            shutil.copytree(anykernel_dir, os.path.join(tmpdir, "AnyKernel"), dirs_exist_ok=True)
            ak_dir = os.path.join(tmpdir, "AnyKernel")
            if not image_path or not os.path.isfile(image_path):
                image_path = os.path.join(PROJECT_DIR, "..", "out", "arch", "arm64", "boot", "Image.gz")
            shutil.copy2(image_path, os.path.join(ak_dir, "Image.gz"))
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(ak_dir):
                    for file in files:
                        abs_path = os.path.join(root, file)
                        rel_path = os.path.relpath(abs_path, ak_dir)
                        zipf.write(abs_path, rel_path)
        size_mb = os.path.getsize(zip_path) / (1024*1024)
        caption = f"Готовый архив для прошивки\nЯдро: {kernel_name}\nРазмер: {size_mb:.2f} MB\nДата: {date_str}"
        with open(zip_path, "rb") as fzip:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=InputFile(fzip, filename=zip_name),
                caption=caption
            )
        return f"✅ Архив создан и отправлен.\nИмя: {zip_name}\nРазмер: {size_mb:.2f} MB"
    except Exception as e:
        logger.exception("Ошибка при упаковке/отправке zip")
        return f"❌ Ошибка при упаковке/отправке zip: {e}"

async def stop_build(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global build_process
    if build_process and build_process.poll() is None:
        build_process.terminate()
        try:
            build_process.wait(timeout=10)
        except Exception:
            build_process.kill()
        build_process = None
        await update.message.reply_text("⛔️ *Сборка остановлена по запросу!*", parse_mode='Markdown')
        send_to_esp8266("Build Stopped!")
    else:
        await update.message.reply_text("ℹ️ Нет активной сборки для остановки.", parse_mode='Markdown')

async def list_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logs = sorted(os.listdir(LOG_DIR), reverse=True)
        if not logs:
            await update.message.reply_text("Логи не найдены")
            return
            
        response = "📋 *Последние логи сборки:*\n"
        for log in logs[:5]:
            size = os.path.getsize(os.path.join(LOG_DIR, log)) / 1024
            response += f"- `{log}` ({size:.1f} KB)\n"
        
        await update.message.reply_text(response, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка при получении списка логов: {e}")

async def clean_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logs = sorted(os.listdir(LOG_DIR))
        if len(logs) <= MAX_LOG_FILES:
            await update.message.reply_text(f"Хранится {len(logs)} логов (максимум {MAX_LOG_FILES}), очистка не требуется")
            return
            
        deleted = 0
        for log in logs[:-MAX_LOG_FILES]:
            os.remove(os.path.join(LOG_DIR, log))
            deleted += 1
            
        await update.message.reply_text(f"Удалено {deleted} старых логов. Сохранено {MAX_LOG_FILES} последних.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка при очистке логов: {e}")

async def system_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        esp_online = False
        try:
            esp_online = requests.get(f"http://{ESP_IP}", timeout=3).ok
        except:
            pass
        
        cpu_usage = psutil.cpu_percent()
        mem = psutil.virtual_memory()
        uptime = subprocess.check_output(["uptime"]).decode().strip()
        
        status_msg = (
            f"📊 *Статус системы*\n\n"
            f"*ESP8266:* {'🟢 Online' if esp_online else '🔴 Offline'}\n"
            f"*CPU:* {cpu_usage}%\n"
            f"*Memory:* {mem.percent}% used\n"
            f"*Uptime:* {uptime.split(',')[0]}" 
        )
        await update.message.reply_text(status_msg, parse_mode='Markdown')
        send_to_esp8266("Status Checked")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка проверки статуса: {e}")

async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 *Перезапускаю бота...*", parse_mode='Markdown')
    send_to_esp8266("Restarting...")
    os.execv(__file__, sys.argv)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📚 *Справка по боту*\n\n"
        "*/build* - Запустить сборку ядра\n"
        "*/status* - Проверить статус системы\n"
        "*/logs* - Получить список последних логов\n"
        "*/clean* - Очистить старые логи\n"
        "*/restart* - Перезапустить бота\n"
        "*/help* - Эта справка"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

def main():
    application = ApplicationBuilder() \
        .token(BOT_TOKEN) \
        .post_init(setup_commands) \
        .build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("build", build_kernel))
    application.add_handler(CommandHandler("status", system_status))
    application.add_handler(CommandHandler("logs", list_logs))
    application.add_handler(CommandHandler("clean", clean_logs))
    application.add_handler(CommandHandler("restart", restart_bot))  
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stopbuild", stop_build))
    
    logger.info("Bot starting...")
    send_to_esp8266("Bot Starting")
    
    application.run_polling()

if __name__ == "__main__":
    import sys
    main()
