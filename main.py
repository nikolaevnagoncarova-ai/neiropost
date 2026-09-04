import os
import sqlite3
import logging
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import LabeledPrice, PreCheckoutQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from openai import AsyncOpenAI

# === НАСТРОЙКИ ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "токен_от_botfather")
PAYMENT_TOKEN = os.getenv("PAYMENT_TOKEN", "токен_платежки_от_botfather")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "ключ_openai")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://твое-название.onrender.com")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# === СОСТОЯНИЯ (FSM) ===
class ChannelSetup(StatesGroup):
    waiting_for_channel = State()

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect('smm_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, free_trial INTEGER DEFAULT 1, sub_end TEXT, channel_id TEXT)''')
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect('smm_bot.db')
    c = conn.cursor()
    c.execute("SELECT free_trial, sub_end, channel_id FROM users WHERE user_id = ?", (user_id,))
    res = c.fetchone()
    if not res:
        c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        res = (1, None, None)
    conn.close()
    return res

def use_trial(user_id):
    conn = sqlite3.connect('smm_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET free_trial = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def add_sub(user_id, days=30):
    sub_end = (datetime.now() + timedelta(days=days)).isoformat()
    conn = sqlite3.connect('smm_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET sub_end = ? WHERE user_id = ?", (sub_end, user_id))
    conn.commit()
    conn.close()

def set_channel(user_id, channel_id):
    conn = sqlite3.connect('smm_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET channel_id = ? WHERE user_id = ?", (str(channel_id), user_id))
    conn.commit()
    conn.close()

def check_access(user_id):
    user_data = get_user(user_id)
    free_trial, sub_end = user_data[0], user_data[1]
    if free_trial > 0:
        return "trial"
    if sub_end:
        end_date = datetime.fromisoformat(sub_end)
        if datetime.now() < end_date:
            return "sub"
    return "none"

init_db()

# === ЛОГИКА БОТА ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    text = (
        "Привет! Я твой личный ИИ-редактор.\n\n"
        "Отправь мне голосовое сообщение, и я превращу его в структурированный текст для канала.\n\n"
        "🔗 Привязать свой канал: /channel\n"
        "💳 Подписка на 30 дней: /buy\n"
        "🎁 У тебя есть 1 бесплатный пост."
    )
    await message.answer(text)

# --- Привязка канала ---
@dp.message(Command("channel"))
async def cmd_channel(message: types.Message, state: FSMContext):
    await message.answer(
        "Чтобы я мог публиковать посты, сделай 2 шага:\n"
        "1. Добавь меня в администраторы своего канала (с правом публикации).\n"
        "2. Перешли сюда любое сообщение из этого канала."
    )
    await state.set_state(ChannelSetup.waiting_for_channel)

@dp.message(ChannelSetup.waiting_for_channel)
async def process_channel_forward(message: types.Message, state: FSMContext):
    # Проверяем, переслано ли сообщение из канала
    if message.forward_origin and message.forward_origin.type == "channel":
        channel_id = message.forward_origin.chat.id
        channel_title = message.forward_origin.chat.title
        set_channel(message.from_user.id, channel_id)
        await message.answer(f"✅ Канал «{channel_title}» успешно привязан! Теперь под сгенерированными постами появится кнопка публикации.")
        await state.clear()
    else:
        await message.answer("Это не похоже на сообщение из канала. Убедись, что ты пересылаешь пост именно из канала, а не из личной переписки. Попробуй еще раз.")

# --- Оплата ---
@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    prices = [LabeledPrice(label="Подписка на 1 месяц", amount=20000)] 
    await bot.send_invoice(
        chat_id=message.chat.id,
        title="SMM Ассистент",
        description="Безлимитная генерация постов на 30 дней",
        payload="sub_1_month",
        provider_token=PAYMENT_TOKEN,
        currency="RUB",
        prices=prices,
    )

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_payment(message: types.Message):
    add_sub(message.from_user.id)
    await message.answer("🎉 Оплата прошла успешно! Подписка активирована на 30 дней.")

# --- Обработка аудио ---
@dp.message(F.voice)
async def handle_voice(message: types.Message):
    user_id = message.from_user.id
    access = check_access(user_id)
    
    if access == "none":
        await message.answer("Лимит исчерпан. Оформи подписку командой /buy 💳")
        return

    wait_msg = await message.answer("Слушаю аудио, собираю мысли... ⏳")
    file_path = f"{message.voice.file_id}.ogg"
    
    try:
        file = await bot.get_file(message.voice.file_id)
        await bot.download_file(file.file_path, file_path)

        with open(file_path, "rb") as audio_file:
            transcription = await openai_client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file
            )
        
        # Улучшенный и строгий промпт
        prompt = (
            "Ты строгий и профессиональный коммерческий редактор. Твоя задача — превратить грязную аудио-расшифровку в чистый пост.\n"
            "Правила, которые нельзя нарушать:\n"
            "1. Удали весь словесный мусор (эканья, заикания, повторы, слова-паразиты).\n"
            "2. Выдели главную мысль в сильный заголовок.\n"
            "3. Разбей текст на короткие абзацы (максимум 3-4 предложения в каждом) для удобства чтения с телефона.\n"
            "4. Сохрани авторскую тональность: если исходник дружелюбный — оставь дружелюбным, если строгий — сделай строгим.\n"
            "5. Используй не более 2-3 уместных эмодзи на весь текст. Никакого «вырвиглазного» стиля.\n"
            "6. В ответе выдай ТОЛЬКО готовый текст поста без приветствий и твоих комментариев.\n\n"
            f"Текст для обработки: {transcription.text}"
        )
        
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.4, # Снижаем фантазию нейросети для большей точности
            messages=[{"role": "user", "content": prompt}]
        )
        final_post = response.choices[0].message.content

        # Добавляем примечание о триале, если нужно
        if access == "trial":
            use_trial(user_id)
            final_post += "\n\n_🔔 Это был бесплатный пост. Для безлимита: /buy_"

        # Создаем кнопку публикации, если канал привязан
        user_data = get_user(user_id)
        keyboard = None
        if user_data[2]: # Если есть channel_id
            kb = [[InlineKeyboardButton(text="📢 Опубликовать в канал", callback_data="publish")]]
            keyboard = InlineKeyboardMarkup(inline_keyboard=kb)

        await wait_msg.edit_text(final_post, reply_markup=keyboard)

    except Exception as e:
        logging.error(f"Ошибка обработки: {e}")
        await wait_msg.edit_text("Произошла ошибка при обработке. Попробуй отправить аудио покороче.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

# --- Публикация в канал ---
@dp.callback_query(F.data == "publish")
async def process_publish(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_data = get_user(user_id)
    channel_id = user_data[2]
    
    if not channel_id:
        await callback.answer("Канал не найден. Привяжи его командой /channel", show_alert=True)
        return
        
    try:
        # Отправляем текст самого сообщения в канал
        post_text = callback.message.text
        # Очищаем приписку про бесплатный пост перед отправкой
        if "_🔔 Это был бесплатный пост" in post_text:
            post_text = post_text.split("\n\n_🔔 Это был бесплатный пост")[0]
            
        await bot.send_message(chat_id=channel_id, text=post_text)
        
        # Убираем кнопку под исходным сообщением
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("✅ Успешно опубликовано!", show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка публикации: {e}")
        await callback.answer("❌ Ошибка. Проверь, что бот назначен администратором в канале.", show_alert=True)

# === ЗАПУСК ===
async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)

dp.startup.register(on_startup)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/")
    setup_application(app, dp, bot=bot)
    port = int(os.environ.get("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=port)
