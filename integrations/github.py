from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import requests

from core.chunker import TreeSitterChunker
from core.vectordb import VectorDatabase
from inference.openrouter_client import OpenRouterClient
from inference.prompt_builder import PromptBuilder
from inference.response_parser import ResponseParser
from processing.diff_processor import DiffProcessor
from processing.reranker import CodeReranker


@dataclass
class GitHubConfig:
    """GitHub integration configuration."""

    token: str
    repo_owner: str
    repo_name: str
    base_url: str = "https://api.github.com"


@dataclass
class PullRequest:
    """Pull request information."""

    number: int
    title: str
    description: str
    author: str
    base_branch: str
    head_branch: str
    diff_url: str
    files_changed: List[str]


class GitHubIntegration:
    """GitHub integration for automated code reviews."""

    def __init__(self, config: GitHubConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"token {config.token}",
                "Accept": "application/vnd.github.v3+json",
            }
        )

        self.chunker = TreeSitterChunker()
        self.diff_processor = DiffProcessor()
        self.prompt_builder = PromptBuilder()
        self.response_parser = ResponseParser()

    def get_pull_request(self, pr_number: int) -> Optional[PullRequest]:
        """Get pull request information."""
        url = f"{self.config.base_url}/repos/{self.config.repo_owner}/{self.config.repo_name}/pulls/{pr_number}"

        response = self.session.get(url)
        if response.status_code != 200:
            return None

        data = response.json()

        return PullRequest(
            number=pr_number,
            title=data["title"],
            description=data["body"] or "",
            author=data["user"]["login"],
            base_branch=data["base"]["ref"],
            head_branch=data["head"]["ref"],
            diff_url=data["diff_url"],
            files_changed=self._get_changed_files(pr_number),
        )

    def get_pull_request_diff(self, pr_number: int) -> Optional[str]:
        """Get pull request diff."""
        url = f"{self.config.base_url}/repos/{self.config.repo_owner}/{self.config.repo_name}/pulls/{pr_number}.diff"

        response = self.session.get(url)
        if response.status_code == 200:
            return response.text
        return None

    async def review_pull_request(
        self,
        pr_number: int,
        openrouter_client: OpenRouterClient,
        index_path: str = "index",
        focus_areas: List[str] = None,
    ) -> Dict[str, Any]:
        """Review a pull request and return structured feedback."""

        # Get PR information
        pr = self.get_pull_request(pr_number)
        if not pr:
            return {"error": "Pull request not found"}

        # Get diff
        diff_content = self.get_pull_request_diff(pr_number)
        if not diff_content:
            return {"error": "Could not retrieve diff"}

        # Process diff
        changed_chunks = self.diff_processor.extract_changed_chunks(diff_content)
        query = self.diff_processor.create_query_from_changes(changed_chunks)

        # Load vector database
        try:
            db = VectorDatabase()
            db.load(index_path)
        except Exception as e:
            return {"error": f"Could not load index: {e}"}

        # Search for related code
        query_embedding = await openrouter_client.embed(query)
        search_results = db.search(query_embedding, k=15)

        # Rerank results
        reranker = CodeReranker(openrouter_client)
        chunk_contents = {
            meta.chunk_id: db.get_content(meta.chunk_id) for meta, _ in search_results
        }
        reranked_results = await reranker.rerank_search_results(
            query, search_results, chunk_contents, top_k=8
        )

        # Build review prompt
        prompt = self.prompt_builder.build_review_prompt(
            diff_content=diff_content,
            context_chunks=reranked_results,
            changed_chunks=changed_chunks,
            focus_areas=focus_areas,
        )

        # Generate review
        review_text = await openrouter_client.complete(
            [{"role": "user", "content": prompt}]
        )

        # Parse review
        parsed_review = self.response_parser.parse_review(review_text)

        return {
            "pull_request": {
                "number": pr.number,
                "title": pr.title,
                "author": pr.author,
                "files_changed": len(pr.files_changed),
            },
            "review": {
                "summary": parsed_review.summary,
                "total_issues": parsed_review.total_issues,
                "severity_counts": {
                    k.value: v for k, v in parsed_review.severity_counts.items()
                },
                "overall_score": parsed_review.overall_score,
                "raw_text": review_text,
            },
            "sections": [
                {
                    "title": section.title,
                    "content": section.content,
                    "issues": [
                        {
                            "title": issue.title,
                            "description": issue.description,
                            "severity": issue.severity.value,
                            "category": issue.category,
                            "file_path": issue.file_path,
                            "line_number": issue.line_number,
                            "suggestion": issue.suggestion,
                        }
                        for issue in section.issues
                    ],
                }
                for section in parsed_review.sections
            ],
        }

    def post_review_comment(self, pr_number: int, comment: str) -> bool:
        """Post a review comment on a pull request."""
        url = f"{self.config.base_url}/repos/{self.config.repo_owner}/{self.config.repo_name}/pulls/{pr_number}/reviews"

        data = {"body": comment, "event": "COMMENT"}

        response = self.session.post(url, json=data)
        return response.status_code == 200

    def post_inline_comments(
        self, pr_number: int, comments: List[Dict[str, Any]]
    ) -> bool:
        """Post inline comments on specific lines."""
        url = f"{self.config.base_url}/repos/{self.config.repo_owner}/{self.config.repo_name}/pulls/{pr_number}/reviews"

        formatted_comments = []
        for comment in comments:
            formatted_comments.append(
                {
                    "path": comment["file_path"],
                    "line": comment["line_number"],
                    "body": comment["body"],
                }
            )

        data = {
            "body": "Automated code review completed",
            "event": "COMMENT",
            "comments": formatted_comments,
        }

        response = self.session.post(url, json=data)
        return response.status_code == 200

    def _get_changed_files(self, pr_number: int) -> List[str]:
        """Get list of files changed in pull request."""
        url = f"{self.config.base_url}/repos/{self.config.repo_owner}/{self.config.repo_name}/pulls/{pr_number}/files"

        response = self.session.get(url)
        if response.status_code != 200:
            return []

        files = response.json()
        return [file["filename"] for file in files]

    def setup_webhook(self, webhook_url: str, events: List[str] = None) -> bool:
        """Set up webhook for pull request events."""
        if events is None:
            events = ["pull_request"]

        url = f"{self.config.base_url}/repos/{self.config.repo_owner}/{self.config.repo_name}/hooks"

        data = {
            "name": "web",
            "active": True,
            "events": events,
            "config": {"url": webhook_url, "content_type": "json", "insecure_ssl": "0"},
        }

        response = self.session.post(url, json=data)
        return response.status_code == 201


