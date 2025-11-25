import os
import re
import time
from dotenv import load_dotenv
import telebot

# Load environment variables from the .env file
load_dotenv()

# Initialize the Telegram bot
API_TOKEN = os.getenv("API_TOKEN")
bot = telebot.TeleBot(API_TOKEN)

def escape_markdown_v2(text: str) -> str:
    """
    Escape special characters for Telegram MarkdownV2 formatting.
    """
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(r'([%s])' % re.escape(escape_chars), r'\\\1', text)

# Send bot message with retry logic and Markdown fallback
def send_bot_message(chat_id: int, message: str):
    """
    Send a Telegram message with rate-limiting and retry mechanism.
    Falls back to plain text if MarkdownV2 fails.
    """
    max_message_length = 4096
    rate_limit_delay = 0.05
    max_attempts = 5

    print(f"Chat ID: {chat_id}, Message Length: {len(message)}")

    try:
        for i in range(0, len(message), max_message_length):
            raw_chunk = message[i:i + max_message_length]
            chunk = escape_markdown_v2(raw_chunk)
            attempt = 0
            success = False

            while attempt < max_attempts and not success:
                try:
                    bot.send_message(chat_id=chat_id, text=chunk, parse_mode='MarkdownV2')
                    success = True
                except Exception as e:
                    print(f"⚠️ Attempt {attempt + 1} failed with MarkdownV2: {e}")
                    attempt += 1
                    time.sleep(rate_limit_delay * 5)

            if not success:
                print("⏳ Falling back to plain text...")
                try:
                    bot.send_message(chat_id=chat_id, text=raw_chunk)  # no parse_mode
                    success = True
                except Exception as e:
                    print(f"❌ Failed to send even plain text: {e}")
                    return f"Failed to send chunk after fallback: {e}"

            time.sleep(rate_limit_delay)

        return "✅ Message sent successfully"

    except Exception as e:
        return f"❌ Unexpected error: {str(e)}"
