import os
import sqlite3
import json
import asyncio
import re  # <--- NEW: For cleaning JSON output
from dotenv import load_dotenv

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# AI Imports
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from google.api_core.exceptions import ResourceExhausted
from pydantic import BaseModel

from pypdf import PdfReader
import io
import database

class MatchRequest(BaseModel):
    resume_text: str
    target_role: str

# 1. SETUP
load_dotenv()
app = FastAPI(title="Poly-to-Pro", version="3.0.0")

database.init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        chain = prompt_template | gemini_llm | StrOutputParser()
        return await chain.ainvoke(inputs)
    except ResourceExhausted:
        print(f"⚠️ GEMINI QUOTA HIT ({step_name}). Switching to GROQ...")
        chain = prompt_template | groq_llm | StrOutputParser()
        return await chain.ainvoke(inputs)
    except Exception as e:
        print(f"⚠️ GEMINI ERROR ({step_name}): {e}. Switching to GROQ...")
        try:
            chain = prompt_template | groq_llm | StrOutputParser()
            return await chain.ainvoke(inputs)
        except Exception as groq_e:
            raise Exception(f"Both AI Engines Failed: {str(groq_e)}")

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

# 4. PROMPTS

# Manager Prompt (Standard Text Output)
manager_prompt = ChatPromptTemplate.from_template(
    """
    You are a Hiring Manager for {role}.
    OFFICIAL SPECS: {skills_context}
    RESUME: {resume_text}
    QUESTION: {question}
    ANSWER: {student_answer}
    
    Compare the answer to the specs. 
    Identify 2 specific gaps regarding terminology or technical depth.
    Be concise.
    """
)

# Coach Prompt (Structured JSON Output)
coach_prompt = ChatPromptTemplate.from_template(
    """
    You are a Career Coach.
    CRITIQUE: {manager_critique}
    ORIGINAL ANSWER: {student_answer}
    
    Task 1: Critique the original answer specifically on the STAR method (Situation, Task, Action, Result). Was it followed?
    Task 2: Rewrite the answer to be perfect, addressing the Manager's critique and using the STAR method strictly.
    
    You MUST output valid JSON only, with this exact structure:
    {{
        "coach_critique": "Your feedback on their use of STAR...",
        "rewritten_answer": "Situation: ... Task: ... Action: ... Result: ..."
    }}
    
    Do not add Markdown formatting (like ```json). Just the raw JSON.
    """
)

# 5. MODELS
class AnalyzeRequest(BaseModel):
    student_answer: str
    question: str
    target_role: str
    resume_text: str

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
        print(f"Error fetching questions: {e}")
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
        print(f"Error fetching roles: {e}")
        return [] # Return empty list on failure

@app.post("/upload_resume")
async def upload_resume(file: UploadFile = File(...)):
    content = await file.read()
    reader = PdfReader(io.BytesIO(content))
    text = "".join([p.extract_text() for p in reader.pages])
    return {"filename": file.filename, "extracted_text": text[:4000]}

