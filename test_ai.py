import os
import pytest
from unittest.mock import patch, MagicMock

from ai_brain import process_command_with_ai
import tools
import main

def test_missing_key():
    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY not configured"):
            process_command_with_ai("hello")

def test_conversational_response():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.function_calls = None
    mock_response.text = "I am Jarvis."
    mock_client.models.generate_content.return_value = mock_response

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client):
        res = process_command_with_ai("Who are you?")
        assert res["success"] is True
        assert res["chat"] is True
        assert "I am Jarvis." in res["message"]

@patch("main.launch_native_app")
def test_automation_tool_invocation(mock_launch):
    mock_launch.return_value = {"method": "AppID", "target": "calculator"}
    
    mock_client = MagicMock()
    
    # First response: returns function call
    mock_response1 = MagicMock()
    mock_call = MagicMock()
    mock_call.name = "open_app"
    mock_call.args = {"name": "calculator"}
    mock_response1.function_calls = [mock_call]
    
    # Second response: returns natural language summary
    mock_response2 = MagicMock()
    mock_response2.function_calls = None
    mock_response2.text = "I have opened the calculator for you."
    
    mock_client.models.generate_content.side_effect = [mock_response1, mock_response2]

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

    mock_client = MagicMock()
    
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
    
    mock_client.models.generate_content.side_effect = [mock_response1, mock_response2]

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client):
        res = process_command_with_ai("Open calculator and search fastapi")
        assert res["success"] is True
        assert "open_app" in res["details"]["target"]
        assert "web_search" in res["details"]["target"]
        assert len(res["details"]["results"]) == 2

@patch("main.resolve_system_command")
def test_destructive_command(mock_sys):
    # Setup mock to raise the confirmation error just like the real engine
    mock_sys.side_effect = RuntimeError('Say "confirm" within 20 seconds to shut down the computer. Nothing has happened yet.')
    
    mock_client = MagicMock()
    
    mock_response1 = MagicMock()
    mock_call = MagicMock()
    mock_call.name = "shutdown"
    mock_call.args = {}
    mock_response1.function_calls = [mock_call]
    mock_client.models.generate_content.return_value = mock_response1

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client):
        with pytest.raises(RuntimeError, match="Say \"confirm\""):
            process_command_with_ai("Shutdown the computer")

def test_arbitrary_shell_command():
    mock_client = MagicMock()
    mock_response = MagicMock()
    
    mock_call = MagicMock()
    mock_call.name = "execute_shell" # THIS TOOL DOES NOT EXIST
    mock_call.args = {"command": "rm -rf /"}
    mock_response.function_calls = [mock_call]
    mock_client.models.generate_content.return_value = mock_response

    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client', return_value=mock_client):
        with pytest.raises(RuntimeError, match="Tool 'execute_shell' not found in registry"):
            process_command_with_ai("Delete all files")

def test_api_failure():
    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_key"}), \
         patch('ai_brain.genai.Client') as MockClient:
        MockClient.return_value.models.generate_content.side_effect = Exception("API error")
        with pytest.raises(RuntimeError, match="AI Brain failed: API error"):
            process_command_with_ai("hello")
