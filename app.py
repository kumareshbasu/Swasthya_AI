# app.py
from flask import Flask, request, jsonify
import requests
import os
import logging
import threading
from langdetect import DetectorFactory 
import google.generativeai as genai
from datetime import datetime, timezone
from supabase import create_client, Client
from dotenv import load_dotenv
import whisper
from gtts import gTTS
import subprocess

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
""",
    'hi': "\n1. सामान्य स्वास्थ्य\n2. टीकाकरण\n3. बीमारी जांच\n4. दवा की जानकारी 💊\n5. स्वास्थ्य केंद्र\n6. हमारे बारे में\n7. Change Language / भाषा बदलें / ভাষা পরিবর্তন / ଭାଷା ପରିବର୍ତ୍ତନ\n8. बाहर निकलें",
    'bn': "\n1. সাধারণ স্বাস্থ্য\n2. টিকা\n3. রোগ পরীক্ষক\n4. ওষুধের তথ্য 💊\n5. স্বাস্থ্য কেন্দ্র\n6. আমাদের সম্পর্কে\n7. Change Language / भाषा बदलें / ভাষা পরিবর্তন / ଭାଷା ପରିବର୍ତ୍ତନ\n8. প্রস্থান",
    'or': "\n1. ସାଧାରଣ ସ୍ୱାସ୍ଥ୍ୟ\n2. ଟୀକାକରଣ\n3. ରୋଗ ଯାଞ୍ଚ\n4. ଔଷଧ ସୂଚନା 💊\n5. ସ୍ୱାସ୍ଥ୍ୟ କେନ୍ଦ୍ର\n6. ଆମ ବିଷୟରେ\n7. Change Language / भाषा बदलें / ভাষা পরিবর্তন / ଭାଷା ପରିବର୍ତ୍ତନ\n8. ବାହାରନ୍ତୁ"
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
Select Language / भाषा चुनें:
1. English
2. हिंदी (Hindi)
3. বাংলা (Bengali)
4. ଓଡ଼ିଆ (Odia)
"""

