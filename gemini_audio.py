#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gemini_audio.py — Google Gemini 3.8 Nöral TTS + Ücretsiz Edge Neural Yedek
---------------------------------------------------------------------------
Birincil motor: Gemini 3.8 Flash TTS (`v1beta/interactions`, Api-Revision
2026-05-20). Tüm hesaplar `api_waterfall` şelalesinden sırayla denenir; 403
sızdırılmış ve 429 kota anahtarları anında atlanır.

Yedek motor: Gemini anahtarı yoksa veya tüm anahtarlar tükendiyse Microsoft
Edge Neural Türkçe sesleri (edge-tts) devreye girer. Böylece Render Free
Tier'da bile gerçek insan sesi üretilir; sahte beep/sine sesi ASLA üretilmez.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from api_waterfall import WaterfallProviderError, execute_key_waterfall

logger = logging.getLogger("YusasufhinCockpit.GeminiAudio")

BASE_DIR = Path(__file__).resolve().parent

# Gemini 3.8 TTS REST uç noktası (2.5 *-preview-tts 2026-11-17'de kapandı).
INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
API_REVISION = "2026-05-20"
GEMINI_TTS_MODELS = ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts")
REQUEST_TIMEOUT = (8, 45)

# Gemini Ses Profilleri
GEMINI_VOICES = {
    "Aoede": "Aoede (Sıcak, Etkileyici Kadın — Astroloji ve Hikaye Anlatımı)",
    "Puck": "Puck (Dinamik, Enerjik Erkek — Teknoloji ve Viral Shorts)",
    "Charon": "Charon (Derin, Otoriter Erkek — Belgesel ve Tarih)",
    "Kore": "Kore (Net, Sakin Kadın — Haber ve Eğitici İçerik)",
    "Fenrir": "Fenrir (Güçlü, Dramatik Erkek — Sinematik ve Fragman)",
}

# Gemini ses profilini gerçek Türkçe Microsoft Neural sesine eşler.
EDGE_VOICE_MAP = {
    "Aoede": "tr-TR-EmelNeural",
    "Kore": "tr-TR-EmelNeural",
    "Puck": "tr-TR-AhmetNeural",
    "Charon": "tr-TR-AhmetNeural",
    "Fenrir": "tr-TR-AhmetNeural",
}

# Son TTS çağrısının sonucu (çağıranlar `last_tts_diagnostics()` ile okur).
_DIAG_LOCK = threading.Lock()
_LAST_DIAGNOSTICS: Dict[str, Any] = {
    "ok": False,
    "engine": "none",
    "reason": "henüz çalıştırılmadı",
    "key_label": "",
}


def last_tts_diagnostics() -> Dict[str, Any]:
    """Son TTS denemesinin güvenli özetini döner (ham API anahtarı içermez)."""
    with _DIAG_LOCK:
        return dict(_LAST_DIAGNOSTICS)


def _set_diagnostics(ok: bool, engine: str, reason: str, key_label: str = "") -> None:
    with _DIAG_LOCK:
        _LAST_DIAGNOSTICS.clear()
        _LAST_DIAGNOSTICS.update({
            "ok": bool(ok),
            "engine": str(engine),
            "reason": str(reason),
            "key_label": str(key_label),
        })


def collect_gemini_keys() -> List[str]:
    """Sistem ortamından, panel kasasından ve Persona/.env adaylarından tüm Gemini API anahtarlarını şelale sırasında toplar."""
    keys: List[str] = []
    try:
        from api_waterfall import collect_provider_keys

        panel_entries = collect_provider_keys("GEMINI_API_KEY", data_dir=BASE_DIR / "data")
        for _, k in panel_entries:
            if k and k not in keys:
                keys.append(k)
    except Exception as exc:  # panel kasası opsiyonel; ortam anahtarlarıyla devam et
        logger.debug("[GeminiAudio] Panel anahtar kasası okunamadı: %s", exc)

    # 1. Ortam değişkenleri (sayısal sıra: GEMINI_API_KEY, _1.._25)
    env_ordered = ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY_{i}" for i in range(1, 26)]
    for k in env_ordered:
        v = os.environ.get(k)
        if v and v.strip():
            cv = v.strip().strip('"\'')
            if cv and cv not in keys:
                keys.append(cv)
    for k, v in sorted(os.environ.items()):
        if "GEMINI_API_KEY" in k.upper() and v and v.strip():
            cv = v.strip().strip('"\'')
            if cv and cv not in keys:
                keys.append(cv)

    # 2. .env adayları
    candidates = [
        BASE_DIR / ".env",
        Path.home() / "Desktop" / "PYTHON PROJECTS" / "Fabrika" / "Persona" / ".env",
        Path.home() / "Desktop" / "PYTHON PROJECTS" / "Fabrika" / ".env",
    ]
    for c in candidates:
        if c.exists():
            try:
                for line in c.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k_name, k_val = line.split("=", 1)
                    if "GEMINI_API_KEY" in k_name.upper():
                        val = k_val.strip().strip('"\'')
                        if val and val not in keys:
                            keys.append(val)
            except Exception as exc:  # okunamayan .env adayı diğerlerini engellemesin
                logger.debug("[GeminiAudio] .env adayı okunamadı (%s): %s", c, exc)

    return keys


