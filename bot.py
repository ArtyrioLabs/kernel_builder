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

async def build_kernel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Build requested by {user.full_name} (ID: {user.id})")
    
    await update.message.reply_text("⚙️ *Запускаю сборку ядра...*", parse_mode='Markdown')
    send_to_esp8266("Build Started")

    log_filename = f"build_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_path = os.path.join(LOG_DIR, log_filename)

    try:
        with open(log_path, 'w') as log_file:
            process = subprocess.Popen(
                ["./build.sh"],
                cwd=PROJECT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    log_file.write(output)
                    logger.info(output.strip())
                    
                    if "Applying patch" in output:
                        send_to_esp8266("Patching...")
                    elif "Building kernel" in output:
                        send_to_esp8266("Building...")

        if process.returncode == 0:
            success_msg = "✅ *Сборка завершена успешно!*"
            await update.message.reply_text(success_msg, parse_mode='Markdown')
            send_to_esp8266("Build Success")
            
            with open(log_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=InputFile(f, filename=log_filename),
                    caption="Лог успешной сборки"
                )
        else:
            error_msg = "❌ *Сборка завершилась с ошибкой!*"
            await update.message.reply_text(error_msg, parse_mode='Markdown')
            send_to_esp8266("Build Failed")
            
            with open(log_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=InputFile(f, filename=log_filename),
                    caption="Лог ошибки сборки"
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
        cleanup_old_logs()

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
    
    logger.info("Bot starting...")
    send_to_esp8266("Bot Starting")
    
    application.run_polling()

if __name__ == "__main__":
    import sys
    main()