@app.post("/analyze_stream")
async def analyze_stream(request: AnalyzeRequest):
    async def event_generator():
        try:
            # Step 1: Context
            yield json.dumps({"type": "step", "step_id": 1, "message": "Ingesting Context..."}) + "\n"
            await asyncio.sleep(0.5)
            
            loop = asyncio.get_event_loop()
            full_context = await loop.run_in_executor(None, get_full_role_context, request.target_role)

            # Step 2: Manager
            yield json.dumps({"type": "step", "step_id": 2, "message": "Manager Analysis..."}) + "\n"
            manager_res = await run_chain_with_fallback(
                manager_prompt,
                {
                    "role": request.target_role,
                    "skills_context": full_context,
                    "resume_text": request.resume_text,
                    "question": request.question,
                    "student_answer": request.student_answer
                }, 
                "Manager Agent"
            )

            # Step 3: Coach (Returns JSON String)
            yield json.dumps({"type": "step", "step_id": 3, "message": "Coach Refinement..."}) + "\n"
            coach_raw_res = await run_chain_with_fallback(
                coach_prompt,
                {"manager_critique": manager_res, "student_answer": request.student_answer},
                "Coach Agent"
            )
            
            # PARSE JSON RESPONSE
            # Clean up potential Markdown wrappers like ```json ... ```
            clean_json = re.sub(r"```json|```", "", coach_raw_res).strip()
            try:
                coach_data = json.loads(clean_json)
                coach_critique = coach_data.get("coach_critique", "Error parsing critique.")
                rewritten_answer = coach_data.get("rewritten_answer", "Error parsing answer.")
            except json.JSONDecodeError:
                # Fallback if AI fails to give JSON
                coach_critique = "Could not parse specific feedback."
                rewritten_answer = coach_raw_res

            # Step 4: Finish
            yield json.dumps({"type": "step", "step_id": 4, "message": "Finalizing..."}) + "\n"
            final_data = {
                "manager_critique": manager_res,
                "coach_critique": coach_critique,    # <--- NEW FIELD
                "rewritten_answer": rewritten_answer # <--- NEW FIELD
            }
            yield json.dumps({"type": "result", "data": final_data}) + "\n"

        except Exception as e:
            print(f"STREAM ERROR: {e}")
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

@app.post("/match_skills")
async def match_skills(request: MatchRequest):
    """
    1. Fetches official skills for the role from DB.
    2. Uses AI to compare Resume Text vs. Official Skills.
    3. Returns which skills are 'Matched' and which are 'Missing'.
    """
    try:
        # A. GET OFFICIAL SKILLS FROM DB
        conn = sqlite3.connect("skills.db")
        cursor = conn.cursor()
        
        # Get Description
        cursor.execute("SELECT description FROM role_descriptions WHERE role = ?", (request.target_role,))
        desc_row = cursor.fetchone()
        role_desc = desc_row[0] if desc_row else "Standard industry role."

        # Get Skills List
        cursor.execute("""
            SELECT s.title 
            FROM role_skills rs 
            JOIN skill_definitions s ON rs.skill_code = s.skill_code 
            WHERE rs.role = ? 
            LIMIT 8
        """, (request.target_role,))
        official_skills = [r[0] for r in cursor.fetchall()]
        conn.close()

        if not official_skills:
            return {"matched": [], "missing": [], "role_desc": role_desc}

        # B. AI ANALYSIS (Semantic Matching)
        # We ask the AI to strictly classify the skills based on the resume evidence.
        prompt_text = f"""
        You are a strict HR system. 
        
        TASK: Compare the Candidate's Resume against the Required Skills List.
        
        REQUIRED SKILLS: {json.dumps(official_skills)}
        
        CANDIDATE RESUME: 
        {request.resume_text[:4000]} (truncated)
        
        INSTRUCTIONS:
        1. For EACH skill in the "REQUIRED SKILLS" list, check if the resume contains evidence of it (direct mention or strong synonym).
        2. Output valid JSON only. Format:
        {{
            "matched_skills": ["Skill A", "Skill B"],
            "missing_skills": ["Skill C", "Skill D"]
        }}
        """

        # Call AI (using the lighter model for speed)
        llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0, google_api_key=os.getenv("GOOGLE_API_KEY"))
        ai_response = llm.invoke(prompt_text)
        
        # Parse JSON
        content = ai_response.content.replace("```json", "").replace("```", "").strip()
        result = json.loads(content)
        
        return {
            "matched": result.get("matched_skills", []),
            "missing": result.get("missing_skills", []),
            "role_desc": role_desc
        }

    except Exception as e:
        print(f"MATCH ERROR: {e}")
        # Fallback: Return all as missing if AI fails
        return {"matched": [], "missing": [], "role_desc": "Error analyzing skills."}