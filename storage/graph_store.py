"""
Graph database interface using Neo4j for production-grade graph storage.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from neo4j import GraphDatabase
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class GraphNode:
    """Represents a node in the knowledge graph."""

    id: str
    labels: List[str]
    properties: Dict[str, Any]


@dataclass
class GraphRelationship:
    """Represents a relationship in the knowledge graph."""

    start_node: str
    end_node: str
    type: str
    properties: Dict[str, Any]


class Neo4jGraphStore:
    """Production graph store using Neo4j."""

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "turbo-review-password",
    ):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self._ensure_constraints()

    def close(self):
        """Close the database connection."""
        if self.driver:
            self.driver.close()

    def _ensure_constraints(self):
        """Create necessary constraints and indexes."""
        with self.driver.session() as session:
            # Create uniqueness constraints
            constraints = [
                "CREATE CONSTRAINT content_hash_unique IF NOT EXISTS FOR (n:CodeChunk) REQUIRE n.content_hash IS UNIQUE",
                "CREATE CONSTRAINT file_path_unique IF NOT EXISTS FOR (n:File) REQUIRE n.file_path IS UNIQUE",
                "CREATE INDEX content_hash_index IF NOT EXISTS FOR (n:CodeChunk) ON (n.content_hash)",
                "CREATE INDEX file_path_index IF NOT EXISTS FOR (n:File) ON (n.file_path)",
                "CREATE INDEX chunk_type_index IF NOT EXISTS FOR (n:CodeChunk) ON (n.chunk_type)",
            ]

            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as e:
                    logger.debug(f"Constraint/index already exists or failed: {e}")

    def store_nodes(self, nodes: List[GraphNode]) -> bool:
        """Store multiple nodes in the graph."""
        try:
            with self.driver.session() as session:
                for node in nodes:
                    # Build labels string
                    labels_str = ":".join(node.labels)

                    # Create node with MERGE to avoid duplicates
                    query = f"""
                    MERGE (n:{labels_str} {{id: $id}})
                    SET n += $properties
                    RETURN n
                    """

                    session.run(query, id=node.id, properties=node.properties)

                logger.info(f"Stored {len(nodes)} nodes in Neo4j")
                return True

        except Exception as e:
            logger.error(f"Error storing nodes: {e}")
            return False

    def store_relationships(self, relationships: List[GraphRelationship]) -> bool:
        """Store multiple relationships in the graph."""
        try:
            with self.driver.session() as session:
                for rel in relationships:
                    query = (
                        """
                    MATCH (a {id: $start_id})
                    MATCH (b {id: $end_id})
                    MERGE (a)-[r:%s]->(b)
                    SET r += $properties
                    RETURN r
                    """
                        % rel.type
                    )

                    session.run(
                        query,
                        start_id=rel.start_node,
                        end_id=rel.end_node,
                        properties=rel.properties,
                    )

                logger.info(f"Stored {len(relationships)} relationships in Neo4j")
                return True

        except Exception as e:
            logger.error(f"Error storing relationships: {e}")
            return False

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a node by ID."""
        try:
            with self.driver.session() as session:
                result = session.run("MATCH (n {id: $id}) RETURN n", id=node_id)
                record = result.single()

                if record:
                    node = record["n"]
                    return GraphNode(
                        id=node["id"], labels=list(node.labels), properties=dict(node)
                    )
                return None

        except Exception as e:
            logger.error(f"Error getting node {node_id}: {e}")
            return None

    def get_neighbors(
        self, node_id: str, relationship_types: Optional[List[str]] = None
    ) -> List[GraphNode]:
        """Get neighboring nodes."""
        try:
            with self.driver.session() as session:
                if relationship_types:
                    rel_filter = "|".join(relationship_types)
                    query = f"MATCH (n {{id: $id}})-[:{rel_filter}]-(neighbor) RETURN neighbor"
                else:
                    query = "MATCH (n {id: $id})--(neighbor) RETURN neighbor"

                result = session.run(query, id=node_id)

                neighbors = []
                for record in result:
                    node = record["neighbor"]
                    neighbors.append(
                        GraphNode(
                            id=node["id"],
                            labels=list(node.labels),
                            properties=dict(node),
                        )
                    )

                return neighbors

        except Exception as e:
            logger.error(f"Error getting neighbors for {node_id}: {e}")
            return []

    def find_nodes_by_property(
        self, label: str, property_name: str, property_value: Any
    ) -> List[GraphNode]:
        """Find nodes by a property value."""
        try:
            with self.driver.session() as session:
                query = f"MATCH (n:{label}) WHERE n.{property_name} = $value RETURN n"
                result = session.run(query, value=property_value)

                nodes = []
                for record in result:
                    node = record["n"]
                    nodes.append(
                        GraphNode(
                            id=node["id"],
                            labels=list(node.labels),
                            properties=dict(node),
                        )
                    )

                return nodes

        except Exception as e:
            logger.error(f"Error finding nodes: {e}")
            return []

    def run_cypher(
        self, query: str, parameters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Run a custom Cypher query."""
        try:
            with self.driver.session() as session:
                result = session.run(query, parameters or {})
                return [record.data() for record in result]

        except Exception as e:
            logger.error(f"Error running Cypher query: {e}")
            return []

    def get_all_node_ids(self) -> List[str]:
        """Get all node IDs in the graph."""
        try:
            with self.driver.session() as session:
                result = session.run("MATCH (n) RETURN n.id as id")
                return [record["id"] for record in result]
        except Exception as e:
            logger.error(f"Error getting all node IDs: {e}")
            return []

    def clear_graph(self) -> bool:
        """Clear all nodes and relationships."""
        try:
            with self.driver.session() as session:
                session.run("MATCH (n) DETACH DELETE n")
                logger.info("Cleared Neo4j graph")
                return True
        except Exception as e:
            logger.error(f"Error clearing graph: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics."""
        try:
            with self.driver.session() as session:
                node_count = session.run("MATCH (n) RETURN count(n) as count").single()[
                    "count"
                ]
                rel_count = session.run(
                    "MATCH ()-[r]->() RETURN count(r) as count"
                ).single()["count"]

                return {"nodes": node_count, "relationships": rel_count}
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"nodes": 0, "relationships": 0}

    def health_check(self) -> bool:
        """Check if Neo4j is healthy."""
        try:
            with self.driver.session() as session:
                session.run("RETURN 1")
                return True
        except Exception as e:
            logger.error(f"Neo4j health check failed: {e}")
            return False