MULTILINGUAL_AI_CLOSING = {
    'en': "This response is completed.\nSelect any one option:\n1. Do you want to ask anything more about this or something else?\n2. Would you like to go back to main menu?",
    'hi': "उत्तर पूरा हो गया है।\nकृपया एक विकल्प चुनें:\n1. क्या आप इसके बारे में या किसी अन्य विषय पर और पूछना चाहते हैं?\n2. क्या आप मुख्य मेनू पर वापस जाना चाहते हैं?",
    'bn': "উত্তর সম্পূর্ণ হয়েছে।\nএকটি বিকল্প নির্বাচন করুন:\n1. আপনি কি এ সম্পর্কে বা অন্য কিছু সম্পর্কে আরও জানতে চান?\n2. আপনি কি প্রধান মেনুতে ফিরে যেতে চান?",
    'or': "ଉତ୍ତର ସମାପ୍ତ ହୋଇଛି।\nଦୟାକରି ଏକ ବିକଳ୍ପ ବାଛନ୍ତୁ:\n1. ଆପଣ ଏହା ବିଷୟରେ କିମ୍ବା ଅନ୍ୟ କିଛି ବିଷୟରେ ଅଧିକ ପଚାରିବାକୁ ଚାହାନ୍ତି କି?\n2. ଆପଣ ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବାକୁ ଚାହାନ୍ତି କି?"
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

def get_media_url_from_id(media_id):
    try:
        r = requests.get(f"https://graph.facebook.com/v19.0/{media_id}", headers={"Authorization": f"Bearer {META_ACCESS_TOKEN}"})
        return r.json().get("url")
    except: return None

def get_last_5_messages(phone_num):
    try:
        res = supabase.table("user_chat_media").select("*").eq("phone_num", str(phone_num)).order("time_stamp", desc=True).limit(5).execute()
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
        lang = res.get("language") or "en"
        # reduce to 2-letter percent if longer
        if isinstance(lang, str) and len(lang) >= 2:
            lang = lang[:2]
        return text, lang
    except Exception as e:
        logger.exception("Whisper transcription error: %s", e)
        return "", "en"

def call_rasa(transcript, sender_id, lang_code="en"):
    try:
        payload = {"sender": sender_id, "message": transcript, "metadata": {"lang": lang_code}}
        r = requests.post(RASA_WEBHOOK_URL, json=payload, timeout=15)
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

def call_gemini(context_messages, incoming_text, lang_code="en"):
    try:
        if not GEMINI_API_KEY:
            logger.warning("No GEMINI_API_KEY configured; skipping Gemini.")
            return None
        # build system prompt language-specific
        if lang_code == 'hi':
            sys_p = "आप एक सहायक चिकित्सा सहायक हैं। संक्षिप्त और सहायक उत्तर दें।"
        elif lang_code == 'bn':
            sys_p = "আপনি একজন সহায়ক চিকিৎসা সহকারী। সংক্ষিপ্ত ও সহায়ক উত্তর দিন।"
        elif lang_code == 'or':
            sys_p = "ଆପଣ ଜଣେ ସହାୟକ ଚିକିତ୍ସା ସହାୟକ। ସଂକ୍ଷିପ୍ତ ଉତ୍ତର ଦିଅନ୍ତୁ।"
        else:
            sys_p = "You are a helpful medical assistant. Keep replies brief and useful."

        prompt_parts = [sys_p, "\nConversation context:"]
        for m in context_messages:
            prompt_parts.append(f"{m['sender']}: {m['text']}")
        prompt_parts.append(f"user: {incoming_text}")
        prompt = "\n".join(prompt_parts)
        model = genai.GenerativeModel("gemini-2.5-pro")
        resp = model.generate_content([prompt])
        return getattr(resp, "text", str(resp))
    except Exception as e:
        logger.exception("Gemini call failed: %s", e)
        return None

# ---------------------------------------------------------
# 4. MAIN LOGIC
# ---------------------------------------------------------
def process_webhook_event(data):
    try:
        if "object" not in data or "entry" not in data: return

        for entry in data["entry"]:
            for change in entry["changes"]:
                if change["value"].get("messages"):
                    message = change["value"]["messages"][0]
                    from_number = message["from"]
                    msg_type = message["type"]

                    # Init State
                    if from_number not in user_states:
                        user_states[from_number] = {'state': 'language_selection', 'lang': 'en', 'data': {}}

                    current_state = user_states[from_number]['state']
                    current_lang = user_states[from_number]['lang']

                    # --- VOICE HANDLING ---
                    if msg_type in ["audio", "voice"]:
                        media_id = message.get("audio", {}).get("id") or message.get("voice", {}).get("id")
                        if media_id:
                            media_url = get_media_url_from_id(media_id)
                            if media_url:
                                local_path = download_media(media_url, f"audio_{media_id}.ogg")
                                if local_path:
                                    # Convert to WAV for Whisper
                                    wav_path = convert_to_wav(local_path)
                                    if wav_path:
                                        # Transcribe
                                        text, lang = transcribe_with_whisper(wav_path)
                                        if text:
                                            # Log to DB
                                            insert_message(from_number, "user", text=f"[Voice] {text}", language=current_lang)
                                            
                                            # Get AI Response (Text) - Using Gemini directly as per your helper
                                            # You might want to use get_last_5_messages here for context if needed
                                            context_msgs = get_last_5_messages(from_number)
                                            reply = call_gemini(context_msgs, text, lang_code=current_lang)
                                            
                                            if reply:
                                                # Log bot reply
                                                insert_message(from_number, "bot", text=reply, language=current_lang)

                                                # Generate TTS Audio (gTTS -> OGG)
                                                tts_file = text_to_speech_gtts_to_ogg(reply, lang_code=current_lang)
                                                
                                                if tts_file:
                                                    # Upload and send audio
                                                    upload_media_and_send_audio(from_number, tts_file)
                                                else:
                                                    # Fallback to text if TTS fails
                                                    send_whatsapp_message(from_number, reply)
                                            else:
                                                 send_whatsapp_message(from_number, get_localized_message(from_number, "rasa_no_response")) # Or a generic error
                                            return
                        send_whatsapp_message(from_number, get_localized_message(from_number, "voice_error"))
                        return

                    # --- TEXT HANDLING ---
                    incoming_msg = ""
                    if msg_type == "text": incoming_msg = message["text"]["body"].strip()
                    elif msg_type == "button": incoming_msg = message["button"]["payload"].strip()
                    normalized_msg = incoming_msg.lower()

                    if msg_type == "text": insert_message(from_number, "user", text=incoming_msg, language=current_lang)

                    # --- IMAGE HANDLING ---
                    if msg_type == "image":
                        media_id = message["image"]["id"]
                        image_url = get_media_url_from_id(media_id)
                        if image_url:
                            insert_message(from_number, "user", media=[image_url], language=current_lang)
                            
                            rasa_payload = f'/analyze_image{{"image_url": "{image_url}"}}'
                            try:
                                r = requests.post(RASA_WEBHOOK_URL, json={"sender": from_number, "message": rasa_payload, "metadata": {"lang": current_lang}})
                                for bot_msg in r.json():
                                    if bot_msg.get("text"): send_whatsapp_message(from_number, bot_msg.get("text"))
                                
                                closing = MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en'])
                                send_whatsapp_message(from_number, closing)
                                user_states[from_number]['state'] = 'awaiting_ai_choice'
                            except: pass
                            return

                    # --- NAVIGATION ---
                    if normalized_msg in MENU_ENTRY_TRIGGER:
                        if current_state == 'language_selection':
                            send_whatsapp_message(from_number, LANGUAGE_MENU)
                        else:
                            user_states[from_number]['state'] = 'main_menu'
                            send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']))
                        return

                    # --- LANGUAGE SELECTION ---
                    if current_state == 'language_selection':
                        if normalized_msg == '1': user_states[from_number]['lang'] = 'en'
                        elif normalized_msg == '2': user_states[from_number]['lang'] = 'hi'
                        elif normalized_msg == '3': user_states[from_number]['lang'] = 'bn'
                        elif normalized_msg == '4': user_states[from_number]['lang'] = 'or'
                        else: 
                            send_whatsapp_message(from_number, "Invalid. 1-4.\n" + LANGUAGE_MENU)
                            return
                        user_states[from_number]['state'] = 'main_menu'
                        send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(user_states[from_number]['lang']))
                        return

                    # --- DISEASE CHECKER FLOW (10 Steps) ---
                    if current_state == 'ask_age':
                        user_states[from_number]['data']['age'] = incoming_msg
                        user_states[from_number]['state'] = 'ask_weight'
                        send_whatsapp_message(from_number, get_localized_message(from_number, "ask_weight"))
                        return

                    if current_state == 'ask_weight':
                        user_states[from_number]['data']['weight'] = incoming_msg
                        user_states[from_number]['state'] = 'ask_gender'
                        send_whatsapp_message(from_number, get_localized_message(from_number, "ask_gender"))
                        return

                    if current_state == 'ask_gender':
                        user_states[from_number]['data']['gender'] = incoming_msg
                        user_states[from_number]['state'] = 'ask_reports'
                        send_whatsapp_message(from_number, get_localized_message(from_number, "ask_reports"))
                        return

                    if current_state == 'ask_reports':
                        user_states[from_number]['data']['reports'] = incoming_msg
                        user_states[from_number]['state'] = 'ask_eating'
                        send_whatsapp_message(from_number, get_localized_message(from_number, "ask_eating"))
                        return

                    if current_state == 'ask_eating':
                        user_states[from_number]['data']['eating'] = incoming_msg
                        user_states[from_number]['state'] = 'ask_meds'
                        send_whatsapp_message(from_number, get_localized_message(from_number, "ask_meds"))
                        return

                    if current_state == 'ask_meds':
                        user_states[from_number]['data']['meds'] = incoming_msg
                        user_states[from_number]['state'] = 'ask_habits'
                        send_whatsapp_message(from_number, get_localized_message(from_number, "ask_habits"))
                        return

                    if current_state == 'ask_habits':
                        user_states[from_number]['data']['habits'] = incoming_msg
                        user_states[from_number]['state'] = 'ask_disability'
                        send_whatsapp_message(from_number, get_localized_message(from_number, "ask_disability"))
                        return

                    if current_state == 'ask_disability':
                        user_states[from_number]['data']['disability'] = incoming_msg
                        user_states[from_number]['state'] = 'ask_history'
                        send_whatsapp_message(from_number, get_localized_message(from_number, "ask_history"))
                        return

                    if current_state == 'ask_history':
                        user_states[from_number]['data']['history'] = incoming_msg
                        user_states[from_number]['state'] = 'ask_current_symptoms'
                        send_whatsapp_message(from_number, get_localized_message(from_number, "ask_current_symptoms"))
                        return

                    if current_state == 'ask_current_symptoms':
                        user_states[from_number]['data']['current_symptoms'] = incoming_msg
                        d = user_states[from_number]['data']
                        data_str = f"Age: {d.get('age')}, Weight: {d.get('weight')}, Gender: {d.get('gender')}, Reports: {d.get('reports')}, Diet: {d.get('eating')}, Meds: {d.get('meds')}, Habits: {d.get('habits')}, Disability: {d.get('disability')}, History: {d.get('history')}, Symptoms: {incoming_msg}"
                        
                        send_whatsapp_message(from_number, get_localized_message(from_number, "processing_diagnosis"))
                        
                        rasa_payload = f'/check_disease{{"patient_details": "{data_str}"}}'
                        try:
                            # Using call_rasa helper
                            bot_msgs = call_rasa(rasa_payload, from_number, lang_code=current_lang)
                            for msg_text in bot_msgs:
                                send_whatsapp_message(from_number, msg_text)
                            
                            closing = MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en'])
                            send_whatsapp_message(from_number, closing)
                            user_states[from_number]['state'] = 'awaiting_ai_choice'
                        except: pass
                        return

                    # --- MEDICINE INFO FLOW ---
                    if current_state == 'ask_medicine_name':
                        medicine_name = incoming_msg
                        send_whatsapp_message(from_number, get_localized_message(from_number, "processing_medicine"))
                        
                        rasa_payload = f'/check_medicine{{"medicine_name": "{medicine_name}"}}'
                        try:
                            # Using call_rasa helper
                            bot_msgs = call_rasa(rasa_payload, from_number, lang_code=current_lang)
                            for msg_text in bot_msgs:
                                send_whatsapp_message(from_number, msg_text)
                            
                            closing = MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en'])
                            send_whatsapp_message(from_number, closing)
                            user_states[from_number]['state'] = 'awaiting_ai_choice'
                        except: pass
                        return

                    # --- AI CHOICE ---
                    if current_state == 'awaiting_ai_choice':
                        if normalized_msg == '1':
                            user_states[from_number]['state'] = 'in_rasa_conversation'
                            send_whatsapp_message(from_number, get_localized_message(from_number, "entering_ai_assistant"))
                        elif normalized_msg == '2':
                            user_states[from_number]['state'] = 'main_menu'
                            send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']))
                        else:
                            send_whatsapp_message(from_number, MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en']))
                        return

                    # --- GENERAL CHAT ---
                    if current_state == 'in_rasa_conversation':
                        if normalized_msg in MENU_RETURN_TRIGGER:
                            user_states[from_number]['state'] = 'main_menu'
                            send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']))
                            return
                        try:
                            # Using call_rasa helper
                            bot_msgs = call_rasa(incoming_msg, from_number, lang_code=current_lang)
                            if bot_msgs:
                                for msg_text in bot_msgs:
                                    send_whatsapp_message(from_number, msg_text)
                                closing = MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en'])
                                send_whatsapp_message(from_number, closing)
                                user_states[from_number]['state'] = 'awaiting_ai_choice'
                            else:
                                send_whatsapp_message(from_number, get_localized_message(from_number, "rasa_no_response"))
                        except: pass
                        return

                    # --- MAIN MENU ---
                    if current_state == 'main_menu':
                        if normalized_msg == '1':
                            user_states[from_number]['state'] = 'in_rasa_conversation'
                            send_whatsapp_message(from_number, get_localized_message(from_number, "entering_ai_assistant"))
                        elif normalized_msg == '2':
                            send_whatsapp_message(from_number, get_localized_message(from_number, "vaccination_selected"))
                        elif normalized_msg == '3': # DISEASE CHECKER
                            user_states[from_number]['state'] = 'ask_age'
                            user_states[from_number]['data'] = {} 
                            send_whatsapp_message(from_number, get_localized_message(from_number, "ask_age"))
                        elif normalized_msg == '4': # MEDICINE INFO
                            user_states[from_number]['state'] = 'ask_medicine_name'
                            send_whatsapp_message(from_number, get_localized_message(from_number, "ask_medicine_name"))
                        elif normalized_msg == '5': # CENTER
                            send_whatsapp_message(from_number, get_localized_message(from_number, "health_center_selected"))
                        elif normalized_msg == '6': # ABOUT
                            send_whatsapp_message(from_number, get_localized_message(from_number, "about_us_selected"))
                        elif normalized_msg == '7': # LANG
                            user_states[from_number]['state'] = 'language_selection'
                            send_whatsapp_message(from_number, LANGUAGE_MENU)
                        elif normalized_msg == '8': # EXIT
                            user_states.pop(from_number, None)
                            send_whatsapp_message(from_number, get_localized_message(from_number, "thank_you_goodbye"))
                        else:
                            send_whatsapp_message(from_number, get_localized_message(from_number, "invalid_option"))
                            send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']))
                        return

    except Exception as e: logger.error(f"Logic Error: {e}")

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    data = request.get_json()
    if not data: return "Error", 400
    threading.Thread(target=process_webhook_event, args=(data,)).start()
    return jsonify({"status": "ok"}), 200

@app.route("/whatsapp", methods=['GET'])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Invalid", 403

if __name__ == "__main__":
    app.run(port=6000, debug=True)