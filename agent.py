"""
agent.py - OpenAI Agents SDK Implementation for YourFindJob.
Wires tools into an autonomous AI agent capable of multi-tier storage:
1. MongoDB (Primary Database)
2. JSON (data/jobs.json Local Backup)
3. Excel (data/jobs.xlsx Formatted Report)
"""

import os
import json
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
import yaml

from agents import Agent, Runner, function_tool
from tools.bdjobs_search import search_bdjobs
from tools.job_details import read_job_details
from tools.duplicate_checker import filter_new_jobs, update_processed_cache
from tools.job_analyzer import analyze_job_match
from tools.excel_manager import save_jobs_to_excel
from tools.email_sender import send_job_email
from tools.mongodb_manager import (
    save_jobs_to_mongodb,
    record_search_history,
    record_agent_log
)
from tools.json_manager import save_jobs_to_json, DEFAULT_JSON_PATH
from database.mongodb import is_mongodb_available

load_dotenv()


class JobHuntingAgentContext:
    """Shared state container for the agent and its tools."""

    def __init__(self, config_path: str = "config.yaml", limit: Optional[int] = None, dry_run: bool = False, logger=None):
        self.config_path = config_path
        self.limit = limit
        self.dry_run = dry_run
        self.logger = logger
        self.config = self._load_config()
        
        # State caches
        self.discovered_jobs: Dict[str, Dict[str, Any]] = {}
        self.active_new_jobs: Dict[str, Dict[str, Any]] = {}
        self.analyzed_jobs: List[Dict[str, Any]] = []
        
        # Storage counts & status
        self.mongo_saved_count = 0
        self.json_saved_count = 0
        self.excel_saved_count = 0
        self.storage_status: Dict[str, Any] = {}
        self.email_sent = False

    def _load_config(self) -> Dict[str, Any]:
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def log(self, msg: str):
        if self.logger:
            if hasattr(self.logger, "info"):
                self.logger.info(msg)
            elif callable(self.logger):
                self.logger(msg)
            else:
                print(msg)


_CTX: Optional[JobHuntingAgentContext] = None


def set_agent_context(ctx: JobHuntingAgentContext):
    global _CTX
    _CTX = ctx


# ---------------------------------------------------------------------------
# Core Tool Implementations
# ---------------------------------------------------------------------------

def exec_search_bdjobs(keywords: List[str], max_jobs: int = 30) -> str:
    global _CTX
    if not _CTX:
        return "Error: Agent context not initialized."

    eff_max = _CTX.limit if _CTX.limit else max_jobs
    recency = _CTX.config.get("agent", {}).get("post_recency_days", 7)
    cat_ids = _CTX.config.get("agent", {}).get("category_ids", [8])

    # Preload existing IDs so search continues searching keywords until finding fresh jobs
    excel_file = _CTX.config.get("agent", {}).get("excel_file", "data/jobs.xlsx")
    cache_file = _CTX.config.get("agent", {}).get("processed_cache", "data/processed_jobs.json")
    json_file = _CTX.config.get("agent", {}).get("json_file", DEFAULT_JSON_PATH)
    from tools.duplicate_checker import load_processed_cache
    existing_cache = load_processed_cache(cache_file, excel_file, json_file)
    known_ids = existing_cache.get("ids", set())

    _CTX.log(f"Agent executing: search_bdjobs for up to {len(keywords)} keywords (Target: {eff_max} new jobs)...")
    results = search_bdjobs(
        keywords=keywords,
        category_ids=cat_ids,
        max_jobs=eff_max,
        recency_days=recency,
        exclude_ids=known_ids,
        logger=_CTX.logger
    )

    for j in results:
        jid = str(j.get("job_id"))
        _CTX.discovered_jobs[jid] = j

    # Log search history to MongoDB if available
    try:
        record_search_history(
            keywords=keywords,
            category_ids=cat_ids,
            found_count=len(results),
            new_count=len(results),
            status="Success",
            logger=_CTX.logger
        )
    except Exception:
        pass

    return f"Search completed. Found {len(results)} jobs matching search criteria."


