import os
import pytest
from unittest.mock import patch, MagicMock

from ai_brain import process_command_with_ai

def mock_fallback(cmd: str):
    if "shutdown" in cmd.lower():
        raise RuntimeError('Say "confirm" within 15 seconds to Shutdown. Nothing has happened yet.')
    if "shell" in cmd.lower():
        raise RuntimeError("I couldn't find “shell” on this PC")
    if "calc" in cmd.lower():
        return {"method": "AppID", "target": "calculator"}
    if "chrome" in cmd.lower():
        return {"method": "AppID", "target": "chrome"}
    raise RuntimeError(f"Unknown fallback command: {cmd}")

def test_missing_key():
    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY not configured"):
            process_command_with_ai("hello", mock_fallback)

def test_conversational_response():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.function_calls = None
    mock_response.text = "I am Jarvis."
    mock_client.models.generate_content.return_value = mock_response

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client):
        res = process_command_with_ai("Who are you?", mock_fallback)
        assert res["success"] is True
        assert res["chat"] is True
        assert "I am Jarvis." in res["message"]

def test_automation_tool_invocation():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Opening calculator."
    
    mock_call = MagicMock()
    mock_call.name = "execute_automation_command"
    mock_call.args = {"commands": ["open calc"]}
    mock_response.function_calls = [mock_call]
    mock_client.models.generate_content.return_value = mock_response

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client):
        res = process_command_with_ai("Open calculator", mock_fallback)
        assert res["success"] is True
        assert "calculator" in res["details"]["target"]

def test_compound_request():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Opening calculator and chrome."
    
    mock_call = MagicMock()
    mock_call.name = "execute_automation_command"
    mock_call.args = {"commands": ["open calc", "open chrome"]}
    mock_response.function_calls = [mock_call]
    mock_client.models.generate_content.return_value = mock_response

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client):
        res = process_command_with_ai("Open calculator and chrome", mock_fallback)
        assert res["success"] is True
        assert "calculator" in res["details"]["target"]
        assert "chrome" in res["details"]["target"]

def test_destructive_command():
    mock_client = MagicMock()
    mock_response = MagicMock()
    
    mock_call = MagicMock()
    mock_call.name = "execute_automation_command"
    mock_call.args = {"commands": ["shutdown"]}
    mock_response.function_calls = [mock_call]
    mock_client.models.generate_content.return_value = mock_response

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client):
        with pytest.raises(RuntimeError, match="Say \"confirm\""):
            process_command_with_ai("Shutdown the computer", mock_fallback)

def test_arbitrary_shell_command():
    mock_client = MagicMock()
    mock_response = MagicMock()
    
    mock_call = MagicMock()
    mock_call.name = "execute_automation_command"
    mock_call.args = {"commands": ["shell script rm -rf"]}
    mock_response.function_calls = [mock_call]
    mock_client.models.generate_content.return_value = mock_response

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client):
        with pytest.raises(RuntimeError, match="couldn't find “shell”"):
            process_command_with_ai("Delete all files", mock_fallback)

def test_api_failure():
    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client') as MockClient:
        MockClient.return_value.models.generate_content.side_effect = Exception("API error")
        with pytest.raises(RuntimeError, match="AI Brain failed: API error"):
            process_command_with_ai("hello", mock_fallback)
