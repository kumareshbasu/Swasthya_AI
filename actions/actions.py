import google.generativeai as genai
from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
import logging 

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