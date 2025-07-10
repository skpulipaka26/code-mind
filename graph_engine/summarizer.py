import asyncio
from typing import List, Dict
from graph_engine.knowledge_graph import KnowledgeGraph
from utils.content_utils import smart_truncate, ensure_context_fits


class HierarchicalSummarizer:
    def __init__(
        self,
        knowledge_graph: KnowledgeGraph,
        llm_client=None,
        max_concurrent_requests=5,
    ):
        self.kg = knowledge_graph
        self.llm_client = llm_client
        self.max_concurrent_requests = max_concurrent_requests
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)

    async def summarize_chunk(self, chunk_node_id: str) -> str:
        """Generates a summary for a single code chunk or file."""
        chunk_attributes = self.kg.get_node_attributes(chunk_node_id)
        content = chunk_attributes.get("content", "")
        chunk_type = chunk_attributes.get("type", "")
        name = chunk_attributes.get("name", "")
        file_path = chunk_attributes.get("file_path", "")

        if not self.llm_client:
            return f"[{chunk_type.title()} Summary for {name or file_path}]\n{content[:1000]}{'...' if len(content) > 1000 else ''}"

        # Handle file nodes differently from code chunks
        if chunk_type == "file":
            return await self._summarize_file(chunk_node_id, chunk_attributes)
        else:
            return await self._summarize_code_chunk(chunk_node_id, chunk_attributes)

    async def _summarize_file(self, file_node_id: str, file_attributes: dict) -> str:
        """Generates a summary for a file node."""
        file_path = file_attributes.get("file_path", "")
        language = file_attributes.get("language", "")
        content = file_attributes.get("content", "")

        # Get summaries of contained chunks (children)
        children = self.kg.get_neighbors(file_node_id)
        child_summaries = []
        for child_id in children:
            child_attrs = self.kg.get_node_attributes(child_id)
            if "summary" in child_attrs and child_attrs.get("type") != "file":
                child_type = child_attrs.get("type", "")
                child_name = child_attrs.get("name", "")
                child_summaries.append(
                    f"- {child_type} '{child_name}': {child_attrs['summary'][:200]}..."
                )

        # Ensure content fits within reasonable limits
        safe_content = ensure_context_fits(content, max_tokens=15000)

        prompt = f"""Analyze and provide a high-level summary of the file '{file_path}':

```{language}
{safe_content}
```

This file contains the following components:
{chr(10).join(child_summaries) if child_summaries else "No analyzed components found."}

Provide a concise file-level summary that includes:
- Primary purpose and responsibility of this file
- Main architectural role (entry point, service, utility, configuration, etc.)
- Key exports and public interfaces
- Integration with other parts of the system
- Overall design patterns used

Focus on the file's role in the broader codebase architecture."""

        try:
            messages = [
                {
                    "role": "system",
                    "content": "You are a senior software architect analyzing file structure and purpose. Provide clear, architectural summaries.",
                },
                {"role": "user", "content": prompt},
            ]

            async with self._semaphore:
                summary = await self.llm_client.complete(messages)

            # Store the summary in the graph
            self.kg.graph.nodes[file_node_id]["summary"] = summary

            return f"[File Summary for {file_path}]\n{summary}"

        except Exception as e:
            error_summary = f"Error generating file summary: {str(e)}\n{content[:1000]}{'...' if len(content) > 1000 else ''}"
            self.kg.graph.nodes[file_node_id]["summary"] = error_summary
            return f"[File Summary for {file_path}]\n{error_summary}"

    async def _summarize_code_chunk(
        self, chunk_node_id: str, chunk_attributes: dict
    ) -> str:
        """Generates a summary for a code chunk (function, class, etc.)."""
        content = chunk_attributes.get("content", "")
        chunk_type = chunk_attributes.get("type", "")
        name = chunk_attributes.get("name", "")
        file_path = chunk_attributes.get("file_path", "")
        language = chunk_attributes.get("language", "")

        # Ensure content fits within reasonable limits for single chunk analysis
        safe_content = ensure_context_fits(content, max_tokens=20000)

        # Get summaries of dependencies
        dependencies = self.kg.get_neighbors(chunk_node_id)
        dependency_summaries = []
        for dep_id in dependencies:
            dep_attributes = self.kg.get_node_attributes(dep_id)
            if "summary" in dep_attributes:
                dependency_summaries.append(dep_attributes["summary"])

        prompt = f"""Analyze and summarize the following {chunk_type} '{name}' from file '{file_path}':

```{language}
{safe_content}
```

This chunk has the following dependencies:
{dependency_summaries}

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

            async with self._semaphore:
                summary = await self.llm_client.complete(messages)

            # Store the summary in the graph
            self.kg.graph.nodes[chunk_node_id]["summary"] = summary

            return f"[Chunk Summary for {name} in {file_path}]\n{summary}"

        except Exception as e:
            error_summary = f"Error generating summary: {str(e)}\n{content[:2000]}{'...' if len(content) > 2000 else ''}"

            # Store the error summary in the graph
            self.kg.graph.nodes[chunk_node_id]["summary"] = error_summary

            return f"[Chunk Summary for {name} in {file_path}]\n{error_summary}"

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
            safe_content = smart_truncate(
                content, max_length=5000, preserve_structure=True
            )

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

            async with self._semaphore:
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

        # Generate summaries for each community in parallel
        async def summarize_community_with_id(comm_id: int, nodes: List[str]) -> str:
            try:
                summary = await self.summarize_community(nodes)
                return f"## Community {comm_id}\n{summary}"
            except Exception as e:
                return f"## Community {comm_id}\nError generating summary: {str(e)}"

        community_tasks = [
            summarize_community_with_id(comm_id, nodes)
            for comm_id, nodes in communities.items()
        ]

        community_summaries = await asyncio.gather(
            *community_tasks, return_exceptions=True
        )

        # Handle any exceptions that occurred
        processed_summaries = []
        for i, result in enumerate(community_summaries):
            if isinstance(result, Exception):
                comm_id = list(communities.keys())[i]
                processed_summaries.append(
                    f"## Community {comm_id}\nError generating summary: {str(result)}"
                )
            else:
                processed_summaries.append(result)

        if not processed_summaries:
            return "[Global Summary]\nNo valid community summaries generated."

        combined_summaries = "\n\n".join(processed_summaries)

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

            async with self._semaphore:
                summary = await self.llm_client.complete(messages)
            return f"[Global Summary - {len(communities)} communities]\n{summary}"

        except Exception as e:
            return f"[Global Summary - {len(communities)} communities]\nError generating global summary: {str(e)}\n\nCommunity summaries:\n{combined_summaries[:10000]}{'...' if len(combined_summaries) > 10000 else ''}"

    async def summarize_chunks_batch(
        self,
        chunk_node_ids: List[str],
        batch_size: int = 3,  # Reduced from 10 to 3
    ) -> Dict[str, str]:
        """Generates summaries for multiple chunks in controlled batches."""
        if not chunk_node_ids:
            return {}

        if not self.llm_client:
            return {
                node_id: f"[Chunk Summary]\nLLM client not available for {node_id}"
                for node_id in chunk_node_ids
            }

        async def summarize_single_chunk(node_id: str) -> tuple[str, str]:
            try:
                summary = await self.summarize_chunk(node_id)
                return node_id, summary
            except Exception as e:
                error_summary = f"Error generating summary: {str(e)}"
                return node_id, error_summary

        # Process chunks in batches to avoid overwhelming the API
        all_summaries = {}
        for i in range(0, len(chunk_node_ids), batch_size):
            batch = chunk_node_ids[i : i + batch_size]
            tasks = [summarize_single_chunk(node_id) for node_id in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process batch results
            for j, result in enumerate(results):
                if isinstance(result, Exception):
                    node_id = batch[j]
                    all_summaries[node_id] = f"Error generating summary: {str(result)}"
                else:
                    node_id, summary = result
                    all_summaries[node_id] = summary

            # Add delay between batches to avoid rate limits
            if i + batch_size < len(chunk_node_ids):
                await asyncio.sleep(3)

        return all_summaries
