import json
import logging
import asyncio
import io

from fastapi import APIRouter, Request, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pypdf import PdfReader

from app.services import ai_service
from app.db import database
from app.utils import parsers

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/upload_resume")
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
        text = parsers.extract_text_from_pdf(content)

        # --- LOGIC CHECK: Is it a scanned image? ---
        if len(text.strip()) < 50:
            logger.warning(f"⚠️ OCR Required: File {file.filename} contains almost no text.")
            return {
                "filename": file.filename, 
                "status": "partial_success",
                "warning": "File appears to be a scanned image. OCR may be required.",
                "extracted_text": ""
            }
        
        logger.info("🤖 Verifying document content with AI...")
        
        # Call the new function in ai_service
        validation_result = await ai_service.validate_is_resume(text)
        
        if not validation_result.get("isValid", True):
            reason = validation_result.get("reason", "Unknown")
            logger.warning(f"⛔ AI Rejected Resume: {reason}")
            raise HTTPException(
                status_code=400, 
                detail=f"Uploaded file does not appear to be a resume. AI says: {reason}"
            )
        
        logger.info("✅ AI confirmed document is a valid resume.")
        logger.info(f"✅ Text extraction successful. Length: {len(text)} chars")
        return {
            "filename": file.filename, 
            "status": "success",
            "extracted_text": text[:10000] # Truncate for response
        }

    except HTTPException as he:
        # If we raised a specific HTTP error (like the AI rejection), 
        # let it pass through unmodified!
        raise he 

    except Exception as e:
        # Only catch UNEXPECTED crashes here (like PDF parser bugs)
        logger.error(f"❌ PDF Parsing Failed: {e}")
        raise HTTPException(status_code=400, detail="File is corrupted or encrypted.")

@router.post("/match_skills")
async def match_skills(request: Request):
    """
    Comparing Resume vs DB Standards
    """
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

            clean_resume_text = parsers.redact_pii(resume_text[:5000])

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
                ai_service.get_prompt("match_skills_prompt"), 
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
            
            analysis_result = parsers.extract_clean_json(ai_response_str)
            
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