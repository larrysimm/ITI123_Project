import sqlite3
import pandas as pd
import os
import json
import requests
import logging

# --- LOGGER SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("backend.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "skills.db")
JSON_PATH = os.path.join(BASE_DIR, "questions.json")
EXCEL_FILE = os.path.join(BASE_DIR, "jobsandskills-skillsfuture-skills-framework-dataset.xlsx")

# Github URLs (Keep your existing URLs)
GITHUB_EXCEL_URL = "https://raw.githubusercontent.com/larrysimm/skills-data-static/main/jobsandskills-skillsfuture-skills-framework-dataset.xlsx"
STAR_FILE = os.path.join(BASE_DIR, "star_guide.pdf")
GITHUB_STAR_URL = "https://raw.githubusercontent.com/larrysimm/skills-data-static/main/star_guide.pdf"

def download_file(url, filepath, description):
    if os.path.exists(filepath):
        logger.info(f"📂 {description} found locally.")
        return
    logger.info(f"⬇️ Downloading {description}...")
    try:
        response = requests.get(url)
        response.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(response.content)
        logger.info(f"✅ Download complete: {filepath}")
    except Exception as e:
        logger.error(f"❌ Failed to download {description}: {e}")

def init_db():
    logger.info("🚀 Starting Database Initialization...")
    download_file(GITHUB_EXCEL_URL, EXCEL_FILE, "Excel Dataset")
    download_file(GITHUB_STAR_URL, STAR_FILE, "Star Guide")

    conn = sqlite3.connect(DB_FILE)
    
    try:
        if os.path.exists(EXCEL_FILE):
            logger.info("⚙️  Processing Excel Data...")
            xls = pd.ExcelFile(EXCEL_FILE)

            # --- 1. Descriptions ---
            if "Job Role_Description" in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name="Job Role_Description")
                # CLEANUP: Rename columns to match what your API expects
                df = df.rename(columns={
                    'Job Role': 'role',
                    'Job Role Description': 'description',
                    'Performance Expectation': 'expectations'
                })
                df[['role', 'description', 'expectations']].to_sql('role_descriptions', conn, if_exists='replace', index=False)
                logger.info("   -> Role Descriptions Loaded")

            # --- 2. Tasks ---
            if "Job Role_CWF_KT" in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name="Job Role_CWF_KT")
                df = df.rename(columns={
                    'Job Role': 'role',
                    'Critical Work Function': 'function',
                    'Key Tasks': 'task'
                })
                df[['role', 'function', 'task']].to_sql('role_tasks', conn, if_exists='replace', index=False)
                logger.info("   -> Role Tasks Loaded")

            # --- 3. Role-Skill Map (THIS FIXES YOUR ERROR) ---
            if "Job Role_TCS_CCS" in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name="Job Role_TCS_CCS")
                
                # 🛑 CRITICAL FIX: Rename "Proficiency Level" to "proficiency"
                df = df.rename(columns={
                    'Job Role': 'role',
                    'TSC_CCS Title': 'skill_title',
                    'TSC_CCS Code': 'skill_code',
                    'Proficiency Level': 'proficiency'  # <--- THIS IS THE FIX
                })
                
                # Select only the renamed columns to be safe
                df = df[['role', 'skill_title', 'skill_code', 'proficiency']]
                df.to_sql('role_skills', conn, if_exists='replace', index=False)
                logger.info("   -> Role-Skill Map Loaded (Error Fixed)")

            # --- 4. Skill Definitions ---
            if "TSC_CCS_Key" in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name="TSC_CCS_Key")
                df = df.rename(columns={
                    'TSC Code': 'skill_code',
                    'TSC_CCS Title': 'title',
                    'TSC_CCS Description': 'description'
                })
                df[['skill_code', 'title', 'description']].to_sql('skill_definitions', conn, if_exists='replace', index=False)
                logger.info("   -> Skill Definitions Loaded")

            # --- 5. Skill Details ---
            if "TSC_CCS_K&A" in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name="TSC_CCS_K&A")
                df = df.rename(columns={
                    'TSC_CCS Code': 'skill_code',
                    'Knowledge / Ability Items': 'detail_item'
                })
                df[['skill_code', 'detail_item']].to_sql('skill_details', conn, if_exists='replace', index=False)
                logger.info("   -> Skill Details Loaded")

    except Exception as e:
        logger.error(f"❌ Excel Processing Error: {e}", exc_info=True)

    # --- Create Questions Table ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS saved_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT UNIQUE, 
            category TEXT DEFAULT 'General'
        )
    """)

    try:
        if os.path.exists(JSON_PATH):
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                questions_data = json.load(f)
                
            logger.info(f"📂 Loading {len(questions_data)} questions from JSON...")
            
            # Insert questions (ignoring duplicates)
            for q in questions_data:
                # Handle cases where JSON is a list of strings OR list of objects
                q_text = q if isinstance(q, str) else q.get("question", "")
                
                if q_text:
                    conn.execute(
                        "INSERT OR IGNORE INTO saved_questions (question_text) VALUES (?)", 
                        (q_text,)
                    )
            logger.info("✅ Questions successfully seeded into DB.")
        else:
            logger.warning(f"⚠️ questions.json not found at {JSON_PATH}")
            
    except Exception as e:
        logger.error(f"❌ Error loading questions from JSON: {e}")
        
    conn.commit()
    conn.close()
    logger.info(f"✅ SUCCESS! Database ready.")

if __name__ == "__main__":
    init_db()