import sqlite3
import json
import os

def init_db():
    conn = sqlite3.connect("skills.db")
    cursor = conn.cursor()
    
    # 1. Role Descriptions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS role_descriptions (
        role TEXT PRIMARY KEY,
        description TEXT,
        expectations TEXT
    )
    """)
    
    # 2. Role Tasks
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS role_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        task TEXT
    )
    """)
    
    # 3. Skill Definitions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS skill_definitions (
        skill_code TEXT PRIMARY KEY,
        title TEXT,
        description TEXT
    )
    """)
    
    # 4. Role Skills Map
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS role_skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        skill_code TEXT
    )
    """)

    # 5. Saved Questions (Note: question_text must be UNIQUE to prevent duplicates)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS saved_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_text TEXT UNIQUE, 
        category TEXT DEFAULT 'General'
    )
    """)
    
    # --- SEED DATA (ROLES) ---
    cursor.execute("SELECT count(*) FROM role_descriptions")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO role_descriptions VALUES (?, ?, ?)", 
                       ("Software Engineer", 
                        "Develops, tests, and maintains software applications.", 
                        "Expects proficiency in coding, debugging, and system design."))
        
        # (You can keep your other hardcoded role data here if you wish, 
        # or move them to a JSON file too using the same method below)

    # --- LOAD QUESTIONS FROM FILE ---
    if os.path.exists("questions.json"):
        try:
            with open("questions.json", "r", encoding="utf-8") as f:
                questions_data = json.load(f)
                
                print(f"📂 Found questions.json with {len(questions_data)} questions.")
                
                for q in questions_data:
                    # INSERT OR IGNORE: Skips the insert if the question already exists
                    cursor.execute(
                        "INSERT OR IGNORE INTO saved_questions (question_text, category) VALUES (?, ?)", 
                        (q["text"], q["category"])
                    )
        except Exception as e:
            print(f"⚠️ Error reading questions.json: {e}")
    else:
        print("ℹ️ No questions.json file found. Skipping seed.")

    conn.commit()
    conn.close()
    print("Database initialized.")