from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles 
from pydantic import BaseModel
from typing import List                   # 
import database as db
import graph_store as gs
import agents

app = FastAPI(title="Personal Knowledge Graph")

app.add_middleware(
    CORSMiddleware,   # What if 
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],   # whats this .middleware for? It allows cross-origin requests, which is useful for frontend applications hosted on different domains to interact with this API
)  

db.init_db()

class EntryIn(BaseModel):   # 
    content: str
    source_type: str
    tags: List[str] = []
    is_query: bool = False

@app.post("/entries")
def create_entry(payload: EntryIn, background_tasks: BackgroundTasks): # 
    entry_id = db.insert_entry(payload.content, payload.source_type, payload.tags, payload.is_query)
    chunk_texts = agents.split_into_chunks(payload.content)
    db.insert_chunks(entry_id, chunk_texts)

    result = {"entry_id": entry_id, "saved": True}

    if payload.is_query:
        print("Processing query entry...")
        answer, meta = agents.answer_query(payload.content, entry_id)
        print("Answer generated:\n", answer)
        result["answer"] = answer
        result["meta"] = meta
        agents.run_organizer_on_entry(entry_id)
#--->
    else:
        background_tasks.add_task(agents.run_organizer_on_entry, entry_id)

    return result

@app.get("/entries")
def list_entries():
    return db.get_all_entries()

@app.get("/graph/stats")
def graph_stats():
    return gs.graph_stats()

@app.get("/graph/nodes")
def graph_nodes():
    return gs.all_nodes_summary()

@app.post("/graph/rebuild")
def rebuild_graph():
    agents.run_organizer_all()
    return gs.graph_stats()

@app.post("/reset")
def reset_all():
    db.reset_db()
    gs.reset_graph()
    return {"status": "reset"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")  
