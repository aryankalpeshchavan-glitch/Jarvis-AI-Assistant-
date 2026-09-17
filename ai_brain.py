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

def process_command_with_ai(command: str, fallback_func: Callable = None) -> Dict[str, Any]:
    """
    Process a natural language command using Gemini and the Tool Registry.
    """
    import tools
    if not genai:
        raise RuntimeError("google-genai package not installed.")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or api_key == "mock_key_for_testing":
        raise RuntimeError("GEMINI_API_KEY not configured or is a mock key.")

    try:
        client = genai.Client(api_key=api_key)
        
        # Load structured tool declarations from our Tool Engine
        tool = types.Tool(function_declarations=tools.registry.schemas)
        
        system_instruction = "You are J.A.R.V.I.S., an AI desktop companion. You can chat with the user and answer questions. If the user asks you to perform PC actions (like opening apps, searching the web, system controls), USE THE PROVIDED TOOLS. You can call multiple tools in sequence if needed. Keep conversational responses concise and do not include raw JSON in your final answer."

        config = types.GenerateContentConfig(
            tools=[tool],
            system_instruction=system_instruction,
            temperature=0.3
        )

        model_name = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
        response = client.models.generate_content(
            model=model_name,
            contents=command,
            config=config,
        )

        # Check if the model decided to call a function
        if response.function_calls:
            results = []
            errors = []
            for function_call in response.function_calls:
                tool_name = function_call.name
                args = function_call.args
                
                # Extract arguments safely
                kwargs = {}
                if isinstance(args, dict):
                    kwargs = args
                elif hasattr(args, "items"):
                    kwargs = dict(args)
                elif hasattr(args, "__dict__"):
                    kwargs = {k: v for k, v in args.__dict__.items() if not k.startswith("_")}
                
                # Execute tool
                res = tools.registry.execute(tool_name, kwargs)
                if not res.get("success"):
                    errors.append(res.get("message"))
                results.append(res)
                            
            if errors:
                raise RuntimeError(" ".join(str(e) for e in errors))
            
            # Turn 2: Generate natural language summary of the results
            summary_prompt = (
                f"The user commanded: '{command}'.\n\n"
                f"You executed tools with these results: {json.dumps(results)}\n\n"
                f"Please provide a very short, natural language summary (1-2 sentences) of what you just did for the user. Do not expose JSON or raw tool names."
            )
            
            final_response = client.models.generate_content(
                model=model_name,
                contents=summary_prompt,
                config=types.GenerateContentConfig(system_instruction=system_instruction, temperature=0.3)
            )
                
            return {
                "success": True,
                "message": final_response.text if final_response.text else "Executed successfully.",
                "details": {
                    "results": results,
                    "errors": errors,
                    "target": ", ".join(r.get("tool", "") for r in results if r)
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
