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

from pypdf import PdfReader
import io
import database

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

def get_detailed_skills(role_name):
    """Helper to fetch skills with proficiency and knowledge from DB."""
    try:
        conn = sqlite3.connect("skills.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get Skills + Proficiency + Aggregated Knowledge
        query = """
            SELECT 
                s.title, 
                s.proficiency,
                GROUP_CONCAT(d.detail_item, '; ') as knowledge_list
            FROM role_skills rs 
            JOIN skill_definitions s ON rs.skill_code = s.skill_code 
            LEFT JOIN skill_details d ON s.skill_code = d.skill_code
            WHERE rs.role = ? 
            GROUP BY s.skill_code
            LIMIT 5
        """
        cursor.execute(query, (role_name,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "Standard industry skills for this role."

        # Format as a readable string for the LLM
        skills_text = ""
        for row in rows:
            knowledge = (row["knowledge_list"][:150] + "...") if row["knowledge_list"] else "General competency"
            skills_text += f"- {row['title']} (Level: {row['proficiency'] or 'Standard'}): Requires knowledge of {knowledge}\n"
        
        return skills_text

    except Exception:
        return "Standard industry skills."

# 4. PROMPTS

# Manager Prompt (Standard Text Output)
manager_prompt = ChatPromptTemplate.from_template(
    """
    You are a skeptcial, high-standards Hiring Manager for a {role} position.
    
    THE ROLE REQUIRES THESE SPECIFIC COMPETENCIES (from our internal spec):
    {detailed_skills}
    
    CANDIDATE'S RESUME SUMMARY:
    {resume_text}
    
    INTERVIEW QUESTION:
    "{question}"
    
    CANDIDATE'S ANSWER:
    "{student_answer}"
    
    YOUR TASK:
    Evaluate this answer strictly. 
    1. **Skill Evidence:** Did they demonstrate the specific proficiencies listed above? (e.g. if the role needs 'Level 4 Data Analysis', did their story show that complexity, or was it basic?)
    2. **Depth:** Is the answer vague or does it show specific technical knowledge mentioned in the requirements?
    3. **Verdict:** Be direct. If they missed a key technical requirement, say it.
    
    Keep your feedback professional but critical (approx 100 words). Focus on the *content* and *competence*, not just the communication style.
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

# Match Skills Prompt (Structured JSON Output)
match_skills_prompt = ChatPromptTemplate.from_template(
    """
    You are a Senior HR Auditor performing a Skill Gap Analysis.
    
    JOB ROLE: {role}
    DESCRIPTION: {role_desc}
    
    REQUIRED COMPETENCIES (With Proficiency & Knowledge):
    {detailed_skills}
    
    CANDIDATE RESUME: 
    {resume_text}
    
    INSTRUCTIONS:
    1. Compare the Resume against the REQUIRED COMPETENCIES.
    2. Strict Check: If a skill requires "Level 4" or specific knowledge (e.g., "AsyncIO"), and the resume is vague, mark it as a GAP.
    3. Output valid JSON only:
    {{
        "matched_skills": [ {{ "skill": "Name", "reason": "Evidence found..." }} ],
        "missing_skills": [ {{ "skill": "Name", "gap": "Missing specific evidence of..." }} ]
    }}
    """
)

# 5. MODELS
class AnalyzeRequest(BaseModel):
    student_answer: str
    question: str
    target_role: str
    resume_text: str

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
            yield json.dumps({"type": "step", "step_id": 1, "message": "Fetching Skill Matrix..."}) + "\n"
            await asyncio.sleep(0.5)
            
            # --- UPDATED: Use the specific Skill Matrix Helper ---
            loop = asyncio.get_event_loop()
            detailed_skills_str = await loop.run_in_executor(None, get_detailed_skills, request.target_role)

            # Step 2: Manager Analysis
            yield json.dumps({"type": "step", "step_id": 2, "message": "Manager analyzing proficiency..."}) + "\n"
            
            manager_res = await run_chain_with_fallback(
                manager_prompt,
                {
                    "role": request.target_role,
                    "detailed_skills": detailed_skills_str,  # <--- Pass the DB skills here
                    "resume_text": request.resume_text[:2000], # Truncate to save tokens
                    "question": request.question,
                    "student_answer": request.student_answer
                }, 
                "Manager Agent"
            )

            # Step 3: Coach Refinement (Returns JSON String)
            yield json.dumps({"type": "step", "step_id": 3, "message": "Coach optimizing structure..."}) + "\n"
            
            coach_raw_res = await run_chain_with_fallback(
                coach_prompt,
                {"manager_critique": manager_res, "student_answer": request.student_answer},
                "Coach Agent"
            )
            
            # PARSE JSON RESPONSE
            clean_json = re.sub(r"```json|```", "", coach_raw_res).strip()
            try:
                coach_data = json.loads(clean_json)
                coach_critique = coach_data.get("coach_critique", "Error parsing critique.")
                rewritten_answer = coach_data.get("rewritten_answer", "Error parsing answer.")
            except json.JSONDecodeError:
                coach_critique = "Could not parse specific feedback."
                rewritten_answer = coach_raw_res

            # Step 4: Finish
            yield json.dumps({"type": "step", "step_id": 4, "message": "Finalizing..."}) + "\n"
            
            final_data = {
                "manager_critique": manager_res,
                "coach_critique": coach_critique,    
                "rewritten_answer": rewritten_answer 
            }
            yield json.dumps({"type": "result", "data": final_data}) + "\n"

        except Exception as e:
            print(f"STREAM ERROR: {e}")
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

@app.post("/match_skills")
async def match_skills(request: MatchRequest):
    try:
        # A. FETCH DATA FROM DB
        conn = sqlite3.connect("skills.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get Role Desc
        cursor.execute("SELECT description FROM role_descriptions WHERE role = ?", (request.target_role,))
        desc_row = cursor.fetchone()
        role_desc = desc_row["description"] if desc_row else f"A professional {request.target_role} role."

        # Get Skills + Proficiency + Knowledge
        query = """
            SELECT 
                s.title, 
                s.skill_code, 
                s.proficiency,
                GROUP_CONCAT(d.detail_item, '; ') as knowledge_list
            FROM role_skills rs 
            JOIN skill_definitions s ON rs.skill_code = s.skill_code 
            LEFT JOIN skill_details d ON s.skill_code = d.skill_code
            WHERE rs.role = ? 
            GROUP BY s.skill_code
            LIMIT 8
        """
        cursor.execute(query, (request.target_role,))
        rows = cursor.fetchall()
        
        detailed_skills = []
        for row in rows:
            detailed_skills.append({
                "skill": row["title"],
                "level": row["proficiency"] if row["proficiency"] else "Standard",
                "required_knowledge": (row["knowledge_list"][:300] + "...") if row["knowledge_list"] else "General competency"
            })
        
        conn.close()

        # Fallback if DB is empty
        if not detailed_skills:
            detailed_skills = [{"skill": f"{request.target_role} Core Skills", "level": "Standard", "required_knowledge": "General"}]

        # B. RUN DUAL LLM WITH FALLBACK
        # We use the same helper function you used for the streaming analysis
        inputs = {
            "role": request.target_role,
            "role_desc": role_desc,
            "detailed_skills": json.dumps(detailed_skills, indent=2),
            "resume_text": request.resume_text[:5000]
        }

        ai_response_str = await run_chain_with_fallback(
            match_skills_prompt, 
            inputs, 
            step_name="Skill Matcher"
        )
        
        # C. PARSE JSON
        clean_json = re.sub(r"```json|```", "", ai_response_str).strip()
        try:
            result = json.loads(clean_json)
        except json.JSONDecodeError:
            result = {"matched_skills": [], "missing_skills": []}
        
        return {
            "matched": result.get("matched_skills", []),
            "missing": result.get("missing_skills", []),
            "role_desc": role_desc
        }

    except Exception as e:
        print(f"MATCH ERROR: {e}")
        return {"matched": [], "missing": [], "role_desc": "Error analyzing skills."}