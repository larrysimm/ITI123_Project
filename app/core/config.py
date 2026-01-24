import os
import logging
from dotenv import load_dotenv
from logtail import LogtailHandler

# 1. Load the .env file
load_dotenv()

# 2. Calculate the Project Root Directory
# We are in: /app/core/config.py
# Go up 3 levels: config.py -> core -> app -> my_fastapi_project (ROOT)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 3. Setup Logging (Centralized)
def setup_logging():
    # A. Create the Master Logger
    logger = logging.getLogger("PolyToPro")
    
    # Prevent duplicate logs (propagation)
    logger.propagate = False
    
    # Clear existing handlers to prevent doubles on reload
    if logger.hasHandlers():
        logger.handlers.clear()
        
    logger.setLevel(logging.INFO)

    # B. Add Console Handler (Required for Render Logs)
    stream_handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # C. Add Better Stack (Logtail) - Optional
    logtail_token = os.getenv("LOGTAIL_SOURCE_TOKEN")
    
    if logtail_token:
        try:
            handler = LogtailHandler(source_token=logtail_token)
            logger.addHandler(handler)
            # Use extra dict to prevent 'extra' keyword errors if simple string
            logger.info("✅ Better Stack Cloud Logging ENABLED")
        except Exception as e:
            # Fallback if connection fails
            print(f"❌ Failed to connect to Better Stack: {e}")
    else:
        # Just print to console if token is missing
        print("⚠️ No LOGTAIL_SOURCE_TOKEN found. Logging to console only.")

    return logger

logger = setup_logging()

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
    LOGTAIL_SOURCE_TOKEN = os.getenv("LOGTAIL_SOURCE_TOKEN")

    # --- PINECONE CONFIG ---
    PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")

settings = Settings()