from flask import Flask, request, jsonify
import requests
import os
import json
import logging
import threading
import io
from PIL import Image
from langdetect import DetectorFactory
import google.generativeai as genai
from datetime import datetime, timezone
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# To ensure consistent language detection results
DetectorFactory.seed = 0 

app = Flask(__name__)

# ---------------------------------------------------------
# 1. CONFIGURATION
# ---------------------------------------------------------

# --- Meta / WhatsApp ---
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
META_API_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"

# --- Rasa ---
RASA_WEBHOOK_URL = "http://localhost:5005/webhooks/rest/webhook"

# --- Gemini API Key (For app.py usage) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# --- NEW: Supabase Configuration ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Initialize Supabase Client
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"Supabase connection failed: {e}")
    supabase = None

user_states = {} # In-memory user state tracking
                 # Structure: {phone_num: {'state': 'main_menu'/'in_rasa_conversation'/..., 'lang': 'en'/'hi'/...}}

MENU_ENTRY_TRIGGER = ['hi', 'hello', 'menu', 'start'] # Triggers to enter main menu
MENU_RETURN_TRIGGER = ['back', 'main menu', 'Back', 'Return', 'return', 'Exit', 'exit'] # Triggers to return to main menu

# ---------------------------------------------------------
# 2. CONSTANTS (Menus & Messages)
# ---------------------------------------------------------
MULTILINGUAL_MENUS = {
    'en': """
Welcome to Swasthya AI!
1. General Health Info (Chat with AI)
2. Vaccination Schedule
3. Disease Checker (By Symptoms) 🩺
4. Find Nearest Health Center
5. About Us
6. Change Language
7. Exit Chat
""",
    'hi': """
स्वास्थ्य AI में आपका स्वागत है!
1. सामान्य स्वास्थ्य जानकारी (AI से बात करें)
2. टीकाकरण अनुसूची
3. बीमारी जांच (लक्षणों द्वारा) 🩺
4. निकटतम स्वास्थ्य केंद्र खोजें
5. हमारे बारे में
6. भाषा बदलें
7. चैट से बाहर निकलें
""",
    'bn': """
স্বাস্থ্য AI-তে আপনাকে স্বাগতম!
1. সাধারণ স্বাস্থ্য তথ্য (AI এর সাথে চ্যাট করুন)
2. টিকা দেওয়ার সময়সূচী
3. রোগ পরীক্ষক (লক্ষণ দ্বারা) 🩺
4. নিকটতম স্বাস্থ্য কেন্দ্র খুঁজুন
5. আমাদের সম্পর্কে
6. ভাষা পরিবর্তন
7. চ্যাট থেকে প্রস্থান
""",
    'or': """
ସ୍ୱାସ୍ଥ୍ୟ AI ରେ ଆପଣଙ୍କୁ ସ୍ୱାଗତ!
1. ସାଧାରଣ ସ୍ୱାସ୍ଥ୍ୟ ସୂଚନା (AI ସହିତ ଆଲୋଚନା କରନ୍ତୁ)
2. ଟୀକାକରଣ ଅନୁସୂଚୀ
3. ରୋଗ ଯାଞ୍ଚ (ଲକ୍ଷଣ ଦ୍ୱାରା) 🩺
4. ସବୁଠାରୁ ନିକଟସ୍ଥ ସ୍ୱାସ୍ଥ୍ୟ କେନ୍ଦ୍ର ଖୋଜନ୍ତୁ
5. ଆମ ବିଷୟରେ
6. ଭାଷା ପରିବର୍ତ୍ତନ
7. ଚାଟ୍ ଛାଡ଼ନ୍ତୁ
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
        "chat_ended_prompt_restart": "Chat session ended. Please type 'hi' or 'hello' if you wish to start a new conversation.",

        # --- Disease Checker Prompts ---
        "ask_age": "Step 1/10: Please enter the patient's Age (e.g., 25).",
        "ask_weight": "Step 2/10: Enter Weight (e.g., 60kg).",
        "ask_gender": "Step 3/10: Enter Gender (Male/Female/Other).",
        "ask_reports": "Step 4/10: Any recent Test Reports? (Type 'None' if not).",
        "ask_eating": "Step 5/10: Describe daily eating routine.",
        "ask_meds": "Step 6/10: Any ongoing medications? (Type 'None' if not).",
        "ask_habits": "Step 7/10: Any habits like smoking/alcohol? (Type 'None' if not).",
        "ask_disability": "Step 8/10: Any physical/mental disabilities? (Type 'None' if not).",
        "ask_history": "Step 9/10: Any family history of diseases (Diabetes, Cancer, etc.)?",
        "ask_current_symptoms": "Step 10/10: Please describe the SYMPTOMS you are facing right now (e.g., Fever, Headache, Stomach pain):",
        
        "processing_diagnosis": "Thank you. Analyzing all 10 points to generate a report... Please wait."
    },
    'hi': {
        "welcome_back": "वापस स्वागत है!",
        "already_main_menu": "आप पहले से ही मुख्य मेनू में हैं।",
        "left_ai_assistant": "आपने AI स्वास्थ्य सहायक छोड़ दिया है।",
        "entering_ai_assistant": "ठीक है, AI स्वास्थ्य सहायक में प्रवेश कर रहा हूँ। मैं आज आपकी कैसे मदद कर सकता हूँ? (मुख्य मेनू पर लौटने के लिए 'back' टाइप करें)",
        "vaccination_selected": "आपने टीकाकरण अनुसूची चुना है। (मुख्य मेनू पर लौटने के लिए 'menu' टाइप करें)\nयहाँ टीकाकरण अनुसूची के बारे में जानकारी है...",
        "health_center_selected": "आपने निकटतम स्वास्थ्य केंद्र खोजें चुना है। (मुख्य मेनू पर लौटने के लिए 'menu' टाइप करें)\nकृपया निकटतम स्वास्थ्य केंद्र खोजने के लिए अपना वर्तमान स्थान या क्षेत्र बताएं।",
        "about_us_selected": "आपने हमारे बारे में चुना है। (मुख्य मेनू पर लौटने के लिए 'menu' टाइप करें)\nयह स्वास्थ्य AI स्वास्थ्य सूचना चैटबॉट है, जो Rasa और Gemini द्वारा संचालित है, जिसे बुनियादी सार्वजनिक स्वास्थ्य जानकारी प्रदान करने के लिए डिज़ाइन किया गया है। हमारा लक्ष्य स्वास्थ्य ज्ञान को सुलभ बनाना है। (मुख्य मेनू पर लौटने के लिए 'menu' टाइप करें)",
        "thank_you_goodbye": "स्वास्थ्य AI का उपयोग करने के लिए धन्यवाद! अलविदा। (पुनः शुरू करने के लिए 'hi' या 'hello' टाइप करें)",
        "invalid_option": "यह एक वैध विकल्प नहीं है। कृपया नीचे दिए गए मेनू से एक नंबर चुनें:",
        "rasa_no_response": "क्षमा करें, मुझे AI से कोई प्रतिक्रिया नहीं मिली। आप मुख्य मेनू पर लौटने के लिए 'back' कह सकते हैं।",
        "rasa_connection_error": "क्षमा करें, मुझे अभी अपने मस्तिष्क से जुड़ने में परेशानी हो रही है। कृपया मुख्य मेनू पर लौटने के लिए 'back' टाइप करें।",
        "chat_ended_prompt_restart": "चैट सत्र समाप्त हो गया है। यदि आप एक नई बातचीत शुरू करना चाहते हैं तो 'hi' या 'hello' टाइप करें।",

        # --- Disease Checker Prompts ---
        "ask_age": "चरण 1/10: कृपया रोगी की उम्र दर्ज करें (जैसे: 25).",
        "ask_weight": "चरण 2/10: वजन दर्ज करें (जैसे: 60kg).",
        "ask_gender": "चरण 3/10: लिंग दर्ज करें (पुरुष/महिला/अन्य).",
        "ask_reports": "चरण 4/10: क्या कोई हालिया जांच रिपोर्ट है? (यदि नहीं, तो 'None' या 'कोई नहीं' लिखें).",
        "ask_eating": "चरण 5/10: अपने दैनिक भोजन की दिनचर्या का वर्णन करें.",
        "ask_meds": "चरण 6/10: क्या कोई दवा चल रही है? (यदि नहीं, तो 'None' या 'कोई नहीं' लिखें).",
        "ask_habits": "चरण 7/10: क्या धूम्रपान/शराब जैसी कोई आदत है? (यदि नहीं, तो 'None' या 'कोई नहीं' लिखें).",
        "ask_disability": "चरण 8/10: क्या कोई शारीरिक/मानसिक विकलांगता है? (यदि नहीं, तो 'None' या 'कोई नहीं' लिखें).",
        "ask_history": "चरण 9/10: क्या बीमारियों का कोई पारिवारिक इतिहास है (जैसे मधुमेह, कैंसर, आदि)?",
        "ask_current_symptoms": "चरण 10/10: कृपया वर्तमान में आप जिन लक्षणों का सामना कर रहे हैं उनका वर्णन करें (जैसे बुखार, सिरदर्द, पेट दर्द):",
        "processing_diagnosis": "धन्यवाद। रिपोर्ट तैयार करने के लिए सभी 10 बिंदुओं का विश्लेषण किया जा रहा है... कृपया प्रतीक्षा करें."
    },
    'bn': {
        "welcome_back": "পুনরায় স্বাগতম!",
        "already_main_menu": "আপনি ইতিমধ্যেই প্রধান মেনুতে আছেন।",
        "left_ai_assistant": "আপনি AI স্বাস্থ্য সহায়ক ছেড়ে গেছেন।",
        "entering_ai_assistant": "ঠিক আছে, AI স্বাস্থ্য সহায়ক-এ প্রবেশ করছি। আমি আজ আপনাকে কীভাবে সাহায্য করতে পারি? (প্রধান মেনুতে ফিরে যেতে 'back' টাইপ করুন)",
        "vaccination_selected": "আপনি টিকা দেওয়ার সময়সূচী নির্বাচন করেছেন। (প্রধান মেনুতে ফিরে যেতে 'menu' টাইপ করুন)\nএখানে টিকা দেওয়ার সময়সূচী সম্পর্কিত তথ্য আছে...",
        "health_center_selected": "আপনি নিকটতম স্বাস্থ্য কেন্দ্র খুঁজুন নির্বাচন করেছেন। (প্রধান মেনুতে ফিরে যেতে 'menu' টাইপ করুন)\nনিকটতম স্বাস্থ্য কেন্দ্র খুঁজে পেতে দয়া করে আপনার বর্তমান অবস্থান বা এলাকা বলুন।",
        "about_us_selected": "আপনি আমাদের সম্পর্কে নির্বাচন করেছেন। (প্রধান মেনুতে ফিরে যেতে 'menu' টাইপ করুন)\nএটি স্বাচ্ছন্দ্য AI স্বাস্থ্য তথ্য চ্যাটবট, যা Rasa এবং Gemini দ্বারা চালিত, মৌলিক জনস্বাস্থ্য তথ্য সরবরাহ করার জন্য ডিজাইন করা হয়েছে। আমাদের লক্ষ্য হল স্বাস্থ্য জ্ঞানকে সহজলভ্য করা। (প্রধান মেনুতে ফিরে যেতে 'menu' টাইপ করুন)",
        "thank_you_goodbye": "স্বাস্থ্য AI ব্যবহার করার জন্য ধন্যবাদ! বিদায়। (পুনরায় শুরু করতে 'hi' বা 'hello' টাইপ করুন)",
        "invalid_option": "এটি একটি বৈধ বিকল্প নয়। দয়া করে নিচের মেনু থেকে একটি নম্বর বেছে নিন:",
        "rasa_no_response": "দুঃখিত, আমি AI থেকে কোনো প্রতিক্রিয়া পাইনি। আপনি প্রধান মেনুতে ফিরে যেতে 'back' বলতে পারেন।",
        "rasa_connection_error": "দুঃখিত, আমার মস্তিষ্কের সাথে সংযোগ করতে সমস্যা হচ্ছে। দয়া করে প্রধান মেনুতে ফিরে যেতে 'back' টাইপ করুন।",
        "chat_ended_prompt_restart": "চ্যাট সেশন শেষ হয়েছে। আপনি যদি নতুন কথোপকথন শুরু করতে চান তবে 'hi' বা 'hello' টাইপ করুন।",

        # --- Disease Checker Prompts ---
        "ask_age": "ধাপ 1/10: দয়া করে রোগীর বয়স লিখুন (যেমন: 25)।",
        "ask_weight": "ধাপ 2/10: ওজন লিখুন (যেমন: 60kg)।",
        "ask_gender": "ধাপ 3/10: লিঙ্গ লিখুন (পুরুষ/মহিলা/অন্যান্য)।",
        "ask_reports": "ধাপ 4/10: কোনো সাম্প্রতিক পরীক্ষার রিপোর্ট আছে? (যদি না থাকে, তবে 'None' বা 'কোনো নেই' লিখুন)।",
        "ask_eating": "ধাপ 5/10: দৈনিক খাদ্যাভ্যাস বর্ণনা করুন।",
        "ask_meds": "ধাপ 6/10: কোনো চলমান ওষুধ আছে? (যদি না থাকে, তবে 'None' বা 'কোনো নেই' লিখুন)।",
        "ask_habits": "ধাপ 7/10: ধূমপান/মদ্যপান এর মতো কোনো অভ্যাস আছে? (যদি না থাকে, তবে 'None' বা 'কোনো নেই' লিখুন)।",
        "ask_disability": "ধাপ 8/10: কোনো শারীরিক/মানসিক অক্ষমতা আছে? (যদি না থাকে, তবে 'None' বা 'কোনো নেই' লিখুন)।",
        "ask_history": "ধাপ 9/10: কোনো রোগের পারিবারিক ইতিহাস আছে (ডায়াবেটিস, ক্যান্সার, ইত্যাদি)?",
        "ask_current_symptoms": "ধাপ 10/10: দয়া করে বর্তমানে আপনি যে লক্ষণগুলি অনুভব করছেন তা বর্ণনা করুন (যেমন: জ্বর, মাথাব্যথা, পেটের ব্যথা):",
        "processing_diagnosis": "ধন্যবাদ। একটি রিপোর্ট তৈরি করতে সমস্ত 10টি পয়েন্ট বিশ্লেষণ করা হচ্ছে... দয়া করে অপেক্ষা করুন।"
    },
    'or': {
        "welcome_back": "ପୁଣି ସ୍ୱାଗତ!",
        "already_main_menu": "ଆପଣ ପୂର୍ବରୁ ମୁଖ୍ୟ ମେନୁରେ ଅଛନ୍ତି।",
        "left_ai_assistant": "ଆପଣ AI ସ୍ୱାସ୍ଥ୍ୟ ସହାୟକ ଛାଡି ଦେଇଛନ୍ତି।",
        "entering_ai_assistant": "ଠିକ୍ ଅଛି, AI ସ୍ୱାସ୍ଥ୍ୟ ସହାୟକରେ ପ୍ରବେଶ କରୁଛି। ମୁଁ ଆଜି ଆପଣଙ୍କୁ କିପରି ସାହାଯ୍ୟ କରିପାରିବି? (ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବା ପାଇଁ 'back' ଟାଇପ୍ କରନ୍ତୁ)",
        "vaccination_selected": "ଆପଣ ଟୀକାକରଣ ସୂଚୀ ବାଛିଛନ୍ତି। (ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବା ପାଇଁ 'menu' ଟାଇପ୍ କରନ୍ତୁ)\nଏଠାରେ ଟୀକାକରଣ ସୂଚୀ ବିଷୟରେ ସୂଚନା ଅଛି...",
        "health_center_selected": "ଆପଣ ନିକଟସ୍ଥ ସ୍ୱାସ୍ଥ୍ୟ କେନ୍ଦ୍ର ଖୋଜନ୍ତୁ ବାଛିଛନ୍ତି। (ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବା ପାଇଁ 'menu' ଟାଇପ୍ କରନ୍ତୁ)\nନିକଟସ୍ଥ ସ୍ୱାସ୍ଥ୍ୟ କେନ୍ଦ୍ର ଖୋଜିବା ପାଇଁ ଦୟାକରି ଆପଣଙ୍କ ବର୍ତ୍ତମାନର ସ୍ଥାନ କିମ୍ବା ଅଞ୍ଚଳ କୁହନ୍ତୁ।",
        "about_us_selected": "ଆପଣ ଆମ ବିଷୟରେ ବାଛିଛନ୍ତି। (ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବା ପାଇଁ 'menu' ଟାଇପ୍ କରନ୍ତୁ)\nଏହା ହେଉଛି ସ୍ୱାସ୍ଥ୍ୟ AI ସ୍ୱାସ୍ଥ୍ୟ ସୂଚନା ଚାଟ୍‌ବଟ୍, ଯାହା Rasa ଏବଂ Gemini ଦ୍ୱାରା ପରିଚାଳିତ, ମୌଳିକ ଜନସ୍ୱାସ୍ଥ୍ୟ ସୂଚନା ପ୍ରଦାନ କରିବା ପାଇଁ ଡିଜାଇନ୍ କରାଯାଇଛି। ଆମର ଲକ୍ଷ୍ୟ ହେଉଛି ସ୍ୱାସ୍ଥ୍ୟ ଜ୍ଞାନକୁ ସୁଗମ କରିବା। (ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବା ପାଇଁ 'menu' ଟାଇପ୍ କରନ୍ତୁ)",
        "thank_you_goodbye": "ସ୍ୱାସ୍ଥ୍ୟ AI ବ୍ୟବହାର କରିଥିବାରୁ ଧନ୍ୟବାଦ! ଶୁଭରାତ୍ରି। (ପୁନର୍ବାର ଆରମ୍ଭ କରିବାକୁ 'hi' କିମ୍ବା 'hello' ଟାଇପ୍ କରନ୍ତୁ)",
        "invalid_option": "ଏହା ଏକ ବୈଧ ବିକଳ୍ପ ନୁହେଁ। ଦୟାକରି ତଳ ମେନୁରୁ ଏକ ନମ୍ବର ବାଛନ୍ତୁ:",
        "rasa_no_response": "କ୍ଷମା କରନ୍ତୁ, ମୁଁ AI ରୁ କୌଣସି ପ୍ରତିକ୍ରିୟା ପାଇଲି ନାହିଁ। ଆପଣ ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବା ପାଇଁ 'back' କହିପାରିବେ।",
        "rasa_connection_error": "କ୍ଷମା କରନ୍ତୁ, ମୋର ମସ୍ତିଷ୍କ ସହିତ ସଂଯୋଗ କରିବାରେ ଅସୁବିଧା ହେଉଛି। ଦୟାକରି ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବା ପାଇଁ 'back' ଟାଇପ୍ କରନ୍ତୁ।",
        "chat_ended_prompt_restart": "ଚାଟ୍ ଅଧିବେଶନ ଶେଷ ହୋଇଛି। ଯଦି ଆପଣ ଏକ ନୂଆ କଥାବାର୍ତ୍ତା ଆରମ୍ଭ କରିବାକୁ ଚାହାଁନ୍ତି ତେବେ 'hi' କିମ୍ବା 'hello' ଟାଇପ୍ କରନ୍ତୁ।",

        # --- Disease Checker Prompts ---
        "ask_age": "ପଦକ୍ଷେପ 1/10: ଦୟାକରି ରୋଗୀଙ୍କ ବୟସ୍ ଦାଖଲ କରନ୍ତୁ (ଉଦାହରଣ: 25)।",
        "ask_weight": "ପଦକ୍ଷେପ 2/10: ଓଜନ୍ ଦାଖଲ କରନ୍ତୁ (ଉଦାହରଣ: 60kg)।",
        "ask_gender": "ପଦକ୍ଷେପ 3/10: ଲିଙ୍ଗ ଦାଖଲ କରନ୍ତୁ (ପୁରୁଷ/ମହିଳା/ଅନ୍ୟ).",
        "ask_reports": "ପଦକ୍ଷେପ 4/10: କୌଣସି ସাম্প୍ରତିକ ପରୀକ୍ଷା ରିପୋର୍ଟ ଅଛି? (ଯଦି ନାହିଁ, ତେବେ 'None' କିମ୍ବା 'କୌଣସି ନାହିଁ' ଟାଇପ୍ କରନ୍ତୁ)।",
        "ask_eating": "ପଦକ୍ଷେପ 5/10: ଦৈନନ୍ଦିନ ଖାଦ୍ୟ ଅଭ୍ୟାସ ବର୍ଣ୍ଣନା କରନ୍ତୁ।",
        "ask_meds": "ପଦକ୍ଷେପ 6/10: କୌଣସି ଚାଲୁଥିବା ଔଷଧ ଅଛି? (ଯଦି ନାହିଁ, ତେବେ 'None' କିମ୍ବା 'କୌଣସି ନାହିଁ' ଟାଇପ୍ କରନ୍ତୁ)।",
        "ask_habits": "ପଦକ୍ଷେପ 7/10: ଧୂମପାନ/ମଦ୍ୟପାନ ଭଳି କୌଣସି ଅଭ୍ୟାସ ଅଛି? (ଯଦି ନାହିଁ, ତେବେ 'None' କିମ୍ବା 'କୌଣସି ନାହିଁ' ଟାଇପ୍ କରନ୍ତୁ)।",
        "ask_disability": "ପଦକ୍ଷେପ 8/10: କୌଣସି ଶାରୀରିକ/ମାନସିକ ଅସମର୍ଥତା ଅଛି? (ଯଦି ନାହିଁ, ତେବେ 'None' କିମ୍ବା 'କୌଣସି ନାହିଁ' ଟାଇପ୍ କରନ୍ତୁ)।",
        "ask_history": "ପଦକ୍ଷେପ 9/10: କୌଣସି ରୋଗର ପାରିବାରିକ ଇତିହାସ ଅଛି (ମଧୁମେହ, କ୍ୟାନ୍ସର୍, ଇତ୍ୟାଦି)?",
        "ask_current_symptoms": "ପଦକ୍ଷେପ 10/10: ଦୟାକରି ବର୍ତ୍ତମାନ ଆପଣ ଯେଉଁ ଲକ୍ଷଣଗୁଡିକୁ ଅନୁଭବ କରୁଛନ୍ତି ସେଗୁଡିକୁ ବର୍ଣ୍ଣନା କରନ୍ତୁ (ଉଦାହରଣ: ଜ୍ୱର, ମୁଣ୍ଡବେଥା, ପେଟ୍ ବେଥା):",
        "processing_diagnosis": "ଧନ୍ୟବାଦ। ଏକ ରିପୋର୍ଟ ପ୍ରସ୍ତୁତ କରିବା ପାଇଁ ସମସ୍ତ 10ଟି ବିନ୍ଦୁ ବିଶ୍ଳେଷଣ କରାଯାଉଛି... ଦୟାକରି ପ୍ରତୀକ୍ଷା କରନ୍ତୁ।"
    }
}

# Language selection menu
LANGUAGE_MENU = """
Please select your preferred language / कृपया अपनी पसंदीदा भाषा चुनें / অনুগ্রহ করে আপনার পছন্দের ভাষা নির্বাচন করুন / ଦୟାକରି ଆପଣଙ୍କ ପସନ୍ଦର ଭାଷା ବାଛନ୍ତୁ:
1. English
2. हिंदी (Hindi)
3. বাংলা (Bengali)
4. ଓଡ଼ିଆ (Odia)
"""
# Closing prompt after each gemini response
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

# --- NEW: Database Helper Functions ---
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
        
        logger.info(f"Message sent to {to_number}: {message_body[:50]}...")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending message to WhatsApp API for {to_number}: {e}", exc_info=True)
        return None

# --- Image Helpers ---
def get_media_url_from_id(media_id):
    """
    Queries Meta API to get the URL for a specific media ID.
    """
    url = f"https://graph.facebook.com/v19.0/{media_id}"
    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get("url")
    except Exception as e:
        logger.error(f"Error getting media URL: {e}")
        return None

def download_image_bytes(media_url):
    """
    Downloads the actual image binary data from Meta's URL.
    """
    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}"}
    try:
        response = requests.get(media_url, headers=headers)
        response.raise_for_status()
        return response.content
    except Exception as e:
        logger.error(f"Error downloading image: {e}")
        return None

def analyze_image_with_gemini(image_bytes, lang='en'):
    """
    Sends the image to Gemini for medical/health analysis.
    """
    try:
        # Use Gemini 1.5 Pro (Correct model)
        model = genai.GenerativeModel('gemini-2.5-pro') 
        img = Image.open(io.BytesIO(image_bytes))
        
        # Construct Prompt based on Language
        if lang == 'hi':
            system_prompt = "आप एक सहायक चिकित्सा सहायक हैं। इस छवि का विश्लेषण करें (यदि यह घाव, त्वचा की समस्या, या दवा है) और सुझाव दें कि यह क्या हो सकता है और घरेलू उपचार क्या हैं। हमेशा सलाह दें कि 'कृपया डॉक्टर से मिलें'। बहुत संक्षेप में उत्तर दें।"
        elif lang == 'bn':
            system_prompt = "আপনি একজন সহায়ক চিকিৎসা সহকারী। এই চিত্রটি বিশ্লেষণ করুন (যদি এটি ক্ষত, ত্বকের সমস্যা বা ওষুধ হয়) এবং এটি কী হতে পারে এবং ঘরোয়া প্রতিকারগুলি কী তা পরামর্শ দিন। সর্বদা পরামর্শ দিন 'দয়া করে একজন ডাক্তারের সাথে দেখা করুন'। খুব সংক্ষেপে উত্তর দিন।"
        elif lang == 'or':
            system_prompt = "ଆପଣ ଜଣେ ସହାୟକ ଚିକିତ୍ସା ସହାୟକ ଅଟନ୍ତି। ଏହି ଚିତ୍ରକୁ ବିଶ୍ଳେଷଣ କରନ୍ତୁ (ଯଦି ଏହା କ୍ଷତ, ଚର୍ମ ସମସ୍ୟା କିମ୍ବା ଔଷଧ) ଏବଂ ଏହା କ’ଣ ହୋଇପାରେ ଏବଂ ଘରୋଇ ଉପଚାର କ’ଣ ତାହା ପରାମର୍ଶ ଦିଅନ୍ତୁ। ସର୍ବଦା ପରାମର୍ଶ ଦିଅନ୍ତୁ 'ଦୟାକରି ଡାକ୍ତରଙ୍କୁ ଦେଖା କରନ୍ତୁ'। ବହୁତ ସଂକ୍ଷେପରେ ଉତ୍ତର ଦିଅନ୍ତୁ।"
        else:
            system_prompt = "You are a helpful medical assistant. Analyze this image (if it is a wound, skin issue, or medicine) and suggest what it might be and actionable home remedies. Always add a disclaimer: 'This is AI advice, please consult a doctor'. Keep it concise."

        # Generate response content
        response = model.generate_content([system_prompt, img])
        return response.text
    except Exception as e:
        logger.error(f"Gemini Vision Error: {e}")
        return "Sorry, I could not analyze that image. Please try again with a clearer photo."

# ---------------------------------------------------------
# 4. MAIN LOGIC (Webhook Processor)
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

                    incoming_msg = ""
                    if msg_type == "text": incoming_msg = message["text"]["body"].strip()
                    elif msg_type == "button": incoming_msg = message["button"]["payload"].strip()

                    # Init State (Force Language Selection for new users)
                    if from_number not in user_states:
                        user_states[from_number] = {'state': 'language_selection', 'lang': 'en', 'data': {}}

                    current_state = user_states[from_number]['state']
                    current_lang = user_states[from_number]['lang']
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

                    # --- NAVIGATION & RESET LOGIC (FIXED) ---
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

                    # --- STEP 10: GET SYMPTOMS & PROCESS ---
                    if current_state == 'ask_current_symptoms':
                        user_states[from_number]['data']['current_symptoms'] = incoming_msg
                        
                        # Format data
                        d = user_states[from_number]['data']
                        data_str = (f"Age: {d.get('age')}, Weight: {d.get('weight')}, Gender: {d.get('gender')}, "
                                    f"Reports: {d.get('reports')}, Diet: {d.get('eating')}, "
                                    f"Meds: {d.get('meds')}, Habits: {d.get('habits')}, "
                                    f"Disability: {d.get('disability')}, History: {d.get('history')}, "
                                    f"CURRENT SYMPTOMS: {incoming_msg}")
                        
                        send_whatsapp_message(from_number, get_localized_message(from_number, "processing_diagnosis"))
                        
                        rasa_payload = f'/check_disease{{"patient_details": "{data_str}"}}'
                        try:
                            r = requests.post(RASA_WEBHOOK_URL, json={"sender": from_number, "message": rasa_payload, "metadata": {"lang": current_lang}})
                            for bot_msg in r.json():
                                if bot_msg.get("text"): send_whatsapp_message(from_number, bot_msg.get("text"))
                            
                            # --- THIS WAS MISSING: SEND CLOSING OPTIONS ---
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
                            r = requests.post(RASA_WEBHOOK_URL, json={"sender": from_number, "message": incoming_msg, "metadata": {"lang": current_lang}})
                            data = r.json()
                            if data:
                                for bot_msg in data:
                                    if bot_msg.get("text"): send_whatsapp_message(from_number, bot_msg.get("text"))
                                
                                closing = MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en'])
                                send_whatsapp_message(from_number, closing)
                                user_states[from_number]['state'] = 'awaiting_ai_choice'
                            else:
                                send_whatsapp_message(from_number, get_localized_message(from_number, "rasa_no_response"))
                        except: pass
                        return

                    # --- MAIN MENU LOGIC ---
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
                        elif normalized_msg == '4':
                            send_whatsapp_message(from_number, get_localized_message(from_number, "health_center_selected"))
                        elif normalized_msg == '5':
                            send_whatsapp_message(from_number, get_localized_message(from_number, "about_us_selected"))
                        elif normalized_msg == '6':
                            user_states[from_number]['state'] = 'language_selection'
                            send_whatsapp_message(from_number, LANGUAGE_MENU)
                        elif normalized_msg == '7':
                            user_states.pop(from_number, None)
                            send_whatsapp_message(from_number, get_localized_message(from_number, "thank_you_goodbye"))
                        else:
                            send_whatsapp_message(from_number, get_localized_message(from_number, "invalid_option"))
                            send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']))
                        return

    except Exception as e: logger.error(f"Logic Error: {e}")

# ---------------------------------------------------------
# 5. FLASK ROUTES
# ---------------------------------------------------------

# Flask app
@app.route("/whatsapp", methods=['GET'])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("WEBHOOK VERIFIED")
        return challenge, 200
    else:
        return "Verification failed", 403

# 6. MAIN WEBHOOK PROCESSING ROUTE
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