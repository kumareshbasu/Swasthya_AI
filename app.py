# app.py
import tempfile
from flask import Flask, request, jsonify, render_template, Response
import requests
import os
import logging
import threading
import io
import math
# --- FIXED DATETIME IMPORTS ---
from datetime import datetime, timezone 
import pandas as pd

# --- AI & Media Imports ---
from langdetect import DetectorFactory 
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv
import re
import whisper
from gtts import gTTS
import subprocess

# --- MATPLOTLIB SETUP ---
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

load_dotenv()
DetectorFactory.seed = 0 
app = Flask(__name__)

# --- CONFIGURATION ---
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
META_API_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
RASA_WEBHOOK_URL = "http://localhost:5005/webhooks/rest/webhook"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"Supabase connection failed: {e}")
    supabase = None

user_states = {} 

# --- Menu Entry Triggers (Multilingual) ---
MENU_ENTRY_TRIGGER = [
    # English
    "hi", "hello", "hey", "menu", "start", "begin", "restart",
    "hi!", "hello!", "hey!", "hii", "hiii", "start again",

    # Hindi (Devanagari)
    "नमस्ते", "हैलो", "स्टार्ट", "मेन्यू", "शुरू", "शुरू करें", "दोबारा शुरू",

    # Hindi (Translated English words)
    "namaste", "hindi hello", "namaskar", "shuru", "menu dikhaye",

    # Bengali (বাংলা)
    "হাই", "হ্যালো", "মেনু", "শুরু", "স্টার্ট", "হাই!", "হ্যালো!", "মেনু দিন",
    "hi bolo", "ami menu chai",

    # Odia (ଓଡ଼ିଆ)
    "ହାଇ", "ହେଲୋ", "ମେନୁ", "ଆରମ୍ଭ", "ସ୍ଟାର୍ଟ", "ମେନୁ ଦିଅ",
    "ନମସ୍କାର", "ନମସ୍ତେ",

    # Spelling mistakes or short variations
    "helo", "heloo", "heyy", "menoo", "starrt", "menue",
    "mnue", "main menu", "begin chat", "chat start",
]

# --- Menu Return Triggers (Multilingual) ---
MENU_RETURN_TRIGGER = [
    # English
    "back", "go back", "return", "main menu", "menu", "exit", "quit",
    "b", "bk", "back!", "go to menu", "back to menu",

    # Hindi (Devanagari)
    "वापस", "पीछे", "मुख्य मेन्यू", "मेन्यू", "बैक", "निकास", "बाहर",
    "मेन्यू दिखाओ", "मेन्‍यू पर जाओ",

    # Hindi (English transliteration)
    "wapas", "peeche", "main menu", "nikas", "bahar jao",

    # Bengali (বাংলা)
    "ফিরে যাও", "ব্যাক", "মেনু", "মেইন মেনু", "বের হও", "রিটার্ন",
    "ফিরে আস", "মেনুতে ফিরে যাও",

    # Odia (ଓଡ଼ିଆ)
    "ପଛକୁ", "ବ୍ୟାକ୍", "ମେନୁ", "ମୁଖ୍ୟ ମେନୁ", "ପଛକୁ ଯାଅ",
    "ଫେରନ୍ତୁ", "ବାହାରିବାକୁ",

    # Mistakes / slang / shortcuts
    "bak", "retun", "mn", "mm", "mainmenu", "manu", "exit chat", "close",
]

# --- MENUS (Updated with Option 4) ---
MULTILINGUAL_MENUS = {
    'en': """
Welcome to Swasthya AI!
1. General Health Info (Chat with AI)
2. Vaccination Schedule
3. Disease Checker (By Symptoms) 🩺
4. Medicine Info (Search by Name) 💊
5. Find Nearest Health Center
6. About Us
7. Change Language / भाषा बदलें / ভাষা পরিবর্তন / ଭାଷା ପରିବର୍ତ୍ତନ
8. Exit Chat

Type the option number to proceed.
Type 'SOS' for emergency assistance.
""",
    'hi': "\n1. सामान्य स्वास्थ्य\n2. टीकाकरण\n3. बीमारी जांच\n4. दवा की जानकारी 💊\n5. स्वास्थ्य केंद्र\n6. हमारे बारे में\n7. Change Language / भाषा बदलें / भाषा परिवर्तन / ଭାଷା ପରିବର୍ତ୍ତନ\n8. बाहर निकलें\n\nआगे बढ़ने के लिए विकल्प संख्या टाइप करें।\nआपातकालीन सहायता के लिए 'SOS' टाइप करें।",
    'bn': "\n1. সাধারণ স্বাস্থ্য\n2. টিকা\n3. রোগ পরীক্ষক\n4. ওষুধের তথ্য 💊\n5. স্বাস্থ্য কেন্দ্র\n6. আমাদের সম্পর্কে\n7. Change Language / भाषा बदलें / भाषा পরিবর্তন / ଭାଷା ପରିବର୍ତ୍ତନ\n8. প্রস্থান\n\nঅগ্রসর হতে বিকল্প নম্বর টাইপ করুন।\nজরুরি সহায়তার জন্য 'SOS' টাইপ করুন।",
    'or': "\n1. ସାଧାରଣ ସ୍ୱାସ୍ଥ୍ୟ\n2. ଟୀକାକରଣ\n3. ରୋଗ ଯାଞ୍ଚ\n4. ଔଷଧ ସୂଚନା 💊\n5. ସ୍ୱାସ୍ଥ୍ୟ କେନ୍ଦ୍ର\n6. ଆମ ବିଷୟରେ\n7. Change Language / भाषा बदलें / ভাষা পরিবর্তন / ଭାଷା ପରିବର୍ତ୍ତନ\n8. ବାହାରନ୍ତୁ\n\nଆଗକୁ ବଢିବା ପାଇଁ ବିକଳ୍ପ ନମ୍ବର ଟାଇପ୍ କରନ୍ତୁ।\nଜରୁରୀକାଳୀନ ସହାୟତା ପାଇଁ 'SOS' ଟାଇପ୍ କରନ୍ତୁ।"
}

MULTILINGUAL_STATIC_MESSAGES = {
    'en': {
        "welcome_back": "Welcome back!",
        "already_main_menu": "You are at the main menu.",
        "left_ai_assistant": "Exited AI Assistant.",
        "entering_ai_assistant": "Entering AI Health Assistant.",
        "vaccination_selected": "Vaccination Info: [Chart Data]",
        "health_center_selected": "Please share your location.",
        "about_us_selected": "Swasthya AI is your personal health assistant.",
        "thank_you_goodbye": "Goodbye! Type 'Hi' to start again.",
        "invalid_option": "Invalid option.",
        "rasa_no_response": "No response.",
        "chat_ended_prompt_restart": "Chat ended.",
        
        # --- Medicine Info Prompt (NEW) ---
        "ask_medicine_name": "Please enter the NAME of the medicine (e.g., Paracetamol, Amoxicillin):",
        "processing_medicine": "Fetching medicine details... Please wait."
    },
    'hi': {
        "welcome_back": "फिर से स्वागत है!",
        "already_main_menu": "आप मुख्य मेनू पर हैं।",
        "left_ai_assistant": "AI सहायक से बाहर निकल गए।",
        "entering_ai_assistant": "AI स्वास्थ्य सहायक में प्रवेश कर रहे हैं।",
        "vaccination_selected": "टीकाकरण जानकारी: [चार्ट डेटा]",
        "health_center_selected": "कृपया अपना स्थान साझा करें।",
        "about_us_selected": "स्वास्थ्य AI आपका व्यक्तिगत स्वास्थ्य सहायक है।",
        "thank_you_goodbye": "अलविदा! फिर से शुरू करने के लिए 'हाय' टाइप करें।",
        "invalid_option": "अमान्य विकल्प।",
        "rasa_no_response": "कोई उत्तर नहीं।",
        "chat_ended_prompt_restart": "चैट समाप्त।",

        # --- Medicine Info Prompt (NEW) ---
        "ask_medicine_name": "कृपया दवा का नाम दर्ज करें (जैसे, पैरासिटामोल, एमोक्सिसिलिन):",
        "processing_medicine": "दवा विवरण प्राप्त किया जा रहा है... कृपया प्रतीक्षा करें।"
    },
    'bn': {
        "welcome_back": "আবার স্বাগতম!",
        "already_main_menu": "আপনি প্রধান মেনুতে আছেন।",
        "left_ai_assistant": "AI সহকারী থেকে বেরিয়ে এসেছেন।",
        "entering_ai_assistant": "AI স্বাস্থ্য সহকারী প্রবেশ করা হচ্ছে।",
        "vaccination_selected": "টিকাদান তথ্য: [চার্ট ডেটা]",
        "health_center_selected": "অনুগ্রহ করে আপনার অবস্থান শেয়ার করুন।",
        "about_us_selected": "স্বাস্থ্য AI আপনার ব্যক্তিগত স্বাস্থ্য সহকারী।",
        "thank_you_goodbye": "বিদায়! আবার শুরু করতে 'হাই' টাইপ করুন।",
        "invalid_option": "অবৈধ বিকল্প।",
        "rasa_no_response": "কোনো উত্তর নেই।",
        "chat_ended_prompt_restart": "চ্যাট শেষ।",

        # --- Medicine Info Prompt (NEW) ---
        "ask_medicine_name": "অনুগ্রহ করে ওষুধের নাম লিখুন (যেমন, প্যারাসিটামল, অ্যামোক্সিসিলিন):",
        "processing_medicine": "ওষুধের বিবরণ পাওয়া যাচ্ছে... অনুগ্রহ করে অপেক্ষা করুন।"
    },

    'or': {
        "welcome_back": "ପୁଣି ସ୍ୱାଗତ!",
        "already_main_menu": "ଆପଣ ମୁଖ୍ୟ ମେନୁରେ ଅଛନ୍ତି।",
        "left_ai_assistant": "AI ସହାୟକ ଛାଡ଼ିଦେଲେ।",
        "entering_ai_assistant": "AI ସ୍ୱାସ୍ଥ୍ୟ ସହାୟକରେ ପ୍ରବେଶ କରୁଛି।",
        "vaccination_selected": "ଟୀକାକରଣ ସୂଚନା: [ଚାର୍ଟ ତଥ୍ୟ]",
        "health_center_selected": "ଦୟାକରି ଆପଣଙ୍କର ଅବସ୍ଥାନ ସେୟାର୍ କରନ୍ତୁ।",
        "about_us_selected": "ସ୍ୱାସ୍ଥ୍ୟ AI ଆପଣଙ୍କର ବ୍ୟକ୍ତିଗତ ସ୍ୱାସ୍ଥ୍ୟ ସହାୟକ।",
        "thank_you_goodbye": "ବିଦାୟ! ପୁଣି ଆରମ୍ଭ କରିବାକୁ 'ହାଇ' ଟାଇପ୍ କରନ୍ତୁ।",
        "invalid_option": "ଅବୈଧ ବିକଳ୍ପ।",
        "rasa_no_response": "କୌଣସି ପ୍ରତିକ୍ରିୟା ନାହିଁ।",
        "chat_ended_prompt_restart": "ଚାଟ୍ ସମାପ୍ତ।",

        # --- Medicine Info Prompt (NEW) ---
        "ask_medicine_name": "ଦୟାକରି ଔଷଧର ନାମ ଦାଖଲ କରନ୍ତୁ (ଉଦାହରଣ ସ୍ୱରୂପ, ପ୍ୟାରାସିଟାମଲ୍, ଏମୋକ୍ସିସିଲିନ୍):",
        "processing_medicine": "ଔଷଧ ବିବରଣୀ ଆଣାଯାଉଛି... ଦୟାକରି ପ୍ରତୀକ୍ଷା କରନ୍ତୁ।"
    }
}

