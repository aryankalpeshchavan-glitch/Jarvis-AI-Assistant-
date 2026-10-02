import os
import json
import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Any, List, Optional, AsyncGenerator
from google import genai
from google.genai import types
from google.genai import errors
from pydantic import BaseModel, ValidationError

from response_types import AssistantResponse, CodeBlock

log = logging.getLogger("jarvis.ai_provider")


class AIProvider(ABC):
    @abstractmethod
    def process_command(self, command: str, system_instruction: str) -> AssistantResponse:
        pass

    @abstractmethod
    async def stream_command(self, command: str, system_instruction: str) -> AsyncGenerator[str, None]:
        yield ""

    @abstractmethod
    def clear_context(self):
        pass


# ──────────────────────────────────────────────────────────────────
# ChatProvider — uses client.chats.create (Interactions/Chat API)
# Required for the API key tier in use. Recommended by Google.
# ──────────────────────────────────────────────────────────────────
class ChatProvider(AIProvider):
    def __init__(self, client: genai.Client, model_name: str):
        self.client = client
        self.model_name = model_name
        self._chat = None  # lazy-initialised on first use
        self._system_instruction: Optional[str] = None

    def _get_or_create_chat(self, system_instruction: str):
        """Return existing chat session or create a new one (also recreates if system changes)."""
        if self._chat is None or system_instruction != self._system_instruction:
            import tools
            tool_decl = types.Tool(function_declarations=tools.registry.schemas)
            self._chat = self.client.chats.create(
                model=self.model_name,
                config=types.GenerateContentConfig(
                    tools=[tool_decl],
                    system_instruction=system_instruction,
                    temperature=0.3,
                )
            )
            self._system_instruction = system_instruction
        return self._chat

    def clear_context(self):
        self._chat = None
        self._system_instruction = None

    def _execute_with_retry(self, func, *args, **kwargs):
        import time as _time
        max_retries = 5
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except errors.ServerError as e:
                if e.code == 503 and attempt < max_retries - 1:
                    wait = min(2 ** attempt, 16)  # cap at 16s
                    log.warning(f"503 Service Unavailable, retrying in {wait}s (attempt {attempt+1})...")
                    _time.sleep(wait)
                    continue
                raise
            except Exception:
                raise

    def process_command(self, command: str, system_instruction: str) -> AssistantResponse:
        import response_parser
        chat = self._get_or_create_chat(system_instruction)

        try:
            response = self._execute_with_retry(chat.send_message, command)
        except errors.ServerError as e:
            if e.code == 503:
                return AssistantResponse(
                    success=False, intent="error",
                    message="I'm having trouble connecting to Google's servers right now.",
                    error="AI_PROVIDER_UNAVAILABLE"
                )
        except errors.ClientError as e:
            log.error(f"Gemini ClientError: {e}")
            if getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                return AssistantResponse(
                    success=False, intent="error",
                    message="Gemini API rate limit reached. Please wait a moment before trying again.",
                    error="AI_RATE_LIMIT"
                )
            raise RuntimeError(f"Gemini API error: {e}")

        actions_taken = []

        # Handle tool calls
        if response.function_calls:
            import tools
            tool_responses = []
            errors_list = []
            for function_call in response.function_calls:
                tool_name = function_call.name
                args = function_call.args
                kwargs = args if isinstance(args, dict) else (dict(args) if hasattr(args, "items") else {})
                res = tools.registry.execute(tool_name, kwargs)
                if not res.get("success"):
                    errors_list.append(res.get("message", "Tool failed"))
                actions_taken.append(res)
                tool_responses.append(
                    types.Part.from_function_response(name=tool_name, response=res)
                )

            if errors_list:
                raise RuntimeError(" ".join(str(e) for e in errors_list))

            # Send tool results back to continue the conversation
            try:
                final_response = self._execute_with_retry(
                    chat.send_message,
                    types.Content(role="user", parts=tool_responses)
                )
                result_text = final_response.text or ""
            except Exception as e:
                raise RuntimeError(f"Tool follow-up failed: {e}")

            result_msg = result_text.strip() or "; ".join(
                r.get("message", "") for r in actions_taken if r.get("success")
            ) or "Done."
            return AssistantResponse(
                success=True, intent="tool_action",
                message=result_msg, spoken_text=result_msg,
                actions_taken=actions_taken
            )

        # Conversational / code response
        full_text = response.text or ""
        try:
            parsed = response_parser.parse_response(full_text)
            code_blocks = [CodeBlock(language=cb["language"], code=cb["code"])
                           for cb in parsed["code_blocks"]]
            return AssistantResponse(
                success=True,
                intent="code" if code_blocks else "conversation",
                message=full_text,
                spoken_text=parsed.get("explanation", full_text) if code_blocks else full_text,
                code_blocks=code_blocks,
                actions_taken=actions_taken
            )
        except Exception:
            return AssistantResponse(
                success=True, intent="conversation",
                message=full_text, spoken_text=full_text,
                actions_taken=actions_taken
            )

    async def stream_command(self, command: str, system_instruction: str) -> AsyncGenerator[str, None]:
        import tools
        import response_parser

        yield json.dumps({"type": "status", "status": "ANALYZING"}) + "\n"

        chat = await asyncio.to_thread(self._get_or_create_chat, system_instruction)

        try:
            response = await asyncio.to_thread(
                self._execute_with_retry,
                chat.send_message,
                command
            )
        except errors.ServerError as e:
            err_str = str(e)
            log.error(f"Gemini ServerError in stream (code={e.code}): {err_str}")
            if e.code == 503:
                yield json.dumps({"type": "error", "message": "Google's AI service is temporarily overloaded. Please try again in a moment."}) + "\n"
                return
            elif e.code == 429 or "RESOURCE_EXHAUSTED" in err_str:
                yield json.dumps({"type": "error", "message": "Gemini rate limit reached. Please wait a moment before trying again."}) + "\n"
                return
            yield json.dumps({"type": "error", "message": f"Gemini server error ({e.code}). Please try again."}) + "\n"
            return
        except errors.ClientError as e:
            err_str = str(e)
            log.error(f"Gemini ClientError in stream: {err_str}")
            if getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
                yield json.dumps({"type": "error", "message": "Gemini rate limit reached. Please wait a moment before trying again."}) + "\n"
                return
            if "401" in err_str or "403" in err_str or "API_KEY" in err_str or "authentication" in err_str.lower():
                yield json.dumps({"type": "error", "message": "Gemini API authentication error. Please check your API key."}) + "\n"
                return
            yield json.dumps({"type": "error", "message": f"Gemini API error: {err_str[:120]}"}) + "\n"
            return
        except Exception as e:
            err_str = str(e)
            log.error(f"Unexpected AI error in stream [{type(e).__name__}]: {err_str}")
            if "503" in err_str or "unavailable" in err_str.lower():
                yield json.dumps({"type": "error", "message": "Google's AI service is temporarily overloaded. Please try again."}) + "\n"
            elif "429" in err_str or "quota" in err_str.lower() or "RESOURCE_EXHAUSTED" in err_str:
                yield json.dumps({"type": "error", "message": "Gemini rate limit reached. Please wait a moment."}) + "\n"
            else:
                yield json.dumps({"type": "error", "message": f"AI error: {err_str[:120]}"}) + "\n"
            return

        actions_taken = []

        if response.function_calls:
            yield json.dumps({"type": "status", "status": "EXECUTING TOOLS"}) + "\n"

            tool_responses = []
            errors_list = []
            for function_call in response.function_calls:
                tool_name = function_call.name
                args = function_call.args
                kwargs = args if isinstance(args, dict) else (dict(args) if hasattr(args, "items") else {})
                res = await asyncio.to_thread(tools.registry.execute, tool_name, kwargs)
                if not res.get("success"):
                    errors_list.append(res.get("message", "Tool failed"))
                actions_taken.append(res)
                tool_responses.append(types.Part.from_function_response(name=tool_name, response=res))

            if errors_list:
                err_msg = "; ".join(str(e) for e in errors_list)
                yield json.dumps({"type": "done", "response": {
                    "success": False, "intent": "error", "message": err_msg,
                    "spoken_text": err_msg, "code_blocks": [], "actions_taken": actions_taken
                }}) + "\n"
                return

            yield json.dumps({"type": "status", "status": "THINKING"}) + "\n"

            try:
                final_response = await asyncio.to_thread(
                    self._execute_with_retry,
                    chat.send_message,
                    types.Content(role="user", parts=tool_responses)
                )
                full_text = final_response.text or ""
            except Exception as e:
                yield json.dumps({"type": "error", "message": str(e)}) + "\n"
                return

            result_msg = full_text.strip() or "; ".join(
                r.get("message", "") for r in actions_taken if r.get("success")
            ) or "Done."
            yield json.dumps({"type": "done", "response": {
                "success": True, "intent": "tool_action", "message": result_msg,
                "spoken_text": result_msg, "code_blocks": [],
                "actions_taken": actions_taken
            }}) + "\n"

        else:
            # Conversational / code response
            full_text = response.text or ""

            if full_text:
                yield json.dumps({"type": "chunk", "text": full_text}) + "\n"

            parsed = response_parser.parse_response(full_text)
            code_blocks = [
                {"language": cb["language"], "code": cb["code"], "label": cb.get("language", "Code")}
                for cb in parsed["code_blocks"]
            ]
            explanation = parsed.get("explanation", full_text)
            spoken = response_parser.sanitize_for_tts(explanation) if code_blocks else response_parser.sanitize_for_tts(full_text)

            yield json.dumps({"type": "done", "response": {
                "success": True,
                "intent": "code" if code_blocks else "conversation",
                "message": full_text,
                "spoken_text": (spoken or "I've generated the requested code.") if code_blocks else spoken,
                "code_blocks": code_blocks,
                "actions_taken": []
            }}) + "\n"


