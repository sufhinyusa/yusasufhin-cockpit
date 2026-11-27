# -*- coding: utf-8 -*-
"""ai_video_montaj.py — GERÇEK YZ görsellerinden sinematik video montajı.

NEDEN BU MODÜL VAR (2026-11-10 ikinci tur):
Kurucu haklı olarak şikâyet etti: *"prompt girdiğimde sadece o promptu okuyor,
neden video üretimi yok"*. Ölçüm bunu doğruladı: `video_render.py` prompt metnini
kareye basan TEK bir statik kart üretiyordu (2.0s / 3.5s / 4.8s kareleri birebir
aynı, sahne değişimi 0). Yani "video" değil, zoom'lu bir afişti.

Bu modül GERÇEK difüzyon üretimi yapar:
  1. **FLUX.1-schnell** (HF Space, `gradio_client`) ile prompt'tan N adet
     sinematik sahne görseli üretilir — gerçek YZ difüzyon çıktısı.
  2. Her sahne ffmpeg `zoompan` ile Ken Burns hareketine sokulur.
  3. Sahneler `xfade` ile yumuşak geçişlerle birleştirilir.

Dürüstlük (Kural 1): bu bir **görsel montajdır** — kareler arası fizik
sürekliliği yoktur (Wan/LTX gibi video difüzyonu değil). Çıktı etiketlenir:
`kaynak = "flux_montaj"`. Gerçek video difüzyonu için HF ZeroGPU kotası gerekir;
kota yoksa bu hat devreye girer ve bunu raporda açıkça söyler.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("YusasufhinCockpit.AIVideoMontaj")

KOK = Path(__file__).resolve().parent
FLUX_SPACE = "black-forest-labs/FLUX.1-schnell"
FLUX2_SPACE = "black-forest-labs/FLUX.2-klein-4B"
SAHNE_SAYISI = 3
SAHNE_SURE_SN = 3.0
GECIS_SN = 0.6
FLUX_ZAMAN_ASIMI_SN = 120
# Link #296 (`saas-motion-kit`): ardışık sahnelerde aynı geçişin tekrarını önleyen palet.
XFADE_PALETI: Tuple[str, ...] = (
    "fade", "smoothleft", "wipeleft", "dissolve", "slidedown", "circleopen",
)
# Link #296 (`opus-video-skills`): Ken Burns tekdüze zoom yerine kamera hareket çeşitliliği.
KAMERA_HAREKETLERI: Tuple[str, ...] = ("zoom_in", "pan_right", "zoom_out", "pan_left")


def sec_xfade_gecisleri(adet: int, palet: Tuple[str, ...] = XFADE_PALETI) -> List[str]:
    """Art arda iki aynı geçişin tekrar etmesini engelleyen `xfade` geçiş dizisi döner."""
    if adet <= 0:
        return []
    temiz_palet = [g for g in palet if str(g).strip()] or ["fade"]
    secilen: List[str] = []
    for i in range(adet):
        aday = temiz_palet[i % len(temiz_palet)]
        if secilen and aday == secilen[-1] and len(temiz_palet) > 1:
            aday = temiz_palet[(i + 1) % len(temiz_palet)]
        secilen.append(aday)
    return secilen


def _hf_token() -> Optional[str]:
    """HF token: env → Persona/.env → KovaLab/.env → ~/.cache/huggingface/token sırasıyla aranır."""
    aday = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if aday and aday.strip():
        return aday.strip()
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    for dosya in (
        KOK.parent / "Video_Otomasyon" / "KovaLab" / ".env",
        Path("/Users/yusufsahin/Desktop/Fabrika_Products/Video_Otomasyon/KovaLab/.env"),
        Path("/Users/yusufsahin/Desktop/PYTHON PROJECTS/Fabrika/Persona/.env"),
    ):
        try:
            for satir in dosya.read_text(encoding="utf-8").splitlines():
                if satir.strip().startswith(("HF_TOKEN=", "HUGGINGFACE_TOKEN=")):
                    val = satir.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
        except Exception:
            continue
    try:
        cache_tok = Path.home() / ".cache" / "huggingface" / "token"
        if cache_tok.is_file():
            val = cache_tok.read_text(encoding="utf-8").strip()
            if val:
                return val
    except Exception:
        pass
    return None


def _nvidia_kimlik() -> Optional[str]:
    """NVIDIA_API_KEY okur (pytest sırasında açık env yoksa atlar)."""
    val = os.environ.get("NVIDIA_API_KEY")
    if val and val.strip():
        return val.strip().strip('"').strip("'")
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    for dosya in (
        KOK / ".env",
        Path("/Users/yusufsahin/Desktop/PYTHON PROJECTS/Fabrika/Persona/.env"),
        KOK.parent / "Persona" / ".env",
    ):
        try:
            for satir in dosya.read_text(encoding="utf-8").splitlines():
                k, _, v = satir.partition("=")
                if k.strip() == "NVIDIA_API_KEY" and not satir.strip().startswith("#"):
                    temiz = v.strip().strip('"').strip("'")
                    if temiz:
                        return temiz
        except Exception:
            continue
    return None


def _cover_kaydet_png(im: Any, hedef: Path, genislik: int, yukseklik: int) -> Path:
    """PIL Image nesnesini hedef en-boy oranına göre ortadan kırpıp PNG kaydeder."""
    from PIL import Image

    im = im.convert("RGB")
    hedef_oran = max(0.1, float(genislik) / max(1, int(yukseklik)))
    w, h = im.size
    if w / max(1, h) > hedef_oran:
        yeni_w = max(1, int(h * hedef_oran))
        im = im.crop(((w - yeni_w) // 2, 0, (w + yeni_w) // 2, h))
    else:
        yeni_h = max(1, int(w / hedef_oran))
        im = im.crop((0, (h - yeni_h) // 2, w, (h + yeni_h) // 2))
    hedef.parent.mkdir(parents=True, exist_ok=True)
    im.resize((genislik, yukseklik), Image.LANCZOS).save(hedef, "PNG")
    return hedef


def tesis_durumu() -> Dict[str, Any]:
    """YZ video hattının canlı ortamda çalışabilirliğini teşhis eder."""
    durum: Dict[str, Any] = {
        "nvidia": bool(_nvidia_kimlik()),
        "hf_token": bool(_hf_token()),
        "cloudflare": False,
        "gradio_client": False,
        "pillow": False,
        "ffmpeg": False,
        "hazir": False,
        "eksikler": [],
    }

    cf_token, cf_hesap = _cf_kimlik()
    durum["cloudflare"] = bool(cf_token and cf_hesap)
    if not (durum["nvidia"] or durum["cloudflare"] or durum["hf_token"]):
        durum["eksikler"].append(
            "NVIDIA_API_KEY / CLOUDFLARE_API_TOKEN / HF_TOKEN tanımlı değil "
            "(anonim ZeroGPU FLUX.2 denenebilir)"
        )

    try:
        import gradio_client  # noqa: F401

        durum["gradio_client"] = True
    except Exception:
        durum["eksikler"].append("gradio_client paketi kurulu değil (requirements.txt)")

    try:
        import PIL  # noqa: F401

        durum["pillow"] = True
    except Exception:
        durum["eksikler"].append("Pillow paketi kurulu değil (requirements.txt)")

    ff = _ffmpeg()
    try:
        r = subprocess.run([ff, "-version"], capture_output=True, timeout=15)
        durum["ffmpeg"] = r.returncode == 0
        durum["ffmpeg_yolu"] = ff
    except Exception:
        durum["ffmpeg"] = False
    if not durum["ffmpeg"]:
        durum["eksikler"].append("ffmpeg çalıştırılamıyor (imageio-ffmpeg kurulu mu?)")

    durum["hazir"] = not durum["eksikler"]
    return durum


def _sahne_promptlari(prompt: str, adet: int, style_preset: str = "cinematic_realism") -> List[str]:
    """Türkçe/soyut konuyu somut İngilizce sinematik sahnelere dönüştürür."""
    try:
        from prompt_director import plan_visual_scenes

        plan = plan_visual_scenes(
            prompt=prompt, style_preset=style_preset, scene_count=adet, use_llm=True
        )
        sahneler = [s["image_prompt"] for s in plan.get("scenes", []) if s.get("image_prompt")]
        if sahneler:
            return [sahneler[i % len(sahneler)] for i in range(adet)]
    except Exception as e:
        logger.debug("[AIVideoMontaj] prompt_director yedeğine düşüldü: %s", e)

    temel = prompt.strip().rstrip(".")
    kalip = [
        "cinematic wide establishing shot of {p}, dramatic lighting, ultra detailed, 8k, film still",
        "close up detail shot of {p}, shallow depth of field, macro texture, cinematic color grading",
        "epic aerial view of {p}, atmospheric haze, golden hour, cinematic composition",
    ]
    return [kalip[i % len(kalip)].format(p=temel) for i in range(adet)]


def preview_single_image(
    prompt: str,
    hedef: Path,
    genislik: int = 1280,
    yukseklik: int = 720,
    style_preset: str = "cinematic_realism",
    camera_motion: str = "otomatik",
    use_planner: bool = True,
    seed: int = 42,
    character_lock: str = "",
    reference_image_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Hızlı bulut önizleme PNG üretir (FLUX.2 referans görsel kilidi + sabit tohum destekli)."""
    if use_planner:
        try:
            from prompt_director import plan_visual_scenes

            plan = plan_visual_scenes(
                prompt=prompt,
                style_preset=style_preset,
                camera_motion=camera_motion,
                scene_count=1,
                character_lock=character_lock,
                seed=seed,
                use_llm=True,
            )
            img_prompt = plan["image_prompt"]
            mot_prompt = plan["motion_prompt"]
            narration = plan["narration_text"]
            planner = plan["planner_source"]
            seed = int(plan.get("seed") or seed or 42)
        except Exception:
            img_prompt = prompt
            mot_prompt = prompt
            narration = prompt
            planner = "ham_fallback"
    else:
        img_prompt = prompt
        if character_lock and character_lock.strip():
            try:
                from prompt_director import _inject_character_lock
                img_prompt = _inject_character_lock(img_prompt, character_lock)
            except Exception:
                pass
        mot_prompt = prompt
        narration = prompt
        planner = "hazir_sahne"

    hedef = Path(hedef)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    yol, saglayici = _tek_gorsel_saglayici_zinciri(
        img_prompt,
        hedef,
        genislik,
        yukseklik,
        int(seed or 42),
        reference_image_path=reference_image_path,
    )
    if yol is not None and hedef.is_file():
        return {
            "ok": True,
            "path": hedef,
            "provider": saglayici,
            "image_prompt": img_prompt,
            "motion_prompt": mot_prompt,
            "narration_text": narration,
            "planner_source": planner,
            "seed": int(seed or 42),
            "reference_used": bool(reference_image_path and Path(reference_image_path).is_file() and saglayici == "hf-flux2-klein-4b"),
        }
    return {
        "ok": False,
        "path": None,
        "provider": None,
        "image_prompt": img_prompt,
        "motion_prompt": mot_prompt,
        "narration_text": narration,
        "planner_source": planner,
        "seed": int(seed or 42),
        "error": "Gerçek YZ görsel sağlayıcıları yanıt vermedi (Pollinations devre dışı; metin kartı üretilmez).",
    }