def exec_check_duplicate_jobs() -> str:
    global _CTX
    if not _CTX:
        return "Error: Agent context not initialized."

    excel_file = _CTX.config.get("agent", {}).get("excel_file", "data/jobs.xlsx")
    cache_file = _CTX.config.get("agent", {}).get("processed_cache", "data/processed_jobs.json")
    json_file = _CTX.config.get("agent", {}).get("json_file", DEFAULT_JSON_PATH)

    job_list = list(_CTX.discovered_jobs.values())
    new_jobs = filter_new_jobs(
        job_list,
        cache_path=cache_file,
        excel_path=excel_file,
        json_path=json_file,
        logger=_CTX.logger
    )

    _CTX.active_new_jobs = {str(j["job_id"]): j for j in new_jobs}
    return f"Duplicate check done. {len(new_jobs)} new jobs remain to be processed."


def exec_read_job_details(job_id: str) -> str:
    global _CTX
    if not _CTX:
        return "Error: Agent context not initialized."

    details = read_job_details(job_id, logger=_CTX.logger)
    if "error" in details:
        return f"Error reading job {job_id}: {details.get('error')}"

    # Strict check: Require available application deadline
    deadline = details.get('application_deadline') or details.get('deadline') or ''
    deadline_str = str(deadline).strip()
    if not deadline_str or deadline_str.lower() in ['', 'n/a', 'none', 'not stated']:
        _CTX.log(f"Skipping job {job_id} ('{details.get('job_title')}'): Application deadline is not available.")
        _CTX.active_new_jobs.pop(job_id, None)
        return f"Job {job_id} skipped: No application deadline available."

    if job_id in _CTX.active_new_jobs:
        _CTX.active_new_jobs[job_id].update(details)
    else:
        _CTX.active_new_jobs[job_id] = details

    return f"Details loaded for '{details.get('job_title')}' at '{details.get('company_name')}' (Deadline: {deadline_str})."


def exec_analyze_job_match(job_id: str) -> str:
    global _CTX
    if not _CTX:
        return "Error: Agent context not initialized."

    job = _CTX.active_new_jobs.get(job_id)
    if not job:
        return f"Job {job_id} not found in active new jobs."

    # Verify deadline before analyzing
    deadline = job.get('application_deadline') or job.get('deadline') or ''
    deadline_str = str(deadline).strip()
    if not deadline_str or deadline_str.lower() in ['', 'n/a', 'none', 'not stated']:
        _CTX.log(f"Skipping analysis for job {job_id}: Application deadline is not available.")
        _CTX.active_new_jobs.pop(job_id, None)
        return f"Job {job_id} skipped: No application deadline available."

    user_profile = _CTX.config.get("user_profile", {})
    analysis = analyze_job_match(job, user_profile, logger=_CTX.logger)
    job.update(analysis)
    _CTX.analyzed_jobs.append(job)

    # Log action to MongoDB agent_logs
    try:
        record_agent_log(
            level="INFO",
            action="JOB_ANALYZED",
            message=f"Job {job_id} ({job.get('job_title')}) scored {analysis['match_score']}/10",
            metadata={"job_id": job_id, "score": analysis["match_score"], "priority": analysis["priority"]}
        )
    except Exception:
        pass

    return f"Analyzed job {job_id}: Score {analysis['match_score']}/10 ({analysis['priority']} Priority). Reason: {analysis['match_reason']}"


