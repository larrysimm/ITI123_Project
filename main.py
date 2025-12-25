import os
import sqlite3
from dotenv import load_dotenv

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# LangChain Imports
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# PDF Parsing
from pypdf import PdfReader
import io

# Database Init
import database

# 1. SETUP
load_dotenv()
app = FastAPI(title="Poly-to-Pro (P2P)", version="2.0.0")

# Auto-build database on startup
if not os.path.exists("skills.db"):
    database.init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Gemini
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# 2. MODELS
class AnalyzeRequest(BaseModel):
    student_answer: str
    question: str
    target_role: str
    resume_text: str

class AnalyzeResponse(BaseModel):
    manager_critique: str
    coach_feedback: str
    model_answer: str

# 3. HELPER: THE "FULL CONTEXT" RETRIEVER
def get_full_role_context(role: str) -> str:
    """
    Queries all 5 tables to build a massive context profile for the role.
    """
    db_file = "skills.db"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    # A. Get Role Description & Expectations
    cursor.execute("SELECT description, expectations FROM role_descriptions WHERE role = ?", (role,))
    desc_row = cursor.fetchone()
    
    # B. Get Top 5 Key Tasks
    cursor.execute("SELECT task FROM role_tasks WHERE role = ? LIMIT 5", (role,))
    tasks = [r[0] for r in cursor.fetchall()]
    
    # C. Get Top 10 Skills with Descriptions
    # Join role_skills with skill_definitions
    query = """
        SELECT s.title, s.description 
        FROM role_skills rs
        JOIN skill_definitions s ON rs.skill_code = s.skill_code
        WHERE rs.role = ?
        LIMIT 10
    """
    cursor.execute(query, (role,))
    skills = cursor.fetchall()
    
    conn.close()
    
    # D. Format the Context for the AI
    if not desc_row:
        return f"Warning: No official data found for role '{role}'."
        
    context = f"""
    OFFICIAL JOB PROFILE: {role}
    --------------------------------
    DESCRIPTION: {desc_row[0]}
    
    PERFORMANCE EXPECTATIONS:
    {desc_row[1]}
    
    KEY TASKS (Daily Duties):
    """
    for t in tasks:
        context += f"- {t}\n"
        
    context += "\nREQUIRED COMPETENCIES (SkillsFuture):\n"
    for title, desc in skills:
        context += f"- {title}: {desc}\n"
        
    return context

# 4. AGENTS
manager_prompt = ChatPromptTemplate.from_template(
    """
    You are a strict Hiring Manager for the role of {role}.
    
    OFFICIAL GOVERNMENT DATA FOR THIS ROLE:
    {skills_context}
    
    CANDIDATE RESUME:
    {resume_text}
    
    INTERVIEW QUESTION:
    {question}
    
    ANSWER:
    {student_answer}
    
    TASK:
    1. Compare the candidate's answer against the "KEY TASKS" and "COMPETENCIES" above.
    2. Did they describe tasks that match the official job description?
    3. Did they use the correct terminology from the Competencies list?
    
    OUTPUT:
    - KEYWORDS MISSED: [List specific terms]
    - TECHNICAL GAPS: [Explain if their answer fits the official job description or if it sounds too generic]
    """
)
manager_chain = manager_prompt | llm | StrOutputParser()

coach_prompt = ChatPromptTemplate.from_template(
    """
    You are a Career Coach.
    
    MANAGER'S CRITIQUE:
    {manager_critique}
    
    STUDENT ANSWER:
    {student_answer}
    
    TASK:
    Rewrite the student's answer using the STAR Method. 
    Crucially, inject the 'KEY TASKS' terminology identified by the Manager to make it sound professional.
    
    OUTPUT:
    - STAR IMPROVEMENT:
    - MODEL ANSWER:
    """
)
coach_chain = coach_prompt | llm | StrOutputParser()

# 5. ENDPOINTS
@app.post("/upload_resume")
async def upload_resume(file: UploadFile = File(...)):
    content = await file.read()
    reader = PdfReader(io.BytesIO(content))
    text = "".join([p.extract_text() for p in reader.pages])
    return {"filename": file.filename, "extracted_text": text[:3000]}

@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_answer(request: AnalyzeRequest):
    # 1. Get massive context
    full_context = get_full_role_context(request.target_role)
    
    # 2. Manager Agent
    manager_res = await manager_chain.ainvoke({
        "role": request.target_role,
        "skills_context": full_context,
        "resume_text": request.resume_text,
        "question": request.question,
        "student_answer": request.student_answer
    })
    
    # 3. Coach Agent
    coach_res = await coach_chain.ainvoke({
        "manager_critique": manager_res,
        "student_answer": request.student_answer
    })
    
    return AnalyzeResponse(
        manager_critique=manager_res,
        coach_feedback=coach_res,
        model_answer="See Coach Feedback"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)