#actions.py
import google.generativeai as genai
import os
from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet 
import logging 
import requests
from PIL import Image
import io
from supabase import create_client, Client
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# --- Gemini Initialization ---
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

global_gemini_model_name = "gemini-2.5-flash" # Ensure this is 'gemini-2.5-flash'
try:
    global_gemini_model_instance = genai.GenerativeModel(global_gemini_model_name)
    logger.info(f"Globally initialized Gemini model: {global_gemini_model_name}")
except Exception as e:
    logger.error(f"Failed to initialize Gemini model globally: {e}. Will try initializing in run() method.", exc_info=True)
    global_gemini_model_instance = None


# --- SUPABASE CLIENT SETUP ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("Supabase client initialized successfully.")
except Exception as e:
    logger.error(f"Supabase connection failed: {e}")
    supabase = None

# --- ActionAskGemini (MODIFIED) ---
class ActionAskGemini(Action):
    def name(self) -> Text:
        return "action_ask_gemini"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        # 1. CHECK METADATA FOR 'DETAILED' FLAG (From Code 2)
        metadata = tracker.latest_message.get('metadata', {})
        is_detailed = metadata.get('detailed_response', False)

        # Set length instruction based on the flag
        if is_detailed:
            length_instruction = "Provide a VERY DETAILED, comprehensive explanation with examples."
        else:
            length_instruction = "Keep the response SHORT, CONCISE, and under 150-200 words."

        # 2. EXTRACT INTENT AND ENTITIES (From Code 1)
        intent = tracker.latest_message['intent'].get('name')
        entities = tracker.latest_message.get('entities', [])
        disease = None
        for entity in entities:
            if entity.get('entity') == 'disease':
                disease = entity.get('value')
                break 

        # 3. GET USER LANGUAGE (From Code 1)
        user_lang = tracker.get_slot('lang') 
        if not user_lang: 
            user_lang = tracker.latest_message.get('metadata', {}).get('lang', 'en')
            if not user_lang: 
                user_lang = 'en'
        
        logger.info(f"DEBUG ACTIONS: Intent: {intent}, Disease: {disease}, Lang: {user_lang}, Detailed: {is_detailed}")

        if not disease:
            logger.warning("No disease entity extracted for Gemini query.")
            dispatcher.utter_message(text=f"I can help with that. Which disease or symptom are you interested in? (Lang: {user_lang})")
            return []
        
        # 4. CONSTRUCT BASE PROMPT (From Code 1)
        base_prompt = ""
        if intent == "ask_symptoms":
            base_prompt = f"As a public health expert, explain the common symptoms of '{disease}' in simple terms for a rural audience."
        elif intent == "ask_preventive_measures":
            base_prompt = f"As a public health expert, describe simple, actionable preventive measures for '{disease}' for a rural audience."
        else: 
            base_prompt = f"As a public health expert, provide an overview of '{disease}' for a rural audience."

        # 5. LANGUAGE MAPPING (From Code 1)
        lang_names = {
            'en': 'English',
            'hi': 'Hindi',
            'bn': 'Bengali',
            'or': 'Odia'
        }
        lang_name_for_gemini = lang_names.get(user_lang, 'English')

        # 6. FINAL PROMPT ASSEMBLY (Merged)
        # We combine the base prompt + length instruction + language instruction
        prompt = f"{base_prompt} {length_instruction} Respond ONLY in {lang_name_for_gemini}."

        logger.info(f"DEBUG ACTIONS: Prompt: '{prompt}...'")

        # 7. CALL GEMINI API (From Code 1)
        try:
            model = global_gemini_model_instance
            if not model: 
                logger.warning("Falling back to local Gemini model initialization.")
                model = genai.GenerativeModel(global_gemini_model_name) 

            response = model.generate_content(prompt)
            
            if response and hasattr(response, 'text') and response.text:
                final_text_to_dispatch = response.text 
                dispatcher.utter_message(text=final_text_to_dispatch) 
            else:
                logger.warning(f"Gemini API returned an empty response.")
                dispatcher.utter_message(response="utter_default_fallback") 
        except Exception as e: 
            logger.error(f"General Error during Gemini API call: {e}", exc_info=True) 
            dispatcher.utter_message(response="utter_default_fallback")

        return []

