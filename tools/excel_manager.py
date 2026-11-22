"""
tools/excel_manager.py - Tool 5: save_job_to_excel()
Manages creation, styling, and non-destructive appending of jobs in jobs.xlsx.
Includes bold colored headers, auto-filters, frozen header pane, clickable hyperlinks,
priority highlighting, and auto-adjusted column widths.
"""

import os
from datetime import datetime
from typing import List, Dict, Any
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

COLUMNS = [
    "Serial Number",
    "Job Title",
    "Company Name",
    "Job Category",
    "Location",
    "Salary",
    "Experience Required",
    "Required Skills",
    "Job Posting Date",
    "Application Deadline",
    "Job Match Score",
    "Priority",
    "Match Reason",
    "Job Description Summary",
    "Original Job Link",
    "Apply Link",
    "Date Found",
    "Status"
]

# Color Schemes
HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

PRIORITY_STYLES = {
    "High": {
        "fill": PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid"),
        "font": Font(name="Calibri", size=10, bold=True, color="375623")
    },
    "Medium": {
        "fill": PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"),
        "font": Font(name="Calibri", size=10, bold=True, color="7F6000")
    },
    "Low": {
        "fill": PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid"),
        "font": Font(name="Calibri", size=10, color="595959")
    }
}

DATA_FONT = Font(name="Calibri", size=10, color="000000")
LINK_FONT = Font(name="Calibri", size=10, color="0563C1", underline="single")
THIN_BORDER = Border(
    left=Side(style="thin", color="D9D9D9"),
    right=Side(style="thin", color="D9D9D9"),
    top=Side(style="thin", color="D9D9D9"),
    bottom=Side(style="thin", color="D9D9D9")
)