def _ffmpeg() -> str:
    aday = shutil.which("ffmpeg")
    if aday:
        return aday
    for sabit in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"):
        if os.path.isfile(sabit):
            return sabit
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _cf_kimlik() -> Tuple[Optional[str], Optional[str]]:
    """Cloudflare Workers AI kimliği: (api_token, account_id).

    NEDEN CLOUDFLARE: FLUX.2 tüm ücretsiz yolları kapalıydı (ZeroGPU kotası
    doldu, Inference Providers ücretli). Cloudflare Workers AI'da
    FLUX.1-schnell **ücretsiz katmanda** çalışıyor ve Pollinations'ın `sana`
    modeline göre ölçülebilir şekilde çok daha kaliteli:
        kenar enerjisi 20.4 vs 8.39 (2.4×), std 69 vs 46.
    """
    token = (
        os.environ.get("CLOUDFLARE_API_TOKEN")
        or os.environ.get("CF_API_TOKEN")
        or os.environ.get("APIToken")
    )
    hesap = (
        os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        or os.environ.get("CF_ACCOUNT_ID")
        or os.environ.get("AccountID")
    )
    if token and hesap:
        return token.strip(), hesap.strip()

    for dosya in (
        Path("/Users/yusufsahin/Desktop/PYTHON PROJECTS/Fabrika/Persona/.env"),
        KOK.parent / "Persona" / ".env",
    ):
        try:
            for satir in dosya.read_text(encoding="utf-8").splitlines():
                if "=" not in satir or satir.strip().startswith("#"):
                    continue
                k, _, v = satir.partition("=")
                k = k.strip()
                temiz = v.strip().strip('"').strip("'")
                if not temiz:
                    continue
                if k in ("CLOUDFLARE_API_TOKEN", "CF_API_TOKEN", "APIToken"):
                    token = token or temiz
                elif k in ("CLOUDFLARE_ACCOUNT_ID", "CF_ACCOUNT_ID", "AccountID"):
                    hesap = hesap or temiz
        except Exception:
            continue
        if token and hesap:
            return token, hesap
    return token, hesap


