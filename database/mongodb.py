"""
database/mongodb.py - MongoDB connection manager and collections initializer.
Provides persistent client connection, ping checks, index creation, and collection access.
"""

import os
from typing import Optional, Dict, Any, Tuple
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from pymongo.collection import Collection
from pymongo.database import Database

load_dotenv()

DEFAULT_URI = "mongodb://localhost:27017/"
DEFAULT_DB_NAME = "yourfindjob_db"
DEFAULT_TIMEOUT_MS = 3000

COLLECTION_JOBS = "jobs"
COLLECTION_PROCESSED_JOBS = "processed_jobs"
COLLECTION_SEARCH_HISTORY = "search_history"
COLLECTION_AGENT_LOGS = "agent_logs"


class MongoDBManager:
    """Singleton MongoDB Client & Database Manager."""

    _instance: Optional['MongoDBManager'] = None

    def __init__(self):
        self.uri = os.getenv("MONGODB_URI", DEFAULT_URI).strip() or DEFAULT_URI
        self.db_name = os.getenv("MONGODB_DB_NAME", DEFAULT_DB_NAME).strip() or DEFAULT_DB_NAME
        timeout = int(os.getenv("MONGODB_TIMEOUT_MS", str(DEFAULT_TIMEOUT_MS)))
        self.timeout_ms = timeout
        self._client: Optional[MongoClient] = None
        self._db: Optional[Database] = None

    @classmethod
    def get_instance(cls) -> 'MongoDBManager':
        if cls._instance is None:
            cls._instance = MongoDBManager()
        return cls._instance

    def connect(self) -> Tuple[bool, str]:
        """
        Attempts to connect to MongoDB and ping the server.
        Returns:
            (success: bool, message: str)
        """
        try:
            if self._client is None:
                self._client = MongoClient(
                    self.uri,
                    serverSelectionTimeoutMS=self.timeout_ms,
                    connectTimeoutMS=self.timeout_ms
                )
            # Ping the admin server to verify live connectivity
            self._client.admin.command('ping')
            self._db = self._client[self.db_name]
            self.init_indexes()
            return True, f"Successfully connected to MongoDB ({self.uri}) DB: {self.db_name}"
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            self._client = None
            self._db = None
            return False, f"MongoDB connection failed: {e}"
        except Exception as e:
            self._client = None
            self._db = None
            return False, f"Unexpected error connecting to MongoDB: {e}"

    def is_connected(self) -> bool:
        """Quickly checks if current connection is active."""
        if self._client is None or self._db is None:
            ok, _ = self.connect()
            return ok
        try:
            self._client.admin.command('ping')
            return True
        except Exception:
            return False

    def get_database(self) -> Optional[Database]:
        """Returns the active MongoDB database instance, or None if offline."""
        if not self.is_connected():
            return None
        return self._db

    def get_collection(self, collection_name: str) -> Optional[Collection]:
        """Returns a specific collection from the database."""
        db = self.get_database()
        if db is not None:
            return db[collection_name]
        return None

    def init_indexes(self) -> None:
        """
        Ensures unique indexes are established for deduplication:
        - jobs: unique on job_id, unique on original_url
        - processed_jobs: unique on job_id
        """
        if self._db is None:
            return
        try:
            jobs_col = self._db[COLLECTION_JOBS]
            jobs_col.create_index([("job_id", ASCENDING)], unique=True, sparse=True)
            jobs_col.create_index([("original_url", ASCENDING)], unique=True, sparse=True)
            jobs_col.create_index([("match_score", ASCENDING)])
            jobs_col.create_index([("priority", ASCENDING)])
            jobs_col.create_index([("date_found", ASCENDING)])

            proc_col = self._db[COLLECTION_PROCESSED_JOBS]
            proc_col.create_index([("job_id", ASCENDING)], unique=True, sparse=True)
            proc_col.create_index([("url", ASCENDING)])

            search_col = self._db[COLLECTION_SEARCH_HISTORY]
            search_col.create_index([("timestamp", ASCENDING)])

            logs_col = self._db[COLLECTION_AGENT_LOGS]
            logs_col.create_index([("timestamp", ASCENDING)])
        except Exception:
            pass

    def close(self):
        """Closes the client connection."""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None


# Module-level convenience functions
def get_mongodb_manager() -> MongoDBManager:
    return MongoDBManager.get_instance()


def is_mongodb_available() -> bool:
    return get_mongodb_manager().is_connected()
