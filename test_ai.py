import os
import pytest
from unittest.mock import patch, MagicMock

from ai_brain import process_command_with_ai
import tools
import main


def _make_chat_client(send_message_responses):
    """
    Build a mock genai.Client that:
      - client.chats.create(...) returns a mock chat session
      - chat.send_message(...) returns items from send_message_responses in order
    """
    mock_client = MagicMock()
    mock_chat = MagicMock()
    if isinstance(send_message_responses, list):
        mock_chat.send_message.side_effect = send_message_responses
    else:
        mock_chat.send_message.return_value = send_message_responses
    mock_client.chats.create.return_value = mock_chat
    return mock_client


def test_missing_key():
    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY not configured"):
            process_command_with_ai("hello")


def test_conversational_response():
    mock_response = MagicMock()
    mock_response.function_calls = None
    mock_response.text = "I am Jarvis."
    mock_client = _make_chat_client(mock_response)

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client):
        res = process_command_with_ai("Who are you?")
        assert res["success"] is True
        assert res["chat"] is True
        assert "I am Jarvis." in res["message"]


@patch("main.launch_native_app")
def test_automation_tool_invocation(mock_launch):
    mock_launch.return_value = {"method": "AppID", "target": "calculator"}

    # First call: function call response
    mock_response1 = MagicMock()
    mock_call = MagicMock()
    mock_call.name = "open_app"
    mock_call.args = {"name": "calculator"}
    mock_response1.function_calls = [mock_call]

    # Second call: follow-up natural language response
    mock_response2 = MagicMock()
    mock_response2.function_calls = None
    mock_response2.text = "I have opened the calculator for you."

    mock_client = _make_chat_client([mock_response1, mock_response2])

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client):
        res = process_command_with_ai("Open calculator")
        assert res["success"] is True
        assert "open_app" in res["details"]["target"]
        assert res["message"] == "I have opened the calculator for you."
        mock_launch.assert_called_once_with("calculator")


@patch("main.launch_native_app")
@patch("main.open_website")
def test_compound_request(mock_open_website, mock_launch):
    mock_launch.return_value = {"method": "AppID", "target": "calculator"}
    mock_open_website.return_value = {"method": "Website", "target": "https://www.google.com/search?q=fastapi"}

    mock_response1 = MagicMock()
    mock_call1 = MagicMock()
    mock_call1.name = "open_app"
    mock_call1.args = {"name": "calculator"}

    mock_call2 = MagicMock()
    mock_call2.name = "web_search"
    mock_call2.args = {"query": "fastapi"}

    mock_response1.function_calls = [mock_call1, mock_call2]

    mock_response2 = MagicMock()
    mock_response2.function_calls = None
    mock_response2.text = "I've opened the calculator and searched for fastapi."

    mock_client = _make_chat_client([mock_response1, mock_response2])

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client):
        res = process_command_with_ai("Open calculator and search fastapi")
        assert res["success"] is True
        assert "open_app" in res["details"]["target"]
        assert "web_search" in res["details"]["target"]
        assert len(res["details"]["results"]) == 2


@patch("main.resolve_system_command")
def test_destructive_command(mock_sys):
    # resolve_system_command raises RuntimeError for confirmation-required actions.
    # We mock tools.registry.execute so the error surfaces correctly through ChatProvider.
    mock_sys.side_effect = RuntimeError('Say "confirm" within 20 seconds to shut down the computer. Nothing has happened yet.')

    mock_response1 = MagicMock()
    mock_call = MagicMock()
    mock_call.name = "shutdown"   # Actual registered tool name in tools.py
    mock_call.args = {}
    mock_response1.function_calls = [mock_call]

    mock_client = _make_chat_client(mock_response1)

    # Patch registry.execute so 'shutdown' raises the confirm error
    orig_execute = tools.registry.execute
    def _mock_execute(name, kwargs):
        if name == "shutdown":
            raise RuntimeError('Say "confirm" within 20 seconds to shut down the computer. Nothing has happened yet.')
        return orig_execute(name, kwargs)

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client), \
         patch.object(tools.registry, 'execute', side_effect=_mock_execute):
        with pytest.raises(RuntimeError, match='Say "confirm"'):
            process_command_with_ai("Shutdown the computer")


def test_arbitrary_shell_command():
    mock_response = MagicMock()
    mock_call = MagicMock()
    mock_call.name = "execute_shell"   # THIS TOOL DOES NOT EXIST
    mock_call.args = {"command": "rm -rf /"}
    mock_response.function_calls = [mock_call]

    mock_client = _make_chat_client(mock_response)

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client):
        with pytest.raises(RuntimeError, match="Tool 'execute_shell' not found in registry"):
            process_command_with_ai("Delete all files")


def test_api_failure():
    mock_client = MagicMock()
    mock_chat = MagicMock()
    mock_chat.send_message.side_effect = Exception("API error")
    mock_client.chats.create.return_value = mock_chat

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client):
        with pytest.raises(RuntimeError, match="AI Brain failed: API error"):
            process_command_with_ai("hello")
