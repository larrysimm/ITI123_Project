import os
import json
import re
import random
import time
import yaml
from pypdf import PdfReader
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

# Import settings to get API Keys
from ..core.config import settings, logger

# --- GLOBAL STATE ---
STAR_GUIDE_TEXT = "Standard STAR Method principles."
PROMPTS = {}
gemini_llm = None
openai_llm = None
groq_llm = None

def load_prompts():
    """Loads prompts from app/prompts.yaml"""
    global PROMPTS
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts.yaml")
    
    if os.path.exists(prompt_path):
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                PROMPTS = yaml.safe_load(f)
            logger.info("✅ Prompts loaded from YAML.")
        except Exception as e:
            logger.error(f"❌ Failed to load prompts.yaml: {e}")
            # Fallback to empty dict (will cause errors if not handled, but better than crash)
            PROMPTS = {}
    else:
        logger.warning(f"⚠️ prompts.yaml not found at {prompt_path}")

def load_star_guide():
    """
    Loads the STAR Method Guide from a local PDF into memory.
    """
    global STAR_GUIDE_TEXT
    
    if os.path.exists(settings.STAR_GUIDE_PATH):
        try:
            reader = PdfReader(settings.STAR_GUIDE_PATH)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            STAR_GUIDE_TEXT = text
            logger.info(f"✅ STAR Guide loaded successfully ({len(text)} chars).")
        except Exception as e:
            logger.error(f"❌ Failed to load STAR Guide: {e}")
            STAR_GUIDE_TEXT = "Standard STAR Method principles." # Fallback
    else:
        logger.warning(f"⚠️ '{settings.STAR_GUIDE_PATH}' not found. Using default AI knowledge.")

def mask_key(key: str) -> str:
    if not key or len(key) < 5:
        return "❌ NOT SET"
    return f"✅ ...{key[-4:]}"  # Shows only last 4 chars

def init_ai_models():
    global gemini_llm, openai_llm, groq_llm
    
    # Initialize Gemini
    if settings.GOOGLE_API_KEY:
        try:
            gemini_llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash", 
                temperature=0.2, 
                google_api_key=settings.GOOGLE_API_KEY
            )
            logger.info(f"✅ Gemini Initialized successfully. Google API: {mask_key(settings.GOOGLE_API_KEY)}")
        except Exception as e: logger.error(f"Gemini Fail: {e}")

    # Initialize OpenAI
    if settings.OPENAI_API_KEY:
        try:
            openai_llm = ChatOpenAI(
                model="gpt-4o-mini", 
                temperature=0.2, 
                api_key=settings.OPENAI_API_KEY
            )
            logger.info(f"✅ OpenAI Initialized successfully. OpenAI API: {mask_key(settings.OPENAI_API_KEY)}")
        except Exception as e: logger.error(f"OpenAI Fail: {e}")

    # Initialize Groq
    if settings.GROQ_API_KEY:
        try:
            groq_llm = ChatGroq(
                model_name="llama-3.3-70b-versatile", 
                temperature=0.2, 
                groq_api_key=settings.GROQ_API_KEY
            )
            logger.info(f"✅ Groq Initialized successfully. Groq API: {mask_key(settings.GROQ_API_KEY)}")
        except Exception as e: logger.error(f"Groq Fail: {e}")

def get_prompt(prompt_name):
    """Retrieves a prompt template from the loaded YAML."""
    raw_text = PROMPTS.get(prompt_name, "")
    if not raw_text:
        logger.error(f"Prompt '{prompt_name}' not found!")
        return ChatPromptTemplate.from_template("Error: Prompt missing.")
    return ChatPromptTemplate.from_template(raw_text)

def redact_pii(text):
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

def extract_clean_json(text):
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

def parse_llm_response(raw_text):
    """
    Extracts content inside <thinking> tags and separates it from the final answer.
    Returns: (thinking_trace, final_answer)
    """
    if not raw_text:
        return "No thinking.", "No response."

    # 1. Try to find the thinking block
    thinking_match = re.search(r'<thinking>(.*?)</thinking>', raw_text, re.DOTALL)
    
    if thinking_match:
        # Case A: Tags found
        thinking_content = thinking_match.group(1).strip()
        final_answer = re.sub(r'<thinking>.*?</thinking>', '', raw_text, flags=re.DOTALL).strip()
        
        # Safety: If final answer is empty but thinking exists, use thinking as the answer
        if not final_answer:
            return "Thinking used as answer.", thinking_content
            
        return thinking_content, final_answer
    
    else:
        # Case B: NO Tags found (The Critical Fix)
        # If the AI didn't output tags, treat the WHOLE text as the final answer.
        return "No internal thought trace.", raw_text.strip()

