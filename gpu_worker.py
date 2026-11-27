# -*- coding: utf-8 -*-
"""gpu_worker.py — Kaggle / Colab GPU işçisi: GERÇEK FLUX.2 görsel + Wan2.1 video difüzyonu.

NEDEN BU MODÜL VAR
Kurucu talebi: *"kaggle ya da colabe kurabiliriz flux.2 yi ayrıca wan2.1 kurabiliriz
resimden videoya çevirebilir"*. Canlı sitedeki hat ücretsiz API'lere bağlıydı ve
FLUX.2'ye erişilemiyordu (ZeroGPU kotası dolu, Inference Providers ücretli).
Bu işçi modelleri **kendi GPU'sunda yerel** çalıştırır: kota yok, ücret yok.

DOĞRULANMIŞ MODELLER (HF API ile ölçüldü, 2026-11-11)
    black-forest-labs/FLUX.2-klein-4B   3.88 B param  gated=False  → bf16 ≈ 7.8 GB
    Wan-AI/Wan2.1-T2V-1.3B              1.42 B param  gated=False  → bf16 ≈ 2.8 GB
    Wan-AI/Wan2.1-I2V-14B-480P         16.39 B param  gated=False  → bf16 ≈ 33 GB

VRAM GERÇEĞİ (dürüstlük — Kural 1)
    * Kaggle T4 / Colab T4 = 16 GB. FLUX.2-klein-4B ve Wan2.1-T2V-1.3B sığar.
    * Wan2.1-I2V-14B-480P bf16'da SIĞMAZ → `enable_sequential_cpu_offload()`
      zorunludur ve 5 sn klip 10–25 dk sürer. Sığmıyorsa dürüst hata verilir,
      sahte çıktı üretilmez.
    * İşçi hangi modeli gerçekten çalıştırdığını `engine` alanında bildirir.

PROTOKOL (mevcut sunucu uçları — yeni uç icat edilmedi)
    POST /api/worker/heartbeat   → kayıt
    GET  /api/worker/claim       → iş al
    POST /api/worker/progress    → ilerleme / failed=true hata bildirimi
    POST /api/worker/upload      → MP4 veya PNG yükle (multipart, media_type)

KİMLİK DOĞRULAMA
    Tüm işçi çağrıları `Authorization: Bearer <key>` ve `X-Worker-Key: <key>`
    başlıklarını taşır. Anahtar `--token` veya `FABRIKA_WORKER_KEY` /
    `FABRIKA_TOKEN` ortam değişkeninden gelir; loglara yazılmaz.

DESTEKLENEN MODLAR
    remotion_cinema / blender_wan / opus_canvas / viral_shorts → Wan2.1 T2V
    wan_i2v / burc_video / hibrit → Wan2.1 I2V (görsel varsa) + ses/altyazı mux
    burc_video → FLUX.2 keyframe → Wan2.1 I2V; keyframe üretilemezse T2V
    flux2_resim → yalnız FLUX.2 PNG (site onayı için media_type="image")
    flux2 → FLUX.2 PNG → 3 sn MP4

KULLANIM (Kaggle / Colab hücresi)
    !git clone https://github.com/sufhinyusa/yusasufhin-cockpit.git
    %cd yusasufhin-cockpit
    !pip -q install -r requirements-gpu.txt
    !python gpu_worker.py --server https://yusasufhin.com --token <WORKER_KEY> --tek-seferlik
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

# --- Doğrulanmış model kimlikleri (HF API: gated=False) ---
# DİKKAT (2026-11-11 düzeltmesi): diffusers kütüphanesi `model_index.json`
# ister. `Wan-AI/Wan2.1-T2V-1.3B` ve `Wan-AI/Wan2.1-I2V-14B-480P` depolarında
# bu dosya YOK (ölçüldü) → pipeline yüklenemez. `-Diffusers` ekli sürümler
# gerekir. Bu hata kurucunun Kaggle notebook'u karşılaştırılırken yakalandı.
FLUX2_KLEIN = "black-forest-labs/FLUX.2-klein-4B"
Z_IMAGE_TURBO = "Tongyi-MAI/Z-Image-Turbo"
SDXL_TURBO = "stabilityai/sdxl-turbo"
REALVIS_XL = "SG161222/RealVisXL_V4.0"
ANIMAGINE_XL = "cagliostrolab/animagine-xl-3.1"

WAN21_T2V = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
WAN21_I2V = "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers"
WAN21_VACE = "Wan-AI/Wan2.1-VACE-1.3B-diffusers"
WAN22_TI2V = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
LTX_VIDEO = "Lightricks/LTX-Video"
COGVIDEOX_I2V = "THUDM/CogVideoX-5b-I2V"
SVD_XT = "stabilityai/stable-video-diffusion-img2vid-xt"

# Ücretsiz Yerel AI Müzik Modelleri (Kaggle/Colab T4 15 GB doğrulandı)
# ACE-Step 1.5 (MIT, 5B DiT, 48 kHz stereo, Türkçe/çok dilli vokal + söz + Cover/Repaint, 240 sn)
ACESTEP_TURBO = "ACE-Step/acestep-v15-xl-turbo-diffusers"
ACESTEP_SFT = "ACE-Step/acestep-v15-xl-sft-diffusers"
# Meta MusicGen (hızlı enstrümantal yedek, 32 kHz gerçek stereo)
MUSICGEN_STEREO_MEDIUM = "facebook/musicgen-stereo-medium"
MUSICGEN_MEDIUM = "facebook/musicgen-medium"
MUSICGEN_SMALL = "facebook/musicgen-small"

IMAGE_MODEL_REPOS: Dict[str, str] = {
    "flux2": FLUX2_KLEIN,
    "flux2-klein": FLUX2_KLEIN,
    "black-forest-labs/flux.2-klein-4b": FLUX2_KLEIN,
    "z-image-turbo": Z_IMAGE_TURBO,
    "tongyi-mai/z-image-turbo": Z_IMAGE_TURBO,
    "sdxl-turbo": SDXL_TURBO,
    "stabilityai/sdxl-turbo": SDXL_TURBO,
    "realvis-xl": REALVIS_XL,
    "sg161222/realvisxl_v4.0": REALVIS_XL,
    "animagine-xl": ANIMAGINE_XL,
    "cagliostrolab/animagine-xl-3.1": ANIMAGINE_XL,
}

I2V_MODEL_REPOS: Dict[str, str] = {
    "wan2.1-vace-1.3b": WAN21_VACE,
    "wan2.1_vace": WAN21_VACE,
    "vace": WAN21_VACE,
    "wan-ai/wan2.1-vace-1.3b-diffusers": WAN21_VACE,
    "wan2.1_i2v": WAN21_I2V,
    "wan2.1-i2v-14b": WAN21_I2V,
    "wan-ai/wan2.1-i2v-14b-480p-diffusers": WAN21_I2V,
    "wan2.2-ti2v-5b": WAN22_TI2V,
    "wan2.2_ti2v": WAN22_TI2V,
    "wan-ai/wan2.2-ti2v-5b-diffusers": WAN22_TI2V,
    "ltx-video": LTX_VIDEO,
    "ltx_video": LTX_VIDEO,
    "lightricks/ltx-video": LTX_VIDEO,
    "cogvideox-5b-i2v": COGVIDEOX_I2V,
    "cogvideox_i2v": COGVIDEOX_I2V,
    "thudm/cogvideox-5b-i2v": COGVIDEOX_I2V,
    "svd-xt": SVD_XT,
    "svd_xt": SVD_XT,
    "stabilityai/stable-video-diffusion-img2vid-xt": SVD_XT,
    "wan2.1-t2v-1.3b": WAN21_T2V,
    "wan2.1_t2v": WAN21_T2V,
    "wan-ai/wan2.1-t2v-1.3b-diffusers": WAN21_T2V,
}

VARSAYILAN_SUNUCU = "https://yusasufhin.com"
ISCI_DOSYA = Path(__file__).resolve().parent / "gpu_worker_durum.json"


# -----------------------------------------------------------------------------
# 1. GPU / ORTAM
# -----------------------------------------------------------------------------
def gpu_bilgisi() -> Dict[str, Any]:
    """Gerçek GPU bilgisini nvidia-smi ve torch ile sorgular (uydurma yok).

    Dual GPU (ör. Kaggle T4 x2) desteği: tüm satırları okur, VRAM'leri toplar,
    gpu_count ekler. Tek GPU'da da çalışır.
    """
    bilgi: Dict[str, Any] = {
        "var": False, "ad": None, "vram_gb": 0.0, "kaynak": None, "gpu_count": 0
    }
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0 and r.stdout.strip():
            gpu_list = []
            toplam_vram_mb = 0
            for satir in r.stdout.strip().splitlines():
                ad, _, mb = satir.partition(",")
                ad = ad.strip()
                try:
                    vram_mb = float(mb.strip())
                except ValueError:
                    continue
                gpu_list.append({"ad": ad, "vram_gb": round(vram_mb / 1024, 1)})
                toplam_vram_mb += vram_mb
            if gpu_list:
                # İlk GPU adını ana ad olarak kullan, çoklu ise "+N more" ekle
                ana_ad = gpu_list[0]["ad"]
                if len(gpu_list) > 1:
                    ana_ad += f" +{len(gpu_list)-1} more"
                bilgi.update({
                    "var": True,
                    "ad": ana_ad,
                    "vram_gb": round(toplam_vram_mb / 1024, 1),
                    "gpu_count": len(gpu_list),
                    "gpu_list": gpu_list,
                    "kaynak": "nvidia-smi",
                })
                return bilgi
    except Exception:
        pass
    try:
        import torch

        if torch.cuda.is_available():
            count = torch.cuda.device_count()
            gpu_list = []
            toplam_vram = 0
            for i in range(count):
                prop = torch.cuda.get_device_properties(i)
                vram_gb = round(prop.total_memory / 1024**3, 1)
                gpu_list.append({"ad": prop.name, "vram_gb": vram_gb})
                toplam_vram += prop.total_memory
            if gpu_list:
                ana_ad = gpu_list[0]["ad"]
                if len(gpu_list) > 1:
                    ana_ad += f" +{len(gpu_list)-1} more"
                bilgi.update({
                    "var": True,
                    "ad": ana_ad,
                    "vram_gb": round(toplam_vram / 1024**3, 1),
                    "gpu_count": len(gpu_list),
                    "gpu_list": gpu_list,
                    "kaynak": "torch",
                })
    except Exception:
        pass
    return bilgi


def _dtype():
    """bf16 varsa bf16 (T4'te yok → fp16), yoksa fp32."""
    import torch

    if torch.cuda.is_available() and torch.cuda.is_bf16_supported():
        return torch.bfloat16
    if torch.cuda.is_available():
        return torch.float16
    return torch.float32


def _bosalt() -> None:
    """VRAM'i boşalt (modeller arası geçişte zorunlu — 16 GB sınırı)."""
    try:
        import gc

        import torch

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass


_EXTRA_IMG_PIPE = None
_EXTRA_IMG_KEY = ""
_EXTRA_VID_PIPE = None
_EXTRA_VID_KEY = ""
_EXTRA_T2V_PIPE = None
_EXTRA_T2V_KEY = ""
_WAN_VACE = None
_MUZIK_PIPE = None
_MUZIK_KEY = ""
_ACESTEP_PIPE = None
_ACESTEP_KEY = ""


def _muzik_cache_temizle() -> None:
    """ACE-Step / MusicGen boru hatlarını RAM/VRAM'den bırakır (FLUX/Wan ile VRAM paylaşımı için)."""
    global _MUZIK_PIPE, _MUZIK_KEY, _ACESTEP_PIPE, _ACESTEP_KEY
    _MUZIK_PIPE = None
    _MUZIK_KEY = ""
    _ACESTEP_PIPE = None
    _ACESTEP_KEY = ""
    _bosalt()


def _gorsel_cache_temizle() -> None:
    """Görsel boru hatlarını RAM/VRAM'den bırakır (I2V aşamasından önce T4 güvenliği)."""
    global _FLUX_PIPE, _EXTRA_IMG_PIPE, _EXTRA_IMG_KEY
    _FLUX_PIPE = None
    _EXTRA_IMG_PIPE = None
    _EXTRA_IMG_KEY = ""
    _muzik_cache_temizle()
    _bosalt()


def _video_cache_temizle() -> None:
    """Video boru hatlarını RAM/VRAM'den bırakır (farklı modele geçerken)."""
    global _WAN_T2V, _WAN_I2V, _WAN_VACE, _EXTRA_VID_PIPE, _EXTRA_VID_KEY, _EXTRA_T2V_PIPE, _EXTRA_T2V_KEY
    _WAN_T2V = None
    _WAN_I2V = None
    _WAN_VACE = None
    _EXTRA_VID_PIPE = None
    _EXTRA_VID_KEY = ""
    _EXTRA_T2V_PIPE = None
    _EXTRA_T2V_KEY = ""
    _muzik_cache_temizle()
    _bosalt()


def _gorsel_modeli_coz(anahtar: Optional[str]) -> str:
    k = str(anahtar or "").strip().lower()
    return IMAGE_MODEL_REPOS.get(k, FLUX2_KLEIN)


def _i2v_modeli_coz(anahtar: Optional[str]) -> str:
    k = str(anahtar or "").strip().lower()
    return I2V_MODEL_REPOS.get(k, WAN21_I2V)


def _hizala(val: int, kat: int = 16, alt_sinir: int = 256) -> int:
    return max(alt_sinir, (int(val) // kat) * kat)


# -----------------------------------------------------------------------------
# 2. FLUX.2-klein-4B — GERÇEK görsel difüzyonu (3.88 B, T4'e sığar)
# -----------------------------------------------------------------------------
_FLUX_PIPE = None


def flux2_yukle(log=print):
    """FLUX.2-klein-4B boru hattını yükler (tek sefer, sonra cache).

    ÖLÇÜLMÜŞ BULGULAR (2026-11-11, Kaggle T4 15.0 GB):
    * `Flux2Pipeline` YANLIŞ — o FLUX.2-dev (32B, Mistral3) için. klein-4B
      Qwen3 text encoder kullanıyor → "Expected types for text_encoder:
      Mistral3ForConditionalGeneration, got Qwen3ForCausalLM".
    * Doğru yol: `DiffusionPipeline` (auto-detect `Flux2KleinPipeline`) +
      `dtype=torch.bfloat16` (`torch_dtype` DEĞİL) + `enable_model_cpu_offload()`.
    * `device_map="cuda"` T4'te OOM veriyor (model kartı ~13 GB diyor ama
      gerçekte 14.39 GB'a çıkıyor, 14.56 GB kartta yer kalmıyor).
    * CPU offload ile ÇALIŞIYOR: 1024x1024, kenar enerjisi 33.7
      (FLUX.1-schnell 20.4, Pollinations 8.4). Süre GPU/offload durumuna göre
      değişir; sabit bir "14 dk" iddiası yoktur.
    """
    global _FLUX_PIPE
    if _FLUX_PIPE is not None:
        return _FLUX_PIPE

    import torch
    from diffusers import DiffusionPipeline

    log(f"⏳ {FLUX2_KLEIN} indiriliyor/yükleniyor…")
    pipe = DiffusionPipeline.from_pretrained(
        FLUX2_KLEIN, dtype=torch.bfloat16, low_cpu_mem_usage=True
    )
    # T4 15 GB'da device_map="cuda" OOM veriyor — CPU offload ZORUNLU
    pipe.enable_model_cpu_offload()
    vae = getattr(pipe, "vae", None)
    if vae is not None and hasattr(vae, "enable_slicing"):
        vae.enable_slicing()
    _FLUX_PIPE = pipe
    log(f"✅ FLUX.2-klein-4B hazır ({type(pipe).__name__}, CPU offload)")
    return pipe



def flux2_gorsel_uret(prompt: str, genislik: int, yukseklik: int,
                      adim: int = 4, tohum: int = 42,
                      ref_gorsel: Optional[Path] = None, log=print) -> Path:
    """Prompt'tan GERÇEK FLUX.2-klein-4B görseli üretir (seed + çoklu referans karakter kilidi destekli).

    `Flux2KleinPipeline` distilled 4 adımlı bir modeldir ve `image` parametresiyle
    karakter portre referansı alarak yüz/kıyafet tutarlılığını koruyabilir.
    """
    import torch

    pipe = flux2_yukle(log=log)
    # Kenar uzunlukları 16'nın katı olmalı
    w = max(256, (genislik // 16) * 16)
    h = max(256, (yukseklik // 16) * 16)
    uid = uuid.uuid4().hex[:8]
    hedef = Path(tempfile.gettempdir()) / f"flux2_{uid}.png"

    sig = inspect.signature(pipe.__call__)
    sig_params = set(sig.parameters.keys())
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    kwargs: Dict[str, Any] = {"prompt": prompt, "width": w, "height": h}
    if has_var_kw or "num_inference_steps" in sig_params:
        kwargs["num_inference_steps"] = max(1, min(12, int(adim or 4)))
    if has_var_kw or "generator" in sig_params:
        kwargs["generator"] = torch.Generator(device="cpu").manual_seed(int(tohum or 42))

    ref_kullanildi = False
    ref_pil = None
    if ref_gorsel is not None and Path(ref_gorsel).is_file() and (has_var_kw or "image" in sig_params):
        from PIL import Image
        ref_pil = Image.open(ref_gorsel).convert("RGB")
        kwargs["image"] = [ref_pil]
        ref_kullanildi = True

    log(
        f"🎨 FLUX.2 difüzyon: {w}x{h} (seed={tohum}, "
        f"karakter_ref={'EVET' if ref_kullanildi else 'yok'}, CPU offload)"
    )
    try:
        sonuc = pipe(**kwargs)
    except TypeError:
        if ref_pil is not None:
            # Bazı tekil referans sarmalayıcıları liste yerine tek PIL.Image bekler
            kwargs["image"] = ref_pil
            sonuc = pipe(**kwargs)
        else:
            raise
    sonuc.images[0].save(hedef, "PNG")
    log(f"✅ Görsel hazır: {hedef.stat().st_size // 1024} KB")
    return hedef


def secimli_gorsel_uret(prompt: str, model_key: Optional[str], genislik: int, yukseklik: int,
                        neg_prompt: str = "", adim: Optional[int] = None,
                        tohum: int = 42, ref_gorsel: Optional[Path] = None, log=print) -> Path:
    """Seçilen görsel modeliyle (FLUX.2, Z-Image-Turbo, SDXL-Turbo, RealVisXL, AnimagineXL) PNG üretir."""
    global _EXTRA_IMG_PIPE, _EXTRA_IMG_KEY
    repo = _gorsel_modeli_coz(model_key)
    if repo == FLUX2_KLEIN:
        return flux2_gorsel_uret(prompt, genislik, yukseklik,
                                 adim=adim or 4, tohum=tohum, ref_gorsel=ref_gorsel, log=log)

    import torch
    from diffusers import DiffusionPipeline

    w = _hizala(genislik, 16)
    h = _hizala(yukseklik, 16)

    if _EXTRA_IMG_PIPE is None or _EXTRA_IMG_KEY != repo:
        _gorsel_cache_temizle()
        _video_cache_temizle()
        log(f"⏳ Görsel modeli yükleniyor: {repo}…")
        dt = torch.bfloat16 if (repo == Z_IMAGE_TURBO and torch.cuda.is_available() and torch.cuda.is_bf16_supported()) else _dtype()
        pipe = DiffusionPipeline.from_pretrained(repo, torch_dtype=dt, low_cpu_mem_usage=True)
        pipe.enable_model_cpu_offload()
        vae = getattr(pipe, "vae", None)
        if vae is not None and hasattr(vae, "enable_slicing"):
            vae.enable_slicing()
        _EXTRA_IMG_PIPE = pipe
        _EXTRA_IMG_KEY = repo
        log(f"✅ Görsel modeli hazır: {repo} ({type(pipe).__name__})")

    pipe = _EXTRA_IMG_PIPE
    if repo == Z_IMAGE_TURBO:
        steps, cfg = int(adim or 8), 0.0
    elif repo == SDXL_TURBO:
        steps, cfg = int(adim or 4), 0.0
    else:
        steps, cfg = int(adim or 24), 6.5

    kwargs: Dict[str, Any] = {
        "prompt": prompt,
        "width": w,
        "height": h,
        "num_inference_steps": steps,
        "guidance_scale": cfg,
        "generator": torch.Generator(device="cpu").manual_seed(int(tohum)),
    }
    if neg_prompt and cfg > 0.0:
        kwargs["negative_prompt"] = neg_prompt

    uid = uuid.uuid4().hex[:8]
    hedef = Path(tempfile.gettempdir()) / f"img_{uid}.png"
    log(f"🎨 Görsel difüzyon ({repo}): {w}x{h}, {steps} adım")
    pipe(**kwargs).images[0].save(hedef, "PNG")
    log(f"✅ Anahtar kare hazır: {hedef.stat().st_size // 1024} KB")
    return hedef



# -----------------------------------------------------------------------------
# 3. Wan2.1 — GERÇEK video difüzyonu (T2V 1.3B + I2V 14B)
# -----------------------------------------------------------------------------
_WAN_T2V = None
_WAN_I2V = None


def wan21_t2v_yukle(log=print):
    """Wan2.1-T2V-1.3B (1.42 B) — 16 GB T4'e sığar.

    ÖLÇÜLMÜŞ OOM (2026-11-11, Kaggle T4 15.0 GB):
    832x480 / 33 kare / 25 adım → `CUDA out of memory. Tried to allocate
    8.81 GiB ... 2.09 GiB is free`. Sebep: VAE decode tüm videoyu tek seferde
    açıyor. Çözüm: `vae.enable_slicing()` + `vae.enable_tiling()` ZORUNLU.
    """
    global _WAN_T2V
    if _WAN_T2V is not None:
        return _WAN_T2V
    import torch
    from diffusers import AutoencoderKLWan, WanPipeline

    log(f"⏳ {WAN21_T2V} yükleniyor…")
    vae = AutoencoderKLWan.from_pretrained(
        WAN21_T2V, subfolder="vae", torch_dtype=torch.float32
    )
    pipe = WanPipeline.from_pretrained(
        WAN21_T2V, vae=vae, torch_dtype=_dtype(), low_cpu_mem_usage=True
    )
    pipe.enable_model_cpu_offload()
    # OOM koruması — bu iki satır olmadan 832x480/33 kare T4'te patlıyor
    pipe.vae.enable_slicing()
    pipe.vae.enable_tiling()
    _WAN_T2V = pipe
    log("✅ Wan2.1-T2V-1.3B hazır (VAE slicing+tiling açık)")
    return pipe



def wan21_i2v_yukle(log=print):
    """Wan2.1-I2V-14B-480P (16.39 B) — 16 GB T4'e NF4 4-bit ile sığdırılır.

    TEKNİK (kurucunun Kaggle notebook'undan port edildi, 2026-11-11):
    bf16'da 33 GB isteyen 14B modeli `bitsandbytes` NF4 4-bit kuantizasyon ile
    ~10 GB'a iner ve T4 16 GB'a **offload'suz** sığar. Bu, `sequential_cpu_offload`
    yaklaşımından kat kat hızlıdır (o yöntem 5 sn klip için 10–25 dk harcıyordu).
    bitsandbytes yoksa veya CUDA yoksa güvenli yola (bf16 + sequential offload)
    düşülür ve bu durum log'a yazılır.
    """
    global _WAN_I2V
    if _WAN_I2V is not None:
        return _WAN_I2V

    import torch
    from diffusers import AutoencoderKLWan, WanImageToVideoPipeline

    # VAE her durumda fp32 (fp16 VAE bu modelde bozulma üretiyor)
    vae = AutoencoderKLWan.from_pretrained(
        WAN21_I2V, subfolder="vae", torch_dtype=torch.float32
    )

    nf4_kullanildi = False
    if torch.cuda.is_available() and torch.cuda.get_device_properties(0).total_memory < 24 * 1024**3:
        try:
            from diffusers import BitsAndBytesConfig as DiffusersBnB
            from diffusers import WanTransformer3DModel

            log(f"⏳ {WAN21_I2V} yükleniyor (NF4 4-bit — T4 için)…")
            transformer = WanTransformer3DModel.from_pretrained(
                WAN21_I2V,
                subfolder="transformer",
                quantization_config=DiffusersBnB(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.float16,
                ),
                torch_dtype=torch.float16,
                low_cpu_mem_usage=True,
            )
            pipe = WanImageToVideoPipeline.from_pretrained(
                WAN21_I2V,
                transformer=transformer,
                vae=vae,
                torch_dtype=torch.float16,
                low_cpu_mem_usage=True,
            )
            pipe.to("cuda")
            nf4_kullanildi = True
            log("✅ Wan2.1-I2V-14B NF4 4-bit hazır (offload YOK — hızlı yol)")
        except Exception as e:
            log(f"⚠️ NF4 yüklenemedi ({type(e).__name__}: {str(e)[:120]}) — "
                f"bf16 + sequential offload'a düşülüyor (yavaş)")
            _bosalt()

    if not nf4_kullanildi:
        log(f"⏳ {WAN21_I2V} yükleniyor (bf16 + sequential offload — yavaş)…")
        pipe = WanImageToVideoPipeline.from_pretrained(
            WAN21_I2V, vae=vae, torch_dtype=_dtype(), low_cpu_mem_usage=True
        )
        pipe.enable_sequential_cpu_offload()
        pipe.vae.enable_slicing()

    _WAN_I2V = pipe
    pipe._fabrika_nf4 = nf4_kullanildi  # type: ignore[attr-defined]
    return pipe




def _kare_sayisi_hesapla(sure_sn: float, fps: int = 16) -> int:
    """Wan2.1 kare kuralı: 4k+1, 17..81 aralığı, 16 fps varsayımı.

    Wan pipeline'ı `(kare - 1) % 4 == 0` ister. Geçersiz/sıfır sürelerde bile
    en az 17 kare döner; böylece boş video üretilmez.
    """
    try:
        sn = max(0.0, float(sure_sn))
    except (TypeError, ValueError):
        sn = 0.0
    kare = int(max(17, min(81, round(sn * fps))))
    return ((kare - 1) // 4) * 4 + 1


def _videoyu_yaz(sonuc: Any, hedef: Path, fps: int = 16) -> Path:
    """Difüzyon sonucunu MP4'e yazar; boş kare listesini dürüst hataya çevirir."""
    from diffusers.utils import export_to_video

    kareler = getattr(sonuc, "frames", None) or []
    if not kareler or not kareler[0]:
        raise RuntimeError("Difüzyon boş kare listesi döndürdü — video yazılmadı")
    export_to_video(kareler[0], str(hedef), fps=fps)
    if not hedef.is_file() or hedef.stat().st_size == 0:
        raise RuntimeError(f"Video dosyası yazılamadı: {hedef}")
    return hedef


def wan21_video_uret(prompt: str, genislik: int, yukseklik: int,
                     sure_sn: float = 3.0, adim: int = 25,
                     tohum: int = 42, log=print) -> Path:
    """Wan2.1-T2V-1.3B ile GERÇEK metinden-videoya difüzyonu. Döner: MP4 yolu."""
    import torch

    pipe = wan21_t2v_yukle(log=log)
    # Wan 16 fps ve 4kare+1 yapısı ister; 480p sınıfı için 480/832 sınırı
    w = max(256, (genislik // 16) * 16)
    h = max(256, (yukseklik // 16) * 16)
    kare = _kare_sayisi_hesapla(sure_sn)

    log(f"🎬 Wan2.1 T2V: {w}x{h}, {kare} kare @16fps, {adim} adım")
    uretici = torch.Generator(device="cpu").manual_seed(int(tohum))
    sonuc = pipe(
        prompt=prompt,
        height=h,
        width=w,
        num_frames=kare,
        num_inference_steps=max(4, min(50, int(adim))),
        guidance_scale=5.0,
        generator=uretici,
    )
    uid = uuid.uuid4().hex[:8]
    hedef = Path(tempfile.gettempdir()) / f"wan21_{uid}.mp4"
    _videoyu_yaz(sonuc, hedef, fps=16)
    log(f"✅ Video hazır: {hedef.stat().st_size // 1024} KB")
    return hedef


def wan21_i2v_uret(gorsel_yolu: Path, prompt: str, genislik: int, yukseklik: int,
                   sure_sn: float = 3.0, adim: int = 20,
                   tohum: int = 42, log=print) -> Path:
    """Wan2.1-I2V-14B-480P ile GERÇEK görselden-videoya difüzyonu."""
    import torch
    from diffusers.utils import load_image

    pipe = wan21_i2v_yukle(log=log)
    gorsel = load_image(str(gorsel_yolu)).resize(
        (max(256, (genislik // 16) * 16), max(256, (yukseklik // 16) * 16))
    )
    kare = _kare_sayisi_hesapla(sure_sn)

    log(f"🎬 Wan2.1 I2V: {gorsel.size}, {kare} kare, {adim} adım (yavaş)")
    uretici = torch.Generator(device="cpu").manual_seed(int(tohum))
    sonuc = pipe(
        image=gorsel,
        prompt=prompt,
        height=gorsel.size[1],
        width=gorsel.size[0],
        num_frames=kare,
        num_inference_steps=max(4, min(50, int(adim))),
        guidance_scale=5.0,
        generator=uretici,
    )
    uid = uuid.uuid4().hex[:8]
    hedef = Path(tempfile.gettempdir()) / f"wan21_i2v_{uid}.mp4"
    _videoyu_yaz(sonuc, hedef, fps=16)
    log(f"✅ I2V video hazır: {hedef.stat().st_size // 1024} KB")
    return hedef


def _extra_vid_pipe_al(repo: str, log=print):
    """Seçili I2V model boru hattını tek cache slotunda yükler (16GB T4 uyumlu)."""
    global _EXTRA_VID_PIPE, _EXTRA_VID_KEY
    if _EXTRA_VID_PIPE is not None and _EXTRA_VID_KEY == repo:
        return _EXTRA_VID_PIPE

    import torch

    _gorsel_cache_temizle()
    _video_cache_temizle()
    log(f"⏳ I2V modeli yükleniyor: {repo}…")

    if repo == WAN22_TI2V:
        from diffusers import AutoencoderKLWan, WanImageToVideoPipeline

        vae = AutoencoderKLWan.from_pretrained(repo, subfolder="vae", torch_dtype=torch.float32)
        pipe = WanImageToVideoPipeline.from_pretrained(repo, vae=vae, torch_dtype=_dtype(), low_cpu_mem_usage=True)
        pipe.enable_model_cpu_offload()
        pipe.vae.enable_slicing()
        pipe.vae.enable_tiling()
    elif repo == LTX_VIDEO:
        from diffusers import LTXImageToVideoPipeline

        dt = torch.bfloat16 if (torch.cuda.is_available() and torch.cuda.is_bf16_supported()) else torch.float16
        pipe = LTXImageToVideoPipeline.from_pretrained(repo, torch_dtype=dt, low_cpu_mem_usage=True)
        pipe.enable_model_cpu_offload()
        if hasattr(pipe.vae, "enable_tiling"):
            pipe.vae.enable_tiling()
    elif repo == COGVIDEOX_I2V:
        from diffusers import CogVideoXImageToVideoPipeline

        pipe = CogVideoXImageToVideoPipeline.from_pretrained(repo, torch_dtype=torch.float16, low_cpu_mem_usage=True)
        pipe.enable_sequential_cpu_offload()
        pipe.vae.enable_slicing()
        pipe.vae.enable_tiling()
    elif repo == SVD_XT:
        from diffusers import StableVideoDiffusionPipeline

        pipe = StableVideoDiffusionPipeline.from_pretrained(repo, torch_dtype=torch.float16, low_cpu_mem_usage=True)
        pipe.enable_model_cpu_offload()
    else:
        raise ValueError(f"Desteklenmeyen ek I2V modeli: {repo}")

    _EXTRA_VID_PIPE = pipe
    _EXTRA_VID_KEY = repo
    log(f"✅ I2V modeli hazır: {repo} ({type(pipe).__name__})")
    return pipe


_I2V_TEK_GECIS_MAX_SN: Dict[str, float] = {
    WAN21_VACE: 5.0,
    WAN21_I2V: 5.0,
    WAN22_TI2V: 3.3,
    LTX_VIDEO: 4.0,
    COGVIDEOX_I2V: 6.0,
    SVD_XT: 3.5,
}
_I2V_MODEL_FPS: Dict[str, int] = {
    WAN21_VACE: 16,
    WAN21_I2V: 16,
    WAN22_TI2V: 24,
    LTX_VIDEO: 24,
    COGVIDEOX_I2V: 8,
    SVD_XT: 7,
}


def wan21_vace_yukle(log=print):
    """Wan2.1-VACE-1.3B (Tutarlı Karakter R2V + İlk/Son Kare FLF2V — T4 15 GB uyumlu)."""
    global _WAN_VACE
    if _WAN_VACE is not None:
        return _WAN_VACE

    import torch
    from diffusers import AutoencoderKLWan
    from diffusers.schedulers.scheduling_unipc_multistep import UniPCMultistepScheduler
    try:
        from diffusers import WanVACEPipeline
    except ImportError as exc:
        raise RuntimeError(
            "WanVACEPipeline kurulu diffusers sürümünde yok. "
            "Kaggle hücresinde: pip install -U git+https://github.com/huggingface/diffusers.git"
        ) from exc

    _gorsel_cache_temizle()
    _video_cache_temizle()
    log(f"⏳ {WAN21_VACE} yükleniyor (CPU offload + VAE slicing/tiling)…")
    vae = AutoencoderKLWan.from_pretrained(WAN21_VACE, subfolder="vae", torch_dtype=torch.float32)
    pipe = WanVACEPipeline.from_pretrained(
        WAN21_VACE, vae=vae, torch_dtype=_dtype(), low_cpu_mem_usage=True
    )
    pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config, flow_shift=3.0)
    pipe.enable_model_cpu_offload()
    pipe.vae.enable_slicing()
    pipe.vae.enable_tiling()
    _WAN_VACE = pipe
    log("✅ Wan2.1-VACE-1.3B hazır (R2V tutarlı karakter + FLF2V geçiş)")
    return pipe


def wan21_vace_uret(
    prompt: str,
    genislik: int,
    yukseklik: int,
    *,
    ilk_kare: Optional[Path] = None,
    son_kare: Optional[Path] = None,
    ref_gorseller: Optional[list[Path]] = None,
    neg_prompt: str = "",
    sure_sn: float = 5.0,
    adim: int = 30,
    tohum: int = 42,
    log=print,
) -> Path:
    """Wan2.1-VACE-1.3B ile Tutarlı Karakter R2V, İlk+Son Kare FLF2V veya Karakter-Kilitli I2V üretir."""
    import torch
    from PIL import Image

    pipe = wan21_vace_yukle(log=log)
    w, h = _hizala(genislik, 16), _hizala(yukseklik, 16)
    kare = _kare_sayisi_hesapla(sure_sn, fps=16)

    video_frames = None
    mask_frames = None
    if ilk_kare is not None and Path(ilk_kare).is_file():
        first_pil = Image.open(ilk_kare).convert("RGB").resize((w, h), Image.Resampling.LANCZOS)
        gray = Image.new("RGB", (w, h), (128, 128, 128))
        mask_black = Image.new("L", (w, h), 0)
        mask_white = Image.new("L", (w, h), 255)
        if son_kare is not None and Path(son_kare).is_file():
            last_pil = Image.open(son_kare).convert("RGB").resize((w, h), Image.Resampling.LANCZOS)
            video_frames = [first_pil] + [gray] * (kare - 2) + [last_pil]
            mask_frames = [mask_black] + [mask_white] * (kare - 2) + [mask_black]
            mod_etiketi = "FLF2V (İlk+Son Kare)"
        else:
            video_frames = [first_pil] + [gray] * (kare - 1)
            mask_frames = [mask_black] + [mask_white] * (kare - 1)
            mod_etiketi = "VACE-I2V"
    else:
        mod_etiketi = "VACE-R2V (Tutarlı Karakter)"

    ref_pils = None
    if ref_gorseller:
        valid_refs = [Image.open(p).convert("RGB") for p in ref_gorseller if p is not None and Path(p).is_file()]
        if valid_refs:
            ref_pils = valid_refs

    if video_frames is None and not ref_pils:
        # Saf VACE-T2V: tüm kareler gri + tüm maskeler beyaz (255=üret) → her diffusers sürümünde kararlı
        gray = Image.new("RGB", (w, h), (128, 128, 128))
        mask_white = Image.new("L", (w, h), 255)
        video_frames = [gray] * kare
        mask_frames = [mask_white] * kare
        mod_etiketi = "VACE-T2V"

    varsayilan_neg = (
        "blurry, distorted face, flickering artifacts, low quality, text, watermark, static frozen frame"
    )
    uretici = torch.Generator(device="cpu").manual_seed(int(tohum or 42))
    uid = uuid.uuid4().hex[:8]
    hedef = Path(tempfile.gettempdir()) / f"vace_{uid}.mp4"
    log(
        f"🎬 Wan2.1-VACE [{mod_etiketi}]: {w}x{h}, {kare} kare, {adim} adım, "
        f"ref={len(ref_pils or [])}, seed={tohum}"
    )
    vace_kwargs: Dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": neg_prompt or varsayilan_neg,
        "height": h,
        "width": w,
        "num_frames": kare,
        "num_inference_steps": max(12, min(50, int(adim or 30))),
        "guidance_scale": 5.0,
        "generator": uretici,
    }
    if video_frames is not None:
        vace_kwargs["video"] = video_frames
    if mask_frames is not None:
        vace_kwargs["mask"] = mask_frames
    if ref_pils is not None:
        vace_kwargs["reference_images"] = ref_pils
    sonuc = pipe(**vace_kwargs)
    return _videoyu_yaz(sonuc, hedef, fps=16)


def secimli_t2v_uret(
    prompt: str,
    model_key: Optional[str],
    genislik: int,
    yukseklik: int,
    *,
    neg_prompt: str = "",
    sure_sn: float = 5.0,
    adim: int = 25,
    tohum: int = 42,
    ref_gorseller: Optional[list[Path]] = None,
    log=print,
) -> Path:
    """Doğrudan T2V için seçili video modelini (Wan2.2-TI2V-5B, Wan2.1-VACE, LTX-Video, Wan2.1-T2V-1.3B) çalıştırır."""
    global _EXTRA_T2V_PIPE, _EXTRA_T2V_KEY
    repo = _i2v_modeli_coz(model_key) if model_key else WAN21_T2V

    if repo == WAN21_VACE:
        return wan21_vace_uret(
            prompt, genislik, yukseklik,
            ref_gorseller=ref_gorseller, neg_prompt=neg_prompt,
            sure_sn=sure_sn, adim=adim, tohum=tohum, log=log,
        )

    if repo == WAN22_TI2V:
        import torch
        from diffusers import AutoencoderKLWan, WanPipeline

        if _EXTRA_T2V_PIPE is None or _EXTRA_T2V_KEY != WAN22_TI2V:
            _gorsel_cache_temizle()
            _video_cache_temizle()
            log(f"⏳ {WAN22_TI2V} (WanPipeline T2V) yükleniyor…")
            vae = AutoencoderKLWan.from_pretrained(WAN22_TI2V, subfolder="vae", torch_dtype=torch.float32)
            pipe = WanPipeline.from_pretrained(WAN22_TI2V, vae=vae, torch_dtype=_dtype(), low_cpu_mem_usage=True)
            pipe.enable_model_cpu_offload()
            pipe.vae.enable_slicing()
            pipe.vae.enable_tiling()
            _EXTRA_T2V_PIPE, _EXTRA_T2V_KEY = pipe, WAN22_TI2V
        w, h = _hizala(genislik, 32), _hizala(yukseklik, 32)
        kare = _kare_sayisi_hesapla(sure_sn, fps=24)
        uretici = torch.Generator(device="cpu").manual_seed(int(tohum or 42))
        hedef = Path(tempfile.gettempdir()) / f"wan22_t2v_{uuid.uuid4().hex[:8]}.mp4"
        varsayilan_neg = "blurry, deformed, low quality, flickering artifacts, text, watermark, static"
        log(f"🎬 Wan2.2-TI2V-5B T2V: {w}x{h}, {kare} kare, {adim} adım")
        sonuc = _EXTRA_T2V_PIPE(
            prompt=prompt, negative_prompt=neg_prompt or varsayilan_neg,
            height=h, width=w, num_frames=kare,
            num_inference_steps=max(12, min(40, int(adim))), guidance_scale=5.0,
            generator=uretici,
        )
        return _videoyu_yaz(sonuc, hedef, fps=24)

    if repo == LTX_VIDEO:
        import torch
        from diffusers import LTXPipeline

        if _EXTRA_T2V_PIPE is None or _EXTRA_T2V_KEY != LTX_VIDEO:
            _gorsel_cache_temizle()
            _video_cache_temizle()
            log(f"⏳ {LTX_VIDEO} (LTXPipeline T2V) yükleniyor…")
            dt = torch.bfloat16 if (torch.cuda.is_available() and torch.cuda.is_bf16_supported()) else torch.float16
            pipe = LTXPipeline.from_pretrained(LTX_VIDEO, torch_dtype=dt, low_cpu_mem_usage=True)
            pipe.enable_model_cpu_offload()
            if hasattr(pipe.vae, "enable_tiling"):
                pipe.vae.enable_tiling()
            _EXTRA_T2V_PIPE, _EXTRA_T2V_KEY = pipe, LTX_VIDEO
        w, h = _hizala(genislik, 32), _hizala(yukseklik, 32)
        kare = max(17, min(97, ((int(round(max(2.0, sure_sn) * 24)) - 1) // 8) * 8 + 1))
        uretici = torch.Generator(device="cpu").manual_seed(int(tohum or 42))
        hedef = Path(tempfile.gettempdir()) / f"ltx_t2v_{uuid.uuid4().hex[:8]}.mp4"
        log(f"🎬 LTX-Video T2V: {w}x{h}, {kare} kare, {adim} adım")
        sonuc = _EXTRA_T2V_PIPE(
            prompt=prompt, negative_prompt=neg_prompt or None,
            height=h, width=w, num_frames=kare,
            num_inference_steps=max(12, min(40, int(adim))), guidance_scale=3.0,
            generator=uretici,
        )
        return _videoyu_yaz(sonuc, hedef, fps=24)

    return wan21_video_uret(prompt, genislik, yukseklik, sure_sn=sure_sn, adim=adim, tohum=tohum, log=log)


def _i2v_segment_planla(sure_sn: float, tek_gecis_max_sn: float = 5.0, max_segment: int = 6) -> list[float]:
    """İstenen süre tek GPU geçişini aştığında (ör. 10 sn > 5 sn) son-kare zincirleme segment sürelerini böler."""
    hedef = max(1.5, min(30.0, float(sure_sn or 5.0)))
    sinir = max(1.5, float(tek_gecis_max_sn or 5.0))
    if hedef <= sinir + 0.2:
        return [round(hedef, 2)]
    adet = min(max_segment, max(2, int(-(-hedef // sinir))))
    parca = round(min(sinir, hedef / adet), 2)
    parcalar = [parca] * adet
    # Toplam hedefin biraz üstünde/eşit kalmasını sağla (concat sonrası -t ile tam kesilir)
    if sum(parcalar) < hedef - 0.1 and len(parcalar) < max_segment:
        parcalar.append(round(max(1.5, min(sinir, hedef - sum(parcalar))), 2))
    return parcalar


def _son_kare_cikar(video_yol: Path, hedef_png: Path) -> Path:
    """Bir segment MP4'ünün son karesini PNG olarak çıkarır (karakter tutarlılığı için)."""
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.08", "-i", str(video_yol),
         "-vframes", "1", "-q:v", "2", str(hedef_png)],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0 or not hedef_png.is_file() or hedef_png.stat().st_size == 0:
        raise RuntimeError(f"Son kare çıkarılamadı: {(r.stderr or '')[-160:]}")
    return hedef_png


def _klipleri_zincirle(klipler: list[Path], hedef_mp4: Path,
                       hedef_sure_sn: Optional[float] = None, fps: int = 16) -> Path:
    """Son-kare zincirleme ile üretilen I2V segmentlerini tek sürekli MP4'te birleştirir."""
    if not klipler:
        raise RuntimeError("Birleştirilecek I2V segmenti yok")
    if len(klipler) == 1:
        if hedef_sure_sn and hedef_sure_sn > 0:
            r = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(klipler[0]),
                 "-t", f"{hedef_sure_sn:.3f}", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(hedef_mp4)],
                capture_output=True, text=True, timeout=300,
            )
            if r.returncode == 0 and hedef_mp4.is_file():
                return hedef_mp4
        shutil.copy2(klipler[0], hedef_mp4)
        return hedef_mp4

    tmp_dir = Path(tempfile.mkdtemp(prefix="gpu_chain_"))
    try:
        norm_paths: list[Path] = []
        for idx, k in enumerate(klipler):
            n_out = tmp_dir / f"seg_{idx}.mp4"
            rn = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(k),
                 "-r", str(max(8, int(fps))), "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "20", "-pix_fmt", "yuv420p", "-an", str(n_out)],
                capture_output=True, text=True, timeout=300,
            )
            if rn.returncode != 0 or not n_out.is_file():
                raise RuntimeError(f"Segment normalize hatası: {(rn.stderr or '')[-160:]}")
            norm_paths.append(n_out)
        liste = tmp_dir / "concat.txt"
        liste.write_text("\n".join(f"file '{p.as_posix()}'" for p in norm_paths), encoding="utf-8")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(liste)]
        if hedef_sure_sn and hedef_sure_sn > 0:
            cmd += ["-t", f"{hedef_sure_sn:.3f}"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(hedef_mp4)]
        r2 = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r2.returncode != 0 or not hedef_mp4.is_file():
            raise RuntimeError(f"Zincir concat hatası: {(r2.stderr or '')[-160:]}")
        return hedef_mp4
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _tek_gecis_i2v_uret(
    gorsel_yolu: Path,
    prompt: str,
    repo: str,
    genislik: int,
    yukseklik: int,
    neg_prompt: str = "",
    sure_sn: float = 4.0,
    adim: int = 24,
    tohum: int = 42,
    log=print,
) -> Path:
    """Seçilen I2V modeliyle tek geçişlik gerçek video difüzyonu çalıştırır."""
    if repo == WAN21_VACE:
        return wan21_vace_uret(
            prompt, genislik, yukseklik,
            ilk_kare=gorsel_yolu, neg_prompt=neg_prompt,
            sure_sn=sure_sn, adim=adim, tohum=tohum, log=log,
        )

    if repo == WAN21_I2V:
        _gorsel_cache_temizle()
        return wan21_i2v_uret(gorsel_yolu, prompt, genislik, yukseklik,
                              sure_sn=sure_sn, adim=adim, tohum=tohum, log=log)

    import torch
    from diffusers.utils import load_image

    pipe = _extra_vid_pipe_al(repo, log=log)
    uretici = torch.Generator(device="cpu").manual_seed(int(tohum))
    uid = uuid.uuid4().hex[:8]
    hedef = Path(tempfile.gettempdir()) / f"i2v_{uid}.mp4"
    dikey = yukseklik > genislik

    if repo == WAN22_TI2V:
        w, h = _hizala(genislik, 32), _hizala(yukseklik, 32)
        kare = _kare_sayisi_hesapla(sure_sn, fps=24)
        gorsel = load_image(str(gorsel_yolu)).resize((w, h))
        log(f"🎬 Wan2.2 TI2V-5B I2V: {w}x{h}, {kare} kare, {adim} adım")
        sonuc = pipe(
            image=gorsel, prompt=prompt, negative_prompt=neg_prompt or None,
            height=h, width=w, num_frames=kare,
            num_inference_steps=max(8, min(40, int(adim))), guidance_scale=5.0,
            generator=uretici,
        )
        return _videoyu_yaz(sonuc, hedef, fps=24)

    if repo == LTX_VIDEO:
        w, h = _hizala(max(genislik, 512 if not dikey else 384), 32), _hizala(max(yukseklik, 320 if not dikey else 512), 32)
        k = max(25, min(97, int(round(max(2.0, sure_sn) * 24))))
        kare = ((k - 1) // 8) * 8 + 1
        gorsel = load_image(str(gorsel_yolu)).resize((w, h))
        log(f"🎬 LTX-Video I2V: {w}x{h}, {kare} kare @24fps, {adim} adım")
        sonuc = pipe(
            image=gorsel, prompt=prompt, negative_prompt=neg_prompt or "worst quality, blurry, jittery",
            width=w, height=h, num_frames=kare, frame_rate=24,
            num_inference_steps=max(12, min(40, int(adim))), guidance_scale=3.0,
            generator=uretici,
        )
        return _videoyu_yaz(sonuc, hedef, fps=24)

    if repo == COGVIDEOX_I2V:
        from PIL import ImageOps

        # CogVideoX-5b-I2V RoPE boyut kısıtı: 720x480, en çok 49 kare (Oran bozulmaması için fit)
        gorsel = ImageOps.fit(load_image(str(gorsel_yolu)), (720, 480))
        kare = max(17, min(49, int(round(max(2.0, sure_sn) * 8))))
        log(f"🎬 CogVideoX-5B I2V: 720x480, {kare} kare @8fps, {adim} adım")
        sonuc = pipe(
            image=gorsel, prompt=prompt, negative_prompt=neg_prompt or None,
            height=480, width=720, num_frames=kare,
            num_inference_steps=max(15, min(50, int(adim))), guidance_scale=6.0,
            use_dynamic_cfg=True, generator=uretici,
        )
        return _videoyu_yaz(sonuc, hedef, fps=8)

    # SVD-XT (genişlik/yükseklik 64 katı)
    w, h = (320, 512) if dikey else (512, 320)
    gorsel = load_image(str(gorsel_yolu)).resize((w, h))
    log(f"🎬 SVD-XT I2V: {w}x{h}, 25 kare @7fps")
    sonuc = pipe(
        image=gorsel, width=w, height=h, num_frames=25, fps=7,
        motion_bucket_id=127, noise_aug_strength=0.02, decode_chunk_size=4,
        generator=uretici,
    )
    return _videoyu_yaz(sonuc, hedef, fps=7)


def secimli_i2v_uret(gorsel_yolu: Path, prompt: str, model_key: Optional[str],
                     genislik: int, yukseklik: int, neg_prompt: str = "",
                     sure_sn: float = 4.0, adim: int = 24,
                     tohum: int = 42, log=print) -> Path:
    """Seçilen I2V modeliyle video üretir; süre modelin tek geçiş sınırını aşarsa son-kare zincirleme uygular."""
    repo = _i2v_modeli_coz(model_key)
    if repo == WAN21_T2V:
        _gorsel_cache_temizle()
        return wan21_video_uret(prompt, genislik, yukseklik,
                                sure_sn=sure_sn, adim=adim, tohum=tohum, log=log)

    tek_max = _I2V_TEK_GECIS_MAX_SN.get(repo, 5.0)
    segmentler = _i2v_segment_planla(sure_sn, tek_max)
    if len(segmentler) == 1:
        return _tek_gecis_i2v_uret(
            gorsel_yolu, prompt, repo, genislik, yukseklik,
            neg_prompt=neg_prompt, sure_sn=segmentler[0], adim=adim, tohum=tohum, log=log,
        )

    log(f"🔗 Uzun video ({sure_sn:.1f}s > {tek_max:.1f}s): {len(segmentler)} segment son-kare I2V zinciri başlatılıyor…")
    parcalar: list[Path] = []
    gecici_kareler: list[Path] = []
    aktif_gorsel = gorsel_yolu
    try:
        for idx, seg_sn in enumerate(segmentler):
            log(f"   🎞️ Segment {idx + 1}/{len(segmentler)} ({seg_sn:.1f}s)…")
            parca = _tek_gecis_i2v_uret(
                aktif_gorsel, prompt, repo, genislik, yukseklik,
                neg_prompt=neg_prompt, sure_sn=seg_sn, adim=adim,
                tohum=int(tohum) + idx, log=log,
            )
            parcalar.append(parca)
            if idx + 1 < len(segmentler):
                son_png = Path(tempfile.gettempdir()) / f"lastframe_{uuid.uuid4().hex[:8]}.png"
                _son_kare_cikar(parca, son_png)
                gecici_kareler.append(son_png)
                aktif_gorsel = son_png

        hedef = Path(tempfile.gettempdir()) / f"i2v_chain_{uuid.uuid4().hex[:8]}.mp4"
        fps = _I2V_MODEL_FPS.get(repo, 16)
        cikti = _klipleri_zincirle(parcalar, hedef, hedef_sure_sn=sure_sn, fps=fps)
        log(f"✅ Zincirli I2V video hazır: {cikti.stat().st_size // 1024} KB (~{sure_sn:.1f}s, {len(parcalar)} segment)")
        return cikti
    finally:
        for p in gecici_kareler:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        for p in parcalar:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


# -----------------------------------------------------------------------------
# 4b. SUNO SEVİYESİ YEREL AI MÜZİK — ACE-Step 1.5 (Vokal+Söz) & MusicGen Stereo
# -----------------------------------------------------------------------------
def _ses_tensor_yukle(yol: Path, hedef_sr: int = 48000):
    """Referans ses dosyasını (WAV/MP3/FLAC/OGG) hedef örnekleme hızında (2, N) float32 tensor yapar."""
    import torch

    kaynak = Path(yol).resolve()
    if not kaynak.is_file():
        raise FileNotFoundError(f"Referans ses dosyası bulunamadı: {kaynak}")
    tmp_wav = Path(tempfile.gettempdir()) / f"ref_48k_{uuid.uuid4().hex[:8]}.wav"
    err_log = Path(tempfile.gettempdir()) / f"ref_err_{uuid.uuid4().hex[:8]}.log"
    try:
        with err_log.open("wb") as err_fh:
            r = subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", f"file:{kaynak}",
                 "-ac", "2", "-ar", str(int(hedef_sr)), "-f", "wav", "-c:a", "pcm_s16le", str(tmp_wav)],
                stdout=subprocess.DEVNULL, stderr=err_fh, timeout=120,
            )
        if r.returncode != 0 or not tmp_wav.is_file():
            err_tail = err_log.read_text(encoding="utf-8", errors="ignore")[-240:] if err_log.is_file() else ""
            raise RuntimeError(f"Referans ses dönüştürülemedi: {err_tail}")
        try:
            import soundfile as sf
            data, _ = sf.read(str(tmp_wav), dtype="float32", always_2d=True)  # (N, 2)
            return torch.from_numpy(data.T.copy()).float()
        except Exception:
            import wave
            with wave.open(str(tmp_wav), "rb") as wf:
                raw = wf.readframes(wf.getnframes())
            arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            arr = arr.reshape(-1, 2).T
            return torch.from_numpy(arr.copy()).float()
    finally:
        tmp_wav.unlink(missing_ok=True)
        err_log.unlink(missing_ok=True)


def _stereo_wav_yaz(audio_cs: np.ndarray, sample_rate: int, hedef_yol: Path, log=print) -> Path:
    """(channels, samples) float32 [-1, 1] dizisini 16-bit stereo WAV olarak yazar."""
    arr = np.asarray(audio_cs, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[None, :]
    if arr.shape[0] == 1:
        arr = np.repeat(arr, 2, axis=0)
    elif arr.shape[0] > 2:
        arr = arr[:2, :]
    peak = float(np.max(np.abs(arr))) if arr.size else 0.0
    if peak > 0.99:
        arr = arr * (0.98 / peak)
    try:
        import soundfile as sf
        sf.write(str(hedef_yol), arr.T, int(sample_rate), subtype="PCM_16")
        return hedef_yol
    except Exception as exc_sf:
        log(f"⚠️ soundfile WAV yazımı başarısız ({type(exc_sf).__name__}), scipy/wave yedeğine geçiliyor…")
    pcm = np.ascontiguousarray(np.clip(arr.T * 32767.0, -32768, 32767).astype(np.int16))
    try:
        from scipy.io.wavfile import write as wav_write
        wav_write(str(hedef_yol), int(sample_rate), pcm)
        return hedef_yol
    except Exception as exc_sp:
        log(f"⚠️ scipy WAV yazımı başarısız ({type(exc_sp).__name__}), stdlib wave yedeğine geçiliyor…")
        import wave
        with wave.open(str(hedef_yol), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(int(sample_rate))
            wf.writeframes(pcm.tobytes())
        return hedef_yol


def acestep_muzik_uret(
    prompt: str,
    *,
    lyrics: str = "",
    instrumental: bool = False,
    vocal_language: str = "tr",
    sure_sn: float = 60.0,
    bpm: Optional[int] = None,
    key_scale: str = "",
    time_signature: str = "",
    music_task: str = "text2music",
    ref_audio_path: Optional[Path] = None,
    audio_cover_strength: float = 0.85,
    repaint_start: Optional[float] = None,
    repaint_end: Optional[float] = None,
    tohum: int = 42,
    variant: str = "turbo",
    hedef_yol: Optional[Path] = None,
    bildirim_cb=None,
    log=print,
) -> Path:
    """ACE-Step 1.5 XL Turbo (MIT) ile 48 kHz stereo vokal+sözlü veya enstrümantal tam şarkı üretir."""
    global _ACESTEP_PIPE, _ACESTEP_KEY
    import torch

    def _ilerleme(pct: int, mesaj: str) -> None:
        log(mesaj)
        if callable(bildirim_cb):
            try:
                bildirim_cb(pct, mesaj)
            except Exception:
                pass

    try:
        from diffusers import AceStepPipeline
    except ImportError as exc:
        raise RuntimeError(
            "AceStepPipeline kurulu diffusers sürümünde bulunamadı. "
            "Kaggle hücresinde güncelleyin: pip install -U git+https://github.com/huggingface/diffusers.git"
        ) from exc

    # T4 (SM 7.5, <=16 GB VRAM) tespiti: Turbo + sequential CPU offload ile OOM önlenir
    is_low_vram_t4 = False
    if torch.cuda.is_available():
        try:
            major, _ = torch.cuda.get_device_capability(0)
            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            is_low_vram_t4 = (major < 8) or (vram_gb < 18.0)
        except Exception:
            is_low_vram_t4 = True

    repo = ACESTEP_SFT if ("sft" in str(variant or "").lower() and not is_low_vram_t4) else ACESTEP_TURBO
    is_turbo = repo == ACESTEP_TURBO

    if _ACESTEP_PIPE is None or _ACESTEP_KEY != repo:
        _gorsel_cache_temizle()
        _video_cache_temizle()
        _muzik_cache_temizle()
        offload_mod = "sequential CPU offload (T4 16GB güvenlik)" if is_low_vram_t4 else "model CPU offload"
        _ilerleme(18, f"⏳ ACE-Step 1.5 yükleniyor: {repo} ({offload_mod} + VAE tiling)…")
        dt = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        pipe = AceStepPipeline.from_pretrained(repo, torch_dtype=dt, low_cpu_mem_usage=True)
        if torch.cuda.is_available():
            if is_low_vram_t4 and hasattr(pipe, "enable_sequential_cpu_offload"):
                pipe.enable_sequential_cpu_offload()
            else:
                pipe.enable_model_cpu_offload()
        vae = getattr(pipe, "vae", None)
        if vae is not None and hasattr(vae, "enable_tiling"):
            vae.enable_tiling()
        _ACESTEP_PIPE = pipe
        _ACESTEP_KEY = repo
        _ilerleme(40, f"✅ ACE-Step 1.5 hazır ({repo}, 48 kHz stereo)")

    _bosalt()
    pipe = _ACESTEP_PIPE
    sr = int(getattr(pipe, "sample_rate", 48000) or 48000)
    try:
        sn = max(10.0, min(240.0, float(sure_sn or 60.0)))
    except (TypeError, ValueError):
        sn = 60.0

    clean_lyrics = "[Instrumental]" if (instrumental or not str(lyrics or "").strip()) else str(lyrics).strip()[:4096]
    lang = str(vocal_language or "tr").strip().lower() or "unknown"
    task_map = {"extend": "complete"}
    eff_task = task_map.get(str(music_task or "text2music").strip().lower(), str(music_task or "text2music").strip().lower())

    sig = inspect.signature(pipe.__call__)
    sig_params = set(sig.parameters.keys())
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())

    # Kural 1 (Dürüstlük): Cover / Repaint / Extend için referans ses + diffusers parametresi zorunludur!
    if eff_task in ("cover", "repaint", "complete") and (ref_audio_path is None or not Path(ref_audio_path).is_file()):
        raise ValueError(f"ACE-Step '{eff_task}' görevi için geçerli bir referans ses dosyası (ref_audio_path) zorunludur.")
    if eff_task == "cover" and not (has_var_kw or "reference_audio" in sig_params):
        raise RuntimeError("Kurulu diffusers AceStepPipeline sürümü 'cover' (reference_audio) parametresini desteklemiyor.")
    if eff_task in ("repaint", "complete") and not (has_var_kw or "src_audio" in sig_params):
        raise RuntimeError(f"Kurulu diffusers AceStepPipeline sürümü '{eff_task}' (src_audio) parametresini desteklemiyor.")

    kwargs: Dict[str, Any] = {
        "prompt": str(prompt or "").strip()[:512],
        "lyrics": clean_lyrics,
        "audio_duration": sn,
        "vocal_language": lang,
        "num_inference_steps": 8 if is_turbo else 32,
        "guidance_scale": 1.0 if is_turbo else 7.0,
        "shift": 3.0,
        "generator": torch.Generator(device="cpu").manual_seed(int(tohum or 42)),
        "task_type": eff_task,
    }
    if bpm:
        kwargs["bpm"] = max(40, min(240, int(bpm)))
    if str(key_scale or "").strip():
        kwargs["keyscale"] = str(key_scale).strip()[:32]
    if str(time_signature or "").strip():
        kwargs["timesignature"] = str(time_signature).strip()[:12]

    if ref_audio_path is not None and Path(ref_audio_path).is_file():
        ref_tensor = _ses_tensor_yukle(Path(ref_audio_path), hedef_sr=sr)
        if eff_task == "cover":
            kwargs["reference_audio"] = ref_tensor
            kwargs["audio_cover_strength"] = max(0.0, min(1.0, float(audio_cover_strength)))
        else:
            kwargs["src_audio"] = ref_tensor
            if repaint_start is not None:
                kwargs["repainting_start"] = max(0.0, float(repaint_start))
            if repaint_end is not None:
                kwargs["repainting_end"] = max(0.0, float(repaint_end))

    call_kwargs = kwargs if has_var_kw else {k: v for k, v in kwargs.items() if k in sig_params}

    _ilerleme(
        55,
        f"🎤 ACE-Step 1.5 üretimi: {sn:.0f}s · dil={lang} · görev={eff_task} · "
        f"{'Enstrümantal' if clean_lyrics == '[Instrumental]' else 'Vokal+Söz'} (@{sr}Hz)",
    )
    with torch.inference_mode():
        sonuc = pipe(**call_kwargs)

    audios = getattr(sonuc, "audios", None)
    if audios is None or len(audios) == 0:
        raise RuntimeError("ACE-Step 1.5 boş ses çıktısı döndürdü")
    audio_t = audios[0]
    audio_np = audio_t.detach().cpu().float().numpy() if hasattr(audio_t, "detach") else np.asarray(audio_t, dtype=np.float32)

    if hedef_yol is None:
        hedef_yol = Path(tempfile.gettempdir()) / f"acestep_{uuid.uuid4().hex[:8]}.wav"
    _stereo_wav_yaz(audio_np, sr, hedef_yol, log=log)
    _ilerleme(82, f"✅ ACE-Step 1.5 şarkısı hazır: {hedef_yol.stat().st_size // 1024} KB ({sn:.0f}s, {sr}Hz stereo)")
    return hedef_yol


def muzik_uret(prompt: str, sure_sn: float = 15.0, model_key: str = "stereo",
               hedef_yol: Optional[Path] = None, bildirim_cb=None, log=print) -> Path:
    """MusicGen Stereo Medium (varsayılan) veya small/medium ile 32 kHz gerçek stereo WAV üretir."""
    global _MUZIK_PIPE, _MUZIK_KEY

    import torch

    def _ilerleme(pct: int, mesaj: str) -> None:
        log(mesaj)
        if callable(bildirim_cb):
            try:
                bildirim_cb(pct, mesaj)
            except Exception:
                pass

    mk = str(model_key or "stereo").lower()
    if "small" in mk:
        repo = MUSICGEN_SMALL
    elif "mono" in mk:
        repo = MUSICGEN_MEDIUM
    else:
        repo = MUSICGEN_STEREO_MEDIUM

    if _MUZIK_PIPE is None or _MUZIK_KEY != repo:
        _muzik_cache_temizle()
        _ilerleme(20, f"⏳ MusicGen yükleniyor: {repo} (fp32, CUDA/CPU)…")
        from transformers import AutoProcessor, MusicgenForConditionalGeneration

        device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            processor = AutoProcessor.from_pretrained(repo)
            model = MusicgenForConditionalGeneration.from_pretrained(
                repo, torch_dtype=torch.float32, low_cpu_mem_usage=True
            ).to(device)
        except Exception as exc:
            if repo == MUSICGEN_STEREO_MEDIUM:
                log(f"⚠️ {repo} yüklenemedi ({type(exc).__name__}), {MUSICGEN_MEDIUM} yedeğine geçiliyor…")
                repo = MUSICGEN_MEDIUM
                processor = AutoProcessor.from_pretrained(repo)
                model = MusicgenForConditionalGeneration.from_pretrained(
                    repo, torch_dtype=torch.float32, low_cpu_mem_usage=True
                ).to(device)
            else:
                raise
        _MUZIK_PIPE = (processor, model, device)
        _MUZIK_KEY = repo
        _ilerleme(40, f"✅ MusicGen hazır: {repo} @ {device} (fp32)")

    processor, model, device = _MUZIK_PIPE

    try:
        sn = max(1.0, min(30.0, float(sure_sn)))
    except (TypeError, ValueError):
        sn = 15.0
    max_new = min(1500, max(128, int(sn * 50)))

    _ilerleme(55, f"🎵 MusicGen üretimi: {sn:.1f}s → ~{max_new} token (@32kHz stereo)")
    inputs = processor(text=[prompt], padding=True, return_tensors="pt").to(device)

    with torch.inference_mode():
        cikti = model.generate(**inputs, do_sample=True, guidance_scale=3.0,
                               max_new_tokens=max_new)

    audio = cikti[0].cpu().float().numpy()  # (channels, samples)
    sample_rate = int(getattr(getattr(model, "config", None), "audio_encoder", None).sampling_rate) if hasattr(getattr(getattr(model, "config", None), "audio_encoder", None), "sampling_rate") else 32000
    if hedef_yol is None:
        hedef_yol = Path(tempfile.gettempdir()) / f"musicgen_{uuid.uuid4().hex[:8]}.wav"

    _stereo_wav_yaz(audio, sample_rate, hedef_yol)
    _ilerleme(80, f"✅ Müzik hazır: {hedef_yol.stat().st_size // 1024} KB ({sn:.1f}s, {sample_rate}Hz stereo)")
    return hedef_yol


# -----------------------------------------------------------------------------
# 4. GÖREV YÖNLENDİRME — iş kaydındaki `method` alanına göre
# -----------------------------------------------------------------------------
def _cozunurluk(oran: str, kalite: str = "480p") -> Tuple[int, int]:
    """En-boy oranını (16:9, 9:16, 1:1) Wan/FLUX/VACE 16-piksel sınırlarına çevirir."""
    temiz = str(oran or "16:9").replace(" ", "")
    if temiz == "1:1":
        if kalite == "720p":
            return (720, 720)
        if kalite in ("832p", "480p-genis"):
            return (640, 640)
        return (480, 480)
    dikey = temiz == "9:16"
    if kalite in ("832p", "480p-genis"):
        return (480, 832) if dikey else (832, 480)
    if kalite == "720p":
        return (720, 1280) if dikey else (1280, 720)
    # Varsayılan: T4 16 GB'da güvenli 480p sınıfı
    return (320, 480) if dikey else (480, 320)



def _auth_headers(token: Optional[str]) -> Dict[str, str]:
    """İşçi anahtarını hem Bearer hem X-Worker-Key olarak gönderir."""
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}", "X-Worker-Key": token}


def _medya_uzantisi(url: str, varsayilan: str) -> str:
    uzanti = Path(urllib.parse.urlparse(url).path).suffix
    return uzanti if uzanti and len(uzanti) <= 6 else varsayilan


def _indir(sunucu: str, url: str, hedef: Path, token: Optional[str] = None,
           zaman_asimi: int = 180) -> Path:
    """Sunucudaki göreli/mutlak medya URL'sini auth başlıklarıyla indirir."""
    tam = urllib.parse.urljoin(sunucu.rstrip("/") + "/", url)
    sema = urllib.parse.urlparse(tam).scheme.lower()
    if sema not in ("http", "https"):
        raise ValueError(f"Desteklenmeyen medya URL şeması: {sema or 'yok'}")
    req = urllib.request.Request(
        tam, headers={"Accept": "*/*", **_auth_headers(token)}, method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=zaman_asimi) as yanit:
            hedef.parent.mkdir(parents=True, exist_ok=True)
            hedef.write_bytes(yanit.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Medya indirilemedi HTTP {e.code}: {tam}") from e
    except Exception as e:
        raise RuntimeError(f"Medya indirilemedi ({type(e).__name__}): {tam}") from e
    if not hedef.is_file() or hedef.stat().st_size == 0:
        raise RuntimeError(f"İndirilen medya boş: {tam}")
    return hedef


def _opsiyonel_medya(job: Dict[str, Any], sunucu: str, token: Optional[str],
                     log=print) -> Tuple[Optional[Path], Optional[Path]]:
    """audio_url / subtitle_url varsa indirir; yoksa veya düşerse None döner."""
    ses: Optional[Path] = None
    altyazi: Optional[Path] = None
    uid = uuid.uuid4().hex[:8]
    if sunucu and job.get("audio_url"):
        url = str(job["audio_url"])
        try:
            ses = _indir(sunucu, url, Path(tempfile.gettempdir())
                         / f"ses_{uid}{_medya_uzantisi(url, '.bin')}", token)
        except Exception as e:
            log(f"⚠️ audio_url indirilemedi: {e}")
    if sunucu and job.get("subtitle_url"):
        url = str(job["subtitle_url"])
        try:
            altyazi = _indir(sunucu, url, Path(tempfile.gettempdir())
                             / f"altyazi_{uid}{_medya_uzantisi(url, '.srt')}", token)
        except Exception as e:
            log(f"⚠️ subtitle_url indirilemedi: {e}")
    return ses, altyazi


def _ffmpeg_kacis(yol: Path) -> str:
    return str(yol).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _medya_suresi(yol: Path) -> Optional[float]:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(yol)],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0 and r.stdout.strip():
            return max(0.0, float(r.stdout.strip()))
    except Exception:
        pass
    return None


def _medya_birlestir(video: Path, ses: Optional[Path], altyazi: Optional[Path],
                     log=print, hedef_sure_sn: Optional[float] = None) -> Path:
    """Sesi/altyazıyı H.264+AAC MP4'e mux'lar; kısa ses videoyu kesmez, uzun ses videoyu uzatır."""
    if ses is None and altyazi is None:
        return video
    hedef = Path(tempfile.gettempdir()) / f"mux_{uuid.uuid4().hex[:8]}.mp4"
    vid_dur = _medya_suresi(video) or float(hedef_sure_sn or 5.0)
    ses_dur = (_medya_suresi(ses) or 0.0) if ses is not None else 0.0
    videoyu_uzat = bool(ses is not None and ses_dur > vid_dur + 0.35)
    hedef_cikis_sn = ses_dur if videoyu_uzat else max(vid_dur, float(hedef_sure_sn or 0.0))

    def _calistir(mod: str) -> subprocess.CompletedProcess:
        # mod: "burn" (libass yakma), "soft" (mov_text track), "none" (altyazısız)
        cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        if videoyu_uzat:
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", str(video)]
        if ses is not None:
            cmd += ["-i", str(ses)]
        if mod == "soft" and altyazi is not None and altyazi.suffix.lower() == ".srt":
            cmd += ["-i", str(altyazi)]
        cmd += ["-map", "0:v:0"]
        if ses is not None:
            cmd += ["-map", "1:a:0"]
        if mod == "soft" and altyazi is not None and altyazi.suffix.lower() == ".srt":
            s_idx = "2:s:0" if ses is not None else "1:s:0"
            cmd += ["-map", s_idx, "-c:s", "mov_text"]
        if mod == "burn" and altyazi is not None:
            cmd += ["-vf", f"subtitles=filename='{_ffmpeg_kacis(altyazi)}'"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
        if ses is not None:
            if videoyu_uzat:
                cmd += ["-c:a", "aac", "-b:a", "192k", "-t", f"{ses_dur:.2f}", "-shortest"]
            else:
                cmd += ["-af", f"apad=whole_dur={hedef_cikis_sn:.3f}", "-c:a", "aac", "-b:a", "192k", "-t", f"{hedef_cikis_sn:.3f}"]
        cmd += ["-movflags", "+faststart", str(hedef)]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=900)

    deneme = _calistir("burn" if altyazi is not None else "none")
    if deneme.returncode != 0 and altyazi is not None:
        log("⚠️ Altyazı yakılamadı — mov_text yumuşak altyazı izi deneniyor")
        deneme = _calistir("soft")
    if deneme.returncode != 0 and altyazi is not None:
        deneme = _calistir("none")
    if deneme.returncode != 0:
        if ses is not None:
            raise RuntimeError(f"Ses/video mux başarısız: {(deneme.stderr or '')[-200:].strip()}")
        return video
    if not hedef.is_file() or hedef.stat().st_size == 0:
        raise RuntimeError(f"Mux çıktısı boş: {hedef}")
    log(f"✅ Ses/altyazı mux tamam: {hedef.stat().st_size // 1024} KB (vid={vid_dur:.1f}s, ses={ses_dur:.1f}s)")
    return hedef


def _on_izleme_gonder_opsiyonel(sunucu: str, job: Dict[str, Any], gorsel_yolu: Path,
                                token: Optional[str], log=print) -> None:
    """2 aşamalı I2V sırasında ara anahtar kareyi kapak görseli olarak sunucuya gönderir."""
    jid = str(job.get("job_id") or job.get("id") or "").strip()
    if not (sunucu and jid):
        return
    try:
        yukle(sunucu, jid, gorsel_yolu, token=token, media_type="image")
    except Exception as e:
        log(f"⚠️ Ara anahtar kare yüklemesi atlandı ({type(e).__name__}): {e}")


def gorev_isle(job: Dict[str, Any], secenekler: Dict[str, Any], log=print,
               sunucu: str = "", token: Optional[str] = None) -> Path:
    """Bir işi gerçek difüzyonla üretir ve çıktı yolunu döner.

    `mode` / `method` / `workflow` eşlemesi:
        image_first_preview / flux2_resim → Seçili görsel modeliyle PNG anahtar kare
        image_then_i2v / burc_video       → Önce görsel → Bellek boşalt → Seçili I2V ile MP4
        wan_i2v / i2v                     → Onaylı görselden seçili I2V modeliyle MP4
        hibrit / hybrid                   → Görsel varsa I2V, yoksa T2V
        t2v_direct / diğer                → Doğrudan T2V video difüzyonu
        flux2                             → Görsel PNG → 3 sn MP4
    """
    prompt = str(job.get("image_prompt") or job.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("İş kaydında prompt yok — üretim yapılamaz")
    i2v_prompt = str(job.get("motion_prompt") or prompt)
    neg_prompt = str(job.get("negative_prompt") or "")
    image_model_key = job.get("image_model")
    i2v_model_key = job.get("i2v_model") or job.get("video_model") or job.get("model_id")

    desteklenen = {
        "image_first_preview", "image_then_i2v", "flux2_resim", "burc_video",
        "wan_i2v", "i2v", "vace_r2v", "flf2v", "t2v_direct", "flux2", "hibrit", "hybrid",
        "remotion_cinema", "blender_wan", "opus_canvas", "viral_shorts",
        "musicgen", "gpu_muzik", "acestep", "gpu_acestep", "gpu-acestep-1.5",
    }
    mod = "remotion_cinema"
    for aday in (job.get("method"), job.get("workflow"), job.get("mode")):
        ad = str(aday or "").lower().strip()
        if ad in desteklenen:
            mod = ad
            break

    oran = str(job.get("aspect_ratio") or "16:9")
    w, h = _cozunurluk(oran, secenekler.get("kalite", "480p"))
    tohum = int(job.get("seed") or 42)
    is_music_mod = mod in ("musicgen", "gpu_muzik", "acestep", "gpu_acestep", "gpu-acestep-1.5")
    default_sure = 30.0 if is_music_mod else 5.0
    sure_sn = float(job.get("sure_sn") or job.get("duration") or default_sure)
    flux_adim = secenekler.get("flux_adim")
    muzik_model_key = str(
        job.get("audio_model")
        or job.get("music_model")
        or job.get("model_key")
        or secenekler.get("muzik_model")
        or ("acestep-v15-xl-turbo" if mod in ("acestep", "gpu_acestep", "gpu-acestep-1.5") else "stereo")
    )

    # 1) MÜZİK İŞLERİ (ACE-Step 1.5 Suno Seviyesi + MusicGen Stereo)
    if is_music_mod:
        _gorsel_cache_temizle()
        _video_cache_temizle()
        jid_str = str(job.get("job_id") or job.get("id") or "")
        cb = (
            (lambda pct, msg: ilerleme_bildir(sunucu, jid_str, pct, msg, token=token))
            if (sunucu and jid_str)
            else None
        )
        is_acestep = mod in ("acestep", "gpu_acestep", "gpu-acestep-1.5") or "acestep" in muzik_model_key.lower()
        if is_acestep:
            ref_audio_path: Optional[Path] = None
            ref_audio_url = str(job.get("ref_audio_url") or "").strip()
            try:
                if ref_audio_url:
                    if not sunucu:
                        raise ValueError("ref_audio_url için sunucu adresi gerekli")
                    ref_audio_path = _indir(
                        sunucu, ref_audio_url,
                        Path(tempfile.gettempdir())
                        / f"refaud_{uuid.uuid4().hex[:8]}{_medya_uzantisi(ref_audio_url, '.wav')}",
                        token,
                    )
                elif secenekler.get("ref_audio_path") and Path(str(secenekler["ref_audio_path"])).is_file():
                    ref_audio_path = Path(str(secenekler["ref_audio_path"]))

                style_parts = [str(job.get("raw_prompt") or prompt).strip()]
                if job.get("genre"):
                    style_parts.append(str(job["genre"]).strip())
                if job.get("mood"):
                    style_parts.append(str(job["mood"]).strip())
                ace_prompt = ", ".join(p for p in style_parts if p)[:512]
                job["_engine_label"] = "Kaggle GPU ACE-Step 1.5 (48kHz Stereo)"
                return acestep_muzik_uret(
                    ace_prompt,
                    lyrics=str(job.get("lyrics") or ""),
                    instrumental=bool(job.get("instrumental", False)),
                    vocal_language=str(job.get("vocal_language") or "tr"),
                    sure_sn=sure_sn,
                    bpm=job.get("bpm"),
                    key_scale=str(job.get("key_scale") or ""),
                    time_signature=str(job.get("time_signature") or ""),
                    music_task=str(job.get("music_task") or "text2music"),
                    ref_audio_path=ref_audio_path,
                    audio_cover_strength=float(job.get("audio_cover_strength") or 0.85),
                    repaint_start=job.get("repaint_start"),
                    repaint_end=job.get("repaint_end"),
                    tohum=tohum,
                    variant="sft" if "sft" in muzik_model_key.lower() else "turbo",
                    bildirim_cb=cb,
                    log=log,
                )
            finally:
                if ref_audio_path is not None and ref_audio_url:
                    ref_audio_path.unlink(missing_ok=True)
        job["_engine_label"] = "Kaggle GPU MusicGen Stereo"
        return muzik_uret(
            prompt, sure_sn=sure_sn, model_key=muzik_model_key,
            bildirim_cb=cb, log=log,
        )

    # 2) GİRDİ MEDYALARI (Görsel + Bitiş Karesi + Ses + Altyazı) — flux2_resim ÖNCESİNDE indirilir!
    gecici: list[Path] = []
    gorsel_yolu: Optional[Path] = None
    son_kare_yolu: Optional[Path] = None
    img_url = str(job.get("input_image_url") or job.get("image_url") or "").strip()
    if img_url:
        if not sunucu:
            raise ValueError("input_image_url için sunucu adresi gerekli")
        gorsel_yolu = _indir(
            sunucu, img_url,
            Path(tempfile.gettempdir())
            / f"girdi_{uuid.uuid4().hex[:8]}{_medya_uzantisi(img_url, '.png')}",
            token,
        )
        gecici.append(gorsel_yolu)
    elif secenekler.get("image_path") and Path(str(secenekler["image_path"])).is_file():
        gorsel_yolu = Path(str(secenekler["image_path"]))

    end_img_url = str(job.get("end_image_url") or "").strip()
    if end_img_url:
        if not sunucu:
            raise ValueError("end_image_url için sunucu adresi gerekli")
        son_kare_yolu = _indir(
            sunucu, end_img_url,
            Path(tempfile.gettempdir())
            / f"bitis_{uuid.uuid4().hex[:8]}{_medya_uzantisi(end_img_url, '.png')}",
            token,
        )
        gecici.append(son_kare_yolu)
    elif secenekler.get("end_image_path") and Path(str(secenekler["end_image_path"])).is_file():
        son_kare_yolu = Path(str(secenekler["end_image_path"]))

    try:
        if mod in ("flux2_resim", "image_first_preview"):
            job["_engine_label"] = f"Kaggle GPU {image_model_key or 'flux2-klein'}"
            img_kw: Dict[str, Any] = {"neg_prompt": neg_prompt, "adim": flux_adim, "tohum": tohum, "log": log}
            if gorsel_yolu is not None:
                img_kw["ref_gorsel"] = gorsel_yolu
            return secimli_gorsel_uret(prompt, image_model_key, w, h, **img_kw)

        ses, altyazi = _opsiyonel_medya(job, sunucu, token, log)
        gecici += [p for p in (ses, altyazi) if p is not None]

        if mod == "flux2":
            img_kw2: Dict[str, Any] = {"neg_prompt": neg_prompt, "adim": flux_adim, "tohum": tohum, "log": log}
            if gorsel_yolu is not None:
                img_kw2["ref_gorsel"] = gorsel_yolu
            png = secimli_gorsel_uret(prompt, image_model_key, w, h, **img_kw2)
            gecici.append(png)
            hedef = png.with_suffix(".mp4")
            r = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png),
                 "-t", f"{max(3.0, sure_sn):.2f}", "-vf", f"scale={w}:{h},format=yuv420p",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-movflags", "+faststart", str(hedef)],
                capture_output=True, text=True, timeout=300,
            )
            if r.returncode != 0:
                raise RuntimeError(f"Görsel MP4'e çevrilemedi: {(r.stderr or '')[-200:]}")
            return _medya_birlestir(hedef, ses, altyazi, log=log, hedef_sure_sn=sure_sn)

        if mod == "vace_r2v":
            if gorsel_yolu is None:
                raise ValueError("vace_r2v (Tutarlı Karakter) için karakter portre/referans görseli gerekli")
            job["_engine_label"] = "Kaggle GPU Wan2.1-VACE-1.3B (R2V)"
            video = wan21_vace_uret(
                i2v_prompt, w, h,
                ref_gorseller=[gorsel_yolu], neg_prompt=neg_prompt,
                sure_sn=sure_sn, adim=int(secenekler.get("i2v_adim", 30)),
                tohum=tohum, log=log,
            )
            return _medya_birlestir(video, ses, altyazi, log=log, hedef_sure_sn=sure_sn)

        if mod == "flf2v":
            if gorsel_yolu is None or son_kare_yolu is None:
                raise ValueError("flf2v (İlk+Son Kare Geçişi) için hem başlangıç hem bitiş görseli gerekli")
            job["_engine_label"] = "Kaggle GPU Wan2.1-VACE-1.3B (FLF2V)"
            video = wan21_vace_uret(
                i2v_prompt, w, h,
                ilk_kare=gorsel_yolu, son_kare=son_kare_yolu,
                neg_prompt=neg_prompt, sure_sn=sure_sn,
                adim=int(secenekler.get("i2v_adim", 30)), tohum=tohum, log=log,
            )
            return _medya_birlestir(video, ses, altyazi, log=log, hedef_sure_sn=sure_sn)

        if mod in ("wan_i2v", "i2v"):
            if gorsel_yolu is None:
                raise ValueError(
                    "wan_i2v için `image_path` veya `input_image_url` gerekli (görsel yok)")
            job["_engine_label"] = f"Kaggle GPU {i2v_model_key or 'wan2.1-i2v-14b'}"
            video = secimli_i2v_uret(
                gorsel_yolu, i2v_prompt, i2v_model_key, w, h,
                neg_prompt=neg_prompt, sure_sn=sure_sn,
                adim=int(secenekler.get("i2v_adim", 20)), tohum=tohum, log=log,
            )
            return _medya_birlestir(video, ses, altyazi, log=log, hedef_sure_sn=sure_sn)

        if mod in ("image_then_i2v", "burc_video"):
            if gorsel_yolu is None:
                gorsel_yolu = secimli_gorsel_uret(
                    prompt, image_model_key, w, h, neg_prompt=neg_prompt,
                    adim=flux_adim, tohum=tohum, log=log,
                )
                gecici.append(gorsel_yolu)
                _gorsel_cache_temizle()
                _on_izleme_gonder_opsiyonel(sunucu, job, gorsel_yolu, token, log=log)
            job["_engine_label"] = f"Kaggle GPU {image_model_key or 'flux2'}->{i2v_model_key or 'wan2.1-i2v-14b'}"
            video = secimli_i2v_uret(
                gorsel_yolu, i2v_prompt, i2v_model_key, w, h,
                neg_prompt=neg_prompt, sure_sn=sure_sn,
                adim=int(secenekler.get("i2v_adim", 20)), tohum=tohum, log=log,
            )
            return _medya_birlestir(video, ses, altyazi, log=log, hedef_sure_sn=sure_sn)

        if mod in ("hibrit", "hybrid") and gorsel_yolu is not None:
            video = secimli_i2v_uret(
                gorsel_yolu, i2v_prompt, i2v_model_key, w, h,
                neg_prompt=neg_prompt, sure_sn=sure_sn,
                adim=int(secenekler.get("i2v_adim", 20)), tohum=tohum, log=log,
            )
            return _medya_birlestir(video, ses, altyazi, log=log, hedef_sure_sn=sure_sn)

        # Doğrudan T2V (seçilen video modelini onurlandır: Wan2.2-TI2V-5B / Wan2.1-VACE / LTX / Wan2.1-T2V-1.3B)
        job["_engine_label"] = f"Kaggle GPU T2V {i2v_model_key or 'wan2.1-t2v-1.3b'}"
        video = secimli_t2v_uret(
            prompt, i2v_model_key, w, h, neg_prompt=neg_prompt,
            sure_sn=sure_sn, adim=int(secenekler.get("t2v_adim", 25)),
            tohum=tohum, ref_gorseller=[gorsel_yolu] if gorsel_yolu else None, log=log,
        )
        return _medya_birlestir(video, ses, altyazi, log=log, hedef_sure_sn=sure_sn)
    finally:
        for yol in gecici:
            try:
                yol.unlink(missing_ok=True)
            except OSError:
                pass


# -----------------------------------------------------------------------------
# 5. İŞÇİ PROTOKOLÜ (mevcut sunucu uçları)
# -----------------------------------------------------------------------------
def _istek(sunucu: str, yol: str, veri: Optional[dict] = None,
           token: Optional[str] = None, zaman_asimi: int = 60) -> Tuple[int, bytes]:
    url = sunucu.rstrip("/") + yol
    govde = None
    basliklar = {"Accept": "application/json", **_auth_headers(token)}
    if veri is not None:
        govde = json.dumps(veri).encode("utf-8")
        basliklar["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, data=govde, headers=basliklar, method="POST" if govde else "GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=zaman_asimi) as y:
            return y.status, y.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 0, str(e).encode("utf-8")


def heartbeat(sunucu: str, isci_id: str, tur: str, gpu: Dict[str, Any],
              durum: str = "idle", tamamlanan: int = 0,
              token: Optional[str] = None) -> bool:
    kod, _ = _istek(sunucu, "/api/worker/heartbeat", {
        "worker_id": isci_id,
        "worker_type": tur,
        "gpu_name": gpu.get("ad") or "bilinmiyor",
        "vram_gb": gpu.get("vram_gb") or 0,
        "status": durum,
        "tasks_completed": tamamlanan,
    }, token=token)
    return kod == 200


def is_al(sunucu: str, isci_id: str,
          token: Optional[str] = None, mod: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """İş claim eder; `mod` verildiyse ?mod= query parametresi olarak gönderir."""
    url = f"/api/worker/claim?worker_id={urllib.parse.quote(isci_id)}"
    if mod:
        url += f"&mod={urllib.parse.quote(mod)}"
    kod, govde = _istek(sunucu, url, token=token)
    if kod != 200:
        return None
    try:
        return json.loads(govde).get("job")
    except Exception:
        return None


def ilerleme_bildir(sunucu: str, job_id: str, pct: int, asama: str,
                    token: Optional[str] = None, failed: bool = False,
                    hata: Optional[str] = None) -> None:
    """İlerleme bildirir; başarısızlıkta failed=true + error alanı gönderir."""
    veri: Dict[str, Any] = {
        "job_id": job_id, "progress_pct": pct, "stage": asama,
    }
    if failed:
        veri["failed"] = True
        veri["error"] = hata or asama
    _istek(sunucu, "/api/worker/progress", veri, token=token)


def yukle(sunucu: str, job_id: str, dosya: Path,
          token: Optional[str] = None,
          media_type: str = "video",
          engine_label: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Üretilen MP4/PNG/WAV/MP3/FLAC'ı sunucuya yükler. Döner: sunucu yanıtı veya None."""
    gorsel = media_type == "image"
    ses = media_type == "audio"
    if gorsel:
        mime = {".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(
                    dosya.suffix.lower(), "application/octet-stream")
    elif ses:
        mime = {".wav": "audio/wav", ".mp3": "audio/mpeg",
                ".ogg": "audio/ogg", ".flac": "audio/flac"}.get(
                    dosya.suffix.lower(), "application/octet-stream")
    else:
        mime = "video/mp4"
    sinir = "----Fabrika" + uuid.uuid4().hex
    parcalar = [
        f"--{sinir}\r\n".encode(),
        b'Content-Disposition: form-data; name="job_id"\r\n\r\n',
        job_id.encode(), b"\r\n",
        f"--{sinir}\r\n".encode(),
        b'Content-Disposition: form-data; name="media_type"\r\n\r\n',
        media_type.encode(), b"\r\n",
    ]
    if engine_label:
        parcalar.extend([
            f"--{sinir}\r\n".encode(),
            b'Content-Disposition: form-data; name="engine_label"\r\n\r\n',
            str(engine_label)[:120].encode("utf-8"), b"\r\n",
        ])
    parcalar.extend([
        f"--{sinir}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{dosya.name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        dosya.read_bytes(), b"\r\n",
        f"--{sinir}--\r\n".encode(),
    ])
    govde = b"".join(parcalar)
    basliklar = {
        "Content-Type": f"multipart/form-data; boundary={sinir}",
        **_auth_headers(token),
    }
    req = urllib.request.Request(
        sunucu.rstrip("/") + "/api/worker/upload", data=govde,
        headers=basliklar, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as y:
            return json.loads(y.read())
    except urllib.error.HTTPError as e:
        print(f"❌ Yükleme hatası HTTP {e.code}: {e.read()[:200]!r}")
    except Exception as e:
        print(f"❌ Yükleme istisnası: {e}")
    return None


# -----------------------------------------------------------------------------
# 6. ANA DÖNGÜ
# -----------------------------------------------------------------------------
def _isci_turu() -> str:
    """Ortamdan işçi türünü tahmin eder (Kaggle / Colab / yerel)."""
    if os.environ.get("KAGGLE_KERNEL_RUN_TYPE") or Path("/kaggle").is_dir():
        return "kaggle"
    if os.environ.get("COLAB_GPU") or Path("/content").is_dir():
        return "colab"
    return "yerel"


def _tek_is_isle(sunucu: str, isci_id: str, secenekler: Dict[str, Any],
                 token: Optional[str], sayac: Dict[str, int]) -> bool:
    """Sıradaki işi alır, üretir, yükler. İş varsa True döner."""
    mod_filtresi = secenekler.get("modlar")
    job = is_al(sunucu, isci_id, token=token, mod=mod_filtresi)
    if not job:
        return False

    jid = str(job.get("job_id") or job.get("id") or "")
    mod = job.get("mode") or job.get("method")
    print(f"\n📥 İş alındı: {jid} | mode/method={mod} | "
          f"prompt={str(job.get('prompt'))[:60]}")
    ilerleme_bildir(sunucu, jid, 10, "Model yükleniyor", token=token)

    try:
        cikti = gorev_isle(job, secenekler, log=print, sunucu=sunucu, token=token)
    except Exception as e:
        hata = f"{type(e).__name__}: {e}"
        print(f"❌ İş başarısız: {hata}")
        ilerleme_bildir(sunucu, jid, 0, f"basarisiz: {str(e)[:120]}",
                        token=token, failed=True, hata=hata[:500])
        return True

    gorsel_mi = cikti.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ses_mi = cikti.suffix.lower() in {".wav", ".mp3", ".ogg", ".flac"}
    if gorsel_mi:
        yukleme_turu = "image"
        asama_mesaj = "Görsel yükleniyor"
    elif ses_mi:
        yukleme_turu = "audio"
        asama_mesaj = "Ses yükleniyor"
    else:
        yukleme_turu = "video"
        asama_mesaj = "Video yükleniyor"
    ilerleme_bildir(sunucu, jid, 85, asama_mesaj, token=token)
    yanit = yukle(
        sunucu, jid, cikti, token=token, media_type=yukleme_turu,
        engine_label=str(job.get("_engine_label") or "") or None,
    )
    if yanit and yanit.get("success"):
        sayac["tamam"] += 1
        print(f"✅ Yüklendi: {yanit.get('output_url')} "
              f"({yanit.get('file_size_bytes', 0) // 1024} KB)")
    else:
        ilerleme_bildir(sunucu, jid, 95, "yukleme_basarisiz", token=token,
                        failed=True, hata="Üretim tamamlandı ancak yükleme başarısız")
        print("❌ Yükleme başarısız — iş sunucuda 'isleniyor' kalacak")

    try:
        cikti.unlink(missing_ok=True)
    except OSError:
        pass
    _bosalt()
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Kaggle/Colab GPU işçisi — FLUX.2 görsel + Wan2.1 video + MusicGen müzik"
    )
    ap.add_argument("--server", default=os.environ.get("FABRIKA_SUNUCU", VARSAYILAN_SUNUCU))
    ap.add_argument(
        "--token",
        default=os.environ.get("FABRIKA_WORKER_KEY") or os.environ.get("FABRIKA_TOKEN"),
        help="İşçi anahtarı: Authorization Bearer + X-Worker-Key olarak gönderilir",
    )
    ap.add_argument("--worker-key", dest="token",
                    help="--token ile aynı (FABRIKA_WORKER_KEY ortam değişkenine eşdeğer)")
    ap.add_argument("--isci-id", default=None, help="Sabit işçi kimliği")
    ap.add_argument("--aralik", type=int, default=15, help="Boş kuyruk bekleme (sn)")
    ap.add_argument("--tek-seferlik", action="store_true", help="Tek iş al ve çık")
    ap.add_argument("--kalite", choices=["480p", "832p", "720p"], default="480p")
    ap.add_argument("--t2v-adim", type=int, default=25)
    ap.add_argument("--i2v-adim", type=int, default=20)
    ap.add_argument("--flux-adim", type=int, default=4)
    ap.add_argument("--modlar", default=None,
                    help="İş filtresi: 'all', 'musicgen', 'video', 'image' — claim'e ?mod= olarak gönderilir")
    ap.add_argument("--muzik-model", choices=["stereo", "medium", "small", "acestep-turbo", "acestep-sft"], default="stereo",
                    help="Varsayılan yerel müzik modeli (ACE-Step 1.5 veya MusicGen Stereo)")
    ap.add_argument("--gpu-kontrol", action="store_true",
                    help="Yalnız GPU ve model kullanılabilirliğini raporla, çık")
    args = ap.parse_args()

    gpu = gpu_bilgisi()
    print("=" * 62)
    print(f"Fabrika GPU İşçisi  |  sunucu={args.server}")
    if gpu.get("gpu_count", 1) > 1:
        print(f"GPU: {gpu.get('ad')}  (toplam {gpu.get('vram_gb')} GB, {gpu.get('gpu_count')} GPU, kaynak={gpu.get('kaynak')})")
    else:
        print(f"GPU: {gpu.get('ad') or 'BULUNAMADI'}  ({gpu.get('vram_gb')} GB, kaynak={gpu.get('kaynak')})")

    if not gpu.get("var"):
        print("❌ GPU BULUNAMADI — difüzyon bu ortamda çalışmaz.")
        print("   Kaggle: Settings → Accelerator → GPU T4 x2")
        print("   Colab : Runtime → Change runtime type → T4 GPU")
        return 2

    if args.gpu_kontrol:
        try:
            import diffusers
            import torch

            print(f"torch={torch.__version__}  diffusers={diffusers.__version__}")
            print(f"Flux2KleinPipeline: {hasattr(diffusers, 'Flux2KleinPipeline')}")
            print(f"WanPipeline: {hasattr(diffusers, 'WanPipeline')}")
            print(f"WanImageToVideoPipeline: {hasattr(diffusers, 'WanImageToVideoPipeline')}")
            print(f"WanVACEPipeline (Tutarlı Karakter R2V + FLF2V): {hasattr(diffusers, 'WanVACEPipeline')}")
            print(f"AceStepPipeline (Suno Seviyesi Müzik): {hasattr(diffusers, 'AceStepPipeline')}")
        except Exception as e:
            print(f"⚠️ diffusers/torch eksik: {e}")
        # MusicGen + soundfile kontrolü
        try:
            import transformers
            print(f"transformers={transformers.__version__}")
            print(f"MusicgenForConditionalGeneration: {hasattr(transformers, 'MusicgenForConditionalGeneration')}")
            print(f"AutoProcessor: {hasattr(transformers, 'AutoProcessor')}")
        except Exception as e:
            print(f"⚠️ transformers eksik: {e}")
        print(f"Önerilen modeller: {FLUX2_KLEIN} / {WAN21_VACE} / {WAN21_I2V} / {ACESTEP_TURBO} / {MUSICGEN_STEREO_MEDIUM}")
        return 0

    isci_id = args.isci_id or f"{_isci_turu()}_{uuid.uuid4().hex[:8]}"
    token = (args.token or "").strip() or None
    secenekler = {
        "kalite": args.kalite,
        "t2v_adim": args.t2v_adim,
        "i2v_adim": args.i2v_adim,
        "flux_adim": args.flux_adim,
        "modlar": args.modlar,
        "muzik_model": args.muzik_model,
    }
    sayac = {"tamam": 0}
    print(f"İşçi kimliği: {isci_id}")
    print(f"Kimlik doğrulama: {'Bearer + X-Worker-Key (ayarlı)' if token else 'YOK'}")
    if args.modlar:
        print(f"İş filtresi (mod): {args.modlar}")
    print(f"MusicGen model: {args.muzik_model}")
    print("=" * 62)

    if not heartbeat(args.server, isci_id, _isci_turu(), gpu, "idle", 0, token=token):
        print("⚠️ Sunucuya heartbeat gönderilemedi — yine de kuyruk denenecek")

    while True:
        try:
            is_var = _tek_is_isle(args.server, isci_id, secenekler, token, sayac)
        except KeyboardInterrupt:
            print("\n⏹️ Kullanıcı durdurdu")
            break
        except Exception as e:
            print(f"⚠️ Döngü hatası: {type(e).__name__}: {e}")
            is_var = False

        heartbeat(args.server, isci_id, _isci_turu(), gpu,
                  "idle" if not is_var else "busy", sayac["tamam"], token=token)

        if args.tek_seferlik:
            print(f"\nTek seferlik mod bitti. Tamamlanan iş: {sayac['tamam']}")
            break
        if not is_var:
            time.sleep(max(3, args.aralik))

    return 0


if __name__ == "__main__":
    sys.exit(main())