def exec_save_to_all_storages() -> str:
    """
    Saves newly analyzed jobs to all three tiers:
    Tier 1: MongoDB (Primary Database)
    Tier 2: JSON Backup (data/jobs.json)
    Tier 3: Excel Report (data/jobs.xlsx)
    """
    global _CTX
    if not _CTX:
        return "Error: Agent context not initialized."

    if not _CTX.analyzed_jobs:
        return "No analyzed jobs to save to storage."

    excel_file = _CTX.config.get("agent", {}).get("excel_file", "data/jobs.xlsx")
    cache_file = _CTX.config.get("agent", {}).get("processed_cache", "data/processed_jobs.json")
    json_file = _CTX.config.get("agent", {}).get("json_file", DEFAULT_JSON_PATH)

    jobs = _CTX.analyzed_jobs
    _CTX.log(f"Initiating Multi-Tier Storage operations for {len(jobs)} jobs...")

    # --- Tier 1: MongoDB Primary ---
    mongo_ok, mongo_msg, m_ins, m_upd = save_jobs_to_mongodb(jobs, logger=_CTX.logger)
    _CTX.mongo_saved_count = m_ins + m_upd
    _CTX.storage_status["mongodb"] = {"success": mongo_ok, "count": _CTX.mongo_saved_count, "message": mongo_msg}

    # --- Tier 2: Local JSON Backup ---
    # If MongoDB succeeded, mark synced_to_db=True; otherwise False (for future sync)
    json_ok, json_msg, j_add, j_upd = save_jobs_to_json(
        jobs,
        json_path=json_file,
        synced_to_db=mongo_ok,
        logger=_CTX.logger
    )
    _CTX.json_saved_count = j_add + j_upd
    _CTX.storage_status["json"] = {"success": json_ok, "count": _CTX.json_saved_count, "message": json_msg}

    # --- Tier 3: Excel Report ---
    excel_count = save_jobs_to_excel(jobs, file_path=excel_file, logger=_CTX.logger)
    _CTX.excel_saved_count = excel_count
    _CTX.storage_status["excel"] = {"success": True, "count": excel_count, "path": excel_file}

    # Update processed_jobs tracking
    update_processed_cache(jobs, cache_path=cache_file)

    summary_msg = (
        f"Storage complete: MongoDB: {_CTX.mongo_saved_count} saved | "
        f"JSON: {_CTX.json_saved_count} saved | "
        f"Excel: {_CTX.excel_saved_count} saved"
    )
    _CTX.log(summary_msg)
    return summary_msg


def exec_send_job_email() -> str:
    global _CTX
    if not _CTX:
        return "Error: Agent context not initialized."

    recipient = _CTX.config.get("user_profile", {}).get("email", "user@example.com")
    name = _CTX.config.get("user_profile", {}).get("name", "Job Seeker")
    excel_file = _CTX.config.get("agent", {}).get("excel_file", "data/jobs.xlsx")

    success = send_job_email(
        jobs=_CTX.analyzed_jobs,
        recipient_email=recipient,
        recipient_name=name,
        excel_path=excel_file,
        dry_run=_CTX.dry_run,
        logger=_CTX.logger
    )
    _CTX.email_sent = success
    return f"Email status: {'Sent successfully' if success else 'Skipped/Dry-run'}."


# ---------------------------------------------------------------------------
# Registered Tools for OpenAI Agents SDK
# ---------------------------------------------------------------------------

@function_tool
def search_bdjobs_tool(keywords: List[str], max_jobs: int = 30) -> str:
    """Search for Tech jobs on Bdjobs for the specified keywords."""
    return exec_search_bdjobs(keywords, max_jobs)


@function_tool
def check_duplicate_jobs_tool() -> str:
    """Checks discovered jobs against MongoDB, JSON, and Excel to filter out duplicates."""
    return exec_check_duplicate_jobs()


@function_tool
def read_job_details_tool(job_id: str) -> str:
    """Reads full circular details (skills, educational & experience requirements, salary) for a given Job ID."""
    return exec_read_job_details(job_id)


@function_tool
def analyze_job_match_tool(job_id: str) -> str:
    """Evaluates job compatibility against candidate profile (1-10 match score & priority)."""
    return exec_analyze_job_match(job_id)


@function_tool
def save_job_to_all_storages_tool() -> str:
    """Saves all analyzed new jobs into MongoDB (Primary), JSON (Backup), and Excel (Report)."""
    return exec_save_to_all_storages()


@function_tool
def send_job_email_tool() -> str:
    """Generates and sends the daily job notification email to the configured Gmail address."""
    return exec_send_job_email()


# ---------------------------------------------------------------------------
# Agent Construction & Workflow Orchestrator
# ---------------------------------------------------------------------------

AGENT_INSTRUCTIONS = """
You are YourFindJob, an autonomous AI-powered job hunting assistant for Technology jobs in Bangladesh.
Your goal is to find fresh, relevant tech jobs on Bdjobs, analyze their compatibility, record them across MongoDB, JSON, and Excel, and deliver a daily digest email.

Follow this standard procedure:
1. Search Bdjobs using the keywords provided by the user profile and configuration.
2. Check for duplicate jobs across MongoDB, JSON, and Excel so existing records are not processed again.
3. For all new jobs, read full details (skills, educational & experience requirements, salary).
4. Analyze each job match against the candidate's career interests and skills (1-10 score).
5. Save all verified and scored jobs into MongoDB, JSON backup, and Excel.
6. Dispatch the daily email digest to the candidate's Gmail.
7. Output a concise summary of the run.
"""


