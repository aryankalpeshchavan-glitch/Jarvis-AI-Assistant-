import pytest
from unittest.mock import patch, MagicMock, ANY
import queue
import time
from stt_provider import VoskSpeechProvider, STTState

@pytest.fixture
def mock_deps():
    with patch('stt_provider.os.path.exists', return_value=True):
        with patch.dict('sys.modules', {'sounddevice': MagicMock(), 'vosk': MagicMock()}):
            yield

def test_model_initialization(mock_deps):
    provider = VoskSpeechProvider()
    assert provider.state == STTState.IDLE
    provider.load_model_if_needed()
    assert provider._model is not None

def test_missing_model_path(mock_deps):
    with patch('stt_provider.os.path.exists', return_value=False):
        provider = VoskSpeechProvider("invalid/path")
        with pytest.raises(FileNotFoundError):
            provider.load_model_if_needed()

def test_microphone_unavailable(mock_deps):
    provider = VoskSpeechProvider()
    with patch('stt_provider.threading.Thread') as mock_thread:
        # Mock recognition thread directly raising error
        def run_thread(*args, **kwargs):
            provider._trigger_error("Microphone unavailable")
        mock_thread.return_value.start.side_effect = run_thread
        
        provider.start()
        # Sleep slightly if thread logic was async, but here we just mocked start
        assert provider.state == STTState.IDLE

@patch('stt_provider.os.path.exists', return_value=True)
def test_start_and_stop(mock_exists):
    with patch.dict('sys.modules', {'sounddevice': MagicMock(), 'vosk': MagicMock()}):
        provider = VoskSpeechProvider()
        # We don't want to actually run the thread logic entirely, 
        # so we'll mock the thread start and just manually set state to simulate.
        with patch('stt_provider.threading.Thread'):
            provider.start()
            assert provider.state == STTState.STARTING
            
            # Simulate transition
            provider._set_state(STTState.LISTENING)
            assert provider.state == STTState.LISTENING
            
            provider.stop()
            assert provider.state == STTState.STOPPING
            assert provider._stop_event.is_set()

def test_duplicate_start_protection(mock_deps):
    provider = VoskSpeechProvider()
    with patch('stt_provider.threading.Thread') as mock_thread:
        provider.start()
        assert provider.state == STTState.STARTING
        
        provider.start() # Should not spawn again
        mock_thread.assert_called_once()

def test_shutdown(mock_deps):
    provider = VoskSpeechProvider()
    with patch('stt_provider.threading.Thread'):
        provider.start()
        
        provider.shutdown()
        assert provider.state == STTState.IDLE
        assert provider._model is None

def test_state_transitions(mock_deps):
    provider = VoskSpeechProvider()
    states = []
    def on_state(s):
        states.append(s)
    provider.on_state_change = on_state
    
    provider._set_state(STTState.STARTING)
    provider._set_state(STTState.LISTENING)
    provider._set_state(STTState.PROCESSING)
    provider._set_state(STTState.IDLE)
    
    assert states == ["STARTING", "LISTENING", "PROCESSING", "IDLE"]

# Further logic tests testing the _recognition_thread method directly
@patch('stt_provider.os.path.exists', return_value=True)
def test_recognition_thread_flow(mock_exists):
    with patch.dict('sys.modules', {'sounddevice': MagicMock(), 'vosk': MagicMock()}):
        import vosk
        import sounddevice as sd
        
        mock_model = MagicMock()
        vosk.Model.return_value = mock_model
        
        mock_rec = MagicMock()
        vosk.KaldiRecognizer.return_value = mock_rec
        
        provider = VoskSpeechProvider()
        
        partials = []
        finals = []
        provider.on_partial = lambda t: partials.append(t)
        provider.on_final = lambda t: finals.append(t)
        
        # We will manually put some data and then set stop event
        with patch.object(provider._audio_queue, 'empty', side_effect=[True, False]):
            with patch.object(provider._stop_event, 'is_set', side_effect=[False, False, True]):
                provider._audio_queue.put(b"audio_data")
                provider._audio_queue.put(b"audio_data2")
                
                # Mock AcceptWaveform to return False (Partial) then True (Final)
                mock_rec.AcceptWaveform.side_effect = [False, True]
                import json
                mock_rec.PartialResult.return_value = json.dumps({"partial": "hello"})
                mock_rec.Result.return_value = json.dumps({"text": "hello jarvis"})
                
                # Run thread synchronously for testing
                provider._recognition_thread()
        
        assert "hello" in partials
        assert "hello jarvis" in finals
        assert provider.state == STTState.PROCESSING

@patch('stt_provider.os.path.exists', return_value=True)
def test_malformed_recognizer_output(mock_exists):
    with patch.dict('sys.modules', {'sounddevice': MagicMock(), 'vosk': MagicMock()}):
        import vosk
        
        mock_rec = MagicMock()
        vosk.KaldiRecognizer.return_value = mock_rec
        
        provider = VoskSpeechProvider()
        
        provider._stop_event.set()
        
        with patch.object(provider._audio_queue, 'empty', return_value=True):
            with patch.object(provider._stop_event, 'is_set', side_effect=[False, True]):
                provider._audio_queue.put(b"audio_data")
                mock_rec.AcceptWaveform.return_value = True
                mock_rec.Result.return_value = "invalid json"
                
                provider._recognition_thread()
        
        # Should catch JSONDecodeError and trigger ERROR
        assert provider.state == STTState.IDLE
