import os
import logging
import sys
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from openai import AsyncOpenAI

# Настройка логирования
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# Получение переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN or not GROQ_API_KEY or not WEBHOOK_URL:
    logging.error("❌ Не заданы обязательные переменные окружения (BOT_TOKEN, GROQ_API_KEY, WEBHOOK_URL)!")
    sys.exit(1)

# Инициализация бота и клиентов
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
openai_client = AsyncOpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

# Простая база данных в памяти (для примера)
user_data = {}

def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="btn_profile"),
            InlineKeyboardButton(text="📢 Канал", callback_data="btn_channel")
        ],
        [
            InlineKeyboardButton(text="💳 Купить подписку", callback_data="btn_buy")
        ]
    ])

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="profile", description="Мой профиль и подписка"),
        BotCommand(command="channel", description="Привязать канал"),
        BotCommand(command="buy", description="Оформить подписку")
    ]
    await bot.set_my_commands(commands)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {"posts_left": 3, "is_vip": False, "channel": "Не привязан"}
    
    text = (
        "👋 <b>Привет! Я твой личный ИИ-редактор.</b>\n\n"
        "🎙 Отправь мне голосовое сообщение, и я мгновенно превращу его "
        "в структурированный, красивый пост с абзацами и эмодзи для твоего Telegram-канала!"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    user_id = message.from_user.id
    data = user_data.get(user_id, {"posts_left": 3, "is_vip": False, "channel": "Не привязан"})
    
    status = "👑 VIP (Безлимит)" if data["is_vip"] else "⏳ Базовый"
    text = (
        f"<b>👤 Твой профиль:</b>\n\n"
        f"• Статус подписки: {status}\n"
        f"• Бесплатные посты: {data['posts_left']}\n"
        f"• Привязанный канал: {data['channel']}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())

@dp.message(Command("channel"))
async def cmd_channel(message: types.Message):
    await message.answer("📢 Отправь мне @username твоего канала (например, <code>@my_channel</code>), чтобы привязать его.", parse_mode="HTML")

@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    await message.answer("💳 Модуль оплаты находится в разработке. Скоро здесь появится возможность оформить VIP-подписку!")

@dp.callback_query(F.data.startswith("btn_"))
async def callback_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    data = user_data.get(user_id, {"posts_left": 3, "is_vip": False, "channel": "Не привязан"})
    
    if callback.data == "btn_profile":
        status = "👑 VIP (Безлимит)" if data["is_vip"] else "⏳ Базовый"
        text = (
            f"<b>👤 Твой профиль:</b>\n\n"
            f"• Статус подписки: {status}\n"
            f"• Бесплатные посты: {data['posts_left']}\n"
            f"• Привязанный канал: {data['channel']}"
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_keyboard())
    elif callback.data == "btn_channel":
        await callback.message.answer("📢 Отправь мне @username твоего канала, чтобы привязать его.")
    elif callback.data == "btn_buy":
        await callback.message.answer("💳 Оплата временно недоступна.")
    
    await callback.answer()

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    processing_msg = await message.answer("🎙 <i>Слушаю голосовое и расшифровываю...</i>", parse_mode="HTML")
    
    voice = message.voice
    file_info = await bot.get_file(voice.file_id)
    file_path = file_info.file_path
    
    audio_file_path = f"voice_{message.from_user.id}.ogg"
    
    try:
        await bot.download_file(file_path, audio_file_path)
        
        # 1. Распознавание речи через Whisper
        with open(audio_file_path, "rb") as audio_file:
            transcript = await openai_client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=audio_file
            )
        
        raw_text = transcript.text
        
        if not raw_text.strip():
            await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
            await message.answer("⚠️ Не удалось разобрать слова в голосовом сообщении. Попробуй записать еще раз четче.")
            return

        # 2. Генерация качественного поста через Llama 3
        prompt = (
            "Преврати этот разговорный текст в красивый, профессиональный и вовлекающий пост для Telegram-канала. "
            "Добавь уместные абзацы, выдели главные мысли и добавь подходящие эмодзи, сохранив при этом исходный смысл:\n\n" + raw_text
        )
        
        response = await openai_client.chat.completions.create(
            model="llama3-70b-8192",
            temperature=0.4,
            messages=[{"role": "user", "content": prompt}]
        )
        
        final_text = response.choices[0].message.content
        
        # Удаляем сообщение о загрузке и отправляем результат
        await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        await message.answer(f"✨ <b>Готовый пост для канала:</b>\n\n{final_text}", parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logging.error(f"❌ Ошибка обработки: {e}")
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        except:
            pass
        await message.answer("❌ Произошла ошибка при обработке запроса. Попробуй отправить аудио немного покороче.")
    finally:
        # Гарантированное удаление временного файла
        if os.path.exists(audio_file_path):
            os.remove(audio_file_path)

async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)
    await set_bot_commands(bot)
    logging.info("🚀 Бот успешно запущен на вебхуках!")

if __name__ == "__main__":
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/")
    setup_application(app, dp, bot=bot)
    dp.startup.register(on_startup)
    
    port = int(os.environ.get("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=port)
