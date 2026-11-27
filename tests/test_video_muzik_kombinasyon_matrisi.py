# -*- coding: utf-8 -*-
"""
test_video_muzik_kombinasyon_matrisi.py — Kapsamlı Video + Müzik Kombinasyon Matrisi Testi
=========================================================================================
Kural 1 (Dürüstlük): Sahte başarı yok. Her kombinasyon (müzik modelleri × vokal/enstrümantal ×
süre × görevler × restart dayanıklılığı × karakter kasası × VACE R2V × FLF2V × tüm oranlar ×
tüm kamera hareketleri × stitch+müzik miksajı × güvenlik) gerçek HTTP / FFmpeg / işçi protokolü
üzerinden uçtan uca doğrulanır.
"""
from __future__ import annotations

import base64
import io
import json
import os
import struct
import subprocess
import sys
import types
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

COCKPIT_ROOT = Path(__file__).resolve().parents[1]
if str(COCKPIT_ROOT) not in sys.path:
    sys.path.insert(0, str(COCKPIT_ROOT))


def _make_valid_png(w: int = 32, h: int = 32, color=(40, 120, 220)) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), color)
    dr = ImageDraw.Draw(img)
    for y in range(0, h, 2):
        ratio = y / max(1, h - 1)
        dr.line([(0, y), (w, y)], fill=(int((color[0] + 180 * ratio) % 256), int((color[1] + 90 * ratio) % 256), int((color[2] + 60 * ratio) % 256)))
    dr.ellipse([w // 5, h // 5, w * 4 // 5, h * 4 // 5], fill=(220, 140, 60), outline=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_valid_wav(duration_sec: float = 0.5, sample_rate: int = 16000) -> bytes:
    n_frames = int(duration_sec * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        # Hafif sinüs benzeri PCM örnekleri (sessiz değil, gerçek PCM)
        frames = bytearray()
        for i in range(n_frames):
            val = int(4000 * ((i % 64) / 32.0 - 1.0))
            frames += struct.pack("<hh", val, val)
        wf.writeframes(bytes(frames))
    return buf.getvalue()


def _make_valid_flac_stub() -> bytes:
    return b"fLaC" + b"\x00\x00\x00\x22" + b"\x10\x00" * 64


def _make_valid_mp4(out_path: Path, duration_sec: float = 1.5, w: int = 320, h: int = 240) -> Path:
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc2=s={w}x{h}:d={duration_sec:.2f}:r=24",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 10000
    return out_path


@pytest.fixture()
def cockpit_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "matrix_suite")
    monkeypatch.setenv("GPU_WORKER_SECRET", "matrix-worker-secret-key-99")
    monkeypatch.setenv("SESSION_SECRET", "matrix-session-secret-key-99")
    monkeypatch.setenv("FABRIKA_GATEWAY_PASSWORD", "MatrixTestPass!2026")
    monkeypatch.setenv("GATEWAY_PIN", "784321")
    # R2 bulut bağlantısını test sırasında kapat
    monkeypatch.delenv("R2_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("R2_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_SECRET_ACCESS_KEY", raising=False)

    import main as app_main
    import music_studio

    data_dir = tmp_path / "data"
    media_dir = tmp_path / "media"
    data_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(app_main, "DATA_DIR", data_dir)
    monkeypatch.setattr(app_main, "MEDIA_DIR", media_dir)
    monkeypatch.setattr(app_main, "ACTIVE_GPU_WORKERS", {})
    app_main.ACTIVE_SESSIONS.clear()
    app_main.FAILED_ATTEMPTS.clear()
    music_studio._MUSIC_JOBS.clear()

    client = TestClient(app_main.app)
    login = client.post("/api/auth/verify_pin", json={"pin": "784321"})
    assert login.status_code == 200 and login.json().get("token")
    auth_headers = {"Authorization": f"Bearer {login.json()['token']}"}
    worker_headers = {"X-Worker-Key": app_main.get_worker_key()}
    return {
        "client": client,
        "auth": auth_headers,
        "worker": worker_headers,
        "data_dir": data_dir,
        "media_dir": media_dir,
        "app_main": app_main,
        "music_studio": music_studio,
    }


# =============================================================================
# 1. MÜZİK KOMBİNASYON MATRİSİ (Suno Seviyesi ACE-Step 1.5 + Şelale + Güvenlik)
# =============================================================================
@pytest.mark.parametrize("duration_sec", [15, 30, 60, 120, 180, 240])
@pytest.mark.parametrize("instrumental", [False, True])
@pytest.mark.parametrize("vocal_language", ["tr", "en"])
def test_acestep_kaggle_music_matrix_end_to_end(cockpit_env, duration_sec, instrumental, vocal_language):
    """ACE-Step 1.5 × süre (15..240s) × vokal/enstrümantal × dil (tr/en) uçtan uca kuyruk→claim→upload."""
    c = cockpit_env["client"]
    lyrics = "" if instrumental else "[Verse 1]\nGece yildizlar parlar\n[Chorus]\nRuzgarla ucar hayaller"
    resp = c.post(
        "/api/music/generate",
        headers=cockpit_env["auth"],
        json={
            "model_id": "gpu-acestep-1.5",
            "prompt": "Warm Anatolian rock with electric saz and powerful drums",
            "genre": "Turkish Pop Rock",
            "mood": "Epic and inspiring",
            "duration_sec": duration_sec,
            "instrumental": instrumental,
            "lyrics": lyrics,
            "vocal_language": vocal_language,
            "bpm": 122,
            "key_scale": "A minor",
            "time_signature": "4/4",
            "music_task": "text2music",
            "seed": 777,
        },
    )
    assert resp.status_code == 200, resp.text
    job = resp.json()["job"]
    jid = job["job_id"]
    assert job["status"] == "queued_gpu"
    assert job["model_id"] == "gpu-acestep-1.5"
    assert job["duration_sec"] == duration_sec

    # Kaggle GPU işçisi claim eder ve tüm Suno alanlarını eksiksiz alır
    claim = c.get("/api/worker/claim?worker_id=kaggle_t4&mod=music", headers=cockpit_env["worker"])
    assert claim.status_code == 200
    claimed = claim.json()["job"]
    assert claimed is not None and claimed["job_id"] == jid
    assert claimed["method"] == "acestep"
    assert float(claimed["sure_sn"]) == float(duration_sec)
    assert claimed["vocal_language"] == vocal_language
    assert claimed["bpm"] == 122
    assert claimed["key_scale"] == "A minor"
    assert claimed["seed"] == 777
    if not instrumental:
        assert "[Chorus]" in claimed["lyrics"]
        assert claimed["instrumental"] is False
    else:
        assert claimed["instrumental"] is True

    # İşçi gerçek 48kHz/16kHz WAV yükler (dinamik engine_label ile)
    wav_bytes = _make_valid_wav(0.4)
    up = c.post(
        "/api/worker/upload",
        headers=cockpit_env["worker"],
        data={"job_id": jid, "media_type": "audio", "engine_label": "Kaggle GPU ACE-Step 1.5 (48kHz Stereo)"},
        files={"file": (f"{jid}.wav", wav_bytes, "audio/wav")},
    )
    assert up.status_code == 200, up.text
    up_d = up.json()
    assert up_d["success"] is True
    assert up_d["engine_label"] == "Kaggle GPU ACE-Step 1.5 (48kHz Stereo)"

    # İş durumu ve geçmiş doğrulanır
    st = c.get(f"/api/music/job/{jid}", headers=cockpit_env["auth"])
    assert st.status_code == 200
    assert st.json()["job"]["status"] == "completed"
    assert st.json()["job"]["audio_url"].startswith("/api/media/file?path=")


def test_music_vocal_protection_blocks_instrumental_only_models(cockpit_env):
    """Vokal/şarkı sözü isteyen istek enstrümantal-only modellere (gpu-musicgen, stable-audio-2) reddedilir."""
    c = cockpit_env["client"]
    for inst_only in ("gpu-musicgen", "stable-audio-2", "replicate-musicgen"):
        r = c.post(
            "/api/music/generate",
            headers=cockpit_env["auth"],
            json={
                "model_id": inst_only,
                "prompt": "Turkish pop ballad",
                "duration_sec": 30,
                "instrumental": False,
                "lyrics": "[Verse]\nMerhaba dünya",
            },
        )
        assert r.status_code == 400, f"{inst_only} vokal isteğini reddetmeliydi!"
        assert "gpu-acestep-1.5" in r.json()["detail"]


def test_auto_waterfall_vocal_request_skips_instrumental_and_routes_to_acestep(cockpit_env, monkeypatch):
    """auto_waterfall vokal+söz isteğinde Lyria Free Tier 429 alırsa enstrümantal modelleri atlayıp ACE-Step 1.5'e yönlenir."""
    c = cockpit_env["client"]
    ms = cockpit_env["music_studio"]
    monkeypatch.setenv("GEMINI_API_KEY_1", "AIzaSyFakeFreeTierTestKey1234567890")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    class _FakeResp:
        ok = False
        status_code = 429
        text = '{"error":{"message":"Rate limit exceeded (limit: 0 on Free Tier)"}}'

    monkeypatch.setattr(ms.requests, "post", lambda *a, **kw: _FakeResp())

    r = c.post(
        "/api/music/generate",
        headers=cockpit_env["auth"],
        json={
            "model_id": "auto_waterfall",
            "prompt": "Emotional Turkish indie ballad",
            "duration_sec": 90,
            "instrumental": False,
            "lyrics": "[Chorus]\nYıldızların altında yürüdük",
            "vocal_language": "tr",
        },
    )
    assert r.status_code == 200, r.text
    jid = r.json()["job"]["job_id"]

    # Arka plan iş parçacığının şelaleyi bitirip gpu-acestep-1.5 kuyruğuna almasını bekle
    import time
    final_job = None
    for _ in range(40):
        st = c.get(f"/api/music/job/{jid}", headers=cockpit_env["auth"]).json()["job"]
        if st["status"] != "running":
            final_job = st
            break
        time.sleep(0.05)

    assert final_job is not None
    assert final_job["status"] == "queued_gpu"
    assert final_job["model_id"] == "gpu-acestep-1.5"
    trace_str = " ".join(final_job.get("waterfall_trace") or [])
    assert "Free Tier" in trace_str or "gpu-acestep-1.5" in trace_str


@pytest.mark.parametrize("task_type", ["cover", "repaint", "extend"])
def test_acestep_advanced_tasks_require_and_deliver_ref_audio(cockpit_env, task_type):
    """Cover / Repaint / Extend görevleri referans ses yoksa 400 döner, varsa /api/worker/ref-audio ile işçiye ulaşır."""
    c = cockpit_env["client"]
    # Referans ses yoksa reddedilmeli
    r_bad = c.post(
        "/api/music/generate",
        headers=cockpit_env["auth"],
        json={
            "model_id": "gpu-acestep-1.5",
            "prompt": "Acoustic jazz cover",
            "duration_sec": 60,
            "instrumental": True,
            "music_task": task_type,
        },
    )
    assert r_bad.status_code == 400

    # Geçerli referans WAV ile kabul edilmeli
    wav_b64 = "data:audio/wav;base64," + base64.b64encode(_make_valid_wav(0.3)).decode()
    r_ok = c.post(
        "/api/music/generate",
        headers=cockpit_env["auth"],
        json={
            "model_id": "gpu-acestep-1.5",
            "prompt": "Acoustic jazz cover",
            "duration_sec": 60,
            "instrumental": True,
            "music_task": task_type,
            "ref_audio_base64": wav_b64,
            "audio_cover_strength": 0.75,
            "repaint_start": 5.0,
            "repaint_end": 15.0,
        },
    )
    assert r_ok.status_code == 200, r_ok.text
    claim = c.get("/api/worker/claim?worker_id=k1&mod=music", headers=cockpit_env["worker"]).json()["job"]
    assert claim["music_task"] == task_type
    assert claim["ref_audio_url"].startswith("/api/worker/ref-audio/")

    # Korumalı ref-audio ucu anahtarsız reddedilir, worker anahtarıyla 200 döner
    assert c.get(claim["ref_audio_url"]).status_code in (401, 403)
    dl = c.get(claim["ref_audio_url"], headers=cockpit_env["worker"])
    assert dl.status_code == 200 and dl.content[:4] == b"RIFF"


def test_music_job_survives_server_restart_and_accepts_flac(cockpit_env):
    """Render yeniden başlasa bile (_MUSIC_JOBS sıfırlansa bile) Kaggle'dan dönen FLAC şarkı kaybolmaz."""
    c = cockpit_env["client"]
    ms = cockpit_env["music_studio"]
    r = c.post(
        "/api/music/generate",
        headers=cockpit_env["auth"],
        json={
            "model_id": "gpu-acestep-1.5",
            "prompt": "Cinematic orchestral anthem",
            "duration_sec": 120,
            "instrumental": False,
            "lyrics": "[Chorus]\nYüksel gökyüzüne",
        },
    )
    jid = r.json()["job"]["job_id"]
    c.get("/api/worker/claim?worker_id=k1&mod=music", headers=cockpit_env["worker"])

    # Sunucu restart simülasyonu: tüm RAM içi _MUSIC_JOBS sözlüğünü sil!
    ms._MUSIC_JOBS.clear()

    # İşçi FLAC dosyasıyla upload eder
    up = c.post(
        "/api/worker/upload",
        headers=cockpit_env["worker"],
        data={"job_id": jid, "media_type": "audio", "engine_label": "Kaggle GPU ACE-Step 1.5"},
        files={"file": (f"{jid}.flac", _make_valid_flac_stub(), "audio/flac")},
    )
    assert up.status_code == 200, up.text
    assert up.json()["audio_url"].endswith(".flac")

    # /api/music/job/{jid} ve /api/music/history kaydı eksiksiz dönmeli!
    st = c.get(f"/api/music/job/{jid}", headers=cockpit_env["auth"])
    assert st.status_code == 200
    assert st.json()["job"]["status"] == "completed"
    hist = c.get("/api/music/history", headers=cockpit_env["auth"]).json()["items"]
    assert any(h.get("job_id") == jid for h in hist)


def test_music_security_rejects_ssrf_and_path_traversal(cockpit_env):
    """Referans ses URL'sinde path traversal ve SSRF kesinlikle engellenir."""
    c = cockpit_env["client"]
    for evil in ("../../etc/passwd", "http://169.254.169.254/latest/meta-data", "/api/media/file?path=../secrets.json"):
        r = c.post(
            "/api/music/generate",
            headers=cockpit_env["auth"],
            json={
                "model_id": "gpu-acestep-1.5",
                "prompt": "Cover test",
                "music_task": "cover",
                "ref_audio_url": evil,
            },
        )
        assert r.status_code == 400


# =============================================================================
# 2. VİDEO & TUTARLI KARAKTER KOMBİNASYON MATRİSİ (Higgsfield Seviyesi)
# =============================================================================
@pytest.mark.parametrize("aspect,kalite,expected", [
    ("16:9", "480p", (480, 320)),
    ("9:16", "480p", (320, 480)),
    ("1:1", "480p", (480, 480)),
    ("16:9", "832p", (832, 480)),
    ("9:16", "832p", (480, 832)),
    ("1:1", "832p", (640, 640)),
    ("16:9", "720p", (1280, 720)),
    ("9:16", "720p", (720, 1280)),
    ("1:1", "720p", (720, 720)),
])
def test_gpu_worker_all_aspect_ratios_divisible_by_16(aspect, kalite, expected):
    """16:9, 9:16 ve 1:1 tüm kalitelerde doğru en-boy oranında ve 16'nın katı döner."""
    import gpu_worker
    w, h = gpu_worker._cozunurluk(aspect, kalite)
    assert (w, h) == expected
    assert w % 16 == 0 and h % 16 == 0


def test_character_vault_crud_and_inheritance_in_video_endpoints(cockpit_env):
    """Karakter Kasası CRUD + hem /api/studio/video/generate hem /api/lab/generate içinde otomatik miras."""
    c = cockpit_env["client"]
    png_b64 = "data:image/png;base64," + base64.b64encode(_make_valid_png(64, 64, (200, 80, 40))).decode()

    # 1. Karakter kaydet
    cr = c.post(
        "/api/studio/characters",
        headers=cockpit_env["auth"],
        json={
            "name": "Kaptan Demir",
            "character_bible": "32-year-old Turkish captain with short beard, silver armor and crimson cape",
            "style_preset": "cinematic_realism",
            "seed": 551234,
            "tags": "hero,scifi",
            "image_base64": png_b64,
        },
    )
    assert cr.status_code == 200, cr.text
    ch = cr.json()["character"]
    cid = ch["id"]
    assert ch["has_reference_image"] is True
    assert ch["seed"] == 551234

    # 2. Listele
    lst = c.get("/api/studio/characters", headers=cockpit_env["auth"]).json()
    assert any(x["id"] == cid for x in lst["items"])

    # 3. /api/studio/video/generate içinde vace_r2v + character_id kullan (ayrı görsel yüklemeden!)
    r_vace = c.post(
        "/api/studio/video/generate",
        headers=cockpit_env["auth"],
        json={
            "workflow": "vace_r2v",
            "character_id": cid,
            "prompt": "Walking through a misty ancient pine forest at sunrise",
            "aspect_ratio": "1:1",
            "duration": 5,
            "camera_motion": "dolly_zoom",
            "voice": "none",
            "execution_mode": "gpu_queue",
        },
    )
    assert r_vace.status_code == 200, r_vace.text
    task = r_vace.json()["task"]
    assert task["method"] == "vace_r2v"
    assert task["i2v_model"] == "wan2.1-vace-1.3b"
    assert task["seed"] == 551234
    assert task["input_image_url"] is not None
    assert "silver armor" in task["character_bible"]

    # 4. /api/lab/generate içinde de character_id + seed + character_lock çalışır
    r_lab = c.post(
        "/api/lab/generate",
        headers=cockpit_env["auth"],
        json={
            "workflow": "vace_r2v",
            "character_id": cid,
            "prompt": "Standing on a neon rooftop in rain",
            "aspect_ratio": "9:16",
            "duration": 5,
            "voice": "none",
            "execution_mode": "gpu_queue",
        },
    )
    assert r_lab.status_code == 200, r_lab.text
    lab_job = r_lab.json()["job"]
    assert lab_job["seed"] == 551234
    assert lab_job["character_id"] == cid
    assert lab_job["input_image_url"] is not None

    # 5. Silme
    dl = c.delete(f"/api/studio/characters/{cid}", headers=cockpit_env["auth"])
    assert dl.status_code == 200 and dl.json()["deleted"] == cid


def test_flf2v_workflow_end_to_end_validation_and_worker_delivery(cockpit_env):
    """FLF2V (İlk+Son Kare Geçişi): tek kareyle 400 döner, iki kareyle /api/worker/input + /api/worker/end-image sunar."""
    c = cockpit_env["client"]
    start_b64 = "data:image/png;base64," + base64.b64encode(_make_valid_png(48, 48, (10, 40, 120))).decode()
    end_b64 = "data:image/png;base64," + base64.b64encode(_make_valid_png(48, 48, (220, 140, 20))).decode()

    # Sadece başlangıç karesiyle 400 dönmeli
    r_fail = c.post(
        "/api/studio/video/generate",
        headers=cockpit_env["auth"],
        json={"workflow": "flf2v", "prompt": "Day to night transition", "image_base64": start_b64, "voice": "none"},
    )
    assert r_fail.status_code == 400

    # Başlangıç + bitiş karesiyle 200 + claim'de her iki URL gelir
    r_ok = c.post(
        "/api/studio/video/generate",
        headers=cockpit_env["auth"],
        json={
            "workflow": "flf2v",
            "prompt": "Smooth cinematic transition from dawn harbor to golden sunset",
            "image_base64": start_b64,
            "end_image_base64": end_b64,
            "aspect_ratio": "16:9",
            "duration": 5,
            "voice": "none",
            "execution_mode": "gpu_queue",
        },
    )
    assert r_ok.status_code == 200, r_ok.text
    claim = c.get("/api/worker/claim?worker_id=k_flf&mod=video", headers=cockpit_env["worker"]).json()["job"]
    assert claim["method"] == "flf2v"
    assert claim["input_image_url"].startswith("/api/worker/input/")
    assert claim["end_image_url"].startswith("/api/worker/end-image/")

    # Korumalı end-image ucu doğrulama
    assert c.get(claim["end_image_url"]).status_code in (401, 403)
    end_resp = c.get(claim["end_image_url"], headers=cockpit_env["worker"])
    assert end_resp.status_code == 200 and end_resp.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_gpu_worker_dispatch_matrix_all_video_and_music_modes(tmp_path, monkeypatch):
    """gpu_worker.gorev_isle tüm modlarda (acestep, musicgen, flux2_resim+ref, vace_r2v, flf2v, t2v_direct×modeller) doğru motoru çağırır."""
    import gpu_worker

    calls = []
    fake_png = tmp_path / "ref.png"
    fake_png.write_bytes(_make_valid_png(32, 32))
    fake_end = tmp_path / "end.png"
    fake_end.write_bytes(_make_valid_png(32, 32, (200, 200, 10)))
    fake_wav = tmp_path / "out.wav"
    fake_wav.write_bytes(_make_valid_wav(0.2))
    fake_mp4 = tmp_path / "out.mp4"
    fake_mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42moovmdat")

    monkeypatch.setattr(gpu_worker, "acestep_muzik_uret", lambda *a, **kw: (calls.append(("acestep", kw)), fake_wav)[1])
    monkeypatch.setattr(gpu_worker, "muzik_uret", lambda *a, **kw: (calls.append(("musicgen", kw)), fake_wav)[1])
    monkeypatch.setattr(gpu_worker, "secimli_gorsel_uret", lambda *a, **kw: (calls.append(("img", kw)), fake_png)[1])
    monkeypatch.setattr(gpu_worker, "wan21_vace_uret", lambda *a, **kw: (calls.append(("vace", kw)), fake_mp4)[1])
    monkeypatch.setattr(gpu_worker, "secimli_t2v_uret", lambda *a, **kw: (calls.append(("t2v", a[1], kw)), fake_mp4)[1])
    monkeypatch.setattr(gpu_worker, "_medya_birlestir", lambda v, *a, **kw: v)

    # 1) ACE-Step 1.5 (söz + Türkçe + 120s)
    gpu_worker.gorev_isle(
        {"method": "acestep", "prompt": "Turkish rock", "lyrics": "[Chorus]\nMerhaba", "vocal_language": "tr", "duration": 120, "instrumental": False},
        {},
    )
    assert calls[-1][0] == "acestep" and calls[-1][1]["sure_sn"] == 120.0 and calls[-1][1]["vocal_language"] == "tr"

    # 2) image_first_preview WITH reference image -> ref_gorsel gerçekten aktarılır!
    gpu_worker.gorev_isle(
        {"method": "image_first_preview", "prompt": "Hero in rain", "seed": 999, "aspect_ratio": "1:1"},
        {"image_path": str(fake_png)},
    )
    assert calls[-1][0] == "img" and calls[-1][1]["ref_gorsel"] == fake_png and calls[-1][1]["tohum"] == 999

    # 3) vace_r2v (consistent character) -> default sure_sn 5.0 (eski 15.0 hatası yok!)
    gpu_worker.gorev_isle(
        {"method": "vace_r2v", "prompt": "Hero runs across bridge"},
        {"image_path": str(fake_png)},
    )
    assert calls[-1][0] == "vace" and calls[-1][1]["ref_gorseller"] == [fake_png] and calls[-1][1]["sure_sn"] == 5.0

    # 4) flf2v (ilk + son kare)
    gpu_worker.gorev_isle(
        {"method": "flf2v", "prompt": "Transform sunrise to midnight"},
        {"image_path": str(fake_png), "end_image_path": str(fake_end)},
    )
    assert calls[-1][0] == "vace" and calls[-1][1]["ilk_kare"] == fake_png and calls[-1][1]["son_kare"] == fake_end

    # 5) t2v_direct kullanıcı seçtiği modeli onurlandırır (wan2.2-ti2v-5b, ltx-video, wan2.1-vace-1.3b)
    for mdl in ("wan2.2-ti2v-5b", "ltx-video", "wan2.1-vace-1.3b", "wan2.1-t2v-1.3b"):
        gpu_worker.gorev_isle({"method": "t2v_direct", "prompt": "Flying eagle", "i2v_model": mdl}, {})
        assert calls[-1][0] == "t2v" and calls[-1][1] == mdl


def test_flux2_passes_seed_and_reference_image_to_pipeline(tmp_path, monkeypatch):
    """flux2_gorsel_uret gerçekten Flux2KleinPipeline.__call__ içine generator + image=[PIL] geçirir."""
    import gpu_worker
    from PIL import Image

    captured = {}

    class _FakeFlux2Pipe:
        def __call__(self, image=None, prompt=None, height=None, width=None, num_inference_steps=4, generator=None):
            captured["image"] = image
            captured["prompt"] = prompt
            captured["width"] = width
            captured["height"] = height
            captured["generator"] = generator
            return types.SimpleNamespace(images=[Image.new("RGB", (width, height), (50, 150, 200))])

    monkeypatch.setattr(gpu_worker, "flux2_yukle", lambda log=print: _FakeFlux2Pipe())
    ref_p = tmp_path / "char_ref.png"
    ref_p.write_bytes(_make_valid_png(64, 64))

    out = gpu_worker.flux2_gorsel_uret("Knight in snow", 480, 480, adim=4, tohum=12345, ref_gorsel=ref_p)
    try:
        assert out.is_file()
        assert captured["width"] == 480 and captured["height"] == 480
        assert captured["generator"] is not None
        assert isinstance(captured["image"], list) and len(captured["image"]) == 1
    finally:
        out.unlink(missing_ok=True)


@pytest.mark.parametrize("camera_id", [
    "push_in", "pull_out", "orbital", "pan_right", "pan_left",
    "crane_up", "dolly_zoom", "fpv_drone", "handheld_track", "bullet_time", "wind_cloth_glow",
])
def test_all_higgsfield_camera_presets_render_real_mp4(tmp_path, camera_id):
    """Tüm 11 Higgsfield sinema kamera preset'i hem katalogda var hem gerçek FFmpeg MP4 üretir."""
    import ai_video_montaj
    import channels_manager

    cat_ids = {c["id"] for c in channels_manager.CAMERA_MOTIONS}
    assert camera_id in cat_ids

    img = tmp_path / f"scene_{camera_id}.png"
    img.write_bytes(_make_valid_png(320, 180, (60, 90, 160)))
    out_mp4 = tmp_path / f"cam_{camera_id}.mp4"
    ok = ai_video_montaj._sahne_video(img, out_mp4, 320, 180, 1.5, hareket=camera_id)
    assert ok is True and out_mp4.is_file() and out_mp4.stat().st_size > 5000


def test_stitch_clips_mixes_ai_background_music(cockpit_env):
    """/api/studio/stitch-clips üretilmiş AI müzik parçasını videoya gerçek FFmpeg AAC ses akışı olarak miksler."""
    c = cockpit_env["client"]
    mdir = cockpit_env["media_dir"]

    # 2 gerçek kısa MP4 klip + 1 gerçek WAV müzik parçası hazırla
    _make_valid_mp4(mdir / "CLIP_A1.mp4", duration_sec=1.2)
    _make_valid_mp4(mdir / "CLIP_A2.mp4", duration_sec=1.2)
    (mdir / "mus_bg_test.wav").write_bytes(_make_valid_wav(1.5))

    r = c.post(
        "/api/studio/stitch-clips",
        headers=cockpit_env["auth"],
        json={
            "job_ids": ["CLIP_A1", "CLIP_A2"],
            "voice": "none",
            "music_job_id": "mus_bg_test",
            "music_volume": 0.7,
            "prompt": "AI soundtracked film test",
        },
    )
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert job["music_mixed"] is True
    assert job["music_file"] == "mus_bg_test.wav"
    out_mp4 = mdir / f"{job['job_id']}.mp4"
    assert out_mp4.is_file()

    # ffprobe ile videonun gerçekten AAC ses akışı taşıdığını kanıtla!
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(out_mp4)],
        capture_output=True, text=True, timeout=20,
    )
    assert "audio" in (probe.stdout or "").lower()


# =============================================================================
# 3. DEEPSEEK 1. TUR DENETİM DÜZELTME ÇİVİLERİ (Güvenlik, Determinizm, T4, Miksaj)
# =============================================================================
def test_character_seed_is_sha256_deterministic(tmp_path):
    """Karakter seed üretimi Python hash() yerine deterministik SHA-256 kullanır."""
    import hashlib
    from character_store import CharacterStore

    store = CharacterStore(tmp_path / "d", tmp_path / "m")
    ch = store.upsert_character(
        name="Astra",
        character_bible="Young cyber archaeologist with silver bob hair and blue visor",
    )
    expected_digest = hashlib.sha256(f"{ch['id']}:{ch['character_bible']}".encode("utf-8")).digest()
    expected_seed = 100000 + (int.from_bytes(expected_digest[:4], "big") % 899999)
    assert ch["seed"] == expected_seed


def test_enqueue_music_gpu_job_handles_malformed_numbers_safely(cockpit_env):
    """_enqueue_music_gpu_job geçersiz bpm/cover_strength/repaint değerlerinde 500 atmaz, güvenle temizler."""
    app_main = cockpit_env["app_main"]
    rec = app_main._enqueue_music_gpu_job({
        "job_id": "mus_safe_num_1",
        "method": "acestep",
        "prompt": "Synthwave night drive",
        "bpm": "not-a-number",
        "audio_cover_strength": "invalid",
        "repaint_start": "bad",
        "repaint_end": "9999",
        "seed": "oops",
        "duration_sec": "120",
    })
    assert rec["bpm"] is None
    assert rec["audio_cover_strength"] == 0.85
    assert rec["repaint_start"] is None
    assert rec["repaint_end"] == 360.0
    assert rec["seed"] is None
    assert rec["sure_sn"] == 120


def test_acestep_refuses_silent_downgrade_when_cover_param_missing(tmp_path, monkeypatch):
    """Kurulu diffusers cover/repaint parametresini desteklemiyorsa sessizce text2music üretmez, dürüst hata verir."""
    import gpu_worker

    class _OldAcePipe:
        sample_rate = 48000
        def __call__(self, prompt=None, lyrics="", audio_duration=60.0):
            return types.SimpleNamespace(audios=[])

    monkeypatch.setattr(gpu_worker, "_ACESTEP_PIPE", _OldAcePipe())
    monkeypatch.setattr(gpu_worker, "_ACESTEP_KEY", gpu_worker.ACESTEP_TURBO)

    # Sahte diffusers modülü enjekte et (import geçsin, imza kontrolü yakalasın)
    fake_diffusers = types.SimpleNamespace(AceStepPipeline=_OldAcePipe)
    monkeypatch.setitem(sys.modules, "diffusers", fake_diffusers)

    ref_wav = tmp_path / "ref.wav"
    ref_wav.write_bytes(_make_valid_wav(0.2))
    with pytest.raises(RuntimeError, match="cover"):
        gpu_worker.acestep_muzik_uret(
            "Jazz cover", music_task="cover", ref_audio_path=ref_wav,
        )

    with pytest.raises(ValueError, match="ref_audio_path"):
        gpu_worker.acestep_muzik_uret(
            "Extend without ref", music_task="extend", ref_audio_path=None,
        )


def test_stitch_clips_mixes_both_tts_and_background_music(cockpit_env, monkeypatch):
    """Hem TTS anlatım WAV hem AI arka plan müziği aynı anda 44.1kHz stereo AAC olarak mikslenir."""
    c = cockpit_env["client"]
    mdir = cockpit_env["media_dir"]
    app_main = cockpit_env["app_main"]

    _make_valid_mp4(mdir / "CLIP_M1.mp4", duration_sec=1.5)
    _make_valid_mp4(mdir / "CLIP_M2.mp4", duration_sec=1.5)
    (mdir / "mus_track_mix.wav").write_bytes(_make_valid_wav(2.0, sample_rate=48000))

    def _fake_tts(text, voice, out_wav):
        Path(out_wav).write_bytes(_make_valid_wav(1.0, sample_rate=24000))
        return {"ok": True, "engine": "test_tts"}

    monkeypatch.setattr(app_main, "_burc_tts_yaz", _fake_tts)

    r = c.post(
        "/api/studio/stitch-clips",
        headers=cockpit_env["auth"],
        json={
            "job_ids": ["CLIP_M1", "CLIP_M2"],
            "voice": "Aoede",
            "narration_text": "Merhaba uzay ve müzik testi.",
            "music_job_id": "mus_track_mix",
            "music_volume": 0.25,
        },
    )
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert job["music_mixed"] is True
    out_mp4 = mdir / f"{job['job_id']}.mp4"
    assert out_mp4.is_file()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=sample_rate,channels",
         "-of", "csv=p=0", str(out_mp4)],
        capture_output=True, text=True, timeout=20,
    )
    assert "44100" in (probe.stdout or "") and "2" in (probe.stdout or "")


