import re
import json
import logging
import io
from pypdf import PdfReader

logger = logging.getLogger(__name__)

def extract_text_from_pdf(file_content: bytes) -> str:
    """
    Reads bytes and returns clean text.
    Safeguard: Adds newlines to prevent text merging (crucial for Regex).
    """
    try:
        reader = PdfReader(io.BytesIO(file_content))
        text_parts = []
        
        for page in reader.pages:
            # extraction_mode="layout" (if using newer pypdf) helps, 
            # but adding "\n" manually is the safest fallback for all versions.
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        
        # Join with double newlines to separate sections clearly
        full_text = "\n\n".join(text_parts)
        
        return full_text.strip()

    except Exception as e:
        logger.error(f"❌ PDF Parse Error: {e}")
        return ""

def extract_clean_json(text: str) -> dict:
    logger.debug("Raw AI text received for parsing.")
    """
    Strips '```json' formatting and finds the actual JSON object { ... }
    """
    try:
        # 1. Remove Markdown code blocks
        text = re.sub(r"```json|```", "", text, flags=re.IGNORECASE).strip()
        
        # 2. Find the content between the first '{' and the last '}'
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        
        if start_idx == -1 or end_idx == -1:
            logger.error("Could not find any JSON-like structure in AI response.")
            return None
            
        json_str = text[start_idx : end_idx + 1]
        
        # 3. Parse and return
        logger.info("JSON parsed successfully.")
        return json.loads(json_str)
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON Parsing Failed: {e}", exc_info=True)
        logger.error(f"Bad JSON String: {json_str[:500]}...")
        return None

