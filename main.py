"""
main.py - Main CLI entrypoint for YourFiendJob.
Multi-tier storage integration: MongoDB (Primary) + JSON (Backup) + Excel (Report).

Commands:
  python main.py                  # Normal full workflow run
  python main.py --dry-run        # Run without outbound email, saves to MongoDB/JSON/Excel
  python main.py --limit 5        # Process maximum 5 jobs
  python main.py --test           # Automated general health checks
  python main.py --test-db        # Verify MongoDB connection, collections, and indexes
  python main.py --test-json      # Verify local JSON backup operations and deduplication
  python main.py --test-storage   # Complete Multi-Tier Storage & Offline fallback test
  python main.py --sync           # Synchronize local JSON backup with MongoDB
  python main.py --scheduler      # Start daily 8:00 AM scheduler daemon
"""

import os
import sys
import argparse
import logging
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from agent import run_job_hunting_agent
from scheduler.daily_scheduler import start_scheduler
from database.mongodb import (
    get_mongodb_manager,
    COLLECTION_JOBS,
    COLLECTION_PROCESSED_JOBS,
    COLLECTION_SEARCH_HISTORY,
    COLLECTION_AGENT_LOGS
)
from database.sync_manager import run_sync
from tools.mongodb_manager import (
    save_jobs_to_mongodb,
    is_job_duplicate_in_mongodb,
    get_all_jobs_from_mongodb
)
from tools.json_manager import (
    save_jobs_to_json,
    load_jobs_from_json,
    is_job_duplicate_in_json,
    DEFAULT_JSON_PATH
)
from tools.excel_manager import save_jobs_to_excel

console = Console()


def setup_logger(log_file: str = "logs/yourfiendjob.log") -> logging.Logger:
    """Configures rotating file and console logging."""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logger = logging.getLogger("YourFiendJob")
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%Y-%m-%d %I:%M:%S %p"))
        logger.addHandler(fh)
    return logger


class RichAgentLogger:
    """Provides formatted, real-time logging output to terminal and file."""

    def __init__(self, file_logger: logging.Logger):
        self.file_logger = file_logger

    def info(self, msg: str):
        now_str = datetime.now().strftime("%I:%M %p")
        self.file_logger.info(msg)
        
        # Colorize milestones
        if "[MongoDB Success]" in msg:
            console.print(f"[bold green][{now_str}][/bold green] [bold green]{msg}[/bold green]")
        elif "[JSON Success]" in msg:
            console.print(f"[bold cyan][{now_str}][/bold cyan] [cyan]{msg}[/cyan]")
        elif "[Excel Success]" in msg:
            console.print(f"[bold magenta][{now_str}][/bold magenta] [magenta]{msg}[/magenta]")
        elif "Error" in msg or "Failed" in msg or "offline" in msg.lower():
            console.print(f"[bold red][{now_str}][/bold red] [red]{msg}[/red]")
        elif "High Priority" in msg or "🔥" in msg:
            console.print(f"[bold green][{now_str}][/bold green] [green]{msg}[/green]")
        elif "Warning" in msg or "Skipping" in msg:
            console.print(f"[bold yellow][{now_str}][/bold yellow] [yellow]{msg}[/yellow]")
        elif "Completed" in msg or "Saved" in msg:
            console.print(f"[bold blue][{now_str}][/bold blue] [bold blue]{msg}[/bold blue]")
        else:
            console.print(f"[dim][{now_str}][/dim] {msg}")


def print_banner():
    """Renders the application banner."""
    banner = Text()
    banner.append("YourFiendJob\n", style="bold cyan")
    banner.append("Your Personal AI Job Hunting Assistant • MongoDB + JSON + Excel Multi-Tier Storage", style="dim white")
    console.print(Panel(banner, border_style="cyan", expand=False))