def get_channel_gemini_voice(channel: str) -> str:
    """YouTube kanal profiline göre en uygun Gemini sesini seçer."""
    c_lower = (channel or "").lower()
    if "astroloji" in c_lower or "kova" in c_lower:
        return "Aoede"
    elif "belgesel" in c_lower or "tarih" in c_lower:
        return "Charon"
    elif "shorts" in c_lower or "viral" in c_lower:
        return "Puck"
    elif "tech" in c_lower or "ai" in c_lower:
        return "Puck"
    return "Aoede"


def _find_ffmpeg() -> Optional[str]:
    """PATH, Homebrew veya imageio-ffmpeg üzerinden ffmpeg ikilisini bulur."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin and os.path.isfile("/opt/homebrew/bin/ffmpeg"):
        ffmpeg_bin = "/opt/homebrew/bin/ffmpeg"
    if not ffmpeg_bin:
        try:
            import imageio_ffmpeg

            ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:
            logger.debug("[GeminiAudio] imageio-ffmpeg bulunamadı: %s", exc)
    return ffmpeg_bin or None


def _wav_duration_from_bytes(raw: bytes) -> float:
    try:
        with wave.open(io.BytesIO(raw), "rb") as wf:
            rate = wf.getframerate()
            frames = wf.getnframes()
            return round(frames / float(rate), 2) if rate else 0.0
    except Exception:
        return 0.0


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wf:
            rate = wf.getframerate()
            frames = wf.getnframes()
            return round(frames / float(rate), 2) if rate else 0.0
    except Exception:
        return 0.0


def _media_duration(path: Path) -> float:
    """WAV dışındaki MP3 için ffprobe varsa süreyi okur; yoksa 0.0 döner."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        res = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode == 0 and res.stdout.strip():
            return round(float(res.stdout.strip()), 2)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logger.debug("[GeminiAudio] ffprobe süre okuması başarısız: %s", exc)
    return 0.0


