import streamlit as st
import requests
import json
import uuid
from datetime import datetime
import time

# Configure Streamlit page
st.set_page_config(
    page_title="Grievance Management Chatbot",
    page_icon="🎧",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# API Configuration
API_BASE_URL = "http://localhost:5000"

# Custom CSS for better styling
st.markdown("""
<style>
    .main {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    }
    
    .chat-container {
        background: white;
        border-radius: 15px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    
    .user-message {
        background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
        color: white;
        padding: 12px 16px;
        border-radius: 18px;
        margin: 8px 0;
        margin-left: 20%;
        border-top-right-radius: 4px;
    }
    
    .bot-message {
        background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
        color: #1565c0;
        padding: 12px 16px;
        border-radius: 18px;
        margin: 8px 0;
        margin-right: 20%;
        border-top-left-radius: 4px;
    }
    
    .complaint-id {
        background: #fff3cd;
        border: 2px solid #ffeaa7;
        border-radius: 8px;
        padding: 10px;
        margin: 10px 0;
        font-family: monospace;
        font-weight: bold;
        text-align: center;
    }
    
    .timestamp {
        font-size: 0.8em;
        color: #666;
        text-align: right;
        margin-top: 4px;
    }
    
    .sidebar-info {
        background: #f8f9fa;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 20px;
    }
    
    .status-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 15px;
        border-radius: 10px;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'messages' not in st.session_state:
    st.session_state.messages = []
    st.session_state.session_id = str(uuid.uuid4())
    # Add welcome message
    welcome_msg = {
        'content': """Hello! I'm your grievance management assistant. I can help you:

• Register a new complaint
• Check the status of existing complaints  
• Answer questions about the grievance process

How can I assist you today?""",
        'is_user': False,
        'timestamp': datetime.now()
    }
    st.session_state.messages.append(welcome_msg)

if 'api_status' not in st.session_state:
    st.session_state.api_status = None

def check_api_status():
    """Check if the Flask API is running"""
    try:
        response = requests.get(f"{API_BASE_URL}/api/health", timeout=5)
        return response.status_code == 200
    except:
        return False

def send_message_to_api(message, session_id):
    """Send message to Flask API and get response"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/chat",
            json={
                'message': message,
                'session_id': session_id
            },
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {'error': f'API Error: {response.status_code}'}
    except requests.exceptions.ConnectionError:
        return {'error': 'Cannot connect to API. Please ensure the Flask server is running on localhost:5000'}
    except requests.exceptions.Timeout:
        return {'error': 'Request timeout. Please try again.'}
    except Exception as e:
        return {'error': f'Error: {str(e)}'}

def get_complaint_status(complaint_id):
    """Get complaint status by ID"""
    try:
        response = requests.get(f"{API_BASE_URL}/api/complaint/status/{complaint_id}")
        if response.status_code == 200:
            return response.json()
        else:
            return {'error': f'API Error: {response.status_code}'}
    except Exception as e:
        return {'error': f'Error: {str(e)}'}

def format_message_content(content):
    """Format message content with special styling for complaint IDs"""
    if 'Complaint ID:' in content:
        lines = content.split('\n')
        formatted_lines = []
        for line in lines:
            if 'Complaint ID:' in line:
                complaint_id = line.split('Complaint ID:')[1].strip()
                formatted_lines.append(f'<div class="complaint-id">🎫 Complaint ID: {complaint_id}</div>')
            else:
                formatted_lines.append(line)
        return '<br>'.join(formatted_lines)
    return content.replace('\n', '<br>')

# Main UI
st.title("🎧 Grievance Management System")
st.markdown("---")

# Sidebar for API status and additional features
with st.sidebar:
    st.markdown("### 🔧 System Status")
    
    # Check API status
    api_online = check_api_status()
    if api_online:
        st.success("✅ API Server Online")
        st.session_state.api_status = True
    else:
        st.error("❌ API Server Offline")
        st.session_state.api_status = False
        st.markdown("""
        <div class="sidebar-info">
        <strong>⚠️ Flask API Not Running</strong><br>
        Please start the Flask server:<br>
        <code>python flask_api.py</code>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Quick status check
    st.markdown("### 🔍 Quick Status Check")
    complaint_id_input = st.text_input("Enter Complaint ID:", placeholder="GRV123456")
    if st.button("Check Status") and complaint_id_input:
        if api_online:
            status_result = get_complaint_status(complaint_id_input)
            if 'error' not in status_result:
                info = status_result['complaint_info']
                st.markdown(f"""
                <div class="status-card">
                <strong>📋 {info['complaint_id']}</strong><br>
                👤 {info['name']}<br>
                📊 Status: {info['status']}<br>
                📅 Created: {info['created_at'][:10]}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.error(status_result['error'])
        else:
            st.error("API server is not running")
    
    st.markdown("---")
    
    # Session info
    st.markdown("### 📱 Session Info")
    st.text(f"Session ID: {st.session_state.session_id[:8]}...")
    st.text(f"Messages: {len(st.session_state.messages)}")
    
    if st.button("🔄 Clear Chat"):
        st.session_state.messages = []
        st.session_state.session_id = str(uuid.uuid4())
        st.rerun()

# Main chat area
col1, col2, col3 = st.columns([1, 6, 1])

with col2:
    st.markdown('<div class="chat-container">', unsafe_allow_html=True)
    
    # Display chat messages
    chat_container = st.container()
    with chat_container:
        for i, message in enumerate(st.session_state.messages):
            timestamp = message['timestamp'].strftime("%H:%M")
            
            if message['is_user']:
                st.markdown(f"""
                <div class="user-message">
                    {format_message_content(message['content'])}
                    <div class="timestamp">{timestamp}</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="bot-message">
                    {format_message_content(message['content'])}
                    <div class="timestamp">{timestamp}</div>
                </div>
                """, unsafe_allow_html=True)
    
    st.markdown('</div>', unsafe_allow_html=True)

    # Chat input
    st.markdown("---")

    # Create input form without columns
    with st.form(key='chat_form', clear_on_submit=True):
        # Use a single input with the button integrated
        user_input = st.text_input(
            "Type your message:",
            placeholder="E.g., I have issues with my laptop. Register a complaint for me.",
            # label_visibility="collapsed"
        )
        
        # Center the button or use full width
        # send_button = st.form_submit_button("Send 📤", use_container_width=True)
        send_button = st.form_submit_button("Send 📤")
    
    
    
    
    
    # Process message when form is submitted
    if send_button and user_input:
        if not st.session_state.api_status:
            st.error("⚠️ Cannot send message. Flask API server is not running.")
        else:
            # Add user message to chat
            user_msg = {
                'content': user_input,
                'is_user': True,
                'timestamp': datetime.now()
            }
            st.session_state.messages.append(user_msg)
            
            # Show typing indicator
            with st.spinner('🤖 Bot is thinking...'):
                # Send to API
                response = send_message_to_api(user_input, st.session_state.session_id)
            
            # Add bot response
            if 'error' in response:
                bot_msg = {
                    'content': f"❌ {response['error']}",
                    'is_user': False,
                    'timestamp': datetime.now()
                }
            else:
                bot_msg = {
                    'content': response['response'],
                    'is_user': False,
                    'timestamp': datetime.now()
                }
                
                # Update session ID if provided
                if 'session_id' in response:
                    st.session_state.session_id = response['session_id']
            
            st.session_state.messages.append(bot_msg)
            
            # Rerun to update the display
            # st.rerun()
            st.experimental_rerun()


# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #666; padding: 20px;">
    <p>🔧 Powered by Flask API + Streamlit | 🤖 AI-Powered Grievance Management</p>
    <p><em>Make sure your Flask API server is running on localhost:5000</em></p>
</div>
""", unsafe_allow_html=True)

# Auto-refresh API status every 30 seconds
if st.session_state.api_status is False:
    time.sleep(5)  # Wait 5 seconds before checking again
    # st.rerun()
    st.experimental_rerun()
