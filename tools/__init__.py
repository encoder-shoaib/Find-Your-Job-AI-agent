"""
Tools package for YourFindJob.
Exports the core tools and multi-tier storage managers:
1. search_bdjobs
2. read_job_details
3. filter_new_jobs, update_processed_cache
4. analyze_job_match
5. save_jobs_to_excel
6. send_job_email
7. save_jobs_to_mongodb, is_job_duplicate_in_mongodb
8. save_jobs_to_json, load_jobs_from_json
"""

from .bdjobs_search import search_bdjobs
from .job_details import read_job_details
from .duplicate_checker import filter_new_jobs, update_processed_cache
from .job_analyzer import analyze_job_match
from .excel_manager import save_jobs_to_excel
from .email_sender import send_job_email
from .mongodb_manager import (
    save_jobs_to_mongodb,
    is_job_duplicate_in_mongodb,
    record_search_history,
    record_agent_log,
    get_all_jobs_from_mongodb
)
from .json_manager import (
    save_jobs_to_json,
    load_jobs_from_json,
    is_job_duplicate_in_json,
    get_unsynced_jobs_from_json,
    mark_jobs_as_synced_in_json
)

__all__ = [
    'search_bdjobs',
    'read_job_details',
    'filter_new_jobs',
    'update_processed_cache',
    'analyze_job_match',
    'save_jobs_to_excel',
    'send_job_email',
    'save_jobs_to_mongodb',
    'is_job_duplicate_in_mongodb',
    'record_search_history',
    'record_agent_log',
    'get_all_jobs_from_mongodb',
    'save_jobs_to_json',
    'load_jobs_from_json',
    'is_job_duplicate_in_json',
    'get_unsynced_jobs_from_json',
    'mark_jobs_as_synced_in_json'
]
