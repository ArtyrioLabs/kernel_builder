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
from git import Repo

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
ESP_ENABLED = os.getenv("ESP_ENABLED", "false").lower() == "true"  # Новый параметр
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
    """Отправка сообщения на ESP8266 (опционально)"""
    if not ESP_ENABLED or not ESP_IP:
        logger.info(f"ESP8266 disabled, message: {message}")
        return True
    
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

def check_esp8266_status():
    """Проверка статуса ESP8266"""
    if not ESP_ENABLED or not ESP_IP:
        return False, "ESP8266 отключен"
    
    try:
        response = requests.get(f"http://{ESP_IP}", timeout=3)
        return response.ok, "🟢 Online" if response.ok else "🔴 Offline"
    except Exception as e:
        return False, f"🔴 Offline ({str(e)})"

async def setup_commands(application):
    commands = [
        BotCommand("start", "Запустить бота"),
        BotCommand("build", "Запустить сборку ядра"),
        BotCommand("status", "Проверить статус системы"),
        BotCommand("logs", "Получить список логов"),
        BotCommand("clean", "Очистить старые логи"),
        BotCommand("help", "Показать справку"),
        BotCommand("stopbuild", "Остановить сборку"),
        BotCommand("lastzip", "Получить последний архив прошивки"),
        BotCommand("buildinfo", "Информация о последней сборке"),
        BotCommand("patchlist", "Список патчей для сборки"),
    ]
    
    # Добавляем команды ESP8266 только если он включен
    if ESP_ENABLED:
        esp_commands = [
            BotCommand("lsd", "Список файлов на SD-карте ESP8266"),
            BotCommand("getfile", "Скачать файл с SD-карты ESP8266"),
            BotCommand("deletefile", "Удалить файл на SD-карте ESP8266"),
            BotCommand("uploadfile", "Загрузить файл на SD-карту ESP8266"),
            BotCommand("clearlog", "Очистить лог на SD-карте ESP8266"),
            BotCommand("sdinfo", "Информация о SD-карте ESP8266"),
            BotCommand("rebootesp", "Перезагрузить ESP8266"),
            BotCommand("webui", "Веб-интерфейс ESP8266"),
        ]
        commands.extend(esp_commands)
    
    await application.bot.set_my_commands(commands)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    esp_status = "🟢 Включен" if ESP_ENABLED else "🔴 Отключен"
    welcome_msg = (
        "🔧 *Build Monitor Bot*\n\n"
        f"*ESP8266:* {esp_status}\n\n"
        "Доступные команды:\n"
        "/build - Запустить сборку ядра\n"
        "/status - Проверить статус системы\n"
        "/logs - Получить список логов\n"
        "/clean - Очистить старые логи\n"
        "/stopbuild - Остановить сборку\n"
        "/lastzip - Получить последний архив прошивки\n"
        "/buildinfo - Информация о последней сборке\n"
        "/patchlist - Список патчей для сборки\n"
        "/help - Показать справку"
    )
    
    if ESP_ENABLED:
        welcome_msg += "\n\n*Команды ESP8266:*\n"
        welcome_msg += "/lsd - Список файлов на SD-карте\n"
        welcome_msg += "/getfile <имя> - Скачать файл с SD-карты\n"
        welcome_msg += "/deletefile <имя> - Удалить файл на SD-карте\n"
        welcome_msg += "/uploadfile - Загрузить файл на SD-карту\n"
        welcome_msg += "/clearlog - Очистить лог на SD-карте\n"
        welcome_msg += "/sdinfo - Информация о SD-карте\n"
        welcome_msg += "/rebootesp - Перезагрузить ESP8266\n"
        welcome_msg += "/webui - Веб-интерфейс ESP8266"
    
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')
    send_to_esp8266("Bot Ready")

build_process = None

