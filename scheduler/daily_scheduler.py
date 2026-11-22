"""
scheduler/daily_scheduler.py - Daily Automation Scheduler for YourFindJob.
Runs every morning at 8:00 AM Bangladesh Time (Asia/Dhaka) using APScheduler.
"""

import os
import sys
import yaml
import logging
from datetime import datetime
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from agent import run_job_hunting_agent


def setup_logger(log_file: str = "logs/yourfindjob.log"):
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logger = logging.getLogger("YourFindJob")
    logger.setLevel(logging.INFO)
    
    # Avoid duplicate handlers if re-run
    if not logger.handlers:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%Y-%m-%d %I:%M:%S %p"))
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%I:%M %p"))
        logger.addHandler(console_handler)
    return logger


def scheduled_job():
    logger = setup_logger()
    logger.info("=" * 60)
    logger.info("YourFindJob Daily Scheduled Trigger Started.")
    try:
        summary = run_job_hunting_agent(config_path="config.yaml", dry_run=False, logger=logger)
        logger.info(f"Daily Run Completed: {summary.get('total_analyzed', 0)} jobs processed, "
                    f"{summary.get('high_priority', 0)} High Priority, {summary.get('excel_saved', 0)} saved to Excel.")
    except Exception as e:
        logger.error(f"Error during scheduled execution: {e}", exc_info=True)
    logger.info("=" * 60)


def start_scheduler(config_path: str = "config.yaml"):
    logger = setup_logger()
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    sched_cfg = cfg.get("scheduler", {})
    tz_str = sched_cfg.get("timezone", "Asia/Dhaka")
    cron_hour = sched_cfg.get("cron_hour", 8)
    cron_minute = sched_cfg.get("cron_minute", 0)

    tz = pytz.timezone(tz_str)
    scheduler = BlockingScheduler(timezone=tz)

    trigger = CronTrigger(hour=cron_hour, minute=cron_minute, timezone=tz)
    scheduler.add_job(scheduled_job, trigger=trigger, id="yourfindjob_daily_job", replace_existing=True)

    print("\n" + "=" * 65)
    print(f"  YourFindJob Daily Scheduler Active")
    print(f"  Scheduled Time: Every morning at {cron_hour:02d}:{cron_minute:02d} ({tz_str})")
    print(f"  Next Execution: Calculated according to {tz_str} wall clock")
    print(f"  Note: Keep this terminal / process running (or deploy as a background service)")
    print("=" * 65 + "\n")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\nScheduler stopped by user.")


if __name__ == "__main__":
    start_scheduler()