# --- ActionSetLanguageSlot (NEW) ---
class ActionSetLanguageSlot(Action):
    def name(self) -> Text:
        return "action_set_language_slot"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        lang = tracker.latest_message.get('metadata', {}).get('lang', 'en')
        logger.info(f"DEBUG ACTIONS: Setting 'lang' slot to: '{lang}' from metadata.")
        return [SlotSet("lang", lang)]
    

# --- NEW ACTION FOR IMAGES ---
class ActionAnalyzeImageGemini(Action):
    def name(self) -> Text:
        return "action_analyze_image_gemini"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        # 1. Get the image URL and Language from the tracker
        image_url = tracker.get_slot('image_url')
        user_lang = tracker.latest_message.get('metadata', {}).get('lang', 'en')
        
        # We need the Meta Token here to download the image
        # (Ideally, use os.environ, but for simplicity we copy it here as you did in app.py)
        META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")

        if not image_url:
            dispatcher.utter_message(text="I received the image request, but the URL is missing.")
            return []

        # 2. Download the Image Bytes
        headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}"}
        try:
            logger.info(f"DEBUG ACTIONS: Downloading image from {image_url}")
            response = requests.get(image_url, headers=headers)
            response.raise_for_status()
            image_bytes = response.content
        except Exception as e:
            logger.error(f"Failed to download image in actions.py: {e}")
            dispatcher.utter_message(text="I'm having trouble downloading that image from WhatsApp.")
            return []

        # 3. Prepare Gemini
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            img = Image.open(io.BytesIO(image_bytes))

            # 4. Construct Prompt
            if user_lang == 'hi':
                system_prompt = "आप एक सहायक चिकित्सा सहायक हैं। इस छवि का विश्लेषण करें और सुझाव दें। हमेशा सलाह दें कि 'कृपया डॉक्टर से मिलें'।"
            elif user_lang == 'bn':
                system_prompt = "আপনি একজন সহায়ক চিকিৎসা সহকারী। এই চিত্রটি বিশ্লেষণ করুন এবং পরামর্শ দিন। সর্বদা পরামর্শ দিন 'দয়া করে একজন ডাক্তারের সাথে দেখা করুন'।"
            elif user_lang == 'or':
                system_prompt = "ଆପଣ ଜଣେ ସହାୟକ ଚିକିତ୍ସା ସହାୟକ ଅଟନ୍ତି। ଏହି ଚିତ୍ରକୁ ବିଶ୍ଳେଷଣ କରନ୍ତୁ ଏବଂ ପରାମର୍ଶ ଦିଅନ୍ତୁ। ସର୍ବଦା ପରାମର୍ଶ ଦିଅନ୍ତୁ 'ଦୟାକରି ଡାକ୍ତରଙ୍କୁ ଦେଖା କରନ୍ତୁ'।"
            else:
                system_prompt = "You are a helpful medical assistant. Analyze this image (wound/symptom) and suggest what it might be and home remedies. Add disclaimer: 'Consult a doctor'."

            # 5. Generate
            logger.info("DEBUG ACTIONS: Sending image to Gemini...")
            gemini_response = model.generate_content([system_prompt, img])
            
            if gemini_response and gemini_response.text:
                dispatcher.utter_message(text=gemini_response.text)
            else:
                dispatcher.utter_message(text="I couldn't interpret that image.")
            
            """ # --- SEND CLOSING PROMPT AFTER IMAGE ANALYSIS ---
            closing_options = {
                'en': "This response is completed.\nSelect any one option:\n1. Do you want to ask anything more about this or something else?\n2. Would you like to go back to main menu?",
                'hi': "उत्तर पूरा हो गया है।\nकृपया एक विकल्प चुनें:\n1. क्या आप इसके बारे में या किसी अन्य विषय पर और पूछना चाहते हैं?\n2. क्या आप मुख्य मेनू पर वापस जाना चाहते हैं?",
                'bn': "উত্তর সম্পূর্ণ হয়েছে।\nএকটি বিকল্প নির্বাচন করুন:\n1. আপনি কি এ সম্পর্কে বা অন্য কিছু সম্পর্কে আরও জানতে চান?\n2. আপনি কি প্রধান মেনুতে ফিরে যেতে চান?",
                'or': "ଉତ୍ତର ସମାପ୍ତ ହୋଇଛି।\nଦୟାକରି ଏକ ବିକଳ୍ପ ବାଛନ୍ତୁ:\n1. ଆପଣ ଏହା ବିଷୟରେ କିମ୍ବା ଅନ୍ୟ କିଛି ବିଷୟରେ ଅଧିକ ପଚାରିବାକୁ ଚାହାନ୍ତି କି?\n2. ଆପଣ ମୁଖ୍ୟ ମେନୁକୁ ଫେରିବାକୁ ଚାହାନ୍ତି କି?"
            } 
            dispatcher.utter_message(text=closing_options.get(user_lang, closing_options['en']))"""

        except Exception as e:
            logger.error(f"Gemini Vision Error in actions: {e}")
            dispatcher.utter_message(text="Sorry, I encountered an error analyzing the image.")

        return []
    