def get_static_fallback(step_name: str, inputs: dict) -> str:
    """
    Returns a generic, safe response when all AI models fail.
    Used to prevent the frontend from crashing during high traffic/outages.
    """
    logger.warning(f"🪂 DEPLOYING STATIC PARACHUTE for {step_name}")
    
    # 1. Fallback for "Skill Matcher" (Gap Analysis)
    if step_name == "Skill Matcher":
        return json.dumps({
            "matched_skills": [
                {
                    "skill": "General Professionalism",
                    "code": "GEN-PRO-001",
                    "reason": "Resume detected, but AI deep analysis is currently offline due to high server load."
                }
            ],
            "missing_skills": [
                {
                    "skill": "Technical Deep Dive (System Busy)",
                    "code": "ERR-503",
                    "gap": "Our AI analysis servers are currently experiencing very high traffic. Please manually review your specific technical requirements against the job description while we cool down."
                }
            ]
        })

    # 2. Fallback for "Coach Agent" (Interview Coaching) or "Manager Agent"
    else:
        # We return a format that works for BOTH Manager and Coach parsing
        return json.dumps({
            # Manager-style keys
            "manager_critique": "⚠️ **System Notification:** High Server Load. We cannot provide specific technical feedback right now.",
            
            # Coach-style keys
            "coach_critique": "Our AI Coach is currently assisting too many users (Capacity Limit Reached). However, a universal tip is to ensure your answer follows the STAR method strictly.",
            "rewritten_answer": "**Situation:** [Your Context] **Task:** [Your Challenge] **Action:** [Specific Steps Taken] **Result:** [Quantifiable Outcome]. \n\n*(Please try again in 5 minutes for a specific rewrite).* "
        })
    
async def run_chain_with_fallback(prompt_template, inputs, step_name="AI"):
    """
    Strategy:
    1. Tier 1: OpenAI & Gemini (Randomize order 50/50).
    2. Tier 2: Groq (Only if BOTH Tier 1 models fail).
    3. Tier 3: Static Fallback (If ALL AI fails).
    """

    # Helper to run and log tokens
    async def execute_and_log(chain, model_name):
        # --- 1. LOG INPUT (First 50 words) ---
        # Convert inputs dict to string and flatten newlines for cleaner logs
        input_flat = str(inputs).replace('\n', ' ')
        input_preview = " ".join(input_flat.split()[:50])
        logger.info(f"📤 [{model_name}] SENDING: {input_preview}...")

        # Start Timer
        start_time = time.time()

        # --- 2. EXECUTE ---
        response = await chain.ainvoke(inputs)
        
        # Stop Timer
        duration = time.time() - start_time

        # --- 3. LOG OUTPUT (First 50 words) ---
        content = response.content
        if content:
            # Flatten newlines
            content_flat = content.replace('\n', ' ')
            output_preview = " ".join(content_flat.split()[:50])
            logger.info(f"📥 [{model_name}] RECEIVED ({duration:.2f}s): {output_preview}...")
        else:
            logger.info(f"📥 [{model_name}] RECEIVED ({duration:.2f}s): [Empty Content]")

        # --- 4. LOG TOKEN USAGE (Your existing code) ---
        usage = response.usage_metadata
        if usage:
            input_tok = usage.get('input_tokens', 0)
            output_tok = usage.get('output_tokens', 0)
            total_tok = usage.get('total_tokens', 0)
            logger.info(
                f"💰 TOKEN USAGE ({step_name} - {model_name}): "
                f"In={input_tok}, Out={output_tok}, Total={total_tok}"
            )
            
        return response.content

    chains = {}
    
    # Only create the chain if the LLM actually exists
    if gemini_llm:
        chains["Gemini"] = prompt_template | gemini_llm

    if openai_llm:
        chains["OpenAI"] = prompt_template | openai_llm

    if groq_llm:
        chains["Groq"]   = prompt_template | groq_llm

    # =========================================================
    # 2. BUILD THE EXECUTION PLAN
    # =========================================================
    
    # Create a list of Tier 1 models (Gemini + OpenAI)
    tier1 = []
    
    # We check if the KEY exists in our valid 'chains' dict
    if "Gemini" in chains: 
        tier1.append("Gemini")
        
    if "OpenAI" in chains: 
        tier1.append("OpenAI")
    
    # Shuffle them! (Randomly decides who goes first)
    random.shuffle(tier1) 
    
    # Add Groq as the final safety net (if it exists)
    execution_order = tier1
    if "Groq" in chains:
        execution_order.append("Groq")
    
    logger.info(f"🎲 Execution Plan for {step_name}: {execution_order}")

    # =========================================================
    # 3. EXECUTE WITH FAILOVER
    # =========================================================
    if not execution_order:
        # Case: ALL keys are missing (or app config is broken)
        logger.critical(f"❌ No AI models available for {step_name}.")
        return get_static_fallback(step_name, inputs)

    last_exception = None
    
    for model_name in execution_order:
        try:
            logger.info(f"🤖 Attempting {step_name} with {model_name}...")
            return await execute_and_log(chains[model_name], model_name)
        except Exception as e:
            last_exception = e
            logger.warning(f"⚠️ {model_name} Failed: {e}. Failing over...")

    # =========================================================
    # 4. FINAL FALLBACK (Parachute)
    # =========================================================
    logger.critical(f"❌ ALL AI MODELS FAILED for {step_name}. Deploying Static Response.")
    return get_static_fallback(step_name, inputs)
