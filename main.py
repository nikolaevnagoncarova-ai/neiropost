import os
import logging
import sys
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN or not GROQ_API_KEY or not WEBHOOK_URL:
    logging.error("❌ Не заданы обязательные переменные окружения!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
openai_client = AsyncOpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

class ChannelStates(StatesGroup):
    waiting_for_channel = State()

users_db = {}

def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile"),
            InlineKeyboardButton(text="📢 Канал", callback_data="menu_channel")
        ],
        [
            InlineKeyboardButton(text="⭐ Избранное", callback_data="menu_saved"),
            InlineKeyboardButton(text="📜 История", callback_data="menu_history")
        ],
        [
            InlineKeyboardButton(text="💳 Подписка", callback_data="menu_buy")
        ]
    ])

def get_post_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💾 В избранное", callback_data="action_save"),
            InlineKeyboardButton(text="📢 Опубликовать", callback_data="action_publish")
        ],
        [
            InlineKeyboardButton(text="🎭 Сделать смешнее", callback_data="action_funny"),
            InlineKeyboardButton(text="👔 Строгий стиль", callback_data="action_formal")
        ],
        [
            InlineKeyboardButton(text="🎨 Идея для картинки", callback_data="action_image_prompt")
        ],
        [
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu_home")
        ]
    ])

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="profile", description="Мой профиль"),
        BotCommand(command="channel", description="Привязать канал"),
        BotCommand(command="buy", description="Купить подписку")
    ]
    await bot.set_my_commands(commands)

