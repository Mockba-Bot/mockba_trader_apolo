import os
import re
import sys
import time
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'machine_learning')))
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
import telebot
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from db.db_ops import get_bot_status, startStopBotOp
import json
from datetime import timedelta
import redis

# Load environment variables from the .env file
load_dotenv()


# Initialize Redis connection
redis_url = os.getenv("REDIS_URL")
if redis_url:
    try:
        redis_client = redis.from_url(redis_url)
        redis_client.ping()
    except redis.ConnectionError as e:
        print(f"Redis connection error: {e}")
        redis_client = None
else:
    redis_client = None

API_TOKEN = os.getenv("API_TOKEN")
bot = telebot.TeleBot(API_TOKEN)
gnext = ""
gdata = ""
gp1 = ""

# translation function using GoogleTranslator
def translate(text, chat_id):
    # Try to get cached translation from Redis
    if redis_client:
        cache_key = f"translation:{chat_id}:{text}"
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

    # Get language from database
    lang = os.getenv("BOT_LANGUAGE", "en").lower()

    # print(f"Translating to {lang} for user {chat_id}")

    try:
        translated_text = GoogleTranslator(source='auto', target=lang).translate(text)
        # Cache the translation for 30 days
        if redis_client:
            redis_client.setex(
                cache_key,
                timedelta(days=30),
                json.dumps(translated_text)
            )
        return translated_text
    except Exception as e:
        print(f"Translation error: {e}")
        return text  # Fallback to original text


# only used for console output now
def listener(messages):
   """
   When new messages arrive TeleBot will call this function.
   """
   for m in messages:
       if m.content_type == 'text':
           # print the sent message to the console
           print(str(m.chat.first_name) + " [" + str(m.chat.id) + "]: " + m.text)

   bot.set_update_listener(listener)  # register listener     


# Comando inicio
@bot.message_handler(commands=['start'])
def command_start(m):
    if m.chat.type != 'private':
        return
    cid = m.chat.id
    nom = m.chat.first_name
    text = translate("Welcome to Mockba! With this bot, you trade against Binance.", cid)
    welcome_text = f"{text}."
    bot.send_message(cid,
                    welcome_text + str(nom) + " - " + str(cid))
    command_list(m) 


@bot.message_handler(commands=['list'])
def command_list(m):
    if m.chat.type != 'private':
        return
    cid = m.chat.id
    help_text = translate("Available options.", cid)
    message_button1 = translate("▶️ ⏹️  Start/Stop Bot", cid)
    message_button2 = translate("📝  List Bot Status", cid)
    # Define the buttons
    button1 = InlineKeyboardButton(message_button1, callback_data="SetBotStatus")
    button2 = InlineKeyboardButton(message_button2, callback_data="ListBotStatus")
    # Create a nested list of buttons
    buttons = [[button1], [button2]]
    # Order the buttons in the second row
    buttons[1].sort(key=lambda btn: btn.text)

    # Create the keyboard markup
    reply_markup = InlineKeyboardMarkup(buttons)             
    bot.send_message(cid, help_text, reply_markup=reply_markup)  

# Callback_Handler
# This code creates a dictionary called options that maps the call.data to the corresponding function. 
# The get() method is used to retrieve the function based on the call.data. If the function exists
# , it is called passing the call.message as argument. 
# This approach avoids the need to use if statements to check the value of call.data for each possible option.
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.message.chat.type != 'private':
        return
    cid = call.message.chat.id
    # Define the mapping between call.data and functions
    options = {
        'List': command_list,
        'SetBotStatus': SetBotStatus,
        'ListBotStatus': listBotStatus
    }
    # Get the function based on the call.data
    func = options.get(call.data)

    # Call the function if it exists
    if func:
        func(call.message) 


def listMenu(m):
    if m.chat.type != 'private':
        return
    cid = m.chat.id
    help_text = translate("Available options.", cid)
    # Define the buttons
    button1 = InlineKeyboardButton(translate("📋  List Bot Status", cid), callback_data="ListBotStatus")
    button2 = InlineKeyboardButton(translate("<< Back to list", cid), callback_data="List")

    # Create a nested list of buttons
    buttons = [[button1], [button2]]
    buttons[1].sort(key=lambda btn: btn.text)

    # Create the keyboard markup
    reply_markup = InlineKeyboardMarkup(buttons)    
    bot.send_message(cid, help_text, reply_markup=reply_markup)  


def listBotStatus(m):
    if m.chat.type != 'private':
        return
    cid = m.chat.id
    markup = types.ReplyKeyboardMarkup()
    itemd = types.KeyboardButton('/list')
    markup.row(itemd)
    global gpair

    bot.send_message(cid, translate("Listing ...", cid), parse_mode='Markdown')

    status = get_bot_status()
    signal_status = translate('🔴  OFF - NOT TRADING', cid) if status == 0 else translate('🟢  ON - TRADING', cid)
    bot.send_message(cid, signal_status, parse_mode='Markdown')
    bot.send_message(cid, translate('Done', cid), parse_mode='Markdown', reply_markup=markup)


def SetBotStatus(m):
    if m.chat.type != 'private':
        return
    #get env
    cid = m.chat.id
    global gnext
    gframe = m.text
    markup = types.ReplyKeyboardMarkup()
    itema = types.KeyboardButton('Start')
    itemb = types.KeyboardButton('Stop')
    itemd = types.KeyboardButton('CANCEL')
    markup.row(itema)
    markup.row(itemb)
    markup.row(itemd)

    if gframe == 'CANCEL':
       markup = types.ReplyKeyboardMarkup()
       item = types.KeyboardButton('/list')
       markup.row(item)
       text = translate("🔽 Select your option", cid)
       bot.send_message(cid, text, parse_mode='Markdown', reply_markup=markup)
    else:
        bot.send_message(cid, translate('🤖 This operation will stop or start your bot.', cid), parse_mode='Markdown', reply_markup=markup)
        bot.register_next_step_handler_by_chat_id(cid, startStopBot)

def startStopBot(m):
    if m.chat.type != 'private':
        return
    cid = m.chat.id
    valor = m.text
    global gdata, gpair, gframe, gp1
    gp1 = valor
    markup = types.ReplyKeyboardMarkup()
    itemd = types.KeyboardButton('/list')
    markup.row(itemd)
    if valor != 'Start' and valor != 'Stop':
        markup = types.ReplyKeyboardMarkup()
        item = types.KeyboardButton('/list')
        markup.row(item)
        bot.send_message(cid, translate("Invalid option", cid), parse_mode='Markdown', reply_markup=markup)
        return
    else:
        gdata = 1 if valor == 'Start' else 0
        if valor == 'CANCEL':
            markup = types.ReplyKeyboardMarkup()
            item = types.KeyboardButton('/list')
            markup.row(item)
            bot.send_message(cid, translate('🔽 Select your option', cid), parse_mode='Markdown', reply_markup=markup)
        else:
            bot.send_message(cid, translate("Processing...", cid), parse_mode='Markdown')
            startStopBotOp(gdata)
            bot.send_message(cid, translate(f"Operation to {valor} bot executed...", cid), parse_mode='Markdown', reply_markup=markup)



bot.polling()