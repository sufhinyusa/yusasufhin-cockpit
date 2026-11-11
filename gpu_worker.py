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
    POST /api/worker/progress    → ilerleme
    POST /api/worker/upload      → MP4 yükle (multipart)

KULLANIM (Kaggle / Colab hücresi)
    !git clone https://github.com/sufhinyusa/yusasufhin-cockpit.git
    %cd yusasufhin-cockpit
    !pip -q install -r requirements-gpu.txt
    !python gpu_worker.py --server https://yusasufhin.com --token <PIN> --tek-seferlik
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
WAN21_T2V = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
WAN21_I2V = "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers"

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


# -----------------------------------------------------------------------------
# 2. FLUX.2-klein-4B — GERÇEK görsel difüzyonu (3.88 B, T4'e sığar)
# -----------------------------------------------------------------------------
_FLUX_PIPE = None


def flux2_yukle(log=print):
    """FLUX.2-klein-4B boru hattını yükler (tek sefer, sonra cache)."""
    global _FLUX_PIPE
    if _FLUX_PIPE is not None:
        return _FLUX_PIPE

    import torch
    from diffusers import Flux2Pipeline

    log(f"⏳ {FLUX2_KLEIN} indiriliyor/yükleniyor…")
    pipe = Flux2Pipeline.from_pretrained(
        FLUX2_KLEIN, torch_dtype=_dtype(), low_cpu_mem_usage=True
    )
    # 16 GB T4 için zorunlu: model CPU'da bekler, katman katman GPU'ya taşınır
    pipe.enable_model_cpu_offload()
    pipe.vae.enable_slicing()
    try:
        pipe.transformer.enable_gradient_checkpointing()
    except Exception:
        pass
    _FLUX_PIPE = pipe
    log("✅ FLUX.2-klein-4B hazır")
    return pipe


