"""
tools/email_sender.py - Tool 6: send_job_email()
Composes responsive HTML job digest emails, highlights High & Medium priority openings,
attaches jobs.xlsx, and sends via Gmail SMTP (App Password) or Google OAuth2.
Includes dry-run preview mode.
"""

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()


def generate_email_html(
    jobs: List[Dict[str, Any]],
    recipient_name: str = "Job Seeker",
    date_str: Optional[str] = None
) -> str:
    """
    Constructs a modern, responsive HTML email digest for job notifications.
    """
    if not date_str:
        date_str = datetime.now().strftime("%B %d, %Y")

    total_jobs = len(jobs)
    high_priority_jobs = [j for j in jobs if j.get("priority") == "High"]
    medium_priority_jobs = [j for j in jobs if j.get("priority") == "Medium"]
    low_priority_jobs = [j for j in jobs if j.get("priority") == "Low"]

    # Render job card HTML
    def render_card(job: Dict[str, Any], is_high: bool = False) -> str:
        score = job.get('match_score', 5)
        border_color = "#28A745" if is_high else "#007BFF"
        badge_bg = "#28A745" if is_high else "#FFC107"
        badge_text_color = "#FFFFFF" if is_high else "#212529"
        priority_label = "🔥 HIGH PRIORITY" if is_high else "⭐ MEDIUM PRIORITY"
        if not is_high and job.get("priority") == "Low":
            badge_bg = "#6C757D"
            priority_label = "LOW PRIORITY"

        apply_url = job.get('apply_link') or job.get('original_url') or '#'
        desc = job.get('job_description') or job.get('job_description_snippet') or ''
        desc_clean = desc[:280].strip()
        if len(desc) > 280:
            desc_clean += "..."

        salary_display = job.get('salary', 'Negotiable')
        skills = job.get('required_skills', '')
        skills_badge = f"""<div style="margin-top: 8px; font-size: 12px; color: #495057;"><strong>Skills:</strong> {skills[:120]}</div>""" if skills else ""

        return f"""
        <div style="background-color: #ffffff; border-radius: 8px; border-left: 6px solid {border_color}; padding: 18px 20px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.06);">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                <div>
                    <span style="background-color: {badge_bg}; color: {badge_text_color}; font-size: 11px; font-weight: bold; padding: 3px 8px; border-radius: 4px; text-transform: uppercase;">{priority_label}</span>
                    <span style="background-color: #EBF3FB; color: #1F4E79; font-size: 11px; font-weight: bold; padding: 3px 8px; border-radius: 4px; margin-left: 6px;">Score: {score}/10</span>
                </div>
            </div>
            <h3 style="margin: 6px 0 4px 0; color: #1F4E79; font-size: 18px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">
                <a href="{apply_url}" style="color: #1F4E79; text-decoration: none;">{job.get('job_title', 'Tech Position')}</a>
            </h3>
            <div style="color: #495057; font-size: 14px; font-weight: 600; margin-bottom: 6px;">
                🏢 {job.get('company_name', 'Company')} | 📍 {job.get('location', 'Bangladesh')}
            </div>
            <div style="color: #6C757D; font-size: 13px; margin-bottom: 10px;">
                💰 <strong>Salary:</strong> {salary_display} | ⏳ <strong>Deadline:</strong> {job.get('deadline', job.get('application_deadline', 'N/A'))}
            </div>
            <div style="background-color: #F8F9FA; border-radius: 6px; padding: 10px 12px; font-size: 13px; color: #333333; line-height: 1.5; margin-bottom: 12px;">
                <strong>Reason:</strong> {job.get('match_reason', 'Matches tech profile.')}<br>
                <span style="color: #555555;">{desc_clean}</span>
            </div>
            {skills_badge}
            <div style="margin-top: 14px;">
                <a href="{apply_url}" target="_blank" style="display: inline-block; background-color: #1F4E79; color: #ffffff; text-decoration: none; font-size: 13px; font-weight: bold; padding: 8px 18px; border-radius: 5px;">
                    Apply on Bdjobs &rarr;
                </a>
                <a href="{job.get('original_url', '#')}" target="_blank" style="display: inline-block; margin-left: 10px; color: #1F4E79; text-decoration: underline; font-size: 13px;">
                    View Circular
                </a>
            </div>
        </div>
        """

    high_cards = "\n".join(render_card(j, is_high=True) for j in high_priority_jobs) if high_priority_jobs else "<p style='color:#6c757d; font-style:italic;'>No High Priority jobs found in this run.</p>"
    med_cards = "\n".join(render_card(j, is_high=False) for j in medium_priority_jobs) if medium_priority_jobs else ""
    low_cards = "\n".join(render_card(j, is_high=False) for j in low_priority_jobs) if low_priority_jobs else ""

    content_section = f"""
    <div style="margin-bottom: 25px;">
        <h2 style="color: #28A745; font-size: 16px; border-bottom: 2px solid #28A745; padding-bottom: 6px; margin-top: 25px;">
            🌟 Top Picks: High Priority Jobs ({len(high_priority_jobs)})
        </h2>
        {high_cards}
    </div>
    """

    if medium_priority_jobs:
        content_section += f"""
        <div style="margin-bottom: 25px;">
            <h2 style="color: #007BFF; font-size: 16px; border-bottom: 2px solid #007BFF; padding-bottom: 6px; margin-top: 25px;">
                ⭐ Medium Priority Opportunities ({len(medium_priority_jobs)})
            </h2>
            {med_cards}
        </div>
        """

    if not jobs:
        content_section = """
        <div style="background-color: #F8F9FA; border-radius: 8px; padding: 25px; text-align: center; color: #6C757D;">
            <h3>No New Tech Jobs Found Today</h3>
            <p>YourFindJob scanned all configured tech keywords on Bdjobs, but there are no new listings matching your profile today. We will run again tomorrow morning!</p>
        </div>
        """

    html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YourFindJob Daily Digest</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #F4F6F9; margin: 0; padding: 20px;">
    <div style="max-width: 680px; margin: 0 auto; background-color: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.08);">
        
        <!-- Header Banner -->
        <div style="background: linear-gradient(135deg, #1F4E79 0%, #0D233A 100%); color: #ffffff; padding: 30px 25px; text-align: center;">
            <h1 style="margin: 0; font-size: 26px; letter-spacing: 0.5px;">YourFindJob</h1>
            <p style="margin: 6px 0 0 0; font-size: 14px; opacity: 0.85;">Your Personal AI Job Hunting Assistant • Bangladesh Tech Digest</p>
            <div style="margin-top: 15px; font-size: 13px; background-color: rgba(255,255,255,0.15); display: inline-block; padding: 4px 14px; border-radius: 20px;">
                📅 {date_str}
            </div>
        </div>

        <!-- Metric Badges -->
        <div style="background-color: #EBF3FB; padding: 15px 25px; border-bottom: 1px solid #D6E4F0;">
            <table width="100%" cellpadding="0" cellspacing="0" style="text-align: center;">
                <tr>
                    <td width="33%">
                        <div style="font-size: 22px; font-weight: bold; color: #1F4E79;">{total_jobs}</div>
                        <div style="font-size: 12px; color: #555555; text-transform: uppercase;">Total Found</div>
                    </td>
                    <td width="33%" style="border-left: 1px solid #C4D7E8; border-right: 1px solid #C4D7E8;">
                        <div style="font-size: 22px; font-weight: bold; color: #28A745;">{len(high_priority_jobs)}</div>
                        <div style="font-size: 12px; color: #555555; text-transform: uppercase;">High Priority</div>
                    </td>
                    <td width="33%">
                        <div style="font-size: 22px; font-weight: bold; color: #007BFF;">{len(medium_priority_jobs)}</div>
                        <div style="font-size: 12px; color: #555555; text-transform: uppercase;">Medium Priority</div>
                    </td>
                </tr>
            </table>
        </div>

        <!-- Greeting & Content -->
        <div style="padding: 25px;">
            <p style="font-size: 15px; color: #333333; margin-top: 0;">
                Hello <strong>{recipient_name}</strong>,<br>
                Here is your daily curated summary of the latest Technology and Software jobs posted on Bdjobs. All listings have been scored according to your preferred tech stack and career profile.
            </p>

            {content_section}

            <!-- Attachment Notice -->
            <div style="margin-top: 30px; padding: 15px; background-color: #E8F4FD; border: 1px solid #B8DAFF; border-radius: 8px; text-align: center;">
                <p style="margin: 0; font-size: 14px; color: #004085;">
                    📎 <strong>Full Database Attached:</strong> Complete listings, match reasons, and apply links have been exported to the attached <code>jobs.xlsx</code> file.
                </p>
            </div>
        </div>

        <!-- Footer -->
        <div style="background-color: #F8F9FA; padding: 20px; text-align: center; border-top: 1px solid #E9ECEF; font-size: 12px; color: #6C757D;">
            <p style="margin: 0 0 5px 0;">This email was automatically generated and delivered by <strong>YourFindJob</strong>.</p>
            <p style="margin: 0;">Only sent to your configured email. Never applies on your behalf.</p>
        </div>

    </div>
