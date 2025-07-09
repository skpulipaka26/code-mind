import networkx as nx


class KnowledgeGraph:
    def __init__(self):
        self.graph = nx.Graph()

    def add_node(self, node_id, node_type, attributes=None):
        if attributes is None:
            attributes = {}
        self.graph.add_node(node_id, type=node_type, **attributes)

    def add_edge(self, u, v, edge_type, attributes=None):
        if attributes is None:
            attributes = {}
        self.graph.add_edge(u, v, type=edge_type, **attributes)

    def get_node_attributes(self, node_id):
        return self.graph.nodes[node_id]

    def get_edge_attributes(self, u, v):
        return self.graph.edges[(u, v)]

    def get_neighbors(self, node_id):
        return list(self.graph.neighbors(node_id))

    def get_nodes_by_type(self, node_type):
        return [
            node
            for node, data in self.graph.nodes(data=True)
            if data.get("type") == node_type
        ]

    def detect_communities(self, algorithm="louvain"):
        if algorithm == "louvain":
            try:
                import community as co

                partition = co.best_partition(self.graph)
                communities = {}
                for node, comm_id in partition.items():
                    if comm_id not in communities:
                        communities[comm_id] = []
                    communities[comm_id].append(node)
                return communities
            except ImportError:
                print(
                    "python-louvain not installed. Please install it using 'pip install python-louvain'"
                )
                return None
        else:
            raise ValueError(f"Unsupported community detection algorithm: {algorithm}")

    def get_subgraph(self, nodes):
        return self.graph.subgraph(nodes)
