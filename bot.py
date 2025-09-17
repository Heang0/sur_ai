import os
import json
import re
import asyncio
from datetime import datetime, timedelta

from telegram import Update, BotCommand
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import Conflict, NetworkError

import openai
from dotenv import load_dotenv

# Load secrets from .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# Cache for greetings
CACHE = {
    "hi": "Hello! How can I assist you today?",
    "hello": "Hello! How can I assist you today?",
    "thanks": "You're welcome! 😊",
    "thank you": "You're welcome! 😊"
}

# Daily message limit
DAILY_LIMIT = 50

# User counters file
COUNTERS_FILE = "user_counters.json"
if os.path.exists(COUNTERS_FILE):
    with open(COUNTERS_FILE, "r", encoding="utf-8") as f:
        USER_COUNTERS = json.load(f)
        for u in USER_COUNTERS:
            USER_COUNTERS[u]["reset_time"] = datetime.fromisoformat(USER_COUNTERS[u]["reset_time"])
else:
    USER_COUNTERS = {}

# Users in translation mode
TRANSLATE_MODE_USERS = set()


def clean_response(text: str) -> str:
    text = text.replace("**", "")
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


async def set_bot_commands(application: Application):
    commands = [
        BotCommand("start", "Show the main menu"),
        BotCommand("help", "Get instructions"),
        BotCommand("translate", "Translate text (English ↔ Khmer)")
    ]
    await application.bot.set_my_commands(commands)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hello! I'm your AI assistant. Use the menu button to access my commands."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"ℹ️ Instructions:\n"
        "- Send any message and I will respond.\n"
        "- Use the /start command or menu button to show main options.\n"
        "- Use /translate to translate text (English ↔ Khmer).\n"
        f"- Daily limit: {DAILY_LIMIT} messages per user."
    )


async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if not check_user_limit(user_id):
        await update.message.reply_text(
            f"⚠️ You have reached your daily limit of {DAILY_LIMIT} messages. Please try again tomorrow."
        )
        return
    TRANSLATE_MODE_USERS.add(user_id)
    await update.message.reply_text("🌐 Send me the text you want to translate (English ↔ Khmer):")


def check_user_limit(user_id: str) -> bool:
    now = datetime.now()
    user_data = USER_COUNTERS.get(user_id)
    if user_data:
        if now >= user_data["reset_time"]:
            USER_COUNTERS[user_id] = {"count": 0, "reset_time": now + timedelta(days=1)}
            return True
        elif user_data["count"] >= DAILY_LIMIT:
            return False
        else:
            return True
    else:
        USER_COUNTERS[user_id] = {"count": 0, "reset_time": now + timedelta(days=1)}
        return True


def save_counters():
    data = {}
    for u in USER_COUNTERS:
        data[u] = {
            "count": USER_COUNTERS[u]["count"],
            "reset_time": USER_COUNTERS[u]["reset_time"].isoformat()
        }
    with open(COUNTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def fetch_chatgpt_reply(user_message: str) -> str:
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": user_message}]
        )
        return clean_response(response.choices[0].message.content)
    except Exception as e:
        print("❌ OpenAI Error:", e)
        return "⚠️ Sorry, I'm busy right now. Try again later."


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    user_message = update.message.text

    if not check_user_limit(user_id):
        await update.message.reply_text(
            f"⚠️ You have reached your daily limit of {DAILY_LIMIT} messages. Please try again tomorrow."
        )
        return

    is_translate_mode = user_id in TRANSLATE_MODE_USERS

    # Typing indicator
    async def send_typing():
        while True:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
            await asyncio.sleep(2)

    typing_task = asyncio.create_task(send_typing())

    # Check cache
    key = user_message.lower().strip()
    if key in CACHE and not is_translate_mode:
        reply = CACHE[key]
    else:
        prompt = user_message
        if is_translate_mode:
            prompt = f"Translate this text to Khmer and English: {user_message}"
        reply = await fetch_chatgpt_reply(prompt)
        if is_translate_mode:
            TRANSLATE_MODE_USERS.remove(user_id)

    typing_task.cancel()
    USER_COUNTERS[user_id]["count"] += 1
    save_counters()

    await update.message.reply_text(reply)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors."""
    print(f"Error occurred: {context.error}")
    if isinstance(context.error, Conflict):
        print("⚠️ Another bot instance is running. Please stop other instances.")
    elif isinstance(context.error, NetworkError):
        print("⚠️ Network error occurred.")


async def post_init(application: Application):
    """Function to run after the application is initialized"""
    await set_bot_commands(application)
    print("✅ Bot is running...")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("translate", translate_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    
    # Add error handler
    app.add_error_handler(error_handler)

    # Start polling (PTB manages the event loop internally)
    try:
        app.run_polling()
    except Conflict:
        print("❌ Another bot instance is already running with the same token!")
        print("💡 Please check for other running Python processes and stop them.")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    main()