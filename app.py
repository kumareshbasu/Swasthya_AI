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
7. Change Language
8. Exit Chat
""",
    'hi': "\n1. सामान्य स्वास्थ्य\n2. टीकाकरण\n3. बीमारी जांच\n4. दवा की जानकारी 💊\n5. स्वास्थ्य केंद्र\n6. हमारे बारे में\n7. भाषा बदलें\n8. बाहर निकलें",
    'bn': "\n1. সাধারণ স্বাস্থ্য\n2. টিকা\n3. রোগ পরীক্ষক\n4. ওষুধের তথ্য 💊\n5. স্বাস্থ্য কেন্দ্র\n6. আমাদের সম্পর্কে\n7. ভাষা পরিবর্তন\n8. প্রস্থান",
    'or': "\n1. ସାଧାରଣ ସ୍ୱାସ୍ଥ୍ୟ\n2. ଟୀକାକରଣ\n3. ରୋଗ ଯାଞ୍ଚ\n4. ଔଷଧ ସୂଚନା 💊\n5. ସ୍ୱାସ୍ଥ୍ୟ କେନ୍ଦ୍ର\n6. ଆମ ବିଷୟରେ\n7. ଭାଷା ପରିବର୍ତ୍ତନ\n8. ବାହାରନ୍ତୁ"
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
    # (Other langs rely on fallback or you can add specific translations here)
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
    lang = user_states.get(from_number, {}).get('lang', 'en')
    msgs = MULTILINGUAL_STATIC_MESSAGES.get('en') 
    return msgs.get(key, "")

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

# --- LOGIC ---
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

                    # --- DISEASE CHECKER FLOW ---
                    if current_state == 'ask_age':
                        user_states[from_number]['data']['age'] = incoming_msg
                        user_states[from_number]['state'] = 'ask_weight'
                        send_whatsapp_message(from_number, get_localized_message(from_number, "ask_weight"))
                        return
                    # (Shortened steps 2-9 for brevity, logic remains identical to previous)
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
                            r = requests.post(RASA_WEBHOOK_URL, json={"sender": from_number, "message": rasa_payload, "metadata": {"lang": current_lang}})
                            for bot_msg in r.json():
                                if bot_msg.get("text"): send_whatsapp_message(from_number, bot_msg.get("text"))
                            
                            closing = MULTILINGUAL_AI_CLOSING.get(current_lang, MULTILINGUAL_AI_CLOSING['en'])
                            send_whatsapp_message(from_number, closing)
                            user_states[from_number]['state'] = 'awaiting_ai_choice'
                        except: pass
                        return

                    # --- MEDICINE INFO FLOW (NEW) ---
                    if current_state == 'ask_medicine_name':
                        medicine_name = incoming_msg
                        send_whatsapp_message(from_number, get_localized_message(from_number, "processing_medicine"))
                        
                        # Trigger Rasa Action
                        rasa_payload = f'/check_medicine{{"medicine_name": "{medicine_name}"}}'
                        try:
                            r = requests.post(RASA_WEBHOOK_URL, json={"sender": from_number, "message": rasa_payload, "metadata": {"lang": current_lang}})
                            for bot_msg in r.json():
                                if bot_msg.get("text"): send_whatsapp_message(from_number, bot_msg.get("text"))
                            
                            # Send closing
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
                        
                        # --- NEW OPTION 4: MEDICINE INFO ---
                        elif normalized_msg == '4': 
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