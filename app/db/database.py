import sqlite3
import logging
import os
import numpy as np
from sentence_transformers import SentenceTransformer
from app.core.config import settings

logger = logging.getLogger(__name__)
DB_FILE = settings.DB_PATH

# --- GLOBAL MODEL LOADER ---
# Load once to keep RAM usage low
_embedding_model = None

def get_model():
    global _embedding_model
    if _embedding_model is None:
        logger.info("🧠 Loading Local Embedding Model (all-MiniLM-L6-v2)...")
        _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    return _embedding_model

def get_db_connection():
    """Factory to get a database connection."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def get_hybrid_matches(resume_text, target_role, top_k=8):
    """
    Search Logic:
    1. SQL: Filter skills by Role.
    2. Vector: Rank by similarity to Resume using local CPU model.
    """
    try:
        model = get_model()
        
        # 1. SQL Fetch (Candidate Generation)
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = """
            SELECT 
                s.title, s.skill_code, rs.proficiency, s.description, s.embedding
            FROM role_skills rs
            JOIN skill_definitions s ON rs.skill_code = s.skill_code
            WHERE rs.role = ? AND s.embedding IS NOT NULL
        """
        cursor.execute(query, (target_role,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            logger.warning(f"⚠️ No skills found for role: {target_role}")
            return []

        # 2. Vector Math (Re-Ranking)
        query_vector = model.encode(resume_text, normalize_embeddings=True)
        results = []
        
        for row in rows:
            # Unpack Row
            title = row["title"]
            code = row["skill_code"]
            level = row["proficiency"]
            desc = row["description"]
            emb_blob = row["embedding"]
            
            # Convert Binary BLOB -> Numpy Array
            db_vector = np.frombuffer(emb_blob, dtype=np.float32)
            
            # Dot Product (Cosine Similarity)
            score = np.dot(query_vector, db_vector)
            
            results.append({
                "skill": title,
                "code": code,
                "level": level if level else "Standard",
                "required_knowledge": desc,
                "relevance_score": float(score)
            })
            
        # 3. Sort & Return
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        return results[:top_k]

    except Exception as e:
        logger.error(f"❌ Search Failed: {e}")
        return []

# --- KEEP YOUR EXISTING HELPER FUNCTIONS BELOW ---
# e.g. get_questions(), save_interview_interaction(), etc.
# Just ensure they use get_db_connection()
def get_questions():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, question_text FROM saved_questions ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]