from typing import List
from core.chunker import CodeChunk
from graph_engine.knowledge_graph import KnowledgeGraph


class GraphBuilder:
    def __init__(self, knowledge_graph: KnowledgeGraph):
        self.kg = knowledge_graph

    def build_graph_from_chunks(self, chunks: List[CodeChunk]):
        for chunk in chunks:
            node_id = self._generate_node_id(chunk)
            node_type = chunk.chunk_type
            attributes = {
                "file_path": chunk.file_path,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "content": chunk.content,
                "language": chunk.language,
            }
            if chunk.name:
                attributes["name"] = chunk.name

            self.kg.add_node(node_id, node_type, attributes)

            # Add file node if not already present
            file_node_id = f"file_{chunk.file_path}"
            if not self.kg.graph.has_node(file_node_id):
                self.kg.add_node(
                    file_node_id,
                    "file",
                    {"path": chunk.file_path, "language": chunk.language},
                )

            # Add CONTAINS relationship from file to chunk
            self.kg.add_edge(file_node_id, node_id, "CONTAINS")

            # Basic import relationship (file imports module/symbol)
            if chunk.chunk_type == "import" and chunk.name:
                # For now, just add an edge from the file to the import node
                # More sophisticated import analysis can be added later
                pass

    def _generate_node_id(self, chunk: CodeChunk) -> str:
        """Generates a unique ID for a chunk node."""
        if chunk.name:
            return (
                f"{chunk.chunk_type}_{chunk.name}_{chunk.file_path}_{chunk.start_line}"
            )
        return f"{chunk.chunk_type}_{chunk.file_path}_{chunk.start_line}"
