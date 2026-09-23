import os
import pickle        # What is this pickle module for? It is used for serializing and deserializing Python objects, allowing you to save and load the graph structure to and from a file.
import networkx as nx
from config import GRAPH_PATH

_graph = None

def get_graph():
    global _graph
    if _graph is None:
        if os.path.exists(GRAPH_PATH):
            with open(GRAPH_PATH, "rb") as f:
                _graph = pickle.load(f)
        else:
            _graph = nx.DiGraph()
    return _graph

def save_graph():
    with open(GRAPH_PATH, "wb") as f:
        pickle.dump(get_graph(), f)

def reset_graph():
    global _graph
    _graph = nx.DiGraph()
    if os.path.exists(GRAPH_PATH):
        os.remove(GRAPH_PATH)

def normalize(name):
    return name.strip().lower()

def add_node(name, category, chunk_id):
    g = get_graph()
    key = normalize(name)
    if key not in g:
        g.add_node(key, display_name=name.strip(), category=category, source_chunk_ids=[chunk_id], mention_count=1)
    else:
        g.nodes[key]["mention_count"] = g.nodes[key].get("mention_count", 0) + 1
        if chunk_id not in g.nodes[key]["source_chunk_ids"]:
            g.nodes[key]["source_chunk_ids"].append(chunk_id)
    return key

def add_edge(source_name, target_name, label, chunk_id):
    g = get_graph()
    s = normalize(source_name)
    t = normalize(target_name)
    if g.has_edge(s, t):
        edge = g[s][t]
        if chunk_id not in edge["source_chunk_ids"]:
            edge["source_chunk_ids"].append(chunk_id)
    else:
        g.add_edge(s, t, label=label, source_chunk_ids=[chunk_id])

def find_matching_nodes(name):
    g = get_graph()
    key = normalize(name)
    if key in g:
        return [key]
    matches = []
    for node in g.nodes:
        if key in node or node in key:
            matches.append(node)
    return matches

def personalized_pagerank(seed_names, top_k=8):
    g = get_graph()
    if g.number_of_nodes() == 0:
        return []
    personalization = {}
    for name in seed_names:
        for node in find_matching_nodes(name):
            personalization[node] = 1.0
    if not personalization:
        return []
    total = sum(personalization.values())
    personalization = {k: v / total for k, v in personalization.items()}
    try:
        scores = nx.pagerank(g, personalization=personalization, alpha=0.85)
    except Exception:
        return []
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ranked[:top_k]

def get_node_source_chunks(node_keys):
    g = get_graph()
    chunk_ids = set()
    for node in node_keys:
        if node not in g:
            continue
        for cid in g.nodes[node].get("source_chunk_ids", []):
            chunk_ids.add(cid)
        for _, _, edata in g.out_edges(node, data=True):
            for cid in edata.get("source_chunk_ids", []):
                chunk_ids.add(cid)
        for _, _, edata in g.in_edges(node, data=True):
            for cid in edata.get("source_chunk_ids", []):
                chunk_ids.add(cid)
    return list(chunk_ids)

def graph_stats():
    g = get_graph()
    return {"nodes": g.number_of_nodes(), "edges": g.number_of_edges()}

def graph_neighborhood_summary(names, limit=15):
    g = get_graph()
    lines = []
    seen = set()
    for name in names:
        for node in find_matching_nodes(name):
            if node in seen:
                continue
            seen.add(node)
            for _, target, edata in list(g.out_edges(node, data=True))[:limit]:
                lines.append(f"{g.nodes[node]['display_name']} -[{edata['label']}]-> {g.nodes[target]['display_name']}")
            for source, _, edata in list(g.in_edges(node, data=True))[:limit]:
                lines.append(f"{g.nodes[source]['display_name']} -[{edata['label']}]-> {g.nodes[node]['display_name']}")
    return "\n".join(lines[:limit])

def all_nodes_summary(limit=200):
    g = get_graph()
    out = []
    for node, data in list(g.nodes(data=True))[:limit]:
        out.append({
            "name": data.get("display_name", node),
            "category": data.get("category"),
            "mentions": data.get("mention_count", 0)
        })
    return out

if __name__ == "__main__":
    
    # g = get_graph()
    # add_node("Alice", "person", 1)
    # add_node("Bob", "person", 2)
    # add_edge("Alice", "Bob", "knows", 3)
    # save_graph()
    # print(graph_stats())

    print(all_nodes_summary())
    print(find_matching_nodes("Tina"))
    