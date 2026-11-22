"""
tools/json_manager.py - Local JSON Backup & Storage Manager.
Maintains data/jobs.json as a persistent, structured, human-readable local backup.
Ensures zero duplicates, atomic file writes, and sync status tracking.
"""

import os
import json
import tempfile
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional, Set

DEFAULT_JSON_PATH = "data/jobs.json"


def load_jobs_from_json(json_path: str = DEFAULT_JSON_PATH) -> List[Dict[str, Any]]:
    """Loads all job records from local JSON storage."""
    if not os.path.exists(json_path):
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("jobs", [])
    except Exception:
        return []
    return []


def is_job_duplicate_in_json(
    job_id: str,
    url: Optional[str] = None,
    json_path: str = DEFAULT_JSON_PATH
) -> bool:
    """Checks if a job exists in the local JSON storage by ID or URL."""
    jobs = load_jobs_from_json(json_path)
    job_id_str = str(job_id).strip()
    for j in jobs:
        if job_id_str and str(j.get("job_id", "")).strip() == job_id_str:
            return True
        if url and j.get("original_url", "").strip() == url.strip():
            return True
    return False


def save_jobs_to_json(
    jobs: List[Dict[str, Any]],
    json_path: str = DEFAULT_JSON_PATH,
    synced_to_db: bool = False,
    logger=None
) -> Tuple[bool, str, int, int]:
    """
    Saves or appends jobs to local JSON file without duplicates.
    Uses atomic write to prevent corruption during concurrent access or restarts.

    Returns:
        (success: bool, message: str, added_count: int, updated_count: int)
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
        return True, "No jobs to save to JSON.", 0, 0

    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    existing_jobs = load_jobs_from_json(json_path)

    # Index existing jobs by job_id
    jobs_map: Dict[str, Dict[str, Any]] = {}
    url_to_id: Dict[str, str] = {}

    for j in existing_jobs:
        jid = str(j.get("job_id", "")).strip()
        if jid:
            jobs_map[jid] = j
            if j.get("original_url"):
                url_to_id[j["original_url"]] = jid

    added_count = 0
    updated_count = 0

    for new_j in jobs:
        jid = str(new_j.get("job_id", "")).strip()
        if not jid:
            continue

        job_copy = dict(new_j)
        job_copy["last_updated"] = datetime.now().isoformat()
        job_copy.setdefault("created_at", datetime.now().isoformat())
        # Set sync flag
        if "synced_to_db" not in job_copy:
            job_copy["synced_to_db"] = synced_to_db

        if jid in jobs_map:
            # Update existing record
            jobs_map[jid].update(job_copy)
            updated_count += 1
        elif new_j.get("original_url") and new_j["original_url"] in url_to_id:
            orig_id = url_to_id[new_j["original_url"]]
            jobs_map[orig_id].update(job_copy)
            updated_count += 1
        else:
            # Add new record
            jobs_map[jid] = job_copy
            if job_copy.get("original_url"):
                url_to_id[job_copy["original_url"]] = jid
            added_count += 1

    final_list = list(jobs_map.values())

    # Atomic write to temporary file first, then replace
    try:
        dir_name = os.path.dirname(json_path) or "."
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
            json.dump(final_list, tf, indent=2, ensure_ascii=False)
            temp_name = tf.name

        # Atomically replace target file
        if os.path.exists(json_path):
            os.replace(temp_name, json_path)
        else:
            os.rename(temp_name, json_path)

        msg = f"JSON Backup: {added_count} jobs added, {updated_count} updated in '{json_path}' (Total: {len(final_list)})."
        log(f"[JSON Success] {msg}")
        return True, msg, added_count, updated_count

    except Exception as e:
        err_msg = f"JSON storage error: {e}"
        log(f"[JSON Error] {err_msg}")
        return False, err_msg, 0, 0


def get_unsynced_jobs_from_json(json_path: str = DEFAULT_JSON_PATH) -> List[Dict[str, Any]]:
    """Returns all jobs currently marked as not yet synced to MongoDB."""
    jobs = load_jobs_from_json(json_path)
    unsynced = [j for j in jobs if not j.get("synced_to_db", False)]
    return unsynced


def mark_jobs_as_synced_in_json(synced_job_ids: Set[str], json_path: str = DEFAULT_JSON_PATH) -> int:
    """Updates the 'synced_to_db' status to True for the given Job IDs."""
    if not synced_job_ids or not os.path.exists(json_path):
        return 0

    jobs = load_jobs_from_json(json_path)
    count = 0
    for j in jobs:
        if str(j.get("job_id", "")).strip() in synced_job_ids:
            j["synced_to_db"] = True
            j["synced_at"] = datetime.now().isoformat()
            count += 1

    try:
        dir_name = os.path.dirname(json_path) or "."
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
            json.dump(jobs, tf, indent=2, ensure_ascii=False)
            temp_name = tf.name
        os.replace(temp_name, json_path)
    except Exception:
        pass

    return count
