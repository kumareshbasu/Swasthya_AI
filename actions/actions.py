# --- actions.py ---
# This file contains Custom Actions for the Rasa chatbot.
# Unlike standard Rasa responses (which are static text), Custom Actions allow
# us to run Python code, call external APIs (like Google Gemini), 
# and perform complex logic before sending a message back to the user.

# --- IMPORTS ---
# google.generativeai: The official Python library to interact with Google's Gemini models.
import google.generativeai as genai

# Typing imports to ensure code clarity and IDE support.
from typing import Any, Text, Dict, List

# Rasa SDK components required to build custom actions.
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet

# Logging allows us to see errors and debug info in the terminal (rasa run actions).
import logging 

# Requests library is used to make HTTP calls (e.g., downloading images from WhatsApp).
import requests

# PIL (Python Imaging Library) is used to process image data before sending it to Gemini.
from PIL import Image

# io allows us to handle byte streams (images in memory) without saving files to disk.
import io

# --- CONFIGURATION & SETUP ---

# Get a logger instance for this file. This is standard practice for debugging.
logger = logging.getLogger(__name__)

# 1. Configure the Gemini API Key.
# This key authenticates our requests to Google servers.
# SECURITY NOTE: In production, store this in an environment variable (os.environ).
GEMINI_API_KEY = "AIzaSyD3V-KfgabsetBfnT1gEjXOBUsahW5DLM8" 
genai.configure(api_key=GEMINI_API_KEY) 

# 2. Initialize the Gemini Model Globally.
# We do this outside the classes so the model is loaded only once when the server starts,
# rather than reloading it every time a user sends a message. This improves speed.
global_gemini_model_name = "gemini-2.5-pro" # NOTE: Ensure this model version exists in your Google Cloud project.

try:
    # Attempt to create the model instance.
    global_gemini_model_instance = genai.GenerativeModel(global_gemini_model_name)
    logger.info(f"Globally initialized Gemini model: {global_gemini_model_name}")
except Exception as e:
    # If initialization fails (e.g., bad internet, wrong API key), log the error
    # and set the instance to None. We will handle the fallback inside the Action classes.
    logger.error(f"Failed to initialize Gemini model globally: {e}. Will try initializing in run() method.", exc_info=True)
    global_gemini_model_instance = None


