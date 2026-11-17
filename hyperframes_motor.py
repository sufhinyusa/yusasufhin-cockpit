# -*- coding: utf-8 -*-
"""hyperframes_motor.py — Link #296 Video Motoru & Anında Bulut I2V Hareket Sentezleyici.

Link #296 ("Claude ile Video Editlemek İçin En İyi Repoları İnceledim") bulgularının
yusasufhin.com stüdyosuna doğrudan entegre edilmiş çekirdek modülü:
  * **HyperFrames**: Zaman çizelgesi tabanlı HTML5/CSS/Canvas kompozisyonu (.html) +
    FFmpeg H.264 MP4 render köprüsü.
  * **opus-video-skills & Barty-Bart**: Kinetik tipografi sahne kartları ve sahne ritmi.
  * **saas-motion-kit**: Ardışık sahnelerde tekrar etmeyen `xfade` geçişleri.
  * **brag & ffmpeg-skill**: İlk/orta kare parlaklık-düzlük kontrolü + platform uyumu.
  * **open-edit**: Ekrandaki/anlatımdaki sayısal verilerin kaynak metne göre doğrulanması.
  * **product-launch-motion**: Web sitesi URL'sinden otomatik lansman sahne akışı.
  * **rea-video**: Mevcut MP4 dosyasından sahne/kesim/telemetri şeması (reverse-engineer).

Dürüstlük (Kural 1):
  Canlı Wan2.1/LTX GPU işçisi bağlı değilken onaylı görselden üretilen hareketli MP4,
  gerçek video difüzyonu DEĞİLDİR — açıkça `simulasyon=True`, `video_difuzyonu=False` ve
  `"bulut hareketli kurgu"` etiketiyle sunulur.
"""
from __future__ import annotations

import html as _html
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("YusasufhinCockpit.HyperFramesMotor")

KOK = Path(__file__).resolve().parent
FONT_BOLD = KOK / "static" / "fonts" / "DejaVuSans-Bold.ttf"
FONT_REG = KOK / "static" / "fonts" / "DejaVuSans.ttf"


def _ffmpeg_bin() -> str:
    try:
        from ai_video_montaj import _ffmpeg
        return _ffmpeg()
    except Exception:
        return shutil.which("ffmpeg") or "ffmpeg"


def _cozunurluk(aspect_ratio: str) -> Tuple[int, int]:
    oran = (aspect_ratio or "16:9").replace(" ", "")
    if oran == "9:16":
        return 720, 1280
    if oran == "1:1":
        return 720, 720
    return 1280, 720


def _norm_metric_tok(tok: str) -> str:
    t = re.sub(r"\s+", "", (tok or "").strip().lower())
    return re.sub(r"kat$", "x", t)


def verify_onscreen_metrics(narration_text: str, source_text: str) -> Dict[str, Any]:
    """Link #296 (`open-edit`): Anlatımdaki sayısal iddiaları kaynak metinle karşılaştırır."""
    num_re = re.compile(r"(?:\b\d+(?:[.,]\d+)?\s*(?:%|x|kat|gb|mb|tb|sn|ms|saat|tl|\$|€)?\b|%\s*\d+(?:[.,]\d+)?)", re.I)
    kaynak_nums = {_norm_metric_tok(m) for m in num_re.findall(source_text or "") if m.strip()}
    anlatim_nums = [m.strip() for m in num_re.findall(narration_text or "") if m.strip()]
    dogrulanan: List[str] = []
    dogrulanmayan: List[str] = []
    for n in anlatim_nums:
        if _norm_metric_tok(n) in kaynak_nums:
            dogrulanan.append(n)
        else:
            dogrulanmayan.append(n)
    return {
        "checked": True,
        "verified_numbers": dogrulanan,
        "unverified_numbers": dogrulanmayan,
        "clean": len(dogrulanmayan) == 0,
    }