# --- NEW ACTION FOR NON-HEALTH QUERIES ---
class ActionHandleNonHealthQuery(Action):
    def name(self) -> Text:
        return "action_handle_non_health_query"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        user_lang = tracker.get_slot("lang") or "en"

        replies = {
            "en": "Sorry, I am a Health Chatbot. Please ask health-related questions.",
            "hi": "क्षमा करें, मैं एक स्वास्थ्य चैटबोट हूँ। कृपया स्वास्थ्य संबंधी प्रश्न पूछें।",
            "bn": "দুঃখিত, আমি একটি স্বাস্থ্য চ্যাটবট। অনুগ্রহ করে স্বাস্থ্য সম্পর্কিত প্রশ্ন করুন।",
            "or": "ଦୁଃଖିତ, ମୁଁ ଏକ ସ୍ୱାସ୍ଥ୍ୟ ଚାଟବଟ୍। ଦୟାକରି ସ୍ୱାସ୍ଥ୍ୟ ସମ୍ୱନ୍ଧୀୟ ପ୍ରଶ୍ନ ପଚାରନ୍ତୁ।"
        }

        dispatcher.utter_message(text=replies.get(user_lang, replies["en"]))
        return []


# --- NEW ACTION FOR GIBBERISH QUERIES --- 
class ActionHandleGibberish(Action):
    def name(self) -> Text:
        return "action_handle_gibberish"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        user_lang = tracker.get_slot("lang") or "en"

        replies = {
            "en": "I couldn't understand that. Please send a valid health-related question.",
            "hi": "मैं समझ नहीं पाया। कृपया कोई सही स्वास्थ्य संबंधी प्रश्न भेजें।",
            "bn": "আমি বুঝতে পারিনি। অনুগ্রহ করে একটি সঠিক স্বাস্থ্য সম্পর্কিত প্রশ্ন পাঠান।",
            "or": "ମୁଁ ଏହା ବୁଝିପାରିଲି ନାହିଁ। ଦୟାକରି ଏକ ସଠିକ୍ ସ୍ୱାସ୍ଥ୍ୟ ସମ୍ୱନ୍ଧୀୟ ପ୍ରଶ୍ନ ପଠାନ୍ତୁ।"
        }

        dispatcher.utter_message(text=replies.get(user_lang, replies["en"]))
        return []

# --- NEW ACTION: DISEASE CHECKER (SYMPTOMS) ---
class ActionCheckDiseaseGemini(Action):
    def name(self) -> Text:
        return "action_check_disease_gemini"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        details = tracker.get_slot('patient_details')
        user_lang = tracker.latest_message.get('metadata', {}).get('lang', 'en')
        
        logger.info(f"DEBUG ACTIONS: Disease Check for: {details}")

        if not details:
            dispatcher.utter_message(text="Error: No patient details provided.")
            return []

        # Prompt based on Language
        lang_instruction = "Respond in English."
        if user_lang == 'hi': lang_instruction = "उत्तर हिंदी में दें।"
        elif user_lang == 'bn': lang_instruction = "বাংলায় উত্তর দিন।"
        elif user_lang == 'or': lang_instruction = "ଓଡିଆରେ ଉତ୍ତର ଦିଅନ୍ତୁ |"

        system_prompt = f"""
        Act as an experienced diagnostic assistant. 
        Patient Profile & Symptoms:
        {details}

        Tasks:
        1. Identify all possible causes/diseases.
        2. Suggest immediate home care steps.
        3. Recommend which specialist (e.g., Cardiologist, Dermatologist) to visit.

        MANDATORY DISCLAIMER: "This is AI advice, NOT a medical diagnosis. Please consult a doctor."
        
        {lang_instruction}
        """

        try:
            model = global_gemini_model_instance or genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(system_prompt)
            
            if response and response.text:
                dispatcher.utter_message(text=response.text)
            else:
                dispatcher.utter_message(text="I couldn't generate a diagnosis.")

        except Exception as e:
            logger.error(f"Disease Checker Error: {e}")
            dispatcher.utter_message(text="Error processing diagnosis.")
        
        return []
    
