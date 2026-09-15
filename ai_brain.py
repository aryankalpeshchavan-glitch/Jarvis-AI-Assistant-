import os
import json
import asyncio
from typing import Dict, Any, Callable
from dotenv import load_dotenv

load_dotenv()

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

def process_command_with_ai(command: str, fallback_func: Callable[[str], Dict[str, Any]]) -> Dict[str, Any]:
    """
    Process a natural language command using Gemini.
    If the command is conversational, Gemini answers directly.
    If it's an automation task, Gemini calls the execute_automation_command tool.
    If Gemini is unavailable or fails, raises an exception to trigger fallback.
    """
    if not genai:
        raise RuntimeError("google-genai package not installed.")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or api_key == "mock_key_for_testing":
        raise RuntimeError("GEMINI_API_KEY not configured or is a mock key.")

    try:
        client = genai.Client(api_key=api_key)
        
        # Define the tool as a dictionary (standard format for google-genai)
        # Using the standard schema structure
        execute_automation_command = {
            "name": "execute_automation_command",
            "description": "Executes one or more PC automation commands (e.g., 'open chrome', 'lock screen', 'take a screenshot', 'shutdown', 'open downloads'). Use this for ANY request that requires interacting with the PC, opening an app/website, or system controls. Do NOT use this for conversational questions.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "commands": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "List of commands to execute. E.g., ['open chrome', 'search for fastapi']"
                    }
                },
                "required": ["commands"]
            }
        }

        tool = types.Tool(function_declarations=[execute_automation_command])
        
        system_instruction = "You are J.A.R.V.I.S., an AI desktop companion. You can chat with the user and answer questions. If the user asks you to perform PC actions, use the execute_automation_command tool. Pass natural language commands to the tool, such as 'open calculator' or 'shutdown'. Do NOT attempt to execute arbitrary shell scripts. Keep your conversational responses concise."

        config = types.GenerateContentConfig(
            tools=[tool],
            system_instruction=system_instruction,
            temperature=0.3
        )

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=command,
            config=config,
        )

        # Check if the model decided to call a function
        if response.function_calls:
            results = []
            errors = []
            for function_call in response.function_calls:
                if function_call.name == "execute_automation_command":
                    args = function_call.args
                    commands = []
                    if isinstance(args, dict) and "commands" in args:
                        commands = args["commands"]
                    elif hasattr(args, "commands"):
                        commands = args.commands
                    
                    for cmd in commands:
                        try:
                            # The fallback_func here is launch_app, which handles a single string 
                            # that might contain compound statements, but we assume the AI 
                            # broke them down into strings like "open chrome".
                            # Actually, fallback_func expects the raw command string.
                            res = fallback_func(cmd)
                            if "results" in res:
                                results.extend(res["results"])
                                if res.get("errors"):
                                    errors.extend(res["errors"])
                            else:
                                results.append(res)
                        except Exception as e:
                            errors.append(str(e))
                            
            if not results and errors:
                raise RuntimeError(" ".join(errors))
                
            return {
                "success": True,
                "message": response.text if response.text else "Executed successfully.",
                "details": {
                    "results": results,
                    "errors": errors,
                    "target": ", ".join(r.get("target", "") for r in results if r)
                }
            }
        
        # If no function was called, it's a conversational response
        return {
            "success": True,
            "chat": True,
            "category": "ai_response",
            "message": response.text
        }

    except Exception as e:
        raise RuntimeError(f"AI Brain failed: {str(e)}")
