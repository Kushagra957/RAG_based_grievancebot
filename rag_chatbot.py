import google.generativeai as genai
import re
from typing import Dict, List, Optional, Tuple
from dbmanager import DatabaseManager
import os

class GrievanceChatbot:
    def __init__(self, api_key: str, db_path: str = "grievance_system.db"):
        # Configure Gemini API
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-pro')
        
        # Initialize database
        self.db = DatabaseManager(db_path)
        
        # Define conversation states
        self.STATES = {
            'INITIAL': 'initial',
            'COLLECTING_NAME': 'collecting_name',
            'COLLECTING_MOBILE': 'collecting_mobile',
            'COLLECTING_COMPLAINT': 'collecting_complaint',
            'COMPLETED': 'completed'
        }
        
        # System prompt for the chatbot
        self.system_prompt = """
You are a helpful customer service chatbot for a grievance management system. Your role is to:

1. Help users register complaints by collecting their name, mobile number, and complaint details
2. Help users check the status of their existing complaints
3. Provide helpful information about the grievance process
4. Be polite, professional, and empathetic

Key behaviors:
- When someone wants to register a complaint, ask for name, mobile, and complaint details step by step
- When someone asks about complaint status, try to identify them or ask for their complaint ID
- Use the provided knowledge base to answer common questions
- Keep responses concise and helpful
- Show empathy for user issues

Current conversation context will be provided to you.
"""
    
    def analyze_intent(self, message: str) -> str:
        """Analyze user message to determine intent"""
        message_lower = message.lower()
        
        # Intent keywords
        complaint_keywords = ['complaint', 'issue', 'problem', 'register', 'file', 'submit', 'grievance']
        status_keywords = ['status', 'check', 'update', 'progress', 'resolved']
        
        if any(keyword in message_lower for keyword in complaint_keywords):
            return 'register_complaint'
        elif any(keyword in message_lower for keyword in status_keywords):
            return 'check_status'
        else:
            return 'general'
    
    def extract_info_from_message(self, message: str, info_type: str) -> Optional[str]:
        """Extract specific information from user message"""
        if info_type == 'mobile':
            # Extract mobile number (Indian format)
            mobile_pattern = r'(\+91|91)?[\s-]?[6-9]\d{9}'
            match = re.search(mobile_pattern, message)
            if match:
                mobile = re.sub(r'[^\d]', '', match.group())
                if len(mobile) == 10:
                    return mobile
                elif len(mobile) == 12 and mobile.startswith('91'):
                    return mobile[2:]
        
        elif info_type == 'name':
            # Simple name extraction (assuming name is provided clearly)
            # This could be enhanced with NER
            message = message.strip()
            if len(message.split()) <= 4 and message.replace(' ', '').isalpha():
                return message.title()
        
        return None
    
    def get_rag_response(self, query: str) -> str:
        """Get response using RAG - search knowledge base and generate response"""
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
            return "I apologize, but I'm having trouble processing your request right now. Please try again."
    
    def process_message(self, session_id: str, message: str) -> Tuple[str, bool]:
        """
        Process user message and return response
        Returns: (response_text, is_complaint_registered)
        """
        # Get or create session
        session = self.db.get_chat_session(session_id)
        if not session:
            session = {'user_data': {}, 'current_step': self.STATES['INITIAL']}
        
        user_data = session['user_data']
        current_step = session['current_step']
        
        # Analyze intent if in initial state
        if current_step == self.STATES['INITIAL']:
            intent = self.analyze_intent(message)
            
            if intent == 'register_complaint':
                current_step = self.STATES['COLLECTING_NAME']
                response = "I'll help you register your complaint. First, could you please provide your full name?"
                
            elif intent == 'check_status':
                # Try to find existing complaint
                mobile = self.extract_info_from_message(message, 'mobile')
                if mobile:
                    status_info = self.db.get_grievance_status(mobile=mobile)
                    if status_info:
                        response = f"Your complaint {status_info['complaint_id']} is currently: {status_info['status']}"
                    else:
                        response = "I couldn't find any complaints associated with that mobile number. Could you provide your complaint ID?"
                else:
                    response = "To check your complaint status, please provide your complaint ID or the mobile number used during registration."
                
            else:
                # Use RAG for general queries
                response = self.get_rag_response(message)
        
        # Handle complaint registration flow
        elif current_step == self.STATES['COLLECTING_NAME']:
            name = self.extract_info_from_message(message, 'name')
            if name:
                user_data['name'] = name
                current_step = self.STATES['COLLECTING_MOBILE']
                response = f"Thank you, {name}. Now, please provide your mobile number."
            else:
                response = "Please provide a valid name (letters only, up to 4 words)."
        
        elif current_step == self.STATES['COLLECTING_MOBILE']:
            mobile = self.extract_info_from_message(message, 'mobile')
            if mobile:
                user_data['mobile'] = mobile
                current_step = self.STATES['COLLECTING_COMPLAINT']
                response = "Great! Now, please describe your complaint or issue in detail."
            else:
                response = "Please provide a valid 10-digit mobile number."
        
        elif current_step == self.STATES['COLLECTING_COMPLAINT']:
            if len(message.strip()) > 10:  # Ensure meaningful complaint
                user_data['complaint_details'] = message
                
                # Register the complaint
                complaint_id = self.db.register_grievance(
                    user_data['name'],
                    user_data['mobile'],
                    user_data['complaint_details']
                )
                
                current_step = self.STATES['COMPLETED']
                response = f"Your complaint has been registered successfully!\n\nComplaint ID: {complaint_id}\n\nYou can use this ID to check the status of your complaint. We'll work on resolving your issue as soon as possible."
                
                # Update session
                self.db.update_chat_session(session_id, {}, self.STATES['INITIAL'])
                return response, True
            else:
                response = "Please provide a detailed description of your complaint (at least 10 characters)."
        
        else:
            # Reset to initial state
            current_step = self.STATES['INITIAL']
            response = self.get_rag_response(message)
        
        # Update session
        self.db.update_chat_session(session_id, user_data, current_step)
        
        return response, False
    
    def get_complaint_status_by_id(self, complaint_id: str) -> Optional[Dict]:
        """Get complaint status by complaint ID"""
        return self.db.get_grievance_status(complaint_id=complaint_id)

# Example usage and testing
if __name__ == "__main__":
    # Initialize chatbot (you'll need to provide your Gemini API key)
    # API_KEY = "your-gemini-api-key-here"
    API_KEY = os.getenv('GEMINI_API_KEY')
    chatbot = GrievanceChatbot(API_KEY)
    
    # Test conversation
    session_id = "test_session_001"
    
    test_messages = [
        "I have issues with my laptop. Register a complaint for me.",
        "John Doe",
        "9876543210",
        "My laptop screen is flickering and sometimes goes black. It started 3 days ago."
    ]
    
    print("Testing complaint registration flow:")
    for msg in test_messages:
        print(f"User: {msg}")
        response, registered = chatbot.process_message(session_id, msg)
        print(f"Bot: {response}")
        print("-" * 50)