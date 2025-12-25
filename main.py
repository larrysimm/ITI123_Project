import os
from typing import List, Optional
from dotenv import load_dotenv

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- UPDATED IMPORTS FOR GOOGLE GEMINI ---
# --- UPDATED IMPORTS FOR LANGCHAIN v0.1+ ---
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# PDF Parsing
from pypdf import PdfReader
import io

# 1. SETUP & CONFIGURATION
# ---------------------------------------------------------
load_dotenv()

# Verify API Key
if not os.getenv("GOOGLE_API_KEY"):
    print("⚠️ WARNING: GOOGLE_API_KEY not found in environment variables.")

app = FastAPI(
    title="Poly-to-Pro (P2P) API",
    description="Dual-Agent Interview Validator Backend (Powered by Gemini)",
    version="1.0.0"
)

# CORS - Allow your React App to talk to this Backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, change to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- INITIALIZE GEMINI LLM ---
# We use 'gemini-1.5-flash' for speed (low latency < 8s) and good reasoning.
# You can also use 'gemini-1.5-pro' for higher quality but slightly slower speed.
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    temperature=0.2,
    convert_system_message_to_human=True # Helps with some specific prompting nuances
)


# 2. DATA MODELS (Pydantic)
# ---------------------------------------------------------
class AnalyzeRequest(BaseModel):
    student_answer: str
    question: str
    target_role: str
    resume_text: str

class AnalyzeResponse(BaseModel):
    manager_critique: str
    coach_feedback: str
    model_answer: str


# 3. HELPER FUNCTIONS
# ---------------------------------------------------------
def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extracts raw text from a PDF file."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid PDF: {str(e)}")

def get_skills_context(role: str) -> str:
    """
    Simulates the RAG Retrieval Step.
    """
    # Mock Database - In production, this queries ChromaDB
    skills_db = {
        "Audit Associate": (
            "Required Skills: Financial Reconciliation, Regulatory Compliance (SFRS), "
            "Data Analytics (Excel/Tableau), Internal Controls, Audit Documentation."
        ),
        "Software Engineer": (
            "Required Skills: CI/CD Pipelines, RESTful APIs, Cloud Infrastructure (AWS/GCP), "
            "Agile Scrum, Version Control (Git), Unit Testing."
        ),
    }
    
    return skills_db.get(role, "Required Skills: Professional Communication, Industry Standard Terminology, Problem Solving.")


# 4. AGENT DEFINITIONS (LangChain)
# ---------------------------------------------------------

# --- AGENT A: THE HIRING MANAGER (Technical Validator) ---
manager_prompt = ChatPromptTemplate.from_template(
    """
    You are a strict Hiring Manager interviewing a candidate for the role of {role}.
    
    CONTEXT DATA (Government Framework):
    {skills_context}
    
    CANDIDATE RESUME SUMMARY:
    {resume_text}
    
    INTERVIEW QUESTION:
    {question}
    
    CANDIDATE ANSWER:
    {student_answer}
    
    YOUR TASK:
    Perform a Technical Audit of the answer.
    1. Check if the candidate used the specific keywords from the CONTEXT DATA.
    2. Identify if they used vague language (e.g., "checked the numbers") instead of industry terms (e.g., "Reconciliation").
    3. Be critical. Do not give praise. Only point out the GAPS.
    
    OUTPUT FORMAT:
    - MISSING KEYWORDS: [List specific terms they missed]
    - TECHNICAL CRITIQUE: [2-3 sentences explaining why the answer is technically weak]
    """
)
manager_chain = manager_prompt | llm | StrOutputParser()


# --- AGENT B: THE CAREER COACH (Behavioral Strategist) ---
coach_prompt = ChatPromptTemplate.from_template(
    """
    You are a supportive Career Coach helping a Polytechnic graduate.
    
    INTERVIEW QUESTION:
    {question}
    
    CANDIDATE ANSWER:
    {student_answer}
    
    TECHNICAL CRITIQUE (From Hiring Manager):
    {manager_critique}
    
    YOUR TASK:
    1. Acknowledge the Manager's critique but focus on STRUCTURE.
    2. Rewrite the candidate's answer using the STAR Method (Situation, Task, Action, Result).
    3. You MUST incorporate the missing technical keywords identified by the Manager.
    4. Do NOT invent new experiences. Use the facts provided in the candidate's answer.
    
    OUTPUT FORMAT:
    - STAR BREAKDOWN: (Briefly label S, T, A, R)
    - GOLDEN MODEL ANSWER: (The perfect paragraph to say in the interview)
    """
)
coach_chain = coach_prompt | llm | StrOutputParser()


# 5. API ENDPOINTS
# ---------------------------------------------------------

@app.get("/")
async def root():
    return {"status": "active", "system": "Poly-to-Pro Validator Engine (Gemini)"}

@app.post("/upload_resume")
async def upload_resume(file: UploadFile = File(...)):
    """
    Receives a PDF, extracts text, and returns it to the frontend.
    """
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="File must be a PDF")
    
    content = await file.read()
    text = extract_text_from_pdf(content)
    
    # Return first 2000 chars to avoid token limits
    return {"filename": file.filename, "extracted_text": text[:2000]}

@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_answer(request: AnalyzeRequest):
    """
    The Core Dual-Agent Logic.
    """
    
    # Step 1: Retrieve Context (Simulated RAG)
    skills_context = get_skills_context(request.target_role)
    
    # Step 2: Run Agent A (Manager)
    manager_feedback = await manager_chain.ainvoke({
        "role": request.target_role,
        "skills_context": skills_context,
        "resume_text": request.resume_text,
        "question": request.question,
        "student_answer": request.student_answer
    })
    
    # Step 3: Run Agent B (Coach)
    coach_feedback_raw = await coach_chain.ainvoke({
        "question": request.question,
        "student_answer": request.student_answer,
        "manager_critique": manager_feedback
    })
    
    return AnalyzeResponse(
        manager_critique=manager_feedback,
        coach_feedback=coach_feedback_raw,
        model_answer="Refer to Coach Feedback for the Golden Answer." 
    )

# 6. RUNNER
# ---------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)