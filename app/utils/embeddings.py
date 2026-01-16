import logging
from chromadb.utils import embedding_functions
from app.core.config import settings

logger = logging.getLogger(__name__)

def get_embedding_function():
    """
    Selects the Embedding Model based on available keys.
    Priority 1: OpenAI
    Priority 2: Google Gemini
    """
    
    # 1. Try OpenAI First
    if settings.OPENAI_API_KEY:
        logger.info("🧠 Vector DB: Using OpenAI Embeddings")
        return embedding_functions.OpenAIEmbeddingFunction(
            api_key=settings.OPENAI_API_KEY,
            model_name="text-embedding-3-small"
        )
    
    # 2. Fallback to Gemini
    elif settings.GOOGLE_API_KEY:
        logger.info("🧠 Vector DB: Using Google Gemini Embeddings")
        return embedding_functions.GoogleGenerativeAIEmbeddingFunction(
            api_key=settings.GOOGLE_API_KEY,
            model_name="models/text-embedding-004"
        )
        
    else:
        raise ValueError("❌ No API Key found for Embeddings! Set OPENAI_API_KEY or GOOGLE_API_KEY.")