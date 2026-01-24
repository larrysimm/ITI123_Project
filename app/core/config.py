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
    # Create the Master Logger
    logger = logging.getLogger("PolyToPro")
    logger.setLevel(logging.INFO)

    # A. Always log to Console (Terminal / Render System Logs)
    stream_handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # B. Add Better Stack (Logtail) ONLY if Token exists
    # This prevents crashes if you forget the token locally
    logtail_token = os.getenv("LOGTAIL_SOURCE_TOKEN")
    
    if logtail_token:
        try:
            handler = LogtailHandler(source_token=logtail_token)
            logger.addHandler(handler)
            logger.info("✅ Better Stack Cloud Logging ENABLED")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Better Stack: {e}")
    else:
        logger.warning("⚠️ No LOGTAIL_SOURCE_TOKEN found. Logging to console only.")

    return logger

# Initialize immediately so other files can import 'logger'
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

    # --- PINECONE CONFIG ---
    PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")

settings = Settings()