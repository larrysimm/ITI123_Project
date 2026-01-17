import sqlite3
import pandas as pd
import os
import json
import requests
import logging
import gc  # <--- NEW: Garbage Collector to free RAM
from app.core.config import settings

# --- LOGGER SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
# Use the /tmp directory for downloads on Render to avoid permission issues
TEMP_DIR = "/tmp" if os.path.exists("/tmp") else "."
DB_FILE = settings.DB_PATH

# Github URLs
GITHUB_EXCEL_URL = "https://raw.githubusercontent.com/larrysimm/skills-data-static/main/jobsandskills-skillsfuture-skills-framework-dataset.xlsx"
QUESTION_JSON_URL = "https://raw.githubusercontent.com/larrysimm/skills-data-static/main/questions.json"
GITHUB_STAR_URL = "https://raw.githubusercontent.com/larrysimm/skills-data-static/main/star_guide.pdf"

def init_db():
    """Create tables."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # 1. Skill Definitions (Added 'embedding' column)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skill_definitions (
            skill_code TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            category TEXT,
            embedding BLOB
        )
    """)
    
    # 2. Role Skills
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS role_skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT,
            skill_code TEXT,
            skill_title TEXT,
            proficiency TEXT,
            FOREIGN KEY(skill_code) REFERENCES skill_definitions(skill_code)
        )
    """)

    # 3. Skill Details (Knowledge items)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skill_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_code TEXT,
            detail_type TEXT, 
            detail_item TEXT,
            FOREIGN KEY(skill_code) REFERENCES skill_definitions(skill_code)
        )
    """)

    # 4. Saved Questions
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("✅ Database Schema Ready.")

def download_file_streamed(url, local_filename):
    """
    Downloads a file in chunks to avoid loading it all into RAM.
    """
    logger.info(f"⬇️ Downloading stream: {url}...")
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(local_filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return True
    except Exception as e:
        logger.error(f"❌ Download Failed: {e}")
        return False

def fetch_excel_data():
    """
    Downloads Excel, processes it efficiently, and clears memory immediately.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Check if we already have data to skip heavy processing
    cursor.execute("SELECT COUNT(*) FROM role_skills")
    if cursor.fetchone()[0] > 0:
        logger.info("✅ Data already exists. Skipping Excel download.")
        conn.close()
        return

    # 1. Download to Temp File (Streamed)
    temp_excel_path = os.path.join(TEMP_DIR, "skills_data.xlsx")
    if not download_file_streamed(GITHUB_EXCEL_URL, temp_excel_path):
        conn.close()
        return

    logger.info("📊 Processing Excel Data (This may take a moment)...")

    try:
        # 2. Read ONLY necessary columns to save RAM
        # Adjust these column names if your Excel matches strictly
        df = pd.read_excel(temp_excel_path)
        
        # Rename for consistency
        df.columns = [c.lower().replace(' ', '_') for c in df.columns]
        
        # --- BATCH INSERT: Skill Definitions ---
        unique_skills = df[['skill_code', 'skill_title', 'skill_description', 'skill_category']].drop_duplicates('skill_code')
        
        skill_data = []
        for _, row in unique_skills.iterrows():
            skill_data.append((
                str(row['skill_code']), 
                str(row['skill_title']), 
                str(row['skill_description']), 
                str(row['skill_category']), 
                None # Embedding starts empty
            ))
            
        cursor.executemany(
            "INSERT OR IGNORE INTO skill_definitions (skill_code, title, description, category, embedding) VALUES (?, ?, ?, ?, ?)", 
            skill_data
        )
        logger.info(f"   -> Inserted {len(skill_data)} definitions.")

        # --- BATCH INSERT: Role Skills ---
        role_data = []
        # Take just what we need
        roles_df = df[['job_role', 'skill_code', 'skill_title', 'proficiency_level']]
        
        for _, row in roles_df.iterrows():
            role_data.append((
                str(row['job_role']), 
                str(row['skill_code']), 
                str(row['skill_title']), 
                str(row['proficiency_level'])
            ))
            
        cursor.executemany(
            "INSERT INTO role_skills (role, skill_code, skill_title, proficiency) VALUES (?, ?, ?, ?)", 
            role_data
        )
        logger.info(f"   -> Inserted {len(role_data)} role mappings.")
        
        # Commit and Close DB
        conn.commit()
        conn.close()
        
        # 3. CRITICAL: Free Memory
        del df
        del unique_skills
        del roles_df
        del skill_data
        del role_data
        
        # Force Python to release RAM
        gc.collect() 
        logger.info("🗑️ RAM Cleared after Excel processing.")

        # Remove temp file
        if os.path.exists(temp_excel_path):
            os.remove(temp_excel_path)

    except Exception as e:
        logger.error(f"❌ Excel Processing Failed: {e}")
        conn.close()

def generate_local_embeddings():
    """
    Generates embeddings locally. 
    Lazy loads the AI model so it doesn't crash the server during Excel processing.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Check if we actually need to run this
    cursor.execute("SELECT COUNT(*) FROM skill_definitions WHERE embedding IS NULL")
    remaining = cursor.fetchone()[0]
    
    if remaining == 0:
        logger.info("✅ All embeddings up to date. Skipping AI load.")
        conn.close()
        return

    logger.info(f"🧠 Loading AI Model to generate {remaining} vectors...")

    # --- LAZY IMPORT (Saves RAM until this exact moment) ---
    from sentence_transformers import SentenceTransformer
    import numpy as np
    
    # Load Model (Uses ~100MB RAM)
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    # Fetch Data in Batches to avoid OOM
    BATCH_SIZE = 100
    cursor.execute("SELECT skill_code, title, description FROM skill_definitions WHERE embedding IS NULL")
    
    while True:
        rows = cursor.fetchmany(BATCH_SIZE)
        if not rows:
            break
            
        codes = [r[0] for r in rows]
        texts = [f"{r[1]}: {r[2]}" for r in rows]
        
        # Generate
        embeddings = model.encode(texts, normalize_embeddings=True)
        
        # Save
        update_data = []
        for code, emb in zip(codes, embeddings):
            emb_blob = emb.astype(np.float32).tobytes()
            update_data.append((emb_blob, code))
            
        cursor.executemany("UPDATE skill_definitions SET embedding = ? WHERE skill_code = ?", update_data)
        conn.commit()
        logger.info(f"   -> Processed batch of {len(rows)}...")

    conn.close()
    logger.info("✅ Local Embeddings generation complete!")

def fetch_star_guide():
    """Downloads the STAR guide PDF."""
    local_path = settings.STAR_GUIDE_PATH
    if not os.path.exists(local_path):
        download_file_streamed(GITHUB_STAR_URL, local_path)

def fetch_questions():
    """Fetches questions JSON."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM saved_questions")
    if cursor.fetchone()[0] == 0:
        logger.info("⬇️ Downloading Questions JSON...")
        try:
            resp = requests.get(QUESTION_JSON_URL)
            data = resp.json()
            q_list = [(q['question_text'],) for q in data]
            cursor.executemany("INSERT INTO saved_questions (question_text) VALUES (?)", q_list)
            conn.commit()
        except Exception as e:
            logger.error(f"❌ Failed to load questions: {e}")
    conn.close()

# --- MAIN BLOCK ---
if __name__ == "__main__":
    init_db()
    fetch_excel_data()          # 1. Heavy Excel (RAM goes up, then down)
    fetch_star_guide()
    fetch_questions()
    generate_local_embeddings() # 2. Heavy AI (RAM goes up again)