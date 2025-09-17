import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from telegram import Update, BotCommand
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)

# Cache for greetings / common messages
CACHE = {
    "hi": "Hello! How can I assist you today?",
    "hello": "Hello! How can I assist you today?",
    "thanks": "You're welcome! 😊",
    "thank you": "You're welcome! 😊"
}

# User counters file
COUNTERS_FILE = "user_counters.json"

# Load counters from disk
if os.path.exists(COUNTERS_FILE):
    with open(COUNTERS_FILE, "r", encoding="utf-8") as f:
        USER_COUNTERS = json.load(f)
        for u in USER_COUNTERS:
            USER_COUNTERS[u]["reset_time"] = datetime.fromisoformat(USER_COUNTERS[u]["reset_time"])
else:
    USER_COUNTERS = {}

# Daily message limit
DAILY_LIMIT = 50

# Track users in translation mode
TRANSLATE_MODE_USERS = set()

# Clean Gemini response
def clean_response(text: str) -> str:
    text = text.replace("**", "")
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()

# Set up persistent bot menu commands
async def set_bot_commands(application: Application):
    commands = [
        BotCommand("start", "Show the main menu"),
        BotCommand("help", "Get instructions"),
        BotCommand("translate", "Translate text (English ↔ Khmer)"),
    ]
    await application.bot.set_my_commands(commands)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello! I'm your AI assistant. Use the menu button to access my commands.")

# Translate command
async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if not check_user_limit(user_id):
        await update.message.reply_text(f"⚠️ You have reached your daily limit of {DAILY_LIMIT} messages. Try again tomorrow.")
        return
    TRANSLATE_MODE_USERS.add(user_id)
    await update.message.reply_text("🌐 Send me the text you want to translate (English ↔ Khmer):")

# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"ℹ️ Instructions:\n"
        "- Send any message and I will respond.\n"
        "- Use the /start command or menu button to see options.\n"
        "- Use /translate to enter translation mode.\n"
        f"- Daily limit: {DAILY_LIMIT} messages per user."
    )

# Check daily limit
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

# Save counters
def save_counters():
    data = {}
    for u in USER_COUNTERS:
        data[u] = {"count": USER_COUNTERS[u]["count"], "reset_time": USER_COUNTERS[u]["reset_time"].isoformat()}
    with open(COUNTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Async Gemini API call
async def fetch_gemini_reply(user_message: str) -> str:
    loop = asyncio.get_event_loop()
    try:
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(model="gemini-2.5-flash", contents=user_message)
        )
        return clean_response(response.text)
    except Exception as e:
        print("❌ Gemini Error:", e)
        return "⚠️ Sorry, I'm busy right now. Try again in a moment 🙏"

# Chat / translation handler
async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    user_message = update.message.text

    if not check_user_limit(user_id):
        await update.message.reply_text(f"⚠️ You have reached your daily limit of {DAILY_LIMIT} messages. Try again tomorrow.")
        return

    is_translate_mode = user_id in TRANSLATE_MODE_USERS

    # Start continuous typing indicator
    async def send_typing():
        while True:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
            await asyncio.sleep(2)

    typing_task = asyncio.create_task(send_typing())

    # Check cache first
    key = user_message.lower().strip()
    if key in CACHE and not is_translate_mode:
        reply = CACHE[key]
    else:
        prompt = user_message
        if is_translate_mode:
            prompt = f"Translate this text to Khmer and English: {user_message}"
        reply = await fetch_gemini_reply(prompt)
        if is_translate_mode:
            TRANSLATE_MODE_USERS.remove(user_id)

    # Stop typing
    typing_task.cancel()

    # Increment counter
    USER_COUNTERS[user_id]["count"] += 1
    save_counters()

    await update.message.reply_text(reply)

# Main function
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("translate", translate_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    print("✅ Bot is running...")

    # Run polling and schedule setting menu commands in event loop
    asyncio.get_event_loop().create_task(set_bot_commands(app))
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
