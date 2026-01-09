import os
import sqlite3
import json
import asyncio
import re  # <--- NEW: For cleaning JSON output
import json
import io
import database
import logging

from ast import Dict
from typing import Optional, Dict, List
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from google.api_core.exceptions import ResourceExhausted
from pypdf import PdfReader

STAR_GUIDE_TEXT = "Standard STAR Method principles." # Default fallback
API_SECRET = os.getenv("BACKEND_SECRET", "default-insecure-secret")

# --- LOGGER SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("backend.log"), # Saves logs to this file
        logging.StreamHandler()             # Prints logs to terminal
    ]
)
logger = logging.getLogger(__name__)

# 1. SETUP
load_dotenv()
app = FastAPI(title="Poly-to-Pro", version="3.0.0")

database.init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://larrysim-iti123-project.netlify.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 👇 INSERT THIS BLOCK HERE 👇
@app.on_event("startup")
async def startup_event():
    logger.info(">>> SERVER STARTING UP <<<")
    
    # Load the PDF Guide into memory
    load_star_guide()
    
    logger.info("Server is ready to accept requests.")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info(">>> SERVER SHUTTING DOWN <<<")

@app.middleware("http")
async def verify_secret_header(request: Request, call_next):
    # Allow OPTIONS requests (needed for CORS pre-flight checks)
    if request.method == "OPTIONS":
        return await call_next(request)
        
    # Public endpoints (like docs or root) can be excluded if you want
    if request.url.path in ["/", "/docs", "/openapi.json"]:
         return await call_next(request)

    # Check for the secret header
    client_secret = request.headers.get("X-Poly-Secret")
    
    if client_secret != API_SECRET:
        # Reject the request
        return json.dumps({"detail": "Unauthorized: Invalid Secret"}), 401
        
    response = await call_next(request)
    return response

# 2. DUAL AI SETUP
gemini_llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

groq_llm = ChatGroq(
    model_name="llama-3.3-70b-versatile",
    temperature=0.2,
    groq_api_key=os.getenv("GROQ_API_KEY")
)

# Helper: Failover Logic
async def run_chain_with_fallback(prompt_template, inputs, step_name="AI"):
    try:
        logger.info(f"🤖 [Model Selection] Using GEMINI 2.5 Flash for {step_name}...")
        chain = prompt_template | gemini_llm | StrOutputParser()
        return await chain.ainvoke(inputs)
    except ResourceExhausted:
        # CHANGED: print -> logger.warning
        logger.warning(f"⚠️ GEMINI QUOTA HIT ({step_name}). Switching to GROQ...")
        
        logger.info(f"🤖 [Model Selection] Using GROQ (Llama 3.3) for {step_name}...")
        chain = prompt_template | groq_llm | StrOutputParser()
        return await chain.ainvoke(inputs)
    except Exception as e:
        # CHANGED: print -> logger.error with traceback
        logger.error(f"⚠️ GEMINI ERROR ({step_name}): {e}. Switching to GROQ...", exc_info=True)
        try:
            chain = prompt_template | groq_llm | StrOutputParser()
            return await chain.ainvoke(inputs)
        except Exception as groq_e:
            logger.critical(f"Both AI Engines Failed: {str(groq_e)}", exc_info=True)
            raise Exception(f"Both AI Engines Failed: {str(groq_e)}")
        
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

# 3. DATABASE CONTEXT RETRIEVER
def get_full_role_context(role: str) -> str:
    conn = sqlite3.connect("skills.db")
    cursor = conn.cursor()
    cursor.execute("SELECT description, expectations FROM role_descriptions WHERE role = ?", (role,))
    desc_row = cursor.fetchone()
    
    if not desc_row:
        conn.close()
        return "No specific role data found. Use general best practices."

    cursor.execute("SELECT task FROM role_tasks WHERE role = ? LIMIT 5", (role,))
    tasks = [r[0] for r in cursor.fetchall()]
    
    query = """
        SELECT s.title, s.description FROM role_skills rs 
        JOIN skill_definitions s ON rs.skill_code = s.skill_code 
        WHERE rs.role = ? LIMIT 10
    """
    cursor.execute(query, (role,))
    skills = cursor.fetchall()
    conn.close()

    context = f"ROLE: {role}\nDESC: {desc_row[0]}\nEXPECTATIONS: {desc_row[1]}\nKEY TASKS:\n"
    for t in tasks: context += f"- {t}\n"
    context += "\nCOMPETENCIES:\n"
    for t, d in skills: context += f"- {t}: {d}\n"
    return context