async def build_kernel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global build_process
    user = update.effective_user
    repo = Repo(PROJECT_DIR)
    commit = repo.head.commit.hexsha[:8]
    branch = repo.active_branch.name
    build_start = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"Build requested by {user.full_name} (ID: {user.id}), git: {branch} {commit}, time: {build_start}")
    await update.message.reply_text(f"⚙️ *Запускаю сборку ядра...*\nGit: `{branch}` `{commit}`\nВремя: {build_start}", parse_mode='Markdown')
    send_to_esp8266("Build Started")
    log_filename = f"build_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_path = os.path.join(LOG_DIR, log_filename)
    kernel_name = None
    image_path = None
    try:
        with open(log_path, 'w') as log_file:
            log_file.write(f"Build started by: {user.full_name} (ID: {user.id})\n")
            log_file.write(f"Git branch: {branch}\nGit commit: {commit}\nStart time: {build_start}\n\n")
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
        build_end = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(log_path, 'a') as log_file:
            log_file.write(f"\nBuild finished at: {build_end}\n")
        if build_process.returncode == 0:
            await update.message.reply_text(f"✅ *Сборка завершена успешно!*\nGit: `{branch}` `{commit}`\nВремя: {build_end}", parse_mode='Markdown')
            send_to_esp8266("Build Success")
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
            await update.message.reply_text(f"❌ *Сборка завершилась с ошибкой!*\nGit: `{branch}` `{commit}`\nВремя: {build_end}", parse_mode='Markdown')
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
        if not os.path.isfile(zip_path):
            return f"❌ Ошибка: zip-файл не создан ({zip_name})"
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
        esp_online, esp_status = check_esp8266_status()
        
        cpu_usage = psutil.cpu_percent()
        mem = psutil.virtual_memory()
        uptime = subprocess.check_output(["uptime"]).decode().strip()
        
        status_msg = (
            f"📊 *Статус системы*\n\n"
            f"*ESP8266:* {esp_status}\n"
            f"*CPU:* {cpu_usage}%\n"
            f"*Memory:* {mem.percent}% used\n"
            f"*Uptime:* {uptime.split(',')[0]}"
        )
        
        # Добавляем информацию о SD-карте только если ESP8266 включен и доступен
        if ESP_ENABLED and esp_online:
            try:
                resp = requests.get(f"http://{ESP_IP}/sdinfo", timeout=3)
                if resp.ok:
                    log_size = None
                    for line in resp.text.split("\n"):
                        if line.startswith("log_size="):
                            log_size = int(line.split("=",1)[-1])
                    if log_size is not None:
                        status_msg += f"\n*Лог на SD:* {log_size} байт"
            except:
                pass
        
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
        "*/getlog <имя_лога>* - Скачать лог по имени\n"
        "*/clean* - Очистить старые логи\n"
        "*/restart* - Перезапустить бота\n"
        "*/stopbuild* - Остановить сборку\n"
        "*/lastzip* - Получить последний архив прошивки\n"
        "*/buildinfo* - Информация о последней сборке\n"
        "*/patchlist* - Список патчей для сборки\n"
        "*/help* - Эта справка"
    )
    
    if ESP_ENABLED:
        help_text += "\n\n*Команды ESP8266:*\n"
        help_text += "*/lsd* - Список файлов на SD-карте\n"
        help_text += "*/getfile <имя>* - Скачать файл с SD-карты\n"
        help_text += "*/deletefile <имя>* - Удалить файл на SD-карте\n"
        help_text += "*/uploadfile* - Загрузить файл на SD-карту\n"
        help_text += "*/clearlog* - Очистить лог на SD-карте\n"
        help_text += "*/sdinfo* - Информация о SD-карте\n"
        help_text += "*/setlogname <имя>* - Сменить имя файла лога\n"
        help_text += "*/rebootesp* - Перезагрузить ESP8266\n"
        help_text += "*/webui* - Веб-интерфейс ESP8266"
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