class GitHubWebhookHandler:
    """Handle GitHub webhook events."""

    def __init__(self, github_integration: GitHubIntegration):
        self.github = github_integration

    async def handle_pull_request_event(
        self, event_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle pull request webhook event."""
        action = event_data.get("action")

        if action not in ["opened", "synchronize"]:
            return {"message": "Event ignored"}

        pr_number = event_data["pull_request"]["number"]

        # Review the pull request
        async with OpenRouterClient() as client:
            review_result = await self.github.review_pull_request(
                pr_number, client, focus_areas=["security", "performance", "bugs"]
            )

        if "error" in review_result:
            return review_result

        # Post review comment
        review_summary = self._format_review_summary(review_result)
        success = self.github.post_review_comment(pr_number, review_summary)

        return {
            "message": "Review posted successfully"
            if success
            else "Failed to post review",
            "review_summary": review_summary,
        }

    def _format_review_summary(self, review_result: Dict[str, Any]) -> str:
        """Format review result for GitHub comment."""
        pr_info = review_result["pull_request"]
        review_info = review_result["review"]

        summary_parts = [
            "# 🤖 Automated Code Review",
            "",
            f"**Pull Request:** #{pr_info['number']} - {pr_info['title']}",
            f"**Files Changed:** {pr_info['files_changed']}",
            "",
            "## Summary",
            review_info["summary"],
            "",
            "## Review Results",
            f"- **Total Issues:** {review_info['total_issues']}",
        ]

        if review_info["overall_score"]:
            summary_parts.append(
                f"- **Overall Score:** {review_info['overall_score']}/10"
            )

        # Add severity breakdown
        severity_counts = review_info["severity_counts"]
        if any(count > 0 for count in severity_counts.values()):
            summary_parts.append("")
            summary_parts.append("### Issues by Severity")
            for severity, count in severity_counts.items():
                if count > 0:
                    emoji = {
                        "critical": "🔴",
                        "high": "🟠",
                        "medium": "🟡",
                        "low": "🟢",
                        "info": "ℹ️",
                    }
                    summary_parts.append(
                        f"- {emoji.get(severity, '•')} **{severity.title()}:** {count}"
                    )

        summary_parts.extend(
            [
                "",
                "---",
                "*This review was generated automatically by Turbo Review*",
                "*Please validate all suggestions before implementing*",
            ]
        )

        return "\n".join(summary_parts)
