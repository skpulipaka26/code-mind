from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from processing.diff_processor import ChangedChunk
from processing.reranker import RerankedResult


@dataclass
class ReviewPrompt:
    """Structured review prompt."""
    diff_content: str
    context: str
    instructions: str
    focus_areas: List[str]


class PromptBuilder:
    """Build prompts for code review generation."""
    
    def __init__(self):
        self.default_instructions = """
Analyze the code change and provide a comprehensive review.
Be specific, actionable, and focus on code quality.
Use clear sections and bullet points for readability.
"""
    
    def build_review_prompt(
        self,
        diff_content: str,
        context_chunks: List[RerankedResult] = None,
        changed_chunks: List[ChangedChunk] = None,
        focus_areas: List[str] = None,
        custom_instructions: str = None
    ) -> str:
        """Build a comprehensive review prompt."""
        
        # Build context section
        context_section = self._build_context_section(context_chunks, changed_chunks)
        
        # Build focus areas
        focus_section = self._build_focus_section(focus_areas)
        
        # Build instructions
        instructions = custom_instructions or self.default_instructions
        
        # Assemble prompt
        prompt_parts = [
            "# Code Review Request",
            "",
            "## Code Changes",
            "```diff",
            diff_content.strip(),
            "```",
            "",
            context_section,
            "",
            "## Instructions",
            instructions.strip(),
            "",
            focus_section,
            "",
            "## Response Format",
            "Provide your review in the following sections:",
            "1. **Summary** - Brief overview of changes",
            "2. **Issues Found** - Bugs, problems, concerns",
            "3. **Improvements** - Code quality suggestions",
            "4. **Best Practices** - Standards and conventions",
            "5. **Security** - Security considerations (if applicable)",
            "6. **Performance** - Performance implications (if applicable)",
            "",
            "Keep each section concise and actionable."
        ]
        
        return "\n".join(prompt_parts)
    
    def build_security_focused_prompt(self, diff_content: str, context_chunks: List[RerankedResult] = None) -> str:
        """Build a security-focused review prompt."""
        context_section = self._build_context_section(context_chunks)
        
        prompt_parts = [
            "# Security Code Review",
            "",
            "## Code Changes",
            "```diff",
            diff_content.strip(),
            "```",
            "",
            context_section,
            "",
            "## Security Analysis Instructions",
            "Perform a thorough security analysis focusing on:",
            "",
            "### Critical Areas",
            "- Authentication and authorization flaws",
            "- Input validation and sanitization",
            "- SQL injection and XSS vulnerabilities",
            "- Insecure data storage and transmission",
            "- Access control issues",
            "- Cryptographic weaknesses",
            "- Business logic flaws",
            "",
            "### Response Format",
            "1. **Security Score** (1-10, 10 being most secure)",
            "2. **Critical Issues** - Immediate security concerns",
            "3. **Medium Issues** - Important security improvements",
            "4. **Minor Issues** - Best practice suggestions",
            "5. **Recommendations** - Specific mitigation steps",
            "",
            "Be specific about file locations and line numbers where possible."
        ]
        
        return "\n".join(prompt_parts)
    
    def build_performance_focused_prompt(self, diff_content: str, context_chunks: List[RerankedResult] = None) -> str:
        """Build a performance-focused review prompt."""
        context_section = self._build_context_section(context_chunks)
        
        prompt_parts = [
            "# Performance Code Review",
            "",
            "## Code Changes",
            "```diff",
            diff_content.strip(),
            "```",
            "",
            context_section,
            "",
            "## Performance Analysis Instructions",
            "Analyze the performance impact focusing on:",
            "",
            "### Key Areas",
            "- Algorithm complexity (Big O analysis)",
            "- Database query efficiency",
            "- Memory usage and leaks",
            "- Network requests and caching",
            "- CPU-intensive operations",
            "- Asynchronous operations",
            "- Resource cleanup",
            "",
            "### Response Format",
            "1. **Performance Impact** - Overall assessment",
            "2. **Bottlenecks** - Potential performance issues",
            "3. **Optimizations** - Specific improvement suggestions",
            "4. **Monitoring** - Metrics to track",
            "",
            "Include complexity analysis and specific optimization recommendations."
        ]
        
        return "\n".join(prompt_parts)
    
    def build_quick_review_prompt(self, diff_content: str) -> str:
        """Build a quick review prompt for fast feedback."""
        prompt_parts = [
            "# Quick Code Review",
            "",
            "## Code Changes",
            "```diff",
            diff_content.strip(),
            "```",
            "",
            "## Instructions",
            "Provide a quick but thorough review focusing on:",
            "- Critical bugs or issues",
            "- Code quality problems",
            "- Best practice violations",
            "",
            "Keep the review concise but actionable.",
            "Highlight the most important issues first."
        ]
        
        return "\n".join(prompt_parts)
    
    def _build_context_section(
        self, 
        context_chunks: List[RerankedResult] = None, 
        changed_chunks: List[ChangedChunk] = None
    ) -> str:
        """Build the context section of the prompt."""
        if not context_chunks and not changed_chunks:
            return "## Context\nNo additional context available."
        
        context_parts = ["## Related Code Context"]
        
        if context_chunks:
            context_parts.append("\n### Similar/Related Code")
            for i, result in enumerate(context_chunks[:5], 1):
                context_parts.append(f"\n#### Context {i}: {result.metadata.file_path}")
                context_parts.append(f"Type: {result.metadata.chunk_type}")
                if result.metadata.name:
                    context_parts.append(f"Name: {result.metadata.name}")
                context_parts.append(f"Relevance Score: {result.score:.2f}")
                context_parts.append("```" + result.metadata.language)
                context_parts.append(result.content[:500] + ("..." if len(result.content) > 500 else ""))
                context_parts.append("```")
        
        if changed_chunks:
            context_parts.append("\n### Changed Chunks Summary")
            for chunk in changed_chunks[:3]:
                context_parts.append(f"- {chunk.change_type.title()}: {chunk.chunk.chunk_type}")
                if chunk.chunk.name:
                    context_parts.append(f"  Name: {chunk.chunk.name}")
                context_parts.append(f"  File: {chunk.chunk.file_path}")
        
        return "\n".join(context_parts)
    
    def _build_focus_section(self, focus_areas: List[str] = None) -> str:
        """Build the focus areas section."""
        if not focus_areas:
            focus_areas = [
                "Correctness and bugs",
                "Code readability and maintainability", 
                "Performance implications",
                "Security considerations",
                "Best practices and conventions",
                "Error handling",
                "Testing considerations"
            ]
        
        focus_parts = [
            "## Focus Areas",
            "Pay special attention to:"
        ]
        
        for area in focus_areas:
            focus_parts.append(f"- {area}")
        
        return "\n".join(focus_parts)