LANGUAGE_MENU = """
Select Language / भाषा चुनें / ভাষা নির্বাচন করুন / ଭାଷା ଚୟନ କରନ୍ତୁ:
1. English
2. हिंदी (Hindi)
3. বাংলা (Bengali)
4. ଓଡ଼ିଆ (Odia)
"""

MULTILINGUAL_AI_CLOSING = {
    'en': "This response is completed.\nSelect any one option:\n1. Get more detailed information about this.\n2. Do you want to ask anything more about something else?\n3. Would you like to go back to main menu?",
    'hi': "उत्तर पूरा हो गया है।\nकृपया एक विकल्प चुनें:\n1. इस बारे में अधिक विस्तृत जानकारी प्राप्त करें।\n2. क्या आप इसके बारे में या किसी अन्य विषय पर और पूछना चाहते हैं?\n3. क्या आप मुख्य मेनू पर वापस जाना चाहते हैं?",
    'bn': "উত্তর সম্পূর্ণ হয়েছে।\nএকটি বিকল্প নির্বাচন করুন:\n3. এর সম্পর্কে আরও বিস্তারিত তথ্য পান।\n2. আপনি কি এ সম্পর্কে বা অন্য কিছু সম্পর্কে আরও জানতে চান?\n3. আপনি কি প্রধান মেনুতে ফিরে যেতে চান?",
    'or': "ଉତ୍ତର ସମାପ୍ତ ହୋଇଛି।\nଦୟାକରି ଏକ ବିକଳ୍ପ ବାଛନ୍ତୁ:\n3. ଏହା ବିଷୟରେ ଅଧିକ ବିସ୍ତୃତ ସୂଚନା ପାଇଁ।\n2. ଆପଣ ଏହା ବିଷୟରେ କିମ୍ବା ଅନ୍ୟ କିଛି ବିଷୟରେ ଅଧିକ ପଚାରିବାକୁ ଚାହାନ୍ତି କି?\n3. ଆପଣ ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବାକୁ ଚାହାନ୍ତି କି?"
}

# Vaccination Menu
vacc_menu = {
    "en": "Vaccination Menu:\n1. Standard Vaccination Schedule\n2. My Child’s Upcoming Vaccines\n3. Return to Main Menu",
    "hi": "टीकाकरण मेनू:\n1. मानक टीकाकरण अनुसूची\n2. मेरे बच्चे के आने वाले टीके?\n3. मुख्य मेनू पर वापस जाएँ",
    "bn": "টিকাদান মেনু:\n1. স্ট্যান্ডার্ড টিকাদান সূচি\n2. আমার শিশুর আগামী টিকা\n3. প্রধান মেনুতে ফিরে যান",
    "or": "ଟୀକାକରଣ ମେନୁ:\n1. ସାଧାରଣ ଟୀକା ସୂଚୀ\n2. ମୋ ଶିଶୁଙ୍କ ଆସନ୍ତା ଟୀକାଗୁଡିକ\n3. ମୁଖ୍ୟ ମେନୁକୁ ଫେରନ୍ତୁ"
}

# Ask Date of Birth Prompt
askdob = {
    "en": "Please enter the child’s date of birth in YYYY-MM-DD format:",
    "hi": "कृपया बच्चे की जन्म तिथि YYYY-MM-DD में दर्ज करें:",
    "bn": "শিশুর জন্মতারিখ YYYY-MM-DD ফরম্যাটে লিখুন:",
    "or": "ଶିଶୁର ଜନ୍ମତାରିଖ YYYY-MM-DD ରେ ଲେଖନ୍ତୁ:"
}

# Vaccination Closing Prompt
MULTILINGUAL_VACC_CLOSING = {
    'en': "Vaccination info completed.\nChoose an option:\n1. Ask details about a specific vaccine\n2. Return to Vaccination Menu",
    
    'hi': "टीकाकरण जानकारी पूरी हुई।\nकृपया एक विकल्प चुनें:\n1. किसी विशेष टीके के बारे में अधिक जानकारी\n2. टीकाकरण मेनू पर वापस जाएँ",
    
    'bn': "টিকাদানের তথ্য সম্পূর্ণ।\nএকটি বিকল্প নির্বাচন করুন:\n1. কোনও নির্দিষ্ট টিকা সম্পর্কে জানতে চান\n2. টিকাদান মেনুতে ফিরে যান",
    
    'or': "ଟୀକା ସୂଚନା ସମାପ୍ତ।\nଦୟାକରି ଏକ ବିକଳ୍ପ ଚୟନ କରନ୍ତୁ:\n1. ନିର୍ଦ୍ଦିଷ୍ଟ ଟୀକା ବିଷୟରେ ଅଧିକ ଜାଣନ୍ତୁ\n2. ଟୀକାକରଣ ମେନୁକୁ ଫେରନ୍ତୁ"
}
# Language equivalence mapping for DB matching
LANG_EQUIVALENCE = {
    "en": ["en", "english", "en-us", "eng"],
    "hi": ["hi", "hindi", "hin", "hi-in"],
    "bn": ["bn", "bengali", "ben", "bn-in"],
    "or": ["or", "odia", "oriya", "ori", "or-in"]
}

MULTILINGUAL_MED_CLOSING = {
    'en': "Medicine information completed.\nChoose one option:\n1. Ask details about another medicine\n2. Return to Medicine Menu",
    
    'hi': "दवा की जानकारी पूरी हुई।\nएक विकल्प चुनें:\n1. किसी और दवा के बारे में पूछें\n2. दवा मेनू पर वापस जाएँ",
    
    'bn': "ওষুধের তথ্য সম্পূর্ণ হয়েছে।\nএকটি বিকল্প বেছে নিন:\n1. অন্য কোনো ওষুধ সম্পর্কে জানতে চান\n2. ওষুধ মেনুতে ফিরে যান",
    
    'or': "ଔଷଧ ସୂଚନା ସମାପ୍ତ।\nଦୟାକରି ବିକଳ୍ପ ଚୟନ କରନ୍ତୁ:\n1. ଅନ୍ୟ ଔଷଧ ବିଷୟରେ ପଚାରନ୍ତୁ\n2. ଔଷଧ ମେନୁକୁ ଫେରନ୍ତୁ"
}

