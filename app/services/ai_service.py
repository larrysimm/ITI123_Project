# File: app/services/ai_service.py
import os
import json
import re
import random
from pypdf import PdfReader
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

# Import settings to get API Keys
from ..core.config import settings, logger

# --- GLOBAL STATE ---
STAR_GUIDE_TEXT = "Standard STAR Method principles."
gemini_llm = None
openai_llm = None
groq_llm = None

# --- INITIALIZATION ---
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

# Helper to safely mask keys
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
            logger.info(f"Gemini Init: {mask_key(settings.GOOGLE_API_KEY)}")
        except Exception as e: logger.error(f"Gemini Fail: {e}")

    # Initialize OpenAI
    if settings.OPENAI_API_KEY:
        try:
            openai_llm = ChatOpenAI(
                model="gpt-4o-mini", 
                temperature=0.2, 
                api_key=settings.OPENAI_API_KEY
            )
            logger.info(f"OpenAI Init: {mask_key(settings.OPENAI_API_KEY)}")
        except Exception as e: logger.error(f"OpenAI Fail: {e}")

    # Initialize Groq
    if settings.GROQ_API_KEY:
        try:
            groq_llm = ChatGroq(
                model_name="llama-3.3-70b-versatile", 
                temperature=0.2, 
                groq_api_key=settings.GROQ_API_KEY
            )
            logger.info(f"Groq Init: {mask_key(settings.GROQ_API_KEY)}")
        except Exception as e: logger.error(f"Groq Fail: {e}")

# --- PROMPTS ---
manager_prompt = ChatPromptTemplate.from_template(
    """
    You are a skeptcial, high-standards Hiring Manager for a {role} position.
    
    THE ROLE REQUIRES THESE SPECIFIC COMPETENCIES (from our internal spec):
    {detailed_skills}
    
    CANDIDATE'S RESUME SUMMARY:
    {resume_text}

    CRITICAL SKILL GAPS (FROM AUDIT)
    The following skills were marked as MISSING in the candidate's resume:
    {skill_gaps}
    
    INTERVIEW QUESTION:
    "{question}"
    
    CANDIDATE'S ANSWER:
    "{student_answer}"
    
    YOUR TASK:
    Evaluate this answer strictly. 
    1. **Cite Your Sources:** You MUST reference the **Ref Code** (e.g., [ICT-DIT-3002-1.1]) when critiquing a specific skill.
       - *Bad:* "You lack system design skills."
       - *Good:* "Regarding **System Design (Ref: ICT-DES-4002-1.1)**, the spec requires Level 4 proficiency, but your answer was generic."
    2. **Depth:** Is the answer vague or does it show specific technical knowledge mentioned in the requirements?
    3. **Compare Explicitly:** - Look at the **"Key Knowledge"** field in the data source. Did the candidate mention those specific keywords?
       - If the data says "Level 5", but the candidate sounds like a junior, point out the gap.
    4. **Skill Demonstration:** Does the answer provide evidence for the {role} skills?
    5. **Gap Mitigation:** specifically check if the answer helps cover any of the **Critical Skill Gaps** listed above. 
       - If they demonstrate a missing skill here, acknowledge it enthusiastically.
       - If they miss a chance to demonstrate a missing skill, point it out.
    6. **Verdict:** Be direct and professional. If they missed a key technical requirement, say it.
    
    IMPORTANT OUTPUT INSTRUCTIONS:
    --------------------------------------------------------
    You must output your response in TWO parts:
    
    PART 1: Internal Thought Process (Wrapped in <thinking> tags)
    - Briefly analyze the candidate's answer against the skill gaps.
    - Note down which specific Reference Codes you need to cite.
    - Decide if the tone should be harsh or approving.
    
    PART 2: Final Manager Feedback
    - The actual response to the candidate (approx 100 words).
    - Focus on content and competence.
    
    Example Format:
    <thinking>
    Candidate mentioned Python, but the Ref Code ICT-PRG-3001 requires Java. 
    They missed the gap on 'Cloud Computing'. I need to be critical about that.
    </thinking>
    
    [Your Final Critique Here]
    """
)

