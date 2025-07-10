from typing import List
from dataclasses import dataclass
from processing.diff_processor import ChangedChunk
from processing.reranker import RerankedResult
from utils.content_utils import smart_truncate


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
You are a Senior Staff Engineer with 15+ years of experience performing comprehensive code reviews.
As a tech lead, you have deep expertise in software architecture, design patterns, and best practices.
Your role is to provide thorough, constructive feedback that helps improve code quality and prevent issues.

Analyze the code change thoroughly, considering all aspects of software engineering:
- Code correctness and potential bugs
- Software architecture and design patterns
- Performance implications and optimizations
- Security vulnerabilities and best practices
- Maintainability and code clarity
- Testing considerations and coverage
- Documentation and code comments
- Error handling and edge cases
- Scalability and future extensibility

Provide specific, actionable, and constructive feedback with concrete examples.
Reference specific line numbers and suggest exact code improvements where applicable.
Use clear, well-structured sections and bullet points for readability.
"""

    def build_review_prompt(
        self,
        diff_content: str,
        context_chunks: List[RerankedResult] = None,
        changed_chunks: List[ChangedChunk] = None,
        focus_areas: List[str] = None,
        custom_instructions: str = None,
        graph_context: List[str] = None,
    ) -> str:
        """Build a comprehensive review prompt."""

        # Build context section
        context_section = self._build_context_section(
            context_chunks, changed_chunks, graph_context
        )

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
            "Provide your review in the following comprehensive sections:",
            "",
            "### 1. Summary",
            "- Brief overview of the changes and their purpose",
            "- Overall assessment of the code quality",
            "- Key areas of concern or excellence",
            "",
            "### 2. Critical Issues",
            "- Bugs and correctness issues that must be fixed",
            "- Security vulnerabilities",
            "- Breaking changes or compatibility issues",
            "- Include specific line numbers and exact fixes",
            "",
            "### 3. Code Quality & Design",
            "- Architecture and design pattern adherence",
            "- Code structure and organization",
            "- Readability and maintainability concerns",
            "- Refactoring opportunities",
            "",
            "### 4. Performance & Scalability",
            "- Performance implications of the changes",
            "- Scalability considerations",
            "- Resource usage optimization opportunities",
            "- Algorithm complexity analysis",
            "",
            "### 5. Best Practices & Standards",
            "- Coding standards and conventions",
            "- Documentation and commenting improvements",
            "- Error handling and edge case coverage",
            "- Testing recommendations",
            "",
            "### 6. Recommendations",
            "- Specific action items with priority levels",
            "- Suggested implementation approaches",
            "- Follow-up tasks or considerations",
            "",
            "For each point, provide specific examples and actionable suggestions.",
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
            "Highlight the most important issues first.",
        ]

        return "\n".join(prompt_parts)

    def _build_context_section(
        self,
        context_chunks: List[RerankedResult] = None,
        changed_chunks: List[ChangedChunk] = None,
        graph_context: List[str] = None,
    ) -> str:
        """Build the context section of the prompt."""
        if not context_chunks and not changed_chunks and not graph_context:
            return "## Context\nNo additional context available."

        context_parts = ["## Related Code Context"]

        if context_chunks:
            context_parts.append("\n### Similar/Related Code")
            for i, result in enumerate(context_chunks[:5], 1):
                # Handle both old and new result formats
                if hasattr(result, "result"):
                    # New RerankedResult format
                    metadata = result.result.metadata
                    content = result.result.content
                    score = result.score
                else:
                    # Old format (fallback)
                    metadata = result.metadata
                    content = result.content
                    score = result.score

                context_parts.append(
                    f"\n#### Context {i}: {metadata.get('file_path', 'unknown')}"
                )
                context_parts.append(
                    f"**Type:** {metadata.get('chunk_type', 'unknown')}"
                )

                if metadata.get("name"):
                    context_parts.append(f"**Name:** {metadata.get('name')}")

                # Add enriched metadata if available
                if metadata.get("parent_name"):
                    parent_type = metadata.get("parent_type", "unknown")
                    context_parts.append(
                        f"**Parent:** {parent_type} `{metadata.get('parent_name')}`"
                    )

                if metadata.get("full_signature"):
                    context_parts.append(
                        f"**Signature:** `{metadata.get('full_signature')}`"
                    )

                if metadata.get("docstring"):
                    safe_docstring = smart_truncate(
                        metadata.get("docstring"),
                        max_length=1000,
                        preserve_structure=False,
                    )
                    context_parts.append(f"**Documentation:** {safe_docstring}")

                context_parts.append(f"**Relevance Score:** {score:.2f}")
                context_parts.append("```" + metadata.get("language", "text"))
                safe_content = smart_truncate(
                    content, max_length=8000, preserve_structure=True
                )
                context_parts.append(safe_content)
                context_parts.append("```")

        if changed_chunks:
            context_parts.append("\n### Changed Chunks Summary")
            for chunk in changed_chunks[:3]:
                context_parts.append(
                    f"\n#### {chunk.change_type.title()}: {chunk.chunk.chunk_type}"
                )

                # Basic info
                if chunk.chunk.name:
                    context_parts.append(f"**Name:** {chunk.chunk.name}")
                context_parts.append(f"**File:** {chunk.chunk.file_path}")
                context_parts.append(
                    f"**Lines:** {chunk.chunk.start_line}-{chunk.chunk.end_line}"
                )

                # Enriched metadata
                if chunk.chunk.parent_name:
                    context_parts.append(
                        f"**Parent:** {chunk.chunk.parent_type} `{chunk.chunk.parent_name}`"
                    )

                if chunk.chunk.full_signature:
                    context_parts.append(
                        f"**Signature:** `{chunk.chunk.full_signature}`"
                    )

                if chunk.chunk.docstring:
                    safe_docstring = smart_truncate(
                        chunk.chunk.docstring, max_length=1500, preserve_structure=False
                    )
                    context_parts.append(f"**Documentation:** {safe_docstring}")

                # Code preview
                context_parts.append(f"```{chunk.chunk.language}")
                safe_content = smart_truncate(
                    chunk.chunk.content, max_length=10000, preserve_structure=True
                )
                context_parts.append(safe_content)
                context_parts.append("```")

        if graph_context:
            context_parts.append("\n### Graph-Based Context")
            for i, context_str in enumerate(graph_context, 1):
                context_parts.append(f"\n#### Graph Context {i}")
                safe_context = smart_truncate(
                    context_str, max_length=8000, preserve_structure=True
                )
                context_parts.append(safe_context)

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
                "Testing considerations",
            ]

        focus_parts = ["## Focus Areas", "Pay special attention to:"]

        for area in focus_areas:
            focus_parts.append(f"- {area}")

        return "\n".join(focus_parts)

    def build_chat_prompt(
        self,
        query: str,
        context_chunks: List[RerankedResult] = None,
    ) -> str:
        """Build a chat prompt for codebase questions."""
        
        prompt_parts = [
            "# Codebase Assistant",
            "",
            f"## User Question",
            query,
            "",
        ]
        
        # Add context if available
        if context_chunks:
            prompt_parts.extend([
                "## Relevant Code Context",
                "Here are the most relevant code chunks from the codebase:",
                ""
            ])
            
            for i, result in enumerate(context_chunks[:5], 1):
                # Handle RerankedResult format
                if hasattr(result, "result"):
                    metadata = result.result.metadata
                    content = result.result.content
                    score = result.score
                else:
                    metadata = result.metadata
                    content = result.content
                    score = result.score
                
                prompt_parts.extend([
                    f"### Context {i}: {metadata.get('file_path', 'unknown')}",
                    f"**Type:** {metadata.get('chunk_type', 'unknown')}",
                ])
                
                if metadata.get("name"):
                    prompt_parts.append(f"**Name:** {metadata.get('name')}")
                
                if metadata.get("summary"):
                    prompt_parts.append(f"**Summary:** {metadata.get('summary')}")
                
                prompt_parts.extend([
                    f"**Relevance Score:** {score:.2f}",
                    f"```{metadata.get('language', 'text')}",
                    smart_truncate(content, max_length=2000, preserve_structure=True),
                    "```",
                    ""
                ])
        
        prompt_parts.extend([
            "## Instructions",
            "You are a helpful codebase assistant with deep knowledge of software engineering.",
            "Based on the user's question and the provided code context:",
            "",
            "1. **Answer the question directly and clearly**",
            "2. **Reference specific code examples** from the context when relevant",
            "3. **Provide practical insights** about the codebase structure and patterns",
            "4. **Suggest improvements or alternatives** if applicable",
            "5. **Be concise but thorough** - focus on what's most helpful",
            "",
            "If the context doesn't contain enough information to fully answer the question,",
            "say so and provide what insights you can based on the available code.",
            "",
            "Format your response clearly with sections and code examples where helpful."
        ])
        
        return "\n".join(prompt_parts)
