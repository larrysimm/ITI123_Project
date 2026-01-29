import re
import json
import logging
import io
from pypdf import PdfReader

logger = logging.getLogger(__name__)

def extract_text_from_pdf(file_content: bytes) -> str:
    """Reads bytes (from upload or file) and returns clean text."""
    try:
        reader = PdfReader(io.BytesIO(file_content))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text.strip()
    except Exception as e:
        logger.error(f"PDF Parse Error: {e}")
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

    # 1. EMAILS
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL_REDACTED]', text)
    
    # 2. PHONE NUMBERS (SG 8-digit & Intl formats)
    # Matches: 91234567, (+65) 91234567, 65-9123-4567
    text = re.sub(r'(?:\+?65[- ]?)?[689]\d{3}[- ]?\d{4}\b', '[PHONE_REDACTED]', text)

    # 3. SINGAPORE ADDRESSES (The "Fingerprint")
    # A. Postal Codes (6 digits, often appearing as "Singapore 123456" or just "123456")
    text = re.sub(r'\b(?:Singapore\s*)?\d{6}\b', '[POSTAL_CODE]', text)
    
    # B. Unit Numbers (e.g., #04-123)
    text = re.sub(r'#\d{1,4}-\d{1,5}', '[UNIT_NO]', text)
    
    # C. HDB Block Numbers (e.g., Blk 123, Block 10A)
    text = re.sub(r'\b(Blk|Block)\s*\d+[A-Za-z]?\b', '[BLOCK_NO]', text, flags=re.IGNORECASE)

    # 4. NAMES (Heuristic Approach)
    # A. Explicit labels like "Name: John Doe"
    text = re.sub(r'(?i)(Name|Candidate):\s*([A-Z][a-z]+ [A-Z][a-z]+)', r'\1: [NAME_REDACTED]', text)

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
            "improvements": ["Please rephrase your request."]
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