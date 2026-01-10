import os
import asyncio
import re  
import json
import io
import logging
import random  

from typing import Optional, Dict, List
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pypdf import PdfReader
from .db import initialize 
from .db import database
from .core.config import settings, logger
from .services import ai_service

# --- LOGGER SETUP ---
logger = logging.getLogger(__name__)

# 1. SETUP
load_dotenv()
app = FastAPI(title="Poly-to-Pro", version="3.0.0")

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

    initialize.init_db()
    ai_service.init_ai_models()
    ai_service.load_star_guide()

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
    
    if client_secret != settings.API_SECRET:
        # Reject the request
        return json.dumps({"detail": "Unauthorized: Invalid Secret"}), 401
        
    response = await call_next(request)
    return response

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
    # ✅ CALL THE DB MODULE
    return database.get_questions()

@app.get("/roles")
def get_roles():
    # ✅ CALL THE DB MODULE
    return database.get_roles()

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
            detailed_skills_str = await loop.run_in_executor(None, database.get_detailed_skills, request.target_role)
            
            # --- STEP 2: MANAGER ANALYSIS ---
            yield json.dumps({"type": "step", "step_id": 2, "message": "Manager Analysis..."}) + "\n"
            
            raw_manager_res = await ai_service.run_chain_with_fallback(
                ai_service.manager_prompt,
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
            manager_thinking, manager_feedback_clean = ai_service.parse_llm_response(raw_manager_res)

            # 🚀 NEW: Send the Thinking Trace IMMEDIATELY to the frontend
            yield json.dumps({
                "type": "partial_update", 
                "data": { "manager_thinking": manager_thinking }
            }) + "\n"

            # --- STEP 3: COACH REFINEMENT ---
            yield json.dumps({"type": "step", "step_id": 3, "message": "Coach Refinement..."}) + "\n"
            
            # 1. Call Coach Agent (Now returns Thinking + JSON)
            raw_coach_res = await ai_service.run_chain_with_fallback(
                ai_service.oach_prompt,
                {"manager_critique": manager_feedback_clean, 
                 "student_answer": request.student_answer,
                 "star_guide_content": ai_service.STAR_GUIDE_TEXT},
                "Coach Agent"
            )
            
            # 2. ✂️ SPLIT DATA (Thinking vs. The Rest)
            coach_thinking, coach_potential_json = ai_service.parse_llm_response(raw_coach_res)

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
                    coach_data = ai_service.extract_clean_json(json_str, strict=False)
                    
                coach_data = {
                    "coach_critique": "Could not parse AI response.",
                    "rewritten_answer": json_str # Fallback to raw text
                }
                # Final Result
                yield json.dumps({"type": "result", "data": {
                    "manager_critique": manager_feedback_clean,
                    "coach_critique": coach_data.get("coach_critique"),
                    "rewritten_answer": coach_data.get("rewritten_answer")
                }}) + "\n"

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
            
            # --- B. BUILD detailed_skills LIST (CRITICAL: DO THIS BEFORE COUNTING) ---
            detailed_skills = database.get_match_skills_data(target_role)

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

            clean_resume_text = ai_service.redact_pii(resume_text[:5000])

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
            ai_response_str = await ai_service.run_chain_with_fallback(
                ai_service.match_skills_prompt, 
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
            
            analysis_result = ai_service.extract_clean_json(ai_response_str)
            
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