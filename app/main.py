import json
import logging
import gc
import asyncio

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .db import initialize 
from .core.config import settings, logger
from .services import ai_service
from .routers import interview, skills, audio

logger = logging.getLogger(__name__)

load_dotenv()
app = FastAPI(title="Poly-to-Pro", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://larrysim-iti123-project.netlify.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(interview.router, prefix="/api/interview", tags=["Interview"])
app.include_router(skills.router, prefix="/api/skills", tags=["Skills"])
app.include_router(audio.router, prefix="/api/audio", tags=["Audio"])

async def run_heavy_initialization():
    """
    Runs the heavy data loading in the background so the server doesn't timeout.
    """
    logger.info("⏳ [Background] Starting Data Ingestion...")
    
    # 1. Download & Process Excel (High RAM spike)
    try:
        initialize.fetch_excel_data()
        gc.collect() # Force RAM cleanup
        
        initialize.fetch_star_guide()
        initialize.fetch_questions()
        
        # 2. Generate Embeddings (High RAM spike)
        # This will take time, but the server is already running!
        initialize.generate_local_embeddings()
        gc.collect()
        
        logger.info("✅ [Background] All Data Ready & Embeddings Generated!")
        
    except Exception as e:
        logger.error(f"❌ [Background] Ingestion Failed: {e}")

@app.on_event("startup")
async def startup_event():
    logger.info(">>> SERVER STARTING UP <<<")

    initialize.init_db()

    ai_service.init_ai_models()
    ai_service.load_prompts()

    asyncio.create_task(run_heavy_initialization())
    
    logger.info("Server is ready to accept requests.")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info(">>> SERVER SHUTTING DOWN <<<")

@app.middleware("http")
async def verify_secret_header(request: Request, call_next):
    # Allow OPTIONS requests (needed for CORS pre-flight checks)
    if request.method == "OPTIONS":
        return await call_next(request)
        
    # Public endpoints (like docs or root) can be excluded if you want
    if request.url.path in ["/", "/docs", "/openapi.json", "/api/audio/transcribe"]:
         return await call_next(request)

    # Check for the secret header
    client_secret = request.headers.get("X-Poly-Secret")
    
    if client_secret != settings.API_SECRET:
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized: Invalid Secret"}
        )  
    
    response = await call_next(request)
    return response

@app.get("/")
async def root():
    return {
        "message": "Poly-to-Pro API is running!",
        "docs": "/docs",
        "status": "OK"
    }