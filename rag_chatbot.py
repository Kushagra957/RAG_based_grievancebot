import google.generativeai as genai
import re
from typing import Dict, List, Optional, Tuple
from dbmanager import DatabaseManager
import os

from dotenv import load_dotenv
load_dotenv()

class GrievanceChatbot:
    def __init__(self, api_key: str, db_path: str = "grievance_system.db"):
        # Configure Gemini API
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.0-flash')
        
        # Initialize database
        self.db = DatabaseManager(db_path)
        
        # Define conversation states
        self.STATES = {
            'INITIAL_CHOICE': 'initial_choice', # New state for initial routing
            'COLLECTING_NAME': 'collecting_name',
            'COLLECTING_MOBILE': 'collecting_mobile',
            'COLLECTING_COMPLAINT': 'collecting_complaint',
            'COLLECTING_COMPLAINT_ID_OR_MOBILE': 'collecting_complaint_id_or_mobile', # New state for status inquiry
            'COMPLETED': 'completed' # For complaint registration completion
        }
        
        # System prompt for the chatbot
        self.system_prompt = """
You are a helpful customer service chatbot for a grievance management system. Your role is to:

1. Guide users to either register a new complaint or check the status of an existing one.
2. For new complaints, collect name, mobile number, and detailed complaint information step-by-step.
3. For status inquiries, ask for either a complaint ID or the mobile number used for registration.
4. Provide helpful information about the grievance process based on your knowledge base.
5. Be polite, professional, and empathetic.

Key behaviors:
- At the beginning of any chat, ask the user if they want to register a new complaint or check an existing one.
- When registering a complaint, ask for name, then mobile, then complaint details, each in a separate turn.
- When checking status, ask for complaint ID or mobile number.
- Use the provided knowledge base to answer common questions.
- Keep responses concise and helpful.
- Show empathy for user issues.

Current conversation context will be provided to you.
"""
    
    def analyze_intent(self, message: str) -> str:
        """Analyze user message to determine intent using a Gemini model call."""
        prompt = f"""
You are an intent classification system for a grievance management chatbot.
Your task is to classify the user's message into one of the following categories:
- 'register_complaint': The user wants to file a new complaint or report an issue.
- 'check_status': The user wants to know the status of an existing complaint.
- 'general': The user's message is a general query, a greeting, or something not related to registering/checking a complaint.

Respond with only one of these exact words: 'register_complaint', 'check_status', 'general'.

Examples:
User: I have a problem with my internet.
Classification: register_complaint

User: What's the status of my ticket?
Classification: check_status

User: Hello, how are you?
Classification: general

User: My laptop is broken, please help.
Classification: register_complaint

User: Can I get an update on GRV123456?
Classification: check_status

User: Tell me about your services.
Classification: general

User: I want to file a new grievance.
Classification: register_complaint

User: My complaint is not resolved yet.
Classification: check_status

User: Thanks.
Classification: general

User message: {message}
Classification:
"""
        try:
            response = self.model.generate_content(prompt)
            # Clean the response to ensure it matches one of the expected states
            intent = response.text.strip().lower()
            if intent in ['register_complaint', 'check_status', 'general']:
                return intent
            else:
                # Fallback to general if classification is unexpected
                return 'general' 
        except Exception as e:
            print(f"Error classifying intent with Gemini: {e}")
            # Fallback to general if API call fails
            return 'general'
    
    def extract_info_from_message(self, message: str, info_type: str) -> Optional[str]:
        """Extract specific information from user message based on info_type"""
        if info_type == 'mobile':
            # Extract mobile number (Indian format, 10 digits)
            mobile_pattern = r'(\+91|91)?[\s-]?[6-9]\d{9}'
            match = re.search(mobile_pattern, message)
            if match:
                mobile = re.sub(r'[^\d]', '', match.group()) # Remove non-digits
                if len(mobile) == 10:
                    return mobile
                elif len(mobile) == 12 and mobile.startswith('91'): # Handle +91 or 91 prefix
                    return mobile[2:]
        
        elif info_type == 'name':
            # Simple name extraction: assumes name is primarily alphabetic, up to 4 words.
            # This can be improved with more sophisticated NLP/NER for production.
            message = message.strip()
            # Check if it looks like a name (mostly letters, reasonable length)
            if all(part.isalpha() for part in message.split()) and 1 <= len(message.split()) <= 4:
                return message.title() # Capitalize each word for common name format
        
        elif info_type == 'complaint_id':
            # Extract complaint ID (e.g., GRV123456)
            complaint_id_pattern = r'[Gg][Rr][Vv]\d{6}'
            match = re.search(complaint_id_pattern, message)
            if match:
                return match.group().upper()
        
        return None
    
    def get_rag_response(self, query: str) -> str:
        """Get response using RAG - search knowledge base and generate response with LLM"""
        # Search knowledge base
        kb_results = self.db.search_knowledge_base(query)
        
        # Prepare context for LLM
        context = ""
        if kb_results:
            context = "Relevant information from knowledge base:\n"
            for result in kb_results:
                context += f"Q: {result['question']}\nA: {result['answer']}\n\n"
        
        # Generate response with context
        prompt = f"""
{self.system_prompt}

Context from knowledge base:
{context}

User query: {query}

Provide a helpful response based on the context and your role as a grievance management chatbot.
"""
        
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"Error generating content: {e}")
            return f"I apologize, but I'm having trouble processing your request right now. Please try again later. (Error: {e})"
    
    def process_message(self, session_id: str, message: str) -> Tuple[str, bool]:
        """
        Process user message and return response based on conversation state.
        Returns: (response_text, is_complaint_registered)
        """
        # Get or create session
        session = self.db.get_chat_session(session_id)
        if not session:
            # If no session, start at initial choice
            session = {'user_data': {}, 'current_step': self.STATES['INITIAL_CHOICE']}
            # Add initial welcome message specific to this flow
            response = """Hello! I'm your grievance management assistant. How can I help you today?
Please type 'register new complaint' to get started, or 'check status' to inquire about an existing one."""
            self.db.update_chat_session(session_id, session['user_data'], session['current_step'])
            return response, False
        
        user_data = session['user_data']
        current_step = session['current_step']
        
        # Always log user message
        self.db.add_chat_message(session_id, message, True)

        response = ""
        is_complaint_registered = False

        if current_step == self.STATES['INITIAL_CHOICE']:
            # Use LLM for intent analysis
            intent = self.analyze_intent(message)
            
            if intent == 'register_complaint':
                current_step = self.STATES['COLLECTING_NAME']
                response = "I'll help you register your complaint. First, could you please provide your full name?"
            elif intent == 'check_status':
                current_step = self.STATES['COLLECTING_COMPLAINT_ID_OR_MOBILE']
                response = "To check your complaint status, please provide your complaint ID or the mobile number used during registration."
            else:
                # If intent is general or not clearly defined, try RAG or re-prompt
                response = self.get_rag_response(message)
                if "I'm sorry" in response or "try again" in response: # Check for LLM apology
                    response = "I can help you with two main things: registering a new complaint or checking the status of an existing one. Please tell me which one you'd like to do."
                    current_step = self.STATES['INITIAL_CHOICE'] # Stay in initial choice
                # else: intent is general, stay in initial choice and let RAG handle it
        
        elif current_step == self.STATES['COLLECTING_NAME']:
            name = self.extract_info_from_message(message, 'name')
            if name:
                user_data['name'] = name
                current_step = self.STATES['COLLECTING_MOBILE']
                response = f"Thank you, {name}. Now, please provide your 10-digit mobile number."
            else:
                response = "That doesn't look like a valid name. Please provide your full name (e.g., John Doe)."
        
        elif current_step == self.STATES['COLLECTING_MOBILE']:
            mobile = self.extract_info_from_message(message, 'mobile')
            if mobile:
                user_data['mobile'] = mobile
                current_step = self.STATES['COLLECTING_COMPLAINT']
                response = "Great! Now, please describe your complaint or issue in detail (e.g., 'My laptop screen is flickering, it started 3 days ago')."
            else:
                response = "Please provide a valid 10-digit mobile number."
        
        elif current_step == self.STATES['COLLECTING_COMPLAINT']:
            if len(message.strip()) >= 10:  # Ensure meaningful complaint details
                user_data['complaint_details'] = message
                
                try:
                    # Register the complaint
                    complaint_id = self.db.register_grievance(
                        user_data['name'],
                        user_data['mobile'],
                        user_data['complaint_details'],
                        session_id # Pass session ID to transfer chat history
                    )
                    
                    response = f"Your complaint has been registered successfully!\n\nComplaint ID: {complaint_id}\n\nYou can use this ID to check the status of your complaint. We'll work on resolving your issue as soon as possible."
                    current_step = self.STATES['INITIAL_CHOICE'] # Reset state after completion
                    is_complaint_registered = True
                    user_data = {} # Clear user data after registration
                except Exception as e:
                    response = f"I'm sorry, I encountered an error while trying to register your complaint: {e}. Please try again."
                    # Keep the current step, or reset to initial if error is critical
                    current_step = self.STATES['INITIAL_CHOICE'] # Go back to choice on error
                    user_data = {} # Clear user data on error
            else:
                response = "Please provide a more detailed description of your complaint (at least 10 characters)."
        
        elif current_step == self.STATES['COLLECTING_COMPLAINT_ID_OR_MOBILE']:
            complaint_id = self.extract_info_from_message(message, 'complaint_id')
            mobile = self.extract_info_from_message(message, 'mobile')

            status_info = None
            if complaint_id:
                status_info = self.db.get_grievance_status(complaint_id=complaint_id)
            elif mobile:
                status_info = self.db.get_grievance_status(mobile=mobile)

            if status_info:
                response = (f"Your complaint (ID: {status_info['complaint_id']}) is currently: {status_info['status']}. "
                            f"Registered by {status_info['name']} on {status_info['created_at'][:10]}.")
            else:
                response = "I couldn't find any complaints with the provided ID or mobile number. Please double-check and try again, or you can choose to 'register new complaint'."
            
            current_step = self.STATES['INITIAL_CHOICE'] # Always reset after status check
            user_data = {} # Clear user data for status check path

        # Log bot message
        self.db.add_chat_message(session_id, response, False)
        
        # Update session in DB
        self.db.update_chat_session(session_id, user_data, current_step)
        
        return response, is_complaint_registered

    def get_complaint_status_by_id(self, complaint_id: str) -> Optional[Dict]:
        """Get complaint status by complaint ID - exposed for external use"""
        return self.db.get_grievance_status(complaint_id=complaint_id)

