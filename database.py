import sqlite3
import pandas as pd
import os

# --- CONFIGURATION: EXACT FILE NAMES ---
# We map your uploaded files to database tables
FILES = {
    "role_desc": "jobsandskills-skillsfuture-skills-framework-dataset.xlsx - Job Role_Description.csv",
    "role_tasks": "jobsandskills-skillsfuture-skills-framework-dataset.xlsx - Job Role_CWF_KT.csv",
    "role_skills": "jobsandskills-skillsfuture-skills-framework-dataset.xlsx - Job Role_TCS_CCS.csv",
    "skill_info": "jobsandskills-skillsfuture-skills-framework-dataset.xlsx - TSC_CCS_Key.csv",
    "skill_details": "jobsandskills-skillsfuture-skills-framework-dataset.xlsx - TSC_CCS_K&A.csv"
}

DB_FILE = "skills.db"

def init_db():
    print("🚀 Starting Database Build Process...")
    
    # 1. VALIDATE FILES EXIST
    missing_files = [f for f in FILES.values() if not os.path.exists(f)]
    if missing_files:
        print("❌ CRITICAL ERROR: The following files are missing:")
        for f in missing_files:
            print(f"   - {f}")
        print("Please upload all 5 CSVs to the backend folder.")
        return

    conn = sqlite3.connect(DB_FILE)
    
    try:
        # --- TABLE 1: JOB ROLE DESCRIPTIONS ---
        print("1️⃣  Processing Role Descriptions...")
        df_desc = pd.read_csv(FILES["role_desc"])
        # Columns: Sector, Track, Job Role, Job Role Description, Performance Expectation
        df_desc = df_desc[['Job Role', 'Job Role Description', 'Performance Expectation']]
        df_desc.columns = ['role', 'description', 'expectations']
        df_desc.to_sql('role_descriptions', conn, if_exists='replace', index=False)

        # --- TABLE 2: JOB ROLE TASKS (Critical Work Functions) ---
        print("2️⃣  Processing Role Tasks...")
        df_tasks = pd.read_csv(FILES["role_tasks"])
        # Columns: Job Role, Critical Work Function, Key Tasks
        df_tasks = df_tasks[['Job Role', 'Critical Work Function', 'Key Tasks']]
        df_tasks.columns = ['role', 'function', 'task']
        df_tasks.to_sql('role_tasks', conn, if_exists='replace', index=False)

        # --- TABLE 3: ROLE TO SKILL MAPPING ---
        print("3️⃣  Processing Role-Skill Maps...")
        df_map = pd.read_csv(FILES["role_skills"])
        # Columns: Job Role, TSC_CCS Title, TSC_CCS Code, Proficiency Level
        df_map = df_map[['Job Role', 'TSC_CCS Title', 'TSC_CCS Code']]
        df_map.columns = ['role', 'skill_title', 'skill_code']
        df_map.to_sql('role_skills', conn, if_exists='replace', index=False)

        # --- TABLE 4: SKILL DEFINITIONS ---
        print("4️⃣  Processing Skill Definitions...")
        df_info = pd.read_csv(FILES["skill_info"])
        # Columns: TSC Code, TSC_CCS Title, TSC_CCS Description
        df_info = df_info[['TSC Code', 'TSC_CCS Title', 'TSC_CCS Description']]
        df_info.columns = ['skill_code', 'title', 'description']
        df_info.to_sql('skill_definitions', conn, if_exists='replace', index=False)
        
        # --- TABLE 5: DETAILED KNOWLEDGE & ABILITIES ---
        print("5️⃣  Processing Skill Details (K&A)...")
        df_ka = pd.read_csv(FILES["skill_details"])
        # Columns: TSC_CCS Code, Knowledge / Ability Items
        df_ka = df_ka[['TSC_CCS Code', 'Knowledge / Ability Items']]
        df_ka.columns = ['skill_code', 'detail_item']
        df_ka.to_sql('skill_details', conn, if_exists='replace', index=False)

        print(f"✅ SUCCESS! Database built at '{DB_FILE}'")
        
    except Exception as e:
        print(f"❌ DATABASE BUILD FAILED: {str(e)}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()