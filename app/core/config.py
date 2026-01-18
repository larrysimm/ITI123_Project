import os
import logging
from dotenv import load_dotenv

# 1. Load the .env file
load_dotenv()

# 2. Calculate the Project Root Directory
# We are in: /app/core/config.py
# Go up 3 levels: config.py -> core -> app -> my_fastapi_project (ROOT)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 3. Setup Logging (Centralized)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("backend.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("PolyToPro")

class Settings:
    PROJECT_NAME = "Poly-to-Pro"
    VERSION = "3.0.0"
    
    # --- CRITICAL: ABSOLUTE PATHS ---
    # This forces the DB to be found in the root folder
    DB_PATH = os.path.join(BASE_DIR, "skills.db")
    STAR_GUIDE_PATH = os.path.join(BASE_DIR, "star_guide.pdf")
    EXCEL_PATH = os.path.join(BASE_DIR, "jobsandskills.xlsx")
    JSON_PATH = os.path.join(BASE_DIR, "questions.json")

    # --- API KEYS ---
    API_SECRET = os.getenv("BACKEND_SECRET", "default-insecure-secret")
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

    # --- PINECONE CONFIG ---
    PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")

settings = Settings()