# Example usage and testing
if __name__ == "__main__":
    # Initialize chatbot (you'll need to provide your Gemini API key)
    # Ensure GEMINI_API_KEY is set in your environment or .env file
    API_KEY = os.getenv('GEMINI_API_KEY')
    if not API_KEY:
        print("Error: GEMINI_API_KEY environment variable not set.")
        exit(1)

    chatbot = GrievanceChatbot(API_KEY)
    
    # Test conversation scenarios
    session_id_1 = "test_session_user_1"
    session_id_2 = "test_session_user_2"
    
    print("--- Test Scenario 1: Register a new complaint ---")
    messages_reg = [
        "Hi, I want to register a new complaint.",
        "Alice Smith",
        "9876543210",
        "My internet is not working since yesterday, and the lights on my router are red."
    ]
    
    for msg in messages_reg:
        print(f"User ({session_id_1}): {msg}")
        response, registered = chatbot.process_message(session_id_1, msg)
        print(f"Bot: {response}")
        print("-" * 50)
        if registered:
            print(f"Complaint successfully registered: {response.split('ID:')[1].splitlines()[0].strip()}")
            break # End registration flow

    print("\n--- Test Scenario 2: Check status ---")
    messages_status = [
        "Hello, check status please.",
        "My complaint ID is GRV123456", # Replace with a known complaint ID or test mobile number
        # "My mobile is 9876543210" # Alternative for status check
    ]

    for msg in messages_status:
        print(f"User ({session_id_2}): {msg}")
        response, registered = chatbot.process_message(session_id_2, msg)
        print(f"Bot: {response}")
        print("-" * 50)

    print("\n--- Test Scenario 3: General query ---")
    messages_general = [
        "What is your service?",
        "How do I update my complaint details?"
    ]
    
    for msg in messages_general:
        print(f"User ({session_id_1}): {msg}")
        response, registered = chatbot.process_message(session_id_1, msg)
        print(f"Bot: {response}")
        print("-" * 50)
