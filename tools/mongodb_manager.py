"""
tools/mongodb_manager.py - MongoDB CRUD operations for YourFindJob.
Handles:
- 'jobs' collection: primary job document storage with unique job_id / URL
- 'processed_jobs' collection: tracking already processed jobs
- 'search_history' collection: recording search runs and metrics
- 'agent_logs' collection: structured logging of agent actions and errors
"""

from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Set
from pymongo.errors import PyMongoError, DuplicateKeyError
from database.mongodb import (
    get_mongodb_manager,
    COLLECTION_JOBS,
    COLLECTION_PROCESSED_JOBS,
    COLLECTION_SEARCH_HISTORY,
    COLLECTION_AGENT_LOGS
)


def save_jobs_to_mongodb(jobs: List[Dict[str, Any]], logger=None) -> Tuple[bool, str, int, int]:
    """
    Saves or updates jobs in the 'jobs' collection using upsert on job_id.

    Returns:
        (success: bool, message: str, inserted_count: int, updated_count: int)
    """
    def log(msg: str):
        if logger:
            if hasattr(logger, "info"):
                logger.info(msg)
            elif callable(logger):
                logger(msg)
            else:
                print(msg)

    if not jobs:
        return True, "No jobs provided to save.", 0, 0

    mgr = get_mongodb_manager()
    col = mgr.get_collection(COLLECTION_JOBS)
    if col is None:
        err_msg = "MongoDB is currently unavailable. Offline fallback active."
        log(f"[MongoDB Error] {err_msg}")
        return False, err_msg, 0, 0

    inserted_count = 0
    updated_count = 0

    try:
        for job in jobs:
            # Check deadline availability: Only deadline available job allowed
            deadline = job.get("application_deadline") or job.get("deadline") or ""
            deadline_str = str(deadline).strip()
            if not deadline_str or deadline_str.lower() in ["", "n/a", "none", "not stated"]:
                log(f"[MongoDB] Skipping job without available deadline: '{job.get('job_title')}'")
                continue

            job_id = str(job.get("job_id", "")).strip()
            if not job_id:
                continue

            orig_url = str(job.get("original_url") or job.get("apply_link") or "").strip()

            # Check if job already exists in database: Never duplicate/re-add existing jobs
            dup_query = {"job_id": job_id}
            if orig_url:
                dup_query = {"$or": [{"job_id": job_id}, {"original_url": orig_url}, {"url": orig_url}]}

            existing_doc = col.find_one(dup_query)
            if existing_doc:
                log(f"[MongoDB] Job already in database, skipping re-add: {job_id} ('{job.get('job_title')}')")
                continue

            doc = dict(job)
            doc["deadline"] = deadline_str
            doc["application_deadline"] = deadline_str
            doc["updated_at"] = datetime.now().isoformat()
            doc.setdefault("created_at", datetime.now().isoformat())
            doc["synced_to_db"] = True

            col.insert_one(doc)
            inserted_count += 1

        # Also register in processed_jobs collection
        mark_jobs_processed_in_mongodb(jobs, logger=logger)

        msg = f"MongoDB: {inserted_count} new jobs inserted (all duplicates skipped) in '{COLLECTION_JOBS}' collection."
        log(f"[MongoDB Success] {msg}")
        return True, msg, inserted_count, updated_count

    except PyMongoError as e:
        err_msg = f"MongoDB write error: {e}"
        log(f"[MongoDB Error] {err_msg}")
        return False, err_msg, inserted_count, updated_count


def mark_jobs_processed_in_mongodb(jobs: List[Dict[str, Any]], logger=None) -> int:
    """Inserts or updates tracking entries in 'processed_jobs' collection."""
    mgr = get_mongodb_manager()
    col = mgr.get_collection(COLLECTION_PROCESSED_JOBS)
    if col is None:
        return 0

    count = 0
    now_iso = datetime.now().isoformat()
    for job in jobs:
        job_id = str(job.get("job_id", "")).strip()
        if not job_id:
            continue
        try:
            col.update_one(
                {"job_id": job_id},
                {"$set": {
                    "job_id": job_id,
                    "url": job.get("original_url") or job.get("apply_link") or "",
                    "title": job.get("job_title", ""),
                    "company": job.get("company_name", ""),
                    "match_score": job.get("match_score", 0),
                    "priority": job.get("priority", "Low"),
                    "processed_at": now_iso
                }},
                upsert=True
            )
            count += 1
        except Exception:
            pass
    return count


def is_job_duplicate_in_mongodb(job_id: str, url: Optional[str] = None) -> bool:
    """Checks if a job already exists in MongoDB by job_id or URL."""
    mgr = get_mongodb_manager()
    col = mgr.get_collection(COLLECTION_JOBS)
    if col is None:
        return False

    try:
        if job_id and col.find_one({"job_id": str(job_id).strip()}):
            return True
        if url and col.find_one({"original_url": url.strip()}):
            return True
        # Also check processed_jobs collection
        proc_col = mgr.get_collection(COLLECTION_PROCESSED_JOBS)
        if proc_col and job_id and proc_col.find_one({"job_id": str(job_id).strip()}):
            return True
    except Exception:
        pass
    return False


def get_known_job_ids_from_mongodb() -> Set[str]:
    """Retrieves all existing job IDs from MongoDB."""
    mgr = get_mongodb_manager()
    known = set()
    try:
        col = mgr.get_collection(COLLECTION_JOBS)
        if col:
            for doc in col.find({}, {"job_id": 1}):
                if "job_id" in doc:
                    known.add(str(doc["job_id"]))
        proc_col = mgr.get_collection(COLLECTION_PROCESSED_JOBS)
        if proc_col:
            for doc in proc_col.find({}, {"job_id": 1}):
                if "job_id" in doc:
                    known.add(str(doc["job_id"]))
    except Exception:
        pass
    return known


def record_search_history(
    keywords: List[str],
    category_ids: List[int],
    found_count: int,
    new_count: int,
    status: str = "Success",
    logger=None
) -> bool:
    """Records search run parameters and counts in 'search_history' collection."""
    mgr = get_mongodb_manager()
    col = mgr.get_collection(COLLECTION_SEARCH_HISTORY)
    if col is None:
        return False
    try:
        doc = {
            "timestamp": datetime.now().isoformat(),
            "keywords": keywords,
            "category_ids": category_ids,
            "found_count": found_count,
            "new_count": new_count,
            "status": status
        }
        col.insert_one(doc)
        return True
    except Exception:
        return False


def record_agent_log(
    level: str,
    action: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """Records an event or error in the 'agent_logs' collection."""
    mgr = get_mongodb_manager()
    col = mgr.get_collection(COLLECTION_AGENT_LOGS)
    if col is None:
        return False
    try:
        doc = {
            "timestamp": datetime.now().isoformat(),
            "level": level.upper(),
            "action": action,
            "message": message,
            "metadata": metadata or {}
        }
        col.insert_one(doc)
        return True
    except Exception:
        return False


def get_all_jobs_from_mongodb(limit: int = 100) -> List[Dict[str, Any]]:
    """Fetches jobs stored in MongoDB."""
    mgr = get_mongodb_manager()
    col = mgr.get_collection(COLLECTION_JOBS)
    if col is None:
        return []
    try:
        docs = list(col.find({}, {"_id": 0}).sort("date_found", -1).limit(limit))
        return docs
    except Exception:
        return []
