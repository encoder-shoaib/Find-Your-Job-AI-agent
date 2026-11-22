"""
tools/duplicate_checker.py - Tool 3: check_duplicate_jobs()
Multi-tier deduplication checking across:
1. MongoDB Database (Primary)
2. Local JSON Files: data/jobs.json and data/processed_jobs.json (Backup)
3. Excel Spreadsheet: data/jobs.xlsx (Report)

Identifies duplicates by Unique Job ID, original URLs, and Company + Title fuzzy matching.
"""

import os
import json
from datetime import datetime
from typing import List, Dict, Any, Set, Tuple

from tools.mongodb_manager import (
    is_job_duplicate_in_mongodb,
    get_known_job_ids_from_mongodb,
    mark_jobs_processed_in_mongodb
)
from tools.json_manager import load_jobs_from_json, DEFAULT_JSON_PATH


def normalize_string(val: str) -> str:
    """Normalizes a string for comparison."""
    if not val:
        return ""
    return "".join(c.lower() for c in val if c.isalnum())


def load_processed_cache(
    cache_path: str = "data/processed_jobs.json",
    excel_path: str = "data/jobs.xlsx",
    json_path: str = DEFAULT_JSON_PATH
) -> Dict[str, Any]:
    """
    Aggregates all known job IDs, URLs, and (Company, Title) signatures
    from MongoDB, JSON Backup, JSON Cache, and Excel.
    """
    known_ids: Set[str] = set()
    known_urls: Set[str] = set()
    known_signatures: Set[str] = set()
    records: Dict[str, Dict[str, Any]] = {}

    # 1. Read from MongoDB (Primary Tier)
    try:
        mongo_ids = get_known_job_ids_from_mongodb()
        known_ids.update(mongo_ids)
    except Exception:
        pass

    # 2. Read from data/jobs.json (Local Backup Tier)
    try:
        json_jobs = load_jobs_from_json(json_path)
        for j in json_jobs:
            jid = str(j.get("job_id", "")).strip()
            if jid:
                known_ids.add(jid)
            if j.get("original_url"):
                known_urls.add(j["original_url"])
            if j.get("apply_link"):
                known_urls.add(j["apply_link"])
            comp = normalize_string(j.get("company_name", ""))
            tit = normalize_string(j.get("job_title", ""))
            if comp and tit:
                known_signatures.add(f"{comp}::{tit}")
    except Exception:
        pass

    # 3. Read from data/processed_jobs.json (Cache Tier)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                records = data.get("jobs", {})
                for jid, item in records.items():
                    known_ids.add(str(jid).strip())
                    if item.get("url"):
                        known_urls.add(item["url"])
                    comp = normalize_string(item.get("company", ""))
                    tit = normalize_string(item.get("title", ""))
                    if comp and tit:
                        known_signatures.add(f"{comp}::{tit}")
        except Exception:
            records = {}

    # 4. Read from Excel database (Report Tier)
    if os.path.exists(excel_path):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(excel_path, read_only=True)
            if wb.sheetnames:
                ws = wb.active
                for row in ws.iter_rows(min_row=2, values_only=True):
                    if not row or len(row) < 3:
                        continue
                    title = str(row[1] or "")
                    company = str(row[2] or "")
                    orig_url = str(row[14] if len(row) > 14 else "")

                    if orig_url:
                        known_urls.add(orig_url)
                        import re
                        m = re.search(r'(?:details/|id=)(\d+)', orig_url)
                        if m:
                            known_ids.add(m.group(1))

                    c_norm = normalize_string(company)
                    t_norm = normalize_string(title)
                    if c_norm and t_norm:
                        known_signatures.add(f"{c_norm}::{t_norm}")
            wb.close()
        except Exception:
            pass

    return {
        "ids": known_ids,
        "urls": known_urls,
        "signatures": known_signatures,
        "raw_records": records
    }


def is_job_duplicate(job: Dict[str, Any], cache: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Checks if a job is duplicate across MongoDB, JSON, and Excel tiers.
    """
    jid = str(job.get("job_id", "")).strip()
    if jid and jid in cache["ids"]:
        return True, f"Duplicate Job ID: {jid}"

    url = job.get("original_url") or job.get("apply_link") or ""
    if url and url in cache["urls"]:
        return True, f"Duplicate URL: {url}"

    company = normalize_string(job.get("company_name", ""))
    title = normalize_string(job.get("job_title", ""))
    if company and title:
        sig = f"{company}::{title}"
        if sig in cache["signatures"]:
            return True, f"Duplicate Company+Title: {job.get('company_name')} - {job.get('job_title')}"

    # Also directly probe MongoDB if not caught by cache set
    if jid and is_job_duplicate_in_mongodb(jid, url):
        return True, f"Duplicate in MongoDB: {jid}"

    return False, ""


def filter_new_jobs(
    jobs: List[Dict[str, Any]],
    cache_path: str = "data/processed_jobs.json",
    excel_path: str = "data/jobs.xlsx",
    json_path: str = DEFAULT_JSON_PATH,
    logger=None
) -> List[Dict[str, Any]]:
    """
    Filters jobs, returning only those that do NOT exist in MongoDB, JSON, or Excel.
    """
    def log(msg: str):
        if logger:
            if hasattr(logger, "info"):
                logger.info(msg)
            elif callable(logger):
                logger(msg)
            else:
                print(msg)

    cache = load_processed_cache(cache_path, excel_path, json_path)
    new_jobs = []
    skipped_count = 0

    for job in jobs:
        dup, reason = is_job_duplicate(job, cache)
        if dup:
            skipped_count += 1
        else:
            new_jobs.append(job)
            # Add to local cache set to catch intra-batch duplicates
            jid = str(job.get("job_id", "")).strip()
            if jid:
                cache["ids"].add(jid)
            url = job.get("original_url", "")
            if url:
                cache["urls"].add(url)
            comp = normalize_string(job.get("company_name", ""))
            tit = normalize_string(job.get("job_title", ""))
            if comp and tit:
                cache["signatures"].add(f"{comp}::{tit}")

    log(f"Duplicate check (Multi-Tier): {len(jobs)} input jobs -> {len(new_jobs)} new, {skipped_count} duplicates skipped.")
    return new_jobs


def update_processed_cache(
    new_jobs: List[Dict[str, Any]],
    cache_path: str = "data/processed_jobs.json"
) -> None:
    """
    Saves newly processed jobs into processed_jobs.json AND MongoDB processed_jobs collection.
    """
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    existing_data = {"jobs": {}, "last_updated": datetime.now().isoformat()}

    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception:
            pass

    records = existing_data.setdefault("jobs", {})
    for j in new_jobs:
        jid = str(j.get("job_id", "")).strip()
        if not jid:
            continue
        records[jid] = {
            "title": j.get("job_title", ""),
            "company": j.get("company_name", ""),
            "url": j.get("original_url", ""),
            "processed_at": datetime.now().isoformat(),
            "match_score": j.get("match_score", 0),
            "priority": j.get("priority", "Low")
        }

    existing_data["last_updated"] = datetime.now().isoformat()
    existing_data["total_count"] = len(records)

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)

    # Sync to MongoDB processed_jobs collection
    mark_jobs_processed_in_mongodb(new_jobs, logger=None)
