import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, List
import threading
import time

class DatabaseManager:
    def __init__(self, db_path: str = "grievance_system.db"):
        self.db_path = db_path
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        try:
            self.init_database()
        except Exception as e:
            raise RuntimeError(f"Failed to initialize database: {e}")
    
    def _get_connection(self):
        """Get a database connection with proper configuration"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")  # Use WAL mode for better concurrency
        conn.execute("PRAGMA synchronous=NORMAL")  # Balance between safety and performance
        conn.execute("PRAGMA temp_store=MEMORY")  # Store temp data in memory
        conn.execute("PRAGMA cache_size=10000")  # Increase cache size
        return conn
    
    def init_database(self):
        """Initialize the database with required tables"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Create grievances table with integrated chat history
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS grievances (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            complaint_id TEXT UNIQUE NOT NULL,
                            name TEXT NOT NULL,
                            mobile TEXT NOT NULL,
                            complaint_details TEXT NOT NULL,
                            status TEXT DEFAULT 'Submitted',
                            chat_history TEXT DEFAULT '[]',
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
                    
                    # Create temporary chat sessions table for ongoing conversations
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS temp_chat_sessions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            session_id TEXT UNIQUE NOT NULL,
                            user_data TEXT,
                            current_step TEXT,
                            chat_history TEXT DEFAULT '[]',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
                    
                    conn.commit()
                    self.populate_knowledge_base()
        except sqlite3.Error as e:
            raise RuntimeError(f"Database initialization error: {e}")
    
    def populate_knowledge_base(self):
        """Populate the knowledge base with common grievance-related Q&A"""
        knowledge_data = [
            ("How to register a complaint?", "You can register a complaint by providing your name, mobile number, and complaint details. I'll help you through the process.", "general"),
            ("How to check complaint status?", "You can check your complaint status by asking 'What's the status of my complaint?' I'll identify you and provide the current status.", "status"),
            ("What information is needed for complaint?", "For registering a complaint, I need your full name, mobile number, and detailed description of your issue.", "registration"),
            ("How long does it take to resolve?", "Resolution time varies based on the complexity of the issue. You'll receive updates on the status.", "general"),
            ("Can I update my complaint?", "Once submitted, complaints are processed by our team. For updates, please provide your complaint ID.", "general")
        ]
        
        try:
            with self._lock:
                with self._get_connection() as conn:
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
        except sqlite3.Error as e:
            print(f"Warning: Failed to populate knowledge base: {e}")
    
    def add_chat_message(self, session_id: str, message: str, is_user: bool, complaint_id: str = None):
        """Add a chat message to the appropriate chat history"""
        try:
            if not session_id or not message:
                raise ValueError("Session ID and message are required")
            
            chat_entry = {
                'session_id': session_id,
                'chat_text': f"{'User' if is_user else 'Bot'}: {message}",
                'timestamp': datetime.now().isoformat(),
                'is_user': is_user
            }
            
            with self._lock:
                if complaint_id:
                    # Validate that this session can be associated with this complaint
                    if not self._can_session_be_added_to_complaint(session_id, complaint_id):
                        raise ValueError(f"Session ID {session_id} cannot be added to complaint {complaint_id} - already associated with another complaint")
                    
                    # Add to existing complaint's chat history
                    self._add_to_complaint_chat_history(complaint_id, chat_entry)
                else:
                    # Add to temporary session chat history
                    self._add_to_temp_session_chat_history(session_id, chat_entry)
        except Exception as e:
            raise RuntimeError(f"Failed to add chat message: {e}")
    
    def _add_to_complaint_chat_history(self, complaint_id: str, chat_entry: Dict):
        """Add chat entry to complaint's chat history"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Get current chat history
                cursor.execute('SELECT chat_history FROM grievances WHERE complaint_id = ?', (complaint_id,))
                result = cursor.fetchone()
                
                if result:
                    try:
                        chat_history = json.loads(result[0]) if result[0] else []
                    except json.JSONDecodeError:
                        chat_history = []
                    
                    chat_history.append(chat_entry)
                    
                    # Update chat history and timestamp
                    cursor.execute('''
                        UPDATE grievances 
                        SET chat_history = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE complaint_id = ?
                    ''', (json.dumps(chat_history), complaint_id))
                    conn.commit()
                else:
                    raise ValueError(f"Complaint {complaint_id} not found")
        except sqlite3.Error as e:
            raise RuntimeError(f"Database error adding to complaint chat: {e}")
    
    def _add_to_temp_session_chat_history(self, session_id: str, chat_entry: Dict):
        """Add chat entry to temporary session chat history"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Get current session chat history
                cursor.execute('SELECT chat_history FROM temp_chat_sessions WHERE session_id = ?', (session_id,))
                result = cursor.fetchone()
                
                if result:
                    try:
                        chat_history = json.loads(result[0]) if result[0] else []
                    except json.JSONDecodeError:
                        chat_history = []
                else:
                    chat_history = []
                
                chat_history.append(chat_entry)
                
                # Update or insert session chat history
                cursor.execute('''
                    INSERT OR REPLACE INTO temp_chat_sessions (session_id, chat_history, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (session_id, json.dumps(chat_history)))
                conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"Database error adding to temp session: {e}")
    
    def register_grievance(self, name: str, mobile: str, complaint_details: str, session_id: str = None) -> str:
        """Register a new grievance and transfer chat history from temp session"""
        try:
            if not all([name, mobile, complaint_details]):
                raise ValueError("Name, mobile, and complaint details are required")
            
            import random
            import string
            
            with self._lock:
                # Generate unique complaint ID
                complaint_id = 'GRV' + ''.join(random.choices(string.digits, k=6))
                
                # Get chat history from temp session if session_id provided
                chat_history = []
                if session_id:
                    # Check if this session_id is already associated with another complaint
                    if self._is_session_already_used(session_id):
                        raise ValueError(f"Session ID {session_id} is already associated with another complaint")
                    
                    temp_session = self.get_temp_chat_session(session_id)
                    if temp_session and temp_session.get('chat_history'):
                        chat_history = temp_session['chat_history']
                
                # Add registration completion message to chat history
                registration_entry = {
                    'session_id': session_id or 'system',
                    'chat_text': f"System: Complaint registered successfully with ID {complaint_id}",
                    'timestamp': datetime.now().isoformat(),
                    'is_user': False
                }
                chat_history.append(registration_entry)
                
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO grievances (complaint_id, name, mobile, complaint_details, chat_history)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (complaint_id, name, mobile, complaint_details, json.dumps(chat_history)))
                    conn.commit()
                
                # Clean up temporary session
                if session_id:
                    try:
                        self.delete_temp_chat_session(session_id)
                    except Exception as e:
                        print(f"Warning: Failed to cleanup temp session: {e}")
                
                return complaint_id
        except sqlite3.Error as e:
            raise RuntimeError(f"Database error registering grievance: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to register grievance: {e}")
    
    def get_grievance_status(self, complaint_id: str = None, mobile: str = None) -> Optional[Dict]:
        """Get grievance status by complaint ID or mobile number"""
        try:
            if not complaint_id and not mobile:
                return None
            
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    if complaint_id:
                        cursor.execute('''
                            SELECT complaint_id, name, status, created_at, updated_at, chat_history
                            FROM grievances WHERE complaint_id = ?
                        ''', (complaint_id,))
                    elif mobile:
                        cursor.execute('''
                            SELECT complaint_id, name, status, created_at, updated_at, chat_history
                            FROM grievances WHERE mobile = ?
                            ORDER BY created_at DESC LIMIT 1
                        ''', (mobile,))
                    
                    result = cursor.fetchone()
                    if result:
                        try:
                            chat_history = json.loads(result[5]) if result[5] else []
                        except json.JSONDecodeError:
                            chat_history = []
                        
                        return {
                            'complaint_id': result[0],
                            'name': result[1],
                            'status': result[2],
                            'created_at': result[3],
                            'updated_at': result[4],
                            'chat_history': chat_history
                        }
                return None
        except sqlite3.Error as e:
            raise RuntimeError(f"Database error getting grievance status: {e}")
    
    def get_grievance_chat_history(self, complaint_id: str) -> List[Dict]:
        """Get chat history for a specific complaint"""
        try:
            grievance_info = self.get_grievance_status(complaint_id=complaint_id)
            if grievance_info:
                return grievance_info.get('chat_history', [])
            return []
        except Exception as e:
            print(f"Warning: Failed to get chat history: {e}")
            return []
    
    def update_chat_session(self, session_id: str, user_data: Dict, current_step: str):
        """Update or create temporary chat session"""
        try:
            if not session_id:
                raise ValueError("Session ID is required")
            
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT OR REPLACE INTO temp_chat_sessions (session_id, user_data, current_step, updated_at)
                        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ''', (session_id, json.dumps(user_data), current_step))
                    conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"Database error updating chat session: {e}")
    
    def get_chat_session(self, session_id: str) -> Optional[Dict]:
        """Get temporary chat session data"""
        return self.get_temp_chat_session(session_id)
    
    def get_temp_chat_session(self, session_id: str) -> Optional[Dict]:
        """Get temporary chat session data"""
        try:
            if not session_id:
                return None
            
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT user_data, current_step, chat_history FROM temp_chat_sessions WHERE session_id = ?
                    ''', (session_id,))
                    result = cursor.fetchone()
                    
                    if result:
                        try:
                            user_data = json.loads(result[0]) if result[0] else {}
                            chat_history = json.loads(result[2]) if result[2] else []
                        except json.JSONDecodeError:
                            user_data = {}
                            chat_history = []
                        
                        return {
                            'user_data': user_data,
                            'current_step': result[1],
                            'chat_history': chat_history
                        }
                return None
        except sqlite3.Error as e:
            print(f"Warning: Database error getting temp session: {e}")
            return None
    
    def delete_temp_chat_session(self, session_id: str):
        """Delete temporary chat session"""
        try:
            if not session_id:
                return
            
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM temp_chat_sessions WHERE session_id = ?', (session_id,))
                    conn.commit()
        except sqlite3.Error as e:
            print(f"Warning: Database error deleting temp session: {e}")
    
    def update_grievance_status(self, complaint_id: str, new_status: str, update_message: str = None):
        """Update grievance status and optionally add a status update message to chat history"""
        try:
            if not complaint_id or not new_status:
                raise ValueError("Complaint ID and new status are required")
            
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Update status
                    cursor.execute('''
                        UPDATE grievances 
                        SET status = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE complaint_id = ?
                    ''', (new_status, complaint_id))
                    
                    if cursor.rowcount == 0:
                        raise ValueError(f"Complaint {complaint_id} not found")
                    
                    conn.commit()
                
                # Add status update to chat history if message provided (separate transaction)
                if update_message:
                    status_entry = {
                        'session_id': 'system',
                        'chat_text': f"System: {update_message}",
                        'timestamp': datetime.now().isoformat(),
                        'is_user': False
                    }
                    self._add_to_complaint_chat_history(complaint_id, status_entry)
                
        except sqlite3.Error as e:
            raise RuntimeError(f"Database error updating grievance status: {e}")
    
    def search_knowledge_base(self, query: str) -> List[Dict]:
        """Search knowledge base for relevant answers"""
        try:
            if not query:
                return []
            
            with self._lock:
                with self._get_connection() as conn:
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
        except sqlite3.Error as e:
            print(f"Warning: Database error searching knowledge base: {e}")
            return []
    
    def get_all_grievances(self, limit: int = 50) -> List[Dict]:
        """Get all grievances with basic info (for admin/reporting purposes)"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT complaint_id, name, mobile, status, created_at, updated_at
                        FROM grievances
                        ORDER BY created_at DESC
                        LIMIT ?
                    ''', (limit,))
                    
                    results = cursor.fetchall()
                    return [{
                        'complaint_id': r[0],
                        'name': r[1],
                        'mobile': r[2],
                        'status': r[3],
                        'created_at': r[4],
                        'updated_at': r[5]
                    } for r in results]
        except sqlite3.Error as e:
            print(f"Warning: Database error getting all grievances: {e}")
            return []
    
    def cleanup_old_temp_sessions(self, hours_old: int = 24):
        """Clean up temporary chat sessions older than specified hours"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        DELETE FROM temp_chat_sessions 
                        WHERE datetime(created_at) < datetime('now', '-{} hours')
                    '''.format(hours_old))
                    conn.commit()
                    return cursor.rowcount
        except sqlite3.Error as e:
            print(f"Warning: Database error cleaning up temp sessions: {e}")
            return 0
    
    def _is_session_already_used(self, session_id: str) -> bool:
        """Check if a session ID is already associated with any complaint"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) FROM grievances 
                    WHERE chat_history LIKE ?
                ''', (f'%"session_id": "{session_id}"%',))
                count = cursor.fetchone()[0]
                return count > 0
        except sqlite3.Error as e:
            print(f"Warning: Database error checking session usage: {e}")
            return False
    
    def _can_session_be_added_to_complaint(self, session_id: str, complaint_id: str) -> bool:
        """Check if a session ID can be added to a specific complaint"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Check if session is already in this complaint (allowed)
                cursor.execute('''
                    SELECT chat_history FROM grievances WHERE complaint_id = ?
                ''', (complaint_id,))
                result = cursor.fetchone()
                
                if result and result[0]:
                    try:
                        chat_history = json.loads(result[0])
                        # Check if session is already in this complaint
                        for entry in chat_history:
                            if entry.get('session_id') == session_id:
                                return True  # Already in this complaint, OK to add more
                    except json.JSONDecodeError:
                        pass
                
                # Check if session is in any other complaint (not allowed)
                cursor.execute('''
                    SELECT COUNT(*) FROM grievances 
                    WHERE complaint_id != ? AND chat_history LIKE ?
                ''', (complaint_id, f'%"session_id": "{session_id}"%'))
                count = cursor.fetchone()[0]
                return count == 0
        except sqlite3.Error as e:
            print(f"Warning: Database error checking session compatibility: {e}")
            return False
    
    def get_sessions_for_complaint(self, complaint_id: str) -> List[str]:
        """Get all unique session IDs associated with a complaint"""
        try:
            chat_history = self.get_grievance_chat_history(complaint_id)
            session_ids = set()
            for entry in chat_history:
                if entry.get('session_id') and entry['session_id'] != 'system':
                    session_ids.add(entry['session_id'])
            return list(session_ids)
        except Exception as e:
            print(f"Warning: Error getting sessions for complaint: {e}")
            return []
    
    def get_complaint_for_session(self, session_id: str) -> Optional[str]:
        """Get the complaint ID associated with a session ID (if any)"""
        try:
            if not session_id:
                return None
            
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT complaint_id FROM grievances 
                        WHERE chat_history LIKE ?
                    ''', (f'%"session_id": "{session_id}"%',))
                    result = cursor.fetchone()
                    return result[0] if result else None
        except sqlite3.Error as e:
            print(f"Warning: Database error getting complaint for session: {e}")
            return None
    
    def add_session_to_existing_complaint(self, complaint_id: str, session_id: str) -> bool:
        """
        Add a new session to an existing complaint by transferring temp session history
        Returns True if successful, False if session already associated with another complaint
        """
        try:
            if not complaint_id or not session_id:
                return False
            
            with self._lock:
                # Check if session can be added to this complaint
                if not self._can_session_be_added_to_complaint(session_id, complaint_id):
                    return False
                
                # Get temp session chat history
                temp_session = self.get_temp_chat_session(session_id)
                if not temp_session or not temp_session.get('chat_history'):
                    return True  # Nothing to transfer, but not an error
                
                # Add each message from temp session to complaint
                for chat_entry in temp_session['chat_history']:
                    self._add_to_complaint_chat_history(complaint_id, chat_entry)
                
                # Add a system message about session continuation
                continuation_entry = {
                    'session_id': session_id,
                    'chat_text': f"System: Continued conversation in session {session_id}",
                    'timestamp': datetime.now().isoformat(),
                    'is_user': False
                }
                self._add_to_complaint_chat_history(complaint_id, continuation_entry)
                
                # Clean up temp session
                self.delete_temp_chat_session(session_id)
                return True
        except Exception as e:
            print(f"Warning: Error adding session to complaint: {e}")
            return False

