import google.generativeai as genai
from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
import logging 
import requests
from PIL import Image
import io

logger = logging.getLogger(__name__)

GEMINI_API_KEY = "AIzaSyD3V-KfgabsetBfnT1gEjXOBUsahW5DLM8"
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

# The ActionSetLanguageSlot from previous response remains unchanged and is crucial.
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
        META_ACCESS_TOKEN = "EAAJz0nEJSNgBQBZAtoR33JIAZBuZB7UmoMo4ojqlsZB7ZCgYxJQZBluxKrH8CxDPFv8Qfiq9hSuZBrwuz3TCndQlhw5196a1sxbX8mmxZBzdedho9N5oZAYwUDIVeNfoGguo6QyE0ag765AXIaIa83GxrMcvZAkMjM1mizJrCYlVrzbsMQBl8AjsQw3bPGuZBhET9glywZDZD"

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

        except Exception as e:
            logger.error(f"Gemini Vision Error in actions: {e}")
            dispatcher.utter_message(text="Sorry, I encountered an error analyzing the image.")

        return []