def get_or_create_workbook(file_path: str):
    """Opens existing workbook or creates a brand new one with standard headers."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    if os.path.exists(file_path):
        try:
            wb = openpyxl.load_workbook(file_path)
            ws = wb.active
            return wb, ws
        except Exception:
            pass

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tech Jobs"

    # Write Header Row
    for col_idx, col_name in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)
        cell.border = THIN_BORDER

    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"
    return wb, ws


def save_jobs_to_excel(
    jobs: List[Dict[str, Any]],
    file_path: str = "data/jobs.xlsx",
    logger=None
) -> int:
    """
    Appends newly discovered jobs to jobs.xlsx without altering existing entries.
    Strictly verifies that:
    1. Only jobs with an available application deadline are written.
    2. Any job already present in Excel (matched by URL, Job ID, or Company+Title) is skipped.

    Returns:
        Number of jobs written
    """
    import re

    def log(msg: str):
        if logger:
            if hasattr(logger, "info"):
                logger.info(msg)
            elif callable(logger):
                logger(msg)
            else:
                print(msg)

    if not jobs:
        log("No new jobs to write to Excel.")
        return 0

    wb, ws = get_or_create_workbook(file_path)

    # 1. Inspect existing rows to ensure strict duplicate prevention
    existing_urls = set()
    existing_signatures = set()
    existing_ids = set()

    for r in range(2, ws.max_row + 1):
        t_val = str(ws.cell(row=r, column=2).value or "").strip().lower()
        c_val = str(ws.cell(row=r, column=3).value or "").strip().lower()
        orig_u = str(ws.cell(row=r, column=15).value or "").strip()
        appl_u = str(ws.cell(row=r, column=16).value or "").strip()

        for u_val in [orig_u, appl_u]:
            if not u_val:
                continue
            url_match = re.search(r'https?://[^\",\s]+', u_val)
            if url_match:
                found_url = url_match.group(0)
                existing_urls.add(found_url)
                m = re.search(r'(?:details/|id=)(\d+)', found_url)
                if m:
                    existing_ids.add(m.group(1))
            elif u_val.startswith('http'):
                existing_urls.add(u_val)
                m = re.search(r'(?:details/|id=)(\d+)', u_val)
                if m:
                    existing_ids.add(m.group(1))

        if t_val and c_val:
            c_norm = re.sub(r'[^a-z0-9]', '', c_val)
            t_norm = re.sub(r'[^a-z0-9]', '', t_val)
            if c_norm and t_norm:
                existing_signatures.add(f"{c_norm}::{t_norm}")

    # Calculate starting serial number and next row
    existing_rows = ws.max_row
    next_serial = 1
    if existing_rows > 1:
        # Read last serial number if available
        last_val = ws.cell(row=existing_rows, column=1).value
        try:
            next_serial = int(last_val) + 1
        except Exception:
            next_serial = existing_rows

    written_count = 0
    current_row = existing_rows + 1

    for job in jobs:
        # Check deadline availability: Only deadline available job allowed
        deadline = job.get('application_deadline') or job.get('deadline') or ''
        deadline_str = str(deadline).strip()
        if not deadline_str or deadline_str.lower() in ['', 'n/a', 'none', 'not stated']:
            log(f"Skipping job without available deadline for Excel: '{job.get('job_title')}'")
            continue

        jid = str(job.get('job_id', '')).strip()
        orig_url = str(job.get('original_url', '')).strip()
        apply_url = str(job.get('apply_link') or orig_url).strip()
        company_name = str(job.get('company_name', '')).strip()
        job_title = str(job.get('job_title', '')).strip()

        c_norm = re.sub(r'[^a-z0-9]', '', company_name.lower())
        t_norm = re.sub(r'[^a-z0-9]', '', job_title.lower())
        sig = f"{c_norm}::{t_norm}" if c_norm and t_norm else ""

        # Strict duplicate check against existing Excel data
        if (jid and jid in existing_ids) or \
           (orig_url and orig_url in existing_urls) or \
           (apply_url and apply_url in existing_urls) or \
           (sig and sig in existing_signatures):
            log(f"Skipping duplicate job in Excel: '{job_title}' at '{company_name}'")
            continue

        # Prepare row values
        serial_no = next_serial
        job_category = job.get('job_category', 'Software Development')
        location = job.get('location', '')
        salary = job.get('salary', 'Negotiable')
        experience = job.get('experience_level') or job.get('experience', 'Not specified')
        required_skills = job.get('required_skills', '')
        posting_date = job.get('job_posting_date') or job.get('publish_date', '')
        match_score = int(job.get('match_score', 5))
        priority = job.get('priority', 'Medium')
        match_reason = job.get('match_reason', '')
        
        # Snippet or summary
        desc = job.get('job_description') or job.get('job_description_snippet', '')
        desc_summary = desc[:250].replace('\n', ' ').strip()
        if len(desc) > 250:
            desc_summary += "..."

        date_found = job.get('date_found') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        status = job.get('status', 'New')

        row_data = [
            serial_no,
            job_title,
            company_name,
            job_category,
            location,
            salary,
            experience,
            required_skills,
            posting_date,
            deadline_str,
            match_score,
            priority,
            match_reason,
            desc_summary,
            orig_url,
            apply_url,
            date_found,
            status
        ]

        # Write cells
        for col_idx, val in enumerate(row_data, 1):
            cell = ws.cell(row=current_row, column=col_idx)
            cell.font = DATA_FONT
            cell.border = THIN_BORDER
            cell.alignment = Alignment(vertical="center")

            # Alignment and formatting specifics
            if col_idx == 1:  # Serial
                cell.value = val
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx == 11:  # Match Score
                cell.value = val
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx == 12:  # Priority
                cell.value = val
                cell.alignment = Alignment(horizontal="center", vertical="center")
                style = PRIORITY_STYLES.get(priority, PRIORITY_STYLES["Medium"])
                cell.fill = style["fill"]
                cell.font = style["font"]
            elif col_idx in (15, 16):  # Hyperlinks
                if val and val.startswith("http"):
                    label = "View Circular" if col_idx == 15 else "Apply Online"
                    cell.value = f'=HYPERLINK("{val}", "{label}")'
                    cell.font = LINK_FONT
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                else:
                    cell.value = val
            else:
                cell.value = val

        ws.row_dimensions[current_row].height = 22

        # Register in existing sets so subsequent items in this run also don't duplicate
        if jid:
            existing_ids.add(jid)
        if orig_url:
            existing_urls.add(orig_url)
        if apply_url:
            existing_urls.add(apply_url)
        if sig:
            existing_signatures.add(sig)

        current_row += 1
        next_serial += 1
        written_count += 1

    # Auto-adjust column widths
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            val_str = str(cell.value or '')
            if cell.value and str(cell.value).startswith('=HYPERLINK'):
                val_str = "Apply Online"
            max_len = max(max_len, len(val_str))
        ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 40)

    # Enable Auto Filter over the complete populated data table
    ws.auto_filter.ref = ws.dimensions

    try:
        wb.save(file_path)
        log(f"[Excel Success] Saved {written_count} jobs to Excel file: {file_path}")
    except PermissionError:
        fallback_path = file_path.replace(".xlsx", "_latest.xlsx")
        wb.save(fallback_path)
        log(f"[Excel Warning] {file_path} is currently locked/open in another program. Successfully saved {written_count} jobs to fallback: {fallback_path}")
    except Exception as e:
        log(f"[Excel Error] Failed to save Excel file: {e}")

    return written_count


if __name__ == "__main__":
    sample_jobs = [{
        'job_id': '9999999',
        'job_title': 'Junior Python Developer',
        'company_name': 'Tech Corp BD',
        'job_category': 'Software Development',
        'location': 'Dhaka (Gulshan)',
        'salary': 'Tk. 35000 - 45000 (Monthly)',
        'experience_level': '0 to 2 years',
        'required_skills': 'Python, Django, PostgreSQL, Git',
        'job_posting_date': '2026-11-20',
        'application_deadline': '2026-12-15',
        'match_score': 9,
        'priority': 'High',
        'match_reason': 'Direct match with Python career interest and junior level.',
        'job_description': 'Building REST APIs using Python and Django.',
        'original_url': 'https://bdjobs.com/h/details/9999999?ln=1',
        'apply_link': 'https://bdjobs.com/h/details/9999999?ln=1',
        'date_found': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'status': 'Active'
    }]
    save_jobs_to_excel(sample_jobs, "data/test_jobs.xlsx")
    print("Test Excel created successfully.")
