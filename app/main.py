import logging
import os
import time

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.db import initialize 
from app.core.config import settings, logger
from app.services import ai_service
from app.routers import interview, skills, audio

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logtail_token = os.getenv("LOGTAIL_SOURCE_TOKEN")

if logtail_token:
    console_handler = logging.StreamHandler()
    logger.addHandler(console_handler)
    logger.info("✅ Logger initialized in main.py")
else:
    console_handler = logging.StreamHandler()
    logger.addHandler(console_handler)
    logger.info("⚠️ Logger initialized without Better Stack in main.py")

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

@app.on_event("startup")
async def startup_event():
    logger.info(">>> SERVER STARTING UP <<<")

    initialize.init_db()
    initialize.verify_pinecone_connection()
    ai_service.init_ai_models()
    ai_service.load_prompts()
    ai_service.load_star_guide()

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

@app.middleware("http")
async def log_visits(request: Request, call_next):
    start_time = time.time()
    
    # Process the request
    response = await call_next(request)
    
    # Calculate duration
    process_time = time.time() - start_time
    
    # Define which paths to ignore (noise filter)
    ignored_paths = ["/favicon.ico", "/openapi.json"]
    
    # Only log if it's NOT in the ignored list
    if request.url.path not in ignored_paths:
        
        # Prepare structured data for Better Stack
        log_data = {
            "event": "api_hit",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ip": request.client.host,
            "duration_seconds": round(process_time, 4),
            "user_agent": request.headers.get("user-agent", "unknown")
        }
        
        # Log it! (This sends JSON to Better Stack)
        # We use the 'extra' parameter to send searchable JSON fields
        logger.info(f"API Request: {request.method} {request.url.path}", extra=log_data)
        
    return response

@app.get("/")
async def root():
    return {
        "message": "Poly-to-Pro API is running!",
        "docs": "/docs",
        "status": "OK"
    }