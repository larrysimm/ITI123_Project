# File: app/db/database.py
import sqlite3
import logging
import os
from app.core.config import settings

# --- LOGGER SETUP ---
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
# We use relative paths to find skills.db in the ROOT folder
# File is in: app/db/database.py
# .parent -> app/db/
# .parent -> app/
# .parent -> PROJECT_ROOT/
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(CURRENT_DIR)))
DB_FILE = settings.DB_PATH

# Fallback if the logic above fails in some envs, assume standard structure
if not os.path.exists(DB_FILE):
    # Try one level up (if running from root)
    DB_FILE = settings.DB_PATH

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row # Access columns by name
    return conn

# --- MOVED FROM MAIN.PY ---

def get_questions():
    """Fetches the list of questions from the database."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, question_text FROM saved_questions ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
        return [{"id": r["id"], "text": r["question_text"]} for r in rows]
    except Exception as e:
        logger.error(f"Error fetching questions: {e}", exc_info=True)
        return []

def get_roles():
    """Fetches a unique list of job roles."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT role FROM role_descriptions ORDER BY role ASC")
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"Error fetching roles: {e}", exc_info=True)
        return []

def get_full_role_context(role: str) -> str:
    """Fetches context for the Manager Agent."""
    try:
        conn = get_db_connection()
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
    except Exception as e:
        logger.error(f"Error fetching role context: {e}")
        return "Error loading context."

def get_detailed_skills(role_name):
    """
    Fetches explicit metadata (Role, Skill Code, Proficiency, Knowledge) 
    to force the AI to cite sources precisely.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
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

        skills_text = f"OFFICIAL SPECIFICATION FOR ROLE: {role_name.upper()}\n"
        skills_text += "=" * 40 + "\n\n"
        
        for row in rows:
            knowledge = (row["knowledge_list"][:200] + "...") if row["knowledge_list"] else "General application"
            level = row["proficiency"] if row["proficiency"] else "Standard"
            
            skills_text += f"Ref Code: [{row['skill_code']}]\n"
            skills_text += f"Skill Title: {row['title']}\n"
            skills_text += f"Required Level: {level}\n"
            skills_text += f"Key Knowledge: {knowledge}\n"
            skills_text += "-" * 20 + "\n"
        
        return skills_text

    except Exception as e:
        logger.error(f"Error fetching skills: {e}", exc_info=True)
        return "Standard industry skills."

def get_match_skills_data(target_role):
    """
    Extracted logic from the /match_skills endpoint.
    Returns a formatted list of skills for the AI.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # The exact query from your main.py
        query = """
            SELECT 
                COALESCE(s.title, rs.skill_title) as title, 
                rs.skill_code, 
                rs.proficiency,
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
        
        detailed_skills = []
        for row in rows:
            detailed_skills.append({
                "skill": row["title"],
                "code": row["skill_code"],
                "level": row["proficiency"] if row["proficiency"] else "Standard", 
                "required_knowledge": (row["knowledge_list"][:300] + "...") if row["knowledge_list"] else "General competency"
            })

        # Fallback logic moved here
        if not detailed_skills:
                logger.warning(f"No skills found for {target_role}, using default fallback.")
                detailed_skills = [{"skill": "General Competency", "code": "N/A", "level": "Standard", "required_knowledge": "General professional skills"}]
        
        return detailed_skills

    except Exception as e:
        logger.error(f"Error in get_match_skills_data: {e}", exc_info=True)
        return []