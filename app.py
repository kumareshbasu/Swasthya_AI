# app.py
from flask import Flask, request, jsonify
import requests
import os
import json
import logging
import threading
import io
from PIL import Image
from langdetect import detect, DetectorFactory 
import google.generativeai as genai
from datetime import datetime, timezone

# --- NEW: Supabase Imports ---
from supabase import create_client, Client

# To ensure consistent language detection results
DetectorFactory.seed = 0 

app = Flask(__name__)

# ---------------------------------------------------------
# 1. CONFIGURATION & CREDENTIALS
# ---------------------------------------------------------

# --- Meta / WhatsApp ---
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "EAAJz0nEJSNgBQBZAtoR33JIAZBuZB7UmoMo4ojqlsZB7ZCgYxJQZBluxKrH8CxDPFv8Qfiq9hSuZBrwuz3TCndQlhw5196a1sxbX8mmxZBzdedho9N5oZAYwUDIVeNfoGguo6QyE0ag765AXIaIa83GxrMcvZAkMjM1mizJrCYlVrzbsMQBl8AjsQw3bPGuZBhET9glywZDZD")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "819746631222018")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "secret_swasthya_ai_is_the_best") 
META_API_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"

# --- Rasa ---
RASA_WEBHOOK_URL = "http://localhost:5005/webhooks/rest/webhook"

# --- Gemini API Key ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyD3V-KfgabsetBfnT1gEjXOBUsahW5DLM8")
genai.configure(api_key=GEMINI_API_KEY)

# --- NEW: Supabase Configuration ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://yovoeamdqiravtfhurtc.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inlvdm9lYW1kcWlyYXZ0Zmh1cnRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjQxMjExOTgsImV4cCI6MjA3OTY5NzE5OH0.Hm-jhl01nGvCghRWk7rAM24fB8SkUuc2AhOPIttpOfA")

# Initialize Supabase Client
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"Supabase connection failed: {e}")
    supabase = None

user_states = {} 

# Navigation Triggers
MENU_ENTRY_TRIGGER = ['hi', 'hello', 'menu', 'start'] 
MENU_RETURN_TRIGGER = ['back', 'main menu', 'Back', 'Return', 'return', 'Exit', 'exit']

# ---------------------------------------------------------
# 2. CONSTANTS (Menus & Messages) - (UPDATED FROM CODE 2)
# ---------------------------------------------------------
MULTILINGUAL_MENUS = {
    'en': """
Welcome to Swasthya AI!
Please choose an option by typing its number:
1. General Health Info (Chat with AI)
2. Vaccination Schedule
3. Find Nearest Health Center
4. About Us
5. Change Language / भाषा बदलें
6. Exit Chat
""",
    'hi': """
स्वस्थ्य AI में आपका स्वागत है!
कृपया इसका नंबर टाइप करके एक विकल्प चुनें:
1. सामान्य स्वास्थ्य जानकारी (AI से बात करें)
2. टीकाकरण अनुसूची
3. निकटतम स्वास्थ्य केंद्र खोजें
4. हमारे बारे में
5. भाषा बदलें / Change Language
6. चैट से बाहर निकलें
""",
    'bn': """
স্বাস্থ্য AI-তে আপনাকে স্বাগতম!
দয়া করে এর নম্বর টাইপ করে একটি বিকল্প বেছে নিন:
1. সাধারণ স্বাস্থ্য তথ্য (AI এর সাথে চ্যাট করুন)
2. টিকা দেওয়ার সময়সূচী
3. নিকটতম স্বাস্থ্য কেন্দ্র খুঁজুন
4. আমাদের সম্পর্কে
5. ভাষা পরিবর্তন করুন / Change Language
6. চ্যাট থেকে প্রস্থান করুন
""",
    'or': """
ସ୍ୱାସ୍ଥ୍ୟ AI କୁ ସ୍ୱାଗତ!
ଦୟାକରି ଏହାର ନମ୍ବର ଟାଇପ୍ କରି ଏକ ବିକଳ୍ପ ବାଛନ୍ତୁ:
1. ସାଧାରଣ ସ୍ୱାସ୍ଥ୍ୟ ସୂଚନା (AI ସହିତ ଚାଟ୍ କରନ୍ତୁ)
2. ଟୀକାକରଣ ସୂଚୀ
3. ନିକଟସ୍ଥ ସ୍ୱାସ୍ଥ୍ୟ କେନ୍ଦ୍ର ଖୋଜନ୍ତୁ
4. ଆମ ବିଷୟରେ
5. ଭାଷା ପରିବର୍ତ୍ତନ କରନ୍ତୁ / Change Language
6. ଚାଟ୍ ରୁ ବାହାରନ୍ତୁ
"""
}