def _write_wav_from_pcm(raw_pcm: bytes, target: Path) -> None:
    """24 kHz / mono / 16-bit little-endian PCM'i stdlib wave ile WAV'a sarar."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(raw_pcm)


def _convert_with_ffmpeg(input_args: List[str], source: Path, target: Path) -> bool:
    ffmpeg_bin = _find_ffmpeg()
    if not ffmpeg_bin:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_bin, "-y", *input_args, "-i", str(source), "-c:a", "libmp3lame", "-b:a", "192k", str(target)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("[GeminiAudio] FFmpeg dönüşümü çalıştırılamadı: %s", exc)
        return False
    if res.returncode != 0 or not target.is_file() or target.stat().st_size <= 500:
        logger.warning("[GeminiAudio] FFmpeg dönüşümü başarısız: %s", (res.stderr or "")[-200:])
        return False
    return True


def _pcm_to_mp3(raw_pcm: bytes, target: Path) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as tmp:
        tmp.write(raw_pcm)
        tmp_path = Path(tmp.name)
    try:
        return _convert_with_ffmpeg(
            ["-f", "s16le", "-ar", "24000", "-ac", "1"], tmp_path, target
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def _wav_bytes_to_mp3(raw_wav: bytes, target: Path) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(raw_wav)
        tmp_path = Path(tmp.name)
    try:
        return _convert_with_ffmpeg([], tmp_path, target)
    finally:
        tmp_path.unlink(missing_ok=True)


def _finalize_audio(raw_audio: bytes, target_out: Path, output_format: str) -> Tuple[Optional[Path], float]:
    """Gemini çıktısını (tam WAV veya çıplak PCM) hedef formata yazar."""
    if not raw_audio:
        return None, 0.0

    target_out = Path(target_out)
    target_out.parent.mkdir(parents=True, exist_ok=True)

    if raw_audio[:4] == b"RIFF":
        # Gemini 3.8 unary yanıtı tam WAV olarak gelir.
        duration = _wav_duration_from_bytes(raw_audio)
        if output_format == "mp3":
            mp3_target = target_out if target_out.suffix.lower() == ".mp3" else target_out.with_suffix(".mp3")
            if _wav_bytes_to_mp3(raw_audio, mp3_target):
                return mp3_target, duration or _media_duration(mp3_target)
            # ffmpeg yoksa WAV olarak yaz; sahte ses üretmektense gerçek WAV döner.
            wav_target = target_out if target_out.suffix.lower() == ".wav" else target_out.with_suffix(".wav")
            wav_target.write_bytes(raw_audio)
            return wav_target, duration
        wav_target = target_out if target_out.suffix.lower() == ".wav" else target_out.with_suffix(".wav")
        wav_target.write_bytes(raw_audio)
        return wav_target, duration

    # 24 kHz s16le PCM: stdlib wave ile ffmpeg'siz WAV üretilebilir.
    duration = round(len(raw_audio) / (24000 * 2), 2)
    if output_format == "mp3":
        mp3_target = target_out if target_out.suffix.lower() == ".mp3" else target_out.with_suffix(".mp3")
        if _pcm_to_mp3(raw_audio, mp3_target):
            return mp3_target, duration
    wav_target = target_out if target_out.suffix.lower() == ".wav" else target_out.with_suffix(".wav")
    _write_wav_from_pcm(raw_audio, wav_target)
    return wav_target, duration


def _strip_data_uri(value: str) -> str:
    text = value.strip()
    if text.startswith("data:") and "," in text:
        return text.split(",", 1)[1].strip()
    return text


def _extract_audio_base64(data: Dict[str, Any]) -> Optional[str]:
    """Gemini interactions yanıtındaki model_output/audio bloğunu bulur."""
    steps = data.get("steps") or []
    if isinstance(steps, dict):
        steps = [steps]
    if not isinstance(steps, list):
        return None

    for step in steps:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        content = step.get("content") or []
        if isinstance(content, dict):
            content = [content]
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "audio":
                    continue
                b64 = block.get("data") or block.get("audio")
                if isinstance(b64, str) and b64.strip():
                    return _strip_data_uri(b64)

    # Eski biçimle karşılaşılırsa (inlineData) geriye dönük uyumluluk.
    for candidate in data.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        parts = (candidate.get("content") or {}).get("parts") or []
        for part in parts:
            inline = part.get("inlineData") or part.get("inline_data") or {}
            b64 = inline.get("data")
            if isinstance(b64, str) and b64.strip():
                return _strip_data_uri(b64)
    return None


def _request_gemini_tts(
    api_key: str,
    model_name: str,
    clean_text: str,
    selected_voice: str,
) -> bytes:
    """Tek anahtar + tek model için Gemini 3.8 interactions çağrısı yapar."""
    payload = {
        "model": model_name,
        "input": [
            {
                "type": "user_input",
                "content": [{"type": "text", "text": clean_text}],
            }
        ],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": selected_voice}]},
    }
    headers = {
        "x-goog-api-key": api_key,
        "Api-Revision": API_REVISION,
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(
            INTERACTIONS_URL,
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.Timeout as exc:
        raise WaterfallProviderError(504, f"{model_name} zaman aşımı") from exc
    except requests.RequestException as exc:
        raise WaterfallProviderError(502, f"{model_name} ağ hatası: {exc}") from exc

    if resp.status_code != 200:
        message = (resp.text or "").strip()[:200]
        if resp.status_code == 404:
            raise WaterfallProviderError(404, f"{model_name} bulunamadı")
        raise WaterfallProviderError(
            resp.status_code,
            f"{model_name} HTTP {resp.status_code}: {message}",
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise WaterfallProviderError(502, f"{model_name} geçersiz JSON yanıtı") from exc

    b64 = _extract_audio_base64(data if isinstance(data, dict) else {})
    if not b64:
        raise WaterfallProviderError(502, f"{model_name} yanıtında ses bloğu yok")
    try:
        raw_audio = base64.b64decode(b64, validate=False)
    except (ValueError, TypeError) as exc:
        raise WaterfallProviderError(502, f"{model_name} base64 ses çözülemedi") from exc
    if not raw_audio:
        raise WaterfallProviderError(502, f"{model_name} boş ses verisi döndürdü")
    return raw_audio


def _build_env_getter(all_keys: List[str]):
    """api_waterfall'un env katmanına panel + .env dahil tüm anahtarları verir."""
    joined = ",".join(all_keys)

    def _getter(name: str) -> Optional[str]:
        if name == "GEMINI_API_KEY":
            return joined or None
        return None

    return _getter