# ESP8266 функции (только если ESP включен)
async def getlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ESP_ENABLED:
        await update.message.reply_text("ESP8266 отключен в настройках.")
        return
    
    try:
        url = f"http://{ESP_IP}/log"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            log_text = resp.text
            if not log_text.strip():
                await update.message.reply_text("Лог на SD-карте пуст.")
            elif len(log_text) > 4000:
                with open("log.txt", "w") as f:
                    f.write(log_text)
                with open("log.txt", "rb") as f:
                    await update.message.reply_document(f, filename="log.txt", caption="Лог с SD-карты ESP8266")
            else:
                await update.message.reply_text(f"Лог с SD-карты:\n\n{log_text}")
        else:
            await update.message.reply_text("Ошибка при получении лога с ESP8266.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def lsd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ESP_ENABLED:
        await update.message.reply_text("ESP8266 отключен в настройках.")
        return
    
    try:
        url = f"http://{ESP_IP}/ls"
        resp = requests.get(url, timeout=5)
        if resp.ok:
            await update.message.reply_text(f"Файлы на SD:\n{resp.text}")
        else:
            await update.message.reply_text("Ошибка при получении списка файлов.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def getfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ESP_ENABLED:
        await update.message.reply_text("ESP8266 отключен в настройках.")
        return
    
    if not context.args:
        await update.message.reply_text("Укажи имя файла: /getfile <имя>")
        return
    fname = context.args[0]
    url = f"http://{ESP_IP}/download?file={fname}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.ok:
            with open(fname, "wb") as f:
                f.write(resp.content)
            with open(fname, "rb") as f:
                await update.message.reply_document(f, filename=fname)
        else:
            await update.message.reply_text("Файл не найден на SD.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def deletefile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ESP_ENABLED:
        await update.message.reply_text("ESP8266 отключен в настройках.")
        return
    
    if not context.args:
        await update.message.reply_text("Укажи имя файла: /deletefile <имя>")
        return
    fname = context.args[0]
    url = f"http://{ESP_IP}/delete?file={fname}"
    try:
        resp = requests.get(url, timeout=5)
        if resp.ok:
            await update.message.reply_text(f"Файл {fname} удалён.")
        else:
            await update.message.reply_text("Ошибка при удалении файла.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def uploadfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ESP_ENABLED:
        await update.message.reply_text("ESP8266 отключен в настройках.")
        return
    
    if not update.message.document:
        await update.message.reply_text("Пришли файл для загрузки на SD-карту.")
        return
    file = await update.message.document.get_file()
    fname = update.message.document.file_name
    file_bytes = await file.download_as_bytearray()
    url = f"http://{ESP_IP}/upload"
    try:
        resp = requests.post(url, data=file_bytes, params={"file": fname}, timeout=10)
        if resp.ok:
            await update.message.reply_text(f"Файл {fname} загружен на SD-карту.")
        else:
            await update.message.reply_text("Ошибка при загрузке файла.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def clearlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ESP_ENABLED:
        await update.message.reply_text("ESP8266 отключен в настройках.")
        return
    
    url = f"http://{ESP_IP}/clearlog"
    try:
        resp = requests.get(url, timeout=5)
        if resp.ok:
            await update.message.reply_text("Лог очищен.")
        else:
            await update.message.reply_text("Ошибка при очистке лога.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def sdinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ESP_ENABLED:
        await update.message.reply_text("ESP8266 отключен в настройках.")
        return
    
    url = f"http://{ESP_IP}/sdinfo"
    try:
        resp = requests.get(url, timeout=5)
        if resp.ok:
            await update.message.reply_text(f"SD info:\n{resp.text}")
        else:
            await update.message.reply_text("Ошибка при получении информации о SD.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def setlogname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ESP_ENABLED:
        await update.message.reply_text("ESP8266 отключен в настройках.")
        return
    
    if not context.args:
        await update.message.reply_text("Укажи имя файла: /setlogname <имя>")
        return
    fname = context.args[0]
    url = f"http://{ESP_IP}/setlogname?name={fname}"
    try:
        resp = requests.get(url, timeout=5)
        if resp.ok:
            await update.message.reply_text(f"Имя лога изменено на {fname}.")
        else:
            await update.message.reply_text("Ошибка при смене имени лога.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def rebootesp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ESP_ENABLED:
        await update.message.reply_text("ESP8266 отключен в настройках.")
        return
    
    url = f"http://{ESP_IP}/reboot"
    try:
        resp = requests.get(url, timeout=5)
        if resp.ok:
            await update.message.reply_text("ESP8266 перезагружается.")
        else:
            await update.message.reply_text("Ошибка при перезагрузке ESP.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def webui(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ESP_ENABLED:
        await update.message.reply_text("ESP8266 отключен в настройках.")
        return
    
    await update.message.reply_text(f"Веб-интерфейс ESP8266: http://{ESP_IP}/webui")

async def get_last_zip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получить последний архив прошивки"""
    try:
        zips_dir = os.path.join(PROJECT_DIR, "zips")
        if not os.path.exists(zips_dir):
            await update.message.reply_text("Директория с архивами не найдена.")
            return
        
        zip_files = [f for f in os.listdir(zips_dir) if f.endswith('.zip')]
        if not zip_files:
            await update.message.reply_text("Архивы не найдены.")
            return
        
        # Сортируем по времени создания
        zip_files.sort(key=lambda x: os.path.getctime(os.path.join(zips_dir, x)), reverse=True)
        latest_zip = zip_files[0]
        zip_path = os.path.join(zips_dir, latest_zip)
        
        size_mb = os.path.getsize(zip_path) / (1024*1024)
        created_time = datetime.fromtimestamp(os.path.getctime(zip_path))
        
        caption = f"Последний архив:\nИмя: {latest_zip}\nРазмер: {size_mb:.2f} MB\nСоздан: {created_time.strftime('%Y-%m-%d %H:%M:%S')}"
        
        with open(zip_path, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=InputFile(f, filename=latest_zip),
                caption=caption
            )
    except Exception as e:
        await update.message.reply_text(f"Ошибка при получении архива: {e}")

async def get_build_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получить информацию о последних  сборках"""
    try:
        logs = sorted(os.listdir(LOG_DIR), reverse=True)
        if not logs:
            await update.message.reply_text("Логи сборки не найдены.")
            return
        repo = Repo(PROJECT_DIR)
        commit = repo.head.commit.hexsha[:8]
        branch = repo.active_branch.name
        response = f"\U0001F4CB *Информация о последних сборках*\n\nТекущий git: `{branch}` `{commit}`\n\n"
        for log_name in logs[:3]:
            log_path = os.path.join(LOG_DIR, log_name)
            with open(log_path, 'r') as f:
                lines = f.readlines()
            kernel_name = "Неизвестно"
            build_status = "Неизвестно"
            for line in lines:
                if "Using kernel name:" in line:
                    kernel_name = line.split(":", 1)[-1].strip()
                elif "Kernel image:" in line:
                    build_status = "Успешно"
                elif "Build failed" in line or "error" in line.lower():
                    build_status = "Ошибка"
            created_time = datetime.fromtimestamp(os.path.getctime(log_path))
            build_time = created_time.strftime('%Y-%m-%d %H:%M:%S')
            size_kb = os.path.getsize(log_path) / 1024
            # Поиск zip-архива
            zip_name = None
            zip_size = None
            if kernel_name != "Неизвестно":
                zips_dir = os.path.join(PROJECT_DIR, "zips")
                if os.path.isdir(zips_dir):
                    for f in os.listdir(zips_dir):
                        if kernel_name in f and f.endswith('.zip'):
                            zip_name = f
                            zip_size = os.path.getsize(os.path.join(zips_dir, f)) / 1024 / 1024
                            break
            response += (
                f"*Ядро:* {kernel_name}\n"
                f"*Статус:* {build_status}\n"
                f"*Время:* {build_time}\n"
                f"*Лог:* `{log_name}` ({size_kb:.1f} KB)\n"
            )
            if zip_name:
                response += f"*Архив:* `{zip_name}` ({zip_size:.2f} MB)\n"
            response += "\n"
        await update.message.reply_text(response, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"Ошибка при получении информации о сборках: {e}")

async def list_patches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список патчей для сборки"""
    try:
        patches_dir = os.path.join(PROJECT_DIR, "patches")
        if not os.path.exists(patches_dir):
            await update.message.reply_text("Директория с патчами не найдена.")
            return
        
        patch_files = [f for f in os.listdir(patches_dir) if f.endswith('.patch')]
        if not patch_files:
            await update.message.reply_text("Патчи не найдены.")
            return
        
        # Сортируем по имени
        patch_files.sort()
        
        response = "📝 *Список патчей для сборки:*\n\n"
        for i, patch in enumerate(patch_files[:10], 1):  # Показываем первые 10
            size_kb = os.path.getsize(os.path.join(patches_dir, patch)) / 1024
            response += f"{i}. `{patch}` ({size_kb:.1f} KB)\n"
        
        if len(patch_files) > 10:
            response += f"\n... и еще {len(patch_files) - 10} патчей"
        
        await update.message.reply_text(response, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"Ошибка при получении списка патчей: {e}")

async def getlogfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажи имя лога: /getlog <имя_лога>")
        return
    log_name = context.args[0]
    # Безопасность: только буквы, цифры, -, _, .
    import re
    if not re.match(r'^[\w\-.]+$', log_name):
        await update.message.reply_text("Недопустимое имя файла.")
        return
    log_path = os.path.join(LOG_DIR, log_name)
    if not os.path.isfile(log_path):
        await update.message.reply_text("Лог не найден.")
        return
    try:
        with open(log_path, "rb") as f:
            await update.message.reply_document(f, filename=log_name)
    except Exception as e:
        await update.message.reply_text(f"Ошибка при отправке лога: {e}")

def main():
    application = ApplicationBuilder() \
        .token(BOT_TOKEN) \
        .post_init(setup_commands) \
        .build()
    
    # Основные команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("build", build_kernel))
    application.add_handler(CommandHandler("status", system_status))
    application.add_handler(CommandHandler("logs", list_logs))
    application.add_handler(CommandHandler("clean", clean_logs))
    application.add_handler(CommandHandler("restart", restart_bot))  
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stopbuild", stop_build))
    application.add_handler(CommandHandler("lastzip", get_last_zip))
    application.add_handler(CommandHandler("buildinfo", get_build_info))
    application.add_handler(CommandHandler("patchlist", list_patches))
    application.add_handler(CommandHandler("getlog", getlogfile))
    
    # ESP8266 команды (только если ESP включен)
    if ESP_ENABLED:
        application.add_handler(CommandHandler("getlog", getlog))
        application.add_handler(CommandHandler("lsd", lsd))
        application.add_handler(CommandHandler("getfile", getfile))
        application.add_handler(CommandHandler("deletefile", deletefile))
        application.add_handler(CommandHandler("uploadfile", uploadfile))
        application.add_handler(CommandHandler("clearlog", clearlog))
        application.add_handler(CommandHandler("sdinfo", sdinfo))
        application.add_handler(CommandHandler("setlogname", setlogname))
        application.add_handler(CommandHandler("rebootesp", rebootesp))
        application.add_handler(CommandHandler("webui", webui))
    
    logger.info(f"Bot starting... ESP8266: {'enabled' if ESP_ENABLED else 'disabled'}")
    send_to_esp8266("Bot Starting")
    
    application.run_polling()

if __name__ == "__main__":
    import sys
    main()