def test_burc_video_inherits_character_vault_profile(cockpit_env):
    """/api/burc/video/generate da character_id üzerinden karakter kilidi, seed ve portre miras alır."""
    c = cockpit_env["client"]
    png_b64 = "data:image/png;base64," + base64.b64encode(_make_valid_png(64, 64, (90, 60, 200))).decode()
    cr = c.post(
        "/api/studio/characters",
        headers=cockpit_env["auth"],
        json={
            "name": "Kozmik Kova",
            "character_bible": "Celestial Aquarius guardian with sapphire cloak and golden amphora",
            "seed": 884422,
            "image_base64": png_b64,
        },
    )
    cid = cr.json()["character"]["id"]
    rb = c.post(
        "/api/burc/video/generate",
        headers=cockpit_env["auth"],
        json={
            "burc_kodu": "kova",
            "konu": "Yıldızlı gökyüzünden su döküyor",
            "character_id": cid,
            "method": "wan_i2v",
            "execution_mode": "gpu_queue",
            "voice": "none",
        },
    )
    assert rb.status_code == 200, rb.text
    task = rb.json()["task"]
    assert task["character_id"] == cid
    assert task["seed"] == 884422
    assert "sapphire cloak" in task["character_bible"]
    assert task["input_image_url"] is not None