def flux2_gorsel_uret(prompt: str, genislik: int, yukseklik: int,
                      adim: int = 4, tohum: int = 42, log=print) -> Path:
    """Prompt'tan GERÇEK FLUX.2 görseli üretir. Döner: PNG yolu."""
    import torch

    pipe = flux2_yukle(log=log)
    # 16'ya yuvarla (VAE 8x + patch 2x)
    w = max(256, (genislik // 16) * 16)
    h = max(256, (yukseklik // 16) * 16)
    uid = uuid.uuid4().hex[:8]
    hedef = Path(tempfile.gettempdir()) / f"flux2_{uid}.png"

    log(f"🎨 FLUX.2 difüzyon: {w}x{h}, {adim} adım, tohum={tohum}")
    uretici = torch.Generator(device="cpu").manual_seed(int(tohum))
    sonuc = pipe(
        prompt=prompt,
        width=w,
        height=h,
        num_inference_steps=max(1, min(50, int(adim))),
        generator=uretici,
    )
    gorsel = sonuc.images[0]
    gorsel.save(hedef, "PNG")
    log(f"✅ Görsel hazır: {hedef.stat().st_size // 1024} KB")
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




def wan21_video_uret(prompt: str, genislik: int, yukseklik: int,
                     sure_sn: float = 3.0, adim: int = 25,
                     tohum: int = 42, log=print) -> Path:
    """Wan2.1-T2V-1.3B ile GERÇEK metinden-videoya difüzyonu. Döner: MP4 yolu."""
    import torch
    from diffusers.utils import export_to_video

    pipe = wan21_t2v_yukle(log=log)
    # Wan 16 fps ve 4kare+1 yapısı ister; 480p sınıfı için 480/832 sınırı
    w = max(256, (genislik // 16) * 16)
    h = max(256, (yukseklik // 16) * 16)
    kare = int(max(17, min(81, round(sure_sn * 16))))
    kare = ((kare - 1) // 4) * 4 + 1

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
    export_to_video(sonuc.frames[0], str(hedef), fps=16)
    log(f"✅ Video hazır: {hedef.stat().st_size // 1024} KB")
    return hedef


def wan21_i2v_uret(gorsel_yolu: Path, prompt: str, genislik: int, yukseklik: int,
                   sure_sn: float = 3.0, adim: int = 20,
                   tohum: int = 42, log=print) -> Path:
    """Wan2.1-I2V-14B-480P ile GERÇEK görselden-videoya difüzyonu."""
    import torch
    from diffusers.utils import export_to_video, load_image

    pipe = wan21_i2v_yukle(log=log)
    gorsel = load_image(str(gorsel_yolu)).resize(
        (max(256, (genislik // 16) * 16), max(256, (yukseklik // 16) * 16))
    )
    kare = int(max(17, min(81, round(sure_sn * 16))))
    kare = ((kare - 1) // 4) * 4 + 1

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
    export_to_video(sonuc.frames[0], str(hedef), fps=16)
    log(f"✅ I2V video hazır: {hedef.stat().st_size // 1024} KB")
    return hedef


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



def gorev_isle(job: Dict[str, Any], secenekler: Dict[str, Any], log=print) -> Path:
    """Bir işi gerçek difüzyonla üretir ve çıktı yolunu döner.

    `method` eşlemesi:
        remotion_cinema / blender_wan / opus_canvas / viral_shorts
            → Wan2.1-T2V-1.3B (metinden video)
        wan_i2v  → Wan2.1-I2V-14B-480P (görselden video; `image_url` gerekir)
        flux2    → yalnız FLUX.2 görsel (MP4'e sarılır)
    """
    prompt = str(job.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("İş kaydında prompt yok — üretim yapılamaz")

    method = str(job.get("method") or "remotion_cinema").lower()
    oran = str(job.get("aspect_ratio") or "16:9")
    w, h = _cozunurluk(oran, secenekler.get("kalite", "480p"))
    tohum = int(job.get("seed") or 42)

    if method == "flux2":
        png = flux2_gorsel_uret(prompt, w, h, adim=secenekler.get("flux_adim", 4),
                                tohum=tohum, log=log)
        # Tek kareyi 3 sn'lik videoya sar (kullanıcı MP4 bekliyor)
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
        return hedef

    if method == "wan_i2v":
        kaynak = secenekler.get("image_path")
        if not kaynak or not Path(str(kaynak)).is_file():
            raise ValueError("wan_i2v için `image_path` gerekli (görsel yok)")
        return wan21_i2v_uret(
            Path(str(kaynak)), prompt, w, h,
            sure_sn=float(job.get("duration") or 3.0),
            adim=secenekler.get("i2v_adim", 20), tohum=tohum, log=log,
        )

    # Varsayılan: gerçek video difüzyonu (metinden videoya)
    return wan21_video_uret(
        prompt, w, h,
        sure_sn=float(job.get("duration") or 3.0),
        adim=secenekler.get("t2v_adim", 25), tohum=tohum, log=log,
    )


# -----------------------------------------------------------------------------
# 5. İŞÇİ PROTOKOLÜ (mevcut sunucu uçları)
# -----------------------------------------------------------------------------
def _istek(sunucu: str, yol: str, veri: Optional[dict] = None,
           token: Optional[str] = None, zaman_asimi: int = 60) -> Tuple[int, bytes]:
    url = sunucu.rstrip("/") + yol
    govde = None
    basliklar = {"Accept": "application/json"}
    if veri is not None:
        govde = json.dumps(veri).encode("utf-8")
        basliklar["Content-Type"] = "application/json"
    if token:
        basliklar["Authorization"] = f"Bearer {token}"
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
              durum: str = "idle", tamamlanan: int = 0) -> bool:
    kod, _ = _istek(sunucu, "/api/worker/heartbeat", {
        "worker_id": isci_id,
        "worker_type": tur,
        "gpu_name": gpu.get("ad") or "bilinmiyor",
        "vram_gb": gpu.get("vram_gb") or 0,
        "status": durum,
        "tasks_completed": tamamlanan,
    })
    return kod == 200


def is_al(sunucu: str, isci_id: str) -> Optional[Dict[str, Any]]:
    kod, govde = _istek(sunucu, f"/api/worker/claim?worker_id={urllib.parse.quote(isci_id)}")
    if kod != 200:
        return None
    try:
        return json.loads(govde).get("job")
    except Exception:
        return None


def ilerleme_bildir(sunucu: str, job_id: str, pct: int, asama: str) -> None:
    _istek(sunucu, "/api/worker/progress", {
        "job_id": job_id, "progress_pct": pct, "stage": asama,
    })


def yukle(sunucu: str, job_id: str, dosya: Path,
          token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Üretilen MP4'ü sunucuya yükler. Döner: sunucu yanıtı veya None."""
    sinir = "----Fabrika" + uuid.uuid4().hex
    govde = b"".join([
        f"--{sinir}\r\n".encode(),
        b'Content-Disposition: form-data; name="job_id"\r\n\r\n',
        job_id.encode(), b"\r\n",
        f"--{sinir}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{dosya.name}"\r\n'.encode(),
        b"Content-Type: video/mp4\r\n\r\n",
        dosya.read_bytes(), b"\r\n",
        f"--{sinir}--\r\n".encode(),
    ])
    basliklar = {"Content-Type": f"multipart/form-data; boundary={sinir}"}
    if token:
        basliklar["Authorization"] = f"Bearer {token}"
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
    job = is_al(sunucu, isci_id)
    if not job:
        return False

    jid = str(job.get("job_id") or job.get("id") or "")
    print(f"\n📥 İş alındı: {jid} | method={job.get('method')} | prompt={str(job.get('prompt'))[:60]}")
    ilerleme_bildir(sunucu, jid, 10, "Model yükleniyor")

    try:
        cikti = gorev_isle(job, secenekler, log=print)
    except Exception as e:
        print(f"❌ İş başarısız: {type(e).__name__}: {e}")
        ilerleme_bildir(sunucu, jid, 0, f"basarisiz: {str(e)[:120]}")
        return True

    ilerleme_bildir(sunucu, jid, 85, "Yükleniyor")
    yanit = yukle(sunucu, jid, cikti, token=token)
    if yanit and yanit.get("success"):
        sayac["tamam"] += 1
        print(f"✅ Yüklendi: {yanit.get('output_url')} "
              f"({yanit.get('file_size_bytes', 0) // 1024} KB)")
    else:
        print("❌ Yükleme başarısız — iş sunucuda 'isleniyor' kalacak")

    try:
        cikti.unlink(missing_ok=True)
    except Exception:
        pass
    _bosalt()
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Kaggle/Colab GPU işçisi — FLUX.2 görsel + Wan2.1 video difüzyonu"
    )
    ap.add_argument("--server", default=os.environ.get("FABRIKA_SUNUCU", VARSAYILAN_SUNUCU))
    ap.add_argument("--token", default=os.environ.get("FABRIKA_TOKEN"),
                    help="Yükleme için oturum tokenı (sunucu isterse)")
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
    secenekler = {
        "kalite": args.kalite,
        "t2v_adim": args.t2v_adim,
        "i2v_adim": args.i2v_adim,
        "flux_adim": args.flux_adim,
    }
    sayac = {"tamam": 0}
    print(f"İşçi kimliği: {isci_id}")
    print("=" * 62)

    if not heartbeat(args.server, isci_id, _isci_turu(), gpu, "idle", 0):
        print("⚠️ Sunucuya heartbeat gönderilemedi — yine de kuyruk denenecek")

    while True:
        try:
            is_var = _tek_is_isle(args.server, isci_id, secenekler, args.token, sayac)
        except KeyboardInterrupt:
            print("\n⏹️ Kullanıcı durdurdu")
            break
        except Exception as e:
            print(f"⚠️ Döngü hatası: {type(e).__name__}: {e}")
            is_var = False

        heartbeat(args.server, isci_id, _isci_turu(), gpu,
                  "idle" if not is_var else "busy", sayac["tamam"])

        if args.tek_seferlik:
            print(f"\nTek seferlik mod bitti. Tamamlanan iş: {sayac['tamam']}")
            break
        if not is_var:
            time.sleep(max(3, args.aralik))

    return 0


if __name__ == "__main__":
    sys.exit(main())