def get_user(user_id):
    if user_id not in users_db:
        users_db[user_id] = {
            "posts_left": 1, # Теперь ровно 1 бесплатный пост
            "is_vip": False,
            "channel": None,
            "saved_posts": [],
            "history_posts": [],
            "last_generated_text": "" # Для переписывания
        }
    return users_db[user_id]

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    get_user(message.from_user.id)
    text = (
        "✨ <b>Добро пожаловать в ИИ-Редактор Pro!</b>\n\n"
        "🎙 <b>Опишите голосовым любые мысли</b>, а я превращу их в шикарный пост.\n\n"
        "Выберите нужный раздел в меню ниже 👇"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id)
    status = "👑 VIP (Безлимит)" if user["is_vip"] else "⏳ Базовый статус"
    channel_name = user["channel"] if user["channel"] else "Не привязан"
    text = (
        f"<b>👤 Личный кабинет</b>\n\n"
        f"• <b>Статус:</b> {status}\n"
        f"• <b>Доступно генераций:</b> {user['posts_left']}\n"
        f"• <b>Канал:</b> {channel_name}\n"
        f"• <b>Сохранено постов:</b> {len(user['saved_posts'])}\n\n"
        f"<i>Запишите голосовое сообщение, чтобы создать контент.</i>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())

@dp.message(Command("channel"))
async def cmd_channel(message: types.Message, state: FSMContext):
    await state.set_state(ChannelStates.waiting_for_channel)
    await message.answer(
        "📢 <b>Привязка канала:</b>\n\n"
        "1. Добавьте этого бота в администраторы канала.\n"
        "2. Перешлите сюда любое сообщение из него или отправьте <code>@username</code>.",
        parse_mode="HTML"
    )

@dp.message(ChannelStates.waiting_for_channel)
async def process_channel_input(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if message.forward_origin and message.forward_origin.type == "channel":
        target = f"@{message.forward_origin.chat.username}" if message.forward_origin.chat.username else str(message.forward_origin.chat.id)
        user["channel"] = target
        await state.clear()
        await message.answer(f"✅ Канал привязан!", reply_markup=get_main_keyboard())
    elif message.text and message.text.startswith("@"):
        user["channel"] = message.text.strip()
        await state.clear()
        await message.answer(f"✅ Канал <b>{user['channel']}</b> сохранен!", parse_mode="HTML", reply_markup=get_main_keyboard())

@dp.callback_query(F.data.startswith("menu_"))
async def menu_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user = get_user(callback.from_user.id)
    data = callback.data
    
    if data == "menu_profile":
        status = "👑 VIP" if user["is_vip"] else "⏳ Базовый"
        text = f"<b>👤 Кабинет</b>\n\n• <b>Статус:</b> {status}\n• <b>Генераций:</b> {user['posts_left']}\n• <b>Канал:</b> {user['channel'] or 'Нет'}"
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_keyboard())
    elif data == "menu_channel":
        await state.set_state(ChannelStates.waiting_for_channel)
        await callback.message.answer("📢 Отправьте @username канала.")
    elif data == "menu_buy":
        await callback.message.answer("💳 Чтобы снять лимиты, оплатите подписку (Интеграция скоро).")
    elif data == "menu_home":
        await callback.message.edit_text("✨ <b>ИИ-Редактор Pro</b>\nЖду ваше голосовое сообщение!", parse_mode="HTML", reply_markup=get_main_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("action_"))
async def action_handler(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    post_text = user.get("last_generated_text", callback.message.text)
    
    if callback.data == "action_save":
        if post_text not in user["saved_posts"]:
            user["saved_posts"].append(post_text)
            await callback.answer("✅ Успешно сохранено!", show_alert=True)
        else:
            await callback.answer("ℹ️ Уже в избранном.", show_alert=True)
            
    elif callback.data == "action_publish":
        if not user["channel"]:
            await callback.answer("❌ Сначала привяжите канал!", show_alert=True)
            return
        try:
            await bot.send_message(chat_id=user["channel"], text=post_text, parse_mode="HTML")
            await callback.answer("✅ Опубликовано!", show_alert=True)
        except Exception:
            await callback.answer("❌ Ошибка публикации. Бот админ?", show_alert=True)

    elif callback.data in ["action_funny", "action_formal"]:
        await callback.message.edit_text("🔄 <i>Переписываю текст...</i>", parse_mode="HTML")
        style = "максимально смешным, ироничным и фановым" if callback.data == "action_funny" else "строгим, экспертным и официально-деловым"
        
        prompt = f"Перепиши этот пост, сделав его {style}. Сохрани HTML-разметку (<b>, <i>, <code>) и суть, не используй <br>.\n\nТекст:\n{post_text}"
        try:
            resp = await openai_client.chat.completions.create(model="openai/gpt-oss-20b", messages=[{"role": "user", "content": prompt}])
            new_text = resp.choices[0].message.content.strip()
            user["last_generated_text"] = new_text
            await callback.message.edit_text(new_text, parse_mode="HTML", reply_markup=get_post_keyboard())
        except Exception:
            await callback.message.edit_text(post_text, parse_mode="HTML", reply_markup=get_post_keyboard())
            await callback.answer("❌ Ошибка генерации", show_alert=True)

    elif callback.data == "action_image_prompt":
        await callback.message.answer("🎨 <i>Анализирую текст и создаю промпт...</i>", parse_mode="HTML")
        prompt = f"Напиши один идеальный промпт на английском языке для Midjourney/DALL-E, чтобы сгенерировать крутую иллюстрацию к этому посту. Только сам промпт, без лишних слов.\n\nПост:\n{post_text}"
        try:
            resp = await openai_client.chat.completions.create(model="openai/gpt-oss-20b", messages=[{"role": "user", "content": prompt}])
            img_prompt = resp.choices[0].message.content.strip()
            await callback.message.answer(f"🖼 <b>Промпт для генерации картинки:</b>\n\n<code>{img_prompt}</code>", parse_mode="HTML")
        except Exception:
            await callback.answer("❌ Ошибка генерации промпта", show_alert=True)
    
    await callback.answer()

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    user = get_user(message.from_user.id)
    
    # Проверка лимитов
    if not user["is_vip"] and user["posts_left"] <= 0:
        await message.answer("⚠️ <b>У вас закончились бесплатные посты (Доступно: 0).</b>\nДля продолжения приобретите подписку.", parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    processing_msg = await message.answer("🎙 <i>Слушаю аудио и создаю шедевр... ✨</i>", parse_mode="HTML")
    
    voice = message.voice
    file_info = await bot.get_file(voice.file_id)
    audio_file_path = f"voice_{message.from_user.id}.ogg"
    
    try:
        await bot.download_file(file_info.file_path, audio_file_path)
        with open(audio_file_path, "rb") as audio_file:
            transcript = await openai_client.audio.transcriptions.create(model="whisper-large-v3", file=audio_file)
        
        raw_text = transcript.text.strip()
        if not raw_text:
            await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
            await message.answer("⚠️ Речь не распознана.")
            return

        # Прокачанный промт элитного копирайтера
        prompt = (
            "Ты — элитный копирайтер и контент-мейкер для Telegram. Твоя цель — сделать безупречный пост из мыслей пользователя.\n"
            "ПРАВИЛА:\n"
            "1. ДЛИНА: Слушай указания! Просят коротко — делай 3 строки. Просят лонгрид — расписывай глубоко.\n"
            "2. СТРУКТУРА: Если формат позволяет, сделай цепляющий заголовок (жирным), ритмичную основную часть и вовлекающую концовку (вопрос/призыв).\n"
            "3. УЧЕТ ДЕТАЛЕЙ: Строго соблюдай все факты и требования из аудио.\n"
            "4. РАЗМЕТКА: ТОЛЬКО <b>, <i>, <code>. ЗАПРЕЩЕН тег <br>! Переносы строк только через обычный Enter.\n"
            "5. ЭМОДЗИ: Расставь их со вкусом, стильно, не перегружая.\n"
            "6. СТИЛЬ: Никаких избитых клише («В современном мире», «Важно отметить»). Пиши ярко, современно, авторским языком.\n\n"
            f"Мысли из аудио:\n{raw_text}"
        )
        
        response = await openai_client.chat.completions.create(model="openai/gpt-oss-20b", temperature=0.7, messages=[{"role": "user", "content": prompt}])
        final_text = response.choices[0].message.content.strip().replace("<br>", "").replace("<br/>", "")
        
        # Списываем лимит
        if not user["is_vip"]:
            user["posts_left"] -= 1

        user["history_posts"].append(final_text)
        user["last_generated_text"] = final_text
        
        await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        await message.answer(final_text, parse_mode="HTML", reply_markup=get_post_keyboard())
        
    except Exception as e:
        logging.error(f"❌ Ошибка: {e}")
        try: await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        except: pass
        await message.answer("❌ Произошла ошибка при обработке.")
    finally:
        if os.path.exists(audio_file_path):
            os.remove(audio_file_path)

# Эндпоинт-заглушка для UptimeRobot, чтобы бот не спал на Render
async def ping_handler(request):
    return web.Response(text="Bot is awake!")

async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)
    await set_bot_commands(bot)
    logging.info("🚀 Бот успешно запущен!")

if __name__ == "__main__":
    app = web.Application()
    app.router.add_get('/ping', ping_handler) # Тот самый маршрут для анти-сна
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/")
    setup_application(app, dp, bot=bot)
    dp.startup.register(on_startup)
    
    port = int(os.environ.get("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=port)
