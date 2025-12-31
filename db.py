"""
Turso Database Module for MT5 DOM Visualization
================================================
Handles all database operations using Turso HTTP API.

Tables:
- user_settings: Key-value store for user preferences
- price_history: Sampled price snapshots
- trade_log: Simulated trades and order blocks
- session_data: User session tracking
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
import httpx

# ============================================================================
# CONFIGURATION
# ============================================================================

TURSO_URL = "https://mrvgfx-arra7trader.aws-ap-northeast-1.turso.io"
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3NjcyMTUxNTYsImlkIjoiOWU2YjA4NDgtMWFhMC00YmJlLTg2YjUtOGNiZDI4YTE2Y2VhIiwicmlkIjoiYjM3NTg4ZTctOTY4Yy00YWY2LTk3NDgtOTc4ZGJmMmY3NTg3In0.k6D-4oYJX3kU4RiHzuCtFE9YBF5VLpO8mOjBDobBFGm79aNJmyHhtfbiNtBz2_pTecWKPJwExO6gQ-DpwHKNBQ"

PRICE_SNAPSHOT_INTERVAL = 5  # seconds

logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE CONNECTION (HTTP API)
# ============================================================================

class TursoDatabase:
    """Manages Turso database connection via HTTP API."""
    
    def __init__(self):
        self.base_url = TURSO_URL
        self.headers = {
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type": "application/json"
        }
        self.initialized = False
    
    def _execute(self, sql: str, args: List[Any] = None) -> Optional[Dict]:
        """Execute a SQL statement via HTTP API."""
        try:
            payload = {
                "requests": [
                    {
                        "type": "execute",
                        "stmt": {
                            "sql": sql,
                            "args": [{"type": "text", "value": str(a)} if isinstance(a, str) 
                                    else {"type": "integer", "value": a} if isinstance(a, int)
                                    else {"type": "float", "value": a} if isinstance(a, float)
                                    else {"type": "null"} for a in (args or [])]
                        }
                    },
                    {"type": "close"}
                ]
            }
            
            response = httpx.post(
                f"{self.base_url}/v2/pipeline",
                headers=self.headers,
                json=payload,
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                if "results" in data and len(data["results"]) > 0:
                    return data["results"][0]
                return data
            else:
                logger.error(f"Database error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Database request failed: {e}")
            return None
    
    def initialize_schema(self) -> bool:
        """Create tables if they don't exist."""
        try:
            # User Settings Table
            self._execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Price History Table
            self._execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    bid REAL NOT NULL,
                    ask REAL NOT NULL,
                    mid_price REAL NOT NULL,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Trade Log Table
            self._execute("""
                CREATE TABLE IF NOT EXISTS trade_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    price REAL NOT NULL,
                    volume REAL NOT NULL,
                    side TEXT NOT NULL,
                    is_order_block INTEGER DEFAULT 0,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Session Data Table
            self._execute("""
                CREATE TABLE IF NOT EXISTS session_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE NOT NULL,
                    last_symbol TEXT,
                    last_activity TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for performance
            self._execute("CREATE INDEX IF NOT EXISTS idx_price_symbol ON price_history(symbol)")
            self._execute("CREATE INDEX IF NOT EXISTS idx_trade_symbol ON trade_log(symbol)")
            
            self.initialized = True
            logger.info("✅ Database schema initialized")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize schema: {e}")
            return False

    # ========================================================================
    # USER SETTINGS OPERATIONS
    # ========================================================================
    
    def get_setting(self, key: str) -> Optional[str]:
        """Get a user setting by key."""
        try:
            result = self._execute(
                "SELECT value FROM user_settings WHERE key = ?", [key]
            )
            if result and "response" in result:
                resp = result["response"]
                if "result" in resp and "rows" in resp["result"]:
                    rows = resp["result"]["rows"]
                    if len(rows) > 0:
                        return rows[0][0]["value"]
            return None
        except Exception as e:
            logger.error(f"Error getting setting {key}: {e}")
            return None
    
    def set_setting(self, key: str, value: str) -> bool:
        """Set or update a user setting."""
        try:
            result = self._execute("""
                INSERT INTO user_settings (key, value, updated_at) 
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
            """, [key, value])
            return result is not None
        except Exception as e:
            logger.error(f"Error setting {key}: {e}")
            return False
    
    def get_all_settings(self) -> Dict[str, str]:
        """Get all user settings as a dictionary."""
        try:
            result = self._execute("SELECT key, value FROM user_settings")
            settings = {}
            if result and "response" in result:
                resp = result["response"]
                if "result" in resp and "rows" in resp["result"]:
                    for row in resp["result"]["rows"]:
                        settings[row[0]["value"]] = row[1]["value"]
            return settings
        except Exception as e:
            logger.error(f"Error getting all settings: {e}")
            return {}

    # ========================================================================
    # PRICE HISTORY OPERATIONS
    # ========================================================================
    
    def save_price_snapshot(self, symbol: str, bid: float, ask: float) -> bool:
        """Save a price snapshot to history."""
        try:
            mid_price = (bid + ask) / 2
            result = self._execute("""
                INSERT INTO price_history (symbol, bid, ask, mid_price, timestamp)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, [symbol, bid, ask, mid_price])
            return result is not None
        except Exception as e:
            logger.error(f"Error saving price snapshot: {e}")
            return False
    
    def get_price_history(self, symbol: str, limit: int = 100) -> List[Dict]:
        """Get recent price history for a symbol."""
        try:
            result = self._execute("""
                SELECT bid, ask, mid_price, timestamp 
                FROM price_history 
                WHERE symbol = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, [symbol, limit])
            
            history = []
            if result and "response" in result:
                resp = result["response"]
                if "result" in resp and "rows" in resp["result"]:
                    for row in resp["result"]["rows"]:
                        history.append({
                            "bid": float(row[0]["value"]),
                            "ask": float(row[1]["value"]),
                            "mid_price": float(row[2]["value"]),
                            "timestamp": row[3]["value"]
                        })
            return history
        except Exception as e:
            logger.error(f"Error getting price history: {e}")
            return []

    # ========================================================================
    # TRADE LOG OPERATIONS
    # ========================================================================
    
    def log_trade(self, symbol: str, price: float, volume: float, 
                  side: str, is_order_block: bool = False) -> bool:
        """Log a simulated trade or order block."""
        try:
            result = self._execute("""
                INSERT INTO trade_log (symbol, price, volume, side, is_order_block, timestamp)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
            """, [symbol, price, volume, side, 1 if is_order_block else 0])
            return result is not None
        except Exception as e:
            logger.error(f"Error logging trade: {e}")
            return False
    
    def get_trade_log(self, symbol: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Get recent trade log entries."""
        try:
            if symbol:
                result = self._execute("""
                    SELECT symbol, price, volume, side, is_order_block, timestamp 
                    FROM trade_log 
                    WHERE symbol = ?
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """, [symbol, limit])
            else:
                result = self._execute("""
                    SELECT symbol, price, volume, side, is_order_block, timestamp 
                    FROM trade_log 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """, [limit])
            
            trades = []
            if result and "response" in result:
                resp = result["response"]
                if "result" in resp and "rows" in resp["result"]:
                    for row in resp["result"]["rows"]:
                        trades.append({
                            "symbol": row[0]["value"],
                            "price": float(row[1]["value"]),
                            "volume": float(row[2]["value"]),
                            "side": row[3]["value"],
                            "is_order_block": bool(int(row[4]["value"])),
                            "timestamp": row[5]["value"]
                        })
            return trades
        except Exception as e:
            logger.error(f"Error getting trade log: {e}")
            return []

    # ========================================================================
    # SESSION OPERATIONS
    # ========================================================================
    
    def update_session(self, session_id: str, last_symbol: str) -> bool:
        """Update or create a session record."""
        try:
            result = self._execute("""
                INSERT INTO session_data (session_id, last_symbol, last_activity)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(session_id) DO UPDATE SET 
                    last_symbol = excluded.last_symbol, 
                    last_activity = datetime('now')
            """, [session_id, last_symbol])
            return result is not None
        except Exception as e:
            logger.error(f"Error updating session: {e}")
            return False
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session data by ID."""
        try:
            result = self._execute(
                "SELECT last_symbol, last_activity FROM session_data WHERE session_id = ?",
                [session_id]
            )
            if result and "response" in result:
                resp = result["response"]
                if "result" in resp and "rows" in resp["result"]:
                    rows = resp["result"]["rows"]
                    if len(rows) > 0:
                        return {
                            "last_symbol": rows[0][0]["value"],
                            "last_activity": rows[0][1]["value"]
                        }
            return None
        except Exception as e:
            logger.error(f"Error getting session: {e}")
            return None


# Global database instance
db = TursoDatabase()


def init_database() -> bool:
    """Initialize database schema."""
    return db.initialize_schema()