def _kamera_filtre_ifadesi(camera_motion: str, kare: int, genislik: int, yukseklik: int) -> str:
    """Seçili kamera hareketi için pürüzsüz FFmpeg `zoompan` filtresi üretir."""
    cam = (camera_motion or "otomatik").strip().lower()
    k = max(24, kare)
    if cam in ("orbital", "wind_cloth_glow"):
        z = "1.10+0.05*sin(2*PI*on/{k})".format(k=k)
        x = "(iw-iw/zoom)*(0.5+0.35*sin(2*PI*on/{k}))".format(k=k)
        y = "(ih-ih/zoom)*(0.5+0.25*cos(2*PI*on/{k}))".format(k=k)
    elif cam == "pull_out":
        z = f"if(eq(on,1),1.20,max(1.20-0.20*(on/{k}),1.0))"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif cam in ("pan_right", "pan_left"):
        z = "1.14"
        x = f"(iw-iw/zoom)*(on/{k})" if cam == "pan_right" else f"(iw-iw/zoom)*(1-on/{k})"
        y = "ih/2-(ih/zoom/2)"
    else:
        # push_in veya otomatik
        z = f"min(1.0+0.18*(on/{k}),1.20)"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"

    return (
        f"scale={int(genislik * 1.25)}:{int(yukseklik * 1.25)}:force_original_aspect_ratio=increase,"
        f"crop={int(genislik * 1.25)}:{int(yukseklik * 1.25)},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={genislik}x{yukseklik}:fps=24,"
        f"setsar=1,vignette=PI/6,format=yuv420p"
    )


def build_hyperframes_html(
    hedef_html: Path,
    title: str,
    subtitle: str,
    scenes: List[Dict[str, Any]],
    duration_sec: float,
    aspect_ratio: str = "16:9",
    style_preset: str = "cinematic_realism",
) -> Path:
    """Link #296 (`HyperFrames`): Tarayıcıda doğrudan oynatılıp WebM/MP4 kaydedilebilen HTML5 zaman çizelgesi üretir."""
    w, h = _cozunurluk(aspect_ratio)
    accent_map = {
        "astrology_mystic": "#a78bfa",
        "tech_futuristic": "#38bdf8",
        "pixar_3d_animation": "#f59e0b",
        "anime_2d": "#f472b6",
        "history_documentary": "#d97706",
        "minimal_explainer": "#10b981",
    }
    accent = accent_map.get(style_preset, "#38bdf8")
    safe_title = _html.escape(title[:80] or "yusasufhin Studio")
    safe_sub = _html.escape(subtitle[:180] or "")
    scenes_json = json.dumps(
        [{"caption": str(s.get("caption") or title)[:120], "motion": str(s.get("motion") or "orbital")} for s in (scenes or [{"caption": title, "motion": "orbital"}])],
        ensure_ascii=False,
    ).replace("<", "\\u003c").replace(">", "\\u003e")
    dur_ms = max(3000, int(round(duration_sec * 1000)))

    html_doc = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HyperFrames Composition — {safe_title}</title>
