import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, List

class DatabaseManager:
    def __init__(self, db_path: str = "grievance_system.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize the database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create grievances table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS grievances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    complaint_id TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    mobile TEXT NOT NULL,
                    complaint_details TEXT NOT NULL,
                    status TEXT DEFAULT 'Submitted',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create chat_sessions table to track user conversations
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE NOT NULL,
                    user_data TEXT,
                    current_step TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create knowledge_base table for RAG
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS knowledge_base (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    category TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            self.populate_knowledge_base()
    
    def populate_knowledge_base(self):
        """Populate the knowledge base with common grievance-related Q&A"""
        knowledge_data = [
            ("How to register a complaint?", "You can register a complaint by providing your name, mobile number, and complaint details. I'll help you through the process.", "general"),
            ("How to check complaint status?", "You can check your complaint status by asking 'What's the status of my complaint?' I'll identify you and provide the current status.", "status"),
            ("What information is needed for complaint?", "For registering a complaint, I need your full name, mobile number, and detailed description of your issue.", "registration"),
            ("How long does it take to resolve?", "Resolution time varies based on the complexity of the issue. You'll receive updates on the status.", "general"),
            ("Can I update my complaint?", "Once submitted, complaints are processed by our team. For updates, please provide your complaint ID.", "general")
        ]
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Check if knowledge base is already populated
            cursor.execute("SELECT COUNT(*) FROM knowledge_base")
            count = cursor.fetchone()[0]
            
            if count == 0:
                cursor.executemany(
                    "INSERT INTO knowledge_base (question, answer, category) VALUES (?, ?, ?)",
                    knowledge_data
                )
                conn.commit()
    
    def register_grievance(self, name: str, mobile: str, complaint_details: str) -> str:
        """Register a new grievance and return complaint ID"""
        import random
        import string
        
        # Generate unique complaint ID
        complaint_id = 'GRV' + ''.join(random.choices(string.digits, k=6))
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO grievances (complaint_id, name, mobile, complaint_details)
                VALUES (?, ?, ?, ?)
            ''', (complaint_id, name, mobile, complaint_details))
            conn.commit()
        
        return complaint_id
    
    def get_grievance_status(self, complaint_id: str = None, mobile: str = None) -> Optional[Dict]:
        """Get grievance status by complaint ID or mobile number"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if complaint_id:
                cursor.execute('''
                    SELECT complaint_id, name, status, created_at, updated_at
                    FROM grievances WHERE complaint_id = ?
                ''', (complaint_id,))
            elif mobile:
                cursor.execute('''
                    SELECT complaint_id, name, status, created_at, updated_at
                    FROM grievances WHERE mobile = ?
                    ORDER BY created_at DESC LIMIT 1
                ''', (mobile,))
            else:
                return None
            
            result = cursor.fetchone()
            if result:
                return {
                    'complaint_id': result[0],
                    'name': result[1],
                    'status': result[2],
                    'created_at': result[3],
                    'updated_at': result[4]
                }
        
        return None
    
    def update_chat_session(self, session_id: str, user_data: Dict, current_step: str):
        """Update or create chat session"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO chat_sessions (session_id, user_data, current_step, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ''', (session_id, json.dumps(user_data), current_step))
            conn.commit()
    
    def get_chat_session(self, session_id: str) -> Optional[Dict]:
        """Get chat session data"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_data, current_step FROM chat_sessions WHERE session_id = ?
            ''', (session_id,))
            result = cursor.fetchone()
            
            if result:
                return {
                    'user_data': json.loads(result[0]) if result[0] else {},
                    'current_step': result[1]
                }
        return None
    
    def search_knowledge_base(self, query: str) -> List[Dict]:
        """Search knowledge base for relevant answers"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT question, answer, category FROM knowledge_base
                WHERE question LIKE ? OR answer LIKE ?
                ORDER BY CASE 
                    WHEN question LIKE ? THEN 1
                    WHEN answer LIKE ? THEN 2
                    ELSE 3
                END
                LIMIT 3
            ''', (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))
            
            results = cursor.fetchall()
            return [{'question': r[0], 'answer': r[1], 'category': r[2]} for r in results]

# Initialize the database
if __name__ == "__main__":
    db = DatabaseManager()
    print("Database initialized successfully!")