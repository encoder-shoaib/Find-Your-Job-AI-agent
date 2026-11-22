"""
tools/job_details.py - Tool 2: read_job_details()
Reads and extracts comprehensive details for a specific Bdjobs circular.
Cleans HTML into readable plain text, bounded to maximum 8,000 characters.
"""

import re
import html
from typing import Dict, Any, Optional
import requests

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://jobs.bdjobs.com',
    'Referer': 'https://jobs.bdjobs.com/',
}

DETAILS_API_ENDPOINT = "https://api.bdjobs.com/jobs/api/v1/JobSubsystem/jobDetails"
MAX_CHARS = 8000


def clean_html(raw_html: Optional[str]) -> str:
    """Sanitizes HTML tags into clean, human-readable text."""
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    text = re.sub(r'</?(p|div|section|article)[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>', '• ', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</?(ul|ol)[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    lines = [l.strip() for l in text.splitlines()]
    cleaned = "\n".join(l for l in lines if l)
    return cleaned.strip()


def extract_job_id(url_or_id: str) -> str:
    """Extracts numeric Job ID from URL or string."""
    if not url_or_id:
        return ""
    url_or_id = str(url_or_id).strip()
    # Check if purely digits
    if url_or_id.isdigit():
        return url_or_id
    # Check pattern like /details/1558619 or id=1558619
    match = re.search(r'(?:details/|id=)(\d+)', url_or_id)
    if match:
        return match.group(1)
    # Check any sequence of 6-8 digits
    match2 = re.search(r'\b(\d{6,8})\b', url_or_id)
    if match2:
        return match2.group(1)
    return url_or_id


def read_job_details(job_id_or_url: str, logger=None) -> Dict[str, Any]:
    """
    Fetches full details for a given Bdjobs posting.

    Args:
        job_id_or_url: The Job ID (e.g. '1558619') or full Bdjobs URL
        logger: Optional logging callback

    Returns:
        Dictionary containing detailed, sanitized job specifications
    """
    job_id = extract_job_id(job_id_or_url)
    def log(msg: str):
        if logger:
            if hasattr(logger, "info"):
                logger.info(msg)
            elif callable(logger):
                logger(msg)
            else:
                print(msg)

    if not job_id:
        return {"error": "Invalid or missing Job ID", "job_id": job_id_or_url}

    log(f"Fetching full job details for Job ID: {job_id}...")

    params = {'jobId': job_id, 'ln': 1}
    try:
        response = requests.get(DETAILS_API_ENDPOINT, headers=DEFAULT_HEADERS, params=params, timeout=12)
        if response.status_code != 200:
            log(f"Warning: Failed to fetch details for {job_id}, status {response.status_code}")
            return {"error": f"HTTP {response.status_code}", "job_id": job_id}

        data_json = response.json()
        job_list = data_json.get('data', [])
        if not job_list:
            return {"error": "Job details not found in API response", "job_id": job_id}

        item = job_list[0]

        # Extract and clean all required fields
        job_title = item.get('JobTitle', '').strip()
        company_name = item.get('CompnayName') or item.get('CompanyNameENG', '')
        company_name = company_name.strip()
        job_desc_raw = item.get('JobDescription', '')
        job_key_points_raw = item.get('JobKeyPoints', '')
        context_raw = item.get('Context', '')

        # Combined job description
        desc_parts = []
        if job_key_points_raw:
            desc_parts.append(clean_html(job_key_points_raw))
        if context_raw:
            desc_parts.append(clean_html(context_raw))
        if job_desc_raw:
            desc_parts.append(clean_html(job_desc_raw))
        full_description = "\n\n".join(p for p in desc_parts if p)

        edu_requirements = clean_html(item.get('EducationRequirements', ''))
        exp_requirements = clean_html(item.get('experience', ''))
        add_requirements = clean_html(item.get('AdditionJobRequirements', ''))
        skills_required = item.get('SkillsRequired', '').strip()
        suggested_skills = item.get('SuggestedSkills', '').strip()

        combined_skills = []
        if skills_required:
            combined_skills.append(skills_required)
        if suggested_skills and suggested_skills not in skills_required:
            combined_skills.append(suggested_skills)
        all_skills = ", ".join(combined_skills)

        location = item.get('JobLocation', '').strip()
        salary = item.get('JobSalaryRangeText') or item.get('JobSalaryRange', '')
        salary = salary.strip() if salary and salary != '--' else 'Negotiable'
        employment_type = item.get('JobNature', 'Full Time').strip()
        deadline = item.get('Deadline', '').strip()
        posted_on = item.get('PostedOn', '').strip()

        # URLs
        original_url = f"https://bdjobs.com/h/details/{job_id}?ln=1"
        apply_url = item.get('ApplyURL') or item.get('ApplyRedirectUrl') or original_url
        if apply_url.startswith('//'):
            apply_url = 'https:' + apply_url

        # Cap description to maximum 8,000 characters
        if len(full_description) > MAX_CHARS:
            full_description = full_description[:MAX_CHARS] + "\n...[truncated to 8,000 characters]"

        details = {
            'job_id': job_id,
            'job_title': job_title,
            'company_name': company_name,
            'job_description': full_description,
            'educational_requirements': edu_requirements,
            'experience_requirements': exp_requirements,
            'additional_requirements': add_requirements,
            'required_skills': all_skills,
            'location': location,
            'salary': salary,
            'employment_type': employment_type,
            'application_deadline': deadline,
            'job_posting_date': posted_on,
            'original_url': original_url,
            'apply_link': apply_url,
            'status': 'Active'
        }

        log(f"Successfully retrieved details for: {job_title} at {company_name}")
        return details

    except Exception as e:
        log(f"Exception reading details for {job_id}: {e}")
        return {"error": str(e), "job_id": job_id}


if __name__ == "__main__":
    # Test reading details for sample Job ID
    sample_id = "1558619"
    res = read_job_details(sample_id)
    print("Parsed Job Details:")
    for k, v in res.items():
        if k == 'job_description':
            print(f" - {k}: {repr(v[:100])}...")
        else:
            print(f" - {k}: {v}")
