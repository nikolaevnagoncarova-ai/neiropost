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

def get_main_keyword():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile"),
            InlineKeyboardButton(text="📢 Канал", callback_data="menu_channel")
        ],
        [
            InlineKeyboardButton(text="⭐ Избранное", callback_data="menu_saved"),
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
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu_home")
        ]
    ])

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="profile", description="Мой профиль"),
        BotCommand(command="channel", description="Привязать канал"),
        BotCommand(command="saved", description="Избранные посты"),
        BotCommand(command="buy", description="Купить подписку")
    ]
    await bot.set_my_commands(commands)

def get_user(user_id):
    if user_id not in users_db:
        users_db[user_id] = {
            "posts_left": 3,
            "is_vip": False,
            "channel": None,
            "saved_posts": []
        }
    return users_db[user_id]

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    get_user(message.from_user.id)
    text = (
        "✨ <b>Добро пожаловать в ИИ-Редактор постов!</b>\n\n"
        "🎙 <b>Опишите голосовым, о чем должен быть пост</b>, а я превращу ваши мысли в профессиональную публикацию.\n\n"
        "Выберите нужный раздел в меню ниже 👇"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyword())

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
        f"<i>Запишите голосовое сообщение, чтобы создать новый контент.</i>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyword())

@dp.message(Command("channel"))
async def cmd_channel(message: types.Message, state: FSMContext):
    await state.set_state(ChannelStates.waiting_for_channel)
    await message.answer(
        "📢 <b>Привязка канала:</b>\n\n"
        "1. Добавьте этого бота в администраторы вашего канала (с правом публикации).\n"
        "2. Перешлите сюда любое сообщение из вашего канала ИЛИ отправьте его юзернейм (например, <code>@my_channel</code>).",
        parse_mode="HTML"
    )

@dp.message(ChannelStates.waiting_for_channel)
async def process_channel_input(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    
    if message.forward_origin and message.forward_origin.type == "channel":
        channel_title = message.forward_origin.chat.title
        channel_username = message.forward_origin.chat.username
        target = f"@{channel_username}" if channel_username else str(message.forward_origin.chat.id)
        user["channel"] = target
        await state.clear()
        await message.answer(f"✅ Канал <b>{channel_title}</b> ({target}) успешно привязан!", parse_mode="HTML", reply_markup=get_main_keyword())
    elif message.text and message.text.startswith("@"):
        user["channel"] = message.text.strip()
        await state.clear()
        await message.answer(f"✅ Канал <b>{user['channel']}</b> успешно сохранен! Убедитесь, что бот добавлен в администраторы.", parse_mode="HTML", reply_markup=get_main_keyword())
    else:
        await message.answer("⚠️ Не удалось распознать канал. Перешлите сообщение из канала или отправьте юзернейм в формате <code>@channel</code>.", parse_mode="HTML")

@dp.message(Command("saved"))
async def cmd_saved(message: types.Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id)
    if not user["saved_posts"]:
        await message.answer("⭐ У вас пока нет сохраненных постов.", reply_markup=get_main_keyword())
        return
    text = "⭐ <b>Ваши избранные посты:</b>\n\n" + "\n\n➖➖➖➖➖➖\n\n".join(user["saved_posts"][-5:])
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyword())

