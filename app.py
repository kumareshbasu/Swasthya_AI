from flask import Flask, request, jsonify
import requests
import os
import json
import logging
import threading
from langdetect import detect, DetectorFactory # Import langdetect

# To ensure consistent language detection results
DetectorFactory.seed = 0 

app = Flask(__name__)

# --- Configuration for Meta WhatsApp Business Platform API ---
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "EAAJz0nEJSNgBP3DbZAZBxwzxuJFpNkGaPibZCEQ9jU5aXjRobP127i6uIZBb7SZAfVMIX4JVFwPF05h0eOIoF8W9Ioweci5f9q3bZBSZBASx9cI2ELxRG7cT4znZCElmkiYsuOX621L460BmBm5h2I9AYbBTegzC0PZCFEoITMembrE8RzWn873bdjEypEwZCSZB8tL44eSZAb93DdXhXIntDNnMqB0DWCqHXqcGGZAQgJ0Q9X1jEBjfPQdA8ASbeLdryXZAdjEvMHvwTwaAUssTP3lyTxXlRn")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "819746631222018")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "secret_swasthya_ai_is_the_best") 

META_API_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
RASA_WEBHOOK_URL = "http://localhost:5005/webhooks/rest/webhook"

user_states = {} # Stores user_states: {'from_number': {'state': 'main_menu', 'lang': 'en'}}

# --- Multilingual MAIN_MENU and static messages ---
MULTILINGUAL_MENUS = {
    'en': """
Welcome to Swasthya AI!
Please choose an option by typing its number:
1. General Health Info (Chat with AI)
2. Vaccination Schedule
3. Find Nearest Health Center
4. About Us
5. Exit Chat
""",
    'hi': """
स्वस्थ्य AI में आपका स्वागत है!
कृपया इसका नंबर टाइप करके एक विकल्प चुनें:
1. सामान्य स्वास्थ्य जानकारी (AI से बात करें)
2. टीकाकरण अनुसूची
3. निकटतम स्वास्थ्य केंद्र खोजें
4. हमारे बारे में
5. चैट से बाहर निकलें
""",
    'bn': """
স্বাস্থ্য AI-তে আপনাকে স্বাগতম!
দয়া করে এর নম্বর টাইপ করে একটি বিকল্প বেছে নিন:
1. সাধারণ স্বাস্থ্য তথ্য (AI এর সাথে চ্যাট করুন)
2. টিকা দেওয়ার সময়সূচী
3. নিকটতম স্বাস্থ্য কেন্দ্র খুঁজুন
4. আমাদের সম্পর্কে
5. চ্যাট থেকে প্রস্থান করুন
""",
    'or': """
ସ୍ୱାସ୍ଥ୍ୟ AI କୁ ସ୍ୱାଗତ!
ଦୟାକରି ଏହାର ନମ୍ବର ଟାଇପ୍ କରି ଏକ ବିକଳ୍ପ ବାଛନ୍ତୁ:
1. ସାଧାରଣ ସ୍ୱାସ୍ଥ୍ୟ ସୂଚନା (AI ସହିତ ଚାଟ୍ କରନ୍ତୁ)
2. ଟୀକାକରଣ ସୂଚୀ
3. ନିକଟସ୍ଥ ସ୍ୱାସ୍ଥ୍ୟ କେନ୍ଦ୍ର ଖୋଜନ୍ତୁ
4. ଆମ ବିଷୟରେ
5. ଚାଟ୍ ରୁ ବାହାରନ୍ତୁ
"""
}

# Add more multilingual static messages here if needed for menu confirmations
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
        "chat_ended_prompt_restart": "चैट सत्र समाप्त हो गया है। यदि आप एक नई बातचीत शुरू करना चाहते हैं तो 'hi' या 'hello' टाइप करें।"
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
        "chat_ended_prompt_restart": "চ্যাট সেশন শেষ হয়েছে। আপনি যদি নতুন কথোপকথন শুরু করতে চান তবে 'hi' বা 'hello' টাইপ করুন।"
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
        "chat_ended_prompt_restart": "ଚାଟ୍ ଅଧିବେଶନ ଶେଷ ହୋଇଛି। ଯଦି ଆପଣ ଏକ ନୂଆ କଥାବାର୍ତ୍ତା ଆରମ୍ଭ କରିବାକୁ ଚାହାଁନ୍ତି ତେବେ 'hi' କିମ୍ବା 'hello' ଟାଇପ୍ କରନ୍ତୁ।"
    }
}


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Helper function to get message in preferred language
def get_localized_message(from_number, key):
    user_data = user_states.get(from_number, {})
    lang = user_data.get('lang', 'en') # Default to English
    return MULTILINGUAL_STATIC_MESSAGES.get(lang, {}).get(key, MULTILINGUAL_STATIC_MESSAGES['en'][key])


