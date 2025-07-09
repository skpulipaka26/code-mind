from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import requests
from utils.logging import get_logger

from cli.config import Config
from services.review_service import ReviewService
from monitoring.telemetry import setup_telemetry

logger = get_logger(__name__)


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

        # Review service will be initialized with config when needed

        # Initialize telemetry for GitHub integration
        setup_telemetry()

    def get_pull_request(self, pr_number: int) -> Optional[PullRequest]:
        """Get pull request information."""
        url = f"{self.config.base_url}/repos/{self.config.repo_owner}/{self.config.repo_name}/pulls/{pr_number}"

        response = self.session.get(url)
        if response.status_code != 200:
            logger.error(
                f"Failed to get PR {pr_number} info. Status: {response.status_code}"
            )
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
        config: Config,
        index_path: str = "index",
        focus_areas: List[str] = None,
    ) -> Dict[str, Any]:
        """Review a pull request and return structured feedback."""

        # Get PR information
        pr = self.get_pull_request(pr_number)
        if not pr:
            logger.error(f"Pull request {pr_number} not found.")
            return {"error": "Pull request not found"}

        # Get diff
        diff_content = self.get_pull_request_diff(pr_number)
        if not diff_content:
            logger.error(f"Could not retrieve diff for PR {pr_number}.")
            return {"error": "Could not retrieve diff"}

        # Use ReviewService for consistent review logic
        review_service = ReviewService(config, logger)

        # Create a temporary diff file for the service
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".diff", delete=False) as f:
            f.write(diff_content)
            temp_diff_path = f.name

        try:
            # Use ReviewService to perform the review
            review_result = await review_service.review_diff(
                diff_file=temp_diff_path,
                index=index_path,
                repo_path=None,  # GitHub integration doesn't have local repo path
            )

            if not review_result:
                return {"error": "Review service failed to generate review"}

            review_text = review_result.review_content

        finally:
            # Clean up temp file
            os.unlink(temp_diff_path)

        # Process review (just use raw text)
        raw_review_text = review_text

        return {
            "pull_request": {
                "number": pr.number,
                "title": pr.title,
                "author": pr.author,
                "files_changed": len(pr.files_changed),
            },
            "review": {
                "raw_text": raw_review_text,
            },
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
        config = Config.load()
        review_result = await self.github.review_pull_request(
            pr_number, config, focus_areas=["security", "performance", "bugs"]
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
            "## Raw Review Output",
            review_info["raw_text"],
        ]

        summary_parts.extend(
            [
                "",
                "---",
                "*This review was generated automatically by Turbo Review*",
                "*Please validate all suggestions before implementing*",
            ]
        )

        return "\n".join(summary_parts)
