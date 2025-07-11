"""
Repository management API routes.
"""

from fastapi import APIRouter, HTTPException, Request
from api.models import IndexRepositoryRequest, IndexRepositoryResponse
from services.codebase_service import CodebaseService
from utils.remote_repo_manager import get_repo_manager
from utils.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.post("/", response_model=IndexRepositoryResponse)
async def create_repository_index(
    request: IndexRepositoryRequest, app_request: Request
):
    """
    Index a GitHub repository for code review and chat.

    This endpoint clones the specified GitHub repository, processes all code files,
    generates embeddings, and stores them in the vector database for later retrieval.

    Example:
    ```json
    {
        "repo_url": "https://github.com/facebook/react",
        "branch": "main",
        "access_token": "ghp_xxxx"  // Optional for private repos
    }
    ```
    """
    repo_manager = get_repo_manager()
    local_path = None

    try:
        # Get config and database from app state
        config = app_request.app.state.config
        database = app_request.app.state.database

        # Parse and validate repository URL
        repo_info = repo_manager.get_repository_info(request.repo_url)
        logger.info(f"Indexing repository: {repo_info['full_name']}")

        # Clone the repository
        try:
            local_path = repo_manager.clone_repository(
                repo_url=request.repo_url,
                branch=request.branch,
                access_token=request.access_token,
            )
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Failed to clone repository: {str(e)}"
            )

        # Create codebase service
        codebase_service = CodebaseService(config=config, database=database)

        # Index the repository with full metadata
        result = await codebase_service.index_repository(
            repo_path=local_path,
            repo_url=request.repo_url,
            repo_name=repo_info["repo_name"],
            owner=repo_info["owner"],
            branch=request.branch,
        )

        if result.success:
            return IndexRepositoryResponse(
                success=True,
                message=f"Repository {repo_info['full_name']} indexed successfully in {result.duration:.2f}s",
                chunks_indexed=result.chunks_indexed,
                duration=result.duration,
            )
        else:
            raise HTTPException(status_code=500, detail=result.message)

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error indexing repository: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error indexing repository: {str(e)}"
        )
    finally:
        # Optional: Clean up cloned repository to save disk space
        # Uncomment if you want to clean up immediately after indexing
        # if local_path:
        #     repo_manager.cleanup_repository(request.repo_url)
        pass


@router.get("/")
async def list_repositories(app_request: Request):
    """
    List all indexed repositories with their statistics.
    """
    try:
        config = app_request.app.state.config
        database = app_request.app.state.database

        # Create codebase service
        codebase_service = CodebaseService(config=config, database=database)

        # Get repository statistics
        stats = await codebase_service.get_repository_stats()

        return {
            "status": "ready",
            "message": "Repository service is operational",
            **stats,
        }

    except Exception as e:
        logger.error(f"Error listing repositories: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error listing repositories: {str(e)}"
        )


@router.delete("/{repo_owner}/{repo_name}")
async def delete_repository(repo_owner: str, repo_name: str, app_request: Request):
    """
    Delete a repository and all its indexed data.
    """
    try:
        config = app_request.app.state.config
        database = app_request.app.state.database

        # Reconstruct repo URL
        repo_url = f"https://github.com/{repo_owner}/{repo_name}"

        # Create codebase service
        codebase_service = CodebaseService(config=config, database=database)

        # Delete repository
        success = codebase_service.delete_repository(repo_url)

        if success:
            return {
                "success": True,
                "message": f"Repository {repo_owner}/{repo_name} deleted successfully",
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to delete repository")

    except Exception as e:
        logger.error(f"Error deleting repository: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error deleting repository: {str(e)}"
        )


@router.get("/{repo_owner}/{repo_name}/stats")
async def get_repository_stats(repo_owner: str, repo_name: str, app_request: Request):
    """
    Get detailed statistics for a specific repository.
    """
    try:
        config = app_request.app.state.config
        database = app_request.app.state.database

        # Reconstruct repo URL
        repo_url = f"https://github.com/{repo_owner}/{repo_name}"

        # Create codebase service
        codebase_service = CodebaseService(config=config, database=database)

        # Get repository statistics
        stats = await codebase_service.get_repository_stats(repo_url)

        return stats

    except Exception as e:
        logger.error(f"Error getting repository stats: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error getting repository stats: {str(e)}"
        )