# Initialize the database
if __name__ == "__main__":
    try:
        db = DatabaseManager()
        print("Database initialized successfully!")
        
        # Example usage of new chat history features
        print("\nTesting chat history functionality:")
        
        # Test adding messages to temp session
        session_id = "test_session_123"
        db.add_chat_message(session_id, "I have a problem with my laptop", True)
        db.add_chat_message(session_id, "I'll help you register a complaint. What's your name?", False)
        db.add_chat_message(session_id, "John Doe", True)
        
        # Register complaint and transfer chat history
        complaint_id = db.register_grievance("John Doe", "9876543210", "Laptop screen issues", session_id)
        print(f"Complaint registered: {complaint_id}")
        
        # Get chat history
        chat_history = db.get_grievance_chat_history(complaint_id)
        print(f"Chat history entries: {len(chat_history)}")
        for entry in chat_history:
            print(f"  {entry['timestamp'][:19]} - {entry['chat_text']}")
        
        # Update status with message - add a small delay to ensure proper transaction handling
        time.sleep(0.1)
        db.update_grievance_status(complaint_id, "In Progress", "Your complaint has been assigned to our technical team.")
        
        # Show updated chat history
        time.sleep(0.1)
        updated_history = db.get_grievance_chat_history(complaint_id)
        print(f"\nUpdated chat history entries: {len(updated_history)}")
        for entry in updated_history[-2:]:  # Show last 2 entries
            print(f"  {entry['timestamp'][:19]} - {entry['chat_text']}")
    
    except Exception as e:
        print(f"Error: {e}")