MULTILINGUAL_STATIC_MESSAGES = {
    'en': {
        "welcome_back": "Welcome back!",
        "already_main_menu": "You are already at the main menu.",
        "left_ai_assistant": "You have left the AI Health Assistant.",
        "entering_ai_assistant": "Okay, entering AI Health Assistant. How can I help you today? (Type 'back' to return to the main menu)",
        "vaccination_selected": "You selected Vaccination Schedule. (Type 'menu' to return to the main menu)\nHere's information on vaccination schedules...",
        "health_center_selected": "You selected Find Nearest Health Center. (Type 'menu' to return to the main menu)\nPlease tell me your current location or area to find the nearest health center.",
        "about_us_selected": "You selected About Us. (Type 'menu' to return to the main menu)\nThis is the Swasthya AI Health Info Chatbot, powered by Rasa and Gemini, designed to provide basic public health information. Our goal is to make health knowledge accessible. (Type 'menu' to return to the main menu)",
        "thank_you_goodbye": "Thank you for using Swasthya AI! Goodbye. (Type 'hi' or 'hello' to restart)",
        "invalid_option": "That's not a valid option. Please choose a number from the menu below:",
        "rasa_no_response": "Sorry, I didn't get a response from the AI. You can say 'back' to return to the main menu.",
        "rasa_connection_error": "Sorry, I'm having trouble connecting to my brain right now. Please type 'back' to return to the main menu.",
        "chat_ended_prompt_restart": "Chat session ended. Please type 'hi' or 'hello' if you wish to start a new conversation."
    },
    'hi': {'welcome_back': 'वापस स्वागत है!', 'already_main_menu': 'आप पहले से ही मुख्य मेनू में हैं।', 'left_ai_assistant': 'आपने AI स्वास्थ्य सहायक छोड़ दिया है।', 'entering_ai_assistant': 'ठीक है, AI स्वास्थ्य सहायक में प्रवेश कर रहा हूँ। मैं आज आपकी कैसे मदद कर सकता हूँ? (मुख्य मेनू पर लौटने के लिए \'back\' टाइप करें)', 'vaccination_selected': 'आपने टीकाकरण अनुसूची चुना है। (मुख्य मेनू पर लौटने के लिए \'menu\' टाइप करें)\nयहाँ टीकाकरण अनुसूची के बारे में जानकारी है...', 'health_center_selected': 'आपने निकटतम स्वास्थ्य केंद्र खोजें चुना है। (मुख्य मेनू पर लौटने के लिए \'menu\' टाइप करें)\nकृपया निकटतम स्वास्थ्य केंद्र खोजने के लिए अपना वर्तमान स्थान या क्षेत्र बताएं।', 'about_us_selected': 'आपने हमारे बारे में चुना है। (मुख्य मेनू पर लौटने के लिए \'menu\' टाइप करें)\nयह स्वास्थ्य AI स्वास्थ्य सूचना चैटबॉट है, जो Rasa और Gemini द्वारा संचालित है, जिसे बुनियादी सार्वजनिक स्वास्थ्य जानकारी प्रदान करने के लिए डिज़ाइन किया गया है। हमारा लक्ष्य स्वास्थ्य ज्ञान को सुलभ बनाना है। (मुख्य मेनू पर लौटने के लिए \'menu\' टाइप करें)', 'thank_you_goodbye': 'स्वास्थ्य AI का उपयोग करने के लिए धन्यवाद! अलविदा। (पुनः शुरू करने के लिए \'hi\' या \'hello\' टाइप करें)', 'invalid_option': 'यह एक वैध विकल्प नहीं है। कृपया नीचे दिए गए मेनू से एक नंबर चुनें:', 'rasa_no_response': 'क्षमा करें, मुझे AI से कोई प्रतिक्रिया नहीं मिली। आप मुख्य मेनू पर लौटने के लिए \'back\' कह सकते हैं।', 'rasa_connection_error': 'क्षमा करें, मुझे अभी अपने मस्तिष्क से जुड़ने में परेशानी हो रही है। कृपया मुख्य मेनू पर लौटने के लिए \'back\' टाइप करें।', 'chat_ended_prompt_restart': 'चैट सत्र समाप्त हो गया है। यदि आप एक नई बातचीत शुरू करना चाहते हैं तो \'hi\' या \'hello\' टाइप करें।'},
    'bn': {'welcome_back': 'পুনরায় স্বাগতম!', 'already_main_menu': 'আপনি ইতিমধ্যেই প্রধান মেনুতে আছেন।', 'left_ai_assistant': 'আপনি AI স্বাস্থ্য সহায়ক ছেড়ে গেছেন।', 'entering_ai_assistant': 'ঠিক আছে, AI স্বাস্থ্য সহায়ক-এ প্রবেশ করছি। আমি আজ আপনাকে কীভাবে সাহায্য করতে পারি? (প্রধান মেনুতে ফিরে যেতে \'back\' টাইপ করুন)', 'vaccination_selected': 'আপনি টিকা দেওয়ার সময়সূচী নির্বাচন করেছেন। (প্রধান মেনুতে ফিরে যেতে \'menu\' টাইপ করুন)\nএখানে টিকা দেওয়ার সময়সূচী সম্পর্কিত তথ্য আছে...', 'health_center_selected': 'আপনি নিকটতম স্বাস্থ্য কেন্দ্র খুঁজুন নির্বাচন করেছেন। (প্রধান মেনুতে ফিরে যেতে \'menu\' টাইপ করুন)\nনিকটতম স্বাস্থ্য কেন্দ্র খুঁজে পেতে দয়া করে আপনার বর্তমান অবস্থান বা এলাকা বলুন।', 'about_us_selected': 'আপনি আমাদের সম্পর্কে নির্বাচন করেছেন। (প্রধান মেনুতে ফিরে যেতে \'menu\' টাইপ করুন)\nএটি স্বাচ্ছন্দ্য AI স্বাস্থ্য তথ্য চ্যাটবট, যা Rasa এবং Gemini দ্বারা চালিত, মৌলিক জনস্বাস্থ্য তথ্য সরবরাহ করার জন্য ডিজাইন করা হয়েছে। আমাদের লক্ষ্য হল স্বাস্থ্য জ্ঞানকে সহজলভ্য করা। (প্রধান মেনুতে ফিরে যেতে \'menu\' টাইপ করুন)', 'thank_you_goodbye': 'স্বাস্থ্য AI ব্যবহার করার জন্য ধন্যবাদ! বিদায়। (পুনরায় শুরু করতে \'hi\' বা \'hello\' টাইপ করুন)', 'invalid_option': 'এটি একটি বৈধ বিকল্প নয়। দয়া করে নিচের মেনু থেকে একটি নম্বর বেছে নিন:', 'rasa_no_response': 'দুঃখিত, আমি AI থেকে কোনো প্রতিক্রিয়া পাইনি। আপনি প্রধান মেনুতে ফিরে যেতে \'back\' বলতে পারেন।', 'rasa_connection_error': 'দুঃখিত, আমার মস্তিষ্কের সাথে সংযোগ করতে সমস্যা হচ্ছে। দয়া করে প্রধান মেনুতে ফিরে যেতে \'back\' টাইপ করুন।', 'chat_ended_prompt_restart': 'চ্যাট সেশন শেষ হয়েছে। আপনি যদি নতুন কথোপকথন শুরু করতে চান তবে \'hi\' বা \'hello\' টাইপ করুন।'},
    'or': {'welcome_back': 'ପୁଣି ସ୍ୱାଗତ!', 'already_main_menu': 'ଆପଣ ପୂର୍ବରୁ ମୁଖ୍ୟ ମେନୁରେ ଅଛନ୍ତି।', 'left_ai_assistant': 'ଆପଣ AI ସ୍ୱାସ୍ଥ୍ୟ ସହାୟକ ଛାଡି ଦେଇଛନ୍ତି।', 'entering_ai_assistant': 'ଠିକ୍ ଅଛି, AI ସ୍ୱାସ୍ଥ୍ୟ ସହାୟକରେ ପ୍ରବେଶ କରୁଛି। ମୁଁ ଆଜି ଆପଣଙ୍କୁ କିପରି ସାହାଯ୍ୟ କରିପାରିବି? (ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବା ପାଇଁ \'back\' ଟାଇପ୍ କରନ୍ତୁ)', 'vaccination_selected': 'ଆପଣ ଟୀକାକରଣ ସୂଚୀ ବାଛିଛନ୍ତି। (ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବା ପାଇଁ \'menu\' ଟାଇପ୍ କରନ୍ତୁ)\nଏଠାରେ ଟୀକାକରଣ ସୂଚୀ ବିଷୟରେ ସୂଚନା ଅଛି...', 'health_center_selected': 'ଆପଣ ନିକଟସ୍ଥ ସ୍ୱାସ୍ଥ୍ୟ କେନ୍ଦ୍ର ଖୋଜନ୍ତୁ ବାଛିଛନ୍ତି। (ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବା ପାଇଁ \'menu\' ଟାଇପ୍ କରନ୍ତୁ)\nନିକଟସ୍ଥ ସ୍ୱାସ୍ଥ୍ୟ କେନ୍ଦ୍ର ଖୋଜିବା ପାଇଁ ଦୟାକରି ଆପଣଙ୍କ ବର୍ତ୍ତମାନର ସ୍ଥାନ କିମ୍ବା ଅଞ୍ଚଳ କୁହନ୍ତୁ।', 'about_us_selected': 'ଆପଣ ଆମ ବିଷୟରେ ବାଛିଛନ୍ତି। (ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବା ପାଇଁ \'menu\' ଟାଇପ୍ କରନ୍ତୁ)\nଏହା ହେଉଛି ସ୍ୱାସ୍ଥ୍ୟ AI ସ୍ୱାସ୍ଥ୍ୟ ସୂଚନା ଚାଟ୍‌ବଟ୍, ଯାହା Rasa ଏବଂ Gemini ଦ୍ୱାରା ପରିଚାଳିତ, ମୌଳିକ ଜନସ୍ୱାସ୍ଥ୍ୟ ସୂଚନା ପ୍ରଦାନ କରିବା ପାଇଁ ଡିଜାଇନ୍ କରାଯାଇଛି। ଆମର ଲକ୍ଷ୍ୟ ହେଉଛି ସ୍ୱାସ୍ଥ୍ୟ ଜ୍ଞାନକୁ ସୁଗମ କରିବା। (ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବା ପାଇଁ \'menu\' ଟାଇପ୍ କରନ୍ତୁ)', 'thank_you_goodbye': 'ସ୍ୱାସ୍ଥ୍ୟ AI ବ୍ୟବହାର କରିଥିବାରୁ ଧନ୍ୟବାଦ! ଶୁଭରାତ୍ରି। (ପୁନର୍ବାର ଆରମ୍ଭ କରିବାକୁ \'hi\' କିମ୍ବା \'hello\' ଟାଇପ୍ କରନ୍ତୁ)', 'invalid_option': 'ଏହା ଏକ ବୈଧ ବିକଳ୍ପ ନୁହେଁ। ଦୟାକରି ତଳ ମେନୁରୁ ଏକ ନମ୍ବର ବାଛନ୍ତୁ:', 'rasa_no_response': 'କ୍ଷମା କରନ୍ତୁ, ମୁଁ AI ରୁ କୌଣସି ପ୍ରତିକ୍ରିୟା ପାଇଲି ନାହିଁ। ଆପଣ ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବା ପାଇଁ \'back\' କହିପାରିବେ।', 'rasa_connection_error': 'କ୍ଷମା କରନ୍ତୁ, ମୋର ମସ୍ତିଷ୍କ ସହିତ ସଂଯୋଗ କରିବାରେ ଅସୁବିଧା ହେଉଛି। ଦୟାକରି ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବା ପାଇଁ \'back\' ଟାଇପ୍ କରନ୍ତୁ।', 'chat_ended_prompt_restart': 'ଚାଟ୍ ଅଧିବେଶନ ଶେଷ ହୋଇଛି। ଯଦି ଆପଣ ଏକ ନୂଆ କଥାବାର୍ତ୍ତା ଆରମ୍ଭ କରିବାକୁ ଚାହାଁନ୍ତି ତେବେ \'hi\' କିମ୍ବା \'hello\' ଟାଇପ୍ କରନ୍ତୁ।'}
}