# --- NEW ACTION: MEDICINE CHECKER ---
class ActionCheckMedicineGemini(Action):
    def name(self) -> Text:
        return "action_check_medicine_gemini"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        # 1. Extract Intent and Entities
        intent = tracker.latest_message['intent'].get('name')
        entities = tracker.latest_message.get('entities', [])
        
        # 2. Get Medicine Name
        medicine = tracker.get_slot('medicine_name')
        if not medicine:
            for entity in entities:
                if entity.get('entity') == 'medicine_name':
                    medicine = entity.get('value')
                    break

        # 3. Get User Language
        user_lang = tracker.get_slot('lang') 
        if not user_lang: 
            user_lang = tracker.latest_message.get('metadata', {}).get('lang', 'en')
            if not user_lang: user_lang = 'en'
        
        # --- CLEANING STEP (The Fix) ---
        # Sometimes Rasa extracts "Prolavir benefits" as the name. We clean it here.
        if medicine:
            ignore_words = ["benefits", "benefit", "uses", "use", "side effects", "dosage", "price", "info", "details", "about", "of"]
            for word in ignore_words:
                # Case-insensitive replacement
                medicine = medicine.lower().replace(word, "").strip()

        logger.info(f"DEBUG ACTIONS: Intent: {intent}, Cleaned Medicine: {medicine}, Lang: {user_lang}")

        if not medicine:
            dispatcher.utter_message(text="Error: No medicine name provided.")
            return []

        # 4. Prompt Construction
        lang_instruction = "Respond in English."
        if user_lang == 'hi': lang_instruction = "उत्तर हिंदी में दें।"
        elif user_lang == 'bn': lang_instruction = "বাংলায় উত্তর দিন।"
        elif user_lang == 'or': lang_instruction = "ଓଡିଆରେ ଉତ୍ତର ଦିଅନ୍ତୁ |"

        system_prompt = f"""
        Act as a professional pharmacist. 
        Medicine Name: "{medicine}"

        Please provide the following details clearly:
        1. Uses (What is it for?)
        2. Side Effects (Common risks)
        3. Dosage/Usage (General instructions)
        4. Warnings (Who should avoid it?)

        MANDATORY DISCLAIMER: "This is AI-generated information. Consult a doctor before taking any medication."
        
        {lang_instruction}
        """

        try:
            model = global_gemini_model_instance or genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(system_prompt)
            
            if response and response.text:
                dispatcher.utter_message(text=response.text)
            else:
                dispatcher.utter_message(text="I couldn't find details for this medicine.")

        except Exception as e:
            logger.error(f"Medicine Check Error: {e}")
            dispatcher.utter_message(text="Sorry, I encountered an error checking the medicine.")
        
        return []
    
# --- NEW ACTION FOR NON-HEALTH QUERIES ---
class ActionHandleNonHealthQuery(Action):
    def name(self) -> Text:
        return "action_handle_non_health_query"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        user_lang = tracker.get_slot("lang") or "en"

        replies = {
            "en": "Sorry, I am a Health Chatbot. Please ask health-related questions.",
            "hi": "क्षमा करें, मैं एक स्वास्थ्य चैटबोट हूँ। कृपया स्वास्थ्य संबंधी प्रश्न पूछें।",
            "bn": "দুঃখিত, আমি একটি স্বাস্থ্য চ্যাটবট। অনুগ্রহ করে স্বাস্থ্য সম্পর্কিত প্রশ্ন করুন।",
            "or": "ଦୁଃଖିତ, ମୁଁ ଏକ ସ୍ୱାସ୍ଥ୍ୟ ଚାଟବଟ୍। ଦୟାକରି ସ୍ୱାସ୍ଥ୍ୟ ସମ୍ୱନ୍ଧୀୟ ପ୍ରଶ୍ନ ପଚାରନ୍ତୁ।"
        }

        dispatcher.utter_message(text=replies.get(user_lang, replies["en"]))
        return []