def _synthesize_with_waterfall(
    clean_text: str,
    selected_voice: str,
    keys: List[str],
) -> Tuple[bytes, str, str]:
    """Tüm anahtarları api_waterfall üzerinden dener; (ses, model, etiket) döner."""
    def _call(api_key: str) -> Tuple[bytes, str]:
        last_404: Optional[WaterfallProviderError] = None
        for model_name in GEMINI_TTS_MODELS:
            try:
                raw_audio = _request_gemini_tts(api_key, model_name, clean_text, selected_voice)
            except WaterfallProviderError as exc:
                if exc.status_code == 404:
                    # Model yoksa aynı anahtarla hemen bir sonraki modele geç.
                    last_404 = exc
                    continue
                raise
            return raw_audio, model_name
        raise last_404 or WaterfallProviderError(
            404, "Gemini 3.8 TTS modeli bulunamadı"
        )

    (raw_audio, model_name), key_label, _trace = execute_key_waterfall(
        "GEMINI_API_KEY",
        _call,
        data_dir=BASE_DIR / "data",
        base_get_env=_build_env_getter(keys),
        retry_cooldown_if_all_blocked=False,
    )
    return raw_audio, model_name, key_label


def _edge_tts_allowed() -> bool:
    """pytest içinde edge-tts'i yalnızca açıkça izin/mock varsa çalıştır."""
    if os.environ.get("GEMINI_AUDIO_ALLOW_EDGE_TTS_IN_TESTS") == "1":
        return True
    if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
        edge_module = sys.modules.get("edge_tts")
        # Testlerde sahte/mock modül açıkça enjekte edildiyse gerçek ağa çıkmaz.
        if edge_module is not None and (
            not isinstance(edge_module, types.ModuleType)
            or not getattr(edge_module, "__file__", None)
        ):
            return True
        return False
    return True


def _edge_tts_save(text: str, voice: str, destination: Path) -> None:
    """edge-tts'i temiz bir asyncio döngüsünde çalıştırır (çalışan loop'u bozmaz)."""
    import asyncio

    import edge_tts

    async def _run() -> None:
        communicate = edge_tts.Communicate(text, voice)
        await asyncio.wait_for(communicate.save(str(destination)), timeout=60.0)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_run())
        return

    # Zaten çalışan bir event loop varsa ayrı iş parçacığında kendi loop'unda çalıştır.
    errors: List[BaseException] = []

    def _worker() -> None:
        try:
            asyncio.run(_run())
        except BaseException as exc:  # noqa: BLE001 - hatayı ana iş parçacığına taşı
            errors.append(exc)

    worker = threading.Thread(target=_worker, name="edge-tts", daemon=True)
    worker.start()
    worker.join(timeout=75.0)
    if worker.is_alive():
        raise TimeoutError("edge-tts zaman aşımı")
    if errors:
        raise errors[0]