med_menu = {
    "en": "Medicine Menu:\n1. Search Medicine Information\n2. Return to Main Menu",
    "hi": "दवा मेनू:\n1. दवा की जानकारी खोजें\n2. मुख्य मेनू पर वापस जाएँ",
    "bn": "ওষুধ মেনু:\n1. ওষুধ সম্পর্কিত তথ্য খুঁজুন\n2. প্রধান মেনুতে ফিরে যান",
    "or": "ଔଷଧ ମେନୁ:\n1. ଔଷଧ ସୂଚନା ଖୋଜନ୍ତୁ\n2. ମୁଖ୍ୟ ମେନୁକୁ ଫେରନ୍ତୁ"
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# load whisper
try:
    logger.info(f"Loading Whisper model '{WHISPER_MODEL}'... (this may take a while)")
    whisper_model = whisper.load_model(WHISPER_MODEL)
    logger.info("Whisper loaded.")
except Exception as e:
    logger.exception("Failed to load Whisper model: %s", e)
    whisper_model = None

# language -> gTTS code mapping (gTTS supports 'or' for Odia)
LANG_TO_GTTS = {
    "hi": "hi",
    "bn": "bn",
    "or": "or",
    "en": "en",
}

# --- HELPERS ---
def insert_message(phone_num, sender, text=None, media=None, language="en"):
    if not supabase: return
    entry = {
        "phone_num": str(phone_num),
        "user_message": text if sender == "user" else None,
        "bot_message": text if sender == "bot" else None,
        "user_media": media or [],
        "language": language,
        "time_stamp": datetime.now(timezone.utc).isoformat()
    }
    try: supabase.table("user_chat_media").insert(entry).execute()
    except Exception as e: logger.error(f"DB Error: {e}")

def get_localized_message(from_number, key):
    user_data = user_states.get(from_number, {})
    lang = user_data.get('lang', 'en') # Default to English
    return MULTILINGUAL_STATIC_MESSAGES.get(lang, {}).get(key, MULTILINGUAL_STATIC_MESSAGES['en'][key])

def send_whatsapp_message(to_number, message_body):
    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to_number, "type": "text", "text": {"body": message_body}}
    try:
        requests.post(META_API_URL, headers=headers, json=payload)
        insert_message(to_number, "bot", text=message_body, language=user_states.get(to_number, {}).get('lang', 'en'))
    except Exception as e: logger.error(f"Send Error: {e}")

def send_sms_message(to_number, message_body):
    """
    MOCK SMS sender 
    Just logs the bot reply and continues the flow.
    """
    logger.info(f"[TRIAL SMS] To {to_number} -> {message_body}")

    # Log bot message into the database
    insert_message(
        phone_num=to_number,
        sender="bot",
        text=message_body,
        media=None,
        language=user_states.get(to_number, {}).get("lang", "en")
    )

    return "mock_sid_12345"

def send_unified_message(to_number, message_body, channel='whatsapp'):
    if channel == 'sms':
        send_sms_message(to_number, message_body)
    else:
        send_whatsapp_message(to_number, message_body)

def get_media_url_from_id(media_id):
    try:
        r = requests.get(f"https://graph.facebook.com/v19.0/{media_id}", headers={"Authorization": f"Bearer {META_ACCESS_TOKEN}"})
        return r.json().get("url")
    except: return None

def get_last_20_messages(phone_num):
    try:
        res = supabase.table("user_chat_media").select("*").eq("phone_num", str(phone_num)).order("time_stamp", desc=True).limit(20).execute()
        if not res or not res.data: return []
        messages = []
        for row in reversed(res.data):
            if row.get("user_message"): messages.append({"sender": "user", "text": row.get("user_message")})
            if row.get("bot_message"): messages.append({"sender": "bot", "text": row.get("bot_message")})
        return messages
    except: return []

def download_media(media_url, local_basename):
    local_path = os.path.join("/tmp", local_basename)
    try:
        r = requests.get(media_url, headers={"Authorization": f"Bearer {META_ACCESS_TOKEN}"}, stream=True, timeout=3000)
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
        return local_path
    except Exception as e:
        logger.exception("Failed to download media: %s", e)
        return None

def convert_to_wav(input_path):
    wav_path = input_path + ".wav"
    try:
        # convert to 16k mono wav for whisper
        subprocess.run(["ffmpeg", "-y", "-i", input_path, "-ar", "16000", "-ac", "1", wav_path],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return wav_path
    except Exception as e:
        logger.exception("ffmpeg convert_to_wav failed: %s", e)
        return None

# gTTS -> MP3 then convert MP3 -> OGG/OPUS for WhatsApp
def text_to_speech_gtts_to_ogg(text, lang_code):
    try:
        gtts_lang = LANG_TO_GTTS.get(lang_code, "en")
        # Use tempfile directory for cross-platform compatibility
        mp3_path = os.path.join(tempfile.gettempdir(), f"tts_{int(datetime.now(timezone.utc).timestamp())}.mp3")
        tts = gTTS(text=text, lang=gtts_lang)
        tts.save(mp3_path)

        ogg_path = mp3_path.replace(".mp3", ".ogg")

        # FIX: Just use 'ffmpeg' command, assuming it is installed via brew
        # If not in path, use full path like '/usr/local/bin/ffmpeg' or '/opt/homebrew/bin/ffmpeg'
        subprocess.run(["ffmpeg", "-y", "-i", mp3_path, "-c:a", "libopus", "-b:a", "64k", ogg_path],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        try:
            os.remove(mp3_path)
        except:
            pass
        return ogg_path
    except Exception as e:
        logger.exception("TTS generation failed: %s", e)
        return None

# --- REPLACEMENT FUNCTION ---
def upload_media_and_send_audio(to_number, file_path):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}"}
    
    try:
        # 1. Upload Media
        with open(file_path, "rb") as f:
            # FIX: Explicitly define MIME type as audio/ogg
            files = {
                'file': (os.path.basename(file_path), f, 'audio/ogg'),
                'messaging_product': (None, 'whatsapp') 
            }
            # Remove 'Content-Type' header if it exists, let requests handle multipart boundary
            r = requests.post(url, headers=headers, files=files)
            
            # Log raw response for debugging if it fails
            if r.status_code != 200:
                logger.error(f"Media Upload Failed: {r.status_code} - {r.text}")
                return False
                
            media_id = r.json().get("id")
        
        # 2. Send Media Message
        if media_id:
            payload = {
                "messaging_product": "whatsapp",
                "to": to_number,
                "type": "audio",
                "audio": {"id": media_id}
            }
            r2 = requests.post(META_API_URL, headers={"Authorization": f"Bearer {META_ACCESS_TOKEN}", "Content-Type": "application/json"}, json=payload)
            
            if r2.status_code == 200:
                # Log bot audio to DB
                insert_message(to_number, "bot", text="[Audio Message]", media=[{"id": media_id}], language="en")
                return True
            else:
                logger.error(f"Media Send Failed: {r2.text}")
        else:
            logger.error("Upload failed. No media ID returned.")

    except Exception as e:
        logger.error(f"Audio Send Exception: {e}")
        
    return False


def transcribe_with_whisper(wav_path):
    if not whisper_model:
        logger.error("Whisper model not loaded.")
        return "", "en"
    try:
        res = whisper_model.transcribe(wav_path)
        text = res.get("text", "").strip()
        print(text)
        lang = res.get("language") or "en"
        # reduce to 2-letter percent if longer
        if isinstance(lang, str) and len(lang) >= 2:
            lang = lang[:2]
        return text, lang
    except Exception as e:
        logger.exception("Whisper transcription error: %s", e)
        return "", "en"

def call_rasa(transcript, sender_id, lang_code="en", detailed=False):
    try:
        payload = {"sender": sender_id, "message": transcript, "metadata": {"lang": lang_code, "detailed_response": detailed}}
        r = requests.post(RASA_WEBHOOK_URL, json=payload, timeout=3000)
        r.raise_for_status()
        resp = r.json()
        texts = []
        for it in resp:
            if it.get("text"):
                texts.append(it.get("text"))
        return texts
    except Exception as e:
        logger.exception("Rasa call failed: %s", e)
        return []

def call_gemini(context_messages, incoming_text, lang_code="en", detailed=False):
    try:
        if not GEMINI_API_KEY:
            logger.warning("No GEMINI_API_KEY configured; skipping Gemini.")
            return None

        # 1. Build System Prompt based on Language
        if lang_code == 'hi':
            sys_p = "आप एक सहायक चिकित्सा सहायक हैं। "
        elif lang_code == 'bn':
            sys_p = "আপনি একজন সহায়ক চিকিৎসা সহকারী। "
        elif lang_code == 'or':
            sys_p = "ଆପଣ ଜଣେ ସହାୟକ ଚିକିତ୍ସା ସହାୟକ। "
        else:
            sys_p = "You are a helpful medical assistant."

        # 2. Add Length Instruction
        if detailed:
            sys_p += "Provide a DETAILED and comprehensive explanation."
        else:
            sys_p += "Keep replies VERY SHORT and concise (Around 150-200 words)."
        
        # Add mandatory disclaimer
        sys_p += " Always add: 'Medical advice disclaimer required'."

        # 3. Build Conversation Context
        prompt_parts = [sys_p, "\nConversation context:"]
        
        # This loop ensures previous messages are formatted correctly for Gemini
        for m in context_messages:
            prompt_parts.append(f"{m['sender']}: {m['text']}")
        
        # Add the current user message
        prompt_parts.append(f"user: {incoming_text}")
        
        prompt = "\n".join(prompt_parts)

        # 4. Call Model
        model = genai.GenerativeModel("gemini-2.5-flash")
        resp = model.generate_content([prompt])
        
        raw_text = getattr(resp, "text", str(resp))
        clean_text = raw_text.replace("*", "").replace("#", "")

        return clean_text

    except Exception as e:
        logger.exception("Gemini call failed: %s", e)
        return "Sorry, I'm unable to respond right now."

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) * math.sin(dlat / 2) + \
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
        math.sin(dlon / 2) * math.sin(dlon / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def find_nearest_hospital(user_lat, user_lon):
    nearest = None
    min_dist = float('inf')
    
    try:
        # 1. Fetch all hospitals from Supabase
        # .select("*") grabs all columns. You can specify "name, latitude, longitude, phone" if you prefer.
        response = supabase.table("hospitals").select("*").execute()
        
        # Supabase returns data in response.data
        hospitals_db = response.data if response and response.data else []

        if not hospitals_db:
            # Fallback if DB is empty or connection fails
            logging.warning("No hospitals found in database.")
            return None, 0.0

        # 2. Iterate through the DB results
        for h in hospitals_db:
            # Ensure latitude/longitude exist and are valid numbers
            try:
                h_lat = float(h.get("latitude"))
                h_lon = float(h.get("longitude"))
            except (ValueError, TypeError):
                continue # Skip invalid records

            dist = calculate_distance(user_lat, user_lon, h_lat, h_lon)
            
            if dist < min_dist:
                min_dist = dist
                nearest = h
                
    except Exception as e:
        logging.error(f"Error fetching hospitals from Supabase: {e}")
        return None, 0.0
            
    return nearest, min_dist

# --- Modified Insert: Returns the new ID ---
def insert_disease_record(city=None, disease=None):
    if not supabase: return None
    try:
        payload = {"city": city, "disease": disease}
        response = supabase.table("disease_count").insert(payload).execute()
        
        # Return the ID of the newly created row
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
            
    except Exception as e:
        logger.error(f"Insert Error: {e}")
    return None

# --- NEW Function: Updates an existing row ---
def update_disease_record(row_id, disease):
    if not supabase or not row_id: return False
    try:
        # Update the specific row ID with the new disease
        supabase.table("disease_count").update({"disease": disease}).eq("id", row_id).execute()
        logger.info(f"Updated Row {row_id} with disease: {disease}")
        return True
    except Exception as e:
        logger.error(f"Update Error: {e}")
        return False

# --- Fetch last 24 hours rows from disease_count ---
def get_last_24h_diseases():
    try:
        now = datetime.datetime.now(timezone.utc)
        last_24h = now - datetime.timedelta(hours=24)

        response = (
            supabase
            .table("disease_count")
            .select("*")
            .gte("log_time", last_24h.isoformat())
            .execute()
        )

        return response.data if response and response.data else []
    except Exception as e:
        logger.error(f"Last 24h fetch error: {e}")
        return []

# --- Disease counts per city (last 24 hours only) ---
def get_disease_counts_last24h():
    rows = get_last_24h_diseases()
    result = {}

    for row in rows:
        city = row.get("city") or "Unknown"
        disease = row.get("disease")
        if not disease:
            continue

        if city not in result:
            result[city] = {}

        result[city][disease] = result[city].get(disease, 0) + 1

    return result

# --- Total disease counts for pie chart (last 24 hours only) ---
def get_total_disease_counts_last24h():
    rows = get_last_24h_diseases()
    result = {}

    for row in rows:
        disease = row.get("disease")
        if not disease:
            continue

        disease = disease.lower().strip()
        result[disease] = result.get(disease, 0) + 1

    return result

# --- HELPER: Upload Image to Meta ---
def upload_image_to_meta(file_path):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}"}
    
    try:
        with open(file_path, "rb") as f:
            files = {
                'file': (os.path.basename(file_path), f, 'image/png'),
                'messaging_product': (None, 'whatsapp')
            }
            r = requests.post(url, headers=headers, files=files)
            if r.status_code == 200:
                return r.json().get("id")
            else:
                logger.error(f"Image Upload Failed: {r.text}")
    except Exception as e:
        logger.error(f"Image Upload Error: {e}")
    return None

