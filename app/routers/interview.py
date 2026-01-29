import json
import logging
import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas import AnalyzeRequest 
from app.services import ai_service
from app.db import database
from app.utils import parsers

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/analyze_stream")
async def analyze_stream(request: AnalyzeRequest):
    async def event_generator():
        try:
            # 1. Context
            yield json.dumps({"type": "step", "step_id": 1, "message": "Gathering Context..."}) + "\n"
            loop = asyncio.get_event_loop()
            detailed_skills_str = await loop.run_in_executor(None, database.get_detailed_skills, request.target_role)
            
            skill_gaps_str = "No specific gaps identified."
            if request.skill_data and "missing" in request.skill_data:
                missing = request.skill_data["missing"]
                if missing:
                    skill_gaps_str = "\n".join(
                        [f"- {m['skill']} ({m.get('code', 'N/A')}): {m.get('gap', '')}" for m in missing]
                    )

            yield json.dumps({"type": "step", "step_id": 1, "message": "Reading Context..."}) + "\n"

            # 2. Manager
            yield json.dumps({"type": "step", "step_id": 2, "message": "Manager Analysis..."}) + "\n"
            
            manager_res = await ai_service.run_chain_with_fallback(
                ai_service.get_prompt("manager_prompt"),
                {
                    "role": request.target_role,
                    "detailed_skills": detailed_skills_str,
                    "resume_text": request.resume_text[:10000],
                    "question": request.question,
                    "skill_gaps": skill_gaps_str,
                    "student_answer": request.student_answer
                },
                "Manager Agent"
            )
            
            # ✅ ROBUST PARSING
            man_thinking, man_feedback = ai_service.parse_llm_response(manager_res)
            
            # Send partial update (Thinking)
            yield json.dumps({"type": "partial_update", "data": {"manager_thinking": man_thinking}}) + "\n"

            # 3. Coach
            yield json.dumps({"type": "step", "step_id": 3, "message": "Coach Refinement..."}) + "\n"
            
            coach_res = await ai_service.run_chain_with_fallback(
                ai_service.get_prompt("coach_prompt"),
                {
                    "manager_critique": man_feedback, 
                    "student_answer": request.student_answer,
                    "star_guide_content": ai_service.STAR_GUIDE_TEXT,
                    "question": request.question,
                    "resume_text": request.resume_text[:10000],
                },
                "Coach Agent"
            )

            coach_thinking, coach_json_str = ai_service.parse_llm_response(coach_res)
            yield json.dumps({"type": "partial_update", "data": {"coach_thinking": coach_thinking}}) + "\n"

            # ✅ ROBUST JSON (Prevents Crash)
            # If parsing fails, we default to a safe dictionary, NOT None.
            coach_data = parsers.parse_json_safely(coach_json_str)
            if not coach_data:
                coach_data = {
                    "coach_critique": "Could not parse AI response.",
                    "rewritten_answer": coach_json_str # Show raw text as fallback
                }

            # 4. Final Result
            yield json.dumps({"type": "result", "data": {
                "manager_thinking": man_thinking,
                "manager_critique": man_feedback,
                "coach_thinking": coach_thinking,
                "coach_critique": coach_data.get("coach_critique", "No critique available."),
                "rewritten_answer": coach_data.get("rewritten_answer", "No answer generated.")
            }}) + "\n"

        except Exception as e:
            logger.error(f"Stream Error: {e}", exc_info=True)
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

@router.get("/roles")
def get_roles():
    """Fetches list of available roles for the dropdown."""
    return database.get_roles()

@router.get("/questions")
def get_questions():
    """Fetches list of interview questions."""
    return database.get_questions()