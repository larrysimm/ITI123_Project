import os
import json
import re
import random
import time
import yaml

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from openai import AsyncOpenAI

from app.core.config import settings, logger
from app.utils import parsers
from app.services.guardrails import GuardrailService

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
            with open(settings.STAR_GUIDE_PATH, "rb") as f:
                content = f.read()
            # Use the new utility
            STAR_GUIDE_TEXT = parsers.extract_text_from_pdf(content)
            logger.info(f"✅ STAR Guide loaded successfully ({len(content)} chars).")
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
    
async def validate_is_resume(text: str):
    """
    Uses AI to check if the extracted text looks like a resume.
    """
    try:
        # 1. Get the prompt template
        prompt_template = get_prompt("resume_validator_prompt")
        
        # 2. Prepare inputs (Truncate text to save tokens)
        inputs = {"text_sample": text[:2000]}
        
        # 3. Run with your existing Fallback Engine (Robust!)
        response_text = await run_chain_with_fallback(
            prompt_template, 
            inputs, 
            step_name="Resume Validator"
        )
        
        # 4. Parse the JSON result
        result = parse_json_safely(response_text)
        
        # Fail-safe: If JSON parsing fails, assume it's valid to avoid blocking user
        if not result:
            logger.warning("⚠️ Could not parse Resume Validator response. Defaulting to Valid.")
            return {"isValid": True, "reason": "AI Validation Error (Fail Open)"}
            
        return result

    except Exception as e:
        logger.error(f"❌ Resume Validation Logic Failed: {e}")
        # Default to True so we don't block users if the server crashes
        return {"isValid": True, "reason": "System Error"}
    
async def run_chain_with_fallback(prompt_template, inputs, step_name="AI"):
    """
    Strategy:
    1. Tier 1: OpenAI & Gemini (Randomize order 50/50).
    2. Tier 2: Groq (Only if BOTH Tier 1 models fail).
    3. Tier 3: Static Fallback (If ALL AI fails).
    """
    # =========================================================
    # 🛡️ PHASE 0: INPUT GUARDRAIL (The "Input Rail")
    # Blocks attacks immediately. Saves Money & Latency.
    # =========================================================
    
    # Flatten inputs to a string to scan for attacks
    scan_text = str(inputs)

    # 1. JAILBREAK CHECK (Adversarial Defense)
    if GuardrailService.detect_jailbreak(scan_text):
        logger.warning(f"🛡️ SECURITY: Jailbreak attempt blocked in {step_name}")
        return "I cannot process this request. I am programmed to be a helpful Interview Coach and cannot ignore my instructions."

    # 2. TOXICITY CHECK (Inbound Content Moderation)
    if GuardrailService.check_toxicity(scan_text, source="Inbound"):
        logger.warning(f"🚫 SAFETY: Toxic input blocked in {step_name}")
        return "I cannot process this request as it contains content that violates our safety guidelines."

    # =========================================================

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

async def _transcribe_openai(file_obj):
    """Try OpenAI Whisper-1"""
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return await client.audio.transcriptions.create(
        model="whisper-1", 
        file=(file_obj.filename, file_obj.file)
    )

async def _transcribe_groq(file_obj):
    """Try Groq Whisper-Large (Fast!)"""
    client = AsyncOpenAI(
        api_key=settings.GROQ_API_KEY, 
        base_url="https://api.groq.com/openai/v1"
    )
    return await client.audio.transcriptions.create(
        model="whisper-large-v3", 
        file=(file_obj.filename, file_obj.file)
    )

async def transcribe_audio_with_fallback(file_obj):
    """
    Attempts to transcribe audio using OpenAI first, then falls back to Groq.
    Crucial: Handles file pointer rewinding between attempts.
    """
    # Define the order of providers
    providers = [
        ("OpenAI", _transcribe_openai),
        ("Groq", _transcribe_groq)
    ]

    last_error = None

    for name, func in providers:
        try:
            # 1. Rewind file to start (Crucial for retries!)
            await file_obj.seek(0)
            
            logger.info(f"🎤 Attempting transcription with {name}...")
            
            # 2. Call the provider
            transcript = await func(file_obj)
            
            logger.info(f"✅ Transcription success with {name}")
            return transcript.text

        except Exception as e:
            logger.warning(f"⚠️ {name} Transcription Failed: {e}")
            last_error = e
            # Loop continues to the next provider...

    # If we exit the loop, everything failed
    logger.error("❌ All transcription services failed.")
    return "Error: Could not transcribe audio. Please type your answer."

def parse_json_safely(text: str) -> dict:
    """
    Robust JSON Parser that:
    1. Ignores conversational text ("Here is the JSON...").
    2. Handles Guardrail Refusals cleanly (No scary warnings).
    3. Returns a valid fallback dictionary if parsing fails.
    """
    if not text:
        return {"feedback": "No content generated.", "score": 0}

    # --- 1. Check for Guardrail Refusal (Success Case) ---
    # If the text is exactly the guardrail message, handle it gracefully.
    if "I cannot process this request" in text or "violates our safety" in text:
        logger.info(f"🛡️ Guardrail Refusal Handled: {text[:50]}...")
        return {
            "feedback": "Request Blocked",
            "critique": "Your input was flagged by our safety guidelines. Please try again with professional language.",
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
        "feedback": "System Error: Invalid AI Response",
        "critique": text[:500], # Return raw text so user sees something
        "score": 0,
        "improvements": ["System: Please try again."]
    }