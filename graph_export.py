"""
graph_export.py — Export a project graph to GEXF via NetworkX.
"""

import networkx as nx
from pathlib import Path


def build_nx_graph(nodes: list[dict], edges: list[dict]) -> nx.DiGraph:
    """
    Convert flat node/edge dicts to a NetworkX directed graph.

    Node attributes stored: label, kind
    Edge attributes stored: type
    """
    G = nx.DiGraph()

    for node in nodes:
        node_id = node["id"]
        G.add_node(node_id, label=node.get("label", node_id), kind=node.get("kind", ""))

    for edge in edges:
        src = edge.get("source")
        dst = edge.get("target")
        if src and dst:
            # "type" is reserved in GEXF (directed/undirected), so store as "edge_type"
            G.add_edge(src, dst, edge_type=edge.get("type", ""))

    return G


def export_gexf(nodes: list[dict], edges: list[dict], output_path: Path) -> None:
    """
    Build a NetworkX DiGraph from *nodes* and *edges* and write it as GEXF.

    Args:
        nodes:       List of node dicts with keys: id, label, kind.
        edges:       List of edge dicts with keys: source, target, type.
        output_path: Destination .gexf file path.
    """
    G = build_nx_graph(nodes, edges)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_gexf(G, str(output_path))
