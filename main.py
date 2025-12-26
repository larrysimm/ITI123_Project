import os
import sqlite3
import json
import asyncio
from dotenv import load_dotenv

# FastAPI Imports
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# LangChain Imports
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq  # <--- NEW IMPORT
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from google.api_core.exceptions import ResourceExhausted # To catch the specific 429 error

# PDF Parsing
from pypdf import PdfReader
import io

# Database Init
import database 

# 1. SETUP
load_dotenv()
app = FastAPI(title="Poly-to-Pro (P2P)", version="2.1.0")

if not os.path.exists("skills.db"):
    database.init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DUAL ENGINE SETUP ---

# Primary: Gemini (Good reasoning, currently exhausted for you)
gemini_llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", 
    temperature=0.2,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# Backup: Groq (Super fast, running Llama 3)
groq_llm = ChatGroq(
    model_name="llama3-70b-8192", 
    temperature=0.2,
    groq_api_key=os.getenv("GROQ_API_KEY")
)

# 2. HELPER: SMART FALLBACK EXECUTION
async def run_chain_with_fallback(prompt_template, inputs, step_name="AI"):
    """
    Tries to run the prompt with Gemini. 
    If it hits a rate limit (429), it switches to Groq (Llama 3).
    """
    try:
        # Try Primary (Gemini)
        chain = prompt_template | gemini_llm | StrOutputParser()
        return await chain.ainvoke(inputs)
    
    except ResourceExhausted:
        print(f"⚠️ GEMINI QUOTA HIT during {step_name}. Switching to GROQ...")
        # Fallback to Secondary (Groq)
        chain = prompt_template | groq_llm | StrOutputParser()
        return await chain.ainvoke(inputs)
        
    except Exception as e:
        # If it's a different error (like auth failure), we also try Groq just in case
        print(f"⚠️ Error in {step_name}: {str(e)}. Retrying with GROQ...")
        try:
            chain = prompt_template | groq_llm | StrOutputParser()
            return await chain.ainvoke(inputs)
        except Exception as groq_error:
            # If both fail, then we crash
            print(f"❌ CRITICAL: Both engines failed. {str(groq_error)}")
            raise groq_error

# 3. MODELS & DATABASE (Standard Logic)
class AnalyzeRequest(BaseModel):
    student_answer: str
    question: str
    target_role: str
    resume_text: str

def get_full_role_context(role: str) -> str:
    db_file = "skills.db"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT description, expectations FROM role_descriptions WHERE role = ?", (role,))
    desc_row = cursor.fetchone()
    cursor.execute("SELECT task FROM role_tasks WHERE role = ? LIMIT 5", (role,))
    tasks = [r[0] for r in cursor.fetchall()]
    query = "SELECT s.title, s.description FROM role_skills rs JOIN skill_definitions s ON rs.skill_code = s.skill_code WHERE rs.role = ? LIMIT 10"
    cursor.execute(query, (role,))
    skills = cursor.fetchall()
    conn.close()
    
    if not desc_row: return f"Warning: No data for '{role}'."
    context = f"OFFICIAL JOB PROFILE: {role}\nDESC: {desc_row[0]}\nEXPECTATIONS: {desc_row[1]}\nKEY TASKS:\n"
    for t in tasks: context += f"- {t}\n"
    context += "\nCOMPETENCIES:\n"
    for t, d in skills: context += f"- {t}: {d}\n"
    return context

# 4. PROMPTS
manager_prompt = ChatPromptTemplate.from_template(
    """
    You are a strict Hiring Manager for {role}.
    OFFICIAL DATA: {skills_context}
    RESUME: {resume_text}
    QUESTION: {question}
    ANSWER: {student_answer}
    
    Identify 2 specific gaps where the candidate failed to match the 'KEY TASKS' or 'COMPETENCIES'.
    Be concise.
    """
)

coach_prompt = ChatPromptTemplate.from_template(
    """
    You are a Career Coach.
    MANAGER CRITIQUE: {manager_critique}
    STUDENT ANSWER: {student_answer}
    
    Rewrite the answer using the STAR method to address the critique.
    """
)

# 5. ENDPOINTS
@app.get("/")
async def root():
    return {
        "message": "Poly-to-Pro API is running!",
        "docs": "/docs",
        "status": "OK"
    }

@app.post("/upload_resume")
async def upload_resume(file: UploadFile = File(...)):
    content = await file.read()
    reader = PdfReader(io.BytesIO(content))
    text = "".join([p.extract_text() for p in reader.pages])
    return {"filename": file.filename, "extracted_text": text[:3000]}

@app.post("/analyze_stream")
async def analyze_stream(request: AnalyzeRequest):
    async def event_generator():
        try:
            # --- STEP 1 ---
            yield json.dumps({"type": "step", "step_id": 1, "message": "Ingesting context..."}) + "\n"
            await asyncio.sleep(0.5) 
            
            loop = asyncio.get_event_loop()
            full_context = await loop.run_in_executor(None, get_full_role_context, request.target_role)

            # --- STEP 2 (With Smart Fallback) ---
            yield json.dumps({"type": "step", "step_id": 2, "message": "Analyzing gaps..."}) + "\n"
            
            # We call our new helper function instead of calling Gemini directly
            manager_res = await run_chain_with_fallback(
                manager_prompt, 
                {
                    "role": request.target_role,
                    "skills_context": full_context,
                    "resume_text": request.resume_text,
                    "question": request.question,
                    "student_answer": request.student_answer
                },
                step_name="Manager Analysis"
            )

            # --- STEP 3 (With Smart Fallback) ---
            yield json.dumps({"type": "step", "step_id": 3, "message": "Drafting feedback..."}) + "\n"
            
            coach_res = await run_chain_with_fallback(
                coach_prompt,
                {
                    "manager_critique": manager_res,
                    "student_answer": request.student_answer
                },
                step_name="Coach Refinement"
            )

            # --- STEP 4 ---
            yield json.dumps({"type": "step", "step_id": 4, "message": "Finalizing..."}) + "\n"
            
            final_response = {
                "manager_critique": manager_res,
                "coach_feedback": coach_res,
                "model_answer": "See Coach Feedback"
            }
            yield json.dumps({"type": "result", "data": final_response}) + "\n"
            
        except Exception as e:
            print(f"STREAM ERROR: {str(e)}")
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)