# --- NEW ACTION FOR GIBBERISH QUERIES --- 
class ActionHandleGibberish(Action):
    def name(self) -> Text:
        return "action_handle_gibberish"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        user_lang = tracker.get_slot("lang") or "en"

        replies = {
            "en": "I couldn't understand that. Please send a valid health-related question.",
            "hi": "मैं समझ नहीं पाया। कृपया कोई सही स्वास्थ्य संबंधी प्रश्न भेजें।",
            "bn": "আমি বুঝতে পারিনি। অনুগ্রহ করে একটি সঠিক স্বাস্থ্য সম্পর্কিত প্রশ্ন পাঠান।",
            "or": "ମୁଁ ଏହା ବୁଝିପାରିଲି ନାହିଁ। ଦୟାକରି ଏକ ସଠିକ୍ ସ୍ୱାସ୍ଥ୍ୟ ସମ୍ୱନ୍ଧୀୟ ପ୍ରଶ୍ନ ପଠାନ୍ତୁ।"
        }

        dispatcher.utter_message(text=replies.get(user_lang, replies["en"]))
        return []
    
# NEW ACTION FOR VACCINE STANDARD SCHEDULE ---
# actions.py

class ActionVaccineStandard(Action):
    def name(self):
        return "action_vaccine_standard"

    def run(self, dispatcher, tracker, domain):
        # FIX: Check metadata (from Flask) FIRST, then Slot, then default to English
        lang = tracker.latest_message.get('metadata', {}).get('lang') or tracker.get_slot("lang") or "en"
        
        print(f"🔍 [VACCINE] Fetching full vaccination schedule for language: {lang}")

        try:
            result = (
                supabase.table("vaccine_schedule")
                .select("*")
                .eq("language", lang)
                .order("recommended_age_weeks", desc=False)
                .execute()
            )
            rows = result.data
        except Exception as e:
            print("❌ [DB ERROR] =>", e)
            dispatcher.utter_message(text="Database error.")
            return []

        if not rows:
            dispatcher.utter_message(text=f"No vaccine data found for language: {lang}")
            return []

        reply = ""
        for r in rows:
            reply += (
                f"💉 *{r['vaccine_name']}* ({r['dose_name']})\n"
                f"👶 {r['age_group']}\n"
                f"ℹ️ {r['description']}\n\n"
            )

        dispatcher.utter_message(text=reply)
        return []


