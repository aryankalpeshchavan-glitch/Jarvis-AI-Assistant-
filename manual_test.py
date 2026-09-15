import asyncio
import os
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

print("--- Manual Test Verification ---")

# A. "Who are you?"
res = client.post("/launch", json={"command": "Who are you?"})
print("A. Who are you? ->", res.json())

# B. "Explain Docker containers."
res = client.post("/launch", json={"command": "Explain Docker containers."})
print("B. Explain Docker containers ->", res.json())

# C. "Open calculator."
res = client.post("/launch", json={"command": "Open calculator."})
print("C. Open calculator ->", res.json())

# D. "Open Chrome and search for FastAPI authentication."
res = client.post("/launch", json={"command": "Open Chrome and search for FastAPI authentication."})
print("D. Compound request ->", res.json())

# E. "Shutdown the computer."
res = client.post("/launch", json={"command": "Shutdown the computer."})
print("E. Shutdown ->", res.status_code, res.json())

# F. Disconnect/disable Gemini configuration
os.environ["GEMINI_API_KEY"] = "invalid_key_to_force_failure"
res = client.post("/launch", json={"command": "Open calculator."})
print("F. Disconnected Gemini ->", res.json())
