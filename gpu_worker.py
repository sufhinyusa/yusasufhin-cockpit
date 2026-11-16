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
WAN22_TI2V = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
LTX_VIDEO = "Lightricks/LTX-Video"
COGVIDEOX_I2V = "THUDM/CogVideoX-5b-I2V"
SVD_XT = "stabilityai/stable-video-diffusion-img2vid-xt"

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
    """Gerçek GPU bilgisini nvidia-smi ve torch ile sorgular (uydurma yok)."""
    bilgi: Dict[str, Any] = {"var": False, "ad": None, "vram_gb": 0.0, "kaynak": None}
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0 and r.stdout.strip():
            ilk = r.stdout.strip().splitlines()[0]
            ad, _, mb = ilk.partition(",")
            bilgi.update({
                "var": True, "ad": ad.strip(),
                "vram_gb": round(float(mb.strip()) / 1024, 1),
                "kaynak": "nvidia-smi",
            })
            return bilgi
    except Exception:
        pass
    try:
        import torch

        if torch.cuda.is_available():
            prop = torch.cuda.get_device_properties(0)
            bilgi.update({
                "var": True, "ad": prop.name,
                "vram_gb": round(prop.total_memory / 1024**3, 1),
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


def _gorsel_cache_temizle() -> None:
    """Görsel boru hatlarını RAM/VRAM'den bırakır (I2V aşamasından önce T4 güvenliği)."""
    global _FLUX_PIPE, _EXTRA_IMG_PIPE, _EXTRA_IMG_KEY
    _FLUX_PIPE = None
    _EXTRA_IMG_PIPE = None
    _EXTRA_IMG_KEY = ""
    _bosalt()


def _video_cache_temizle() -> None:
    """Video boru hatlarını RAM/VRAM'den bırakır (farklı modele geçerken)."""
    global _WAN_T2V, _WAN_I2V, _EXTRA_VID_PIPE, _EXTRA_VID_KEY
    _WAN_T2V = None
    _WAN_I2V = None
    _EXTRA_VID_PIPE = None
    _EXTRA_VID_KEY = ""
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
                      adim: int = 4, tohum: int = 42, log=print) -> Path:
    """Prompt'tan GERÇEK FLUX.2 görseli üretir. Döner: PNG yolu.

    `Flux2KleinPipeline` distilled bir modeldir: difüzyon adım sayısı sabittir
    (4). `adim` parametresi yalnız arayüz uyumluluğu/log içindir; gerçek adım
    sayısını değiştirmez. Süre GPU ve CPU-offload durumuna göre değişir.
    """
    pipe = flux2_yukle(log=log)
    # Kenar uzunlukları 16'nın katı olmalı
    w = max(256, (genislik // 16) * 16)
    h = max(256, (yukseklik // 16) * 16)
    uid = uuid.uuid4().hex[:8]
    hedef = Path(tempfile.gettempdir()) / f"flux2_{uid}.png"

    log(f"🎨 FLUX.2 difüzyon: {w}x{h} (sabit 4 distilled adım, CPU offload)")
    sonuc = pipe(prompt=prompt, width=w, height=h)
    sonuc.images[0].save(hedef, "PNG")
    log(f"✅ Görsel hazır: {hedef.stat().st_size // 1024} KB")
    return hedef


def secimli_gorsel_uret(prompt: str, model_key: Optional[str], genislik: int, yukseklik: int,
                        neg_prompt: str = "", adim: Optional[int] = None,
                        tohum: int = 42, log=print) -> Path:
    """Seçilen görsel modeliyle (FLUX.2, Z-Image-Turbo, SDXL-Turbo, RealVisXL, AnimagineXL) PNG üretir."""
    global _EXTRA_IMG_PIPE, _EXTRA_IMG_KEY
    repo = _gorsel_modeli_coz(model_key)
    if repo == FLUX2_KLEIN:
        return flux2_gorsel_uret(prompt, genislik, yukseklik,
                                 adim=adim or 4, tohum=tohum, log=log)

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


def secimli_i2v_uret(gorsel_yolu: Path, prompt: str, model_key: Optional[str],
                     genislik: int, yukseklik: int, neg_prompt: str = "",
                     sure_sn: float = 4.0, adim: int = 24,
                     tohum: int = 42, log=print) -> Path:
    """Seçilen I2V modeliyle (Wan2.1-14B, Wan2.2-5B, LTX-Video, CogVideoX-5B, SVD-XT) video üretir."""
    repo = _i2v_modeli_coz(model_key)
    if repo == WAN21_I2V:
        _gorsel_cache_temizle()
        return wan21_i2v_uret(gorsel_yolu, prompt, genislik, yukseklik,
                              sure_sn=sure_sn, adim=adim, tohum=tohum, log=log)
    if repo == WAN21_T2V:
        _gorsel_cache_temizle()
        return wan21_video_uret(prompt, genislik, yukseklik,
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


# -----------------------------------------------------------------------------
# 4. GÖREV YÖNLENDİRME — iş kaydındaki `method` alanına göre
# -----------------------------------------------------------------------------
def _cozunurluk(oran: str, kalite: str = "480p") -> Tuple[int, int]:
    """En-boy oranını Wan/FLUX sınırlarına uygun piksele çevirir.

    ÖLÇÜM (2026-11-11, Kaggle T4 15.0 GB): Wan2.1-T2V-1.3B için 832x480 +
    33 kare OOM verdi. Wan'ın "480p" sınıfı teknik olarak 832x480'dir ama
    16 GB'da güvenli değil. Bu yüzden varsayılan 480p → 480x320 (VAE
    slicing+tiling ile birlikte güvenli). `--kalite 832p` ile eski değer.
    """
    dikey = str(oran).replace(" ", "") == "9:16"
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
                     log=print) -> Path:
    """Sesi/altyazıyı H.264+AAC MP4'e mux'lar; ses uzunsa videoyu pürüzsüz uzatır, libass yoksa soft-sub ekler."""
    if ses is None and altyazi is None:
        return video
    hedef = Path(tempfile.gettempdir()) / f"mux_{uuid.uuid4().hex[:8]}.mp4"
    vid_dur = _medya_suresi(video) or 0.0
    ses_dur = (_medya_suresi(ses) or 0.0) if ses is not None else 0.0
    videoyu_uzat = bool(ses is not None and ses_dur > vid_dur + 0.35)

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
            cmd += ["-c:a", "aac", "-b:a", "192k"]
            if videoyu_uzat:
                cmd += ["-t", f"{ses_dur:.2f}", "-shortest"]
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
        "wan_i2v", "i2v", "t2v_direct", "flux2", "hibrit", "hybrid",
        "remotion_cinema", "blender_wan", "opus_canvas", "viral_shorts",
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
    sure_sn = float(job.get("sure_sn") or job.get("duration") or 4.0)
    flux_adim = secenekler.get("flux_adim")

    if mod in ("flux2_resim", "image_first_preview"):
        return secimli_gorsel_uret(
            prompt, image_model_key, w, h, neg_prompt=neg_prompt,
            adim=flux_adim, tohum=tohum, log=log,
        )

    gecici: list[Path] = []
    gorsel_yolu: Optional[Path] = None
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

    ses, altyazi = _opsiyonel_medya(job, sunucu, token, log)
    gecici += [p for p in (ses, altyazi) if p is not None]

    try:
        if mod == "flux2":
            png = secimli_gorsel_uret(
                prompt, image_model_key, w, h, neg_prompt=neg_prompt,
                adim=flux_adim, tohum=tohum, log=log,
            )
            gecici.append(png)
            hedef = png.with_suffix(".mp4")
            r = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png),
                 "-t", "3", "-vf", f"scale={w}:{h},format=yuv420p",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-movflags", "+faststart", str(hedef)],
                capture_output=True, text=True, timeout=300,
            )
            if r.returncode != 0:
                raise RuntimeError(f"Görsel MP4'e çevrilemedi: {(r.stderr or '')[-200:]}")
            return _medya_birlestir(hedef, ses, altyazi, log=log)

        if mod in ("wan_i2v", "i2v"):
            if gorsel_yolu is None:
                raise ValueError(
                    "wan_i2v için `image_path` veya `input_image_url` gerekli (görsel yok)")
            video = secimli_i2v_uret(
                gorsel_yolu, i2v_prompt, i2v_model_key, w, h,
                neg_prompt=neg_prompt, sure_sn=sure_sn,
                adim=int(secenekler.get("i2v_adim", 20)), tohum=tohum, log=log,
            )
            return _medya_birlestir(video, ses, altyazi, log=log)

        if mod in ("image_then_i2v", "burc_video"):
            if gorsel_yolu is None:
                gorsel_yolu = secimli_gorsel_uret(
                    prompt, image_model_key, w, h, neg_prompt=neg_prompt,
                    adim=flux_adim, tohum=tohum, log=log,
                )
                gecici.append(gorsel_yolu)
                _gorsel_cache_temizle()
                _on_izleme_gonder_opsiyonel(sunucu, job, gorsel_yolu, token, log=log)
            video = secimli_i2v_uret(
                gorsel_yolu, i2v_prompt, i2v_model_key, w, h,
                neg_prompt=neg_prompt, sure_sn=sure_sn,
                adim=int(secenekler.get("i2v_adim", 20)), tohum=tohum, log=log,
            )
            return _medya_birlestir(video, ses, altyazi, log=log)

        if mod in ("hibrit", "hybrid") and gorsel_yolu is not None:
            video = secimli_i2v_uret(
                gorsel_yolu, i2v_prompt, i2v_model_key, w, h,
                neg_prompt=neg_prompt, sure_sn=sure_sn,
                adim=int(secenekler.get("i2v_adim", 20)), tohum=tohum, log=log,
            )
            return _medya_birlestir(video, ses, altyazi, log=log)

        # Yalnız t2v_direct / eski doğrudan T2V modları
        video = wan21_video_uret(
            prompt, w, h, sure_sn=sure_sn,
            adim=int(secenekler.get("t2v_adim", 25)), tohum=tohum, log=log,
        )
        return _medya_birlestir(video, ses, altyazi, log=log)
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
          token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    kod, govde = _istek(
        sunucu, f"/api/worker/claim?worker_id={urllib.parse.quote(isci_id)}",
        token=token,
    )
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
          media_type: str = "video") -> Optional[Dict[str, Any]]:
    """Üretilen MP4/PNG'yi sunucuya yükler. Döner: sunucu yanıtı veya None."""
    gorsel = media_type == "image"
    if gorsel:
        mime = {".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(
                    dosya.suffix.lower(), "application/octet-stream")
    else:
        mime = "video/mp4"
    sinir = "----Fabrika" + uuid.uuid4().hex
    govde = b"".join([
        f"--{sinir}\r\n".encode(),
        b'Content-Disposition: form-data; name="job_id"\r\n\r\n',
        job_id.encode(), b"\r\n",
        f"--{sinir}\r\n".encode(),
        b'Content-Disposition: form-data; name="media_type"\r\n\r\n',
        media_type.encode(), b"\r\n",
        f"--{sinir}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{dosya.name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        dosya.read_bytes(), b"\r\n",
        f"--{sinir}--\r\n".encode(),
    ])
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
    job = is_al(sunucu, isci_id, token=token)
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
    ilerleme_bildir(sunucu, jid, 85,
                    "Görsel yükleniyor" if gorsel_mi else "Video yükleniyor",
                    token=token)
    yanit = yukle(sunucu, jid, cikti, token=token,
                  media_type="image" if gorsel_mi else "video")
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
        description="Kaggle/Colab GPU işçisi — FLUX.2 görsel + Wan2.1 video difüzyonu"
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
    ap.add_argument("--gpu-kontrol", action="store_true",
                    help="Yalnız GPU ve model kullanılabilirliğini raporla, çık")
    args = ap.parse_args()

    gpu = gpu_bilgisi()
    print("=" * 62)
    print(f"Fabrika GPU İşçisi  |  sunucu={args.server}")
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
            print(f"Flux2Pipeline: {hasattr(diffusers, 'Flux2Pipeline')}")
            print(f"WanPipeline: {hasattr(diffusers, 'WanPipeline')}")
            print(f"WanImageToVideoPipeline: {hasattr(diffusers, 'WanImageToVideoPipeline')}")
        except Exception as e:
            print(f"⚠️ diffusers/torch eksik: {e}")
        print(f"Önerilen modeller: {FLUX2_KLEIN} / {WAN21_T2V} / {WAN21_I2V}")
        return 0

    isci_id = args.isci_id or f"{_isci_turu()}_{uuid.uuid4().hex[:8]}"
    token = (args.token or "").strip() or None
    secenekler = {
        "kalite": args.kalite,
        "t2v_adim": args.t2v_adim,
        "i2v_adim": args.i2v_adim,
        "flux_adim": args.flux_adim,
    }
    sayac = {"tamam": 0}
    print(f"İşçi kimliği: {isci_id}")
    print(f"Kimlik doğrulama: {'Bearer + X-Worker-Key (ayarlı)' if token else 'YOK'}")
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


