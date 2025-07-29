#!/bin/bash

# Скрипт для запуска Kernel Builder Bot в автономном режиме

echo "🔧 Kernel Builder Bot - Автономный режим"
echo "========================================"

# Проверяем наличие .env файла
if [ ! -f ".env" ]; then
    echo "❌ Файл .env не найден!"
    echo "Создайте файл .env на основе env_example.txt:"
    echo "cp env_example.txt .env"
    echo "И настройте BOT_TOKEN и CHAT_ID"
    exit 1
fi

# Проверяем наличие Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден!"
    echo "Установите Python3 и зависимости:"
    echo "pip install python-telegram-bot python-dotenv requests psutil"
    exit 1
fi

# Проверяем зависимости
echo "📦 Проверка зависимостей..."
python3 -c "import telegram, dotenv, requests, psutil" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ Не все зависимости установлены!"
    echo "Установите зависимости:"
    echo "pip install python-telegram-bot python-dotenv requests psutil"
    exit 1
fi

echo "✅ Зависимости установлены"

# Создаем необходимые директории
mkdir -p logs zips

echo "🚀 Запуск бота..."
echo "Для остановки нажмите Ctrl+C"
echo ""

# Запускаем бота
python3 bot.py 