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
        logging.FileHandler("backend.log"), # Log to file
        logging.StreamHandler()             # Log to console
    ]
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "skills.db")
JSON_PATH = os.path.join(BASE_DIR, "questions.json")

EXCEL_FILE = os.path.join(BASE_DIR, "jobsandskills-skillsfuture-skills-framework-dataset.xlsx")
GITHUB_EXCEL_URL = "https://raw.githubusercontent.com/larrysimm/skills-data-static/main/jobsandskills-skillsfuture-skills-framework-dataset.xlsx"
STAR_FILE = os.path.join(BASE_DIR, "star_guide.pdf")
GITHUB_STAR_URL = "https://raw.githubusercontent.com/larrysimm/skills-data-static/main/star_guide.pdf"

def download_excel_from_github():
    if os.path.exists(EXCEL_FILE):
        logger.info(f"📂 Excel file found locally: {EXCEL_FILE}")
        return

    logger.info(f"⬇️ Downloading dataset from GitHub...")
    try:
        response = requests.get(GITHUB_EXCEL_URL)
        response.raise_for_status()
        with open(EXCEL_FILE, "wb") as f:
            f.write(response.content)
        logger.info(f"✅ Download complete. Saved to: {EXCEL_FILE}")
    except Exception as e:
        logger.error(f"❌ Failed to download file: {e}", exc_info=True)

def download_star_from_github():
    if os.path.exists(STAR_FILE):
        logger.info(f"📂 STAR guide found locally: {STAR_FILE}")
        return

    logger.info(f"⬇️ Downloading star guide from GitHub...")
    try:
        response = requests.get(GITHUB_STAR_URL)
        response.raise_for_status()
        with open(STAR_FILE, "wb") as f:
            f.write(response.content)
        logger.info(f"✅ Download complete. Saved to: {STAR_FILE}")
    except Exception as e:
        logger.error(f"❌ Failed to download file: {e}", exc_info=True)

def init_db():
    logger.info("🚀 Starting Database Initialization...")

    # 1. Download Files
    download_excel_from_github()
    download_star_from_github()

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        if os.path.exists(EXCEL_FILE):
            logger.info("⚙️  Processing Excel Data directly into SQLite...")

            # OPTIMIZATION: Load the Excel file structure once
            try:
                xls = pd.ExcelFile(EXCEL_FILE)

                # 1. Descriptions (Sheet: Job Role_Description)
                if "Job Role_Description" in xls.sheet_names:
                    df_desc = pd.read_excel(xls, sheet_name="Job Role_Description")
                    df_desc = df_desc[['Job Role', 'Job Role Description', 'Performance Expectation']]
                    df_desc.columns = ['role', 'description', 'expectations']
                    df_desc.to_sql('role_descriptions', conn, if_exists='replace', index=False)
                    logger.info("   -> Role Descriptions Loaded")
                else:
                    logger.warning("   ⚠️ Sheet 'Job Role_Description' missing.")

                # 2. Tasks (Sheet: Job Role_CWF_KT)
                if "Job Role_CWF_KT" in xls.sheet_names:
                    df_tasks = pd.read_excel(xls, sheet_name="Job Role_CWF_KT")
                    df_tasks = df_tasks[['Job Role', 'Critical Work Function', 'Key Tasks']]
                    df_tasks.columns = ['role', 'function', 'task']
                    df_tasks.to_sql('role_tasks', conn, if_exists='replace', index=False)
                    logger.info("   -> Role Tasks Loaded")
                else:
                    logger.warning("   ⚠️ Sheet 'Job Role_CWF_KT' missing.")

                # 3. Role-Skill Map (Sheet: Job Role_TCS_CCS)
                if "Job Role_TCS_CCS" in xls.sheet_names:
                    df_map = pd.read_excel(xls, sheet_name="Job Role_TCS_CCS")
                    df_map = df_map[['Job Role', 'TSC_CCS Title', 'TSC_CCS Code', 'Proficiency Level']]
                    df_map.columns = ['role', 'skill_title', 'skill_code', 'proficiency'] 
                    df_map.to_sql('role_skills', conn, if_exists='replace', index=False)
                    logger.info("   -> Role-Skill Map Loaded")
                else:
                    logger.warning("   ⚠️ Sheet 'Job Role_TCS_CCS' missing.")

                # 4. Skill Definitions (Sheet: TSC_CCS_Key)
                if "TSC_CCS_Key" in xls.sheet_names:
                    df_info = pd.read_excel(xls, sheet_name="TSC_CCS_Key")
                    df_info = df_info[['TSC Code', 'TSC_CCS Title', 'TSC_CCS Description']]
                    df_info.columns = ['skill_code', 'title', 'description']
                    df_info.to_sql('skill_definitions', conn, if_exists='replace', index=False)
                    logger.info("   -> Skill Definitions Loaded")
                else:
                    logger.warning("   ⚠️ Sheet 'TSC_CCS_Key' missing.")

                # 5. Skill Details (Sheet: TSC_CCS_K&A)
                if "TSC_CCS_K&A" in xls.sheet_names:
                    df_ka = pd.read_excel(xls, sheet_name="TSC_CCS_K&A")
                    df_ka = df_ka[['TSC_CCS Code', 'Knowledge / Ability Items']]
                    df_ka.columns = ['skill_code', 'detail_item']
                    df_ka.to_sql('skill_details', conn, if_exists='replace', index=False)
                    logger.info("   -> Skill Details Loaded")
                else:
                    logger.warning("   ⚠️ Sheet 'TSC_CCS_K&A' missing.")
            
            except Exception as e:
                logger.error(f"❌ Error reading Excel file: {e}", exc_info=True)

        else:
            logger.warning(f"⚠️ Excel File missing at {EXCEL_FILE}, skipping DB population.")

        # --- Question Bank ---
        logger.info("📝 Initializing Question Bank...")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT UNIQUE, 
            category TEXT DEFAULT 'General'
        )
        """)
        
        # Load JSON if exists
        if os.path.exists(JSON_PATH):
            try:
                with open(JSON_PATH, "r", encoding="utf-8") as f:
                    q_data = json.load(f)
                    count = 0
                    for q in q_data:
                        try:
                            cursor.execute(
                                "INSERT OR IGNORE INTO saved_questions (question_text, category) VALUES (?, ?)", 
                                (q["text"], q.get("category", "General"))
                            )
                            if cursor.rowcount > 0: # Only count if actually inserted
                                count += 1
                        except: pass
                    logger.info(f"   -> Loaded {count} new questions from JSON.")
            except Exception as e:
                 logger.error(f"   ⚠️ Error loading questions.json: {e}", exc_info=True)
        
        conn.commit()
        logger.info(f"✅ SUCCESS! Database ready at: {DB_FILE}")

    except Exception as e:
        logger.critical(f"❌ DATABASE CRITICAL ERROR: {e}", exc_info=True)
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()