def create_yourfindjob_agent(model_name: Optional[str] = None) -> Agent:
    """Instantiates the OpenAI Agents SDK Agent with all tools."""
    if not model_name:
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    agent = Agent(
        name="YourFindJob",
        instructions=AGENT_INSTRUCTIONS,
        tools=[
            search_bdjobs_tool,
            check_duplicate_jobs_tool,
            read_job_details_tool,
            analyze_job_match_tool,
            save_job_to_all_storages_tool,
            send_job_email_tool
        ]
    )
    return agent


def run_job_hunting_agent(
    config_path: str = "config.yaml",
    limit: Optional[int] = None,
    dry_run: bool = False,
    logger=None
) -> Dict[str, Any]:
    """
    Executes the job hunting workflow with multi-tier storage (MongoDB, JSON, Excel).
    Uses OpenAI Agents SDK when an API key is available, and an autonomous
    deterministic agent orchestrator when running in offline/dry-run mode.
    """
    ctx = JobHuntingAgentContext(config_path=config_path, limit=limit, dry_run=dry_run, logger=logger)
    set_agent_context(ctx)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    use_openai_agent = bool(api_key and "your_" not in api_key.lower() and len(api_key) > 20)

    # Gather search keywords from config
    keywords: List[str] = []
    categories = ctx.config.get("tech_categories", {})
    for cat_name, kw_list in categories.items():
        if isinstance(kw_list, list):
            keywords.extend(kw_list)

    if not keywords:
        keywords = ["Software Engineer", "Python Developer", "AI Engineer"]

    ctx.log(f"Starting YourFindJob run (OpenAI Agent Mode: {'Active' if use_openai_agent else 'Autonomous Deterministic'})...")

    if use_openai_agent:
        try:
            agent = create_yourfindjob_agent()
            prompt = f"Please hunt for tech jobs on Bdjobs using keywords: {keywords[:8]}. Filter duplicates, inspect details, analyze match with my profile, save to MongoDB/JSON/Excel, and prepare the daily email."
            ctx.log("Invoking OpenAI Agents SDK Runner...")
            result = Runner.run_sync(agent, input=prompt)
            ctx.log(f"OpenAI Agents SDK completed execution: {result.final_output[:200] if hasattr(result, 'final_output') else 'OK'}")
        except Exception as e:
            ctx.log(f"OpenAI Agents SDK execution notice ({e}). Running autonomous agent orchestrator...")
            use_openai_agent = False

    if not use_openai_agent:
        # Step 1: Search
        max_limit = limit if limit else ctx.config.get("agent", {}).get("max_jobs_per_run", 30)
        exec_search_bdjobs(keywords=keywords, max_jobs=max_limit)
        
        # Step 2: Check duplicates (across MongoDB, JSON, Excel)
        exec_check_duplicate_jobs()

        # Step 3 & 4: Read details and analyze match
        for jid in list(ctx.active_new_jobs.keys()):
            exec_read_job_details(job_id=jid)
            exec_analyze_job_match(job_id=jid)

        # Step 5: Save to MongoDB, JSON, and Excel
        if ctx.analyzed_jobs:
            exec_save_to_all_storages()

        # Step 6: Send email
        exec_send_job_email()

    return {
        "total_discovered": len(ctx.discovered_jobs),
        "total_new": len(ctx.active_new_jobs),
        "total_analyzed": len(ctx.analyzed_jobs),
        "high_priority": len([j for j in ctx.analyzed_jobs if j.get("priority") == "High"]),
        "medium_priority": len([j for j in ctx.analyzed_jobs if j.get("priority") == "Medium"]),
        "low_priority": len([j for j in ctx.analyzed_jobs if j.get("priority") == "Low"]),
        "mongo_saved": ctx.mongo_saved_count,
        "json_saved": ctx.json_saved_count,
        "excel_saved": ctx.excel_saved_count,
        "storage_status": ctx.storage_status,
        "email_sent": ctx.email_sent,
        "jobs": ctx.analyzed_jobs
    }
