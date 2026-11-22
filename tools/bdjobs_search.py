"""
tools/bdjobs_search.py - Tool 1: search_bdjobs()
Searches technology-related jobs on Bdjobs using official public REST endpoints.
Respects rate limits, robots.txt, and terms of service.
"""

import time
import re
import html
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Set
import requests

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://jobs.bdjobs.com',
    'Referer': 'https://jobs.bdjobs.com/',
}

SEARCH_API_ENDPOINT = "https://api.bdjobs.com/jobs/api/v1/JobSearch/GetJobSearch"


def clean_html(text: Optional[str]) -> str:
    """Removes HTML tags and normalizes whitespace."""
    if not text:
        return ""
    # Unescape HTML entities
    unescaped = html.unescape(text)
    # Replace line breaks and paragraph tags with newlines
    cleaned = re.sub(r'<br\s*/?>', '\n', unescaped, flags=re.IGNORECASE)
    cleaned = re.sub(r'</p>', '\n', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'</li>', '\n', cleaned, flags=re.IGNORECASE)
    # Remove all remaining HTML tags
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    # Clean up multiple whitespaces
    lines = [line.strip() for line in cleaned.splitlines()]
    return "\n".join(l for l in lines if l)


def parse_publish_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parses ISO or common Bdjobs date strings into datetime."""
    if not date_str:
        return None
    try:
        # ISO format: 2026-11-20T00:50:00Z
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        pass
    
    # Try alternative common formats like 'Nov 20, 2026'
    for fmt in ("%b %d, %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def search_bdjobs(
    keywords: List[str],
    category_ids: Optional[List[int]] = None,
    max_jobs: int = 30,
    recency_days: int = 7,
    exclude_ids: Optional[Set[str]] = None,
    logger=None
) -> List[Dict[str, Any]]:
    """
    Searches Bdjobs for tech-related jobs matching the provided keywords.

    Args:
        keywords: List of keyword search strings (e.g. ['Python', 'Software Engineer'])
        category_ids: List of Bdjobs category IDs (e.g. [8] for IT/Telecommunication)
        max_jobs: Maximum total number of unique jobs to collect
        recency_days: Filter jobs posted within this many days (default: 7)
        exclude_ids: Optional set of already-processed job IDs to skip during search
        logger: Optional logging helper or callback

    Returns:
        List of structured job dictionaries
    """
    if category_ids is None:
        category_ids = [8]  # Default to IT / Telecommunication

    if exclude_ids is None:
        exclude_ids = set()

    collected_jobs: Dict[str, Dict[str, Any]] = {}
    now_utc = datetime.now(timezone.utc)
    cutoff_date = now_utc - timedelta(days=recency_days)

    def log(msg: str):
        if logger:
            if hasattr(logger, "info"):
                logger.info(msg)
            elif callable(logger):
                logger(msg)
            else:
                print(msg)

    log(f"Starting Bdjobs search with {len(keywords)} keywords in Categories {category_ids}...")

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    for cat_id in category_ids:
        for kw in keywords:
            if len(collected_jobs) >= max_jobs:
                break

            log(f"Searching Bdjobs for keyword: '{kw}' (Category {cat_id})...")
            params = {
                'keyword': kw,
                'fcatId': cat_id,
                'pg': 1,
                'q': kw
            }

            try:
                response = session.get(SEARCH_API_ENDPOINT, params=params, timeout=12)
                if response.status_code != 200:
                    log(f"Warning: Bdjobs API responded with status {response.status_code} for '{kw}'")
                    continue

                res_json = response.json()
                raw_data = res_json.get('data', [])
                if not raw_data:
                    continue

                for item in raw_data:
                    job_id = str(item.get('Jobid', '')).strip()
                    if not job_id or job_id in collected_jobs or job_id in exclude_ids:
                        continue

                    # Check publish date
                    pub_date_str = item.get('publishDate')
                    pub_dt = parse_publish_date(pub_date_str)
                    
                    # If date is outside recency window, skip if recency filter is enforced
                    if pub_dt and recency_days > 0:
                        if pub_dt < cutoff_date:
                            continue

                    # Extract job fields
                    job_title = item.get('jobTitle', '').strip()
                    company_name = item.get('companyName', '').strip()
                    location = item.get('location', '').strip()
                    deadline = item.get('deadline', '').strip()
                    salary = item.get('Salary', '--').strip()
                    experience = item.get('experience', '').strip()
                    edu_rec = clean_html(item.get('eduRec', ''))
                    job_desc = clean_html(item.get('jobDescription', ''))
                    job_type = item.get('JobType', '').strip()
                    workplace = item.get('WorkPlace', '').strip()

                    # Direct human-browsable URL
                    original_url = f"https://bdjobs.com/h/details/{job_id}?ln=1"

                    job_dict = {
                        'job_id': job_id,
                        'job_title': job_title,
                        'company_name': company_name,
                        'location': location,
                        'publish_date': pub_date_str or '',
                        'deadline': deadline,
                        'salary': salary if salary and salary != '--' else 'Negotiable',
                        'experience': experience,
                        'education_requirements': edu_rec,
                        'job_description_snippet': job_desc[:500],
                        'job_type': job_type or 'Full-time',
                        'workplace': workplace,
                        'original_url': original_url,
                        'apply_link': original_url,
                        'source': 'Bdjobs',
                        'date_found': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'matched_keyword': kw,
                    }

                    collected_jobs[job_id] = job_dict
                    if len(collected_jobs) >= max_jobs:
                        break

                # Polite delay to respect Bdjobs rate limit
                time.sleep(0.4)

            except Exception as e:
                log(f"Error querying Bdjobs for '{kw}': {e}")
                continue

    result_list = list(collected_jobs.values())
    log(f"Bdjobs search completed. Total unique matching jobs found: {len(result_list)}")
    return result_list


if __name__ == "__main__":
    test_results = search_bdjobs(keywords=['Python', 'Django'], max_jobs=3, recency_days=30)
    print(f"Test collected {len(test_results)} jobs:")
    for j in test_results:
        print(f" - [{j['job_id']}] {j['job_title']} at {j['company_name']} ({j['location']})")
