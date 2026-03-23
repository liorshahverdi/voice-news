"""Kokoro TTS synthesis → WAV file."""

import os
import numpy as np
import soundfile as sf
from pathlib import Path
from datetime import datetime

# Allow MPS fallback for Apple Silicon
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def synthesize(script: str, output_dir: str, voice: str = "am_michael") -> Path:
    """Synthesize script to WAV using Kokoro. Returns output file path."""
    from kokoro import KPipeline  # imported here to keep startup fast on --dry-run

    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    wav_path = output_path / f"digest_{timestamp}.wav"

    print(f"[tts] Initializing Kokoro pipeline (voice={voice})...")
    lang_code = "b" if voice.startswith("b") else "a"
    pipeline = KPipeline(lang_code=lang_code)

    print("[tts] Synthesizing speech...")
    chunks = []
    sample_rate = None

    for result in pipeline(script, voice=voice):
        audio = result.audio
        if audio is not None and len(audio) > 0:
            arr = np.array(audio)
            if arr.ndim > 1:
                arr = arr.squeeze()
            chunks.append(arr)
            if sample_rate is None:
                sample_rate = getattr(result, "sample_rate", 24000)

    if not chunks:
        raise RuntimeError("TTS produced no audio output")

    combined = np.concatenate(chunks)
    sr = sample_rate or 24000

    sf.write(str(wav_path), combined, sr)
    duration = len(combined) / sr
    print(f"[tts] Wrote {duration:.1f}s of audio → {wav_path}")

    return wav_path
