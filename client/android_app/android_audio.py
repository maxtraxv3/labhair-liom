"""Android audio capture/playback via pyjnius (Java AudioRecord/AudioTrack).

Falls back gracefully if pyjnius is not available (i.e. running on desktop).
"""

from __future__ import annotations

import threading
from typing import Optional

try:
    from jnius import autoclass
    _ANDROID = True
except ImportError:
    _ANDROID = False

import numpy as np

SAMPLE_RATE = 16000
CHANNELS = 1
ENCODING = 2  # AudioFormat.ENCODING_PCM_16BIT
CHANNEL_IN = 16  # AudioFormat.CHANNEL_IN_MONO
CHANNEL_OUT = 4  # AudioFormat.CHANNEL_OUT_MONO
AUDIO_SOURCE_MIC = 1  # MediaRecorder.AudioSource.MIC


class AndroidAudio:
    """Microphone capture + speaker playback using Android Java APIs."""

    def __init__(self) -> None:
        self._running = False
        self._record_thread: Optional[threading.Thread] = None
        self._play_thread: Optional[threading.Thread] = None
        self._record_cb = None
        self._play_cb = None
        self._play_lock = threading.Lock()
        self.last_error: Optional[str] = None

    @property
    def available(self) -> bool:
        return _ANDROID

    def start(self, record_cb=None, play_cb=None) -> bool:
        if not _ANDROID:
            print("[android-audio] pyjnius not available — mic disabled")
            return False
        self.last_error = None
        self._running = True
        self._record_cb = record_cb
        self._play_cb = play_cb
        if record_cb:
            self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
            self._record_thread.start()
        if play_cb:
            self._play_thread = threading.Thread(target=self._play_loop, daemon=True)
            self._play_thread.start()
        return True

    def stop(self) -> None:
        self._running = False

    def push_playback(self, pcm_int16: np.ndarray) -> None:
        with self._play_lock:
            if not hasattr(self, '_play_data'):
                self._play_data = bytearray()
            self._play_data.extend(pcm_int16.astype(np.int16).tobytes())

    def _record_loop(self) -> None:
        if not _ANDROID:
            return
        try:
            AudioRecord = autoclass("android.media.AudioRecord")
            min_buf = int(AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL_IN, ENCODING))
            if min_buf <= 0:
                min_buf = SAMPLE_RATE * 2
            buf_size = max(min_buf, SAMPLE_RATE * 2)
            print(f"[android-audio] creating AudioRecord: src={AUDIO_SOURCE_MIC} "
                  f"sr={SAMPLE_RATE} ch={CHANNEL_IN} fmt={ENCODING} buf={buf_size}",
                  flush=True)
            recorder = AudioRecord(
                int(AUDIO_SOURCE_MIC), int(SAMPLE_RATE), int(CHANNEL_IN),
                int(ENCODING), int(buf_size),
            )
            state = recorder.getState()
            if state != 1:
                self.last_error = f"AudioRecord state={state} (not initialized)"
                print(f"[android-audio] {self.last_error}", flush=True)
                return
            recorder.startRecording()
            print("[android-audio] recording started", flush=True)
            chunk_bytes = 2560  # 80ms at 16kHz mono s16
            buf = bytearray(chunk_bytes)
            while self._running:
                n = recorder.read(buf, 0, chunk_bytes)
                if n > 0 and self._record_cb:
                    self._record_cb(np.frombuffer(bytes(buf[:n]), dtype=np.int16))
            recorder.stop()
            recorder.release()
        except Exception as exc:
            self.last_error = str(exc)
            print(f"[android-audio] record error: {exc}", flush=True)

    def _play_loop(self) -> None:
        if not _ANDROID:
            return
        try:
            AudioTrack = autoclass("android.media.AudioTrack")
            min_buf = int(AudioTrack.getMinBufferSize(SAMPLE_RATE, CHANNEL_OUT, ENCODING))
            buf_size = max(min_buf, SAMPLE_RATE * 2)
            track = AudioTrack(
                int(1), int(SAMPLE_RATE), int(CHANNEL_OUT),
                int(ENCODING), int(buf_size), int(1),
            )
            track.play()
            chunk_bytes = 2560  # 80ms at 16kHz mono s16
            silence = bytes(chunk_bytes)
            while self._running:
                data = None
                with self._play_lock:
                    play_data = getattr(self, '_play_data', None)
                    if play_data and len(play_data) >= chunk_bytes:
                        data = bytes(play_data[:chunk_bytes])
                        del self._play_data[:chunk_bytes]
                if data is None:
                    data = silence
                track.write(bytearray(data), 0, chunk_bytes)
            track.stop()
            track.release()
        except Exception as exc:
            self.last_error = str(exc)
            print(f"[android-audio] play error: {exc}", flush=True)
