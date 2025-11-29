#actions.py
import google.generativeai as genai
from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet 
import logging 
import requests
from PIL import Image
import io
import os
from dotenv import load_dotenv

load_dotenv()

# --- Gemini Initialization ---
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

global_gemini_model_name = "gemini-2.5-pro" # Ensure this is 'gemini-2.5-pro'
try:
    global_gemini_model_instance = genai.GenerativeModel(global_gemini_model_name)
    logger.info(f"Globally initialized Gemini model: {global_gemini_model_name}")
except Exception as e:
    logger.error(f"Failed to initialize Gemini model globally: {e}. Will try initializing in run() method.", exc_info=True)
    global_gemini_model_instance = None


# --- ActionAskGemini (MODIFIED) ---
class ActionAskGemini(Action):
    def name(self) -> Text:
        return "action_ask_gemini"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        # Rasa NLU will now identify intent and entities directly
        intent = tracker.latest_message['intent'].get('name')
        entities = tracker.latest_message.get('entities', [])
        disease = None
        for entity in entities:
            if entity.get('entity') == 'disease':
                disease = entity.get('value')
                break 

        # Get the language from tracker metadata or slot
        user_lang = tracker.get_slot('lang') # This slot should be set by ActionSetLanguageSlot
        if not user_lang: 
            user_lang = tracker.latest_message.get('metadata', {}).get('lang', 'en')
            if not user_lang: 
                user_lang = 'en'
        
        logger.info(f"DEBUG ACTIONS: Intent: {intent}, Disease Entity: {disease}, User Language: {user_lang}")

        if not disease:
            logger.warning("No disease entity extracted for Gemini query. Asking for clarification.")
            # This response should also be localized
            dispatcher.utter_message(text=f"I can help with that. Which disease or symptom are you interested in? (Lang: {user_lang})")
            return []
        
        # --- Multilingual Prompts for Gemini (Simplified, as per your idea) ---
        # The key is to instruct Gemini to respond in the detected 'user_lang'
        prompt = ""
        
        # Determine the base prompt structure
        if intent == "ask_symptoms":
            base_prompt = f"As a public health expert, explain the common symptoms of '{disease}' in simple, easy-to-understand terms for a rural audience."
        elif intent == "ask_preventive_measures":
            base_prompt = f"As a public health expert, describe simple, actionable preventive measures for '{disease}' for a rural audience."
        else: # Covers general_health_query and any other intent that leads here
            base_prompt = f"As a public health expert, provide a detailed overview of '{disease}' for a rural audience."

        # Append the language instruction to the base prompt
        # We'll map the 'lang' code to a more natural language name for Gemini
        lang_names = {
            'en': 'English',
            'hi': 'Hindi',
            'bn': 'Bengali',
            'or': 'Odia'
        }
        lang_name_for_gemini = lang_names.get(user_lang, 'English') # Default to English if unknown

        prompt = f"{base_prompt} Respond in details and ONLY in {lang_name_for_gemini}."

        logger.info(f"DEBUG ACTIONS: Gemini prompt prepared (lang:{user_lang}): '{prompt[:200]}...'")

        try:
            model = global_gemini_model_instance
            if not model: 
                logger.warning("Falling back to local Gemini model initialization.")
                model = genai.GenerativeModel(global_gemini_model_name) 

            logger.info(f"DEBUG ACTIONS: Attempting to generate content from Gemini model '{global_gemini_model_name}' for language '{user_lang}'...")
            response = model.generate_content(prompt)
            
            if response and hasattr(response, 'text') and response.text:
                final_text_to_dispatch = response.text 
                
                logger.info(f"DEBUG ACTIONS: RAW Gemini response (lang:{user_lang}, first 200 chars - for dispatch): {final_text_to_dispatch[:200]}...") 
                dispatcher.utter_message(text=final_text_to_dispatch) 
                logger.info("DEBUG ACTIONS: Dispatched Gemini response successfully.")
            else:
                logger.warning(f"Gemini API returned an empty or unreadable 'text' field for {user_lang}. Full response object: {response}")
                dispatcher.utter_message(response="utter_default_fallback") # Fallback utterance
        except Exception as e: 
            logger.error(f"General Error during Gemini API call or response processing for {user_lang}: {e}", exc_info=True) 
            dispatcher.utter_message(response="utter_default_fallback") # Fallback utterance

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
            model = genai.GenerativeModel('gemini-2.5-pro')
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
            model = global_gemini_model_instance or genai.GenerativeModel("gemini-2.5-pro")
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
            model = global_gemini_model_instance or genai.GenerativeModel("gemini-2.5-pro")
            response = model.generate_content(system_prompt)
            
            if response and response.text:
                dispatcher.utter_message(text=response.text)
            else:
                dispatcher.utter_message(text="I couldn't find details for this medicine.")

        except Exception as e:
            logger.error(f"Medicine Check Error: {e}")
            dispatcher.utter_message(text="Sorry, I encountered an error checking the medicine.")
        
        return []