import sqlite3
import pandas as pd
import os
import json

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "skills.db")
JSON_PATH = os.path.join(BASE_DIR, "questions.json")

# Map your CSV files
FILES = {
    "role_desc": "role_desc.csv",
    "role_tasks": "role_tasks.csv",
    "role_skills": "role_skills.csv",
    "skill_info": "skill_defs.csv",
    "skill_details": "skill_details.csv"
}

# ... imports and config ...

def init_db():
    print("🚀 Starting Database Build...")

    # 1. CHECK FOR CRITICAL CSV FILES
    missing = []
    for key, filename in FILES.items():
        if not os.path.exists(os.path.join(BASE_DIR, filename)):
            missing.append(filename)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # --- PART A: PROCESS CSVs ---
        if not missing:
            print("1️⃣  Processing Role Descriptions...")
            df_desc = pd.read_csv(os.path.join(BASE_DIR, FILES["role_desc"]))
            df_desc = df_desc[['Job Role', 'Job Role Description', 'Performance Expectation']]
            df_desc.columns = ['role', 'description', 'expectations']
            df_desc.to_sql('role_descriptions', conn, if_exists='replace', index=False)

            print("2️⃣  Processing Role Tasks...")
            df_tasks = pd.read_csv(os.path.join(BASE_DIR, FILES["role_tasks"]))
            df_tasks = df_tasks[['Job Role', 'Critical Work Function', 'Key Tasks']]
            df_tasks.columns = ['role', 'function', 'task']
            df_tasks.to_sql('role_tasks', conn, if_exists='replace', index=False)

            print("3️⃣  Processing Role Skills...")
            df_map = pd.read_csv(os.path.join(BASE_DIR, FILES["role_skills"]))
            df_map = df_map[['Job Role', 'TSC_CCS Title', 'TSC_CCS Code']]
            df_map.columns = ['role', 'skill_title', 'skill_code']
            df_map.to_sql('role_skills', conn, if_exists='replace', index=False)

            print("4️⃣  Processing Skill Definitions (With Proficiency)...")
            df_info = pd.read_csv(os.path.join(BASE_DIR, FILES["skill_info"]))
            
            # --- UPDATE: Check for Proficiency Column ---
            # We look for 'Proficiency Level' or similar. 
            # If your CSV uses a different name, change 'Proficiency Level' below.
            cols_to_use = ['TSC Code', 'TSC_CCS Title', 'TSC_CCS Description']
            
            if 'Proficiency Level' in df_info.columns:
                cols_to_use.append('Proficiency Level')
                df_info = df_info[cols_to_use]
                df_info.columns = ['skill_code', 'title', 'description', 'proficiency']
            else:
                print("   ⚠️ 'Proficiency Level' column not found in skill_defs.csv. Using default.")
                df_info = df_info[cols_to_use]
                df_info.columns = ['skill_code', 'title', 'description']
                df_info['proficiency'] = "Standard" # Default value

            df_info.to_sql('skill_definitions', conn, if_exists='replace', index=False)
            
            print("5️⃣  Processing Skill Details...")
            df_ka = pd.read_csv(os.path.join(BASE_DIR, FILES["skill_details"]))
            df_ka = df_ka[['TSC_CCS Code', 'Knowledge / Ability Items']]
            df_ka.columns = ['skill_code', 'detail_item']
            df_ka.to_sql('skill_details', conn, if_exists='replace', index=False)
            
        else:
            print(f"⚠️ Skipping CSV Import: Missing files {missing}")

        # --- PART B: QUESTION BANK ---
        print("6️⃣  Initializing Question Bank...")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT UNIQUE, 
            category TEXT DEFAULT 'General'
        )
        """)

        # (Load questions.json code remains the same as before...)
        if os.path.exists(JSON_PATH):
            try:
                with open(JSON_PATH, "r", encoding="utf-8") as f:
                    questions_data = json.load(f)
                    for q in questions_data:
                        cursor.execute(
                            "INSERT OR IGNORE INTO saved_questions (question_text, category) VALUES (?, ?)", 
                            (q["text"], q.get("category", "General"))
                        )
            except Exception as e: print(f"Error loading questions: {e}")
        
        conn.commit()
        print(f"✅ SUCCESS! Database updated at {DB_FILE}")

    except Exception as e:
        print(f"❌ DATABASE ERROR: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()