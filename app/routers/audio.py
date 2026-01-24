from fastapi import APIRouter, UploadFile, File, HTTPException
from app.services import ai_service
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """
    Receives an audio file (wav, mp3, webm), 
    sends it to OpenAI/Groq, 
    returns the text.
    """
    # 1. Validate File Size/Type (Optional but good practice)
    if file.content_type not in ["audio/mpeg", "audio/wav", "audio/webm", "audio/mp4"]:
        # Note: Browsers usually record as 'audio/webm'
        logger.warning(f"Uploaded strange audio format: {file.content_type}")

    try:
        # 2. Call the service (It handles the fallback)
        text = await ai_service.transcribe_audio_with_fallback(file)
        
        return {"transcription": text}
        
    except Exception as e:
        logger.error(f"Audio Router Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))