# --- ACTION 1: TEXT QUERY HANDLING ---
class ActionAskGemini(Action):
    """
    This action handles text-based health queries.
    It extracts the disease/symptom from the user's message,
    constructs a prompt based on the user's intent (symptoms vs prevention),
    and asks Gemini for an answer in the user's preferred language.
    """

    def name(self) -> Text:
        # This name must match the 'action' listed in your domain.yml and rules.yml.
        return "action_ask_gemini"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        # 1. Extract Intent and Entities
        # We look at what Rasa NLU understood from the user's text.
        intent = tracker.latest_message['intent'].get('name')
        entities = tracker.latest_message.get('entities', [])
        
        # We look for an entity named 'disease' (e.g., "Dengue", "Fever").
        disease = None
        for entity in entities:
            if entity.get('entity') == 'disease':
                disease = entity.get('value')
                break 

        # 2. Determine User's Language
        # We check if the 'lang' slot is already set.
        user_lang = tracker.get_slot('lang') 
        
        # If the slot is empty, we try to get it from the metadata sent by app.py.
        if not user_lang: 
            user_lang = tracker.latest_message.get('metadata', {}).get('lang', 'en')
            # If metadata is also missing, default to English ('en').
            if not user_lang: 
                user_lang = 'en'
        
        # Log the extracted info for debugging purposes.
        logger.info(f"DEBUG ACTIONS: Intent: {intent}, Disease Entity: {disease}, User Language: {user_lang}")

        # 3. Validation
        # If we couldn't find a disease name, we can't ask Gemini specific questions.
        if not disease:
            logger.warning("No disease entity extracted for Gemini query. Asking for clarification.")
            # Ask the user to be more specific.
            dispatcher.utter_message(text=f"I can help with that. Which disease or symptom are you interested in? (Lang: {user_lang})")
            return []
        
        # 4. Prompt Engineering
        # We dynamically build the prompt based on what the user wants (Intent).
        prompt = ""
        
        if intent == "ask_symptoms":
            # If user asked "What are signs of Dengue?", use this specific prompt structure.
            base_prompt = f"As a public health expert, explain the common symptoms of '{disease}' in simple, easy-to-understand terms for a rural audience."
        elif intent == "ask_preventive_measures":
            # If user asked "How to avoid Malaria?", use this structure.
            base_prompt = f"As a public health expert, describe simple, actionable preventive measures for '{disease}' for a rural audience."
        else: 
            # Fallback for general queries like "Tell me about Typhoid".
            base_prompt = f"As a public health expert, provide a detailed overview of '{disease}' for a rural audience."

        # 5. Language Instruction
        # Map the language code (e.g., 'hi') to the full name ('Hindi') for the AI.
        lang_names = {
            'en': 'English',
            'hi': 'Hindi',
            'bn': 'Bengali',
            'or': 'Odia'
        }
        lang_name_for_gemini = lang_names.get(user_lang, 'English') # Default to English

        # Add the strict language instruction to the prompt.
        prompt = f"{base_prompt} Respond in details and ONLY in {lang_name_for_gemini}."

        logger.info(f"DEBUG ACTIONS: Gemini prompt prepared (lang:{user_lang}): '{prompt[:200]}...'")

        # 6. Call Gemini API
        try:
            # Try to use the globally loaded model to save time.
            model = global_gemini_model_instance
            if not model: 
                # If global init failed earlier, try to initialize it locally now.
                logger.warning("Falling back to local Gemini model initialization.")
                model = genai.GenerativeModel(global_gemini_model_name) 

            logger.info(f"DEBUG ACTIONS: Attempting to generate content from Gemini...")
            
            # Send the prompt to Google.
            response = model.generate_content(prompt)
            
            # Check if the response is valid and contains text.
            if response and hasattr(response, 'text') and response.text:
                final_text_to_dispatch = response.text 
                
                # Log the response for debugging.
                logger.info(f"DEBUG ACTIONS: RAW Gemini response: {final_text_to_dispatch[:200]}...") 
                
                # Send the AI's answer back to the user on WhatsApp.
                dispatcher.utter_message(text=final_text_to_dispatch) 
                logger.info("DEBUG ACTIONS: Dispatched Gemini response successfully.")
            else:
                # Handling cases where the AI returns nothing (e.g., safety blocks).
                logger.warning(f"Gemini API returned an empty text field.")
                dispatcher.utter_message(response="utter_default_fallback") 
        except Exception as e: 
            # Catch connection errors or API crashes.
            logger.error(f"General Error during Gemini API call: {e}", exc_info=True) 
            dispatcher.utter_message(response="utter_default_fallback") 

        return []


# --- ACTION 2: LANGUAGE SLOT SETTING ---
class ActionSetLanguageSlot(Action):
    """
    This action simply reads the language detected by app.py (sent via metadata)
    and saves it into a Rasa 'slot' memory so other actions can access it later.
    """
    def name(self) -> Text:
        return "action_set_language_slot"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        # Extract 'lang' from the message metadata.
        lang = tracker.latest_message.get('metadata', {}).get('lang', 'en')
        logger.info(f"DEBUG ACTIONS: Setting 'lang' slot to: '{lang}' from metadata.")
        
        # Return a SlotSet event to update Rasa's memory.
        return [SlotSet("lang", lang)]
    