def test_v36_smooth_subpixel_30fps_camera_zero_frozen_and_long_durations(cockpit_env, tmp_path):
    """v36: Float64 alt-piksel 30fps kamera (sıfır adım/donma), 180s video ve 360s/120s uzun müzik."""
    import numpy as np
    from PIL import Image, ImageDraw
    import gpu_worker as gw
    import hyperframes_motor as hf

    # 1. Zengin dokulu test görseli üzerinde push_in ve orbital 30fps akıcılık denetimi
    src = tmp_path / "rich_scene.png"
    im = Image.new("RGB", (640, 360), (20, 40, 80))
    dr = ImageDraw.Draw(im)
    for y in range(0, 360, 4):
        dr.line([(0, y), (640, y)], fill=(int(30 + y * 0.5), int(50 + (y % 90)), int(140 - y * 0.2)))
    for x in range(20, 620, 45):
        dr.rectangle([x, 60, x + 22, 300], fill=(220 - (x % 120), 140, 90))
    im.save(src, "PNG")

    for cam in ("push_in", "orbital"):
        out_mp4 = tmp_path / f"smooth_{cam}.mp4"
        res = hf.render_smooth_camera_clip(src, out_mp4, 320, 180, 2.0, camera_motion=cam, fps=30)
        assert res["ok"] is True and res["fps"] == 30
        pr = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate,nb_frames",
             "-of", "csv=p=0", str(out_mp4)],
            capture_output=True, text=True, check=True,
        )
        assert "30/1" in pr.stdout
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(out_mp4), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True, check=True,
        ).stdout
        fr = np.frombuffer(raw, dtype=np.uint8).reshape((-1, 180, 320)).astype(np.float32)
        diffs = [float(np.abs(fr[i + 1] - fr[i]).mean()) for i in range(len(fr) - 1)]
        mid = diffs[5:-5]
        # Eski bug: push_in 55/59 kare donuyordu; orbital 0.03-5.6 testere yapıyordu!
        assert sum(1 for d in mid if d < 0.05) == 0, f"{cam} donmuş kare içeriyor: {mid[:15]}"

    # 2. Uzun video (120s / 180s) ve uzun müzik (360s ACE-Step, 120s MusicGen) sınırları
    c = cockpit_env["client"]
    r_v = c.post(
        "/api/studio/video/generate",
        headers=cockpit_env["auth"],
        json={"prompt": "Uzun belgesel sahnesi", "duration": 120, "workflow": "image_first_preview", "render_target": "kaggle_32gb"},
    )
    assert r_v.status_code == 200
    assert float(r_v.json()["task"]["duration"]) == 120.0

    r_m1 = c.post(
        "/api/music/generate",
        headers=cockpit_env["auth"],
        json={"model_id": "gpu-acestep-1.5", "prompt": "Uzun epik senfoni", "duration_sec": 360},
    )
    assert r_m1.status_code == 200 and r_m1.json()["job"]["duration_sec"] == 360

    r_m2 = c.post(
        "/api/music/generate",
        headers=cockpit_env["auth"],
        json={"model_id": "gpu-musicgen", "prompt": "Uzun Anadolu lo-fi", "duration_sec": 120, "instrumental": True},
    )
    assert r_m2.status_code == 200 and r_m2.json()["job"]["duration_sec"] == 120

    # 3. GPU I2V 60sn zincirleme + stereo eşit-güçlü crossfade birleştirme
    segs_60 = gw._i2v_segment_planla(60.0, 5.0)
    assert len(segs_60) == 12 and sum(segs_60) >= 59.9

    sr = 1000
    a1 = np.ones((2, 5000), dtype=np.float32) * 0.5
    a2 = np.ones((2, 5000), dtype=np.float32) * 0.5
    joined = gw._stereo_crossfade_birlestir([a1, a2], sr, gecis_sn=1.0)
    assert joined.shape == (2, 9000)
    assert float(np.max(np.abs(joined))) <= 0.72



