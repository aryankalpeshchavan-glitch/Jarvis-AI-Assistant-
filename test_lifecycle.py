import os
import sys
import ctypes
import pytest
from unittest.mock import patch, MagicMock

# We must mock pywebview, pystray, and keyboard BEFORE importing companion
# because it runs initialization code at module level (like CreateMutexW).
# Actually, the Mutex code runs at module level, so we have to mock it before import,
# or reload the module.
import importlib

@pytest.fixture
def mock_dependencies():
    with patch("ctypes.windll.kernel32.CreateMutexW") as mock_mutex, \
         patch("ctypes.windll.kernel32.GetLastError") as mock_getlasterror, \
         patch("ctypes.windll.kernel32.ReleaseMutex") as mock_release, \
         patch("pystray.Icon") as mock_icon, \
         patch("webview.create_window") as mock_create_window, \
         patch("webview.start") as mock_start, \
         patch("keyboard.add_hotkey") as mock_add_hotkey, \
         patch("keyboard.unhook_all") as mock_unhook:
        
        mock_getlasterror.return_value = 0 # No error by default
        
        yield {
            "mutex": mock_mutex,
            "get_last_error": mock_getlasterror,
            "release": mock_release,
            "icon": mock_icon,
            "create_window": mock_create_window,
            "start": mock_start,
            "add_hotkey": mock_add_hotkey,
            "unhook": mock_unhook
        }

def test_single_instance_lock(mock_dependencies):
    # If GetLastError returns 0, it means we got the lock.
    mock_dependencies["get_last_error"].return_value = 0
    import companion
    importlib.reload(companion)
    mock_dependencies["mutex"].assert_called_with(None, False, "Jarvis_Companion_Mutex_2.0")

def test_second_instance_exits(mock_dependencies):
    mock_dependencies["get_last_error"].return_value = 183 # ERROR_ALREADY_EXISTS
    with pytest.raises(SystemExit) as exc_info:
        import companion
        importlib.reload(companion)
    assert exc_info.value.code == 0

def test_hotkey_registration(mock_dependencies):
    mock_dependencies["get_last_error"].return_value = 0
    import companion
    importlib.reload(companion)
    
    # We can't easily test the __main__ block without executing it, 
    # but we can test the toggle_window function directly.
    assert hasattr(companion, "toggle_window")

def test_show_hide_state(mock_dependencies):
    mock_dependencies["get_last_error"].return_value = 0
    import companion
    importlib.reload(companion)
    
    mock_window = MagicMock()
    mock_window.hidden = True
    companion.window = mock_window
    
    companion.toggle_window()
    mock_window.show.assert_called_once()
    mock_window.restore.assert_called_once()
    
    mock_window.hidden = False
    companion.toggle_window()
    mock_window.hide.assert_called_once()

def test_tray_construction(mock_dependencies):
    mock_dependencies["get_last_error"].return_value = 0
    import companion
    importlib.reload(companion)
    
    companion.start_tray()
    mock_dependencies["icon"].assert_called_once()
    args, kwargs = mock_dependencies["icon"].call_args
    assert args[0] == "Jarvis"
    assert args[2] == "J.A.R.V.I.S."
    
    menu = args[3]
    # Check menu items exist
    labels = [item.text for item in menu]
    assert "Show Jarvis" in labels
    assert "Hide Jarvis" in labels
    assert "Quit Jarvis" in labels

def test_lifecycle_cleanup(mock_dependencies):
    mock_dependencies["get_last_error"].return_value = 0
    import companion
    importlib.reload(companion)
    
    mock_window = MagicMock()
    companion.window = mock_window
    mock_icon = MagicMock()
    companion.tray_icon = mock_icon
    
    companion.quit_jarvis()
    
    assert companion.is_quitting is True
    mock_icon.stop.assert_called_once()
    mock_window.destroy.assert_called_once()

def test_on_closing_prevents_destroy_unless_quitting(mock_dependencies):
    mock_dependencies["get_last_error"].return_value = 0
    import companion
    importlib.reload(companion)
    
    mock_window = MagicMock()
    companion.window = mock_window
    
    companion.is_quitting = False
    result = companion.on_closing()
    
    assert result is False # Prevents destroy
    mock_window.hide.assert_called_once()
    
    companion.is_quitting = True
    result2 = companion.on_closing()
    assert result2 is True # Allows destroy
