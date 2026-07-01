"""
Captura y reproducción de audio con códec Opus (RNF-03d), bajo QObject
(no QThread: PortAudio/sounddevice ya gestiona sus propios hilos nativos
para el callback de audio en tiempo real).

Si `opuslib` o la librería nativa `libopus` no están disponibles, la
llamada continúa solo con video (degradación elegante) y se informa el
motivo por señal `audio_error` en vez de tumbar la aplicación.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .. import config

try:
    import opuslib
    import sounddevice as sd
    _AUDIO_AVAILABLE = True
except Exception:  # pragma: no cover - depende del entorno del usuario
    opuslib = None
    sd = None
    _AUDIO_AVAILABLE = False


def audio_available() -> bool:
    return _AUDIO_AVAILABLE


class AudioCaptureWorker(QObject):
    frame_encoded = Signal(bytes)   # paquete Opus listo para cifrar + enviar
    audio_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stream = None
        self._encoder = None
        self._mic_enabled = True   # RF-02b
        self._frame_samples = int(config.AUDIO_SAMPLE_RATE * config.AUDIO_FRAME_MS / 1000)

    def set_mic_enabled(self, enabled: bool) -> None:
        self._mic_enabled = enabled

    def start(self) -> None:
        if not _AUDIO_AVAILABLE:
            self.audio_error.emit("Audio no disponible (falta opuslib/libopus o sounddevice). Continuando solo con video.")
            return
        try:
            self._encoder = opuslib.Encoder(
                config.AUDIO_SAMPLE_RATE, config.AUDIO_CHANNELS, opuslib.APPLICATION_VOIP
            )
            self._encoder.bitrate = config.AUDIO_BITRATE
        except Exception as exc:
            self.audio_error.emit(f"No se pudo inicializar el codificador Opus: {exc}")
            return
        try:
            self._stream = sd.RawInputStream(
                samplerate=config.AUDIO_SAMPLE_RATE,
                channels=config.AUDIO_CHANNELS,
                dtype="int16",
                blocksize=self._frame_samples,
                callback=self._on_audio_block,
            )
            self._stream.start()
        except Exception as exc:
            self.audio_error.emit(f"No se pudo abrir el micrófono: {exc}")
            self._stream = None

    def _on_audio_block(self, indata, frames, time_info, status) -> None:
        if not self._mic_enabled or self._encoder is None:
            return
        try:
            packet = self._encoder.encode(bytes(indata), self._frame_samples)
            self.frame_encoded.emit(packet)
        except Exception:
            pass  # nunca reventar el callback de audio en tiempo real

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._encoder = None


class AudioPlaybackWorker(QObject):
    audio_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stream = None
        self._decoder = None
        self._frame_samples = int(config.AUDIO_SAMPLE_RATE * config.AUDIO_FRAME_MS / 1000)

    def start(self) -> None:
        if not _AUDIO_AVAILABLE:
            return
        try:
            self._decoder = opuslib.Decoder(config.AUDIO_SAMPLE_RATE, config.AUDIO_CHANNELS)
            self._stream = sd.RawOutputStream(
                samplerate=config.AUDIO_SAMPLE_RATE,
                channels=config.AUDIO_CHANNELS,
                dtype="int16",
                blocksize=self._frame_samples,
            )
            self._stream.start()
        except Exception as exc:
            self.audio_error.emit(f"No se pudo abrir la salida de audio: {exc}")
            self._stream = None

    def push_packet(self, opus_bytes: bytes) -> None:
        if self._decoder is None or self._stream is None:
            return
        try:
            pcm = self._decoder.decode(opus_bytes, self._frame_samples)
            self._stream.write(pcm)
        except Exception:
            pass

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._decoder = None
