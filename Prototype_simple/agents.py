import json
import database as db
import graph_store as gs
from llm_client import call_llm
from config import PAGERANK_TOP_K

CATEGORIES = ["language", "framework_or_library", "tool", "concept", "project",
              "person", "organization", "place", "event", "resource", "other"]

EXTRACTION_SYSTEM_PROMPT = f"""You extract structured knowledge triples from a piece of text for a personal knowledge graph.
Return ONLY a JSON object with this exact shape:
{{"entities": [{{"name": "string", "category": "one of {CATEGORIES}"}}], "relations": [{{"source": "string", "relation": "string", "target": "string"}}]}}
Entity names must be short, normalized, singular where sensible. Only create relations between entities you listed.
If the text has no extractable knowledge, return {{"entities": [], "relations": []}}.
"""

RETRIEVAL_SEED_PROMPT = """Given the user's query, extract the key entities/concepts to search for in a knowledge graph.
Return ONLY JSON: {"seeds": ["entity1", "entity2"]}
"""

ANSWER_SYSTEM_PROMPT = """You are answering a question using retrieved notes from the user's personal knowledge base.
Use only the provided context. If the context is insufficient, say so honestly and answer as best you can.
Be concise and direct."""

def split_into_chunks(content):
    parts = [p.strip() for p in content.split("\n\n") if p.strip()]
    if not parts:
        parts = [content.strip()]
    return parts

# 
def process_chunk(chunk, process_id):
    chunk_id = chunk["id"]
    entry_id = chunk["entry_id"]
    db.log_step(process_id, entry_id, chunk_id, "organizer", "extract_triples", "started")
    try:
        raw = call_llm(EXTRACTION_SYSTEM_PROMPT, chunk["chunk_text"], json_mode=True)
        print(f"Raw LLM output for chunk {chunk_id}:\n{raw}")
        data = json.loads(raw)
    except Exception as e:
        db.log_step(process_id, entry_id, chunk_id, "organizer", "extract_triples", "failed", {"error": str(e)})
        db.mark_chunk_processed(chunk_id)
        return
    db.log_step(process_id, entry_id, chunk_id, "organizer", "extract_triples", "success", data)

    for ent in data.get("entities", []):
        name = ent.get("name")
        category = ent.get("category", "other")
        if category not in CATEGORIES:
            category = "other"
        if name:
            gs.add_node(name, category, chunk_id)

    for rel in data.get("relations", []):
        source = rel.get("source")
        target = rel.get("target")
        label = rel.get("relation", "related_to")
        if source and target:
            if gs.normalize(source) not in gs.get_graph():
                gs.add_node(source, "other", chunk_id)
            if gs.normalize(target) not in gs.get_graph():
                gs.add_node(target, "other", chunk_id)
            gs.add_edge(source, target, label, chunk_id)

    gs.save_graph()
    db.log_step(process_id, entry_id, chunk_id, "organizer", "write_graph", "success", gs.graph_stats())
    db.mark_chunk_processed(chunk_id)


# ----> As it turns out, problem is after that print statement. Maybe here, maybe afterwards.
# The background task not working. Gotta check whats wrong, and then we revamp te whole thing, We gonna use 
# Some background worker.
def run_organizer_on_entry(entry_id):
    print(f"Running organizer on entry {entry_id}...")
    process_id = db.new_process_id()
    relevant = [c for c in db.get_unprocessed_chunks() if c["entry_id"] == entry_id]
    for chunk in relevant:
        process_chunk(chunk, process_id)

def run_organizer_all():
    process_id = db.new_process_id()
    for chunk in db.get_unprocessed_chunks():
        process_chunk(chunk, process_id)

def answer_query(query_text, entry_id):
    process_id = db.new_process_id()
    db.log_step(process_id, entry_id, None, "retriever", "extract_seeds", "started")
    try:
        raw = call_llm(RETRIEVAL_SEED_PROMPT, query_text, json_mode=True)
        seeds = json.loads(raw).get("seeds", [])
    except Exception:
        print("exception throw, seeds: ", seeds)
        seeds = [query_text]
    db.log_step(process_id, entry_id, None, "retriever", "extract_seeds", "success", {"seeds": seeds})

    ranked_nodes = gs.personalized_pagerank(seeds, top_k=PAGERANK_TOP_K)
    node_keys = [n for n, _ in ranked_nodes]
    chunk_ids = gs.get_node_source_chunks(node_keys)
    chunks = db.get_chunks_by_ids(chunk_ids)
    db.log_step(process_id, entry_id, None, "retriever", "graph_retrieval", "success",
                {"ranked_nodes": ranked_nodes, "chunk_ids": chunk_ids})

    context_text = "\n---\n".join(c["chunk_text"] for c in chunks)
    graph_context = gs.graph_neighborhood_summary(seeds)

    print("no relavant info found in db")
    if not context_text.strip() and not graph_context.strip():
        
        answer = f"""Cant fetch any saved information. 
        Generated answer : {call_llm(ANSWER_SYSTEM_PROMPT, f"User's query: {query_text}")}
                """
    else:
        user_prompt = f"Question: {query_text}\n\nRetrieved graph relations:\n{graph_context}\n\nRetrieved notes:\n{context_text}"
        try:
            answer = call_llm(ANSWER_SYSTEM_PROMPT, user_prompt)
        except Exception as e:
            answer = f"Failed to generate an answer: {e}"

    db.log_step(process_id, entry_id, None, "retriever", "compose_answer", "success", {"answer": answer})
    return answer, {"seeds": seeds, "ranked_nodes": ranked_nodes, "chunks_used": len(chunks)}


if __name__ == "__main__":
   result = call_llm(EXTRACTION_SYSTEM_PROMPT, "Tina is Mina's friend but Mina doesn't like her, they went to a hotel once together, and they did not have a good time.", json_mode=True)
   print(result)