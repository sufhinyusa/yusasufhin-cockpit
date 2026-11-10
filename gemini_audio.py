#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gemini_audio.py — Google Gemini Nöral Ses ve TTS Motoru (yusasufhin.com)
-----------------------------------------------------------------------
Google Gemini 2.5 Flash TTS API'sini kullanarak stüdyo videoları ve podcast'ler
için yüksek kaliteli stüdyo seslendirmesi üretir.
Microsoft Edge kullanılmaz; %100 saf Google Gemini altyapısıdır.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

import requests

logger = logging.getLogger("YusasufhinCockpit.GeminiAudio")

BASE_DIR = Path(__file__).resolve().parent

# Gemini Ses Profilleri
GEMINI_VOICES = {
    "Aoede": "Aoede (Sıcak, Etkileyici Kadın — Astroloji ve Hikaye Anlatımı)",
    "Puck": "Puck (Dinamik, Enerjik Erkek — Teknoloji ve Viral Shorts)",
    "Charon": "Charon (Derin, Otoriter Erkek — Belgesel ve Tarih)",
    "Kore": "Kore (Net, Sakin Kadın — Haber ve Eğitici İçerik)",
    "Fenrir": "Fenrir (Güçlü, Dramatik Erkek — Sinematik ve Fragman)",
}

def collect_gemini_keys() -> List[str]:
    """Sistem ortamından ve Persona/.env dosyasından tüm Gemini API anahtarlarını toplar."""
    keys: List[str] = []
    # 1. Ortam değişkenleri
    for k, v in os.environ.items():
        if "GEMINI_API_KEY" in k.upper() and v and v.strip() and v.strip() not in keys:
            keys.append(v.strip().strip('"\''))

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
            except Exception:
                pass
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


def synthesize_gemini_speech(
    text: str,
    voice_name: str = "Puck",
    output_path: Optional[Path] = None,
    output_format: str = "wav",
) -> Tuple[Optional[Path], float]:
    """
    Google Gemini 2.5 TTS kullanarak verilen metni seslendirir.
    Dönen değer: (çıktı_dosya_yolu, süre_saniye)
    """
    clean_text = (text or "").strip()
    if not clean_text:
        return None, 0.0

    keys = collect_gemini_keys()
    if not keys:
        logger.warning("[GeminiAudio] Hiçbir GEMINI_API_KEY bulunamadı!")
        return None, 0.0

    models = ["gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"]
    selected_voice = voice_name if voice_name in GEMINI_VOICES else "Puck"

    raw_pcm: Optional[bytes] = None

    # Çoklu anahtar ve model devir havuzu
    for model_name in models:
        for api_key in keys:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": clean_text}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {
                                "voiceName": selected_voice
                            }
                        }
                    }
                }
            }
            try:
                resp = requests.post(url, json=payload, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        for p in parts:
                            inline = p.get("inlineData", {})
                            b64 = inline.get("data")
                            if b64:
                                raw_pcm = base64.b64decode(b64)
                                logger.info("[GeminiAudio] Ses başarıyla üretildi (%d bayt PCM, Model: %s, Ses: %s)", len(raw_pcm), model_name, selected_voice)
                                break
                    if raw_pcm:
                        break
                elif resp.status_code == 429:
                    logger.debug("[GeminiAudio] Kota aşıldı (%s), sıradaki anahtara geçiliyor...", api_key[:10])
                    continue
                else:
                    logger.debug("[GeminiAudio] HTTP %d: %s", resp.status_code, resp.text[:120])
            except Exception as e:
                logger.debug("[GeminiAudio] İstek hatası (%s): %s", model_name, e)
        if raw_pcm:
            break

    if not raw_pcm:
        logger.warning("[GeminiAudio] Gemini TTS çıktısı alınamadı.")
        return None, 0.0

    # Raw PCM verisini FFmpeg ile yüksek kaliteli WAV veya MP3'e çevir
    target_out = output_path or (BASE_DIR / "static" / "media" / f"AUD-GEMINI-{int(time.time()*1000)}.{output_format}")
    target_out.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin and os.path.isfile("/opt/homebrew/bin/ffmpeg"):
        ffmpeg_bin = "/opt/homebrew/bin/ffmpeg"
    if not ffmpeg_bin:
        try:
            import imageio_ffmpeg
            ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg_bin = "ffmpeg"

    with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as tmp_pcm:
        tmp_pcm.write(raw_pcm)
        tmp_pcm_path = tmp_pcm.name

    try:
        # Gemini L16 PCM: 24000 Hz, 1 kanal (mono), 16-bit little-endian
        acodec = ["-c:a", "libmp3lame", "-b:a", "192k"] if output_format == "mp3" else ["-c:a", "pcm_s16le"]
        cmd = [
            ffmpeg_bin, "-y",
            "-f", "s16le", "-ar", "24000", "-ac", "1",
            "-i", tmp_pcm_path,
            *acodec,
            str(target_out)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and target_out.exists() and target_out.stat().st_size > 500:
            # Süreyi hesapla: 24000 Hz, 16-bit (2 bayt/örnek) mono
            duration_sec = round(len(raw_pcm) / (24000 * 2), 2)
            return target_out, duration_sec
        else:
            logger.warning("[GeminiAudio] FFmpeg PCM dönüşümü başarısız: %s", res.stderr[-200:])
    finally:
        if os.path.exists(tmp_pcm_path):
            os.remove(tmp_pcm_path)

    return None, 0.0