# NEW ACTION FOR VACCINE SCHEDULE BASED ON CHILD'S DOB ---  
class ActionVaccineChild(Action):
    def name(self):
        return "action_vaccine_child"

    def run(self, dispatcher, tracker, domain):

        # 1. Get Inputs safely
        dob = tracker.get_slot("dob")
        
        # Get language from metadata first (Flask), then slot (Rasa), default to 'en'
        metadata = tracker.latest_message.get('metadata', {}) or {}
        lang = metadata.get('lang') or tracker.get_slot("lang") or "en"

        # 2. Define Messages Dictionary (Moved inside for safety)
        messages = {
            "en": {
                "child_age": "🧒 Child's Age:",
                "weeks": "weeks",
                "months": "months",
                "years": "years",
                "adult_fallback": "⚠️ Vaccination schedule applies only up to 16 years. No further vaccines required.",
                "dob_missing": "Date of birth is missing.",
                "invalid_dob": "Invalid DOB format. Use YYYY-MM-DD.",
                "no_upcoming": "🎉 No upcoming vaccines required.",
                "db_error": "Database error while fetching vaccines."
            },
            "hi": {
                "child_age": "🧒 बच्चे की उम्र:",
                "weeks": "सप्ताह",
                "months": "महीने",
                "years": "साल",
                "adult_fallback": "⚠️ टीकाकरण अनुसूची 16 वर्ष तक ही लागू होती है।",
                "dob_missing": "जन्म तिथि उपलब्ध नहीं है।",
                "invalid_dob": "अमान्य प्रारूप। कृपया YYYY-MM-DD उपयोग करें।",
                "no_upcoming": "🎉 आगे कोई टीका आवश्यक नहीं है।",
                "db_error": "टीके प्राप्त करते समय डेटाबेस त्रुटि।"
            },
            "bn": {
                "child_age": "🧒 শিশুর বয়স:",
                "weeks": "সপ্তাহ",
                "months": "মাস",
                "years": "বছর",
                "adult_fallback": "⚠️ টিকাদান সূচি শুধুমাত্র ১৬ বছর পর্যন্ত।",
                "dob_missing": "জন্মতারিখ অনুপস্থিত।",
                "invalid_dob": "ভুল ফরম্যাট। দয়া করে YYYY-MM-DD ব্যবহার করুন।",
                "no_upcoming": "🎉 আর কোনো টিকা প্রয়োজন নেই।",
                "db_error": "ডেটাবেস ত্রুটি।"
            },
            "or": {
                "child_age": "🧒 ଶିଶୁର ବୟସ୍:",
                "weeks": "ସପ୍ତାହ",
                "months": "ମାସ",
                "years": "ବର୍ଷ",
                "adult_fallback": "⚠️ ଟୀକା ସୂଚୀ କେବଳ 16 ବର୍ଷ ପର୍ଯ୍ୟନ୍ତ ଲାଗୁହୁଏ।",
                "dob_missing": "ଜନ୍ମତାରିଖ ମିଳିଲା ନାହିଁ।",
                "invalid_dob": "ଭୁଲ ଫର୍ମାଟ୍। YYYY-MM-DD ରେ ଲେଖନ୍ତୁ।",
                "no_upcoming": "🎉 ଆଗାମୀ ଟୀକା କିଛି ନାହିଁ।",
                "db_error": "ଡାଟାବେସ୍ ତ୍ରୁଟି।"
            }
        }

        # 3. Safe Language Fallback
        # This ensures 'msg' is never None
        msg = messages.get(lang, messages["en"])

        # 4. Validation
        if not dob:
            dispatcher.utter_message(text=msg["dob_missing"])
            return []

        try:
            dob_dt = datetime.strptime(dob, "%Y-%m-%d")
        except ValueError:
            dispatcher.utter_message(text=msg["invalid_dob"])
            return []

        # 5. Age Calculation
        today = datetime.today()
        age_days = (today - dob_dt).days
        
        # Basic validation for future dates
        if age_days < 0:
             dispatcher.utter_message(text="Date of birth cannot be in the future.")
             return []

        age_weeks = age_days // 7
        age_months = age_days // 30
        age_years = age_days // 365

        # 6. Age Response
        age_msg = f"{msg['child_age']}\n• {age_weeks} {msg['weeks']}\n"
        if age_months > 0:
            age_msg += f"• {age_months} {msg['months']}\n"
        if age_years > 0:
            age_msg += f"• {age_years} {msg['years']}\n"

        dispatcher.utter_message(text=age_msg)

        # 7. Adult Fallback
        if age_weeks > 900:  # approx 16 years
            dispatcher.utter_message(text=msg["adult_fallback"])
            return []

        # 8. Database Fetch
        try:
            # First try requested language
            data = (
                supabase.table("vaccine_schedule")
                .select("*")
                .eq("language", lang)
                .gte("recommended_age_weeks", age_weeks)
                .order("recommended_age_weeks")
                .execute()
            )
            rows = data.data
            
            # Fallback to English if no rows found in requested language
            if not rows and lang != 'en':
                 data = (
                    supabase.table("vaccine_schedule")
                    .select("*")
                    .eq("language", "en")
                    .gte("recommended_age_weeks", age_weeks)
                    .order("recommended_age_weeks")
                    .execute()
                )
                 rows = data.data
                 
        except Exception as e:
            print(f"Action Vaccine DB Error: {e}")
            dispatcher.utter_message(text=msg["db_error"])
            return []

        if not rows:
            dispatcher.utter_message(text=msg["no_upcoming"])
            return []

        # 9. Build Response
        reply = ""
        # Limit to next 3 vaccines to avoid cluttering chat
        for row in rows[:5]: 
            due_weeks = row["recommended_age_weeks"]
            due_date = dob_dt + timedelta(weeks=due_weeks)

            reply += (
                f"💉 *{row['vaccine_name']}* ({row['dose_name']})\n"
                f"📅 {row['age_group']}\n"
                f"📌 {due_date.strftime('%d %b %Y')}\n"
                f"ℹ️ {row['description']}\n\n"
            )

        dispatcher.utter_message(text=reply)
        return []