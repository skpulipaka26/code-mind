#!/usr/bin/env python3

import asyncio
from integrations.github import GitHubIntegration, GitHubConfig
from cli.config import Config
from utils.logging import setup_logging


async def test_github_integration():
    """Test the GitHub integration."""
    setup_logging(level="DEBUG")
    
    # Test configuration (replace with real values to test)
    github_config = GitHubConfig(
        token="your_github_token_here",
        repo_owner="your_repo_owner",
        repo_name="your_repo_name"
    )
    
    # Initialize GitHub integration
    github = GitHubIntegration(github_config)
    
    # Test getting PR info (replace with real PR number)
    pr_number = 1
    print(f"Testing PR {pr_number}...")
    
    try:
        pr_info = github.get_pull_request(pr_number)
        if pr_info:
            print(f"✅ Successfully retrieved PR: {pr_info.title}")
            print(f"   Author: {pr_info.author}")
            print(f"   Files changed: {len(pr_info.files_changed)}")
            
            # Test reviewing PR
            config = Config.load()
            if config.openrouter_api_key:
                print("Testing PR review...")
                review_result = await github.review_pull_request(
                    pr_number, 
                    config, 
                    focus_areas=["security", "bugs"]
                )
                
                if "error" in review_result:
                    print(f"❌ Review failed: {review_result['error']}")
                else:
                    print("✅ Review completed successfully!")
                    print(f"   Review length: {len(review_result['review']['raw_text'])} characters")
            else:
                print("❌ No OpenRouter API key configured")
        else:
            print("❌ Failed to retrieve PR info")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("🧪 Testing GitHub Integration...")
    print("=" * 50)
    print("NOTE: This test requires:")
    print("1. Valid GitHub token in GitHubConfig")
    print("2. Valid repo owner/name")
    print("3. Valid PR number")
    print("4. OpenRouter API key for review testing")
    print("=" * 50)
    
    asyncio.run(test_github_integration())