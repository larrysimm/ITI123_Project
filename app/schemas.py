from pydantic import BaseModel
from typing import Optional, Dict

class AnalyzeRequest(BaseModel):
    student_answer: str
    question: str
    target_role: str
    resume_text: str
    skill_data: Optional[Dict] = None

class MatchRequest(BaseModel):
    resume_text: str
    target_role: str