# ──────────────────────────────────────────────────────────────────
# GenerateContentProvider — kept as fallback (opt-in via env var)
# ──────────────────────────────────────────────────────────────────
class GenerateContentProvider(AIProvider):
    def __init__(self, client: genai.Client, model_name: str, max_history: int = 10):
        self.client = client
        self.model_name = model_name
        self.max_history = max_history
        self._history: List[types.Content] = []

    def clear_context(self):
        self._history.clear()

    def _execute_with_retry(self, func, *args, **kwargs):
        import time as _time
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except errors.APIError as e:
                if e.code == 503:
                    if attempt < max_retries - 1:
                        log.warning(f"503 Service Unavailable, retrying in {2 ** attempt} seconds...")
                        _time.sleep(2 ** attempt)
                        continue
                raise
            except Exception:
                raise

    def process_command(self, command: str, system_instruction: str) -> AssistantResponse:
        import tools
        import response_parser
        tool_decl = types.Tool(function_declarations=tools.registry.schemas)
        config = types.GenerateContentConfig(
            tools=[tool_decl],
            system_instruction=system_instruction,
            temperature=0.3
        )
        self._history.append(types.Content(role="user", parts=[types.Part.from_text(text=command)]))
        try:
            response = self._execute_with_retry(
                self.client.models.generate_content,
                model=self.model_name,
                contents=self._history,
                config=config
            )
        except errors.APIError as e:
            if e.code == 503:
                return AssistantResponse(success=False, intent="error", message="I'm having trouble connecting to Google's servers right now.", error="AI_PROVIDER_UNAVAILABLE")
            raise

        actions_taken = []
        if response.function_calls:
            self._history.append(response.candidates[0].content)
            tool_responses = []
            errors_list = []
            for function_call in response.function_calls:
                tool_name = function_call.name
                args = function_call.args
                kwargs = args if isinstance(args, dict) else (dict(args) if hasattr(args, "items") else {})
                res = tools.registry.execute(tool_name, kwargs)
                if not res.get("success"):
                    errors_list.append(res.get("message"))
                actions_taken.append(res)
                tool_responses.append(
                    types.Part.from_function_response(name=tool_name, response=res)
                )
            if errors_list:
                raise RuntimeError(" ".join(str(e) for e in errors_list))
            self._history.append(types.Content(role="user", parts=tool_responses))
            config.response_mime_type = "application/json"
            config.response_schema = AssistantResponse
            final_response = self._execute_with_retry(
                self.client.models.generate_content,
                model=self.model_name,
                contents=self._history,
                config=config
            )
            self._history.append(final_response.candidates[0].content)
            result_text = final_response.text
        else:
            self._history.append(response.candidates[0].content)
            result_text = response.text

        if len(self._history) > self.max_history * 2:
            self._history = self._history[-self.max_history * 2:]

        try:
            cleaned_json = result_text.strip()
            if cleaned_json.startswith("```json"):
                cleaned_json = cleaned_json[7:]
            if cleaned_json.startswith("```"):
                cleaned_json = cleaned_json[3:]
            if cleaned_json.endswith("```"):
                cleaned_json = cleaned_json[:-3]
            parsed = AssistantResponse.model_validate_json(cleaned_json)
            parsed.actions_taken = actions_taken
            if actions_taken:
                parsed.intent = "tool_action"
            return parsed
        except Exception as e:
            log.warning(f"Failed to parse structured output, using fallback parser: {e}")
            parsed_fallback = response_parser.parse_response(result_text or "")
            code_blocks = [CodeBlock(language=cb["language"], code=cb["code"]) for cb in parsed_fallback["code_blocks"]]
            return AssistantResponse(
                success=True,
                intent="code" if code_blocks else ("tool_action" if actions_taken else "conversation"),
                message=parsed_fallback["explanation"],
                code_blocks=code_blocks,
                actions_taken=actions_taken
            )

    async def stream_command(self, command: str, system_instruction: str) -> AsyncGenerator[str, None]:
        import tools
        import response_parser
        yield json.dumps({"type": "status", "status": "ANALYZING"}) + "\n"
        tool_decl = types.Tool(function_declarations=tools.registry.schemas)
        config = types.GenerateContentConfig(
            tools=[tool_decl],
            system_instruction=system_instruction,
            temperature=0.3
        )
        self._history.append(types.Content(role="user", parts=[types.Part.from_text(text=command)]))
        try:
            response = await asyncio.to_thread(
                self._execute_with_retry,
                self.client.models.generate_content,
                model=self.model_name,
                contents=self._history,
                config=config
            )
        except errors.APIError as e:
            if e.code == 503:
                yield json.dumps({"type": "error", "message": "AI is temporarily unavailable."}) + "\n"
                return
            yield json.dumps({"type": "error", "message": f"AI error: {e}"}) + "\n"
            return

        actions_taken = []
        if response.function_calls:
            yield json.dumps({"type": "status", "status": "EXECUTING TOOLS"}) + "\n"
            self._history.append(response.candidates[0].content)
            tool_responses = []
            errors_list = []
            for function_call in response.function_calls:
                tool_name = function_call.name
                args = function_call.args
                kwargs = args if isinstance(args, dict) else (dict(args) if hasattr(args, "items") else {})
                res = await asyncio.to_thread(tools.registry.execute, tool_name, kwargs)
                if not res.get("success"):
                    errors_list.append(res.get("message"))
                actions_taken.append(res)
                tool_responses.append(types.Part.from_function_response(name=tool_name, response=res))
            if errors_list:
                err_msg = "; ".join(str(e) for e in errors_list)
                yield json.dumps({"type": "done", "response": {
                    "success": False, "intent": "error", "message": err_msg,
                    "spoken_text": err_msg, "code_blocks": [], "actions_taken": actions_taken
                }}) + "\n"
                return
            self._history.append(types.Content(role="user", parts=tool_responses))
            yield json.dumps({"type": "status", "status": "THINKING"}) + "\n"
            try:
                final_response = await asyncio.to_thread(
                    self._execute_with_retry,
                    self.client.models.generate_content,
                    model=self.model_name,
                    contents=self._history,
                    config=config
                )
                full_text = final_response.text or ""
                self._history.append(final_response.candidates[0].content)
            except errors.APIError as e:
                yield json.dumps({"type": "error", "message": str(e)}) + "\n"
                return
            result_msg = full_text.strip() or "; ".join(
                r.get("message", "") for r in actions_taken if r.get("success")
            ) or "Done."
            yield json.dumps({"type": "done", "response": {
                "success": True, "intent": "tool_action", "message": result_msg,
                "spoken_text": result_msg, "code_blocks": [],
                "actions_taken": actions_taken
            }}) + "\n"
        else:
            full_text = response.text or ""
            self._history.append(response.candidates[0].content)
            if full_text:
                yield json.dumps({"type": "chunk", "text": full_text}) + "\n"
            parsed = response_parser.parse_response(full_text)
            code_blocks = [{"language": cb["language"], "code": cb["code"], "label": cb.get("language", "Code")}
                           for cb in parsed["code_blocks"]]
            explanation = parsed["explanation"]
            spoken = response_parser.sanitize_for_tts(explanation) if code_blocks else response_parser.sanitize_for_tts(full_text)
            yield json.dumps({"type": "done", "response": {
                "success": True,
                "intent": "code" if code_blocks else "conversation",
                "message": full_text,
                "spoken_text": spoken or "I've generated the requested code." if code_blocks else spoken,
                "code_blocks": code_blocks,
                "actions_taken": []
            }}) + "\n"

        if len(self._history) > self.max_history * 2:
            self._history = self._history[-self.max_history * 2:]


# Kept for backward compat — now just an alias for ChatProvider
class InteractionsProvider(ChatProvider):
    pass
