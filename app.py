# app.py
from flask import Flask, request, jsonify, render_template, Response
import requests
import os
import logging
import threading
import tempfile
import io
import math
import datetime
from datetime import timezone, timedelta
import pandas as pd

# --- AI & Media Imports ---
from langdetect import detect, DetectorFactory 
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv
import whisper
from gtts import gTTS
import subprocess

# --- MATPLOTLIB SETUP (For Server-Side Charts) ---
import matplotlib
matplotlib.use('Agg') # Required for server (no screen)
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

MENU_ENTRY_TRIGGER = ['hi', 'hello', 'menu', 'start'] 
MENU_RETURN_TRIGGER = ['back', 'main menu', 'Back', 'Return', 'return', 'Exit', 'exit']

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
        
        # --- Disease Checker Prompts ---
        "ask_age": "Step 1/10: Please enter Age (e.g., 25).",
        "ask_weight": "Step 2/10: Enter Weight (e.g., 60kg).",
        "ask_gender": "Step 3/10: Enter Gender (Male/Female).",
        "ask_reports": "Step 4/10: Recent Reports? (Type 'None' if not).",
        "ask_eating": "Step 5/10: Describe diet.",
        "ask_meds": "Step 6/10: Current medications? (Type 'None' if not).",
        "ask_habits": "Step 7/10: Habits like smoking/alcohol? (Type 'None' if not).",
        "ask_disability": "Step 8/10: Disabilities? (Type 'None' if not).",
        "ask_history": "Step 9/10: Family History?",
        "ask_current_symptoms": "Step 10/10: Describe current SYMPTOMS:",
        "processing_diagnosis": "Analyzing symptoms... Please wait.",
        
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
        
        # --- Disease Checker Prompts ---
        "ask_age": "चरण 1/10: कृपया आयु दर्ज करें (जैसे, 25)।",
        "ask_weight": "चरण 2/10: वजन दर्ज करें (जैसे, 60 किग्रा)।",
        "ask_gender": "चरण 3/10: लिंग दर्ज करें (पुरुष/महिला)।",
        "ask_reports": "चरण 4/10: हाल की रिपोर्ट? (यदि नहीं, तो 'कोई नहीं' टाइप करें)।",
        "ask_eating": "चरण 5/10: आहार का वर्णन करें।",
        "ask_meds": "चरण 6/10: वर्तमान दवाएं? (यदि नहीं, तो 'कोई नहीं' टाइप करें)।",
        "ask_habits": "चरण 7/10: धूम्रपान/शराब जैसी आदतें? (यदि नहीं, तो 'कोई नहीं' टाइप करें)।",
        "ask_disability": "चरण 8/10: विकलांगताएं? (यदि नहीं, तो 'कोई नहीं' टाइप करें)।",
        "ask_history": "चरण 9/10: पारिवारिक इतिहास?",
        "ask_current_symptoms": "चरण 10/10: वर्तमान लक्षणों का वर्णन करें:",
        "processing_diagnosis": "लक्षणों का विश्लेषण किया जा रहा है... कृपया प्रतीक्षा करें।",

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

        # --- Disease Checker Prompts ---
        "ask_age": "ধাপ 1/10: দয়া করে বয়স লিখুন (যেমন, 25)।",
        "ask_weight": "ধাপ 2/10: ওজন লিখুন (যেমন, 60 কেজি)।",
        "ask_gender": "ধাপ 3/10: লিঙ্গ লিখুন (পুরুষ/মহিলা)।",
        "ask_reports": "ধাপ 4/10: সাম্প্রতিক রিপোর্ট? (যদি না থাকে, 'কোনো নেই' টাইপ করুন)।",
        "ask_eating": "ধাপ 5/10: খাদ্য বর্ণনা করুন।",
        "ask_meds": "ধাপ 6/10: বর্তমান ওষুধ? (যদি না থাকে, 'কোনো নেই' টাইপ করুন)।",
        "ask_habits": "ধাপ 7/10: ধূমপান/মদ্যপান এর মতো অভ্যাস? (যদি না থাকে, 'কোনো নেই' টাইপ করুন)।",
        "ask_disability": "ধাপ 8/10: প্রতিবন্ধকতা? (যদি না থাকে, 'কোনো নেই' টাইপ করুন)।",
        "ask_history": "ধাপ 9/10: পারিবারিক ইতিহাস?",
        "ask_current_symptoms": "ধাপ 10/10: বর্তমান লক্ষণগুলি বর্ণনা করুন:",
        "processing_diagnosis": "লক্ষণ বিশ্লেষণ করা হচ্ছে... অনুগ্রহ করে অপেক্ষা করুন।",

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

        # --- Disease Checker Prompts ---
        "ask_age": "ପଦକ୍ଷେପ 1/10: ଦୟାକରି ବୟସ୍ ଦାଖଲ କରନ୍ତୁ (ଉଦାହରଣ ସ୍ୱରୂପ, 25)।",
        "ask_weight": "ପଦକ୍ଷେପ 2/10: ଓଜନ ଦାଖଲ କରନ୍ତୁ (ଉଦାହରଣ ସ୍ୱରୂପ, 60 କିଲୋଗ୍ରାମ୍)।",
        "ask_gender": "ପଦକ୍ଷେପ 3/10: ଲିଙ୍ଗ ଦାଖଲ କରନ୍ତୁ (ପୁରୁଷ/ମହିଳା)।",
        "ask_reports": "ପଦକ୍ଷେପ 4/10: ସাম্প୍ରତିକ ରିପୋର୍ଟ? (ନଥିଲେ, 'କିଛି ନାହିଁ' ଟାଇପ୍ କରନ୍ତୁ)।",
        "ask_eating": "ପଦକ୍ଷେପ 5/10: ଖାଦ୍ୟ ବର୍ଣ୍ଣନା କରନ୍ତୁ।",
        "ask_meds": "ପଦକ୍ଷେପ 6/10: ବର୍ତ୍ତମାନ ଔଷଧ? (ନଥିଲେ, 'କିଛି ନାହିଁ' ଟାଇପ୍ କରନ୍ତୁ)।",
        "ask_habits": "ପଦକ୍ଷେପ 7/10: ଧୁମପାନ/ମଦ୍ୟପାନ ଭଳି ଅଭ୍ୟାସ? (ନଥିଲେ, 'କିଛି ନାହିଁ' ଟାଇପ୍ କରନ୍ତୁ)।",
        "ask_disability": "ପଦକ୍ଷେପ 8/10: ଅସମର୍ଥତା? (ନଥିଲେ, 'କିଛି ନାହିଁ' ଟାଇପ୍ କରନ୍ତୁ)।",
        "ask_history": "ପଦକ୍ଷେପ 9/10: ପରିବାର ଇତିହାସ?",
        "ask_current_symptoms": "ପଦକ୍ଷେପ 10/10: ବର୍ତ୍ତମାନର ଲକ୍ଷଣଗୁଡ଼ିକୁ ବର୍ଣ୍ଣନା କରନ୍ତୁ:",
        "processing_diagnosis": "ଲକ୍ଷଣଗୁଡ଼ିକୁ ବିଶ୍ଳେଷଣ କରାଯାଉଛି... ଦୟାକରି ପ୍ରତୀକ୍ଷା କରନ୍ତୁ।",

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
    'en': "This response is completed.\nSelect any one option:\n1. Do you want to ask anything more about something else?\n2. Would you like to go back to main menu?\n3. Get more detailed information about this.",
    'hi': "उत्तर पूरा हो गया है।\nकृपया एक विकल्प चुनें:\n1. क्या आप इसके बारे में या किसी अन्य विषय पर और पूछना चाहते हैं?\n2. क्या आप मुख्य मेनू पर वापस जाना चाहते हैं?\n3. इस बारे में अधिक विस्तृत जानकारी प्राप्त करें।",
    'bn': "উত্তর সম্পূর্ণ হয়েছে।\nএকটি বিকল্প নির্বাচন করুন:\n1. আপনি কি এ সম্পর্কে বা অন্য কিছু সম্পর্কে আরও জানতে চান?\n2. আপনি কি প্রধান মেনুতে ফিরে যেতে চান?\n3. এর সম্পর্কে আরও বিস্তারিত তথ্য পান।",
    'or': "ଉତ୍ତର ସମାପ୍ତ ହୋଇଛି।\nଦୟାକରି ଏକ ବିକଳ୍ପ ବାଛନ୍ତୁ:\n1. ଆପଣ ଏହା ବିଷୟରେ କିମ୍ବା ଅନ୍ୟ କିଛି ବିଷୟରେ ଅଧିକ ପଚାରିବାକୁ ଚାହାନ୍ତି କି?\n2. ଆପଣ ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବାକୁ ଚାହାନ୍ତି କି?\n3. ଏହା ବିଷୟରେ ଅଧିକ ବିସ୍ତୃତ ସୂଚନା ପାଇଁ।"
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
        r = requests.get(media_url, headers={"Authorization": f"Bearer {META_ACCESS_TOKEN}"}, stream=True, timeout=30)
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
        mp3_path = os.path.join("/tmp", f"tts_{int(datetime.now(timezone.utc).timestamp())}.mp3")
        tts = gTTS(text=text, lang=gtts_lang)
        tts.save(mp3_path)

        # convert mp3 -> ogg (opus) for WhatsApp voice note
        ogg_path = mp3_path.replace(".mp3", ".ogg")
        subprocess.run(["ffmpeg", "-y", "-i", mp3_path, "-c:a", "libopus", "-b:a", "64k", ogg_path],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # cleanup mp3 (optional)
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
        # We use a simpler method that lets requests handle the multipart form data correctly.
        with open(file_path, "rb") as f:
            files = {
                'file': (os.path.basename(file_path), f, 'audio/ogg'),
                'messaging_product': (None, 'whatsapp') # This part is crucial
            }
            r = requests.post(url, headers=headers, files=files)
            r.raise_for_status() # Raise an exception for 4xx/5xx errors
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
            r2.raise_for_status()
            # Log bot audio to DB
            insert_message(to_number, "bot", text="[Audio Message]", media=[{"id": media_id}], language="en")
            return True
        else:
            logger.error(f"Upload failed. No media ID returned. Response: {r.text}")

    except requests.exceptions.HTTPError as e:
        logger.error(f"Audio Upload/Send HTTP Error: {e.response.text}")
    except Exception as e:
        logger.error(f"Audio Send Error: {e}")
        
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
        r = requests.post(RASA_WEBHOOK_URL, json=payload, timeout=180)
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
        
        return getattr(resp, "text", str(resp))

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

# ---------------------------------------------------------
# 4. MAIN LOGIC
# ---------------------------------------------------------
# CORE LOGIC (SHARED BY WHATSAPP & SMS)
# ---------------------------------------------------------
def process_core_logic(from_number, incoming_msg, msg_type, channel, media_url=None, location_data=None):
    try:
        # 1. State Init
        if from_number not in user_states:
            user_states[from_number] = {'state': 'language_selection', 'lang': 'en', 'data': {}}
        
        current_state = user_states[from_number]['state']
        current_lang = user_states[from_number]['lang']
        normalized_msg = incoming_msg.lower().strip() if incoming_msg else ""

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
                        
                        # Send Reply (Text for SMS, Audio for WhatsApp if possible)
                        send_unified_message(from_number, reply, channel=channel)
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

        # --- MAIN MENU ---
        if current_state == 'main_menu':
            if normalized_msg == '1':
                user_states[from_number]['state'] = 'in_rasa_conversation'
                send_unified_message(from_number, get_localized_message(from_number, "entering_ai_assistant"), channel=channel)
            elif normalized_msg == '2':
                send_unified_message(from_number, get_localized_message(from_number, "vaccination_selected"), channel=channel)
            elif normalized_msg == '3': # Disease Checker
                user_states[from_number]['state'] = 'ask_age'
                user_states[from_number]['data'] = {}
                send_unified_message(from_number, get_localized_message(from_number, "ask_age"), channel=channel)
            elif normalized_msg == '4': # Medicine Info
                user_states[from_number]['state'] = 'ask_medicine_name'
                send_unified_message(from_number, get_localized_message(from_number, "ask_medicine_name"), channel=channel)
            elif normalized_msg == '5': # Center
                send_unified_message(from_number, get_localized_message(from_number, "health_center_selected"), channel=channel)
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

        # --- DISEASE CHECKER FLOW (10 Steps) ---
        if current_state == 'ask_age':
            user_states[from_number]['data']['age'] = incoming_msg
            user_states[from_number]['state'] = 'ask_weight'
            send_unified_message(from_number, get_localized_message(from_number, "ask_weight"), channel=channel)
            return
        
        # ... (Abbreviating intermediate steps for brevity, functionality is identical) ...
        # If you need steps 2-9 explicitly, copy from your WhatsApp logic, just change send_whatsapp_message -> send_unified_message
        
        if current_state == 'ask_weight':
            user_states[from_number]['data']['weight'] = incoming_msg
            user_states[from_number]['state'] = 'ask_gender'
            send_unified_message(from_number, get_localized_message(from_number, "ask_gender"), channel=channel)
            return
        if current_state == 'ask_gender':
            user_states[from_number]['data']['gender'] = incoming_msg
            user_states[from_number]['state'] = 'ask_reports'
            send_unified_message(from_number, get_localized_message(from_number, "ask_reports"), channel=channel)
            return
        if current_state == 'ask_reports':
            user_states[from_number]['data']['reports'] = incoming_msg
            user_states[from_number]['state'] = 'ask_eating'
            send_unified_message(from_number, get_localized_message(from_number, "ask_eating"), channel=channel)
            return
        if current_state == 'ask_eating':
            user_states[from_number]['data']['eating'] = incoming_msg
            user_states[from_number]['state'] = 'ask_meds'
            send_unified_message(from_number, get_localized_message(from_number, "ask_meds"), channel=channel)
            return
        if current_state == 'ask_meds':
            user_states[from_number]['data']['meds'] = incoming_msg
            user_states[from_number]['state'] = 'ask_habits'
            send_unified_message(from_number, get_localized_message(from_number, "ask_habits"), channel=channel)
            return
        if current_state == 'ask_habits':
            user_states[from_number]['data']['habits'] = incoming_msg
            user_states[from_number]['state'] = 'ask_disability'
            send_unified_message(from_number, get_localized_message(from_number, "ask_disability"), channel=channel)
            return
        if current_state == 'ask_disability':
            user_states[from_number]['data']['disability'] = incoming_msg
            user_states[from_number]['state'] = 'ask_history'
            send_unified_message(from_number, get_localized_message(from_number, "ask_history"), channel=channel)
            return
        if current_state == 'ask_history':
            user_states[from_number]['data']['history'] = incoming_msg
            user_states[from_number]['state'] = 'ask_current_symptoms'
            send_unified_message(from_number, get_localized_message(from_number, "ask_current_symptoms"), channel=channel)
            return

        if current_state == 'ask_current_symptoms':
            user_states[from_number]['data']['current_symptoms'] = incoming_msg
            d = user_states[from_number]['data']
            data_str = f"Age: {d.get('age')}, Weight: {d.get('weight')}, Gender: {d.get('gender')}, History: {d.get('history')}, Symptoms: {incoming_msg}"
            
            send_unified_message(from_number, get_localized_message(from_number, "processing_diagnosis"), channel=channel)
            
            rasa_payload = f'/check_disease{{"patient_details": "{data_str}"}}'
            try:
                bot_msgs = call_rasa(rasa_payload, from_number, lang_code=current_lang)
                for txt in bot_msgs:
                    send_unified_message(from_number, txt, channel=channel)
                
                send_unified_message(from_number, MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en']), channel=channel)
                user_states[from_number]['state'] = 'awaiting_ai_choice'
            except: pass
            return

        # --- MEDICINE INFO ---
        if current_state == 'ask_medicine_name':
            medicine_name = incoming_msg
            send_unified_message(from_number, get_localized_message(from_number, "processing_medicine"), channel=channel)
            
            rasa_payload = f'/check_medicine{{"medicine_name": "{medicine_name}"}}'
            try:
                bot_msgs = call_rasa(rasa_payload, from_number, lang_code=current_lang)
                for txt in bot_msgs:
                    send_unified_message(from_number, txt, channel=channel)
                
                send_unified_message(from_number, MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en']), channel=channel)
                user_states[from_number]['state'] = 'awaiting_ai_choice'
            except: pass
            return

        # --- AI CHOICE ---
        if current_state == 'awaiting_ai_choice':
            if normalized_msg == '1':
                user_states[from_number]['state'] = 'in_rasa_conversation'
                send_unified_message(from_number, get_localized_message(from_number, "entering_ai_assistant"), channel=channel)
            elif normalized_msg == '2':
                user_states[from_number]['state'] = 'main_menu'
                send_unified_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']), channel=channel)
            elif normalized_msg == '3': # Detailed Info Logic
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

        # --- GENERAL CHAT (RASA) ---
        if current_state == 'in_rasa_conversation':
            if normalized_msg in MENU_RETURN_TRIGGER:
                user_states[from_number]['state'] = 'main_menu'
                send_unified_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']), channel=channel)
                return
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

@app.route("/dashboard")
def dashboard():
    # Fetch Data for HTML Counters
    try:
        response = supabase.table("user_chat_media").select("*").execute()
        df = pd.DataFrame(response.data)
        if df.empty: return "No data yet."
        
        df['time_stamp'] = pd.to_datetime(df['time_stamp'])
        total_users = df['phone_num'].nunique()
        total_messages = len(df)
        
        last_24h = datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=24)
        last_24h = last_24h.replace(tzinfo=None) 
        df['time_stamp_naive'] = df['time_stamp'].dt.tz_localize(None)
        active_24h = df[df['time_stamp_naive'] > last_24h]['phone_num'].nunique()

        # Keyword Analysis
        keywords = ["fever", "dengue", "malaria", "typhoid", "covid", "cough"]
        disease_data = {}
        user_msgs = df[df['phone_num'].notnull()]['user_message'].dropna().str.lower()
        for word in keywords:
            count = user_msgs.str.contains(word).sum()
            if count > 0: disease_data[word.capitalize()] = int(count)

        return render_template("dashboard.html", total_users=total_users, active_24h=active_24h, total_messages=total_messages, disease_data=disease_data)
    except Exception as e: return f"Dashboard Error: {e}"

@app.route("/api/piechart")
def piechart():
    try:
        response = supabase.table("user_chat_media").select("user_message").execute()
        data = response.data
        if not data: return "No Data", 404
        
        keywords = ["fever", "dengue", "malaria", "typhoid", "covid", "flu"]
        counts = {}
        for row in data:
            msg = str(row.get('user_message', '')).lower()
            for word in keywords:
                if word in msg: counts[word] = counts.get(word, 0) + 1
        
        if not counts: return "No Disease Data", 404
        
        plt.figure(figsize=(6, 6))
        plt.pie(counts.values(), labels=counts.keys(), autopct="%1.1f%%")
        plt.title("Disease Trends")
        
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        plt.close()
        return Response(buf.getvalue(), mimetype="image/png")
    except: return "Error", 500

@app.route("/api/city-bar")
def city_bar():
    # Using User Phone as 'City' proxy for demo
    try:
        response = supabase.table("user_chat_media").select("phone_num").execute()
        data = response.data
        if not data: return "No Data", 404
        
        counts = {}
        for row in data:
            u = row.get('phone_num', 'Unknown')
            counts[u] = counts.get(u, 0) + 1
            
        plt.figure(figsize=(8, 5))
        plt.bar(list(counts.keys())[:5], list(counts.values())[:5])
        plt.title("Top Active Users")
        
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        plt.close()
        return Response(buf.getvalue(), mimetype="image/png")
    except: return "Error", 500

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