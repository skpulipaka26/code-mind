from typing import List, Dict
from graph_engine.knowledge_graph import KnowledgeGraph


class Search:
    def __init__(self, knowledge_graph: KnowledgeGraph, llm_client=None):
        self.kg = knowledge_graph
        self.llm_client = llm_client  # Placeholder for LLM client

    def global_search(self, query: str) -> List[Dict]:
        """Performs a global search across the entire knowledge graph."""
        # This could involve:
        # 1. Using LLM to understand the query and identify relevant keywords/entities.
        # 2. Searching node attributes (content, name, type) for keywords.
        # 3. Leveraging community detection to narrow down search space (map-reduce).
        # 4. Ranking results based on relevance.

        results = []
        for node_id, attributes in self.kg.graph.nodes(data=True):
            # Simple keyword matching for now
            if (
                query.lower() in str(attributes.get("content", "")).lower()
                or query.lower() in str(attributes.get("name", "")).lower()
            ):
                results.append({"node_id": node_id, "attributes": attributes})
        return results

    def local_search(
        self, entity_node_id: str, query: str, depth: int = 1
    ) -> List[Dict]:
        """Performs a local search around a specific entity in the graph."""
        # This could involve:
        # 1. Traversing neighbors up to a certain depth.
        # 2. Filtering neighbors based on relationship types.
        # 3. Using LLM for semantic matching of query against neighbor content.

        results = []
        if not self.kg.graph.has_node(entity_node_id):
            return results

        visited = set()
        queue = [(entity_node_id, 0)]

        while queue:
            current_node, current_depth = queue.pop(0)
            if current_node in visited:
                continue
            visited.add(current_node)

            if current_depth > depth:
                continue

            attributes = self.kg.get_node_attributes(current_node)
            if (
                query.lower() in str(attributes.get("content", "")).lower()
                or query.lower() in str(attributes.get("name", "")).lower()
            ):
                results.append({"node_id": current_node, "attributes": attributes})

            if current_depth < depth:
                for neighbor in self.kg.get_neighbors(current_node):
                    if neighbor not in visited:
                        queue.append((neighbor, current_depth + 1))
        return results
