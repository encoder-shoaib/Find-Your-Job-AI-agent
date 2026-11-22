"""
Database package for YourFiendJob.
Exports MongoDB connection management and synchronization utilities.
"""

from .mongodb import (
    MongoDBManager,
    get_mongodb_manager,
    is_mongodb_available,
    COLLECTION_JOBS,
    COLLECTION_PROCESSED_JOBS,
    COLLECTION_SEARCH_HISTORY,
    COLLECTION_AGENT_LOGS
)

__all__ = [
    'MongoDBManager',
    'get_mongodb_manager',
    'is_mongodb_available',
    'COLLECTION_JOBS',
    'COLLECTION_PROCESSED_JOBS',
    'COLLECTION_SEARCH_HISTORY',
    'COLLECTION_AGENT_LOGS'
]
