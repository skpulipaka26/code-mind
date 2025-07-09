from typing import List, Dict
from graph_engine.knowledge_graph import KnowledgeGraph
from utils.content_utils import smart_truncate, ensure_context_fits


class HierarchicalSummarizer:
    def __init__(self, knowledge_graph: KnowledgeGraph, llm_client=None):
        self.kg = knowledge_graph
        self.llm_client = llm_client  # Placeholder for LLM client

    async def summarize_chunk(self, chunk_node_id: str) -> str:
        """Generates a summary for a single code chunk."""
        chunk_attributes = self.kg.get_node_attributes(chunk_node_id)
        content = chunk_attributes.get("content", "")
        chunk_type = chunk_attributes.get("type", "")
        name = chunk_attributes.get("name", "")
        file_path = chunk_attributes.get("file_path", "")
        language = chunk_attributes.get("language", "")

        if not self.llm_client:
            return f"[Chunk Summary for {name} in {file_path}]\n{content[:1000]}{'...' if len(content) > 1000 else ''}"

        # Ensure content fits within reasonable limits for single chunk analysis
        safe_content = ensure_context_fits(content, max_tokens=20000)
        
        prompt = f"""Analyze and summarize the following {chunk_type} '{name}' from file '{file_path}':

```{language}
{safe_content}
```

Provide a concise summary that includes:
- Purpose and functionality
- Key dependencies and relationships
- Important implementation details
- Potential impact on the codebase

Keep the summary focused and technical."""

        try:
            messages = [
                {
                    "role": "system",
                    "content": "You are a senior engineer analyzing code. Provide clear, technical summaries.",
                },
                {"role": "user", "content": prompt},
            ]

            summary = await self.llm_client.complete(messages)
            return f"[Chunk Summary for {name} in {file_path}]\n{summary}"

        except Exception as e:
            return f"[Chunk Summary for {name} in {file_path}]\nError generating summary: {str(e)}\n{content[:2000]}{'...' if len(content) > 2000 else ''}"

    async def summarize_community(self, community_nodes: List[str]) -> str:
        """Generates a summary for a community of code chunks."""
        if not community_nodes:
            return "[Community Summary]\nNo nodes in community."

        if not self.llm_client:
            return f"[Community Summary]\nCommunity of {len(community_nodes)} code chunks (LLM client not available)."

        # Gather detailed information about each node
        node_summaries = []
        for node_id in community_nodes:
            attributes = self.kg.get_node_attributes(node_id)
            content = attributes.get("content", "")
            chunk_type = attributes.get("type", "")
            name = attributes.get("name", "")
            file_path = attributes.get("file_path", "")
            language = attributes.get("language", "")

            # Use smart truncation for better structure preservation
            safe_content = smart_truncate(content, max_length=5000, preserve_structure=True)
            
            node_summary = f"""
### {chunk_type.title()}: {name or "unnamed"} 
**File:** {file_path}
**Language:** {language}
```{language}
{safe_content}
```
"""
            node_summaries.append(node_summary)

        combined_content = "\n".join(node_summaries)
        
        # Ensure the combined content fits within context limits
        safe_combined_content = ensure_context_fits(combined_content, max_tokens=50000)

        prompt = f"""Analyze the following community of related code chunks and provide a comprehensive summary:

{safe_combined_content}

Provide a summary that includes:
- The overall purpose and functionality of this code community
- How the different components work together
- Key architectural patterns and relationships
- Common themes or shared responsibilities
- Potential areas for improvement or refactoring
- Impact on the broader codebase

Focus on the collective behavior and interactions rather than individual components."""

        try:
            messages = [
                {
                    "role": "system",
                    "content": "You are a senior software architect analyzing code communities. Provide insightful analysis of how code components work together.",
                },
                {"role": "user", "content": prompt},
            ]

            summary = await self.llm_client.complete(messages)
            return f"[Community Summary - {len(community_nodes)} chunks]\n{summary}"

        except Exception as e:
            return f"[Community Summary - {len(community_nodes)} chunks]\nError generating summary: {str(e)}"

    async def summarize_global(self, communities: Dict[int, List[str]]) -> str:
        """Generates a global summary of the entire codebase."""
        if not communities:
            return "[Global Summary]\nNo communities found in codebase."

        if not self.llm_client:
            return f"[Global Summary]\nCodebase contains {len(communities)} communities (LLM client not available)."

        # Generate summaries for each community
        community_summaries = []
        for comm_id, nodes in communities.items():
            try:
                summary = await self.summarize_community(nodes)
                community_summaries.append(f"## Community {comm_id}\n{summary}")
            except Exception as e:
                community_summaries.append(
                    f"## Community {comm_id}\nError generating summary: {str(e)}"
                )

        if not community_summaries:
            return "[Global Summary]\nNo valid community summaries generated."

        combined_summaries = "\n\n".join(community_summaries)
        
        # Ensure global summary content fits within context limits
        safe_summaries = ensure_context_fits(combined_summaries, max_tokens=80000)

        prompt = f"""Analyze the following community summaries and provide a comprehensive global overview of the entire codebase:

{safe_summaries}

Provide a high-level analysis that includes:
- Overall architecture and design patterns
- Key components and their relationships
- Technology stack and frameworks used
- Code quality and maintainability assessment
- Potential system-wide improvements
- Technical debt and refactoring opportunities
- Security and performance considerations
- Testing and documentation coverage
- System complexity and scalability

Focus on providing strategic insights about the codebase as a whole."""

        try:
            messages = [
                {
                    "role": "system",
                    "content": "You are a senior technical lead conducting a comprehensive codebase review. Provide strategic insights and architectural analysis.",
                },
                {"role": "user", "content": prompt},
            ]

            summary = await self.llm_client.complete(messages)
            return f"[Global Summary - {len(communities)} communities]\n{summary}"

        except Exception as e:
            return f"[Global Summary - {len(communities)} communities]\nError generating global summary: {str(e)}\n\nCommunity summaries:\n{combined_summaries[:10000]}{'...' if len(combined_summaries) > 10000 else ''}"
