"""
FastAPI application for CodeMind - AI-powered codebase intelligence platform.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from config import Config
from storage.database import CodeMindDatabase
from utils.logging import get_logger

# Import routers
from api.routes import repositories, reviews, conversations, github

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting CodeMind API...")

    # Initialize global config and database
    config = Config.load()
    database = CodeMindDatabase()

    # Store in app state
    app.state.config = config
    app.state.database = database

    yield

    # Shutdown
    logger.info("Shutting down CodeMind API...")


# Create FastAPI app
app = FastAPI(
    title="CodeMind API",
    description="AI-powered codebase intelligence platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(
    repositories.router, prefix="/api/v1/repositories", tags=["repositories"]
)
app.include_router(reviews.router, prefix="/api/v1/reviews", tags=["reviews"])
app.include_router(
    conversations.router, prefix="/api/v1/conversations", tags=["conversations"]
)
app.include_router(github.router, prefix="/api/v1/webhooks", tags=["webhooks"])


@app.get("/")
async def root():
    return {"message": "CodeMind API", "version": "0.1.0", "docs": "/docs"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


def main():
    """Start the CodeMind API server."""
    import uvicorn

    uvicorn.run(
        "api.main:app", host="0.0.0.0", port=8000, reload=True, log_level="info"
    )


if __name__ == "__main__":
    main()
