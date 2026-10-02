import os
import sys
import time
import json
import queue
import logging
import threading
from enum import Enum

log = logging.getLogger("JarvisSTT")

class STTState(Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    ERROR = "ERROR"
    STOPPING = "STOPPING"

class VoskSpeechProvider:
    def __init__(self, model_path: str = None, sample_rate: int = 16000):
        self.state = STTState.IDLE
        
        # Resolve model path
        if not model_path:
            # Default to JarvisP1/models/vosk/vosk-model-small-en-us-0.15
            base_dir = os.path.dirname(os.path.abspath(__file__))
            model_path = os.path.join(base_dir, "models", "vosk", "vosk-model-small-en-us-0.15")
            
        self.model_path = model_path
        self.sample_rate = sample_rate
        
        self._model = None
        self._audio_queue = queue.Queue()
        self._thread = None
        self._stop_event = threading.Event()
        
        # Callbacks
        self.on_state_change = None
        self.on_partial = None
        self.on_final = None
        self.on_error = None
        
        # Ensure vosk/sounddevice is available lazily to avoid crashing on import if missing
        try:
            import sounddevice
            import vosk
            self._has_deps = True
            # Suppress vosk logging
            vosk.SetLogLevel(-1)
        except ImportError:
            self._has_deps = False

    def _set_state(self, new_state: STTState):
        self.state = new_state
        log.info(f"STT State -> {new_state.value}")
        if self.on_state_change:
            try:
                self.on_state_change(new_state.value)
            except Exception as e:
                log.error(f"Error in on_state_change callback: {e}")

    def _trigger_error(self, message: str):
        log.error(f"STT Error: {message}")
        if self.on_error:
            try:
                self.on_error(message)
            except Exception:
                pass
        self._set_state(STTState.IDLE)
        self.stop()

    def load_model_if_needed(self):
        if not self._has_deps:
            raise RuntimeError("Vosk or sounddevice is not installed.")
            
        if self._model is not None:
            return
            
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Vosk speech model not found at {self.model_path}")
            
        import vosk
        log.info(f"Loading Vosk model from {self.model_path}...")
        self._model = vosk.Model(self.model_path)
        log.info("Vosk model loaded.")

    def _audio_callback(self, indata, frames, time_info, status):
        import sounddevice as sd
        if status:
            if status.input_overflow:
                log.warning("Audio input overflow")
            else:
                log.warning(f"Audio callback status: {status}")
        self._audio_queue.put(bytes(indata))

    def _recognition_thread(self):
        try:
            import sounddevice as sd
            import vosk
        except ImportError:
            self._trigger_error("Vosk speech recognition is not installed.")
            return
        
        try:
            self.load_model_if_needed()
        except Exception as e:
            self._trigger_error(str(e))
            return
            
        try:
            # Clear queue
            while not self._audio_queue.empty():
                self._audio_queue.get_nowait()
                
            rec = vosk.KaldiRecognizer(self._model, self.sample_rate)
            
            # Start stream
            with sd.RawInputStream(samplerate=self.sample_rate, 
                                   blocksize=8000, 
                                   dtype='int16', 
                                   channels=1, 
                                   callback=self._audio_callback):
                
                self._set_state(STTState.LISTENING)
                
                log.info("--- STT DIAGNOSTICS START ---")
                log.info(f"Provider: Vosk")
                log.info(f"Model: {self.model_path}")
                log.info(f"Microphone Input Sample Rate: {self.sample_rate}")
                log.info(f"Recognizer Sample Rate: {self.sample_rate}")
                start_ts = time.time()
                log.info(f"Start timestamp: {start_ts}")
                first_partial_ts = None

                while not self._stop_event.is_set():
                    try:
                        # Use timeout so we can check stop_event
                        data = self._audio_queue.get(timeout=0.1)
                        if rec.AcceptWaveform(data):
                            res = json.loads(rec.Result())
                            if res.get('text'):
                                text = res['text'].strip()
                                if text:
                                    self._set_state(STTState.PROCESSING)
                                    
                                    final_ts = time.time()
                                    partial_lat = (first_partial_ts - start_ts) if first_partial_ts else 'N/A'
                                    final_lat = final_ts - start_ts
                                    
                                    log.info(f"Final timestamp: {final_ts}")
                                    log.info(f"First partial latency: {partial_lat}")
                                    log.info(f"Final latency: {final_lat}")
                                    log.info(f"Final transcript: '{text}'")
                                    log.info("--- STT DIAGNOSTICS END ---")

                                    if self.on_final:
                                        self.on_final(text)
                                    # After final result, we stop listening
                                    break
                        else:
                            partial = json.loads(rec.PartialResult())
                            if partial.get('partial'):
                                p_text = partial['partial'].strip()
                                if p_text:
                                    if first_partial_ts is None:
                                        first_partial_ts = time.time()
                                        log.info(f"First partial timestamp: {first_partial_ts}")
                                    log.info(f"Partial transcript: '{p_text}'")
                                    if self.on_partial:
                                        self.on_partial(p_text)
                    except queue.Empty:
                        continue
                        
        except Exception as e:
            self._trigger_error(f"Recognition stream error: {e}")
        finally:
            self._audio_queue.queue.clear()
            if self.state not in [STTState.IDLE, STTState.ERROR, STTState.PROCESSING]:
                self._set_state(STTState.IDLE)
            self._stop_event.clear()
            self._thread = None

    def start(self):
        if self.state not in [STTState.IDLE, STTState.ERROR, STTState.PROCESSING]:
            log.warning(f"Cannot start STT, current state is {self.state}")
            return
            
        self._set_state(STTState.STARTING)
        self._stop_event.clear()
        
        self._thread = threading.Thread(target=self._recognition_thread, daemon=True)
        self._thread.start()

    def stop(self):
        if self.state == STTState.IDLE or self.state == STTState.ERROR:
            return
            
        if self.state == STTState.STARTING or self.state == STTState.LISTENING:
            self._set_state(STTState.STOPPING)
            
        self._stop_event.set()

    def shutdown(self):
        """Release all resources completely."""
        self.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._model = None
        self._set_state(STTState.IDLE)
