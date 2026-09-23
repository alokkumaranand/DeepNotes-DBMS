import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
DB_PATH = os.getenv("DB_PATH", "kb.sqlite3")
GRAPH_PATH = os.getenv("GRAPH_PATH", "graph.pkl")
PAGERANK_TOP_K = int(os.getenv("PAGERANK_TOP_K", "8"))
