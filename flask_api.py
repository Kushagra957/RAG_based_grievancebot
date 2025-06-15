from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import uuid
from datetime import datetime
from rag_chatbot import GrievanceChatbot
from dbmanager import DatabaseManager

from dotenv import load_dotenv
load_dotenv()



app = Flask(__name__)
CORS(app)

# Initialize chatbot and database
API_KEY = os.getenv('GEMINI_API_KEY')
chatbot = GrievanceChatbot(API_KEY)
db = DatabaseManager()

# Store active sessions (in production, use Redis or similar)
active_sessions = {}

@app.route('/')
def index():
    """API root endpoint"""
    return jsonify({
        'message': 'Grievance Management API',
        'version': '1.0.0',
        'endpoints': {
            'chat': '/api/chat',
            'register_complaint': '/api/complaint/register',
            'get_status_by_id': '/api/complaint/status/<complaint_id>',
            'get_status_by_mobile': '/api/complaint/status',
            'health': '/api/health'
        }
    })

@app.route('/api/chat', methods=['POST'])
def chat():
    """Handle chat messages"""
    try:
        data = request.json
        message = data.get('message', '').strip()
        session_id = data.get('session_id')
        
        if not message:
            return jsonify({'error': 'Message is required'}), 400
        
        # Generate session ID if not provided
        if not session_id:
            session_id = str(uuid.uuid4())
        
        # Process message
        response, is_registered = chatbot.process_message(session_id, message)
        
        return jsonify({
            'response': response,
            'session_id': session_id,
            'is_complaint_registered': is_registered,
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/complaint/register', methods=['POST'])
def register_complaint():
    """Direct API endpoint for complaint registration"""
    try:
        data = request.json
        name = data.get('name', '').strip()
        mobile = data.get('mobile', '').strip()
        complaint_details = data.get('complaint_details', '').strip()
        
        # Validate input
        if not all([name, mobile, complaint_details]):
            return jsonify({'error': 'Name, mobile, and complaint details are required'}), 400
        
        if len(mobile) != 10 or not mobile.isdigit():
            return jsonify({'error': 'Mobile number must be 10 digits'}), 400
        
        # Register complaint
        complaint_id = db.register_grievance(name, mobile, complaint_details)
        
        return jsonify({
            'success': True,
            'complaint_id': complaint_id,
            'message': 'Complaint registered successfully',
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        return jsonify({'error': f'Failed to register complaint: {str(e)}'}), 500

@app.route('/api/complaint/status/<complaint_id>', methods=['GET'])
def get_complaint_status(complaint_id):
    """Get complaint status by ID"""
    try:
        status_info = db.get_grievance_status(complaint_id=complaint_id)
        
        if not status_info:
            return jsonify({'error': 'Complaint not found'}), 404
        
        return jsonify({
            'success': True,
            'complaint_info': status_info
        })
    
    except Exception as e:
        return jsonify({'error': f'Failed to retrieve status: {str(e)}'}), 500

@app.route('/api/complaint/status', methods=['POST'])
def get_complaint_status_by_mobile():
    """Get complaint status by mobile number"""
    try:
        data = request.json
        mobile = data.get('mobile', '').strip()
        
        if not mobile:
            return jsonify({'error': 'Mobile number is required'}), 400
        
        status_info = db.get_grievance_status(mobile=mobile)
        
        if not status_info:
            return jsonify({'error': 'No complaints found for this mobile number'}), 404
        
        return jsonify({
            'success': True,
            'complaint_info': status_info
        })
    
    except Exception as e:
        return jsonify({'error': f'Failed to retrieve status: {str(e)}'}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })

if __name__ == '__main__':
    print("Starting Grievance Management API Server...")
    print("Make sure to set your GEMINI_API_KEY environment variable")
    print("API will be available at http://localhost:5000")
    print("\nAvailable endpoints:")
    print("- POST /api/chat - Chat with the bot")
    print("- POST /api/complaint/register - Register complaint directly")
    print("- GET /api/complaint/status/<complaint_id> - Get status by ID")
    print("- POST /api/complaint/status - Get status by mobile")
    print("- GET /api/health - Health check")
    
    app.run(debug=True, host='0.0.0.0', port=5000)