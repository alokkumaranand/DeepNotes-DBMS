from database import get_all_entries
from graph_store import get_graph, save_graph, reset_graph, add_node, add_edge, find_matching_nodes, all_nodes_summary
import agents
import config


def test_get_all_entries():
    entries = get_all_entries()
    print(f"Retrieved {len(entries)} entries from the database.")
    print("Sample entry:", entries[0] if entries else "No entries found.")

