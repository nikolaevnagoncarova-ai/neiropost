import os
import logging
import sys
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
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

# Продвинутая база данных в памяти для пользователей и их постов
users_db = {}

def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile"),
            InlineKeyboardButton(text="📢 Канал", callback_data="menu_channel")
        ],
        [
            InlineKeyboardButton(text="⭐ Избранные посты", callback_data="menu_saved"),
            InlineKeyboardButton(text="💳 Подписка", callback_data="menu_buy")
        ]
    ])

def get_post_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💾 Сохранить в избранное", callback_data="action_save"),
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
            "channel": "Не привязан",
            "saved_posts": []
        }
    return users_db[user_id]

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    get_user(message.from_user.id)
    text = (
        "✨ <b>Добро пожаловать в ИИ-Редактор постов!</b>\n\n"
        "🎙 <b>Опишите голосовым, о чем должен быть пост</b>, а я превращу ваши мысли в профессиональную, структурированную публикацию с идеальными абзацами и эмодзи.\n\n"
        "Выберите нужный раздел в меню ниже 👇"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    user = get_user(message.from_user.id)
    status = "👑 VIP (Безлимит)" if user["is_vip"] else "⏳ Базовый статус"
    text = (
        f"<b>👤 Личный кабинет</b>\n\n"
        f"• <b>Статус:</b> {status}\n"
        f"• <b>Доступно генераций:</b> {user['posts_left']}\n"
        f"• <b>Канал:</b> {user['channel']}\n"
        f"• <b>Сохранено постов:</b> {len(user['saved_posts'])}\n\n"
        f"<i>Запишите голосовое со словами «Опишите о чем должен быть пост», чтобы создать новый контент.</i>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())

@dp.message(Command("channel"))
async def cmd_channel(message: types.Message):
    await message.answer("📢 Отправьте мне @username вашего канала (например, <code>@my_channel</code>), чтобы привязать его для публикаций.", parse_mode="HTML")

@dp.message(Command("saved"))
async def cmd_saved(message: types.Message):
    user = get_user(message.from_user.id)
    if not user["saved_posts"]:
        await message.answer("⭐ У вас пока нет сохраненных постов. Нажмите кнопку «Сохранить в избранное» под любым сгенерированным текстом!", reply_markup=get_main_keyboard())
        return
    
    text = "⭐ <b>Ваши избранные посты:</b>\n\n" + "\n\n➖➖➖➖➖➖\n\n".join(user["saved_posts"][-5:])
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())

@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    await message.answer("💳 Модуль оплаты находится на финальной стадии интеграции. Скоро здесь появится возможность подключить VIP-подписку в один клик!", reply_markup=get_main_keyboard())

# Обработка инлайн-кнопок
@dp.callback_query(F.data.startswith("menu_"))
async def menu_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    data = callback.data
    
    if data == "menu_profile":
        status = "👑 VIP (Безлимит)" if user["is_vip"] else "⏳ Базовый статус"
        text = (
            f"<b>👤 Личный кабинет</b>\n\n"
            f"• <b>Статус:</b> {status}\n"
            f"• <b>Доступно генераций:</b> {user['posts_left']}\n"
            f"• <b>Канал:</b> {user['channel']}\n"
            f"• <b>Сохранено постов:</b> {len(user['saved_posts'])}"
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_keyboard())
    elif data == "menu_channel":
        await callback.message.answer("📢 Отправьте мне @username вашего канала для привязки.")
    elif data == "menu_saved":
        if not user["saved_posts"]:
            await callback.answer("У вас пока нет сохраненных постов!", show_alert=True)
            return
        text = "⭐ <b>Ваши избранные посты:</b>\n\n" + "\n\n➖➖➖➖➖➖\n\n".join(user["saved_posts"][-5:])
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_keyboard())
    elif data == "menu_buy":
        await callback.message.answer("💳 Оплата временно недоступна.")
    elif data == "menu_home":
        text = (
            "✨ <b>ИИ-Редактор постов</b>\n\n"
            "🎙 Опишите голосовым, о чем должен быть пост, и получите готовый текст."
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    await callback.answer()

@dp.callback_query(F.data.startswith("action_"))
async def action_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if callback.data == "action_save":
        post_text = callback.message.text
        if post_text not in user["saved_posts"]:
            user["saved_posts"].append(post_text)
            await callback.answer("✅ Пост успешно сохранен в избранное!", show_alert=True)
        else:
            await callback.answer("ℹ️ Этот пост уже есть в вашем избранном.", show_alert=True)
    elif callback.data == "action_publish":
        await callback.answer("📢 Функция публикации будет доступна сразу после привязки канала!", show_alert=True)

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    processing_msg = await message.answer("🎙 <i>Слушаю аудио... Опишите о чем должен быть пост — обрабатываю запрос...</i>", parse_mode="HTML")
    
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
            await message.answer("⚠️ Не удалось разобрать речь. Пожалуйста, запишите голосовое сообщение еще раз.")
            return

        prompt = (
            "Преврати этот разговорный текст в премиальный, вовлекающий и чистый пост для Telegram-канала. "
            "Опираясь на то, о чем просит пользователь, сделай сильный заголовок, разбей текст на короткие абзацы и добавь уместные эмодзи:\n\n" + raw_text
        )
        
        response = await openai_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0.4,
            messages=[{"role": "user", "content": prompt}]
        )
        
        final_text = response.choices[0].message.content
        
        await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        await message.answer(f"✨ <b>Готовый пост:</b>\n\n{final_text}", parse_mode="HTML", reply_markup=get_post_keyboard())
        
    except Exception as e:
        logging.error(f"❌ Ошибка обработки: {e}")
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        except:
            pass
        await message.answer("❌ Произошла ошибка при генерации. Попробуйте записать более короткое сообщение.")
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