coach_prompt = ChatPromptTemplate.from_template(
    """
    You are an expert Interview Coach specializing in the STAR method (Situation, Task, Action, Result).
    
    RELIES ON THIS GUIDE FOR COACHING:
    <OFFICIAL_STAR_GUIDE>
    {star_guide_content}
    </OFFICIAL_STAR_GUIDE>

    INPUTS:
    1. **Manager's Technical Requirements:** "{manager_critique}" (Use this ONLY for rewriting the answer).
    2. **Candidate's Original Answer:** "{student_answer}"
    
    YOUR GOAL:
    1. **Audit the Structure:** Check if the *Candidate's Original Answer* based STRICTLY on the <OFFICIAL_STAR_GUIDE> above.
    2. **Rewrite the Content:**Create a perfect answer that fixes the structure using the examples in the <OFFICIAL_STAR_GUIDE> as a style reference AND adds the technical skills requested by the Manager.
    
    IMPORTANT OUTPUT INSTRUCTIONS:
    --------------------------------------------------------
    You must output your response in TWO parts:
    
    PART 1: Internal Strategy (Wrapped in <thinking> tags)
    - Identify which letters of S-T-A-R were weak or missing in the original text.
    
    PART 2: Final JSON Output
    
    Field 1: "coach_critique"
    - **DO NOT** mention technical skills (e.g., "You lacked Java knowledge").
    - **FOCUS ONLY** on narrative structure.
    - Ask: Was the 'Situation' clear? Was the 'Action' vague? Did the 'Result' have numbers?
    - Example: "Your 'Action' section was too generic and didn't list specific steps. The 'Result' was missing quantifiable metrics."
    
    Field 2: "rewritten_answer"
    - If the original answer was incomprehensible, Do not try to salvage it, INSTEAD, let the user know and give advice on "HOW TO PREPARE FOR A BEHAVIORAL INTERVIEW" from the [STAR_GUIDE] to teach the user the basics. 
    - This is where you fix everything.
    - Write a polished response using the Manager's keywords.
    - Use Markdown bolding for the headers: **Situation:**, **Task:**, **Action:**, **Result:**.
    
    Output Format:
    <thinking>
    The user had a good Situation but the Action was passive. No numbers in Result.
    </thinking>
    
    ```json
    {{
        "coach_critique": "Your original answer failed to follow the STAR method. You combined Situation and Task, and your Result lacked any quantifiable metrics.",
        "rewritten_answer": "**Situation:** ... **Task:** ... **Action:** ... **Result:** ..."
    }}
    ```
    IMPORTANT RULES:
    1. Do NOT copy the example text above. Generate NEW content based on the user's input.
    """
)

match_skills_prompt = ChatPromptTemplate.from_template(
    """
    You are a Senior HR Auditor performing a Compliance Check.
    
    ### OFFICIAL DATABASE STANDARDS (Source of Truth)
    {detailed_skills}
    
    ### CANDIDATE RESUME
    {resume_text}
    
    ### TASK
    Compare the Resume against the Database Standards.
    
    1. **Exact Matching:** A "Match" must demonstrate the specific **Required Level** defined in the standard.
    2. **Citation:** You MUST extract the **Ref Code** (e.g., [ICT-DIT-3002-1.1]) for every skill.
    
    ### OUTPUT FORMAT (Strict JSON)
    {{
        "matched_skills": [ 
            {{ 
                "skill": "Skill Name", 
                "code": "Ref Code from DB", 
                "reason": "Resume meets Level [X] requirement. Evidence: [Quote]..." 
            }} 
        ],
        "missing_skills": [ 
            {{ 
                "skill": "Skill Name", 
                "code": "Ref Code from DB", 
                "gap": "Resume fails to meet Level [X] standard. Missing evidence of [Key Knowledge]..." 
            }} 
        ]
    }}
    """
)

# --- HELPER FUNCTIONS ---
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
        
    except json.JSONDecodeError:
        logger.error(f"JSON Parsing Failed: {e}", exc_info=True)
        logger.error(f"Bad JSON String: {json_str[:500]}...")
        return None

def parse_llm_response(raw_text):
    """
    Extracts content inside <thinking> tags and separates it from the final answer.
    Returns: (thinking_trace, final_answer)
    """
    # Regex to find content between <thinking> and </thinking>
    # re.DOTALL allows the dot (.) to match newlines
    thinking_match = re.search(r'<thinking>(.*?)</thinking>', raw_text, re.DOTALL)
    
    if thinking_match:
        thinking_content = thinking_match.group(1).strip()
        # Remove the thinking block from the original text to get the final answer
        final_answer = re.sub(r'<thinking>.*?</thinking>', '', raw_text, flags=re.DOTALL).strip()
    else:
        # Fallback if AI forgets tags
        thinking_content = "No thinking trace provided by AI."
        final_answer = raw_text.strip()
        
    return thinking_content, final_answer

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
    
# --- MAIN EXECUTION ---
async def run_chain_with_fallback(prompt_template, inputs, step_name="AI"):
    """
    Strategy:
    1. Tier 1: OpenAI & Gemini (Randomize order 50/50).
    2. Tier 2: Groq (Only if BOTH Tier 1 models fail).
    3. Tier 3: Static Fallback (If ALL AI fails).
    """

    # Helper to run and log tokens
    async def execute_and_log(chain, model_name):
        response = await chain.ainvoke(inputs)
        
        # Capture Usage Stats
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
        
    except json.JSONDecodeError:
        logger.error(f"JSON Parsing Failed: {e}", exc_info=True)
        logger.error(f"Bad JSON String: {json_str[:500]}...")
        return None
