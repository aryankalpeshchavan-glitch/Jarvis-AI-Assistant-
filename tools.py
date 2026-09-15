import urllib.parse
from typing import Dict, Any, Callable, List
import main
import psutil

class RiskLevel:
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    DANGEROUS = "DANGEROUS"

class ToolRegistry:
    def __init__(self):
        self.tools = {}
        self.schemas = []

    def register(self, name: str, description: str, risk: str, parameters: Dict[str, Any], func: Callable):
        self.tools[name] = {
            "func": func,
            "risk": risk
        }
        
        schema = {
            "name": name,
            "description": description,
            "parameters": {
                "type": "OBJECT",
                "properties": parameters,
            }
        }
        # Mark all defined properties as required by default
        if parameters:
            schema["parameters"]["required"] = list(parameters.keys())
        
        self.schemas.append(schema)

    def execute(self, name: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self.tools:
            return {"success": False, "tool": name, "message": f"Tool '{name}' not found in registry."}

        tool_meta = self.tools[name]
        try:
            # If it's a DANGEROUS tool, the underlying main.py functions already 
            # throw a RuntimeError("Say 'confirm'...") which acts as our safety gate.
            result = tool_meta["func"](**kwargs)
            return {
                "success": True,
                "tool": name,
                "message": "Execution successful",
                "data": result or {}
            }
        except RuntimeError as e:
            # This captures the safety confirmation requirement ("Say 'confirm'...")
            # as well as natural failures (e.g., "App not found")
            return {
                "success": False,
                "tool": name,
                "message": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "tool": name,
                "message": f"Unexpected error: {str(e)}"
            }

registry = ToolRegistry()

# ─── Tool Wrappers ──────────────────────────────────────────────────────────

def open_app(name: str):
    return main.launch_native_app(name)

def open_folder(path: str):
    # Try resolving special folders first
    special = main.resolve_special_folder(path)
    if special:
        return main.open_folder(special)
    
    # Try searching for a named folder
    named = main.search_named_folder(path)
    if named:
        return main.open_folder(str(named))
    
    # Fallback to direct path
    return main.open_folder(path)

def open_url(url: str):
    return main.open_website(url)

def web_search(query: str):
    url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
    return main.open_website(url)

def take_screenshot():
    return main.resolve_utility_command("take a screenshot")

def get_time():
    return main.resolve_utility_command("what time is it")

def get_date():
    return main.resolve_utility_command("what's the date")

def get_system_info():
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    return {
        "cpu_usage_percent": cpu,
        "memory_usage_percent": mem.percent,
        "memory_total_gb": round(mem.total / (1024**3), 2),
        "memory_used_gb": round(mem.used / (1024**3), 2)
    }

def volume_control(action: str):
    if action not in ("mute", "unmute", "volume up", "increase volume", "volume down", "decrease volume"):
        raise ValueError("Invalid volume action. Must be mute, unmute, volume up, or volume down.")
    return main.resolve_media_command(action)

def media_control(action: str):
    if action not in ("play", "pause", "play pause", "next track", "previous track"):
        raise ValueError("Invalid media action.")
    return main.resolve_media_command(action)

def close_app(name: str):
    return main.close_app(name)

def shutdown():
    return main.resolve_system_command("shutdown")

def restart():
    return main.resolve_system_command("restart")

def sleep():
    return main.resolve_system_command("sleep")

def empty_recycle_bin():
    return main.resolve_utility_command("empty recycle bin")

# ─── Tool Registrations ─────────────────────────────────────────────────────

registry.register(
    "open_app", "Open a Windows application or game by name.", RiskLevel.SAFE,
    {"name": {"type": "STRING", "description": "Name of the app (e.g., 'chrome', 'calculator', 'Ghost of Tsushima')"}},
    open_app
)

registry.register(
    "open_folder", "Open a folder by name or path.", RiskLevel.SAFE,
    {"path": {"type": "STRING", "description": "Folder name (e.g. 'downloads', 'desktop') or path"}},
    open_folder
)

registry.register(
    "open_url", "Open a specific URL in the default browser.", RiskLevel.SAFE,
    {"url": {"type": "STRING", "description": "The full URL to open"}},
    open_url
)

registry.register(
    "web_search", "Perform a Google search for the given query.", RiskLevel.SAFE,
    {"query": {"type": "STRING", "description": "The search query"}},
    web_search
)

registry.register(
    "take_screenshot", "Take a screenshot of the main display and save it to Pictures.", RiskLevel.SAFE,
    {}, take_screenshot
)

registry.register(
    "get_time", "Get the current time.", RiskLevel.SAFE,
    {}, get_time
)

registry.register(
    "get_date", "Get the current date.", RiskLevel.SAFE,
    {}, get_date
)

registry.register(
    "get_system_info", "Get current CPU and memory usage.", RiskLevel.SAFE,
    {}, get_system_info
)

registry.register(
    "volume_control", "Control system volume.", RiskLevel.SAFE,
    {"action": {"type": "STRING", "description": "One of: 'mute', 'unmute', 'volume up', 'volume down'"}},
    volume_control
)

registry.register(
    "media_control", "Control media playback.", RiskLevel.SAFE,
    {"action": {"type": "STRING", "description": "One of: 'play', 'pause', 'next track', 'previous track'"}},
    media_control
)

registry.register(
    "close_app", "Close a running application by name.", RiskLevel.CAUTION,
    {"name": {"type": "STRING", "description": "Name of the app to close"}},
    close_app
)

registry.register(
    "shutdown", "Shut down the computer (Requires user confirmation).", RiskLevel.DANGEROUS,
    {}, shutdown
)

registry.register(
    "restart", "Restart the computer (Requires user confirmation).", RiskLevel.DANGEROUS,
    {}, restart
)

registry.register(
    "sleep", "Put the computer to sleep.", RiskLevel.SAFE,
    {}, sleep
)

registry.register(
    "empty_recycle_bin", "Empty the Windows Recycle Bin.", RiskLevel.DANGEROUS,
    {}, empty_recycle_bin
)
