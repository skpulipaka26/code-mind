"""
Pydantic models for API requests and responses.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# Request Models
class IndexRepositoryRequest(BaseModel):
    repo_url: str = Field(..., description="GitHub repository URL (e.g., https://github.com/owner/repo)")
    branch: Optional[str] = Field("main", description="Branch to clone (default: main)")
    access_token: Optional[str] = Field(None, description="GitHub access token for private repos")


class ReviewDiffRequest(BaseModel):
    diff_content: str = Field(..., description="Diff content to review")
    repo_url: Optional[str] = Field(None, description="Optional GitHub repository URL for context")


class QuickReviewRequest(BaseModel):
    diff_content: str = Field(..., description="Diff content for quick review")


class ChatQueryRequest(BaseModel):
    query: str = Field(..., description="Question about the codebase")
    repo_url: Optional[str] = Field(None, description="Optional GitHub repository URL filter")
    max_results: int = Field(10, description="Maximum number of context chunks to use")


class GitHubWebhookRequest(BaseModel):
    action: str
    pull_request: Dict[str, Any]
    repository: Dict[str, Any]


# Response Models
class IndexRepositoryResponse(BaseModel):
    success: bool
    message: str
    chunks_indexed: Optional[int] = None
    duration: Optional[float] = None


class ReviewResponse(BaseModel):
    review_content: str
    changed_chunks_count: int
    context_chunks_count: int
    duration: float


class ChatResponse(BaseModel):
    answer: str
    context_chunks: List[Dict[str, Any]]
    query: str
    duration: float


class CodeChunkResponse(BaseModel):
    content: str
    file_path: str
    chunk_type: str
    name: str
    start_line: int
    end_line: int
    language: str
    summary: Optional[str] = None
    score: Optional[float] = None


class SearchResponse(BaseModel):
    chunks: List[CodeChunkResponse]
    total_results: int
    query: str
    duration: float


class GitHubWebhookResponse(BaseModel):
    success: bool
    message: str
    review_posted: bool = False