# ... (your existing send_whatsapp_message function) ...
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
        logger.info(f"Message sent to {to_number} (lang:{user_states.get(to_number,{}).get('lang','en')}): {message_body[:50]}...") # Log language
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending message to WhatsApp API for {to_number}: {e}", exc_info=True)
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"WhatsApp API error response: {e.response.text}")
        return None


# ... (your existing verify_webhook GET route) ...

def process_webhook_event(data):
    """
    This function processes the webhook data in a background thread
    so the main route can return 200 OK immediately.
    """
    try:
        logger.info(f"THREAD: Processing webhook event: {json.dumps(data, indent=2)}")

        if "object" not in data or "entry" not in data:
            logger.warning("THREAD: Webhook event is not a valid WhatsApp event (missing 'object' or 'entry').")
            return # Exit thread

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

                    # --- LANGUAGE DETECTION ---
                    detected_lang = 'en' # Default
                    try:
                        if msg_type == "text" and not incoming_msg.isdigit() and len(incoming_msg) > 3:
                            detected_lang = detect(incoming_msg)
                            if detected_lang not in MULTILINGUAL_MENUS: 
                                detected_lang = 'en'
                        elif incoming_msg.lower() in ['hi', 'hello', 'start', 'menu']:
                             detected_lang = 'en' 
                    except Exception as e:
                        logger.warning(f"THREAD: Could not detect language for '{incoming_msg[:50]}...': {e}. Defaulting to 'en'.")
                        detected_lang = 'en'

                    if from_number not in user_states:
                        user_states[from_number] = {'state': 'initial', 'lang': detected_lang}
                    else:
                        user_states[from_number]['lang'] = detected_lang
                    
                    normalized_incoming_msg = incoming_msg.lower()

                    current_state = user_states[from_number]['state'] 
                    current_lang = user_states[from_number]['lang']
                    
                    logger.info(f"THREAD: Incoming from {from_number} (lang:{current_lang}): '{normalized_incoming_msg}' in state '{current_state}'")

                    if normalized_incoming_msg in ['hi', 'hello', 'menu', 'start']:
                        if current_state == 'main_menu':
                            send_whatsapp_message(from_number, get_localized_message(from_number, "already_main_menu"))
                        elif current_state == 'in_rasa_conversation':
                            send_whatsapp_message(from_number, get_localized_message(from_number, "left_ai_assistant"))
                        elif current_state == 'exited_chat':
                            send_whatsapp_message(from_number, get_localized_message(from_number, "welcome_back"))
                        
                        user_states[from_number]['state'] = 'main_menu' 
                        send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en'])) 
                        logger.info(f"THREAD: User {from_number} navigated to MAIN_MENU in {current_lang}.")
                        return # 3. Changed from 'return jsonify(...)' to just 'return'

                    if current_state == 'initial':
                        user_states[from_number]['state'] = 'main_menu'
                        send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']))
                        logger.info(f"THREAD: New user {from_number} showing MAIN_MENU in {current_lang}.")
                        return 

                    if current_state == 'in_rasa_conversation':
                        if normalized_incoming_msg in ['back', 'main menu']: 
                            user_states[from_number]['state'] = 'main_menu'
                            send_whatsapp_message(from_number, get_localized_message(from_number, "left_ai_assistant"))
                            send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']))
                            logger.info(f"THREAD: User {from_number} explicitly went 'back' to main menu in {current_lang}.")
                            return
                        else:
                            logger.info(f"THREAD: Forwarding message to Rasa for {from_number} (lang:{current_lang}): '{incoming_msg}'")
                            try:
                                rasa_response = requests.post(
                                    RASA_WEBHOOK_URL,
                                    json={"sender": from_number, "message": incoming_msg, "metadata": {"lang": current_lang}} 
                                )
                                rasa_response.raise_for_status()
                                
                                rasa_data = rasa_response.json()
                                logger.info(f"THREAD: Received from Rasa (raw) for {from_number}: {json.dumps(rasa_data, indent=2)}")

                                if rasa_data:
                                    for bot_message in rasa_data:
                                        if bot_message.get("text"):
                                            send_whatsapp_message(from_number, bot_message.get("text"))
                                            logger.info(f"THREAD: Dispatched Rasa text message to {from_number} (lang:{current_lang}): '{bot_message.get('text')[:50]}...'")
                                        if bot_message.get("image"):
                                            image_url = bot_message.get("image")
                                            if image_url:
                                                headers = {
                                                    "Authorization": f"Bearer {META_ACCESS_TOKEN}",
                                                    "Content-Type": "application/json",
                                                }
                                                image_payload = {
                                                    "messaging_product": "whatsapp",
                                                    "to": from_number,
                                                    "type": "image",
                                                    "image": {"link": image_url},
                                                }
                                                requests.post(META_API_URL, headers=headers, json=image_payload)
                                                logger.info(f"THREAD: Dispatched Rasa image message to {from_number}: '{image_url}'")
                                            else:
                                                logger.warning(f"THREAD: Rasa sent an image message without a URL for {from_number}.")

                                else:
                                    send_whatsapp_message(from_number, get_localized_message(from_number, "rasa_no_response"))
                                    logger.warning(f"THREAD: Rasa data was empty for {from_number}. Sending generic no-response message in {current_lang}.")

                            except requests.exceptions.RequestException as e:
                                logger.error(f"THREAD: Error connecting to Rasa for {from_number}: {e}", exc_info=True)
                                send_whatsapp_message(from_number, get_localized_message(from_number, "rasa_connection_error"))
                        return 
                    
                    elif current_state == 'exited_chat':
                        send_whatsapp_message(from_number, get_localized_message(from_number, "chat_ended_prompt_restart"))
                        logger.info(f"THREAD: User {from_number} in 'exited_chat' state in {current_lang}.")
                        return 

                    elif current_state == 'main_menu':
                        if normalized_incoming_msg == '1':
                            user_states[from_number]['state'] = 'in_rasa_conversation'
                            send_whatsapp_message(from_number, get_localized_message(from_number, "entering_ai_assistant"))
                            logger.info(f"THREAD: User {from_number} entered AI Assistant in {current_lang}.")
                        elif normalized_incoming_msg == '2':
                            send_whatsapp_message(from_number, get_localized_message(from_number, "vaccination_selected"))
                            logger.info(f"THREAD: User {from_number} selected Vaccination info in {current_lang}.")
                        elif normalized_incoming_msg == '3':
                            send_whatsapp_message(from_number, get_localized_message(from_number, "health_center_selected"))
                            logger.info(f"THREAD: User {from_number} selected Health Center in {current_lang}.")
                        elif normalized_incoming_msg == '4':
                            send_whatsapp_message(from_number, get_localized_message(from_number, "about_us_selected"))
                            logger.info(f"THREAD: User {from_number} selected About Us in {current_lang}.")
                        elif normalized_incoming_msg == '5':
                            user_states[from_number]['state'] = 'exited_chat' 
                            send_whatsapp_message(from_number, get_localized_message(from_number, "thank_you_goodbye"))
                            logger.info(f"THREAD: User {from_number} exited chat in {current_lang}.")
                        else:
                            send_whatsapp_message(from_number, get_localized_message(from_number, "invalid_option"))
                            send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']))
                            logger.info(f"THREAD: User {from_number} entered invalid main menu option. Redisplaying menu in {current_lang}.")
                        return
                    
                    logger.warning(f"THREAD: No state matched for incoming message: '{normalized_incoming_msg}' from {from_number}. This should not happen. Defaulting to main menu.")
                    user_states[from_number]['state'] = 'main_menu'
                    send_whatsapp_message(from_number, MULTILINGUAL_MENUS.get(current_lang, MULTILINGUAL_MENUS['en']))
                    return

        logger.warning("THREAD: No messages found in the incoming webhook event (might be a status update or other event).")
    
    except Exception as e:
        logger.error(f"THREAD: Unhandled exception in process_webhook_event: {e}", exc_info=True)


@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    """
    This is the main webhook handler.
    It acknowledges the webhook immediately with 200 OK
    and starts a background thread to handle the logic.
    """
    try:
        data = request.get_json()
        if not data:
            logger.error("Received empty JSON data or non-JSON request.")
            return "Bad Request: No JSON data received", 400
    except Exception as e:
        logger.error(f"Could not parse request JSON: {e}")
        return "Bad Request: Malformed JSON", 400

    # 4. START THE BACKGROUND THREAD with the new function
    thread = threading.Thread(target=process_webhook_event, args=(data,))
    thread.start()

    # 5. IMMEDIATELY RETURN 200 OK TO META
    logger.info("Webhook received. Acknowledging 200 OK and processing in background.")
    return jsonify({"status": "pending_processing"}), 200


if __name__ == "__main__":
    app.run(port=6000, debug=True)