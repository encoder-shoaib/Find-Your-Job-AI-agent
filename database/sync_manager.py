"""
database/sync_manager.py - Synchronization Manager between Local JSON & MongoDB.
Handles:
- Detecting MongoDB connectivity
- Syncing un-synced jobs from local JSON backup to MongoDB
- Syncing tracking records from processed_jobs.json to MongoDB
- Bi-directional consistency between MongoDB and local JSON
"""

from typing import Dict, Any, List, Set, Tuple
from database.mongodb import get_mongodb_manager, is_mongodb_available, COLLECTION_JOBS, COLLECTION_PROCESSED_JOBS
from tools.json_manager import (
    load_jobs_from_json,
    save_jobs_to_json,
    mark_jobs_as_synced_in_json,
    DEFAULT_JSON_PATH
)
from tools.mongodb_manager import save_jobs_to_mongodb, mark_jobs_processed_in_mongodb


class SyncManager:
    """Orchestrates bi-directional data synchronization between Local JSON and MongoDB."""

    def __init__(self, json_path: str = DEFAULT_JSON_PATH, processed_path: str = "data/processed_jobs.json", logger=None):
        self.json_path = json_path
        self.processed_path = processed_path
        self.logger = logger

    def log(self, msg: str):
        if self.logger:
            if hasattr(self.logger, "info"):
                self.logger.info(msg)
            elif callable(self.logger):
                self.logger(msg)
            else:
                print(msg)

    def sync_all(self) -> Dict[str, Any]:
        """
        Runs complete sync cycle:
        1. Checks MongoDB connectivity.
        2. Syncs local JSON jobs -> MongoDB.
        3. Syncs MongoDB jobs -> local JSON backup.
        4. Syncs processed_jobs.json -> MongoDB.
        """
        self.log("[Sync] Starting synchronization between JSON Backup and MongoDB...")
        
        mgr = get_mongodb_manager()
        ok, conn_msg = mgr.connect()
        if not ok:
            err_msg = f"[Sync Aborted] MongoDB is offline: {conn_msg}"
            self.log(err_msg)
            return {
                "success": False,
                "message": err_msg,
                "synced_to_mongo": 0,
                "synced_to_json": 0
            }

        synced_to_mongo_count = 0
        synced_to_json_count = 0

        # --- Step 1: Push Local JSON -> MongoDB ---
        local_jobs = load_jobs_from_json(self.json_path)
        col = mgr.get_collection(COLLECTION_JOBS)
        
        if local_jobs and col is not None:
            # Query existing IDs in MongoDB
            existing_mongo_ids = set()
            try:
                for doc in col.find({}, {"job_id": 1}):
                    if "job_id" in doc:
                        existing_mongo_ids.add(str(doc["job_id"]).strip())
            except Exception as e:
                self.log(f"[Sync Warning] Could not fetch MongoDB IDs: {e}")

            # Identify jobs needing sync to MongoDB
            jobs_to_push = []
            synced_ids: Set[str] = set()
            for j in local_jobs:
                jid = str(j.get("job_id", "")).strip()
                if not jid:
                    continue
                # If missing in mongo OR flagged as un-synced
                if jid not in existing_mongo_ids or not j.get("synced_to_db", False):
                    jobs_to_push.append(j)
                    synced_ids.add(jid)

            if jobs_to_push:
                self.log(f"[Sync] Found {len(jobs_to_push)} jobs in JSON needing upload to MongoDB...")
                success, msg, ins, upd = save_jobs_to_mongodb(jobs_to_push, logger=self.logger)
                if success:
                    synced_to_mongo_count = ins + upd
                    mark_jobs_as_synced_in_json(synced_ids, self.json_path)
                    self.log(f"[Sync Success] Uploaded {synced_to_mongo_count} jobs to MongoDB.")
            else:
                self.log("[Sync] All local JSON jobs are already synchronized with MongoDB.")

        # --- Step 2: Pull missing MongoDB jobs -> Local JSON ---
        if col is not None:
            try:
                local_ids = {str(j.get("job_id", "")).strip() for j in local_jobs if j.get("job_id")}
                mongo_missing_locally = []
                for doc in col.find({}, {"_id": 0}):
                    jid = str(doc.get("job_id", "")).strip()
                    if jid and jid not in local_ids:
                        doc["synced_to_db"] = True
                        mongo_missing_locally.append(doc)

                if mongo_missing_locally:
                    self.log(f"[Sync] Found {len(mongo_missing_locally)} jobs in MongoDB missing from local JSON. Backing up...")
                    s_ok, s_msg, added, _ = save_jobs_to_json(
                        mongo_missing_locally,
                        self.json_path,
                        synced_to_db=True,
                        logger=self.logger
                    )
                    if s_ok:
                        synced_to_json_count = added
                        self.log(f"[Sync Success] Pulled {synced_to_json_count} jobs from MongoDB to local JSON.")
            except Exception as e:
                self.log(f"[Sync Warning] Error pulling from MongoDB to JSON: {e}")

        # --- Step 3: Sync processed_jobs cache ---
        self._sync_processed_jobs_cache(mgr)

        result_msg = (
            f"Synchronization Complete: {synced_to_mongo_count} jobs synced to MongoDB, "
            f"{synced_to_json_count} jobs backed up to JSON."
        )
        self.log(f"[Sync Complete] {result_msg}")
        return {
            "success": True,
            "message": result_msg,
            "synced_to_mongo": synced_to_mongo_count,
            "synced_to_json": synced_to_json_count
        }

    def _sync_processed_jobs_cache(self, mgr):
        """Syncs data/processed_jobs.json with processed_jobs collection."""
        import os
        import json
        if not os.path.exists(self.processed_path):
            return

        try:
            with open(self.processed_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            records = data.get("jobs", {})
            job_dicts = []
            for jid, item in records.items():
                job_dicts.append({
                    "job_id": str(jid),
                    "url": item.get("url", ""),
                    "job_title": item.get("title", ""),
                    "company_name": item.get("company", ""),
                    "match_score": item.get("match_score", 0),
                    "priority": item.get("priority", "Low")
                })
            if job_dicts:
                mark_jobs_processed_in_mongodb(job_dicts, logger=None)
        except Exception:
            pass


def run_sync(json_path: str = DEFAULT_JSON_PATH, logger=None) -> Dict[str, Any]:
    """Helper function to execute synchronization."""
    sm = SyncManager(json_path=json_path, logger=logger)
    return sm.sync_all()