# Language selection menu (FROM CODE 2)
LANGUAGE_MENU = """
Please select your preferred language / कृपया अपनी पसंदीदा भाषा चुनें / অনুগ্রহ করে আপনার পছন্দের ভাষা নির্বাচন করুন / ଦୟାକରି ଆପଣଙ୍କ ପସନ୍ଦର ଭାଷା ବାଛନ୍ତୁ:
1. English
2. हिंदी (Hindi)
3. বাংলা (Bengali)
4. ଓଡ଼ିଆ (Odia)
"""

# Closing prompt after each gemini response (FROM CODE 2)
MULTILINGUAL_AI_CLOSING = {
    'en': "This response is completed.\nSelect any one option:\n1. Do you want to ask anything more about this or something else?\n2. Would you like to go back to main menu?",
    'hi': "उत्तर पूरा हो गया है।\nकृपया एक विकल्प चुनें:\n1. क्या आप इसके बारे में या किसी अन्य विषय पर और पूछना चाहते हैं?\n2. क्या आप मुख्य मेनू पर वापस जाना चाहते हैं?",
    'bn': "উত্তর সম্পূর্ণ হয়েছে।\nএকটি বিকল্প নির্বাচন করুন:\n1. আপনি কি এ সম্পর্কে বা অন্য কিছু সম্পর্কে আরও জানতে চান?\n2. আপনি কি প্রধান মেনুতে ফিরে যেতে চান?",
    'or': "ଉତ୍ତର ସମାପ୍ତ ହୋଇଛି।\nଦୟାକରି ଏକ ବିକଳ୍ପ ବାଛନ୍ତୁ:\n1. ଆପଣ ଏହା ବିଷୟରେ କିମ୍ବା ଅନ୍ୟ କିଛି ବିଷୟରେ ଅଧିକ ପଚାରିବାକୁ ଚାହାନ୍ତି କି?\n2. ଆପଣ ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବାକୁ ଚାହାନ୍ତି କି?"
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# 3. HELPER FUNCTIONS
# ---------------------------------------------------------

# --- NEW: Database Helper Function (Supabase) ---
def insert_message(phone_num, sender, text=None, media=None, language="en"):
    """
    Insert a message row into user_chat_media table in Supabase.
    """
    if not supabase:
        return
    
    entry = {
        "phone_num": str(phone_num),
        "user_message": text if sender == "user" else None,
        "bot_message": text if sender == "bot" else None,
        "user_media": media or [],
        "language": language,
        "time_stamp": datetime.now(timezone.utc).isoformat()
    }
    try:
        supabase.table("user_chat_media").insert(entry).execute()
        logger.info(f"DB: Logged {sender} message.")
    except Exception as e:
        logger.error(f"DB Error inserting message: {e}")

# --- Localization ---
def get_localized_message(from_number, key):
    user_data = user_states.get(from_number, {})
    lang = user_data.get('lang', 'en') # Default to English
    return MULTILINGUAL_STATIC_MESSAGES.get(lang, {}).get(key, MULTILINGUAL_STATIC_MESSAGES['en'][key])

# --- Sending Messages ---
def send_whatsapp_message(to_number, message_body):
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message_body},
    }
    try:
        response = requests.post(META_API_URL, headers=headers, json=payload)
        response.raise_for_status() 
        
        # --- NEW: Log Bot Response to DB ---
        insert_message(to_number, "bot", text=message_body, language=user_states.get(to_number, {}).get('lang', 'en'))
        
        logger.info(f"Message sent to {to_number} (lang:{user_states.get(to_number,{}).get('lang','en')}): {message_body[:50]}...") 
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending message to WhatsApp API for {to_number}: {e}", exc_info=True)
        return None