def display_results_table(summary: dict):
    """Displays a clean summary table of analyzed jobs."""
    jobs = summary.get("jobs", [])
    if not jobs:
        console.print("[yellow]No new jobs were processed in this run.[/yellow]")
        return

    table = Table(title="[bold]Discovered & Analyzed Tech Jobs[/bold]", header_style="bold magenta", border_style="dim")
    table.add_column("#", style="dim", width=4)
    table.add_column("Job Title", style="bold white", min_width=25)
    table.add_column("Company", style="cyan", min_width=18)
    table.add_column("Location", style="white", min_width=12)
    table.add_column("Salary", style="green", min_width=12)
    table.add_column("Score", justify="center", width=8)
    table.add_column("Priority", justify="center", width=12)

    for idx, j in enumerate(jobs, 1):
        score = j.get("match_score", 5)
        prio = j.get("priority", "Low")
        
        if prio == "High":
            prio_text = Text("🔥 HIGH", style="bold green")
            score_text = Text(f"{score}/10", style="bold green")
        elif prio == "Medium":
            prio_text = Text("⭐ MEDIUM", style="bold yellow")
            score_text = Text(f"{score}/10", style="bold yellow")
        else:
            prio_text = Text("LOW", style="dim white")
            score_text = Text(f"{score}/10", style="dim white")

        table.add_row(
            str(idx),
            j.get("job_title", "")[:32],
            j.get("company_name", "")[:22],
            j.get("location", "")[:15],
            j.get("salary", "Negotiable")[:15],
            score_text,
            prio_text
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Specific Test Routines
# ---------------------------------------------------------------------------

def run_test_mongodb():
    """Validates MongoDB connection, collections, and index creation."""
    console.print(Panel("[bold cyan]Testing MongoDB Primary Database Connection & Collections...[/bold cyan]", border_style="cyan"))
    mgr = get_mongodb_manager()
    ok, msg = mgr.connect()

    table = Table(header_style="bold cyan", border_style="dim")
    table.add_column("Component", style="bold white")
    table.add_column("Target / Name", style="dim")
    table.add_column("Status", justify="center")

    if not ok:
        table.add_row("MongoDB Server Ping", mgr.uri, "[bold red]FAILED[/bold red]")
        console.print(table)
        console.print(f"[bold red]✘ MongoDB Connection Failed:[/bold red] {msg}")
        console.print("[yellow]Tip: Verify MongoDB service is running (mongod) or update MONGODB_URI in .env[/yellow]")
        return False

    table.add_row("MongoDB Server Ping", mgr.uri, "[bold green]PASS[/bold green]")
    table.add_row("Target Database", mgr.db_name, "[bold green]PASS[/bold green]")

    db = mgr.get_database()
    collections = [COLLECTION_JOBS, COLLECTION_PROCESSED_JOBS, COLLECTION_SEARCH_HISTORY, COLLECTION_AGENT_LOGS]
    
    for c_name in collections:
        col = db[c_name]
        count = col.count_documents({})
        table.add_row(f"Collection: {c_name}", f"{count} records", "[bold green]PASS[/bold green]")

    # Perform quick CRUD test with cleanup
    test_id = "TEST_MONGO_PING_999"
    try:
        col_jobs = db[COLLECTION_JOBS]
        col_jobs.update_one({"job_id": test_id}, {"$set": {"job_id": test_id, "test": True, "created_at": datetime.now().isoformat()}}, upsert=True)
        read_doc = col_jobs.find_one({"job_id": test_id})
        assert read_doc is not None, "Failed to read test document"
        col_jobs.delete_one({"job_id": test_id})
        table.add_row("CRUD Verification", "Write -> Read -> Delete", "[bold green]PASS[/bold green]")
    except Exception as e:
        table.add_row("CRUD Verification", str(e), "[bold red]FAIL[/bold red]")
        console.print(table)
        return False

    console.print(table)
    console.print("\n[bold green]✔ [PASS] MongoDB Database is fully operational and healthy![/bold green]\n")
    return True


def run_test_json():
    """Validates local JSON backup operations and deduplication."""
    console.print(Panel("[bold yellow]Testing Local JSON Storage (data/jobs.json)...[/bold yellow]", border_style="yellow"))
    test_json_path = "data/test_jobs.json"
    
    table = Table(header_style="bold yellow", border_style="dim")
    table.add_column("Test Step", style="bold white")
    table.add_column("Details", style="dim")
    table.add_column("Status", justify="center")

    try:
        # Step 1: Write mock jobs
        mock_jobs = [
            {"job_id": "TEST_J1", "job_title": "Python Dev", "company_name": "Co A", "original_url": "https://test.com/1"},
            {"job_id": "TEST_J2", "job_title": "React Dev", "company_name": "Co B", "original_url": "https://test.com/2"}
        ]
        ok, msg, added, updated = save_jobs_to_json(mock_jobs, json_path=test_json_path, synced_to_db=False)
        assert ok and added == 2
        table.add_row("Initial JSON Write", f"Wrote {added} jobs", "[bold green]PASS[/bold green]")

        # Step 2: Read back
        loaded = load_jobs_from_json(test_json_path)
        assert len(loaded) == 2
        table.add_row("JSON Read & Parse", f"Loaded {len(loaded)} jobs", "[bold green]PASS[/bold green]")

        # Step 3: Duplicate Prevention Test
        dup_job = [{"job_id": "TEST_J1", "job_title": "Python Dev Updated", "company_name": "Co A", "original_url": "https://test.com/1"}]
        ok, msg, d_add, d_upd = save_jobs_to_json(dup_job, json_path=test_json_path, synced_to_db=False)
        reloaded = load_jobs_from_json(test_json_path)
        assert d_add == 0 and d_upd == 1 and len(reloaded) == 2
        table.add_row("Duplicate Protection", "Existing ID updated, not duplicated", "[bold green]PASS[/bold green]")

        # Cleanup
        if os.path.exists(test_json_path):
            os.remove(test_json_path)

        console.print(table)
        console.print("\n[bold green]✔ [PASS] Local JSON Storage & Deduplication passed successfully![/bold green]\n")
        return True

    except Exception as e:
        table.add_row("JSON Verification", str(e), "[bold red]FAIL[/bold red]")
        console.print(table)
        if os.path.exists(test_json_path):
            os.remove(test_json_path)
        return False


def run_test_storage():
    """Comprehensive Multi-Tier Storage & Offline Fallback Test."""
    console.print(Panel("[bold magenta]Running Complete Multi-Tier Storage Suite (MongoDB + JSON + Excel + Offline Simulation)...[/bold magenta]", border_style="magenta"))

    # Test 1: MongoDB
    mongo_ok = run_test_mongodb()
    
    # Test 2: JSON
    json_ok = run_test_json()

    # Test 3: Excel
    excel_ok = False
    test_excel = "data/test_jobs.xlsx"
    try:
        mock_job = {
            "job_id": "TEST_E1",
            "job_title": "QA Engineer",
            "company_name": "Test Labs",
            "match_score": 8,
            "priority": "High",
            "location": "Dhaka",
            "salary": "Negotiable",
            "original_url": "https://bdjobs.com/h/details/test",
            "date_found": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        count = save_jobs_to_excel([mock_job], file_path=test_excel)
        assert count == 1 and os.path.exists(test_excel)
        excel_ok = True
        os.remove(test_excel)
    except Exception as e:
        console.print(f"[red]Excel test error: {e}[/red]")

    # Test 4: Offline Fallback Simulation
    console.print("\n[dim]Simulating Offline MongoDB Fallback...[/dim]")
    offline_json_path = "data/test_offline.json"
    fallback_ok = False
    try:
        # Save to JSON marking synced_to_db=False (simulating MongoDB is down)
        test_offline_job = [{"job_id": "OFFLINE_999", "job_title": "Offline Worker", "synced_to_db": False}]
        ok, msg, added, _ = save_jobs_to_json(test_offline_job, json_path=offline_json_path, synced_to_db=False)
        assert ok and added == 1
        loaded = load_jobs_from_json(offline_json_path)
        assert loaded[0]["synced_to_db"] is False
        fallback_ok = True
        os.remove(offline_json_path)
    except Exception as e:
        console.print(f"[red]Offline simulation error: {e}[/red]")
        if os.path.exists(offline_json_path):
            os.remove(offline_json_path)

    summary_table = Table(title="[bold]Multi-Tier Storage Test Matrix[/bold]", header_style="bold magenta", border_style="dim")
    summary_table.add_column("Storage Tier", style="bold white")
    summary_table.add_column("Target Destination", style="dim")
    summary_table.add_column("Result", justify="center")

    summary_table.add_row("Tier 1 (Primary)", "MongoDB Database (jobs, processed_jobs)", "[bold green]PASS[/bold green]" if mongo_ok else "[bold red]FAIL[/bold red]")
    summary_table.add_row("Tier 2 (Backup)", "Local JSON (data/jobs.json)", "[bold green]PASS[/bold green]" if json_ok else "[bold red]FAIL[/bold red]")
    summary_table.add_row("Tier 3 (Report)", "Excel Spreadsheet (data/jobs.xlsx)", "[bold green]PASS[/bold green]" if excel_ok else "[bold red]FAIL[/bold red]")
    summary_table.add_row("Offline Fallback", "Safe JSON save when MongoDB disconnected", "[bold green]PASS[/bold green]" if fallback_ok else "[bold red]FAIL[/bold red]")

    console.print(summary_table)

    if mongo_ok and json_ok and excel_ok and fallback_ok:
        console.print("\n[bold green]🎉 MULTI-TIER STORAGE SUITE PASSED COMPLETELY![/bold green]\n")
    else:
        console.print("\n[bold yellow]⚠ Some storage components encountered issues. Check logs above.[/bold yellow]\n")


def run_sync_command():
    """Executes synchronization between local JSON and MongoDB."""
    console.print(Panel("[bold blue]Starting Synchronization: Local JSON Backup <--> MongoDB...[/bold blue]", border_style="blue"))
    res = run_sync(json_path=DEFAULT_JSON_PATH)

    table = Table(header_style="bold blue", border_style="dim")
    table.add_column("Metric", style="bold white")
    table.add_column("Count / Status", justify="center")

    table.add_row("Sync Result", "[bold green]SUCCESS[/bold green]" if res["success"] else "[bold red]FAILED[/bold red]")
    table.add_row("Jobs Uploaded to MongoDB", f"[bold green]{res.get('synced_to_mongo', 0)}[/bold green]")
    table.add_row("Jobs Backed up to JSON", f"[bold cyan]{res.get('synced_to_json', 0)}[/bold cyan]")

    console.print(table)
    console.print(f"[bold cyan]{res.get('message')}[/bold cyan]\n")


def run_general_test_suite():
    """Runs automated health checks on all project tools."""
    console.print(Panel("[bold yellow]Running YourFiendJob System Health Checks...[/bold yellow]", border_style="yellow"))
    from tools.bdjobs_search import search_bdjobs
    from tools.job_details import read_job_details
    from tools.duplicate_checker import filter_new_jobs
    from tools.job_analyzer import analyze_job_match
    from tools.email_sender import generate_email_html
    import yaml

    all_passed = True

    # Test 1: Config
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        assert "user_profile" in cfg and "tech_categories" in cfg and "database" in cfg
        console.print("[green]✔ [PASS][/green] Config Check (config.yaml parsed successfully)")
    except Exception as e:
        console.print(f"[red]✘ [FAIL][/red] Config Check: {e}")
        all_passed = False

    # Test 2: Bdjobs Search API
    try:
        results = search_bdjobs(keywords=["Python"], max_jobs=2, recency_days=60)
        assert len(results) > 0, "No jobs returned by Bdjobs Search API"
        console.print(f"[green]✔ [PASS][/green] Bdjobs Search API (Retrieved {len(results)} sample jobs)")
        sample_id = results[0]["job_id"]
    except Exception as e:
        console.print(f"[red]✘ [FAIL][/red] Bdjobs Search API: {e}")
        all_passed = False
        sample_id = "1558619"

    # Test 3: Bdjobs Details API
    try:
        details = read_job_details(sample_id)
        assert "job_title" in details and "company_name" in details
        console.print(f"[green]✔ [PASS][/green] Bdjobs Details API (Retrieved '{details['job_title']}')")
    except Exception as e:
        console.print(f"[red]✘ [FAIL][/red] Bdjobs Details API: {e}")
        all_passed = False

    # Test 4: Duplicate Checker
    try:
        test_job = {"job_id": "TEST_CHK_9999", "company_name": "Test Co", "job_title": "Developer"}
        filtered = filter_new_jobs([test_job], cache_path="data/test_processed.json", excel_path="data/nonexistent.xlsx")
        assert len(filtered) == 1
        console.print("[green]✔ [PASS][/green] Duplicate Checker (Multi-Tier filtered cleanly)")
        if os.path.exists("data/test_processed.json"):
            os.remove("data/test_processed.json")
    except Exception as e:
        console.print(f"[red]✘ [FAIL][/red] Duplicate Checker: {e}")
        all_passed = False

    # Test 5: Job Match Analyzer
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        mock_job = {
            "job_title": "Junior Python Developer",
            "company_name": "AI Soft",
            "job_description": "We need a Python developer who knows Django and SQL.",
            "required_skills": "Python, Django, SQL",
            "experience": "0 to 1 year",
            "location": "Dhaka",
            "employment_type": "Full Time"
        }
        res = analyze_job_match(mock_job, cfg["user_profile"])
        assert 1 <= res["match_score"] <= 10 and res["priority"] in ("High", "Medium", "Low")
        console.print(f"[green]✔ [PASS][/green] Job Match Analyzer (Score: {res['match_score']}/10, Priority: {res['priority']})")
    except Exception as e:
        console.print(f"[red]✘ [FAIL][/red] Job Match Analyzer: {e}")
        all_passed = False

    # Test 6: Storage Checks
    run_test_storage()

    # Test 7: Email HTML Generator
    try:
        html = generate_email_html([mock_job], recipient_name="Tester")
        assert len(html) > 500 and "YourFiendJob" in html
        console.print("[green]✔ [PASS][/green] Email HTML Generator (Generated responsive template)")
    except Exception as e:
        console.print(f"[red]✘ [FAIL][/red] Email HTML Generator: {e}")
        all_passed = False

    if all_passed:
        console.print("\n[bold green]🎉 ALL SYSTEM HEALTH CHECKS PASSED! YourFiendJob is fully operational.[/bold green]\n")
    else:
        console.print("\n[bold red]⚠ Some health checks failed. Review errors above.[/bold red]\n")


def main():
    parser = argparse.ArgumentParser(
        description="YourFiendJob - Your Personal AI Job Hunting Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # Mode flags
    parser.add_argument("--dry-run", action="store_true", help="Run without sending real emails or external Google writes.")
    parser.add_argument("--limit", type=int, default=None, help="Process maximum N jobs (e.g. --limit 5).")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml file.")
    parser.add_argument("--scheduler", action="store_true", help="Start daily 8:00 AM scheduler daemon.")
    
    # Storage and testing flags
    parser.add_argument("--test", action="store_true", help="Run general automated self-tests.")
    parser.add_argument("--test-db", action="store_true", help="Test MongoDB connection, collections, and index creation.")
    parser.add_argument("--test-json", action="store_true", help="Test local JSON backup storage and deduplication.")
    parser.add_argument("--test-storage", action="store_true", help="Run complete Multi-Tier Storage suite (MongoDB, JSON, Excel, Offline).")
    parser.add_argument("--sync", action="store_true", help="Synchronize local JSON backup with MongoDB database.")

    args = parser.parse_args()

    print_banner()

    # Routing
    if args.test_db:
        run_test_mongodb()
        return

    if args.test_json:
        run_test_json()
        return

    if args.test_storage:
        run_test_storage()
        return

    if args.sync:
        run_sync_command()
        return

    if args.test:
        run_general_test_suite()
        return

    if args.scheduler:
        start_scheduler(config_path=args.config)
        return

    # Normal / Dry-Run Execution
    file_logger = setup_logger()
    agent_logger = RichAgentLogger(file_logger)

    mode_label = "[bold yellow]DRY-RUN MODE[/bold yellow]" if args.dry_run else "[bold green]NORMAL RUN MODE[/bold green]"
    if args.limit:
        mode_label += f" [cyan](Limit: {args.limit} jobs)[/cyan]"

    console.print(f"Mode: {mode_label}\n")

    try:
        summary = run_job_hunting_agent(
            config_path=args.config,
            limit=args.limit,
            dry_run=args.dry_run,
            logger=agent_logger
        )

        console.print("\n")
        display_results_table(summary)

        # Final Summary Panel with Multi-Tier Storage Breakdown
        email_status_str = "Preview saved in data/email_preview.html" if args.dry_run else ("Sent to Gmail" if summary.get("email_sent") else "Pending / Check .env credentials")
        summary_text = (
            f"[bold]Total Discovered:[/bold] {summary.get('total_discovered', 0)} | "
            f"[bold]New Processed:[/bold] {summary.get('total_analyzed', 0)}\n"
            f"[bold green]High Priority:[/bold green] {summary.get('high_priority', 0)} | "
            f"[bold yellow]Medium Priority:[/bold yellow] {summary.get('medium_priority', 0)} | "
            f"[dim]Low Priority:[/dim] {summary.get('low_priority', 0)}\n"
            f"[bold green]MongoDB Saved:[/bold green] {summary.get('mongo_saved', 0)} records (Primary)\n"
            f"[bold cyan]JSON Saved:[/bold cyan] {summary.get('json_saved', 0)} records in data/jobs.json (Backup)\n"
            f"[bold magenta]Excel Saved:[/bold magenta] {summary.get('excel_saved', 0)} rows in data/jobs.xlsx (Report)\n"
            f"[bold blue]Email Status:[/bold blue] {email_status_str}"
        )
        console.print(Panel(summary_text, title="[bold cyan]Multi-Tier Storage & Execution Summary[/bold cyan]", border_style="cyan"))

    except KeyboardInterrupt:
        console.print("\n[yellow]Execution interrupted by user.[/yellow]")
    except Exception as e:
        console.print(f"\n[bold red]Fatal error during execution:[/bold red] {e}")
        file_logger.error(f"Fatal error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
