import sqlite3
import pandas as pd
import os
import json
import requests

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "skills.db")
JSON_PATH = os.path.join(BASE_DIR, "questions.json")

EXCEL_FILE = os.path.join(BASE_DIR, "jobsandskills-skillsfuture-skills-framework-dataset.xlsx")
GITHUB_EXCEL_URL = "https://raw.githubusercontent.com/larrysimm/skills-data-static/main/jobsandskills-skillsfuture-skills-framework-dataset.xlsx"

# Excel sheet → CSV mapping
EXCEL_SHEETS = {
    "Job Role_Description": "role_desc.csv",
    "Job Role_CWF_KT": "role_tasks.csv",
    "Job Role_TCS_CCS": "role_skills.csv",
    "TSC_CCS_Key": "skill_defs.csv",
    "TSC_CCS_K&A": "skill_details.csv"
}

# Map your CSV files
FILES = {
    "role_desc": "role_desc.csv",
    "role_tasks": "role_tasks.csv",
    "role_skills": "role_skills.csv",
    "skill_info": "skill_defs.csv",
    "skill_details": "skill_details.csv"
}

def download_excel_from_github():
    if os.path.exists(EXCEL_FILE):
        print(f"📂 Excel file found locally: {EXCEL_FILE}")
        return

    print(f"⬇️ Downloading dataset from GitHub...")
    try:
        response = requests.get(GITHUB_EXCEL_URL)
        response.raise_for_status()
        with open(EXCEL_FILE, "wb") as f:
            f.write(response.content)
        print(f"✅ Download complete. Saved to: {EXCEL_FILE}")
    except Exception as e:
        print(f"❌ Failed to download file: {e}")

def extract_excel_to_csv():
    if not os.path.exists(EXCEL_FILE):
        print(f"⚠️ Excel file missing. Skipping extraction.")
        return

    print("📘 Extracting Excel sheets to CSV...")
    for sheet_name, csv_name in EXCEL_SHEETS.items():
        csv_path = os.path.join(BASE_DIR, csv_name)
        if os.path.exists(csv_path):
            pass # Skip if exists
        try:
            df = pd.read_excel(EXCEL_FILE, sheet_name=sheet_name)
            df.to_csv(csv_path, index=False)
            print(f"   ✅ Extracted: {csv_name}")
        except Exception as e:
            print(f"   ❌ Failed to extract '{sheet_name}': {e}")

def cleanup_csv_files():
    print("🧹 Cleaning up CSV files...")
    for csv_file in FILES.values():
        csv_path = os.path.join(BASE_DIR, csv_file)
        if os.path.exists(csv_path):
            try:
                os.remove(csv_path)
            except: pass

def init_db():
    print("🚀 Starting Database Initialization...")

    # 1. Download & Extract
    download_excel_from_github()
    extract_excel_to_csv()

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # Check files exist
        missing = [f for f in FILES.values() if not os.path.exists(os.path.join(BASE_DIR, f))]
        
        if not missing:
            print("⚙️  Processing CSV Data into SQLite...")

            # 1. Descriptions
            df_desc = pd.read_csv(os.path.join(BASE_DIR, FILES["role_desc"]))
            df_desc = df_desc[['Job Role', 'Job Role Description', 'Performance Expectation']]
            df_desc.columns = ['role', 'description', 'expectations']
            df_desc.to_sql('role_descriptions', conn, if_exists='replace', index=False)
            print("   -> Role Descriptions Loaded")

            # 2. Tasks
            df_tasks = pd.read_csv(os.path.join(BASE_DIR, FILES["role_tasks"]))
            df_tasks = df_tasks[['Job Role', 'Critical Work Function', 'Key Tasks']]
            df_tasks.columns = ['role', 'function', 'task']
            df_tasks.to_sql('role_tasks', conn, if_exists='replace', index=False)
            print("   -> Role Tasks Loaded")

            # 3. Role-Skill Map (UPDATED: NOW INCLUDES PROFICIENCY)
            df_map = pd.read_csv(os.path.join(BASE_DIR, FILES["role_skills"]))
            # We explicitly read the 'Proficiency Level' column here
            df_map = df_map[['Job Role', 'TSC_CCS Title', 'TSC_CCS Code', 'Proficiency Level']]
            df_map.columns = ['role', 'skill_title', 'skill_code', 'proficiency'] 
            df_map.to_sql('role_skills', conn, if_exists='replace', index=False)
            print("   -> Role-Skill Map Loaded (with Proficiency)")

            # 4. Skill Definitions (UPDATED: REMOVED PROFICIENCY CHECK)
            df_info = pd.read_csv(os.path.join(BASE_DIR, FILES["skill_info"]))
            # We no longer look for proficiency here, avoiding the warning
            df_info = df_info[['TSC Code', 'TSC_CCS Title', 'TSC_CCS Description']]
            df_info.columns = ['skill_code', 'title', 'description']
            df_info.to_sql('skill_definitions', conn, if_exists='replace', index=False)
            print("   -> Skill Definitions Loaded")
            
            # 5. Skill Details
            df_ka = pd.read_csv(os.path.join(BASE_DIR, FILES["skill_details"]))
            df_ka = df_ka[['TSC_CCS Code', 'Knowledge / Ability Items']]
            df_ka.columns = ['skill_code', 'detail_item']
            df_ka.to_sql('skill_details', conn, if_exists='replace', index=False)
            print("   -> Skill Details Loaded")

            cleanup_csv_files()

        else:
            print(f"⚠️ Missing files: {missing}")

        # --- Question Bank ---
        print("📝 Initializing Question Bank...")
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
                    for q in q_data:
                        try:
                            cursor.execute(
                                "INSERT OR IGNORE INTO saved_questions (question_text, category) VALUES (?, ?)", 
                                (q["text"], q.get("category", "General"))
                            )
                        except: pass
            except: pass
        
        conn.commit()
        print(f"✅ SUCCESS! Database ready at: {DB_FILE}")

    except Exception as e:
        print(f"❌ DATABASE CRITICAL ERROR: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()