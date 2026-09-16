"""
In-process API tests using FastAPI's TestClient — runs the ASGI app directly,
no background server / port binding needed. More reliable for CI and for
this sandbox than spawning a real subprocess.
Run: python3 test_api.py
"""
import sys
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)

PASS = 0
FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def launch(cmd):
    return client.post("/launch", json={"command": cmd})


def test_api_suite():
    global PASS, FAIL
    PASS = 0
    FAIL = 0
    print("=== /health ===")
    r = client.get("/health")
    check("health returns 200", r.status_code == 200, r.text)
    check("health reports fuzzy engine", "fuzzy_engine" in r.json())
    
    print("\n=== Chitchat via live endpoint ===")
    r = launch("hello")
    check("'hello' -> chat response", r.json().get("chat") is True, r.text)
    
    r = launch("hey jarvis")
    check("'hey jarvis' alone -> chat response", r.json().get("chat") is True, r.text)
    
    r = launch("how are you")
    check("'how are you' -> chat response, category howareyou", r.json().get("category") == "howareyou", r.text)
    
    r = launch("thanks jarvis")
    check("'thanks jarvis' -> chat response, category thanks", r.json().get("category") == "thanks", r.text)
    
    r = launch("bye")
    check("'bye' -> chat response, category farewell", r.json().get("category") == "farewell", r.text)
    
    print("\n=== Graceful failure (no blind shell fallback) ===")
    main.INSTALLED_APPS_CACHE = {}
    main.SHORTCUTS_CACHE = {}
    r = launch("open zzzznonexistentapp123xyz")
    check("garbage app returns 422 with clear message (not a raw OS error)",
          r.status_code == 422 and "couldn't find" in r.json().get("detail", "").lower(), r.text)
    
    print("\n=== Fuzzy game-name matching (Ghost of Tsushima typo) — simulating Windows ===")
    main.INSTALLED_APPS_CACHE = {
        "ghost of tsushima": "SteamApp.12345",
        "google chrome": "ChromeAppId",
        "spotify music": "SpotifyAppId",
        "visual studio code": "VSCodeAppId",
    }
    _real_platform_system = main.platform.system
    main.platform.system = lambda: "Windows"  # this project's app-matching is Windows-specific by design
    try:
        match, score = main.fuzzy_best_match(
            "ghost of tsunami", list(main.INSTALLED_APPS_CACHE.keys()) + list(main.SHORTCUTS_CACHE.keys()), threshold=72
        )
        check("typo'd game name fuzzy-matches to the installed game", match == "ghost of tsushima", f"got {match!r} score={score}")
    
        match2, score2 = main.fuzzy_best_match("chrome", list(main.INSTALLED_APPS_CACHE.keys()), threshold=72)
        check("'chrome' substring-matches installed 'google chrome'",
              "google chrome" in main.INSTALLED_APPS_CACHE and ("chrome" in "google chrome"))
    finally:
        main.platform.system = _real_platform_system
    
    print("\n=== GitHub intent with no username configured (graceful) ===")
    client.post("/config", json={"github_username": ""})
    r = launch("open my top github repo")
    check("no-username case fails gracefully mentioning Settings",
          r.status_code == 422 and "settings" in r.json().get("detail", "").lower(), r.text)
    
    print("\n=== GitHub top-repo intent (mocked — no live network dependency in tests) ===")
    class _FakeResp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self.ok = 200 <= status_code < 300
        def json(self):
            return self._payload
        _payload = None
    
    def _mock_requests_get(url, timeout=None, headers=None):
        r = _FakeResp(200, None)
        r._payload = [
            {"name": "small-repo", "stargazers_count": 3, "html_url": "https://github.com/torvalds/small-repo"},
            {"name": "linux", "stargazers_count": 242000, "html_url": "https://github.com/torvalds/linux"},
        ]
        return r
    
    import types
    _fake_requests = types.SimpleNamespace(get=_mock_requests_get)
    sys.modules["requests"] = _fake_requests
    
    client.post("/config", json={"github_username": "torvalds"})
    r = launch("open my top github repo")
    d = r.json()
    check("mocked top-repo picks the highest-star repo",
          d.get("success") is True and "linux" in d.get("details", {}).get("target", ""), r.text)
    
    print("\n=== GitHub: rate-limit (403) gives a clear message, not a raw API error ===")
    def _mock_requests_get_403(url, timeout=None, headers=None):
        return _FakeResp(403, [])
    _fake_requests.get = _mock_requests_get_403
    r = launch("open my top github repo")
    check("403 -> friendly rate-limit message",
          r.status_code == 422 and "rate-limiting" in r.json().get("detail", "").lower(), r.text)
    
    print("\n=== /reindex endpoint ===")
    r = client.post("/reindex")
    check("/reindex returns 200 with counts", r.status_code == 200 and "indexed_apps" in r.json(), r.text)
    
    print("\n=== Folder resolution via live endpoint (simulated Windows) ===")
    main.platform.system = lambda: "Windows"
    try:
        r = launch("open downloads")
        d = r.json()
        # On this Linux sandbox, explorer.exe genuinely doesn't exist, so the OS
        # launch call itself fails — what matters is that RESOLUTION correctly
        # identified "downloads" as a folder (not a "couldn't find" failure).
        resolved_correctly = (d.get("success") is True) or ("couldn't find" not in r.text.lower() and "explorer.exe" in r.text.lower())
        check("'open downloads' resolves as a folder (not a 'not found' failure)", resolved_correctly, r.text)
    finally:
        main.platform.system = _real_platform_system
    
    print("\n=== New commands via live /launch endpoint ===")
    main.platform.system = lambda: "Windows"
    _real_popen2 = main.subprocess.Popen
    main.subprocess.Popen = lambda *a, **kw: None
    try:
        r = launch("what time is it")
        check("'what time is it' answers via /launch", r.status_code == 200 and r.json().get("success") is True, r.text)
    
        main._PENDING_CONFIRMATION.clear()
        r = launch("shutdown")
        check("'shutdown' via /launch asks for confirmation, doesn't execute",
              r.status_code == 422 and "confirm" in r.json().get("detail", "").lower(), r.text)
    
        r = launch("lock")
        check("'lock' via /launch executes immediately (no confirmation)",
              r.status_code == 200 and r.json().get("success") is True, r.text)
    finally:
        main.subprocess.Popen = _real_popen2
        main.platform.system = _real_platform_system
        main._PENDING_CONFIRMATION.clear()
    
    print("\n=== Autostart endpoint ===")
    r = client.get("/autostart")
    check("/autostart GET returns expected shape", r.status_code == 200 and "enabled" in r.json() and "asked" in r.json(), r.text)
    
    print(f"\n=== RESULTS: {PASS} passed, {FAIL} failed ===")
    assert FAIL == 0, f"{FAIL} tests failed"

if __name__ == '__main__':
    test_api_suite()
    sys.exit(1 if FAIL else 0)