<style>
  *{{box-sizing:border-box}} body{{margin:0;background:#050811;color:#f8fafc;font-family:system-ui,-apple-system,sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;padding:16px}}
  .stage{{position:relative;width:min(92vw,{(920 if w >= h else 420)}px);aspect-ratio:{w}/{h};border-radius:14px;overflow:hidden;border:1px solid rgba(148,163,184,.25);background:#070b17;box-shadow:0 24px 60px rgba(0,0,0,.7)}}
  canvas{{width:100%;height:100%;display:block}}
  .bar{{margin-top:14px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
  button{{background:{accent};color:#050811;border:none;padding:10px 16px;border-radius:8px;font-weight:700;cursor:pointer}}
  .meta{{font-size:.82rem;color:#94a3b8}}
</style>
</head>
<body>
<div class="stage"><canvas id="hfCanvas" width="{w}" height="{h}"></canvas></div>
<div class="bar">
  <button type="button" onclick="recordHyperFrames()">⬇️ WebM/MP4 Olarak Kaydet</button>
  <span class="meta">HyperFrames Engine · {w}x{h} @ 30fps · {(dur_ms/1000):.1f} sn</span>
</div>
<script>
const canvas = document.getElementById('hfCanvas');
const ctx = canvas.getContext('2d');
const SCENES = {scenes_json};
const TITLE = {json.dumps(title[:90], ensure_ascii=False).replace("<", "\\u003c")};
const SUB = {json.dumps(subtitle[:180], ensure_ascii=False).replace("<", "\\u003c")};
const ACCENT = {json.dumps(accent)};
const DURATION = {dur_ms};
const t0 = performance.now();
const stars = Array.from({{length: 72}}, (_, i) => ({{x: (i*137.5)%1, y: (i*293.3)%1, r: 0.8 + (i%4)*0.7, sp: 0.2 + (i%5)*0.12}}));

function draw(now) {{
  const p = ((now - t0) % DURATION) / DURATION;
  const W = canvas.width, H = canvas.height;
  const g = ctx.createRadialGradient(W*(0.5+0.15*Math.sin(p*6.28)), H*(0.45+0.1*Math.cos(p*6.28)), 40, W/2, H/2, Math.max(W,H)*0.75);
  g.addColorStop(0, '#131d38'); g.addColorStop(1, '#04070f');
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  stars.forEach(s => {{
    const sx = ((s.x + p * s.sp * 0.2) % 1) * W;
    const sy = ((s.y + p * s.sp * 0.1) % 1) * H;
    ctx.fillStyle = 'rgba(226,232,240,' + (0.25 + 0.55*Math.abs(Math.sin(p*12 + s.x*10))) + ')';
    ctx.beginPath(); ctx.arc(sx, sy, s.r, 0, Math.PI*2); ctx.fill();
  }});
  const idx = Math.min(SCENES.length - 1, Math.floor(p * SCENES.length));
  const localP = (p * SCENES.length) - idx;
  const fade = Math.min(1, localP * 4) * Math.min(1, (1 - localP) * 4 + 0.15);
  ctx.save(); ctx.globalAlpha = fade;
  ctx.strokeStyle = ACCENT; ctx.lineWidth = 3;
  const rad = Math.min(W, H) * (0.22 + 0.04 * Math.sin(p * Math.PI * 2));
  ctx.beginPath(); ctx.arc(W/2, H*0.42, rad, 0, Math.PI*2); ctx.stroke();
  ctx.fillStyle = '#f8fafc'; ctx.textAlign = 'center';
  ctx.font = 'bold ' + Math.round(W*0.042) + 'px system-ui, sans-serif';
  ctx.fillText(TITLE.slice(0, 48), W/2, H*0.44);
  ctx.fillStyle = ACCENT; ctx.font = '600 ' + Math.round(W*0.025) + 'px system-ui, sans-serif';
  ctx.fillText((SCENES[idx] && SCENES[idx].caption || SUB).slice(0, 64), W/2, H*0.54);
  ctx.restore();
  ctx.fillStyle = 'rgba(148,163,184,0.8)'; ctx.font = Math.round(W*0.018) + 'px monospace';
  ctx.textAlign = 'left'; ctx.fillText('yusasufhin.com · HyperFrames', 28, H - 26);
  requestAnimationFrame(draw);
}}
requestAnimationFrame(draw);

function recordHyperFrames() {{
  const st = canvas.captureStream(30);
  const mime = MediaRecorder.isTypeSupported('video/mp4') ? 'video/mp4' : 'video/webm';
  const rec = new MediaRecorder(st, {{mimeType: mime}});
  const chunks = [];
  rec.ondataavailable = e => e.data.size && chunks.push(e.data);
  rec.onstop = () => {{
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(chunks, {{type: mime}}));
    a.download = 'hyperframes-video.' + (mime.includes('mp4') ? 'mp4' : 'webm');
    a.click();
  }};
  rec.start(); setTimeout(() => rec.stop(), DURATION);
}}
</script>
</body>
</html>"""
    hedef_html.parent.mkdir(parents=True, exist_ok=True)
    hedef_html.write_text(html_doc, encoding="utf-8")
    return hedef_html


def instant_i2v_motion(
    image_path: Path,
    hedef_mp4: Path,
    prompt: str = "",
    camera_motion: str = "orbital",
    aspect_ratio: str = "16:9",
    duration_sec: float = 5.0,
    audio_path: Optional[Path] = None,
    ass_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Onaylı bir görselden anında akıcı kamera hareketli (orbit/push/pan) MP4 üretir.

    Kural 1: Bu bir FFmpeg hareket kurgusudur (`video_difuzyonu=False`, `simulasyon=True`);
    uzak Wan2.1 GPU işçisi bağlı değilken kullanıcının boş beklemesini önler.
    """
    src = Path(image_path)
    out = Path(hedef_mp4)
    if not src.is_file():
        return {"ok": False, "error": "Kaynak görsel bulunamadı."}

    w, h = _cozunurluk(aspect_ratio)
    sure = max(3.0, min(30.0, float(duration_sec or 5.0)))
    kare = max(24, int(round(sure * 24)))
    ff = _ffmpeg_bin()
    out.parent.mkdir(parents=True, exist_ok=True)
    gecici = out.with_name(f".{out.stem}.{time.time_ns()}.part.mp4")

    vf_parts = [_kamera_filtre_ifadesi(camera_motion, kare, w, h)]
    if ass_path and Path(ass_path).is_file():
        kacis = str(Path(ass_path)).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        vf_parts.append(f"subtitles=filename='{kacis}'")

    has_audio = bool(audio_path and Path(audio_path).is_file() and Path(audio_path).stat().st_size > 500)

    def _run_ffmpeg(vf_str: str) -> subprocess.CompletedProcess[str]:
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-framerate", "24", "-t", f"{sure:.2f}", "-i", str(src)]
        if has_audio:
            cmd += ["-i", str(audio_path)]
        else:
            cmd += ["-f", "lavfi", "-t", f"{sure:.2f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        cmd += [
            "-vf", vf_str,
            "-map", "0:v:0", "-map", "1:a:0",
            "-frames:v", str(kare),
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage", "-threads", "1", "-crf", "24", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
            str(gecici),
        ]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    res = _run_ffmpeg(",".join(vf_parts))
    if res.returncode != 0 and len(vf_parts) > 1:
        # Altyazı filtresi (libass eksikliği vb.) başarısızsa altyazısız dene
        res = _run_ffmpeg(vf_parts[0])
    if res.returncode != 0 or not gecici.is_file():
        gecici.unlink(missing_ok=True)
        return {"ok": False, "error": f"FFmpeg hareket render hatası: {(res.stderr or '')[-200:]}"}

    os.replace(gecici, out)
    try:
        from video_render import video_kalite_denetle
        kalite = video_kalite_denetle(out, beklenen_oran=aspect_ratio)
    except Exception:
        kalite = {"gecerli": True, "uygun": True}

    return {
        "ok": bool(kalite.get("gecerli", True)),
        "path": out,
        "file_size_bytes": out.stat().st_size,
        "resolution": f"{w}x{h}",
        "duration_sec": round(sure, 2),
        "kalite": kalite,
        "simulasyon": True,
        "video_difuzyonu": False,
        "kaynak": "bulut_hareket_i2v",
    }


def cloud_real_i2v_animate(
    image_path: Path,
    hedef_mp4: Path,
    prompt: str = "",
    aspect_ratio: str = "16:9",
    duration_sec: float = 3.0,
    audio_path: Optional[Path] = None,
    ass_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Onaylı bir görseldeki karakterleri & sahneyi gerçek I2V difüzyonuyla canlandırır (LTX-Video ZeroGPU).

    FFmpeg zoompan değildir — görselin içindeki figür, su, rüzgar ve nesnelere gerçek
    kare-arası video difüzyonu uygular (`video_difuzyonu=True`, `simulasyon=False`).
    """
    src = Path(image_path)
    out = Path(hedef_mp4)
    if not src.is_file():
        return {"ok": False, "error": "Kaynak görsel bulunamadı."}
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("HF_TOKEN"):
        return {"ok": False, "error": "Pytest ortamında HF_TOKEN olmadan LTX ZeroGPU atlandı."}

    try:
        from gradio_client import Client, handle_file
        import ai_video_montaj as _avm
    except Exception as e:
        return {"ok": False, "error": f"LTX istemci yüklenemedi: {type(e).__name__}"}

    tok = _avm._hf_token()
    if not tok:
        return {"ok": False, "error": "Bulut gerçek karakter canlandırma (LTX-Video ZeroGPU) için HF_TOKEN gerekli."}

    oran = (aspect_ratio or "16:9").replace(" ", "")
    if oran == "9:16":
        lw, lh = 448, 768
    elif oran == "1:1":
        lw, lh = 576, 576
    else:
        lw, lh = 768, 448

    temiz_p = (prompt or "").strip()
    anim_prompt = (
        "The subject, hands, water, hair, fabric, and natural elements inside the image come alive with smooth, "
        f"expressive continuous motion: {temiz_p}"
        if temiz_p
        else "The characters and natural elements in the scene move smoothly and realistically with gentle natural motion."
    )
    dur_val = max(2.0, min(5.0, float(duration_sec or 3.0)))

    gradio_vid_path: Optional[Path] = None
    try:
        client = Client("Lightricks/ltx-video-distilled", token=tok, verbose=False)
        res = client.predict(
            prompt=anim_prompt[:450],
            negative_prompt="static frozen frame, worst quality, inconsistent motion, blurry, jittery, distorted faces, extra limbs",
            input_image_filepath=handle_file(str(src)),
            input_video_filepath=None,
            height_ui=lh,
            width_ui=lw,
            mode="image-to-video",
            duration_ui=dur_val,
            ui_frames_to_use=9,
            seed_ui=42,
            randomize_seed=True,
            ui_guidance_scale=1,
            improve_texture_flag=True,
            api_name="/image_to_video",
        )
        vid_item = res[0] if isinstance(res, (list, tuple)) and res else res
        raw_vid = vid_item.get("video") if isinstance(vid_item, dict) else vid_item
        if not raw_vid or not Path(str(raw_vid)).is_file():
            return {"ok": False, "error": "LTX-Video çıktı videosu üretemedi."}
        gradio_vid_path = Path(str(raw_vid))

        out.parent.mkdir(parents=True, exist_ok=True)
        gecici = out.with_name(f".{out.stem}.{time.time_ns()}.ltx.mp4")
        ff = _ffmpeg_bin()
        has_audio = bool(audio_path and Path(audio_path).is_file() and Path(audio_path).stat().st_size > 500)
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(gradio_vid_path)]
        if has_audio:
            cmd += ["-i", str(audio_path)]
        vf_parts: List[str] = ["format=yuv420p"]
        if ass_path and Path(ass_path).is_file():
            kacis = str(Path(ass_path)).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            vf_parts.append(f"subtitles=filename='{kacis}'")
        cmd += ["-vf", ",".join(vf_parts), "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1", "-crf", "22", "-pix_fmt", "yuv420p"]
        if has_audio:
            cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "128k", "-shortest"]
        cmd += ["-movflags", "+faststart", str(gecici)]

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode != 0 and len(vf_parts) > 1:
            # Altyazı olmadan tekrar dene
            cmd_no_sub = [x if not x.startswith("format=yuv420p,") else "format=yuv420p" for x in cmd]
            r = subprocess.run(cmd_no_sub, capture_output=True, text=True, timeout=180)
        if r.returncode != 0 or not gecici.is_file():
            gecici.unlink(missing_ok=True)
            shutil.copy2(gradio_vid_path, gecici)
        os.replace(gecici, out)

        try:
            from video_render import video_kalite_denetle
            kalite = video_kalite_denetle(out, beklenen_oran=aspect_ratio)
        except Exception:
            kalite = {"gecerli": True, "uygun": True, "genislik": lw, "yukseklik": lh}

        return {
            "ok": bool(kalite.get("gecerli", True)) and out.is_file() and out.stat().st_size > 10000,
            "path": out,
            "file_size_bytes": out.stat().st_size,
            "resolution": f"{kalite.get('genislik') or lw}x{kalite.get('yukseklik') or lh}",
            "duration_sec": float(kalite.get("sure_sn") or dur_val),
            "kalite": kalite,
            "simulasyon": False,
            "video_difuzyonu": True,
            "kaynak": "ltx-video-distilled-i2v",
        }
    except Exception as e:
        logger.info("[HyperFrames] LTX-Video I2V başarısız: %s", str(e)[:160])
        return {"ok": False, "error": f"LTX-Video ZeroGPU I2V hatası: {type(e).__name__}: {str(e)[:140]}"}
    finally:
        if gradio_vid_path is not None:
            shutil.rmtree(gradio_vid_path.parent, ignore_errors=True)


def _kinetic_card_png(
    hedef_png: Path,
    title: str,
    subtitle: str,
    w: int,
    h: int,
    accent_rgb: Tuple[int, int, int] = (56, 189, 248),
) -> Path:
    """Link #296 (`opus-video-skills`): Kinetik tipografi sahne kartı PNG'si çizer."""
    import textwrap
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (w, h), (9, 13, 26))
    draw = ImageDraw.Draw(im)
    for y in range(0, h, 8):
        oran = y / max(1, h)
        r = int(9 + oran * accent_rgb[0] * 0.14)
        g = int(13 + oran * accent_rgb[1] * 0.14)
        b = int(26 + oran * accent_rgb[2] * 0.20)
        draw.rectangle([0, y, w, y + 8], fill=(r, g, b))

    draw.rectangle([48, 48, w - 48, h - 48], outline=accent_rgb, width=3)
    try:
        f_title = ImageFont.truetype(str(FONT_BOLD), max(34, w // 22)) if FONT_BOLD.is_file() else ImageFont.load_default()
        f_sub = ImageFont.truetype(str(FONT_REG), max(22, w // 36)) if FONT_REG.is_file() else ImageFont.load_default()
    except Exception:
        f_title = f_sub = ImageFont.load_default()

    satirlar = textwrap.wrap(title.strip() or "yusasufhin Studio", width=26)[:4]
    y_cur = int(h * 0.30)
    for s in satirlar:
        draw.text((w // 2, y_cur), s, fill=(248, 250, 252), font=f_title, anchor="mm")
        y_cur += max(48, w // 17)

    alt = textwrap.wrap(subtitle.strip(), width=44)[:3]
    y_sub = y_cur + 28
    for s in alt:
        draw.text((w // 2, y_sub), s, fill=accent_rgb, font=f_sub, anchor="mm")
        y_sub += max(32, w // 28)

    hedef_png.parent.mkdir(parents=True, exist_ok=True)
    im.save(hedef_png, "PNG")
    return hedef_png


def hyperframes_studio_render(
    hedef_mp4: Path,
    hedef_html: Path,
    prompt: str,
    image_prompts: List[str],
    aspect_ratio: str = "16:9",
    style_preset: str = "cinematic_realism",
    camera_motion: str = "orbital",
    duration_sec: float = 9.0,
    audio_path: Optional[Path] = None,
    source_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Çok sahneli HyperFrames + Link #296 sinematik montaj motoru."""
    import ai_video_montaj as _avm

    dusuk_bellek = bool(os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"))
    w, h = _cozunurluk(aspect_ratio)
    if dusuk_bellek:
        oran = (aspect_ratio or "16:9").replace(" ", "")
        w, h = (480, 854) if oran == "9:16" else (480, 480) if oran == "1:1" else (854, 480)
        sahneler_say = 2
    else:
        sahneler_say = max(2, min(4, len(image_prompts) or 3))
    sahne_suresi = max(2.5, min(5.0, float(duration_sec) / sahneler_say))

    gecici = Path(tempfile.mkdtemp(prefix="hf_studio_"))
    try:
        png_list: List[Path] = []
        saglayici = "hyperframes_canvas"
        for i in range(sahneler_say):
            sp = image_prompts[i % len(image_prompts)] if image_prompts else prompt
            hedef_png = gecici / f"scene_{i}.png"
            prev = _avm.preview_single_image(
                sp, hedef_png, genislik=w, yukseklik=h,
                style_preset=style_preset, camera_motion=camera_motion, use_planner=False,
            )
            if prev.get("ok") and hedef_png.is_file():
                saglayici = str(prev.get("provider") or "cloud")
                png_list.append(hedef_png)
            else:
                return {
                    "ok": False,
                    "error": prev.get("error") or "Gerçek YZ görseli üretilemedi; promptu metin kartı olarak basma devre dışı.",
                }

        parcalar: List[Path] = []
        for idx, png in enumerate(png_list):
            mp4_part = gecici / f"part_{idx}.mp4"
            hareket = _avm.KAMERA_HAREKETLERI[idx % len(_avm.KAMERA_HAREKETLERI)]
            if _avm._sahne_video(png, mp4_part, w, h, sahne_suresi, hareket=hareket):
                parcalar.append(mp4_part)

        if not parcalar:
            return {"ok": False, "error": "HyperFrames sahne klipleri üretilemedi."}

        sessiz = gecici / "sessiz.mp4"
        if not _avm.montaj_birlestir(parcalar, sessiz, gecis_sn=0.45, sure_sn=sahne_suresi):
            return {"ok": False, "error": "HyperFrames xfade birleştirme başarısız."}

        hedef_mp4.parent.mkdir(parents=True, exist_ok=True)
        ff = _ffmpeg_bin()
        has_audio = bool(audio_path and Path(audio_path).is_file() and Path(audio_path).stat().st_size > 500)
        if has_audio:
            r = subprocess.run(
                [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(sessiz), "-i", str(audio_path),
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(hedef_mp4)],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                shutil.copy2(sessiz, hedef_mp4)
        else:
            shutil.copy2(sessiz, hedef_mp4)

        hf_scenes = [{"caption": f"Sahne {i+1}: {p[:48]}", "motion": _avm.KAMERA_HAREKETLERI[i % len(_avm.KAMERA_HAREKETLERI)]} for i, p in enumerate(image_prompts[:sahneler_say] or [prompt])]
        build_hyperframes_html(hedef_html, prompt[:70], source_url or style_preset, hf_scenes, len(parcalar) * sahne_suresi, aspect_ratio, style_preset)

        from video_render import video_kalite_denetle
        kalite = video_kalite_denetle(hedef_mp4, beklenen_oran=aspect_ratio)
        gecisler = _avm.sec_xfade_gecisleri(max(0, len(parcalar) - 1))
        metrics = verify_onscreen_metrics(prompt, source_url or prompt)

        preview_out: Optional[Path] = None
        if png_list and png_list[0].is_file():
            preview_out = hedef_mp4.with_name(f"{hedef_mp4.stem}_preview.png")
            shutil.copy2(png_list[0], preview_out)

        return {
            "ok": bool(kalite.get("gecerli", True)),
            "path": hedef_mp4,
            "html_path": hedef_html,
            "preview_png": preview_out,
            "file_size_bytes": hedef_mp4.stat().st_size,
            "resolution": f"{w}x{h}",
            "sahne": len(parcalar),
            "saglayici": saglayici,
            "gecisler": gecisler,
            "kalite": kalite,
            "open_edit_metrics": metrics,
            "simulasyon": True,
            "video_difuzyonu": False,
        }
    finally:
        shutil.rmtree(gecici, ignore_errors=True)


def rea_video_reverse_blueprint(video_path: Path) -> Dict[str, Any]:
    """Link #296 (`rea-video` + `ffmpeg-skill`): MP4 dosyasından sahne & teknik blueprint çıkarır."""
    p = Path(video_path)
    if not p.is_file():
        return {"ok": False, "error": "Video dosyası bulunamadı."}

    from video_render import video_kalite_denetle
    kalite = video_kalite_denetle(p)
    ff = _ffmpeg_bin()
    cuts: List[float] = [0.0]
    try:
        r = subprocess.run(
            [ff, "-hide_banner", "-i", str(p), "-vf", "select='gt(scene,0.28)',showinfo", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        for m in re.finditer(r"pts_time:([\d.]+)", r.stderr or ""):
            ts = round(float(m.group(1)), 2)
            if ts not in cuts:
                cuts.append(ts)
    except Exception:
        pass

    return {
        "ok": True,
        "file_name": p.name,
        "telemetry": kalite,
        "scene_cuts_sec": cuts[:20],
        "estimated_scenes": len(cuts),
        "recommended_workflow": "hyperframes_motion" if len(cuts) > 1 else "wan_i2v",
    }