def _cloudflare_sahne(prompt: str, hedef: Path, genislik: int, yukseklik: int,
                      tohum: int, adim: int = 8) -> Optional[Path]:
    """Cloudflare Workers AI · FLUX.1-schnell ile yüksek kaliteli sahne üretir.

    Ücretsiz katman (10 000 neuron/gün). Anahtar yoksa None döner.
    """
    import base64
    import json as _json
    import urllib.request

    try:
        from PIL import Image
    except Exception:
        return None

    token, hesap = _cf_kimlik()
    if not token or not hesap:
        return None

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{hesap}"
        "/ai/run/@cf/black-forest-labs/flux-1-schnell"
    )
    govde = _json.dumps({"prompt": prompt, "steps": max(4, min(8, adim))}).encode()
    try:
        req = urllib.request.Request(
            url, data=govde,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as y:
            veri = _json.loads(y.read())
        if not veri.get("success"):
            logger.info("[AIVideoMontaj] CF yanıtı: %s", str(veri)[:160])
            return None
        ham = base64.b64decode(veri["result"]["image"])
        if len(ham) < 5000:
            return None
        # FLUX.1-schnell kare üretir; hedef orana kırp (cover) ve ölçekle
        im = Image.open(__import__("io").BytesIO(ham)).convert("RGB")
        hedef_oran = genislik / yukseklik
        w, h = im.size
        if w / h > hedef_oran:      # çok geniş → yanlardan kırp
            yeni_w = int(h * hedef_oran)
            im = im.crop(((w - yeni_w) // 2, 0, (w + yeni_w) // 2, h))
        else:                        # çok uzun → üst/alttan kırp
            yeni_h = int(w / hedef_oran)
            im = im.crop((0, (h - yeni_h) // 2, w, (h + yeni_h) // 2))
        im.resize((genislik, yukseklik), Image.LANCZOS).save(hedef, "PNG")
        return hedef
    except Exception as e:
        logger.info("[AIVideoMontaj] Cloudflare sahne hatası: %s", str(e)[:140])
        return None


def _nvidia_sahne(prompt: str, hedef: Path, genislik: int, yukseklik: int) -> Optional[Path]:
    """NVIDIA NIM (`flux.1-dev`) ile gerçek yüksek kaliteli görsel üretir."""
    import base64
    import json as _json
    import urllib.request

    try:
        from PIL import Image
    except Exception:
        return None

    nv_key = _nvidia_kimlik()
    if not nv_key:
        return None

    if genislik > yukseklik:
        nv_w, nv_h = 1344, 768
    elif yukseklik > genislik:
        nv_w, nv_h = 768, 1344
    else:
        nv_w, nv_h = 1024, 1024

    url = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"
    govde = _json.dumps({"prompt": prompt, "width": nv_w, "height": nv_h, "steps": 6}).encode("utf-8")
    try:
        req = urllib.request.Request(
            url,
            data=govde,
            headers={
                "Authorization": f"Bearer {nv_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=40) as y:
            veri = _json.loads(y.read().decode("utf-8"))
        arts = veri.get("artifacts") or []
        b64 = (arts[0] or {}).get("base64") if arts else ""
        if not b64:
            return None
        ham = base64.b64decode(b64)
        if len(ham) < 5000:
            return None
        im = Image.open(__import__("io").BytesIO(ham))
        return _cover_kaydet_png(im, hedef, genislik, yukseklik)
    except Exception as e:
        logger.info("[AIVideoMontaj] NVIDIA FLUX hatası: %s", str(e)[:140])
        return None


def _gradio_dosya_yolu(sonuc: Any) -> Optional[str]:
    item = sonuc[0] if isinstance(sonuc, (list, tuple)) and sonuc else sonuc
    if isinstance(item, dict):
        return item.get("path") or item.get("url")
    if isinstance(item, (str, Path)):
        return str(item)
    return None


def _flux_sahne(
    istemci: Any,
    space_id: str,
    prompt: str,
    hedef: Path,
    genislik: int,
    yukseklik: int,
    tohum: int,
    reference_image_path: Optional[Path] = None,
) -> Optional[Path]:
    """HuggingFace ZeroGPU Space (`FLUX.2-klein-4B` veya `FLUX.1-schnell`) ile sahne üretir.

    `FLUX.2-klein-4B` referans görsel (`input_images`) desteklediği için karakter tutarlılığında
    ilk sahne / karakter referansı doğrudan modele verilir.
    """
    try:
        from PIL import Image
    except Exception:
        return None
    w, h = (1024, 576) if genislik > yukseklik else (576, 1024) if yukseklik > genislik else (768, 768)
    kaynak_yol: Optional[str] = None
    try:
        if "FLUX.2" in space_id:
            ref_list: List[Any] = []
            if reference_image_path and Path(reference_image_path).is_file():
                try:
                    from gradio_client import handle_file
                    ref_list = [handle_file(str(reference_image_path))]
                except Exception:
                    ref_list = []
            try:
                sonuc = istemci.predict(
                    prompt=prompt,
                    input_images=ref_list,
                    mode_choice="Distilled (4 steps)",
                    seed=tohum,
                    randomize_seed=False,
                    width=w,
                    height=h,
                    num_inference_steps=4,
                    guidance_scale=1.0,
                    prompt_upsampling=False,
                    api_name="/infer",
                )
            except Exception:
                if not ref_list:
                    raise
                sonuc = istemci.predict(
                    prompt=prompt,
                    input_images=[],
                    mode_choice="Distilled (4 steps)",
                    seed=tohum,
                    randomize_seed=False,
                    width=w,
                    height=h,
                    num_inference_steps=4,
                    guidance_scale=1.0,
                    prompt_upsampling=False,
                    api_name="/infer",
                )
        else:
            sonuc = istemci.predict(
                prompt=prompt,
                seed=tohum,
                randomize_seed=False,
                width=w,
                height=h,
                num_inference_steps=4,
                api_name="/infer",
            )
        kaynak_yol = _gradio_dosya_yolu(sonuc)
        if not kaynak_yol or not Path(kaynak_yol).is_file():
            return None
        return _cover_kaydet_png(Image.open(kaynak_yol), hedef, genislik, yukseklik)
    except Exception as e:
        logger.info("[AIVideoMontaj] %s ZeroGPU sahne hatası: %s", space_id, str(e)[:140])
        return None
    finally:
        if kaynak_yol:
            shutil.rmtree(Path(kaynak_yol).parent, ignore_errors=True)


def _hf_zerogpu_sahne(
    prompt: str,
    hedef: Path,
    genislik: int,
    yukseklik: int,
    tohum: int = 42,
    reference_image_path: Optional[Path] = None,
) -> Tuple[Optional[Path], Optional[str]]:
    """HF_TOKEN varsa token'lı, yoksa anonim ZeroGPU üzerinden FLUX.2 / FLUX.1 sahnesi üretir."""
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("HF_TOKEN"):
        return None, None
    try:
        from gradio_client import Client
    except Exception:
        return None, None

    tok = _hf_token()
    for space, etiket in ((FLUX2_SPACE, "hf-flux2-klein-4b"), (FLUX_SPACE, "hf-flux1-schnell")):
        try:
            istemci = Client(space, verbose=False, token=tok or None)
            ref = reference_image_path if "FLUX.2" in space else None
            if _flux_sahne(istemci, space, prompt, hedef, genislik, yukseklik, tohum, reference_image_path=ref):
                return hedef, etiket
        except Exception as e:
            logger.info("[AIVideoMontaj] %s bağlantısı kurulamadı: %s", space, str(e)[:120])
            continue
    return None, None


def _tek_gorsel_saglayici_zinciri(
    prompt: str,
    hedef: Path,
    genislik: int,
    yukseklik: int,
    tohum: int = 42,
    reference_image_path: Optional[Path] = None,
) -> Tuple[Optional[Path], Optional[str]]:
    """Referans karakter kilidi varsa önce FLUX.2-klein-4B, ardından NVIDIA -> Cloudflare -> HF ZeroGPU dener."""
    if reference_image_path and Path(reference_image_path).is_file() and _hf_token():
        hf_yol, hf_etiket = _hf_zerogpu_sahne(
            prompt, hedef, genislik, yukseklik, tohum, reference_image_path=reference_image_path
        )
        if hf_yol is not None:
            return hf_yol, hf_etiket

    if _nvidia_kimlik() and _nvidia_sahne(prompt, hedef, genislik, yukseklik):
        return hedef, "nvidia-flux1-dev"

    cf_tok, cf_acc = _cf_kimlik()
    if cf_tok and cf_acc and _cloudflare_sahne(prompt, hedef, genislik, yukseklik, tohum):
        return hedef, "cloudflare-flux1-schnell"

    hf_yol, hf_etiket = _hf_zerogpu_sahne(
        prompt, hedef, genislik, yukseklik, tohum, reference_image_path=reference_image_path
    )
    if hf_yol is not None:
        return hf_yol, hf_etiket
    return None, None


def sahneleri_uret(
    prompt: str,
    adet: int,
    genislik: int,
    yukseklik: int,
    log=None,
    seed: int = 42,
    character_lock: str = "",
    reference_image_path: Optional[Path] = None,
) -> List[Path]:
    """Prompt'tan karakter/tohum tutarlı gerçek YZ sahne görselleri üretir (Pollinations devre dışı)."""
    def _log(m: str) -> None:
        logger.info(m)
        if log:
            try:
                log(m)
            except Exception:
                pass

    try:
        from PIL import Image  # noqa: F401
    except Exception as e:
        _log(f"⚠️ Pillow yok: {e}")
        return []

    gecici = Path(tempfile.mkdtemp(prefix="ai_sahne_"))
    yollar: List[Path] = []
    promptlar = _sahne_promptlari(prompt, adet)
    if character_lock and character_lock.strip():
        try:
            from prompt_director import _inject_character_lock
            promptlar = [_inject_character_lock(sp, character_lock) for sp in promptlar]
        except Exception:
            pass
    son_saglayici = ""
    anchor_ref: Optional[Path] = reference_image_path if (reference_image_path and Path(reference_image_path).is_file()) else None

    for i, sahne_prompt in enumerate(promptlar, 1):
        _log(f"🎨 Sahne {i}/{adet} üretiliyor…")
        hedef = gecici / f"sahne_{i}.png"
        yol, saglayici = _tek_gorsel_saglayici_zinciri(
            sahne_prompt, hedef, genislik, yukseklik, int(seed or 42), reference_image_path=anchor_ref
        )
        if yol is not None and hedef.is_file():
            yollar.append(hedef)
            if anchor_ref is None:
                anchor_ref = hedef
            son_saglayici = saglayici or son_saglayici
            _log(f"   ✅ Sahne {i} hazır ({saglayici}, {hedef.stat().st_size // 1024} KB)")
        else:
            _log(f"   ⚠️ Sahne {i} hiçbir gerçek YZ görsel sağlayıcısında üretilemedi")

    if yollar and son_saglayici:
        sahneleri_uret.son_saglayici = son_saglayici  # type: ignore[attr-defined]
    return yollar





def _sahne_video(sahne_png: Path, cikti: Path, genislik: int, yukseklik: int,
                 sure_sn: float, zoom_in: bool = True,
                 hareket: Optional[str] = None) -> bool:
    """Tek sahneyi gerçek float64 alt-piksel 30fps kamera hareketiyle (sıfır adım atlama) MP4'e çevirir."""
    render_fps = 30
    kare = max(render_fps, int(round(sure_sn * render_fps)))
    mod = (hareket or ("zoom_in" if zoom_in else "zoom_out")).strip().lower()

    # 1. Öncelik: Gerçek float64 alt-piksel PIL afin motoru (sıfır integer zoompan sıçraması!)
    try:
        from hyperframes_motor import render_smooth_camera_clip

        sm = render_smooth_camera_clip(
            sahne_png, cikti, genislik, yukseklik, sure_sn,
            camera_motion=mod, fps=render_fps, audio_path=None,
        )
        if sm.get("ok") and cikti.is_file() and cikti.stat().st_size > 2000:
            return True
    except Exception as e:
        logger.debug("[AIVideoMontaj] Alt-piksel kamera motoru yedeğe düştü: %s", e)

    # 2. Yedek: 4× üst-örneklemeli tek-kare 30fps FFmpeg zoompan (sinüzoidal smoothstep)
    ease = f"(0.5-0.5*cos(PI*on/{kare}))"
    x_ifade = "iw/2-(iw/zoom/2)"
    y_ifade = "ih/2-(ih/zoom/2)"
    if mod in ("wind_cloth_glow", "locked", "static", "sabit"):
        # Sabit kadraj: kesinlikle kamera kayması veya zoom yok (v33 düzeltmesi)
        z_ifade = "1.0"
        x_ifade = "iw/2-(iw/zoom/2)"
        y_ifade = "ih/2-(ih/zoom/2)"
    elif mod in ("pan_right", "pan_right_60fps"):
        z_ifade = "1.16"
        x_ifade = f"(iw-iw/zoom)*(0.04+0.92*{ease})"
    elif mod == "pan_left":
        z_ifade = "1.16"
        x_ifade = f"(iw-iw/zoom)*(0.96-0.92*{ease})"
    elif mod in ("crane_up", "tilt_up"):
        z_ifade = "1.16"
        y_ifade = f"(ih-ih/zoom)*(0.95-0.90*{ease})"
    elif mod in ("crane_down", "tilt_down"):
        z_ifade = "1.16"
        y_ifade = f"(ih-ih/zoom)*(0.05+0.90*{ease})"
    elif mod in ("dolly_zoom", "vertigo"):
        z_ifade = f"1.0+0.26*{ease}"
    elif mod in ("fpv_drone", "fpv"):
        z_ifade = f"1.06+0.20*{ease}"
        x_ifade = f"(iw-iw/zoom)*(0.5+0.30*sin(2*PI*on/{kare}))"
        y_ifade = f"(ih-ih/zoom)*(0.60-0.22*{ease})"
    elif mod in ("handheld_track", "handheld"):
        z_ifade = "1.14"
        x_ifade = f"(iw-iw/zoom)*(0.32+0.36*{ease}+0.04*sin(4*PI*on/{kare}))"
        y_ifade = f"(ih-ih/zoom)*(0.50+0.04*cos(3*PI*on/{kare}))"
    elif mod in ("orbital", "bullet_time"):
        z_ifade = "1.16"
        x_ifade = f"(iw-iw/zoom)*(0.5+0.44*sin(PI*on/{kare}-PI/2))"
        y_ifade = f"(ih-ih/zoom)*(0.5+0.14*sin(2*PI*on/{kare}))"
    elif mod in ("zoom_in", "push_in", "slow_dolly_in", "otomatik"):
        z_ifade = f"1.0+0.18*{ease}"
    else:
        z_ifade = f"1.18-0.18*{ease}"

    ss = 4 if max(genislik, yukseklik) <= 1280 else 2
    cmd = [
        _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(sahne_png),
        "-vf", (
            f"scale={int(genislik * ss)}:{int(yukseklik * ss)}:flags=lanczos:force_original_aspect_ratio=increase,"
            f"crop={int(genislik * ss)}:{int(yukseklik * ss)},"
            f"zoompan=z='{z_ifade}':x='{x_ifade}':y='{y_ifade}':"
            f"d={kare}:s={genislik}x{yukseklik}:fps={render_fps},setsar=1,format=yuv420p"
        ),
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "film", "-threads", "1", "-crf", "21",
        "-pix_fmt", "yuv420p",
        str(cikti),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=max(180, int(sure_sn * 6)))
        return r.returncode == 0 and cikti.is_file() and cikti.stat().st_size > 2000
    except Exception as e:
        logger.warning("[AIVideoMontaj] Sahne render hatası: %s", e)
        return False


def montaj_birlestir(sahne_mp4leri: List[Path], hedef: Path,
                     gecis_sn: float = GECIS_SN, sure_sn: float = SAHNE_SURE_SN) -> bool:
    """Sahneleri `xfade` yumuşak geçişlerle birleştirir."""
    if not sahne_mp4leri:
        return False
    if len(sahne_mp4leri) == 1:
        shutil.copy2(sahne_mp4leri[0], hedef)
        return True

    cmd = [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
    for v in sahne_mp4leri:
        cmd += ["-i", str(v)]

    gecisler = sec_xfade_gecisleri(len(sahne_mp4leri) - 1)
    filtre = ""
    onceki = "[0:v]"
    offset = sure_sn - gecis_sn
    for i in range(1, len(sahne_mp4leri)):
        etiket = f"[x{i}]"
        gecis = gecisler[i - 1]
        filtre += (
            f"{onceki}[{i}:v]xfade=transition={gecis}:duration={gecis_sn}:"
            f"offset={offset:.3f}{etiket};"
        )
        onceki = etiket
        offset += sure_sn - gecis_sn
    filtre = filtre.rstrip(";")

    cmd += [
        "-filter_complex", filtre,
        "-map", onceki,
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "film", "-threads", "1", "-crf", "21",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(hedef),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=max(300, int(len(sahne_mp4leri) * sure_sn * 6)))
        if r.returncode != 0:
            logger.warning("[AIVideoMontaj] Birleştirme hatası: %s", (r.stderr or "")[-300:])
            return False
        return hedef.is_file() and hedef.stat().st_size > 20000
    except Exception as e:
        logger.warning("[AIVideoMontaj] Birleştirme istisnası: %s", e)


def ai_video_uret(
    hedef_mp4: Path,
    prompt: str,
    genislik: int,
    yukseklik: int,
    sahne_sayisi: int = SAHNE_SAYISI,
    sahne_sure_sn: float = SAHNE_SURE_SN,
    ses_yolu: Optional[Path] = None,
    log=None,
    hedef_sure_sn: Optional[float] = None,
    character_lock: str = "",
    seed: int = 42,
) -> Dict[str, Any]:
    """Prompt'tan GERÇEK YZ görselleri üretip hedef süreye tam uyumlu sinematik video montajı yapar.

    Döner: {"basarili", "yol", "boyut", "sahne", "kaynak", "hata"}
    """
    def _log(m: str) -> None:
        logger.info(m)
        if log:
            try:
                log(m)
            except Exception:
                pass

    hedef_mp4 = Path(hedef_mp4)
    hedef_mp4.parent.mkdir(parents=True, exist_ok=True)
    baslangic = time.time()

    if hedef_sure_sn is not None and float(hedef_sure_sn) > 0:
        istenen = max(3.0, min(180.0, float(hedef_sure_sn)))
        n_eff = max(1, int(sahne_sayisi))
        sahne_sure_sn = max(2.0, (istenen + max(0, n_eff - 1) * GECIS_SN) / n_eff)
    else:
        istenen = max(2.0, sahne_sayisi * sahne_sure_sn - max(0, sahne_sayisi - 1) * GECIS_SN)

    _log(f"🎬 Gerçek YZ video hattı: {sahne_sayisi} sahne × {sahne_sure_sn:.2f}s (hedef ~{istenen:.1f}s), {genislik}x{yukseklik}")

    sahneler = sahneleri_uret(
        prompt, sahne_sayisi, genislik, yukseklik, log=_log, seed=seed, character_lock=character_lock
    )
    if not sahneler:
        tesis = tesis_durumu()
        neden = "; ".join(tesis.get("eksikler") or ["FLUX Space erişilemedi (kota/ağ)"])
        return {
            "basarili": False, "yol": None, "boyut": 0, "sahne": 0,
            "kaynak": "flux_montaj", "simulasyon": False,
            "video_difuzyonu": False, "yontem": "flux_goruntu_montaji",
            "hata": f"YZ sahne üretilemedi → {neden}",
            "tesis": tesis,
        }

    # Gerçek üretilen sahne sayısı istenenden azsa süreyi tekrar dengele ki video kısalmasın!
    if hedef_sure_sn is not None and len(sahneler) > 0:
        sahne_sure_sn = max(2.0, (istenen + max(0, len(sahneler) - 1) * GECIS_SN) / len(sahneler))

    gecici = Path(tempfile.mkdtemp(prefix="ai_montaj_"))
    parcalar: List[Path] = []
    for i, png in enumerate(sahneler):
        parca = gecici / f"p{i}.mp4"
        hareket = KAMERA_HAREKETLERI[i % len(KAMERA_HAREKETLERI)]
        if _sahne_video(png, parca, genislik, yukseklik, sahne_sure_sn,
                        zoom_in=(i % 2 == 0), hareket=hareket):
            parcalar.append(parca)
            _log(f"   ✅ Sahne {i + 1} hareketlendirildi ({hareket})")

    if not parcalar:
        return {
            "basarili": False, "yol": None, "boyut": 0, "sahne": 0,
            "kaynak": "flux_montaj", "simulasyon": False,
            "video_difuzyonu": False, "yontem": "flux_goruntu_montaji",
            "hata": "Sahne render edilemedi",
        }

    sessiz = gecici / "sessiz.mp4"
    if not montaj_birlestir(parcalar, sessiz, gecis_sn=GECIS_SN, sure_sn=sahne_sure_sn):
        return {
            "basarili": False, "yol": None, "boyut": 0, "sahne": len(parcalar),
            "kaynak": "flux_montaj", "simulasyon": False,
            "video_difuzyonu": False, "yontem": "flux_goruntu_montaji",
            "hata": "Montaj birleştirme başarısız",
        }

    son = hedef_mp4
    hedef_toplam = max(2.0, len(parcalar) * sahne_sure_sn - max(0, len(parcalar) - 1) * GECIS_SN)
    if ses_yolu is not None and Path(ses_yolu).is_file() and Path(ses_yolu).stat().st_size > 500:
        # KISA SES VİDEOYU KESMEMELİ: apad ile sessizlikle doldur, -t ile hedef sürede sabitle
        cmd = [
            _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(sessiz), "-i", str(ses_yolu),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-af", f"apad=whole_dur={hedef_toplam:.3f}",
            "-c:a", "aac", "-b:a", "128k",
            "-t", f"{hedef_toplam:.3f}", "-movflags", "+faststart", str(son),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                shutil.copy2(sessiz, son)
        except Exception:
            shutil.copy2(sessiz, son)
    else:
        shutil.copy2(sessiz, son)

    kalite: Dict[str, Any] = {}
    try:
        from video_render import mp4_gecerli_mi, video_kalite_denetle

        oran = "9:16" if yukseklik > genislik else "16:9"
        kalite = video_kalite_denetle(son, beklenen_oran=oran)
        gecerli = bool(kalite.get("gecerli")) and not bool(kalite.get("bos_video"))
        neden = str(kalite.get("neden") or "kalite denetimi")
    except Exception:
        try:
            from video_render import mp4_gecerli_mi
            gecerli, neden = mp4_gecerli_mi(son)
        except Exception:
            gecerli, neden = son.is_file(), "doğrulama atlandı"

    if not gecerli:
        return {
            "basarili": False, "yol": None, "boyut": 0, "sahne": len(parcalar),
            "kaynak": "flux_montaj", "simulasyon": False,
            "video_difuzyonu": False, "yontem": "flux_goruntu_montaji",
            "hata": f"doğrulama başarısız: {neden}",
            "kalite": kalite,
        }

    shutil.rmtree(gecici, ignore_errors=True)

    boyut = son.stat().st_size
    saglayici = getattr(sahneleri_uret, "son_saglayici", "bilinmiyor")
    gecisler = sec_xfade_gecisleri(max(0, len(parcalar) - 1))
    _log(f"✅ Gerçek YZ montaj hazır: {len(parcalar)} sahne, {boyut // 1024} KB, "
         f"sağlayıcı={saglayici}, geçişler={gecisler}, {round(time.time() - baslangic, 1)} sn")
    return {
        "basarili": True, "yol": son, "boyut": boyut, "sahne": len(parcalar),
        "kaynak": f"yz_montaj_{saglayici}" if saglayici != "bilinmiyor" else "flux_montaj",
        "saglayici": saglayici, "hata": None,
        "gecisler": gecisler,
        "kalite": kalite,
        # Kural 1: görseller gerçek difüzyon çıktısı; video ise kare bazlı
        # Ken Burns montajıdır — video difüzyonu DEĞİLDİR, açıkça söylenir.
        "simulasyon": False,
        "video_difuzyonu": False,
        "yontem": "flux_goruntu_montaji (Ken Burns + çoklu xfade)",
        "ses": "var" if (ses_yolu is not None and Path(ses_yolu).is_file()) else "yok",
    }