# --- ACTION 3: IMAGE ANALYSIS HANDLING ---
class ActionAnalyzeImageGemini(Action):
    """
    This action handles image messages.
    1. app.py sends the image URL to Rasa.
    2. This action downloads the image from that URL using the Meta API.
    3. It sends the image to Gemini Vision for analysis.
    4. It returns the description/advice to the user.
    """
    def name(self) -> Text:
        return "action_analyze_image_gemini"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        # 1. Retrieve Data
        # 'image_url' is extracted from the custom payload sent by app.py.
        image_url = tracker.get_slot('image_url')
        user_lang = tracker.latest_message.get('metadata', {}).get('lang', 'en')
        
        # --- CREDENTIALS ---
        # This token allows us to download media from WhatsApp servers.
        # IMPORTANT: Keep this token updated. If it expires, image download will fail (401 Error).
        META_ACCESS_TOKEN = "EAAJz0nEJSNgBQBZAtoR33JIAZBuZB7UmoMo4ojqlsZB7ZCgYxJQZBluxKrH8CxDPFv8Qfiq9hSuZBrwuz3TCndQlhw5196a1sxbX8mmxZBzdedho9N5oZAYwUDIVeNfoGguo6QyE0ag765AXIaIa83GxrMcvZAkMjM1mizJrCYlVrzbsMQBl8AjsQw3bPGuZBhET9glywZDZD"

        # Basic validation.
        if not image_url:
            dispatcher.utter_message(text="I received the image request, but the URL is missing.")
            return []

        # 2. Download the Image
        # We must provide the Authorization header to get the file from Meta.
        headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}"}
        try:
            logger.info(f"DEBUG ACTIONS: Downloading image from {image_url}")
            # Make a GET request to the URL.
            response = requests.get(image_url, headers=headers)
            
            # Check if the download was successful (Status 200). 
            # If it's 401 or 403, it usually means the Token is wrong.
            response.raise_for_status()
            
            # Get the raw bytes of the image.
            image_bytes = response.content
        except Exception as e:
            logger.error(f"Failed to download image in actions.py: {e}")
            dispatcher.utter_message(text="I'm having trouble downloading that image from WhatsApp.")
            return []

        # 3. Prepare Gemini Analysis
        try:
            # Initialize the Vision model. If global init failed, this will try locally.
            model = genai.GenerativeModel('gemini-2.5-pro')
            
            # Convert raw bytes into a PIL Image object that Gemini can understand.
            img = Image.open(io.BytesIO(image_bytes))

            # 4. Construct Vision Prompt
            # Tailor the system instruction based on the user's language.
            if user_lang == 'hi':
                system_prompt = "आप एक सहायक चिकित्सा सहायक हैं। इस छवि का विश्लेषण करें और सुझाव दें। हमेशा सलाह दें कि 'कृपया डॉक्टर से मिलें'।"
            elif user_lang == 'bn':
                system_prompt = "আপনি একজন সহায়ক চিকিৎসা সহকারী। এই চিত্রটি বিশ্লেষণ করুন এবং পরামর্শ দিন। সর্বদা পরামর্শ দিন 'দয়া করে একজন ডাক্তারের সাথে দেখা করুন'।"
            elif user_lang == 'or':
                system_prompt = "ଆପଣ ଜଣେ ସହାୟକ ଚିକିତ୍ସା ସହାୟକ ଅଟନ୍ତି। ଏହି ଚିତ୍ରକୁ ବିଶ୍ଳେଷଣ କରନ୍ତୁ ଏବଂ ପରାମର୍ଶ ଦିଅନ୍ତୁ। ସର୍ବଦା ପରାମର୍ଶ ଦିଅନ୍ତୁ 'ଦୟାକରି ଡାକ୍ତରଙ୍କୁ ଦେଖା କରନ୍ତୁ'।"
            else:
                system_prompt = "You are a helpful medical assistant. Analyze this image (wound/symptom) and suggest what it might be and home remedies. Add disclaimer: 'Consult a doctor'."

            # 5. Generate Analysis
            logger.info("DEBUG ACTIONS: Sending image to Gemini...")
            
            # Send both the prompt text AND the image object to the API.
            gemini_response = model.generate_content([system_prompt, img])
            
            # Return the result.
            if gemini_response and gemini_response.text:
                dispatcher.utter_message(text=gemini_response.text)
            else:
                dispatcher.utter_message(text="I couldn't interpret that image.")

        except Exception as e:
            # Catch errors specific to Gemini (e.g., 404 model not found, safety blocks).
            logger.error(f"Gemini Vision Error in actions: {e}")
            dispatcher.utter_message(text="Sorry, I encountered an error analyzing the image.")

        return []