"""
Code review API routes.
"""

from fastapi import APIRouter, HTTPException, Request
from api.models import ReviewDiffRequest, QuickReviewRequest, ReviewResponse
from services.code_review_service import CodeReviewService
from utils.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.post("/", response_model=ReviewResponse)
async def create_review(request: ReviewDiffRequest, app_request: Request):
    """
    Create a code review using the indexed codebase for context.
    
    This endpoint analyzes the provided diff against the indexed codebase,
    finds relevant context, and generates a comprehensive code review.
    """
    try:
        # Get config and database from app state
        config = app_request.app.state.config
        database = app_request.app.state.database
        
        # Create review service
        review_service = CodeReviewService(config=config)
        
        # Review the diff directly with content
        result = await review_service.review_diff(
            diff_content=request.diff_content,
            repo_url=request.repo_url,
            context_enabled=True
        )
        
        if result:
            return ReviewResponse(
                review_content=result.review_content,
                changed_chunks_count=result.changed_chunks_count,
                context_chunks_count=result.context_chunks_count,
                duration=result.duration
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to generate review"
            )
            
    except Exception as e:
        logger.error(f"Error reviewing diff: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error reviewing diff: {str(e)}"
        )


@router.post("/quick", response_model=ReviewResponse)
async def create_quick_review(request: QuickReviewRequest, app_request: Request):
    """
    Create a quick review without using indexed context.
    
    This endpoint provides a fast review of the diff without searching
    the codebase for context. Useful for simple changes or when the
    repository hasn't been indexed yet.
    """
    try:
        # Get config from app state
        config = app_request.app.state.config
        
        # Create review service
        review_service = CodeReviewService(config=config)
        
        # Perform quick review directly with content
        result = await review_service.quick_review(
            diff_content=request.diff_content
        )
        
        if result:
            return ReviewResponse(
                review_content=result.review_content,
                changed_chunks_count=result.changed_chunks_count,
                context_chunks_count=result.context_chunks_count,
                duration=result.duration
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to generate quick review"
            )
            
    except Exception as e:
        logger.error(f"Error in quick review: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error in quick review: {str(e)}"
        )