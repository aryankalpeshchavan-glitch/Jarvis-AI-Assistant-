import os
import json
import asyncio
import logging
import time
from typing import Dict, Any, Callable
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("jarvis.ai_brain")

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

from ai_provider import GenerateContentProvider, ChatProvider, AIProvider
from response_types import AssistantResponse, CodeBlock

_provider_instance = None

def get_provider() -> "AIProvider":
    global _provider_instance
    if _provider_instance is not None and not os.environ.get("PYTEST_CURRENT_TEST"):
        return _provider_instance

    if not genai:
        raise RuntimeError("google-genai package not installed.")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or api_key == "mock_key_for_testing":
        raise RuntimeError("GEMINI_API_KEY not configured or is a mock key.")

    client = genai.Client(api_key=api_key)
    # Fixed: was "gemini-3.6-flash" (non-existent). Correct model: gemini-3.8-flash
    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")

    # Use ChatProvider (Interactions API) — required for this API key tier.
    # Falls back to GenerateContentProvider if explicitly overridden.
    if os.environ.get("USE_GENERATE_CONTENT_API") == "true":
        _provider_instance = GenerateContentProvider(client, model_name)
    else:
        _provider_instance = ChatProvider(client, model_name)

    log.info(f"AI provider initialized: {type(_provider_instance).__name__} / {model_name}")
    return _provider_instance


def clear_ai_context():
    global _provider_instance
    if _provider_instance is not None:
        _provider_instance.clear_context()
        log.info("AI context cleared.")


def process_command_with_ai(command: str, fallback_func: Callable = None) -> Dict[str, Any]:
    """
    Process a natural language command using Gemini and the Tool Registry.
    """
    provider = get_provider()

    system_instruction = (
        "You are J.A.R.V.I.S., an AI desktop companion. You can chat with the user and answer questions. "
        "If the user asks you to perform PC actions (like opening apps, searching the web, system controls), "
        "USE THE PROVIDED TOOLS. You can call multiple tools in sequence if needed. Keep conversational responses concise. "
        "If returning code, always use Markdown code blocks. For code, spoken_text should only be a short summary."
    )

    try:
        t0 = time.perf_counter()
        response: AssistantResponse = provider.process_command(command, system_instruction)
        t1 = time.perf_counter()

        log.info(f"Gemini responded in {t1-t0:.1f}s using {provider.model_name}")

        return {
            "success": response.success,
            "chat": response.intent == "conversation",
            "category": "ai_response",
            "message": response.message,
            "spoken_text": response.spoken_text or response.message,
            "code_blocks": [b.model_dump() for b in response.code_blocks],
            "details": {
                "results": response.actions_taken,
                "errors": [response.error] if response.error else [],
                "target": ", ".join(r.get("tool", "") for r in response.actions_taken if r)
            }
        }
    except Exception as e:
        raise RuntimeError(f"AI Brain failed: {str(e)}")


async def stream_command_with_ai(command: str):
    provider = get_provider()
    system_instruction = (
        "You are J.A.R.V.I.S., an AI desktop companion. You can chat with the user and answer questions. "
        "If the user asks you to perform PC actions (like opening apps, searching the web, system controls), "
        "USE THE PROVIDED TOOLS. You can call multiple tools in sequence if needed. Keep conversational responses concise. "
        "If returning code, always use Markdown code blocks. For code, spoken_text should only be a short summary."
    )

    try:
        async for chunk in provider.stream_command(command, system_instruction):
            yield chunk
    except Exception as e:
        import json
        yield json.dumps({"type": "error", "message": f"AI stream failed: {str(e)}"}) + "\n"