# --- Image Helpers ---
def get_media_url_from_id(media_id):
    url = f"https://graph.facebook.com/v19.0/{media_id}"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get("url")
    except Exception as e:
        logger.error(f"Error getting media URL: {e}")
        return None

def download_image_bytes(media_url):
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
    }
    try:
        response = requests.get(media_url, headers=headers)
        response.raise_for_status()
        return response.content
    except Exception as e:
        logger.error(f"Error downloading image: {e}")
        return None

# ---------------------------------------------------------
# 4. MAIN LOGIC (Webhook Processor)
# ---------------------------------------------------------
def process_webhook_event(data):
    """
    This function processes the webhook data in a background thread.
    Includes DB Logging, Language Selection, and Closing Prompts.
    """
    try:
        logger.info(f"THREAD: Processing webhook event: {json.dumps(data, indent=2)}")

        if "object" not in data or "entry" not in data:
            logger.warning("THREAD: Webhook event is not a valid WhatsApp event.")
            return 

        for entry in data["entry"]:
            for change in entry["changes"]:
                if change.get("field") == "messages" and change.get("value", {}).get("messages"):
                    message = change["value"]["messages"][0]
                    from_number = message["from"]
                    msg_type = message["type"]

                    incoming_msg = ""
                    if msg_type == "text":
                        incoming_msg = message["text"]["body"].strip() 
                    elif msg_type == "button":
                        incoming_msg = message["button"]["payload"].strip()
                    
                    # --- IMAGE HANDLING (UPDATED) ---
                    elif msg_type == "image":
                        media_id = message["image"]["id"]
                        image_url = get_media_url_from_id(media_id)
                        current_lang = user_states.get(from_number, {}).get('lang', 'en')
                        
                        if image_url:
                            logger.info(f"THREAD: Image URL obtained: {image_url}. Forwarding to Rasa...")
                            
                            # --- Log User Image to DB ---
                            insert_message(from_number, "user", text=None, media=[image_url], language=current_lang)

                            # Tell Rasa to process this image
                            rasa_payload = f'/analyze_image{{"image_url": "{image_url}"}}'
                            
                            try:
                                rasa_response = requests.post(
                                    RASA_WEBHOOK_URL,
                                    json={
                                        "sender": from_number, 
                                        "message": rasa_payload, 
                                        "metadata": {"lang": current_lang}
                                    }
                                )
                                rasa_response.raise_for_status()
                                
                                rasa_data = rasa_response.json()
                                if rasa_data:
                                    for bot_message in rasa_data:
                                        if bot_message.get("text"):
                                            send_whatsapp_message(from_number, bot_message.get("text"))
                                    
                                    # --- SEND CLOSING OPTIONS (From Code 2) ---
                                    closing_text = MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en'])
                                    send_whatsapp_message(from_number, closing_text)
                                    
                                    # Switch state so user must pick 1 or 2
                                    user_states[from_number]['state'] = 'awaiting_ai_choice'

                                else:
                                    send_whatsapp_message(from_number, "Thinking...")
                                    
                                return # Done processing this image

                            except Exception as e:
                                logger.error(f"Error forwarding image to Rasa: {e}")
                                send_whatsapp_message(from_number, "Error processing image with AI.")
                                return
                        else:
                            send_whatsapp_message(from_number, "Could not retrieve image from WhatsApp.")
                            return

                    # --- LANGUAGE DETECTION & STATE LOGIC (UPDATED) ---
                    
                    # NEW USER: Force language selection (From Code 2)
                    if from_number not in user_states:
                        user_states[from_number] = {'state': 'language_selection', 'lang': 'en'}
                        send_whatsapp_message(from_number, LANGUAGE_MENU)
                        return

                    current_lang = user_states[from_number]['lang']
                    current_state = user_states[from_number]['state']
                    normalized_incoming_msg = incoming_msg.lower()

                    logger.info(f"THREAD: Incoming from {from_number} (lang:{current_lang}): '{normalized_incoming_msg}' in state '{current_state}'")

                    # --- Log Text Message to DB ---
                    if msg_type == "text":
                        insert_message(from_number, "user", text=incoming_msg, language=current_lang)

                    # --- LANGUAGE SELECTION HANDLER (From Code 2) ---
                    if current_state == 'language_selection':
                        if normalized_incoming_msg == '1':
                            user_states[from_number]['lang'] = 'en'
                        elif normalized_incoming_msg == '2':
                            user_states[from_number]['lang'] = 'hi'
                        elif normalized_incoming_msg == '3':
                            user_states[from_number]['lang'] = 'bn'
                        elif normalized_incoming_msg == '4':
                            user_states[from_number]['lang'] = 'or'
                        else:
                            # Invalid input
                            send_whatsapp_message(from_number, "Invalid choice. Please select 1, 2, 3 or 4.\n" + LANGUAGE_MENU)
                            return

                        # Success: Move to main menu
                        user_states[from_number]['state'] = 'main_menu'
                        lang = user_states[from_number]['lang']
                        send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(lang, MULTILINGUAL_MENUS['en']))
                        return

                    # --- GLOBAL COMMANDS ---
                    if normalized_incoming_msg in MENU_ENTRY_TRIGGER:
                        user_states[from_number]['state'] = 'main_menu' 
                        send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en'])) 
                        logger.info(f"THREAD: User {from_number} reset to MAIN_MENU.")
                        return 

                    # --- AI CHOICE HANDLER (From Code 2) ---
                    if current_state == 'awaiting_ai_choice':
                        ai_choice_prompt = MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en'])
                        
                        if normalized_incoming_msg == '1':
                            # Continue AI conversation
                            user_states[from_number]['state'] = 'in_rasa_conversation'
                            send_whatsapp_message(from_number, get_localized_message(from_number, "entering_ai_assistant"))
                            return
                        elif normalized_incoming_msg == '2':
                            # Go back to main menu
                            user_states[from_number]['state'] = 'main_menu'
                            send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']))
                            return
                        else:
                            # Wrong input → repeat prompt
                            send_whatsapp_message(from_number, ai_choice_prompt)
                            return

                    # --- ACTIVE CONVERSATION ---
                    if current_state == 'in_rasa_conversation':
                        if normalized_incoming_msg in MENU_RETURN_TRIGGER: 
                            user_states[from_number]['state'] = 'main_menu'
                            send_whatsapp_message(from_number, get_localized_message(from_number, "left_ai_assistant"))
                            send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']))
                            return
                        else:
                            logger.info(f"THREAD: Forwarding message to Rasa for {from_number}")
                            try:
                                rasa_response = requests.post(
                                    RASA_WEBHOOK_URL,
                                    json={"sender": from_number, "message": incoming_msg, "metadata": {"lang": current_lang}} 
                                )
                                rasa_response.raise_for_status()
                                rasa_data = rasa_response.json()

                                if rasa_data:
                                    for bot_message in rasa_data:
                                        if bot_message.get("text"):
                                            send_whatsapp_message(from_number, bot_message.get("text"))
                                    
                                    # --- SEND CLOSING OPTIONS (From Code 2) ---
                                    closing_text = MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en'])
                                    send_whatsapp_message(from_number, closing_text)
                                    
                                    # Switch state so user must pick 1 or 2
                                    user_states[from_number]['state'] = 'awaiting_ai_choice'

                                else:
                                    send_whatsapp_message(from_number, get_localized_message(from_number, "rasa_no_response"))

                            except requests.exceptions.RequestException as e:
                                logger.error(f"THREAD: Error connecting to Rasa: {e}")
                                send_whatsapp_message(from_number, get_localized_message(from_number, "rasa_connection_error"))
                        return 
                    
                    # --- EXITED STATE ---
                    elif current_state == 'exited_chat':
                        send_whatsapp_message(from_number, get_localized_message(from_number, "chat_ended_prompt_restart"))
                        return 

                    # --- MAIN MENU ---
                    elif current_state == 'main_menu':
                        if normalized_incoming_msg == '1':
                            user_states[from_number]['state'] = 'in_rasa_conversation'
                            send_whatsapp_message(from_number, get_localized_message(from_number, "entering_ai_assistant"))
                        elif normalized_incoming_msg == '2':
                            send_whatsapp_message(from_number, get_localized_message(from_number, "vaccination_selected"))
                        elif normalized_incoming_msg == '3':
                            send_whatsapp_message(from_number, get_localized_message(from_number, "health_center_selected"))
                        elif normalized_incoming_msg == '4':
                            send_whatsapp_message(from_number, get_localized_message(from_number, "about_us_selected"))
                        elif normalized_incoming_msg == '5':
                            # Change Language (Go back to selection)
                            user_states[from_number]['state'] = 'language_selection'
                            send_whatsapp_message(from_number, LANGUAGE_MENU)
                            return
                        elif normalized_incoming_msg == '6':
                            # Exit
                            user_states[from_number]['state'] = 'exited_chat' 
                            send_whatsapp_message(from_number, get_localized_message(from_number, "thank_you_goodbye"))
                            # Clear state to force lang selection next time
                            user_states.pop(from_number, None)
                            return
                        else:
                            send_whatsapp_message(from_number, get_localized_message(from_number, "invalid_option"))
                            send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']))
                        return
                    
                    logger.warning(f"THREAD: No state matched. Defaulting to main menu.")
                    user_states[from_number]['state'] = 'main_menu'
                    send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']))
                    return

        logger.warning("THREAD: No messages found in the incoming webhook event.")
    
    except Exception as e:
        logger.error(f"THREAD: Unhandled exception in process_webhook_event: {e}", exc_info=True)


@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    try:
        data = request.get_json()
        if not data:
            logger.error("Received empty JSON data or non-JSON request.")
            return "Bad Request: No JSON data received", 400
    except Exception as e:
        logger.error(f"Could not parse request JSON: {e}")
        return "Bad Request: Malformed JSON", 400

    # 4. START THE BACKGROUND THREAD
    thread = threading.Thread(target=process_webhook_event, args=(data,))
    thread.start()

    # 5. IMMEDIATELY RETURN 200 OK TO META
    logger.info("Webhook received. Acknowledging 200 OK and processing in background.")
    return jsonify({"status": "pending_processing"}), 200


if __name__ == "__main__":
    app.run(port=6000, debug=True)