def redact_pii(text: str) -> str:
    """
    Aggressively removes PII (Email, Phone, Address, Name) 
    before sending data to the AI.
    """
    if not text: return ""

    # --- 1. SENSITIVE IDs (Singapore NRIC/FIN) ---
    # Matches: S1234567A, T1234567Z, F1234567N, G1234567X (Case insensitive)
    text = re.sub(r'\b[S|T|F|G]\d{7}[A-Z]\b', '[NRIC_REDACTED]', text, flags=re.IGNORECASE)

    # --- 2. EMAILS & LINKS ---
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL_REDACTED]', text)
    # Remove LinkedIn/GitHub URLs (which often contain names)
    link_pattern = r'(?:https?://)?(?:www\.)?(?:linkedin\.com|github\.com)/[\w\-\./]+'
    text = re.sub(link_pattern, '[LINK_REDACTED]', text, flags=re.IGNORECASE)

    # --- 3. TELEPHONE NUMBERS (Robust Global & SG) ---
    
    # A. International Format (Starts with + or 00)
    # Examples: +1-202-555-0123 | +44 (0) 20 1234 5678 | +65 9123 4567
    # Logic: Look for +, then 1-3 digit country code, then groupings of digits/spaces/dashes
    intl_phone_pattern = r'(?:\+|00)\d{1,3}[-. ]?\(?\d{1,4}\)?[-. ]?\d{3,}[-. ]?\d{3,}'
    text = re.sub(intl_phone_pattern, '[PHONE_REDACTED]', text)

    # B. Standard US/Intl Format (No + sign, but uses parens or dashes)
    # Examples: (555) 123-4567 | 555-123-4567
    # We strictly look for parenthesis OR double dashes to avoid redacting dates like 2020-2024
    us_phone_pattern = r'(?:\(\d{3}\)|\d{3})[-. ]\d{3}[-. ]\d{4}'
    text = re.sub(us_phone_pattern, '[PHONE_REDACTED]', text)

    # C. Singapore Local Format (Specific)
    # Matches: 91234567, 8123 4567, 6123-4567 (Starts with 6, 8, or 9)
    sg_phone_pattern = r'\b[689]\d{3}[- ]?\d{4}\b'
    text = re.sub(sg_phone_pattern, '[PHONE_REDACTED]', text)

    # --- 4. SINGAPORE ADDRESSES ---
    # A. Postal Codes (6 digits, boundary check to avoid matching random large numbers)
    # Often preceded by "Singapore" or "S("
    text = re.sub(r'(?i)(Singapore|S\(?)\s*\d{6}\)?', '[POSTAL_CODE]', text)
    # Fallback: strict 6 digits at word boundary
    text = re.sub(r'\b\d{6}\b', '[POSTAL_CODE]', text)

    # B. Unit Numbers (e.g., #04-123)
    text = re.sub(r'#\d{1,4}-\d{1,5}', '[UNIT_NO]', text)
    
    # C. Block Numbers
    text = re.sub(r'\b(Blk|Block)\s*\d+[A-Za-z]?\b', '[BLOCK_NO]', text, flags=re.IGNORECASE)

    # --- 5. NAMES (Heuristic) ---
    # A. Explicit labels
    text = re.sub(r'(?i)(Name|Candidate):\s*([A-Z][a-z]+ [A-Z][a-z]+)', r'\1: [NAME_REDACTED]', text)

    # --- 6. FINANCIAL DATA (Credit Cards) ---
    # Matches 13-19 digits, with optional dashes or spaces
    # Examples: 4111 1234 5678 9010 | 4111-1234-5678-9010
    cc_pattern = r'\b(?:\d[ -]*?){13,19}\b'
    text = re.sub(cc_pattern, '[CREDIT_CARD_REDACTED]', text)

    # --- 7. SINGAPORE UEN (Company Reg No) ---
    # Invoices often have UENs (e.g., 200812345M). 
    # We redact this to genericize company data.
    text = re.sub(r'\b\d{9,10}[A-Za-z]\b', '[UEN_REDACTED]', text)

    # --- 8. DEMOGRAPHICS (Anti-Bias) --- (NEW) ⚖️
    # Removes Race, Religion, Nationality, Marital Status
    # Matches: "Race: Chinese", "Nationality: Singaporean"
    demographics_pattern = r'(?i)(Race|Religion|Nationality|Marital Status|Gender)\s*[:\-]\s*\w+'
    text = re.sub(demographics_pattern, '[DEMOGRAPHIC_REDACTED]', text)

    # --- 9. DATE OF BIRTH --- (NEW) 🎂
    # Matches: "DOB: 01/01/1990", "Date of Birth: 12 Dec 1990"
    dob_pattern = r'(?i)(Date of Birth|DOB|Born)\s*[:\-]?\s*.*?(?=\n|$)'
    text = re.sub(dob_pattern, '[DOB_REDACTED]', text)

    # --- 10. BANK ACCOUNT NUMBERS (Context-Aware) ---
    # Looks for keywords like "Account No", "A/C", "POSB", "DBS", "OCBC", "UOB"
    # Followed by 7-15 digits (with optional dashes/spaces)
    bank_acct_pattern = r'(?i)(Account|A/C|Acc|POSB|DBS|OCBC|UOB|UB)\W*[:\.]?\W*(\d[\d\s-]{6,15})'
    # We replace the number part (group 2) while keeping the label for context
    text = re.sub(bank_acct_pattern, r'\1 [BANK_ACCT_REDACTED]', text)

    # --- 11. CURRENCY & SALARY ---
    # Matches: $5000, $ 1,234.50, SGD 500, S$5000
    # Logic: Symbol/Code + optional space + digits + optional commas/decimals
    currency_pattern = r'(?i)(SGD|S\$|\$)\s?[\d,]+(?:\.\d{2})?'
    text = re.sub(currency_pattern, '[MONEY_REDACTED]', text)

    # B. The "Header" Assumption:
    # On most resumes, the first non-empty line is the Name. 
    # If the first line is short (< 30 chars) and capitalized, redact it.
    lines = text.split('\n')
    for i in range(len(lines)):
        line = lines[i].strip()
        if line:
            # If line is short and looks like a name (mostly letters, no weird symbols)
            if len(line) < 30 and re.match(r'^[A-Za-z \.]+$', line):
                 lines[i] = "[NAME_REDACTED_HEADER]"
            break # Only try to redact the first valid line
            
    return "\n".join(lines)

def parse_json_safely(text: str) -> dict:
    """
    Robust JSON Parser that:
    1. Ignores conversational text ("Here is the JSON...").
    2. Handles Guardrail Refusals cleanly (No scary warnings).
    3. Returns a valid fallback dictionary if parsing fails.
    """
    if not text:
        return {"coach_critique": "No content generated.", "score": 0}

    # --- 1. Check for Guardrail Refusal (Success Case) ---
    # If the text is exactly the guardrail message, handle it gracefully.
    if "I cannot process this request" in text or "violates our safety" in text:
        logger.info(f"🛡️ Guardrail Refusal Handled: {text[:50]}...")
        return {
            "coach_critique": "🚫 REQUEST BLOCKED: Your input was flagged by our safety guidelines.",
            "rewritten_answer": "Your input was flagged by our safety guidelines. Please try again with professional language.",
            "score": 0,
            "improvements": ["Please rephrase your request."],
            "matched_skills": [],
            "missing_skills": []
        }

    # --- 2. Try to find JSON content using Regex ---
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            json_str = match.group(0)
            return json.loads(json_str)
    except Exception:
        pass

    # --- 3. Parsing TRULY Failed (Error Case) ---
    logger.warning(f"⚠️ JSON Parsing Failed. Raw text: {text[:50]}...")
    
    return {
        "coach_critique": "System Error: Invalid AI Response",
        "rewritten_answer": text[:500], # Return raw text so user sees something
        "score": 0,
        "improvements": ["System: Please try again."]
    }