@dp.message(Command("buy"))
async def cmd_buy(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("💳 Модуль оплаты находится на финальной стадии интеграции.", reply_markup=get_main_keyword())

@dp.callback_query(F.data.startswith("menu_"))
async def menu_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    user = get_user(user_id)
    data = callback.data
    
    if data == "menu_profile":
        status = "👑 VIP (Безлимит)" if user["is_vip"] else "⏳ Базовый статус"
        channel_name = user["channel"] if user["channel"] else "Не привязан"
        text = (
            f"<b>👤 Личный кабинет</b>\n\n"
            f"• <b>Статус:</b> {status}\n"
            f"• <b>Доступно генераций:</b> {user['posts_left']}\n"
            f"• <b>Канал:</b> {channel_name}\n"
            f"• <b>Сохранено постов:</b> {len(user['saved_posts'])}"
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_keyword())
    elif data == "menu_channel":
        await state.set_state(ChannelStates.waiting_for_channel)
        await callback.message.answer("📢 Добавьте бота в админы канала и перешлите сюда любое сообщение из него или отправьте @username.")
    elif data == "menu_saved":
        if not user["saved_posts"]:
            await callback.answer("У вас пока нет сохраненных постов!", show_alert=True)
            return
        text = "⭐ <b>Ваши избранные посты:</b>\n\n" + "\n\n➖➖➖➖➖➖\n\n".join(user["saved_posts"][-5:])
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_keyword())
    elif data == "menu_buy":
        await callback.message.answer("💳 Оплата временно недоступна.")
    elif data == "menu_home":
        text = (
            "✨ <b>ИИ-Редактор постов</b>\n\n"
            "🎙 Опишите голосовым, о чем должен быть пост, и получите готовый текст."
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_keyword())
        
    await callback.answer()

@dp.callback_query(F.data.startswith("action_"))
async def action_handler(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if callback.data == "action_save":
        post_text = callback.message.text
        if post_text not in user["saved_posts"]:
            user["saved_posts"].append(post_text)
            await callback.answer("✅ Успешно сохранено!", show_alert=True)
        else:
            await callback.answer("ℹ️ Пост уже в избранном.", show_alert=True)
            
    elif callback.data == "action_publish":
        if not user["channel"]:
            await callback.answer("❌ Сначала привяжите канал через меню или команду /channel!", show_alert=True)
            return
        
        post_text = callback.message.text
        try:
            await bot.send_message(chat_id=user["channel"], text=post_text, parse_mode="HTML")
            await callback.answer("✅ Пост успешно опубликован в канале!", show_alert=True)
        except Exception as e:
            logging.error(f"Ошибка публикации в канал: {e}")
            await callback.answer(f"❌ Ошибка публикации. Убедитесь, что бот админ канала.", show_alert=True)

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    processing_msg = await message.answer("🎙 <i>Слушаю аудио... Обрабатываю ваш запрос про пост...</i>", parse_mode="HTML")
    
    voice = message.voice
    file_info = await bot.get_file(voice.file_id)
    audio_file_path = f"voice_{message.from_user.id}.ogg"
    
    try:
        await bot.download_file(file_info.file_path, audio_file_path)
        
        with open(audio_file_path, "rb") as audio_file:
            transcript = await openai_client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=audio_file
            )
        
        raw_text = transcript.text.strip()
        if not raw_text:
            await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
            await message.answer("⚠️ Не удалось разобрать речь. Запишите голосовое еще раз.")
            return

        prompt = (
            "Преврати этот разговорный текст в лаконичный, вовлекающий пост для Telegram-канала. "
            "Сделай его средней длины: не слишком длинным, но емким и информативным. "
            "ОБЯЗАТЕЛЬНО используй HTML-теги форматирования для Telegram: <b>жирный текст</b>, <i>курсив</i>, "
            "цитаты через тег <blockquote>текст цитаты</blockquote>. "
            "Добавь сильный заголовок, разбей текст на короткие абзацы и добавь уместные эмодзи. "
            "Выдай ТОЛЬКО готовый текст поста без лишних вступительных фраз и без кавычек в начале и конце:\n\n" + raw_text
        )
        
        response = await openai_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            temperature=0.4,
            messages=[{"role": "user", "content": prompt}]
        )
        
        final_text = response.choices[0].message.content.strip()
        
        await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        # Отправляем чистый текст постов без вводной фразы «Готовый пост:»
        await message.answer(final_text, parse_mode="HTML", reply_markup=get_post_keyboard())
        
    except Exception as e:
        logging.error(f"❌ Ошибка обработки: {e}")
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        except:
            pass
        await message.answer(f"❌ Ошибка генерации: {str(e)[:100]}")
    finally:
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
