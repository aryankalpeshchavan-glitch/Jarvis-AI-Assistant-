import os
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, List, Optional
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from response_types import AssistantResponse, CodeBlock

log = logging.getLogger("jarvis.ai_provider")

class AIProvider(ABC):
    @abstractmethod
    def process_command(self, command: str, system_instruction: str) -> AssistantResponse:
        pass

    @abstractmethod
    def clear_context(self):
        pass

class GenerateContentProvider(AIProvider):
    def __init__(self, client: genai.Client, model_name: str, max_history: int = 10):
        self.client = client
        self.model_name = model_name
        self.max_history = max_history
        self._history: List[types.Content] = []

    def clear_context(self):
        self._history.clear()

    def process_command(self, command: str, system_instruction: str) -> AssistantResponse:
        import tools
        tool_decl = types.Tool(function_declarations=tools.registry.schemas)

        config = types.GenerateContentConfig(
            tools=[tool_decl],
            system_instruction=system_instruction,
            temperature=0.3
        )

        # Append user message
        self._history.append(types.Content(role="user", parts=[types.Part.from_text(text=command)]))

        # First turn
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=self._history,
            config=config
        )

        # Check for function calls
        actions_taken = []
        if response.function_calls:
            self._history.append(response.candidates[0].content)

            tool_responses = []
            errors = []
            for function_call in response.function_calls:
                tool_name = function_call.name
                args = function_call.args
                kwargs = args if isinstance(args, dict) else (dict(args) if hasattr(args, "items") else {})

                res = tools.registry.execute(tool_name, kwargs)
                if not res.get("success"):
                    errors.append(res.get("message"))
                actions_taken.append(res)

                tool_responses.append(
                    types.Part.from_function_response(
                        name=tool_name,
                        response=res
                    )
                )

            if errors:
                raise RuntimeError(" ".join(str(e) for e in errors))

            self._history.append(types.Content(role="user", parts=tool_responses))

            # Final Turn: Ask for structured response
            config.response_mime_type = "application/json"
            config.response_schema = AssistantResponse

            final_response = self.client.models.generate_content(
                model=self.model_name,
                contents=self._history,
                config=config
            )
            self._history.append(final_response.candidates[0].content)
            result_text = final_response.text
        else:
            self._history.append(response.candidates[0].content)
            result_text = response.text

            # If no tools called, we need to ensure the response matches the schema.
            # In a clean implementation, we would just ask for AssistantResponse upfront, but
            # if we didn't get it structured because we didn't specify schema on turn 1, we can
            # parse or do a quick structured turn. Let's optimize: We can specify the schema on Turn 1!
            # Wait, if we specify schema on Turn 1, it might refuse to call tools. Let's see.

        # Maintain history limit
        if len(self._history) > self.max_history * 2:
            self._history = self._history[-self.max_history * 2:]

        # Fallback parser if we didn't enforce schema
        import response_parser
        try:
            # We must strip markdown fences if the model output them for the JSON
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
            log.warning(f"Failed to parse structured output natively, using fallback parser: {e}")
            parsed_fallback = response_parser.parse_response(result_text or "")
            code_blocks = [CodeBlock(language=cb["language"], code=cb["code"]) for cb in parsed_fallback["code_blocks"]]
            return AssistantResponse(
                success=True,
                intent="code" if code_blocks else ("tool_action" if actions_taken else "conversation"),
                message=parsed_fallback["explanation"],
                code_blocks=code_blocks,
                actions_taken=actions_taken
            )

class InteractionsProvider(AIProvider):
    def __init__(self, client: genai.Client, model_name: str):
        self.client = client
        self.model_name = model_name
        self.previous_interaction_id: Optional[str] = None

    def clear_context(self):
        self.previous_interaction_id = None

    def process_command(self, command: str, system_instruction: str) -> AssistantResponse:
        import tools
        tool_decl = types.Tool(function_declarations=tools.registry.schemas)

        # We start by using the Interaction API
        try:
            interaction = self.client.interactions.create(
                model=self.model_name,
                input=command,
                system_instruction=system_instruction,
                tools=[tool_decl],
                previous_interaction_id=self.previous_interaction_id
            )

            actions_taken = []

            # The interactions API in 2.23.0 may return the interaction object, let's extract the response
            # Note: The response handling for Interaction might differ from GenerateContentResponse
            # Due to the complexity and potential instability (Validation errors earlier),
            # we will fall back to GenerateContentProvider if this fails.

            # Let's check if the interaction requested a tool call (this might need to be done on the next turn)
            # Actually, without deep API documentation on how interaction tool calls are handled,
            # we will rely on GenerateContentProvider as the primary, and keep InteractionsProvider as an architectural stub.
            # We will try to read the interaction response.

            result_text = getattr(interaction, "text", "")
            self.previous_interaction_id = getattr(interaction, "interaction_id", None)

            import response_parser
            parsed_fallback = response_parser.parse_response(result_text or "")
            code_blocks = [CodeBlock(language=cb["language"], code=cb["code"]) for cb in parsed_fallback["code_blocks"]]
            return AssistantResponse(
                success=True,
                intent="code" if code_blocks else "conversation",
                message=parsed_fallback["explanation"],
                code_blocks=code_blocks,
                actions_taken=actions_taken
            )
        except Exception as e:
            log.warning(f"Interactions API failed, fallback required: {e}")
            raise
