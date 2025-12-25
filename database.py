import sqlite3
import pandas as pd
import os

# --- SIMPLE CONFIGURATION ---
FILES = {
    "role_desc": "role_desc.csv",
    "role_tasks": "role_tasks.csv",
    "role_skills": "role_skills.csv",
    "skill_info": "skill_defs.csv",
    "skill_details": "skill_details.csv"
}

DB_FILE = "skills.db"

def init_db():
    print("🚀 Starting Database Build...")

    # 1. CHECK FILES
    missing = []
    for key, filename in FILES.items():
        if not os.path.exists(filename):
            missing.append(filename)
    
    if missing:
        print("\n❌ CRITICAL ERROR: MISSING CSV FILES")
        print("---------------------------------------")
        for f in missing:
            print(f"   - {f} not found!")
        print("---------------------------------------")
        print("Please rename your files exactly as requested.")
        return # STOP HERE

    # 2. BUILD DATABASE
    conn = sqlite3.connect(DB_FILE)
    try:
        print("1️⃣  Processing Role Descriptions...")
        df_desc = pd.read_csv(FILES["role_desc"])
        df_desc = df_desc[['Job Role', 'Job Role Description', 'Performance Expectation']]
        df_desc.columns = ['role', 'description', 'expectations']
        df_desc.to_sql('role_descriptions', conn, if_exists='replace', index=False)

        print("2️⃣  Processing Role Tasks...")
        df_tasks = pd.read_csv(FILES["role_tasks"])
        df_tasks = df_tasks[['Job Role', 'Critical Work Function', 'Key Tasks']]
        df_tasks.columns = ['role', 'function', 'task']
        df_tasks.to_sql('role_tasks', conn, if_exists='replace', index=False)

        print("3️⃣  Processing Role Skills...")
        df_map = pd.read_csv(FILES["role_skills"])
        df_map = df_map[['Job Role', 'TSC_CCS Title', 'TSC_CCS Code']]
        df_map.columns = ['role', 'skill_title', 'skill_code']
        df_map.to_sql('role_skills', conn, if_exists='replace', index=False)

        print("4️⃣  Processing Skill Definitions...")
        df_info = pd.read_csv(FILES["skill_info"])
        # Columns might vary, adjust if needed
        df_info = df_info[['TSC Code', 'TSC_CCS Title', 'TSC_CCS Description']]
        df_info.columns = ['skill_code', 'title', 'description']
        df_info.to_sql('skill_definitions', conn, if_exists='replace', index=False)
        
        print("5️⃣  Processing Skill Details...")
        df_ka = pd.read_csv(FILES["skill_details"])
        df_ka = df_ka[['TSC_CCS Code', 'Knowledge / Ability Items']]
        df_ka.columns = ['skill_code', 'detail_item']
        df_ka.to_sql('skill_details', conn, if_exists='replace', index=False)

        print(f"✅ SUCCESS! Database '{DB_FILE}' built successfully.")
        
    except Exception as e:
        print(f"❌ DATABASE ERROR: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()