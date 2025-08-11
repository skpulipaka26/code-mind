"""
Codebase conversation API routes.
"""

from fastapi import APIRouter, HTTPException, Request
from api.models import ChatQueryRequest, ChatResponse, SearchResponse, CodeChunkResponse
from services.codebase_service import CodebaseService
from utils.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.post("/", response_model=ChatResponse)
async def create_conversation(request: ChatQueryRequest, app_request: Request):
    """
    Create a conversation with the indexed codebase.

    This endpoint allows natural language queries about the codebase,
    finding relevant code chunks and generating helpful responses.
    """
    try:
        # Get config and database from app state
        config = app_request.app.state.config
        database = app_request.app.state.database

        # Create codebase service
        codebase_service = CodebaseService(config=config, database=database)

        # Use the codebase service for conversation
        result = await codebase_service.chat_with_codebase(
            query=request.query,
            max_context=request.max_results,
            repo_filter=request.repo_url,
        )

        return ChatResponse(
            answer=result.answer,
            context_chunks=result.context_chunks,
            query=result.query,
            duration=result.duration,
        )

    except Exception as e:
        logger.error(f"Error in chat query: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error processing chat query: {str(e)}"
        )


@router.post("/search", response_model=SearchResponse)
async def search_conversations(request: ChatQueryRequest, app_request: Request):
    """
    Search the codebase for relevant code chunks.

    This endpoint performs semantic search on the indexed codebase
    and returns relevant code chunks without generating a chat response.
    """
    try:
        # Get config and database from app state
        config = app_request.app.state.config
        database = app_request.app.state.database

        # Create codebase service
        codebase_service = CodebaseService(config=config, database=database)

        # Use the codebase service for search
        result = await codebase_service.search_codebase(
            query=request.query,
            max_results=request.max_results,
            repo_filter=request.repo_url,
        )

        # Convert to API response format
        chunks = []
        for chunk_data in result.chunks:
            chunks.append(
                CodeChunkResponse(
                    content=chunk_data["content"],
                    file_path=chunk_data["file_path"],
                    chunk_type=chunk_data["chunk_type"],
                    name=chunk_data["name"],
                    start_line=chunk_data["start_line"],
                    end_line=chunk_data["end_line"],
                    language=chunk_data["language"],
                    summary=chunk_data["summary"],
                    score=chunk_data["score"],
                )
            )

        return SearchResponse(
            chunks=chunks,
            total_results=result.total_results,
            query=result.query,
            duration=result.duration,
        )

    except Exception as e:
        logger.error(f"Error in codebase search: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error searching codebase: {str(e)}"
        )
