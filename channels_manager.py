# -*- coding: utf-8 -*-
"""
channels_manager.py — Çoklu YouTube Kanalı, Görsel/I2V Model Kataloğu & Yayın Paketi
====================================================================================
Kural 1 (Dürüstlük): Yalnız doğrulanmış (gated=False) açık kaynak difüzyon modelleri
gerçek üretim olarak listelenir. YouTube API kimlik doğrulaması (`client_secret.json` +
geçerli OAuth token) yoksa yayın asla başarılı sayılmaz; açıkça "oauth_gerekli /
(simülasyon)" etiketi taşır.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Fabrika.ChannelsManager")

_STORE_LOCK = threading.Lock()

# Doğrulanmış (HF API gated=False) görsel üretim modelleri
IMAGE_MODELS: List[Dict[str, Any]] = [
    {
        "id": "flux2-klein",
        "repo": "black-forest-labs/FLUX.2-klein-4B",
        "ad": "FLUX.2 Klein 4B (Varsayılan — Yüksek Tutarlılık)",
        "kategori": "Genel / Sinematik / Mistik",
        "adim": 4,
        "vram": "T4 16GB (CPU Offload)",
        "pipeline": "Flux2KleinPipeline",
        "not": "En dengeli anahtar kare; I2V öncesinde temiz ışık ve kompozisyon verir.",
    },
    {
        "id": "z-image-turbo",
        "repo": "Tongyi-MAI/Z-Image-Turbo",
        "ad": "Z-Image Turbo 6B (Hızlı Fotorealizm & Tipografi)",
        "kategori": "3D / Fotorealizm / Tipografi",
        "adim": 8,
        "vram": "T4 16GB (CPU Offload)",
        "pipeline": "ZImagePipeline",
        "not": "8 adımda hızlı sahne ve net yazı/afiş kompozisyonu üretir.",
    },
    {
        "id": "realvis-xl",
        "repo": "SG161222/RealVisXL_V4.0",
        "ad": "RealVisXL V4.0 (Ultra Gerçekçi Sinema & Belgesel)",
        "kategori": "Sinematik / Belgesel",
        "adim": 24,
        "vram": "T4 16GB (FP16)",
        "pipeline": "StableDiffusionXLPipeline",
        "not": "Tarihi mekan, insan portresi ve belgesel kadrajlarında fotoğraf gerçekliği.",
    },
    {
        "id": "animagine-xl",
        "repo": "cagliostrolab/animagine-xl-3.1",
        "ad": "Animagine XL 3.1 (Anime & 2D Çizgi Film)",
        "kategori": "Anime / 2D İllüstrasyon",
        "adim": 24,
        "vram": "T4 16GB (FP16)",
        "pipeline": "StableDiffusionXLPipeline",
        "not": "Temiz cel-shading çizgiler ve anime sahne tutarlılığı.",
    },
    {
        "id": "sdxl-turbo",
        "repo": "stabilityai/sdxl-turbo",
        "ad": "SDXL Turbo (En Hızlı Konsept & 3D Çizgi)",
        "kategori": "Hızlı Ön İzleme / 3D",
        "adim": 4,
        "vram": "T4 16GB (FP16, Çok Hızlı)",
        "pipeline": "StableDiffusionXLPipeline",
        "not": "4 adımda hızlı karakter ve renk taslağı; guidance=0.0 ile çalışır.",
    },
]

# Doğrulanmış (HF API gated=False) Görselden-Videoya (I2V) & Video modelleri
I2V_MODELS: List[Dict[str, Any]] = [
    {
        "id": "wan2.1-i2v-14b",
        "repo": "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers",
        "ad": "Wan 2.1 I2V 14B (NF4 4-bit — En Yüksek Fizik & Yüz Sadakati)",
        "is_i2v": True,
        "tur": "i2v",
        "adim": 20,
        "fps": 16,
        "vram": "T4 16GB (NF4 4-bit)",
        "pipeline": "WanImageToVideoPipeline",
        "guclu": "Onayladığınız görseli bozmadan sinematik fizik ve kamera hareketiyle canlandırır.",
    },
    {
        "id": "wan2.2-ti2v-5b",
        "repo": "Wan-AI/Wan2.2-TI2V-5B-Diffusers",
        "ad": "Wan 2.2 TI2V 5B (Yeni Nesil Hızlı Hibrit I2V/T2V)",
        "is_i2v": True,
        "tur": "ti2v",
        "adim": 24,
        "fps": 24,
        "vram": "T4 16GB (CPU Offload)",
        "pipeline": "WanImageToVideoPipeline",
        "guclu": "5B tek gövdeli mimari: 14B'ye göre çok daha hızlı I2V ve metin takibi.",
    },
    {
        "id": "ltx-video",
        "repo": "Lightricks/LTX-Video",
        "ad": "LTX-Video (Hızlı Gerçek Zamanlı I2V — Shorts & Animasyon)",
        "is_i2v": True,
        "tur": "i2v",
        "adim": 25,
        "fps": 24,
        "vram": "T4 16GB (BF16/FP16)",
        "pipeline": "LTXImageToVideoPipeline",
        "guclu": "T4 üzerinde çok hızlı animasyon ve seri Shorts üretimi.",
    },
    {
        "id": "cogvideox-5b-i2v",
        "repo": "THUDM/CogVideoX-5b-I2V",
        "ad": "CogVideoX 5B I2V (3D Animasyon & Akıcı Kamera Hareketi)",
        "is_i2v": True,
        "tur": "i2v",
        "adim": 25,
        "fps": 8,
        "vram": "T4 16GB (CPU Offload)",
        "pipeline": "CogVideoXImageToVideoPipeline",
        "guclu": "3D Pixar benzeri ve stilize illüstrasyonlarda yumuşak süreklilik.",
    },
    {
        "id": "svd-xt",
        "repo": "stabilityai/stable-video-diffusion-img2vid-xt",
        "ad": "Stable Video Diffusion XT (Klasik Atmosferik I2V)",
        "is_i2v": True,
        "tur": "i2v",
        "adim": 25,
        "fps": 7,
        "vram": "T4 16GB (FP16)",
        "pipeline": "StableVideoDiffusionPipeline",
        "guclu": "Manzara, uzay, burç kozmosu ve yumuşak paralaks hareketleri.",
    },
    {
        "id": "wan2.1-t2v-1.3b",
        "repo": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
        "ad": "Wan 2.1 T2V 1.3B (Yalnız Doğrudan Metinden Video — Görselsiz)",
        "is_i2v": False,
        "tur": "t2v",
        "adim": 25,
        "fps": 16,
        "vram": "T4 16GB (CPU Offload)",
        "pipeline": "WanPipeline",
        "guclu": "Önce görsel üretilmeden hızlı taslak T2V için (düşük görsel tutarlılık riski).",
    },
]

# Video üretim iş akışları (kullanıcı önceliği: Önce Görsel -> Onay -> I2V)
PRODUCTION_WORKFLOWS: List[Dict[str, str]] = [
    {
        "id": "image_first_preview",
        "ad": "1. Önce Görsel Üret → Onayla → I2V Videoya Çevir (Önerilen)",
        "ozet": "Seçili görsel modeliyle anahtar kare üretir; siz beğendiğinizde seçili I2V modeline geçer.",
    },
    {
        "id": "image_then_i2v",
        "ad": "2. Otomatik 2 Aşama: Görsel Üret + Hemen I2V ile Canlandır",
        "ozet": "Tek tıkta önce anahtar kare çizer, ardından aynı görseli seçili I2V modeline verir.",
    },
    {
        "id": "wan_i2v",
        "ad": "3. Hazır/Yüklenen Görselden Doğrudan I2V",
        "ozet": "Yüklediğiniz kendi PNG/JPG görselinizi doğrudan seçili I2V modeliyle videoya çevirir.",
    },
    {
        "id": "hyperframes_motion",
        "ad": "4. HyperFrames Sinematik Motion + Kinetik Yazı (#296)",
        "ozet": "Anında HTML5 zaman çizelgesi + çoklu xfade geçiş + ilk-kare kalite kontrolüyle H.264 MP4 üretir.",
    },
    {
        "id": "product_launch",
        "ad": "5. Web Sitesi URL → Lansman Videosu (product-launch-motion)",
        "ozet": "Girilen URL içeriğini okuyup çok sahneli ürün tanıtım/lansman videosu üretir.",
    },
    {
        "id": "t2v_direct",
        "ad": "6. Doğrudan T2V (Metinden Video — Görsel Adımı Olmadan)",
        "ozet": "Ara görsel olmadan doğrudan video difüzyonu çalıştırır.",
    },
    {
        "id": "opus_canvas",
        "ad": "7. Opus Canvas / Kod Motion Grafik (Sunucu/Deterministik)",
        "ozet": "Metrik, tipografi ve açıklayıcı hareketli grafik kurgusu.",
    },
    {
        "id": "remotion_cinema",
        "ad": "8. Remotion Cinema Kurgu / GPU İşçisi",
        "ozet": "Kanal stili + TTS seslendirme ile kurgu veya GPU difüzyon hattı.",
    },
]

# Kanal bazlı görsel & animasyon tarzları
STYLE_PRESETS: List[Dict[str, str]] = [
    {
        "id": "cinematic_realism",
        "ad": "🎬 Sinematik Realizm (Film)",
        "prompt_suffix": "cinematic 35mm film still, dramatic chiaroscuro volumetric lighting, crisp depth of field, rich realistic textures, ultra-detailed coherent subject",
        "negative_prompt": "blurry, deformed hands, flickering artifacts, text watermark, lowres, oversaturated plasticity",
        "motion_default": "smooth steady cinema push-in camera movement, subtle wind and natural atmospheric light shift, preserve exact subject composition",
    },
    {
        "id": "pixar_3d_animation",
        "ad": "🧸 3D Animasyon (Pixar / Blender Tarzı)",
        "prompt_suffix": "high-end 3D CGI animated movie frame, stylized expressive characters, soft subsurface scattering, warm studio rim lighting, coherent 3D geometry, vibrant clean palette",
        "negative_prompt": "photorealistic grain, uncanny Valley, flat 2D, deformed limbs, muddy colors, text artifacts",
        "motion_default": "gentle 3D camera dolly arc, expressive character blink and smooth stylized cloth/hair physics motion",
    },
    {
        "id": "anime_2d",
        "ad": "⛩️ Anime & 2D Çizgi Evren",
        "prompt_suffix": "masterpiece anime keyframe illustration, clean crisp lineart, cel shading, Makoto Shinkai luminous sky lighting, vibrant expressive anime composition",
        "negative_prompt": "3d render, photorealistic, blurry lines, extra fingers, western cartoon, text overlays",
        "motion_default": "dynamic anime sakuga breeze through hair and coat, floating light motes, gentle parallax camera pan",
    },
    {
        "id": "astrology_mystic",
        "ad": "♈ Astroloji & Kozmik Mistik (Burçlar)",
        "prompt_suffix": "mystical celestial astrology artwork, luminous golden zodiac constellation geometry glowing in deep cosmic nebula, ethereal stardust, atmospheric cinema lighting",
        "negative_prompt": "modern office, neon clutter, lowres text, blurry stars, distorted symbols",
        "motion_default": "slow hypnotic cosmic orbit, shimmering constellation golden energy flow and drifting nebula dust",
    },
    {
        "id": "tech_futuristic",
        "ad": "🤖 Yapay Zeka, Kod & Fütürizm",
        "prompt_suffix": "clean futuristic sci-fi hardware laboratory aesthetic, intricate glowing silicon circuitry, sleek obsidian and cyan glass, architectural macro photography",
        "negative_prompt": "messy wires, illegible gibbersh text, sepia retro, blurry background",
        "motion_default": "precision macro slider push-in, subtle pulsing holographic data light paths, clean metallic reflections",
    },
    {
        "id": "history_documentary",
        "ad": "🏛️ Tarih & Kültür Belgeseli",
        "prompt_suffix": "museum-grade historical reconstruction cinematography, torch and golden hour stone reflections, authentic period architecture and wardrobe, 8k documentary still",
        "negative_prompt": "modern clothing, neon lights, anime, cartoon, plastic sheen",
        "motion_default": "reverent slow documentary crane pan, flickering torchlight shadows and drifting dust in sunbeams",
    },
    {
        "id": "minimal_explainer",
        "ad": "📊 Bilgi, Eğitim & Hareketli İnfografik",
        "prompt_suffix": "clean editorial studio isometric visual, crisp geometric forms, bold dark slate background with emerald and gold focal accents, balanced negative space",
        "negative_prompt": "visual clutter, photorealistic crowd, harsh shadows, noise",
        "motion_default": "calm steady studio reveal pan with subtle floating geometric parallax",
    },
]

CAMERA_MOTIONS: List[Dict[str, str]] = [
    {"id": "otomatik", "ad": "Otomatik (Stile Uygun)", "prompt": ""},
    {"id": "push_in", "ad": "Yavaş Yakınlaşma (Push-In)", "prompt": "slow steady cinematic camera push-in toward the focal subject"},
    {"id": "pull_out", "ad": "Yavaş Uzaklaşma (Reveal Pull-Out)", "prompt": "smooth slow pull-back revealing the grand environment around the subject"},
    {"id": "orbital", "ad": "Yörünge Dönüşü (360° Orbital)", "prompt": "graceful gentle orbital arc rotating softly around the central subject"},
    {"id": "pan_right", "ad": "Yatay Kaydırma (Pan Right)", "prompt": "smooth horizontal tracking pan from left to right across the scene"},
    {"id": "wind_cloth_glow", "ad": "Sabit Kadraj + Rüzgar & Işık Akışı", "prompt": "locked stable framing while wind ripples fabric/hair and ambient particles shimmer softly"},
]

GEMINI_VOICES: List[Dict[str, str]] = [
    {"id": "Aoede", "ad": "🎙️ Aoede (Sıcak, Etkileyici Kadın — Astroloji, Hikaye & YouTube)"},
    {"id": "Puck", "ad": "⚡ Puck (Dinamik, Enerjik Erkek — Teknoloji, Animasyon & Shorts)"},
    {"id": "Charon", "ad": "🏛️ Charon (Derin, Otoriter Erkek — Belgesel, Tarih & Felsefe)"},
    {"id": "Kore", "ad": "📰 Kore (Net, Sakin Kadın — Eğitim, Analiz & Haber)"},
    {"id": "Fenrir", "ad": "🔥 Fenrir (Güçlü, Dramatik Erkek — Sinematik Fragman & Aksiyon)"},
    {"id": "none", "ad": "🔇 Sessiz (Sadece Video)"},
]

DEFAULT_CHANNELS: List[Dict[str, Any]] = [
    {
        "id": "Astroloji_Kova",
        "name": "Astroloji & Burçlar (Kova Kozmos)",
        "handle": "@astrolojikova",
        "style_preset": "astrology_mystic",
        "image_model": "flux2-klein",
        "i2v_model": "wan2.1-i2v-14b",
        "workflow": "image_first_preview",
        "aspect_ratio": "9:16",
        "voice": "Aoede",
        "duration": 5,
        "camera_motion": "orbital",
        "privacy": "private",
        "tags": ["astroloji", "burclar", "kovaburcu", "gokyuzu", "shorts"],
        "youtube_channel_id": "",
        "youtube_connected": False,
        "default_prompt": "Kova burcu için mor-mavi bulutsu içinde altın astrolab ve kozmik gezegen hizalanması",
    },
    {
        "id": "Animasyon_3D",
        "name": "3D Animasyon & Hikaye Stüdyosu",
        "handle": "@fabrika3danimasyon",
        "style_preset": "pixar_3d_animation",
        "image_model": "z-image-turbo",
        "i2v_model": "cogvideox-5b-i2v",
        "workflow": "image_first_preview",
        "aspect_ratio": "16:9",
        "voice": "Puck",
        "duration": 5,
        "camera_motion": "push_in",
        "privacy": "private",
        "tags": ["3danimasyon", "hikaye", "aiAnimation", "cgimovie"],
        "youtube_channel_id": "",
        "youtube_connected": False,
        "default_prompt": "Büyülü antik bir kütüphanede parlayan minik robot ve meraklı baykuş, sıcak 3D animasyon ışığı",
    },
    {
        "id": "Anime_Evreni",
        "name": "Anime & Fantastik Çizgi Evren",
        "handle": "@animeevreni",
        "style_preset": "anime_2d",
        "image_model": "animagine-xl",
        "i2v_model": "ltx-video",
        "workflow": "image_first_preview",
        "aspect_ratio": "9:16",
        "voice": "Aoede",
        "duration": 5,
        "camera_motion": "wind_cloth_glow",
        "privacy": "private",
        "tags": ["anime", "cizgifilm", "fantastik", "aianime"],
        "youtube_channel_id": "",
        "youtube_connected": False,
        "default_prompt": "Yağmurlu neon Tokyo çatısında kılıcını tutan genç gezgin, parlayan mor gökyüzü, 2D anime stili",
    },
    {
        "id": "Tech_AI_Fabrika",
        "name": "Fabrika AI & Gelecek Teknolojisi",
        "handle": "@fabrikaaitech",
        "style_preset": "tech_futuristic",
        "image_model": "flux2-klein",
        "i2v_model": "wan2.2-ti2v-5b",
        "workflow": "image_first_preview",
        "aspect_ratio": "16:9",
        "voice": "Puck",
        "duration": 5,
        "camera_motion": "push_in",
        "privacy": "private",
        "tags": ["yapayzeka", "teknoloji", "bilim", "aivideo"],
        "youtube_channel_id": "",
        "youtube_connected": False,
        "default_prompt": "Karanlık veri merkezinde holografik sinirsel çip çekirdeği, turkuaz ve kehribar lazer hatları",
    },
    {
        "id": "Belgesel_Sinematik",
        "name": "İstanbul & Tarih Sinematik Belgeseli",
        "handle": "@tarihbelgeseli",
        "style_preset": "history_documentary",
        "image_model": "realvis-xl",
        "i2v_model": "wan2.1-i2v-14b",
        "workflow": "image_first_preview",
        "aspect_ratio": "16:9",
        "voice": "Charon",
        "duration": 5,
        "camera_motion": "pan_right",
        "privacy": "private",
        "tags": ["tarih", "belgesel", "istanbul", "sinema"],
        "youtube_channel_id": "",
        "youtube_connected": False,
        "default_prompt": "İstanbul Yerebatan Sarnıcı mermer sütunları arasında yanan meşaleler ve durgun su yansıması",
    },
    {
        "id": "Viral_Shorts",
        "name": "Viral Sinematik Shorts & Hızlı Kanca",
        "handle": "@viralshortsai",
        "style_preset": "cinematic_realism",
        "image_model": "sdxl-turbo",
        "i2v_model": "ltx-video",
        "workflow": "image_then_i2v",
        "aspect_ratio": "9:16",
        "voice": "Fenrir",
        "duration": 5,
        "camera_motion": "pull_out",
        "privacy": "private",
        "tags": ["shorts", "viral", "cinematic", "ai"],
        "youtube_channel_id": "",
        "youtube_connected": False,
        "default_prompt": "Okyanus ortasında gökyüzüne açılan dev antik taş kapı, dramatik fırtına ve altın ışık huzmesi",
    },
]


def _by_id(items: List[Dict[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
    return {str(it["id"]): it for it in items}


IMAGE_MODEL_MAP = _by_id(IMAGE_MODELS, "id")
I2V_MODEL_MAP = _by_id(I2V_MODELS, "id")
STYLE_MAP = _by_id(STYLE_PRESETS, "id")
CAMERA_MAP = _by_id(CAMERA_MOTIONS, "id")


def compose_story_plan(
    prompt: str,
    style_preset: str = "cinematic_realism",
    camera_motion: str = "otomatik",
    negative_prompt: str = "",
    scene_count: int = 3,
    duration_sec: float = 5.0,
) -> Dict[str, Any]:
    """Konudan anlatım (TR) + somut İngilizce sahneler + hareket planı üretir."""
    try:
        from prompt_director import plan_visual_scenes

        return plan_visual_scenes(
            prompt=prompt,
            style_preset=style_preset,
            camera_motion=camera_motion,
            scene_count=scene_count,
            duration_sec=duration_sec,
            negative_prompt=negative_prompt,
            use_llm=True,
        )
    except Exception:
        temiz_prompt = str(prompt or "").strip() or "Sinematik özgün sahne"
        stil = STYLE_MAP.get(str(style_preset or "").strip(), STYLE_PRESETS[0])
        cam = CAMERA_MAP.get(str(camera_motion or "").strip(), CAMERA_MOTIONS[0])
        suffix = stil.get("prompt_suffix", "")
        ip = (f"{temiz_prompt}, {suffix}" if suffix else temiz_prompt)[:1200]
        hareket = cam.get("prompt") or stil.get("motion_default") or ""
        mp = (
            f"{hareket}, based closely on the reference frame, consistent character and lighting"
            if hareket else stil.get("motion_default", "")
        )[:500]
        neg = (str(negative_prompt or "").strip() or stil.get("negative_prompt", ""))[:400]
        return {
            "narration_text": temiz_prompt,
            "image_prompt": ip,
            "motion_prompt": mp,
            "negative_prompt": neg,
            "scenes": [{"image_prompt": ip, "motion_prompt": mp}],
            "planner_source": "fallback",
            "simulasyon": True,
        }


def compose_prompts(
    prompt: str,
    style_preset: str = "cinematic_realism",
    camera_motion: str = "otomatik",
    negative_prompt: str = "",
) -> Tuple[str, str, str]:
    """Kullanıcı istemini somut İngilizce görsel sahne ve hareket istemine çevirir."""
    plan = compose_story_plan(
        prompt=prompt,
        style_preset=style_preset,
        camera_motion=camera_motion,
        negative_prompt=negative_prompt,
        scene_count=1,
    )
    return plan["image_prompt"][:1200], plan["motion_prompt"][:500], plan["negative_prompt"][:400]


def get_full_catalog() -> Dict[str, Any]:
    """UI kaydırmalı listeler için tüm gerçek modelleri, tarzları ve iş akışlarını döner."""
    return {
        "image_models": IMAGE_MODELS,
        "i2v_models": I2V_MODELS,
        "workflows": PRODUCTION_WORKFLOWS,
        "styles": STYLE_PRESETS,
        "camera_motions": CAMERA_MOTIONS,
        "voices": GEMINI_VOICES,
    }


def _slugify_channel_id(name: str) -> str:
    temiz = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "").strip()).strip("_")
    return (temiz or f"Kanal_{int(time.time())}")[:48]


class ChannelStore:
    """Kalıcı çoklu YouTube kanalı profili ve yayın paketi yöneticisi."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.channels_file = self.data_dir / "youtube_channels.json"
        self.auth_dir = self.data_dir / "youtube_auth"

    def _load_unlocked(self) -> List[Dict[str, Any]]:
        if not self.channels_file.is_file():
            return [dict(c) for c in DEFAULT_CHANNELS]
        try:
            raw = json.loads(self.channels_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("channels"), list):
                return raw["channels"]
            if isinstance(raw, list):
                return raw
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("[Channels] youtube_channels.json okunamadı: %s", e)
        return [dict(c) for c in DEFAULT_CHANNELS]

    def _save_unlocked(self, channels: List[Dict[str, Any]]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.channels_file.with_name(f".{self.channels_file.name}.{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps({"channels": channels, "updated_at": time.time()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.channels_file)

    def _enrich_channel(self, ch: Dict[str, Any]) -> Dict[str, Any]:
        kayit = dict(ch)
        cid = str(kayit.get("id") or "")
        kayit["youtube_token_present"] = (self.auth_dir / f"{cid}_token.json").is_file() or (
            self.auth_dir / "youtube_token.json"
        ).is_file()
        kayit["youtube_connected"] = bool(
            kayit.get("youtube_channel_id") and kayit["youtube_token_present"]
        )
        return kayit

    def list_channels(self) -> List[Dict[str, Any]]:
        with _STORE_LOCK:
            channels = self._load_unlocked()
            if not self.channels_file.is_file():
                self._save_unlocked(channels)
            return [self._enrich_channel(c) for c in channels]

    def get_channel(self, channel_id: str) -> Optional[Dict[str, Any]]:
        cid = str(channel_id or "").strip()
        for ch in self.list_channels():
            if ch.get("id") == cid:
                return ch
        return None

    def upsert_channel(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Kanal verisi dict olmalıdır.")
        name = str(payload.get("name") or payload.get("id") or "").strip()
        if not name:
            raise ValueError("Kanal adı zorunludur.")
        cid = _slugify_channel_id(str(payload.get("id") or name))

        style = str(payload.get("style_preset") or "cinematic_realism")
        if style not in STYLE_MAP:
            style = "cinematic_realism"
        img_model = str(payload.get("image_model") or "flux2-klein")
        if img_model not in IMAGE_MODEL_MAP:
            img_model = "flux2-klein"
        i2v_model = str(payload.get("i2v_model") or "wan2.1-i2v-14b")
        if i2v_model not in I2V_MODEL_MAP:
            i2v_model = "wan2.1-i2v-14b"
        wf = str(payload.get("workflow") or "image_first_preview")
        if wf not in {w["id"] for w in PRODUCTION_WORKFLOWS}:
            wf = "image_first_preview"

        try:
            dur = max(3, min(60, int(payload.get("duration") or 5)))
        except (TypeError, ValueError):
            dur = 5

        raw_tags = payload.get("tags")
        if isinstance(raw_tags, str):
            tags = [t.strip().lstrip("#") for t in re.split(r"[,#\s]+", raw_tags) if t.strip()][:15]
        elif isinstance(raw_tags, list):
            tags = [str(t).strip().lstrip("#") for t in raw_tags if str(t).strip()][:15]
        else:
            tags = ["fabrika", "aivideo", style]

        kayit: Dict[str, Any] = {
            "id": cid,
            "name": name[:80],
            "handle": str(payload.get("handle") or f"@{cid.lower()}")[:50],
            "style_preset": style,
            "image_model": img_model,
            "i2v_model": i2v_model,
            "workflow": wf,
            "aspect_ratio": str(payload.get("aspect_ratio") or "16:9")[:8],
            "voice": str(payload.get("voice") or "Aoede")[:24],
            "duration": dur,
            "camera_motion": str(payload.get("camera_motion") or "otomatik")[:32],
            "privacy": str(payload.get("privacy") or "private") if payload.get("privacy") in ("private", "unlisted", "public") else "private",
            "tags": tags,
            "youtube_channel_id": str(payload.get("youtube_channel_id") or "").strip()[:64],
            "default_prompt": str(payload.get("default_prompt") or "")[:400],
            "updated_at": time.time(),
        }

        with _STORE_LOCK:
            channels = self._load_unlocked()
            guncellendi = False
            for idx, eski in enumerate(channels):
                if eski.get("id") == cid:
                    channels[idx] = {**eski, **kayit}
                    guncellendi = True
                    break
            if not guncellendi:
                channels.append(kayit)
            self._save_unlocked(channels)
        return self._enrich_channel(kayit)

    def delete_channel(self, channel_id: str) -> bool:
        cid = str(channel_id or "").strip()
        with _STORE_LOCK:
            channels = self._load_unlocked()
            yeni = [c for c in channels if c.get("id") != cid]
            if len(yeni) == len(channels):
                return False
            self._save_unlocked(yeni)
            return True

    def get_youtube_status(self, channel_id: Optional[str] = None) -> Dict[str, Any]:
        """YouTube API v3 kimlik doğrulama durumunu dürüstçe raporlar (asla uydurmaz)."""
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        client_secret = self.auth_dir / "client_secret.json"
        token_global = self.auth_dir / "youtube_token.json"
        token_ch = (self.auth_dir / f"{_slugify_channel_id(channel_id)}_token.json") if channel_id else None
        token_exists = bool(
            (token_ch and token_ch.is_file())
            or token_global.is_file()
            or os.environ.get("YOUTUBE_REFRESH_TOKEN")
        )
        try:
            import googleapiclient.discovery  # noqa: F401
            api_lib_ok = True
        except ImportError:
            api_lib_ok = False

        ready = client_secret.is_file() and token_exists and api_lib_ok
        return {
            "ready_for_live_upload": ready,
            "client_secret_present": client_secret.is_file(),
            "oauth_token_present": token_exists,
            "google_api_client_installed": api_lib_ok,
            "status": "active" if ready else "not_authenticated",
            "message": (
                "YouTube Data API v3 canlı yükleme için hazır."
                if ready
                else "YouTube OAuth kimlik bilgisi (client_secret.json / token) henüz bağlı değil. Videolar SEO paketi + kapak görseliyle yerel olarak hazırlanır (simülasyon)."
            ),
        }

    def save_client_secret(self, raw_json: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Geçersiz client_secret.json: {e}") from e
        if not isinstance(parsed, dict) or not any(k in parsed for k in ("installed", "web")):
            raise ValueError("Google OAuth client_secret.json içinde 'installed' veya 'web' anahtarı bulunamadı.")
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        (self.auth_dir / "client_secret.json").write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self.get_youtube_status()

    def _read_oauth_client(self) -> Dict[str, Any]:
        cs_file = self.auth_dir / "client_secret.json"
        if not cs_file.is_file():
            raise ValueError("Önce Google Cloud client_secret.json anahtarını kaydedin.")
        parsed = json.loads(cs_file.read_text(encoding="utf-8"))
        cfg = parsed.get("web") or parsed.get("installed")
        if not isinstance(cfg, dict) or not cfg.get("client_id") or not cfg.get("client_secret"):
            raise ValueError("client_secret.json içinde client_id / client_secret eksik.")
        return cfg

    def build_oauth_authorize_url(self, channel_id: str, redirect_uri: str) -> str:
        import urllib.parse

        cfg = self._read_oauth_client()
        cid = _slugify_channel_id(channel_id) if channel_id else "default"
        params = urllib.parse.urlencode({
            "client_id": cfg["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly",
            "access_type": "offline",
            "prompt": "consent",
            "state": cid,
        })
        auth_uri = cfg.get("auth_uri") or "https://accounts.google.com/o/oauth2/auth"
        return f"{auth_uri}?{params}"

    def exchange_oauth_code(self, channel_id: str, code: str, redirect_uri: str) -> Dict[str, Any]:
        import urllib.parse
        import urllib.request

        cfg = self._read_oauth_client()
        token_uri = cfg.get("token_uri") or "https://oauth2.googleapis.com/token"
        data = urllib.parse.urlencode({
            "code": code.strip(),
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }).encode("utf-8")
        req = urllib.request.Request(
            token_uri, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            tok = json.loads(resp.read().decode("utf-8"))
        if not tok.get("access_token"):
            raise ValueError("Google OAuth token yanıtında access_token yok.")
        tok_out = {
            "token": tok["access_token"],
            "refresh_token": tok.get("refresh_token"),
            "token_uri": token_uri,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "scopes": ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"],
        }
        cid = _slugify_channel_id(channel_id) if channel_id and channel_id != "default" else ""
        fname = f"{cid}_token.json" if cid else "youtube_token.json"
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        (self.auth_dir / fname).write_text(json.dumps(tok_out, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"saved_token_file": fname, **self.get_youtube_status(cid or None)}

    def build_publish_bundle(self, job: Dict[str, Any], media_dir: Path) -> Dict[str, Any]:
        """Tamamlanmış video + anahtar kare kapak görseli + SRT için YouTube yayın paketi üretir."""
        jid = str(job.get("job_id") or job.get("id") or "")
        if not jid:
            raise ValueError("Geçersiz iş kimliği.")

        channel_id = str(job.get("channel") or "Genel")
        ch = self.get_channel(channel_id)
        stil_ad = STYLE_MAP.get(str(job.get("style_preset") or (ch or {}).get("style_preset") or ""), {}).get("ad", "Sinematik")
        raw_prompt = str(job.get("narration_text") or job.get("prompt") or jid).strip()
        konu_ozeti = re.sub(r"\s+", " ", raw_prompt).split(",")[0][:78]
        aspect = str(job.get("aspect_ratio") or (ch or {}).get("aspect_ratio") or "16:9")
        is_shorts = aspect.replace(" ", "") == "9:16"
        title = (f"{konu_ozeti} #Shorts" if is_shorts and "#shorts" not in konu_ozeti.lower() else konu_ozeti)[:98]

        tags = list((ch or {}).get("tags") or ["ai", "fabrika"])
        for t in ("yusasufhin", "aivideo"):
            if t not in tags:
                tags.append(t)
        hashtags = " ".join(f"#{t}" for t in tags[:8])
        desc = (
            f"{raw_prompt}\n\n"
            f"Kanal: {(ch or {}).get('name') or channel_id} ({(ch or {}).get('handle') or ''})\n"
            f"Üretim Hattı: {stil_ad} | Görsel: {job.get('image_model') or '-'} → Video: {job.get('video_model') or job.get('i2v_model') or '-'}\n\n"
            f"{hashtags}"
        ).strip()[:4500]

        thumb_url = job.get("preview_image_url") or job.get("input_image_url")
        srt_file = media_dir / f"{jid}.srt"
        ass_file = media_dir / f"{jid}.ass"
        sub_url = (
            f"/api/media/file?path={srt_file.name}"
            if srt_file.is_file()
            else (f"/api/media/file?path={ass_file.name}" if ass_file.is_file() else None)
        )
        yt_state = self.get_youtube_status(channel_id)

        bundle = {
            "job_id": jid,
            "channel_id": channel_id,
            "channel_name": (ch or {}).get("name") or channel_id,
            "youtube_channel_id": (ch or {}).get("youtube_channel_id") or "",
            "title": title,
            "description": desc,
            "tags": tags,
            "privacy": (ch or {}).get("privacy") or "private",
            "is_shorts": is_shorts,
            "video_url": job.get("output_url"),
            "download_url": job.get("download_url"),
            "thumbnail_url": thumb_url,
            "subtitle_url": sub_url,
            "youtube_auth": yt_state,
            "created_at": time.time(),
        }
        try:
            media_dir.mkdir(parents=True, exist_ok=True)
            (media_dir / f"{jid}_youtube.json").write_text(
                json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as e:
            logger.warning("[Channels] YouTube paketi yazılamadı (%s): %s", jid, e)
        return bundle

    def attempt_youtube_upload(self, job: Dict[str, Any], media_dir: Path) -> Dict[str, Any]:
        """Gerçek YouTube OAuth token varsa yükler; yoksa dürüstçe (simülasyon) + bundle döner."""
        bundle = self.build_publish_bundle(job, media_dir)
        jid = bundle["job_id"]
        video_path = media_dir / f"{jid}.mp4"
        if not video_path.is_file():
            return {
                "success": False,
                "simulasyon": False,
                "status": "video_yok",
                "bundle": bundle,
                "message": "Video MP4 dosyası henüz üretilmemiş; önce GPU render tamamlanmalı.",
            }
        yt_state = bundle["youtube_auth"]
        if not yt_state["ready_for_live_upload"]:
            return {
                "success": False,
                "simulasyon": True,
                "status": "oauth_gerekli",
                "bundle": bundle,
                "message": f"(simülasyon) {yt_state['message']} Yayın paketi ({jid}_youtube.json) hazırlandı.",
            }
        # Gerçek googleapiclient yükleme yolu
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload

            cid = _slugify_channel_id(bundle["channel_id"])
            tok_file = self.auth_dir / f"{cid}_token.json"
            if not tok_file.is_file():
                tok_file = self.auth_dir / "youtube_token.json"
            creds = Credentials.from_authorized_user_file(
                str(tok_file), ["https://www.googleapis.com/auth/youtube.upload"]
            )
            srv = build("youtube", "v3", credentials=creds)
            req = srv.videos().insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": bundle["title"][:100],
                        "description": bundle["description"][:5000],
                        "tags": bundle["tags"][:15],
                        "categoryId": "22",
                    },
                    "status": {
                        "privacyStatus": bundle["privacy"],
                        "selfDeclaredMadeForKids": False,
                    },
                },
                media_body=MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4"),
            )
            resp = req.execute()
            vid_id = resp.get("id")
            return {
                "success": True,
                "simulasyon": False,
                "status": "uploaded",
                "youtube_video_id": vid_id,
                "youtube_url": f"https://www.youtube.com/watch?v={vid_id}" if vid_id else None,
                "bundle": bundle,
                "message": "Video YouTube kanalına başarıyla yüklendi.",
            }
        except Exception as e:
            logger.error("[Channels] YouTube canlı yükleme hatası (%s): %s", jid, e)
            return {
                "success": False,
                "simulasyon": False,
                "status": "upload_hatasi",
                "bundle": bundle,
                "message": f"YouTube yükleme hatası: {type(e).__name__}: {str(e)[:180]}",
            }
