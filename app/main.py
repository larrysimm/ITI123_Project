import json
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .db import initialize 
from .core.config import settings, logger
from .services import ai_service
from .routers import interview, skills

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

@app.on_event("startup")
async def startup_event():
    logger.info(">>> SERVER STARTING UP <<<")

    initialize.init_db()
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
    if request.url.path in ["/", "/docs", "/openapi.json"]:
         return await call_next(request)

    # Check for the secret header
    client_secret = request.headers.get("X-Poly-Secret")
    
    if client_secret != settings.API_SECRET:
        # Reject the request
        return json.dumps({"detail": "Unauthorized: Invalid Secret"}), 401
        
    response = await call_next(request)
    return response

@app.get("/")
async def root():
    return {
        "message": "Poly-to-Pro API is running!",
        "docs": "/docs",
        "status": "OK"
    }