def _edge_tts_synthesize(
    clean_text: str,
    selected_voice: str,
    target_out: Path,
    output_format: str,
) -> Tuple[Optional[Path], float, str]:
    """Ücretsiz Microsoft Neural Türkçe sesiyle gerçek seslendirme üretir."""
    try:
        import edge_tts  # noqa: F401 - kullanılabilirlik kontrolü
    except Exception as exc:
        return None, 0.0, f"edge-tts yüklü değil: {exc}"

    edge_voice = EDGE_VOICE_MAP.get(selected_voice, "tr-TR-EmelNeural")
    target_out = Path(target_out)
    target_out.parent.mkdir(parents=True, exist_ok=True)
    tmp_mp3: Optional[Path] = None

    try:
        if output_format == "mp3":
            mp3_target = target_out if target_out.suffix.lower() == ".mp3" else target_out.with_suffix(".mp3")
            _edge_tts_save(clean_text, edge_voice, mp3_target)
            if not mp3_target.is_file() or mp3_target.stat().st_size <= 1000:
                return None, 0.0, "edge-tts boş MP3 döndürdü"
            return mp3_target, _media_duration(mp3_target), ""

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_mp3 = Path(tmp.name)
        _edge_tts_save(clean_text, edge_voice, tmp_mp3)
        if not tmp_mp3.is_file() or tmp_mp3.stat().st_size <= 1000:
            return None, 0.0, "edge-tts boş MP3 döndürdü"

        ffmpeg_bin = _find_ffmpeg()
        if not ffmpeg_bin:
            return None, 0.0, "edge-tts MP3 üretildi ancak ffmpeg bulunamadı"

        wav_target = target_out if target_out.suffix.lower() == ".wav" else target_out.with_suffix(".wav")
        res = subprocess.run(
            [ffmpeg_bin, "-y", "-i", str(tmp_mp3), "-c:a", "pcm_s16le", str(wav_target)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if res.returncode != 0 or not wav_target.is_file() or wav_target.stat().st_size <= 1000:
            return None, 0.0, f"edge-tts WAV dönüşümü başarısız: {(res.stderr or '')[-160:]}"
        return wav_target, _wav_duration(wav_target), ""
    except Exception as exc:
        logger.warning("[GeminiAudio] edge-tts hatası: %s", exc)
        return None, 0.0, f"edge-tts hatası: {type(exc).__name__}: {str(exc)[:160]}"
    finally:
        if tmp_mp3 is not None:
            tmp_mp3.unlink(missing_ok=True)


def synthesize_gemini_speech(
    text: str,
    voice_name: str = "Puck",
    output_path: Optional[Path] = None,
    output_format: str = "wav",
) -> Tuple[Optional[Path], float]:
    """
    Gemini 3.8 TTS ile seslendirir; tüm anahtarlar tükenirse edge-tts Neural
    Türkçe sese düşer. Dönen değer: (çıktı_dosya_yolu, süre_saniye)
    """
    clean_text = (text or "").strip()
    if not clean_text:
        _set_diagnostics(False, "none", "boş metin")
        return None, 0.0

    selected_voice = voice_name if voice_name in GEMINI_VOICES else "Puck"
    fmt = (output_format or "wav").lower()
    if fmt not in ("wav", "mp3"):
        fmt = "wav"

    if output_path:
        target_out = Path(output_path)
    else:
        target_out = BASE_DIR / "static" / "media" / f"AUD-GEMINI-{int(time.time() * 1000)}.{fmt}"
    target_out.parent.mkdir(parents=True, exist_ok=True)

    keys = collect_gemini_keys()
    gemini_reason = ""

    if keys:
        try:
            raw_audio, model_name, key_label = _synthesize_with_waterfall(
                clean_text, selected_voice, keys
            )
        except Exception as exc:
            gemini_reason = f"Gemini şelalesi başarısız: {type(exc).__name__}: {str(exc)[:200]}"
            logger.warning("[GeminiAudio] %s", gemini_reason)
        else:
            try:
                path, duration = _finalize_audio(raw_audio, target_out, fmt)
            except OSError as exc:
                path, duration = None, 0.0
                gemini_reason = f"Gemini sesi dosyaya yazılamadı: {exc}"
            else:
                gemini_reason = "Gemini sesi dosyaya yazılamadı"
            if path is not None:
                logger.info(
                    "[GeminiAudio] Ses üretildi (%s, %s, anahtar=%s, %.2fs)",
                    model_name, selected_voice, key_label, duration,
                )
                _set_diagnostics(
                    True, "gemini", f"{model_name} · {selected_voice}", key_label
                )
                return path, duration
            logger.warning("[GeminiAudio] %s", gemini_reason)
    else:
        gemini_reason = "GEMINI_API_KEY bulunamadı"
        logger.warning("[GeminiAudio] Hiçbir GEMINI_API_KEY bulunamadı; edge-tts denenecek.")

    # Gemini başarısız/anahtarsız: ücretsiz gerçek Neural Türkçe ses.
    if _edge_tts_allowed():
        edge_path, edge_duration, edge_reason = _edge_tts_synthesize(
            clean_text, selected_voice, target_out, fmt
        )
        if edge_path is not None:
            edge_voice = EDGE_VOICE_MAP.get(selected_voice, "tr-TR-EmelNeural")
            logger.info(
                "[GeminiAudio] edge-tts Neural yedeği kullanıldı (%s, %.2fs)",
                edge_voice, edge_duration,
            )
            _set_diagnostics(True, "edge-tts", f"Microsoft Neural · {edge_voice}", "edge-tts")
            return edge_path, edge_duration
        reason = f"{gemini_reason} | {edge_reason}"
    else:
        reason = f"{gemini_reason} | pytest ortamında edge-tts atlandı"

    logger.warning("[GeminiAudio] TTS başarısız: %s", reason)
    _set_diagnostics(False, "none", reason)
    return None, 0.0