</body>
</html>
"""
    return html_template


def send_email_smtp(
    subject: str,
    html_content: str,
    recipient_email: str,
    sender_email: str,
    app_password: str,
    attachment_path: Optional[str] = None
) -> bool:
    """Sends email via standard Gmail TLS SMTP (Port 587)."""
    msg = MIMEMultipart("mixed")
    msg["From"] = f"YourFindJob Assistant <{sender_email}>"
    msg["To"] = recipient_email
    msg["Subject"] = subject

    # Attach HTML body
    body_part = MIMEText(html_content, "html", "utf-8")
    msg.attach(body_part)

    # Attach Excel file
    if attachment_path and os.path.exists(attachment_path):
        filename = os.path.basename(attachment_path)
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={filename}")
        msg.attach(part)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(sender_email, app_password)
        server.send_message(msg)

    return True


def send_job_email(
    jobs: List[Dict[str, Any]],
    recipient_email: str,
    recipient_name: str = "Job Seeker",
    excel_path: Optional[str] = "data/jobs.xlsx",
    dry_run: bool = False,
    logger=None
) -> bool:
    """
    Main email delivery dispatcher. Handles dry-run preview and actual email dispatch.
    """
    def log(msg: str):
        if logger:
            if hasattr(logger, "info"):
                logger.info(msg)
            elif callable(logger):
                logger(msg)
            else:
                print(msg)

    today_str = datetime.now().strftime("%Y-%m-%d")
    subject = f"YourFindJob - Daily Tech Job Updates - {today_str}"
    html_content = generate_email_html(jobs, recipient_name=recipient_name)

    # Save HTML preview to data folder for easy local inspection
    preview_file = "data/email_preview.html"
    os.makedirs(os.path.dirname(preview_file), exist_ok=True)
    with open(preview_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    if dry_run:
        log("[DRY-RUN] Email generated successfully. Skipping external SMTP send.")
        log(f"[DRY-RUN] Preview saved to: {preview_file}")
        log(f"[DRY-RUN] Subject: {subject}")
        log(f"[DRY-RUN] Recipient: {recipient_email}")
        log(f"[DRY-RUN] Total Jobs: {len(jobs)} | Attachment: {excel_path}")
        return True

    # Real Send Mode
    sender_email = os.getenv("GMAIL_SENDER_EMAIL", "").strip()
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()

    if not sender_email or not app_password or "your_" in app_password.lower() or len(app_password) < 8:
        log("Warning: Valid GMAIL_SENDER_EMAIL or GMAIL_APP_PASSWORD not configured in .env.")
        log("Skipping actual outbound email delivery. You can inspect the email at data/email_preview.html.")
        return False

    try:
        log(f"Sending daily notification email to {recipient_email}...")
        send_email_smtp(
            subject=subject,
            html_content=html_content,
            recipient_email=recipient_email,
            sender_email=sender_email,
            app_password=app_password,
            attachment_path=excel_path
        )
        log("Email sent successfully!")
        return True
    except Exception as e:
        log(f"Failed to send email via Gmail SMTP: {e}")
        return False