def get_detailed_skills(role_name):
    """
    Fetches explicit metadata (Role, Skill Code, Proficiency, Knowledge) 
    to force the AI to cite sources precisely.
    """
    try:
        conn = sqlite3.connect("skills.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Added s.skill_code to the selection
        # ADDED: Log entry
        logger.info(f"Fetching detailed skills spec for: {role_name}")
        query = """
            SELECT 
                s.title, 
                s.skill_code,
                rs.proficiency,
                GROUP_CONCAT(d.detail_item, '; ') as knowledge_list
            FROM role_skills rs 
            JOIN skill_definitions s ON rs.skill_code = s.skill_code 
            LEFT JOIN skill_details d ON s.skill_code = d.skill_code
            WHERE rs.role = ? 
            GROUP BY s.skill_code
            LIMIT 6
        """
        cursor.execute(query, (role_name,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return f"Standard industry spec for {role_name} (No specific DB entry)."

        # Format as a Strict Reference Document
        skills_text = f"OFFICIAL SPECIFICATION FOR ROLE: {role_name.upper()}\n"
        skills_text += "=" * 40 + "\n\n"
        
        for row in rows:
            knowledge = (row["knowledge_list"][:200] + "...") if row["knowledge_list"] else "General application"
            level = row["proficiency"] if row["proficiency"] else "Standard"
            code = row["skill_code"]
            
            # Explicit Format
            skills_text += f"Ref Code: [{row['skill_code']}]\n"
            skills_text += f"Skill Title: {row['title']}\n"
            skills_text += f"Required Level: {level}\n"
            skills_text += f"Key Knowledge: {knowledge}\n"
            skills_text += "-" * 20 + "\n"
        
        logger.info(f"Successfully retrieved {len(rows)} skills for {role_name}")
        return skills_text

    except Exception as e:
        logger.error(f"Error fetching skills: {e}", exc_info=True)
        return "Standard industry skills."

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

def redact_pii(text):
    """
    Aggressively removes PII (Email, Phone, Address, Name) 
    before sending data to the AI.
    """
    
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

def load_star_guide():
    """
    Loads the STAR Method Guide from a local PDF into memory.
    """
    global STAR_GUIDE_TEXT
    guide_path = "star_guide.pdf"  # <--- Name your file this
    
    if os.path.exists(guide_path):
        try:
            reader = PdfReader(guide_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            STAR_GUIDE_TEXT = text
            logger.info(f"✅ STAR Guide loaded successfully ({len(text)} chars).")
        except Exception as e:
            logger.error(f"❌ Failed to load STAR Guide: {e}")
            STAR_GUIDE_TEXT = "Standard STAR Method principles." # Fallback
    else:
        logger.warning("⚠️ 'star_guide.pdf' not found. Using default AI knowledge.")

# 4. PROMPTS

# Manager Prompt (Standard Text Output)
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

# Coach Prompt (Structured JSON Output)
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

# Match Skills Prompt (Structured JSON Output)
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

# 5. MODELS
class AnalyzeRequest(BaseModel):
    student_answer: str
    question: str
    target_role: str
    resume_text: str
    skill_data: Optional[Dict] = None

class MatchRequest(BaseModel):
    resume_text: str
    target_role: str

# 6. ENDPOINTS
@app.get("/")
async def root():
    return {
        "message": "Poly-to-Pro API is running!",
        "docs": "/docs",
        "status": "OK"
    }

@app.get("/questions")
def get_questions():
    """
    Fetches the list of questions from the database.
    These were populated from your questions.json file.
    """
    try:
        # Connect to the DB
        conn = sqlite3.connect("skills.db")
        cursor = conn.cursor()
        
        # Select all questions
        cursor.execute("SELECT id, question_text FROM saved_questions ORDER BY id ASC")
        rows = cursor.fetchall()
        
        # Convert to JSON-friendly list
        questions = [{"id": r[0], "text": r[1]} for r in rows]
        
        conn.close()
        return questions
    except Exception as e:
        logger.error(f"Error fetching questions: {e}", exc_info=True)
        return []

@app.get("/roles")
def get_roles():
    """
    Fetches a unique list of job roles from the database.
    """
    try:
        conn = sqlite3.connect("skills.db")
        cursor = conn.cursor()
        
        # Get unique roles sorted alphabetically
        cursor.execute("SELECT DISTINCT role FROM role_descriptions ORDER BY role ASC")
        rows = cursor.fetchall()
        
        # Convert list of tuples [('Role A',), ('Role B',)] to simple list ['Role A', 'Role B']
        roles = [row[0] for row in rows]
        
        conn.close()
        return roles
    except Exception as e:
        logger.error(f"Error fetching questions: {e}", exc_info=True)
        logger.error(f"Error fetching roles: {e}", exc_info=True)

        return [] # Return empty list on failure

@app.post("/upload_resume")
async def upload_resume(file: UploadFile = File(...)):
    """
    Securely uploads and validates a PDF resume.
    """
    logger.info(f"📂 Received file upload: {file.filename}")

    # --- SECURITY CHECK 1: Validate MIME Type (Quick Filter) ---
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF allowed.")

    # --- SECURITY CHECK 2: File Size & Magic Bytes ---
    MAX_SIZE = 5 * 1024 * 1024  # 5MB

    # We read the file content into memory. 
    # NOTE: For 5MB this is fine. For large files (e.g., videos), use chunked reading.
    content = await file.read()

    # 2.1: Check Real Size
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Max size is 5MB.")

    # 2.2: Check Magic Bytes (Signature)
    # PDF files start with %PDF (bytes: 25 50 44 46)
    if not content.startswith(b"%PDF"):
        logger.warning(f"⚠️ Security Block: Magic Bytes mismatch for {file.filename}")
        raise HTTPException(status_code=400, detail="Invalid file format. Not a valid PDF.")

    # --- PROCESSING: Text Extraction ---
    try:
        # Wrap the bytes in a stream for pypdf
        pdf_stream = io.BytesIO(content)
        
        # Validate parsing works (Defenses against malformed/exploit PDFs)
        pdf_reader = PdfReader(pdf_stream)
        
        text = ""
        for page in pdf_reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted

        # --- LOGIC CHECK: Is it a scanned image? ---
        if len(text.strip()) < 50:
            logger.warning(f"⚠️ OCR Required: File {file.filename} contains almost no text.")
            return {
                "filename": file.filename, 
                "status": "partial_success",
                "warning": "File appears to be a scanned image. OCR may be required.",
                "extracted_text": ""
            }

        logger.info(f"✅ Text extraction successful. Length: {len(text)} chars")
        return {
            "filename": file.filename, 
            "status": "success",
            "extracted_text": text[:4000] # Truncate for response
        }

    except Exception as e:
        logger.error(f"❌ PDF Parsing Failed: {e}")
        # Return 400, not 500, because the error is likely the user's bad file, not your server logic
        raise HTTPException(status_code=400, detail="File is corrupted or encrypted.")

@app.post("/analyze_stream")
async def analyze_stream(request: AnalyzeRequest):
    async def event_generator():
        try:
            # --- STEP 1: CONTEXT & SKILLS ---
            yield json.dumps({"type": "step", "step_id": 1, "message": "Extracting Data..."}) + "\n"

            # Format Skill Gaps for the LLM
            # We convert the JSON list into a readable string string
            skill_gaps_str = "No specific gaps identified."
            if request.skill_data and "missing" in request.skill_data:
                missing = request.skill_data["missing"]
                if missing:
                    skill_gaps_str = "\n".join(
                        [f"- {m['skill']} ({m.get('code', 'N/A')}): {m.get('gap', '')}" for m in missing]
                    )

            yield json.dumps({"type": "step", "step_id": 1, "message": "Reading Context..."}) + "\n"

            loop = asyncio.get_event_loop()
            detailed_skills_str = await loop.run_in_executor(None, get_detailed_skills, request.target_role)
            
            # --- STEP 2: MANAGER ANALYSIS ---
            yield json.dumps({"type": "step", "step_id": 2, "message": "Manager Analysis..."}) + "\n"
            
            raw_manager_res = await run_chain_with_fallback(
                manager_prompt,
                {
                    "role": request.target_role,
                    "detailed_skills": detailed_skills_str,
                    "resume_text": request.resume_text[:2000],
                    "skill_gaps": skill_gaps_str,
                    "question": request.question,
                    "student_answer": request.student_answer
                }, 
                "Manager Agent"
            )

            # 🔹 NEW: Parse the Thinking Trace vs. Final Feedback
            manager_thinking, manager_feedback_clean = parse_llm_response(raw_manager_res)

            # 🚀 NEW: Send the Thinking Trace IMMEDIATELY to the frontend
            yield json.dumps({
                "type": "partial_update", 
                "data": { "manager_thinking": manager_thinking }
            }) + "\n"

            # --- STEP 3: COACH REFINEMENT ---
            yield json.dumps({"type": "step", "step_id": 3, "message": "Coach Refinement..."}) + "\n"
            
            # 1. Call Coach Agent (Now returns Thinking + JSON)
            raw_coach_res = await run_chain_with_fallback(
                coach_prompt,
                {"manager_critique": manager_feedback_clean, 
                 "student_answer": request.student_answer,
                 "star_guide_content": STAR_GUIDE_TEXT},
                "Coach Agent"
            )
            
            # 2. ✂️ SPLIT DATA (Thinking vs. The Rest)
            coach_thinking, coach_potential_json = parse_llm_response(raw_coach_res)

            # 3. 🚀 SEND THINKING TRACE IMMEDIATELY
            yield json.dumps({
                "type": "partial_update", 
                "data": { "coach_thinking": coach_thinking }
            }) + "\n"
            
            # 4. 🧹 ROBUST JSON CLEANUP (The Fix)
            try:
                # A. Find the braces manually to ignore markdown filler
                start_index = coach_potential_json.find('{')
                end_index = coach_potential_json.rfind('}') + 1
                
                if start_index != -1 and end_index != -1:
                    json_str = coach_potential_json[start_index:end_index]
                    
                    # B. CRITICAL FIX: strict=False allows newlines inside the JSON strings
                    coach_data = json.loads(json_str, strict=False)
                    
                    coach_critique = coach_data.get("coach_critique", "Analysis provided.")
                    rewritten_answer = coach_data.get("rewritten_answer", "Answer generated.")
                else:
                    raise ValueError("No JSON brackets found in response.")

            except Exception as e:
                logger.error(f"Error parsing Coach JSON: {e}", exc_info=True)
                coach_critique = "Could not parse AI structure feedback."
                # Fallback: Strip the markdown tags manually so it's readable
                rewritten_answer = re.sub(r"```json\s*|\s*```", "", coach_potential_json).strip()

            # --- STEP 4: FINAL RESPONSE ---
            yield json.dumps({"type": "step", "step_id": 4, "message": "Drafting Response..."}) + "\n"
            
            await asyncio.sleep(0.05) 

            # 5. Add 'coach_thinking' to final payload
            final_data = {
                "manager_critique": manager_feedback_clean,
                "manager_thinking": manager_thinking,
                "coach_critique": coach_critique,
                "coach_thinking": coach_thinking,    # <--- Add this
                "rewritten_answer": rewritten_answer 
            }
            
            # 4. Send Result
            yield json.dumps({"type": "result", "data": final_data}) + "\n"

        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

@app.post("/match_skills")
async def match_skills(request: Request):
    logger.info("Received request for /match_skills")
    # 1. Parse Input
    data = await request.json()
    resume_text = data.get("resume_text", "")
    target_role = data.get("target_role", "Software Engineer")

    # 2. Define the Stream Generator
    async def generate_updates():
        try:
            logger.info(f"Starting skill match analysis for role: {target_role}")
            # === STEP 1: DB LOOKUP ===
            yield json.dumps({
                "type": "status", 
                "step": 1, 
                "message": f"Querying DB for '{target_role}'..."
            }) + "\n"
            
            # --- A. CONNECT TO DB ---
            conn = sqlite3.connect("skills.db")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = """
                SELECT 
                    COALESCE(s.title, rs.skill_title) as title, 
                    rs.skill_code, 
                    rs.proficiency,             -- ✅ CORRECT (New location)
                    GROUP_CONCAT(d.detail_item, '; ') as knowledge_list
                FROM role_skills rs 
                LEFT JOIN skill_definitions s ON rs.skill_code = s.skill_code 
                LEFT JOIN skill_details d ON rs.skill_code = d.skill_code
                WHERE rs.role = ? 
                GROUP BY rs.skill_code
                LIMIT 8
            """
            cursor.execute(query, (target_role,))
            rows = cursor.fetchall()
            conn.close()
            
            # --- B. BUILD detailed_skills LIST (CRITICAL: DO THIS BEFORE COUNTING) ---
            detailed_skills = []
            for row in rows:
                detailed_skills.append({
                    "skill": row["title"],
                    "code": row["skill_code"],
                    # This reads the column we just selected above
                    "level": row["proficiency"] if row["proficiency"] else "Standard", 
                    "required_knowledge": (row["knowledge_list"][:300] + "...") if row["knowledge_list"] else "General competency"
                })

            # Handle case where DB is empty
            if not detailed_skills:
                 logger.warning(f"No skills found for {target_role}, using default fallback.")
                 detailed_skills = [{"skill": "General Competency", "code": "N/A", "level": "Standard", "required_knowledge": "General professional skills"}]

            # --- C. NOW WE CAN SAFELY COUNT ---
            count = len(detailed_skills)
            yield json.dumps({
                "type": "status", 
                "step": 1, 
                "message": f"✔ Found {count} core competencies."
            }) + "\n"

            # === STEP 2: AI ANALYSIS ===
            yield json.dumps({
                "type": "status", 
                "step": 2, 
                "message": "Anonymizing data & Initializing AI Analyst..."
            }) + "\n"

            clean_resume_text = redact_pii(resume_text[:5000])

            # Simulate thinking steps for the UI trace
            await asyncio.sleep(0.2)
            yield json.dumps({"type": "status", "step": 2, "message": "Reading resume work history..."}) + "\n"
            
            await asyncio.sleep(0.2)
            yield json.dumps({"type": "status", "step": 2, "message": "Mapping skills to gaps..."}) + "\n"

            inputs = {
                "role": target_role,
                "role_desc": f"Professional {target_role}",
                "detailed_skills": json.dumps(detailed_skills, indent=2),
                "resume_text": clean_resume_text[:5000]
            }

            logger.info("Sending prompt to AI...")

            # Run the AI Chain
            ai_response_str = await run_chain_with_fallback(
                match_skills_prompt, 
                inputs, 
                step_name="Skill Matcher"
            )

            logger.info("AI Response received successfully.")

            # === STEP 3: FINALIZING ===
            yield json.dumps({
                "type": "status", 
                "step": 3, 
                "message": "Formatting final JSON report..."
            }) + "\n"
            
            analysis_result = extract_clean_json(ai_response_str)
            
            if not analysis_result:
                logger.error("Failed to parse JSON from AI response.")
                logger.debug(f"Raw AI Output: {ai_response_str}") # Helps debug bad JSON
                analysis_result = {
                    "matched_skills": [],
                    "missing_skills": [{"skill": "Error", "code": "N/A", "gap": "AI Analysis failed to parse."}]
                }

            # --- SEND FINAL RESULT ---
            logger.info("Stream complete. Sending results.")
            yield json.dumps({"type": "result", "data": analysis_result}) + "\n"

        except Exception as e:
            logger.error(f"Stream Error in match_skills: {e}", exc_info=True)
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    # Return the stream
    return StreamingResponse(generate_updates(), media_type="application/x-ndjson")