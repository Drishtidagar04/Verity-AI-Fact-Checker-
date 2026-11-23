"""Check that your API keys load and work. Prints only the first 4 characters of the Groq key.
Run from the project root:  python scripts/check_keys.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verity.config import load_settings
from verity.services import build_llm, build_search

s = load_settings()
print("Groq key found:", bool(s.groq_api_key), "| starts with:", (s.groq_api_key or "")[:4], "(expect gsk_)")
print("Tavily key found:", bool(s.tavily_api_key), "| starts with:", (s.tavily_api_key or "")[:5], "(expect tvly-)")
try:
    print("Groq OK:", build_llm(s).complete_json("Reply with JSON", '{"ok": true}'))
except Exception as e:
    print("Groq FAIL:", e)
try:
    print("Tavily OK:", len(build_search(s).search("capital of France", max_results=2)), "results")
except Exception as e:
    print("Tavily FAIL:", e)
