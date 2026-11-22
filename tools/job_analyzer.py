"""
tools/job_analyzer.py - Tool 4: analyze_job_match()
Evaluates job match using OpenAI GPT (structured evaluation) with an expert
deterministic scoring engine as fallback.
Strictly adheres to the 1-10 scoring rubric:
- Career Interest: 3 Points
- Required Skills Match: 3 Points
- Experience Level Match: 2 Points
- Job Type and Location: 1 Point
- Recency: 1 Point
"""

import os
import json
import re
from datetime import datetime
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()


def deterministic_score(job: Dict[str, Any], user_profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluates job compatibility against user profile using the exact 10-point rubric.
    Never hallucinates; marks confidence 'Low' and notes 'Needs human review' if details are sparse.
    """
    job_title = job.get('job_title', '').lower()
    job_desc = (job.get('job_description', '') + " " + job.get('educational_requirements', '') + " " + job.get('additional_requirements', '')).lower()
    skills_text = (job.get('required_skills', '') + " " + job_desc).lower()
    exp_text = (job.get('experience_requirements', '') or job.get('experience', '')).lower()
    location_text = (job.get('location', '') + " " + job.get('workplace', '')).lower()
    job_type_text = job.get('employment_type', job.get('job_type', '')).lower()

    # 1. Career Interest Match (0 to 3 points)
    interest_score = 0.0
    pref_cats = [c.lower() for c in user_profile.get('preferred_categories', ['software development', 'ai', 'data science', 'it'])]
    
    # Check title keywords
    target_roles = [
        'software engineer', 'developer', 'python', 'django', 'backend', 'frontend',
        'full stack', 'web developer', 'ai engineer', 'machine learning', 'data analyst',
        'data scientist', 'devops', 'cloud', 'mobile', 'flutter', 'react', 'node'
    ]
    matched_role = False
    for r in target_roles:
        if r in job_title:
            matched_role = True
            break
            
    if matched_role:
        interest_score = 3.0
    elif any(cat in job_title or cat in job_desc for cat in ['software', 'programming', 'technology', 'engineer', 'it officer', 'data']):
        interest_score = 2.0
    elif any(cat in job_desc for cat in pref_cats):
        interest_score = 1.0
    else:
        interest_score = 0.5

    # 2. Required Skills Match (0 to 3 points)
    pref_skills = [s.lower() for s in user_profile.get('preferred_skills', ['python', 'javascript', 'react', 'django', 'html', 'css', 'sql', 'ai', 'machine learning'])]
    matched_skills = []
    for s in pref_skills:
        # Regex word boundary match
        pattern = r'\b' + re.escape(s) + r'\b'
        if re.search(pattern, skills_text):
            matched_skills.append(s.title())

    skills_count = len(matched_skills)
    if skills_count >= 3:
        skills_score = 3.0
    elif skills_count == 2:
        skills_score = 2.0
    elif skills_count == 1:
        skills_score = 1.2
    else:
        skills_score = 0.0

    # 3. Experience Level Match (0 to 2 points)
    exp_score = 1.0
    target_exp_levels = [e.lower() for e in user_profile.get('experience_level', ['entry level', 'fresher', 'junior'])]
    
    # Check for fresher or junior
    if any(k in job_title or k in exp_text for k in ['fresher', 'junior', 'entry', 'intern', '0 to 1', '0 to 2', 'at most 1', 'at most 2']):
        exp_score = 2.0
    elif any(k in exp_text for k in ['1 to 3', '2 to 3', 'at least 1', 'at least 2']):
        exp_score = 1.5
    elif any(k in exp_text for k in ['3 to 5', '4 to 6', '5 to 10', 'senior', 'lead', 'head']):
        exp_score = 0.5
    elif 'na' in exp_text or not exp_text.strip():
        exp_score = 1.0  # unspecified

    # 4. Job Type & Location Match (0 to 1 point)
    loc_score = 0.0
    pref_locs = [l.lower() for l in user_profile.get('preferred_job_locations', ['dhaka', 'remote', 'anywhere in bangladesh'])]
    
    loc_matched = any(l in location_text for l in pref_locs) or 'dhaka' in location_text or 'bangladesh' in location_text or 'remote' in location_text
    type_matched = any(t.lower() in job_type_text for t in user_profile.get('preferred_job_types', ['full-time', 'remote']))

    if loc_matched and type_matched:
        loc_score = 1.0
    elif loc_matched or type_matched:
        loc_score = 0.7
    else:
        loc_score = 0.3

    # 5. Job Recency (0 to 1 point)
    recency_score = 0.5
    pub_date_str = job.get('job_posting_date') or job.get('publish_date') or ''
    if pub_date_str:
        recency_score = 1.0  # Already filtered to active within threshold

    total_score = round(interest_score + skills_score + exp_score + loc_score + recency_score)
    total_score = max(1, min(10, total_score))

    # Priority determination
    if total_score >= 7:
        priority = "High"
    elif total_score >= 5:
        priority = "Medium"
    else:
        priority = "Low"

    # Confidence check
    confidence = "High"
    notes = "Match evaluated based on full job description."
    if not job.get('job_description') or len(job.get('job_description', '')) < 50:
        confidence = "Low"
        notes = "Needs human review: job description is brief or omitted."

    # Recommendation
    if priority == "High":
        recommendation = "Strongly Recommended: High alignment with technical skillset and career level."
    elif priority == "Medium":
        recommendation = "Recommended: Good alignment, review specific role requirements."
    else:
        recommendation = "Optional: Lower alignment with current preferences."

    reason_parts = []
    if interest_score >= 2.0:
        reason_parts.append("Direct match with preferred tech career domain")
    if matched_skills:
        reason_parts.append(f"Matching skills: {', '.join(matched_skills[:4])}")
    if exp_score >= 1.5:
        reason_parts.append("Favorable experience requirements")
    if not reason_parts:
        reason_parts.append("General technology listing")

    match_reason = ". ".join(reason_parts) + "."

    # Category determination
    job_category = "Software Development"
    if any(k in job_title for k in ['ai', 'machine learning', 'data', 'prompt', 'deep learning']):
        job_category = "AI & Data"
    elif any(k in job_title for k in ['network', 'system', 'it officer', 'devops', 'cloud', 'support']):
        job_category = "IT & Networking"
    elif any(k in job_title for k in ['qa', 'tester', 'ui/ux', 'mobile', 'flutter', 'android']):
        job_category = "Other Technology Jobs"

    return {
        'match_score': total_score,
        'priority': priority,
        'match_reason': match_reason,
        'required_skills': job.get('required_skills') or (", ".join(matched_skills) if matched_skills else "General Tech"),
        'experience_level': job.get('experience') or job.get('experience_requirements') or "Not specified",
        'job_category': job_category,
        'recommendation': recommendation,
        'confidence': confidence,
        'notes': notes
    }


def analyze_job_match(
    job: Dict[str, Any],
    user_profile: Dict[str, Any],
    logger=None
) -> Dict[str, Any]:
    """
    Evaluates a job posting using OpenAI API when available, falling back seamlessly
    to the deterministic evaluation engine.
    """
    def log(msg: str):
        if logger:
            if hasattr(logger, "info"):
                logger.info(msg)
            elif callable(logger):
                logger(msg)
            else:
                print(msg)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

    # Use deterministic evaluation if API key is missing or dummy placeholder
    if not api_key or "your_" in api_key.lower() or "sk-proj-" not in api_key and len(api_key) < 20:
        return deterministic_score(job, user_profile)

    # Attempt OpenAI inference
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        prompt = f"""
You are an expert technical recruiter evaluating a job posting for a candidate.
Candidate Profile:
- Name: {user_profile.get('name')}
- Preferred Categories: {user_profile.get('preferred_categories')}
- Preferred Skills: {user_profile.get('preferred_skills')}
- Experience Level: {user_profile.get('experience_level')} (Max {user_profile.get('max_experience_years', 2)} years)
- Preferred Locations: {user_profile.get('preferred_job_locations')}
- Preferred Job Types: {user_profile.get('preferred_job_types')}

Job Posting:
- Title: {job.get('job_title')}
- Company: {job.get('company_name')}
- Location: {job.get('location')}
- Employment Type: {job.get('employment_type', job.get('job_type'))}
- Experience: {job.get('experience_requirements', job.get('experience'))}
- Skills: {job.get('required_skills')}
- Educational Requirements: {job.get('educational_requirements')}
- Description: {job.get('job_description', '')[:3000]}

SCORING CRITERIA (1 to 10 points total):
1. Candidate's Tech Career Interest: up to 3 points
2. Required Skills Match: up to 3 points
3. Experience Level Match (entry/junior preference): up to 2 points
4. Job Type & Location Match: up to 1 point
5. Recency / Market Relevance: up to 1 point

SAFETY RULES:
- If key details are missing, do not guess or hallucinate. Mark confidence "Low" and note "Needs human review".
- Priority: 7-10 is "High", 5-6 is "Medium", 1-4 is "Low".

Respond ONLY with a valid JSON object matching this schema:
{{
  "match_score": integer between 1 and 10,
  "priority": "High" | "Medium" | "Low",
  "match_reason": "concise 1-2 sentence reason for the score",
  "required_skills": "extracted or verified key skills string",
  "experience_level": "extracted experience requirement",
  "job_category": "Software Development" | "AI & Data" | "IT & Networking" | "Other Technology Jobs",
  "recommendation": "actionable 1 sentence recommendation",
  "confidence": "High" | "Medium" | "Low",
  "notes": "explanation or 'Needs human review'"
}}
"""
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a professional career matching AI that responds strictly in valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            timeout=15
        )
        content = response.choices[0].message.content
        result = json.loads(content)
        # Ensure priority corresponds correctly
        score = int(result.get("match_score", 5))
        if score >= 7:
            result["priority"] = "High"
        elif score >= 5:
            result["priority"] = "Medium"
        else:
            result["priority"] = "Low"
        return result

    except Exception as e:
        log(f"OpenAI analysis call failed ({e}); falling back to deterministic evaluator.")
        return deterministic_score(job, user_profile)