# --- HELPER: Send Image Message ---
def send_whatsapp_image(to_number, media_id, caption=None):
    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "image",
        "image": {"id": media_id}
    }
    if caption:
        payload["image"]["caption"] = caption
        
    try:
        requests.post(META_API_URL, headers=headers, json=payload)
    except Exception as e:
        logger.error(f"Send Image Error: {e}")

# ---------------------------------------------------------
# 4. MAIN LOGIC
# ---------------------------------------------------------
# CORE LOGIC (SHARED BY WHATSAPP & SMS)
# ---------------------------------------------------------
def process_core_logic(from_number, incoming_msg, msg_type, channel, media_url=None, location_data=None):
    try:
        # 1. State Init
        if from_number not in user_states:
            # Initialize with 'ask_city' state to force location capture first
            user_states[from_number] = {
                'state': 'ask_city', 
                'lang': 'en', 
                'city': 'Unknown', 
                'data': {}
            }
            send_unified_message(from_number, "Welcome to Swasthya AI! 🏥\nTo start, please type your **City Name**:", channel=channel)
            return
        
        current_state = user_states[from_number]['state']
        current_lang = user_states[from_number]['lang']
        normalized_msg = incoming_msg.lower().strip() if incoming_msg else ""

        # --- HANDLE CITY INPUT ---
        if current_state == 'ask_city':
            city_input = incoming_msg.strip().title()
            
            # Basic validation
            if len(city_input) < 3:
                send_unified_message(from_number, "Please enter a valid City name:", channel=channel)
                return
            
            # Save City to State
            user_states[from_number]['city'] = city_input
            user_states[from_number]['state'] = 'language_selection' # Move to next step

            row_id = insert_disease_record(city=city_input, disease=None)

            if row_id:
                user_states[from_number]['current_db_id'] = row_id
            
            send_unified_message(from_number, f"Thank you! Location set to {city_input}.", channel=channel)
            send_unified_message(from_number, LANGUAGE_MENU, channel=channel)
            return

        # 2. Log User Message
        if msg_type == 'text':
            insert_message(from_number, "user", text=incoming_msg, language=current_lang)
        elif msg_type == 'audio' or msg_type == 'image':
            # We log media after processing usually, or here with a tag
            insert_message(from_number, "user", media=[{"url": media_url}], language=current_lang)
        elif msg_type == 'location':
            insert_message(from_number, "user", text=f"Location: {location_data}", language=current_lang)

        # 3. VOICE HANDLING (For both SMS & WhatsApp)
        if msg_type in ["audio", "voice"] and media_url:
            local_path = download_media(media_url, f"audio_{int(datetime.now().timestamp())}.ogg")
            if local_path:
                wav_path = convert_to_wav(local_path)
                if wav_path:
                    text, lang = transcribe_with_whisper(wav_path)
                    if text:
                        # Log Transcription
                        insert_message(from_number, "user", text=f"[Voice Transcribed] {text}", language=current_lang)
                        
                        # Get Reply
                        context = get_last_20_messages(from_number)
                        reply = call_gemini(context, text, lang_code=current_lang)
                        
                        # --- START NEW TTS LOGIC ---
                        # Generate TTS Audio (gTTS -> OGG)
                        tts_file = text_to_speech_gtts_to_ogg(reply, lang_code=current_lang)
                        
                        audio_sent = False
                        if tts_file:
                            # Upload and send audio
                            audio_sent = upload_media_and_send_audio(from_number, tts_file)
                            
                            # Cleanup OGG file
                            try: os.remove(tts_file)
                            except: pass
                        
                        # Fallback to text if audio failed
                        if not audio_sent:
                            send_unified_message(from_number, reply, channel=channel)
                        # --- END NEW TTS LOGIC ---
                        
                        return
            
            send_unified_message(from_number, get_localized_message(from_number, "voice_error"), channel=channel)
            return

        # 4. IMAGE HANDLING (Gemini Vision)
        if msg_type == "image" and media_url:
            rasa_payload = f'/analyze_image{{"image_url": "{media_url}"}}'
            try:
                bot_msgs = call_rasa(rasa_payload, from_number, lang_code=current_lang)
                for txt in bot_msgs:
                    send_unified_message(from_number, txt, channel=channel)
                
                # Show closing options
                send_unified_message(from_number, MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en']), channel=channel)
                user_states[from_number]['state'] = 'awaiting_ai_choice'
            except:
                send_unified_message(from_number, "Image analysis failed.", channel=channel)
            return

        # 5. SOS TEXT TRIGGER
        if normalized_msg == "sos":
            user_states[from_number]['state'] = 'awaiting_sos_location'
            alert_msg = (
                "🚨 *EMERGENCY MODE ACTIVATED* 🚨\n\n"
                "I cannot see your location automatically.\n"
                "Please tap the *Attachment Icon* (📎 or +) \n"
                "Select *Location* -> *Send Your Current Location*."
            )
            send_unified_message(from_number, alert_msg, channel=channel)
            return

        # 6. LOCATION MESSAGE HANDLER
        # This handles the location response regardless of the previous state
        if msg_type == "location" and location_data:
            latitude = location_data.get("latitude")
            longitude = location_data.get("longitude")
            logger.info(f"📍 DEBUG: Location Received! Data: {location_data}")

            if current_state == 'awaiting_sos_location':
                hospital, dist = find_nearest_hospital(latitude, longitude)
                
                if hospital:
                    map_url = f"https://www.google.com/maps/dir/?api=1&destination={hospital['latitude']},{hospital['longitude']}"
                    user_map_url = f"https://www.google.com/maps/dir/?api=1&destination={latitude},{longitude}"
                    
                    reply_to_user = (f"🚑 *SOS ALERT: HELP IS COMING* 🚑\n\n"
                                     f"We have alerted: *{hospital['hospital_name']}*\n"
                                     f"Distance: {dist:.2f} km\n"
                                     f"Phone: {hospital['contact_no']}\n\n"
                                     f"📍 *Directions:* {map_url}")
                    send_unified_message(from_number, reply_to_user, channel=channel)
                    
                    # Alert the Hospital (WhatsApp Only)
                    if channel == 'whatsapp':
                        alert_body = (
                            f"🚨 *EMERGENCY ALERT* 🚨\n"
                            f"Patient SOS nearby.\n"
                            f"Phone: +{from_number}\n"
                            f"Dist: {dist:.2f} km\n"
                            f"📍 *Loc:* {user_map_url}"
                        )
                        if hospital.get('contact_no'):
                            send_whatsapp_message(hospital['contact_no'], alert_body)
                else:
                    send_unified_message(from_number, "No registered hospitals found nearby. Please call 112.", channel=channel)
                
                # Reset to Main Menu after SOS
                user_states[from_number]['state'] = 'main_menu'
                send_unified_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']), channel=channel)
                return
            else:
                # Handle random location sharing if not in SOS mode
                send_unified_message(from_number, "Location received. To find a health center, please use the Main Menu.", channel=channel)
                return

        # 7. NAVIGATION COMMANDS
        if normalized_msg in MENU_ENTRY_TRIGGER:
            if current_state == 'language_selection':
                send_unified_message(from_number, LANGUAGE_MENU, channel=channel)
            else:
                user_states[from_number]['state'] = 'main_menu'
                send_unified_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']), channel=channel)
            return

        # -----------------------------------------
        # STATE MACHINE (Same logic for SMS & WhatsApp)
        # -----------------------------------------
        
        if current_state == 'ask_city':
            city_name = (incoming_msg or "").strip()
            if not city_name:
                send_unified_message(from_number, "I didn't catch your city. Please type the name of your City (e.g., Mumbai):", channel=channel)
                return

            # Save in memory
            user_states[from_number]['city'] = city_name

            # Insert a record into disease_count with city only (disease NULL)
            try:
                insert_disease_record(city=city_name, disease=None)
            except Exception as e:
                logger.error(f"Failed to insert city into disease_count: {e}")

            # Move to language selection
            user_states[from_number]['state'] = 'language_selection'
            send_unified_message(from_number, LANGUAGE_MENU, channel=channel)
            return

        # --- LANGUAGE SELECTION ---
        if current_state == 'language_selection':
            if normalized_msg == '1': user_states[from_number]['lang'] = 'en'
            elif normalized_msg == '2': user_states[from_number]['lang'] = 'hi'
            elif normalized_msg == '3': user_states[from_number]['lang'] = 'bn'
            elif normalized_msg == '4': user_states[from_number]['lang'] = 'or'
            else: 
                send_unified_message(from_number, "Invalid. 1-4.\n" + LANGUAGE_MENU, channel=channel)
                return
            user_states[from_number]['state'] = 'main_menu'
            send_unified_message(from_number, MULTILINGUAL_MENUS.get(user_states[from_number]['lang']), channel=channel)
            return
    
        # --- CHILD DOB FOR VACCINATION --- 
        if current_state == 'ask_child_dob':
            dob = incoming_msg.strip()

            # Validate date format
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', dob):
                send_whatsapp_message(from_number, askdob.get(current_lang) + "\nInvalid DOB format. Use YYYY-MM-DD.")
                return

            # Set language into Rasa
            lang_set_payload = '/set_language'
            requests.post(
                RASA_WEBHOOK_URL,
                json={
                    "sender": from_number,
                    "message": lang_set_payload,
                    "metadata": {"lang": current_lang}
                }
            )

            # Trigger Rasa Action for child vaccination
            rasa_payload = f'/vaccine_child{{"dob":"{dob}"}}'

            try:
                r = requests.post(
                    RASA_WEBHOOK_URL,
                    json={
                        "sender": from_number,
                        "message": rasa_payload,
                        "metadata": {"lang": current_lang}
                    },
                    timeout=300
                )

                # Send all Rasa messages
                for bot_msg in r.json():
                    if bot_msg.get("text"):
                        send_whatsapp_message(from_number, bot_msg["text"])

                # ⬇️ NEW → Show vaccination closing prompt (Option 1 & 2 only)
                send_whatsapp_message(from_number, MULTILINGUAL_VACC_CLOSING.get(current_lang))

                # Move to vaccination choice state
                user_states[from_number]['state'] = 'awaiting_vacc_choice'

            except Exception as e:
                logger.error(f"Error calling Rasa for vaccine_child: {e}", exc_info=True)
                send_whatsapp_message(from_number, "Error. Try again.")
            return

        # --- MEDICINE MENU LOGIC ---
        if current_state == 'medicine_menu':

            # Option 1 → Ask for medicine name
            if normalized_msg == '1':
                user_states[from_number]['state'] = 'ask_medicine_name'
                send_unified_message(from_number, get_localized_message(from_number, "ask_medicine_name"), channel=channel)
                return

            # Option 2 → Return to Main Menu
            if normalized_msg == '2':
                user_states[from_number]['state'] = 'main_menu'
                send_unified_message(from_number, MULTILINGUAL_MENUS.get(current_lang), channel=channel)
                return

            send_unified_message(from_number, "Invalid option.\n" + med_menu.get(current_lang), channel=channel)
            return
                    
        # --- VACCINATION MENU LOGIC ---
        if current_state == 'vaccination_menu':

            # Option 1 — Standard Vaccination Schedule
            if normalized_msg == '1':
                # set language
                lang_set_payload = '/set_language'
                requests.post(
                    RASA_WEBHOOK_URL,
                    json={"sender": from_number, "message": lang_set_payload, "metadata": {"lang": current_lang}}
                )

                # call standard schedule
                rasa_payload = '/vaccine_standard'
                try:
                    r = requests.post(
                        RASA_WEBHOOK_URL,
                        json={"sender": from_number, "message": rasa_payload, "metadata": {"lang": current_lang}},
                        timeout=300
                    )

                    for bot_msg in r.json():
                        if bot_msg.get("text"):
                            send_whatsapp_message(from_number, bot_msg["text"])

                    # NEW → Show Vaccination Closing Menu (not AI closing)
                    send_whatsapp_message(from_number, MULTILINGUAL_VACC_CLOSING.get(current_lang))
                    user_states[from_number]['state'] = 'awaiting_vacc_choice'
                except Exception as e:
                    logger.error(f"Error calling Rasa for vaccine_standard: {e}")
                    send_whatsapp_message(from_number, "Error fetching vaccine info.")
                return

            # Option 2 — Ask DOB
            if normalized_msg == '2':
                user_states[from_number]['state'] = 'ask_child_dob'
                send_whatsapp_message(from_number, askdob.get(current_lang))
                return

            # NEW Option 3 — Return to Main Menu
            if normalized_msg == '3':
                user_states[from_number]['state'] = 'main_menu'
                send_unified_message(from_number, MULTILINGUAL_MENUS.get(current_lang), channel=channel)
                return


        # --- MAIN MENU ---
        if current_state == 'main_menu':
            if normalized_msg == '1':
                user_states[from_number]['state'] = 'in_rasa_conversation'
                send_unified_message(from_number, get_localized_message(from_number, "entering_ai_assistant"), channel=channel)
            elif normalized_msg == '2':
                user_states[from_number]['state'] = 'vaccination_menu'
                lang = current_lang
                send_whatsapp_message(from_number, vacc_menu.get(lang, vacc_menu['en']))
                return
            elif normalized_msg == '3': # SMART DISEASE CHECKER (Replaces old 10-step flow)
                user_states[from_number]['state'] = 'ask_complete_details'
                
                msg = (
                    "🩺 **Smart Symptom Checker**\n"
                    "I can analyze your health based on local trends in your city.\n\n"
                    "Please tell me your **Age, Gender, and Symptoms** in one message.\n"
                    "📝 *Example:* 'I am 24 male from Govindpur. High fever and body pain since yesterday.'"
                )
                send_unified_message(from_number, msg, channel=channel)
                return
            
            elif normalized_msg == '4':  # Medicine Info
                user_states[from_number]['state'] = 'medicine_menu'
                send_unified_message(from_number, med_menu.get(current_lang), channel=channel)
                
            elif normalized_msg == '5': # Center
                user_states[from_number]['state'] = 'ask_pincode'
                send_unified_message(from_number, "Please enter your pincode:", channel=channel)
            elif normalized_msg == '6': # About
                send_unified_message(from_number, get_localized_message(from_number, "about_us_selected"), channel=channel)
            elif normalized_msg == '7': # Lang
                user_states[from_number]['state'] = 'language_selection'
                send_unified_message(from_number, LANGUAGE_MENU, channel=channel)
            elif normalized_msg == '8': # Exit
                user_states.pop(from_number, None)
                send_unified_message(from_number, get_localized_message(from_number, "thank_you_goodbye"), channel=channel)
            else:
                send_unified_message(from_number, get_localized_message(from_number, "invalid_option"), channel=channel)
                send_unified_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']), channel=channel)
            return

        # --- HOSPITAL SEARCH BY PINCODE (NEW) ---
        if current_state == 'ask_pincode':
            pincode = incoming_msg.strip()
            if not pincode:
                send_unified_message(from_number, "Please enter a valid pincode (digits only).", channel=channel)
                return
            # Query Supabase hospitals table by pin_code
            try:
                res = supabase.table("hospitals").select("*").eq("pin_code", pincode).execute()
                data_rows = getattr(res, "data", None)
                if not data_rows:
                    send_unified_message(from_number, f"No hospitals found for pincode {pincode}.", channel=channel)
                    # return to main menu
                    user_states[from_number]['state'] = 'main_menu'
                    send_unified_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']), channel=channel)
                    return

                # Build reply
                reply_lines = [f"🏥 Hospitals for pincode {pincode}:\n"]
                for h in data_rows:
                    # use multiple possible keys to be robust with your table naming
                    hosp_name = h.get("hospital_name") or h.get("hospital") or h.get("name") or "N/A"
                    address = h.get("address", "N/A")
                    category = h.get("category", "N/A")
                    # some tables may store 'specializations' or 'specalizations' etc.
                    specializations = h.get("specializations") or h.get("specalizations") or h.get("discipline_sys") or "N/A"
                    pin = h.get("pin_code", "N/A")
                    contact = h.get("contact_no") or h.get("contact") or "N/A"
                    ambulance = h.get("ambulance_no") or h.get("ambulance") or "N/A"
                    bloodbank = h.get("bloodbank_no") or h.get("blood_bank") or "N/A"
                    website = h.get("hospital_website") or h.get("hospital_webs") or h.get("website") or "N/A"
                    beds = h.get("beds_available") or h.get("beds") or "N/A"

                    reply_lines.append(
                        f"🏥 {hosp_name}\n"
                        f"📍 Address: {address}\n"
                        f"🏷 Category: {category}\n"
                        f"🩺 Specializations: {specializations}\n"
                        f"📞 Contact: {contact}\n"
                        f"🚑 Ambulance: {ambulance}\n"
                        f"🩸 Blood Bank: {bloodbank}\n"
                        f"🌐 Website: {website}\n"
                        f"🛏 Beds Available: {beds}\n"
                        "-----------------------------------\n"
                    )

                send_unified_message(from_number, "\n".join(reply_lines), channel=channel)

                # Go back to main menu
                user_states[from_number]['state'] = 'main_menu'
                send_unified_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']), channel=channel)

            except Exception as e:
                logger.error(f"Hospital Lookup Error: {e}")
                send_unified_message(from_number, "Error fetching hospital details. Try again later.", channel=channel)
            return

        # --- DISEASE CHECKER FLOW (10 Steps) ---
        # --- NEW: SMART ONE-SHOT DIAGNOSIS WITH HYPER-LOCAL CONTEXT ---
        if current_state == 'ask_complete_details':
            
            # 1. Log the query to Database (So it counts towards future stats)
            current_db_id = user_states[from_number].get('current_db_id')
            user_city = user_states[from_number].get('city', 'Unknown')
            
            if len(incoming_msg) > 3:
                 if current_db_id: update_disease_record(current_db_id, incoming_msg)
                 else: insert_disease_record(city=user_city, disease=incoming_msg)

            # 2. THE KILLER FEATURE: Fetch Local Outbreak Context
            # We check your database to see what's trending in THIS specific city right now.
            outbreak_alert = ""
            try:
                # Use your existing helper to get stats
                all_city_counts = get_disease_counts_last24h() 
                my_city_stats = all_city_counts.get(user_city, {})
                
                if my_city_stats:
                    # Find the most common disease in this city today
                    top_disease = max(my_city_stats, key=my_city_stats.get)
                    count = my_city_stats[top_disease]
                    
                    # If we have significant data (e.g., >2 cases), flag it for the AI
                    if count > 2: 
                        outbreak_alert = f"[SYSTEM ALERT: High cases of '{top_disease}' detected in {user_city} today. Check if patient symptoms match this outbreak.]"
                        logger.info(f"Outbreak Context Injected: {outbreak_alert}")
            except Exception as e:
                logger.error(f"Outbreak context error: {e}")

            send_unified_message(from_number, "🔍 Analyzing your symptoms against local health trends...", channel=channel)
            
            # 3. Inject Context into the AI Prompt
            # The User sees: "I have fever"
            # The AI sees: "I have fever [SYSTEM ALERT: High cases of 'Dengue' detected in Govindpur...]"
            final_input = f"{incoming_msg} {outbreak_alert}"
            
            # 4. Call Rasa Action (Reuse existing intent structure)
            rasa_payload = f'/check_disease{{"patient_details": "{final_input}"}}'
            
            try:
                bot_msgs = call_rasa(rasa_payload, from_number, lang_code=current_lang)
                for txt in bot_msgs:
                    send_unified_message(from_number, txt, channel=channel)
                
                send_unified_message(from_number, MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en']), channel=channel)
                user_states[from_number]['state'] = 'awaiting_ai_choice'
            except: pass
            return

        # --- MEDICINE INFO ---
        # --- MEDICINE INFO BLOCK ---
        if current_state == 'ask_medicine_name':
            medicine_name = incoming_msg.strip()

            send_unified_message(from_number, get_localized_message(from_number, "processing_medicine"), channel=channel)

            rasa_payload = f'/check_medicine{{"medicine_name": "{medicine_name}"}}'
            try:
                bot_msgs = call_rasa(rasa_payload, from_number, lang_code=current_lang)
                for txt in bot_msgs:
                    send_unified_message(from_number, txt, channel=channel)

                # NEW → Show Medicine Closing Menu
                send_unified_message(from_number, MULTILINGUAL_MED_CLOSING.get(current_lang), channel=channel)

                # Switch to medicine-choice state
                user_states[from_number]['state'] = 'awaiting_med_choice'

            except:
                send_unified_message(from_number, "Error occurred. Try again.", channel=channel)
            return


        # --- MEDICINE CLOSING OPTIONS ---
        if current_state == 'awaiting_med_choice':

            # Option 1 → Ask about another medicine
            if normalized_msg == '1':
                user_states[from_number]['state'] = 'ask_medicine_name'
                send_unified_message(from_number, get_localized_message(from_number, "ask_medicine_name"), channel=channel)
                return

            # Option 2 → Return to Medicine Menu
            if normalized_msg == '2':
                user_states[from_number]['state'] = 'medicine_menu'
                send_unified_message(from_number, med_menu.get(current_lang, med_menu['en']), channel=channel)
                return

            # Handle invalid input
            send_unified_message(from_number, "Invalid option.\n" + MULTILINGUAL_MED_CLOSING.get(current_lang), channel=channel)
            return

        # --- AI CHOICE ---
        if current_state == 'awaiting_ai_choice':
            if normalized_msg == '2':
                user_states[from_number]['state'] = 'in_rasa_conversation'
                send_unified_message(from_number, get_localized_message(from_number, "entering_ai_assistant"), channel=channel)
            elif normalized_msg == '3':
                user_states[from_number]['state'] = 'main_menu'
                send_unified_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']), channel=channel)
            elif normalized_msg == '1': # Detailed Info Logic
                send_unified_message(from_number, "Generating detailed explanation...", channel=channel)
                history = get_last_20_messages(from_number)
                last_query = "Explain details."
                for msg in reversed(history):
                    if msg['sender'] == 'user' and msg['text'].strip() not in ['1', '2', '3']:
                        last_query = msg['text']
                        break
                
                try:
                    bot_msgs = call_rasa(last_query, from_number, lang_code=current_lang, detailed=True)
                    for txt in bot_msgs:
                        send_unified_message(from_number, txt, channel=channel)
                    send_unified_message(from_number, MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en']), channel=channel)
                except: pass
            return
        
        # --- VACCINE SPECIFIC CHOICE ---
        if current_state == 'awaiting_vacc_choice':
    
            if normalized_msg == '1':   # Ask details about specific vaccine
                user_states[from_number]['state'] = 'ask_specific_vaccine'
                send_unified_message(from_number, "Please type the vaccine name you want details about:", channel=channel)
                return

            if normalized_msg == '2':   # Return to vaccination menu
                user_states[from_number]['state'] = 'vaccination_menu'
                send_whatsapp_message(from_number, vacc_menu.get(current_lang, vacc_menu['en']))
                return

            
        # --- HANDLE SPECIFIC VACCINE DETAIL REQUEST ---
        if current_state == 'ask_specific_vaccine':
            vaccine_name = incoming_msg.strip()

            # Query Supabase for vaccine details in user language
            try:
                result = (
                    supabase.table("vaccine_schedule")
                    .select("*")
                    .ilike("vaccine_name", f"%{vaccine_name}%")
                    .eq("language", current_lang)
                    .execute()
                )

                rows = result.data

                # If no result found in user's language → fallback to English
                if not rows:
                    result = (
                        supabase.table("vaccine_schedule")
                        .select("*")
                        .ilike("vaccine_name", f"%{vaccine_name}%")
                        .eq("language", "en")
                        .execute()
                    )
                    rows = result.data

                if not rows:
                    send_unified_message(from_number, "No such vaccine found. Try another name.", channel=channel)
                    send_unified_message(from_number, MULTILINGUAL_VACC_CLOSING.get(current_lang), channel=channel)
                    user_states[from_number]['state'] = 'awaiting_vacc_choice'
                    return

                reply = ""
                for row in rows:
                    reply += (
                        f"💉 *{row['vaccine_name']}* ({row['dose_name']})\n"
                        f"{row['details']}\n\n"
                    )

                send_unified_message(from_number, reply, channel=channel)

            except Exception as e:
                print(f"[VACCINE DETAIL ERROR]: {e}")
                send_unified_message(from_number, "Database error. Try again later.", channel=channel)

            # Return to vaccination closing menu
            send_unified_message(from_number, MULTILINGUAL_VACC_CLOSING.get(current_lang), channel=channel)
            user_states[from_number]['state'] = 'awaiting_vacc_choice'
            return
        
        
        # ================================
        # SPECIFIC VACCINE DETAILS (MULTILINGUAL)
        # ================================

        if current_state == 'ask_specific_vaccine':
            vaccine_name = incoming_msg.strip()

            # Build language list for DB query
            lang_list = LANG_EQUIVALENCE.get(current_lang, ["en"])

            try:
                # 1️⃣ Try matching vaccine in user's language (multiple variants supported)
                result = (
                    supabase.table("vaccine_schedule")
                    .select("*")
                    .ilike("vaccine_name", f"%{vaccine_name}%")
                    .in_("language", lang_list)
                    .execute()
                )
                rows = result.data

                # 2️⃣ If not found → fallback to English
                if not rows:
                    result = (
                        supabase.table("vaccine_schedule")
                        .select("*")
                        .ilike("vaccine_name", f"%{vaccine_name}%")
                        .in_("language", ["en", "english"])
                        .execute()
                    )
                    rows = result.data

                # 3️⃣ If still nothing found
                if not rows:
                    send_unified_message(
                        from_number,
                        "No such vaccine found. Try another vaccine name.",
                        channel=channel
                    )
                    send_unified_message(
                        from_number,
                        MULTILINGUAL_VACC_CLOSING.get(current_lang),
                        channel=channel
                    )
                    user_states[from_number]['state'] = 'awaiting_vacc_choice'
                    return

                # 4️⃣ Build reply including DETAILS column (not description)
                reply = ""
                for row in rows:
                    reply += (
                        f"💉 *{row['vaccine_name']}* ({row['dose_name']})\n"
                        f"{row['details']}\n\n"
                    )

                send_unified_message(from_number, reply, channel=channel)

            except Exception as e:
                print(f"[VACCINE DETAIL ERROR]: {e}")
                send_unified_message(
                    from_number,
                    "Database error while fetching vaccine details.",
                    channel=channel
                )

            # 5️⃣ Show the vaccination closing menu (options 1 & 2 only)
            send_unified_message(
                from_number,
                MULTILINGUAL_VACC_CLOSING.get(current_lang),
                channel=channel
            )

            # Go back to vaccine closing state
            user_states[from_number]['state'] = 'awaiting_vacc_choice'
            return



        # --- GENERAL CHAT (RASA) ---
        if current_state == 'in_rasa_conversation':
            # prevent 1/2/3 from triggering menu return
            if normalized_msg not in ['1', '2', '3']:
                if normalized_msg in MENU_RETURN_TRIGGER or normalized_msg in MENU_ENTRY_TRIGGER:
                    user_states[from_number]['state'] = 'main_menu'
                    send_unified_message(from_number, MULTILINGUAL_MENUS.get(current_lang), channel=channel)
                    return


            # 2. LOGGING LOGIC (New)
            # Only log if it looks like a real query (longer than 3 chars)
            if len(incoming_msg) > 3:
                current_db_id = user_states[from_number].get('current_db_id')
                user_city = user_states[from_number].get('city', 'Unknown')
                
                # Update existing row (id: 1) or Insert new row (id: 2)
                if current_db_id:
                    update_disease_record(current_db_id, incoming_msg)
                else:
                    # Fallback insert
                    insert_disease_record(city=user_city, disease=incoming_msg)
            try:
                bot_msgs = call_rasa(incoming_msg, from_number, lang_code=current_lang, detailed=False)
                if bot_msgs:
                    for txt in bot_msgs:
                        send_unified_message(from_number, txt, channel=channel)
                    
                    send_unified_message(from_number, MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en']), channel=channel)
                    user_states[from_number]['state'] = 'awaiting_ai_choice'
                else:
                    send_unified_message(from_number, get_localized_message(from_number, "rasa_no_response"), channel=channel)
            except: pass
            return

    except Exception as e:
        logger.error(f"Core Logic Error: {e}")

# --- DASHBOARD ROUTE ---
@app.route("/dashboard")
def dashboard():
    try:
        # 1. Fetch from 'disease_count' instead of 'user_chat_media'
        response = supabase.table("disease_count").select("*").execute()
        df = pd.DataFrame(response.data)
        
        if df.empty:
            return "No data yet."

        # 2. Calculate Metrics based on your Hardcoded SQL Data
        # Since 'disease_count' doesn't have phone numbers, we estimate users
        # For this demo, let's assume 1 row = 1 unique interaction
        total_messages = len(df)
        total_users = df['city'].nunique() # Proxy: counting unique cities as users for demo
        active_24h = total_messages # Showing all 50 messages as active

        # 3. Keyword Analysis for the HTML List
        keywords = ["fever", "dengue", "malaria", "typhoid", "covid", "cough"]
        disease_data = {}
        
        if 'disease' in df.columns:
            # Count directly from the 'disease' column
            for disease in df['disease'].dropna():
                d_lower = disease.lower()
                for k in keywords:
                    if k in d_lower:
                        disease_data[k.capitalize()] = disease_data.get(k.capitalize(), 0) + 1

        return render_template("dashboard.html", 
                               total_users=total_users, 
                               active_24h=active_24h, 
                               total_messages=total_messages, 
                               disease_data=disease_data)

    except Exception as e:
        return f"Dashboard Error: {e}"

# --- API: Total disease count (last 24 hours) for pie chart ---
@app.route("/api/disease-pie-24h")
def disease_pie_24h():
    try:
        counts = get_total_disease_counts_last24h()
        return jsonify(counts), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- API: City-wise disease count (last 24 hours) ---
@app.route("/api/disease-city-24h")
def disease_city_24h():
    try:
        counts = get_disease_counts_last24h()
        return jsonify(counts), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/piechart")
def piechart():
    try:
        # 1. Query the 'disease_count' table (where your hardcoded data is)
        # We REMOVED the .gte() time filter so it fetches ALL data
        response = supabase.table("disease_count").select("disease").execute()
        data = response.data
        
        if not data:
            # Fallback image if table is truly empty
            plt.figure(figsize=(6, 6))
            plt.text(0.5, 0.5, "No Data in DB", ha="center", va="center")
            buf = io.BytesIO()
            plt.savefig(buf, format="png")
            buf.seek(0)
            plt.close()
            return Response(buf.getvalue(), mimetype="image/png")
        
        # 2. Count Diseases
        counts = {}
        for row in data:
            disease = row.get("disease")
            if disease:
                # Normalize text (e.g., "Fever" vs "fever")
                d_name = disease.strip().title()
                counts[d_name] = counts.get(d_name, 0) + 1
        
        # 3. Sort & Filter Top 10
        sorted_counts = dict(sorted(counts.items(), key=lambda item: item[1], reverse=True)[:10])
        
        # 4. Generate Pie Chart
        plt.figure(figsize=(7, 7))
        # Using a colorful palette
        colors = plt.cm.Paired.colors 
        plt.pie(
            sorted_counts.values(), 
            labels=sorted_counts.keys(), 
            autopct="%1.1f%%", 
            startangle=140, 
            colors=colors
        )
        plt.title("Disease Distribution (All Data)")
        
        # 5. Output Image
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches='tight')
        buf.seek(0)
        plt.close()
        return Response(buf.getvalue(), mimetype="image/png")

    except Exception as e:
        logger.error(f"Pie Chart Error: {e}")
        return "Error", 500

@app.route("/api/city-bar")
def city_bar():
    try:
        # 1. Query 'disease_count' (Fetching ALL records)
        response = supabase.table("disease_count").select("city").execute()
        data = response.data
        
        if not data:
            return "No Data", 404
        
        # 2. Count Cities
        counts = {}
        for row in data:
            city = row.get("city")
            if city:
                # Clean up city name (e.g., "Govindpur, Odisha" -> "Govindpur")
                city_name = city.split(',')[0].strip().title()
                counts[city_name] = counts.get(city_name, 0) + 1
            
        # 3. Sort Top 10
        sorted_cities = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
        cities = [x[0] for x in sorted_cities]
        vals = [x[1] for x in sorted_cities]

        # 4. Generate Bar Chart
        plt.figure(figsize=(10, 6))
        # Use Red color to highlight "Hotspots"
        bars = plt.bar(cities, vals, color='#d62728') 
        
        # Add numbers on top of bars
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height,
                     f'{int(height)}',
                     ha='center', va='bottom')

        plt.xticks(rotation=45, ha="right")
        plt.title("Most Affected Cities (All Data)")
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        plt.close()
        return Response(buf.getvalue(), mimetype="image/png")

    except Exception as e:
        logger.error(f"Bar Chart Error: {e}")
        return "Error", 500
    
@app.route("/api/ai-insight")
def ai_insight():
    """
    Uses Gemini to analyze ALL data in the disease_count table.
    """
    try:
        # 1. Fetch ALL data (Removed time filter)
        response = supabase.table("disease_count").select("*").execute()
        rows = response.data
        
        if not rows:
            return jsonify({"insight": "No data available to generate insights."})

        # 2. aggregate data for AI (City -> Disease -> Count)
        city_disease_map = {}
        for row in rows:
            city = row.get("city", "Unknown")
            if city:
                city = city.split(',')[0].strip().title() # Clean "Govindpur, Odisha"
            
            disease = row.get("disease", "Unknown")
            if disease:
                disease = disease.strip().title()

            if city not in city_disease_map:
                city_disease_map[city] = {}
            
            city_disease_map[city][disease] = city_disease_map[city].get(disease, 0) + 1

        # 3. Prepare prompt for Gemini
        data_summary = str(city_disease_map)
        
        prompt = (
            f"Analyze this health data: {data_summary}. "
            "Identify if there are any outbreaks (high frequency of a specific disease in a specific city). "
            "Ignore minor counts (less than 3). "
            "Return a short, urgent summary for a dashboard. "
            "Format: '⚠️ **Possible Outbreak:** [Details]'. If normal, say '✅ Status Normal'."
        )

        # 4. Call Gemini
        if not GEMINI_API_KEY:
            return jsonify({"insight": "⚠️ Gemini API Key Missing in .env"})

        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        insight_text = response.text if response else "AI Analysis Unavailable."
        
        return jsonify({"insight": insight_text})

    except Exception as e:
        logger.error(f"AI Insight Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    data = request.get_json()
    if not data: return "Error", 400
    
    if data.get("entry"):
        entry = data["entry"][0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        if value.get("messages"):
            msg = value["messages"][0]
            sender = msg["from"]
            m_type = msg["type"]
            text = ""
            media_url = None
            location_data = None # New variable for coordinates
            
            if m_type == "text": 
                text = msg["text"]["body"]
            elif m_type == "button": 
                text = msg["button"]["payload"]
            
            # --- NEW: Location Handling ---
            elif m_type == "location":
                loc = msg.get("location", {})
                location_data = {
                    "latitude": loc.get("latitude"),
                    "longitude": loc.get("longitude")
                }
            # ------------------------------

            elif m_type in ["audio", "voice"]:
                media_id = msg.get(m_type, {}).get("id")
                try:
                    r = requests.get(f"https://graph.facebook.com/v19.0/{media_id}", headers={"Authorization": f"Bearer {META_ACCESS_TOKEN}"})
                    media_url = r.json().get("url")
                except: media_url = None
            elif m_type == "image":
                media_id = msg.get("image", {}).get("id")
                try:
                    r = requests.get(f"https://graph.facebook.com/v19.0/{media_id}", headers={"Authorization": f"Bearer {META_ACCESS_TOKEN}"})
                    media_url = r.json().get("url")
                except: media_url = None

            # Pass 'location_data' to the thread
            threading.Thread(target=process_core_logic, 
                             kwargs={
                                 'from_number': sender, 
                                 'incoming_msg': text, 
                                 'msg_type': m_type, 
                                 'channel': 'whatsapp', 
                                 'media_url': media_url,
                                 'location_data': location_data  # Passing coordinates
                             }).start()

    return jsonify({"status": "ok"}), 200

# --- API: BROADCAST ALERT TO ALL USERS ---
@app.route("/api/broadcast-alert", methods=['POST'])
def broadcast_alert():
    try:
        # 1. Get the AI Insight Text (from the frontend or regenerate it)
        # For safety, let's regenerate the latest insight
        insight_response = ai_insight() # Calls your existing function
        insight_text = insight_response.json.get("insight", "Health Alert")
        
        if "Normal" in insight_text:
            return jsonify({"status": "aborted", "message": "Status is Normal. No alert sent."})

        # 2. Generate Charts to Temp Files
        # -- Pie Chart --
        pie_path = os.path.join(tempfile.gettempdir(), "alert_pie.png")
        # (Reuse your piechart logic here to save to file instead of returning bytes)
        # For brevity, I'm calling the existing route logic abstractly, 
        # but in production, you should refactor the plotting code into a reusable function.
        # ... [Imagine plotting code here saving to pie_path] ...
        # ... Let's assume you copy-paste the matplotlib logic from 'piechart' route here ...
        # ... and use plt.savefig(pie_path) ...
        
        # -- Bar Chart --
        bar_path = os.path.join(tempfile.gettempdir(), "alert_bar.png")
        # ... [Imagine plotting code here saving to bar_path] ...

        # 3. Upload Images to Meta
        # (Since we can't refactor your whole code in one go, 
        #  Use this quick hack: Call your own local APIs to get the bytes!)
        pie_bytes = requests.get("http://localhost:5000/api/piechart").content
        with open(pie_path, "wb") as f: f.write(pie_bytes)
        
        bar_bytes = requests.get("http://localhost:5000/api/city-bar").content
        with open(bar_path, "wb") as f: f.write(bar_bytes)

        pie_media_id = upload_image_to_meta(pie_path)
        bar_media_id = upload_image_to_meta(bar_path)

        # 4. Fetch All Users (Unique Phone Numbers)
        response = supabase.table("user_chat_media").select("phone_num").execute()
        users = list(set([row['phone_num'] for row in response.data])) # Unique numbers

        # 5. Send Broadcast Loop
        count = 0
        for user_phone in users:
            # Send Text Warning
            send_whatsapp_message(user_phone, f"🚨 *PUBLIC HEALTH ALERT* 🚨\n\n{insight_text}")
            
            # Send Charts
            if pie_media_id:
                send_whatsapp_image(user_phone, pie_media_id, caption="Current Disease Spread")
            if bar_media_id:
                send_whatsapp_image(user_phone, bar_media_id, caption="Affected Locations")
            
            count += 1
            
        return jsonify({"status": "success", "message": f"Alert sent to {count} users."})

    except Exception as e:
        logger.error(f"Broadcast Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/sms", methods=["POST"])
def sms_webhook():
    try:
        sender = request.values.get('From', '')
        text = request.values.get('Body', '')
        num_media = int(request.values.get('NumMedia', 0))
        
        msg_type = 'text'
        media_url = None

        # Check for Media (MMS)
        if num_media > 0:
            media_content_type = request.values.get('MediaContentType0', '')
            media_url = request.values.get('MediaUrl0', '')
            
            if media_content_type.startswith('image/'):
                msg_type = 'image'
            elif media_content_type.startswith('audio/'):
                msg_type = 'audio'
        
        logger.info(f"SMS from {sender}, Type: {msg_type}, Media: {media_url}")

        threading.Thread(target=process_core_logic, 
                         kwargs={'from_number': sender, 'incoming_msg': text, 'msg_type': msg_type, 'channel': 'sms', 'media_url': media_url}).start()

        return str(""), 200
    except Exception as e:
        logger.error(f"SMS Webhook Error: {e}")
        return "Error", 500

@app.route("/whatsapp", methods=['GET'])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Invalid", 403

if __name__ == "__main__":
    app.run(port=5000, debug=True)