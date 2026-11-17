# -*- coding: utf-8 -*-
"""
prompt_director.py — Türkçe Konuyu Somut İngilizce Görsel Sahnelere Çeviren Yönetmen Planlayıcı
===============================================================================================
NEDEN VAR:
Canlı sitede "♒ Kova Burcu Haftalık Analizi: Gezegen kavuşumları ve sezgisel uyanış dönemi"
isteminin doğrudan FLUX.1-schnell'e ham Türkçe metin olarak gönderilmesi sonucu model
"uyanış / analiz" kelimelerini yanlış yorumlayıp alakasız bir yakın çekim insan gözü üretti.

Bu modül her kullanıcı istemini 3 ayrı parçaya böler:
  1. `narration_text` — Türkçe seslendirme ve SRT/ASS altyazı metni
  2. `scenes`         — Her sahne için somut İNGİLİZCE görsel sahne (`image_prompt`)
                        ve kamera/fizik hareketi (`motion_prompt`)
  3. `negative_prompt` — İstenmeyen artefakt/bozulma filtreleri
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff\u2600-\u27bf]+", flags=re.UNICODE)
_TR_CHARS_RE = re.compile(r"[çğıöşüÇĞİÖŞÜ]")

_ABSTRACT_NOISE = {
    "analiz", "analizi", "haftalik", "haftalık", "gunluk", "günlük", "aylik", "aylık",
    "donem", "dönemi", "donemi", "hakkinda", "hakkında", "konusu", "videosu", "video",
    "shorts", "reels", "bolum", "bölüm", "olsun", "lutfen", "lütfen", "yap", "uret",
    "üret", "cevir", "çevir", "hazirla", "hazırla", "goster", "göster", "anlat",
    "devrimi", "devrim", "uyanisi", "uyaniş", "uyanış", "sezgisel", "konulu", "tarzi",
    "tarzı", "ile", "icin", "için", "ve", "bir", "bu", "su", "şu",
}

# Türkçe kök/gövde -> Somut İngilizce görsel sahne öğeleri (CLIP/FLUX/Wan uyumlu)
_VISUAL_STEM_MAP: Tuple[Tuple[str, str], ...] = (
    # Astroloji & Burçlar & Gökyüzü Figürleri
    ("kova", "mythic Aquarius celestial water-bearer holding an ornate glowing vessel and pouring luminous cosmic water streams beneath sapphire nebula clouds"),
    ("akrep", "mystical Scorpio constellation crimson crystal desert horizon under glowing milky way"),
    ("koc", "celestial Aries golden ram silhouette atop volcanic mountain peaks under fiery aurora sky"),
    ("koç", "celestial Aries golden ram silhouette atop volcanic mountain peaks under fiery aurora sky"),
    ("boga", "serene Taurus emerald sacred valley with golden olive groves beneath warm moonrise"),
    ("boğa", "serene Taurus emerald sacred valley with golden olive groves beneath warm moonrise"),
    ("ikizler", "ethereal Gemini twin silver observatory mirrors reflecting dual glowing moons"),
    ("yengec", "luminous Cancer silver crescent tide reflecting bioluminescent ocean waves at night"),
    ("yengeç", "luminous Cancer silver crescent tide reflecting bioluminescent ocean waves at night"),
    ("aslan", "radiant Leo solar eclipse golden crown flare above sunlit ancient marble colosseum"),
    ("basak", "intricate Virgo cosmic botanical greenhouse with golden astrolabe rings and floating petals"),
    ("başak", "intricate Virgo cosmic botanical greenhouse with golden astrolabe rings and floating petals"),
    ("terazi", "symmetrical Libra golden celestial scales hovering over tranquil twilight marble temple"),
    ("yay", "galactic Sagittarius luminous star arrow flying through deep purple interstellar nebula"),
    ("oglak", "majestic Capricorn obsidian alpine summit bathed in crisp silver starlight"),
    ("oğlak", "majestic Capricorn obsidian alpine summit bathed in crisp silver starlight"),
    ("balik", "dreamy Pisces glowing bioluminescent underwater sanctuary framed by glowing stars"),
    ("balık", "dreamy Pisces glowing bioluminescent underwater sanctuary framed by glowing stars"),
    ("burc", "zodiac celestial wheel glowing with golden constellations in deep night cosmos"),
    ("burç", "zodiac celestial wheel glowing with golden constellations in deep night cosmos"),
    ("astroloji", "ornate golden brass astrolabe and glowing zodiac star charts inside cosmic observatory"),
    ("gezegen", "grand aligned luminous planets Saturn with rings and Jupiter glowing in deep space"),
    ("kavusum", "close luminous planetary conjunction with golden orbital light halo in deep starfield"),
    ("kavuşum", "close luminous planetary conjunction with golden orbital light halo in deep starfield"),
    ("yildiz", "dense shimmering starfield and ethereal glowing nebula dust"),
    ("yıldız", "dense shimmering starfield and glowing nebula dust"),
    ("uzay", "vast outer space nebula vista with glowing star clusters"),
    ("gokyuzu", "high above in the vast starry night heavens and swirling cosmic clouds"),
    ("gökyüzü", "high above in the vast starry night heavens and swirling cosmic clouds"),
    ("yeryuzu", "cascading down toward glowing blue-green planet Earth far below"),
    ("yeryüzü", "cascading down toward glowing blue-green planet Earth far below"),
    ("dunya", "illuminated curved horizon of planet Earth seen from orbital altitude"),
    ("dünya", "illuminated curved horizon of planet Earth seen from orbital altitude"),
    ("adam", "heroic robed celestial man as the central figure"),
    ("kadin", "graceful luminous celestial woman as the central figure"),
    ("kadın", "graceful luminous celestial woman as the central figure"),
    ("elinde", "holding an ornate glowing pitcher firmly in his hands"),
    ("bosalt", "pouring cascading glowing water streams downward in graceful motion"),
    ("boşalt", "pouring cascading glowing water streams downward in graceful motion"),
    ("dokuyor", "pouring shimmering cascading liquid downward in dramatic arcs"),
    ("döküyor", "pouring shimmering cascading liquid downward in dramatic arcs"),
    # Teknoloji, YZ & Bilim
    ("yapay zeka", "glowing futuristic neural processor microchip floating with holographic cyan light paths"),
    ("cip", "macro silicon semiconductor wafer processor with glowing golden and cyan micro-circuits"),
    ("çip", "macro silicon semiconductor wafer processor with glowing golden and cyan micro-circuits"),
    ("transistor", "microscopic golden silicon transistor lattice pulsing with luminous electrons"),
    ("transistör", "microscopic golden silicon transistor lattice pulsing with luminous electrons"),
    ("robot", "expressive stylized futuristic companion robot with warm glowing eyes"),
    ("kuantum", "chandelier-like golden cryogenic quantum computer processor gleaming inside dark glass lab"),
    ("veri", "sleek dark obsidian data center corridor with illuminated fiber-optic light streams"),
    ("kod", "clean futuristic studio workspace with glowing 3D geometric holographic diagrams"),
    # Tarih, İstanbul & Mekanlar
    ("istanbul", "historic Istanbul skyline with Bosphorus water reflections, domes, and golden hour light"),
    ("sarnic", "ancient Basilica Cistern subterranean marble columns illuminated by warm amber torchlight reflections in water"),
    ("sarnıç", "ancient Basilica Cistern subterranean marble columns illuminated by warm amber torchlight reflections in water"),
    ("yeralti", "ancient underground stone vaulted chamber lit by warm flickering torches"),
    ("yeraltı", "ancient underground stone vaulted chamber lit by warm flickering torches"),
    ("kutuphane", "enchanted grand ancient wooden library filled with towering bookshelves and floating warm lanterns"),
    ("kütüphane", "enchanted grand ancient wooden library filled with towering bookshelves and floating warm lanterns"),
    ("tarih", "authentic historical stone architecture illuminated by atmospheric golden sunlight"),
    ("belgesel", "epic documentary wide framing of dramatic historical landmark architecture"),
    # Doğa, Hayvanlar, Karakter & Hareket
    ("baykus", "curious fluffy owl perched beside glowing leather books"),
    ("baykuş", "curious fluffy owl perched beside glowing leather books"),
    ("kedi", "expressive fluffy cat in warm cinematic light"),
    ("kopek", "loyal expressive dog in warm cinematic light"),
    ("köpek", "loyal expressive dog in warm cinematic light"),
    ("okyanus", "dramatic turquoise ocean waves crashing under storm clouds and golden sunbeams"),
    ("deniz", "tranquil deep blue sea horizon catching warm sunset rays"),
    ("oksa", "gentle warm hand softly petting with calm affection"),
    ("okşa", "gentle warm hand softly petting with calm affection"),
    ("yagmur", "raindrops glistening across neon-lit wet cobblestones at twilight"),
    ("yağmur", "raindrops glistening across neon-lit wet cobblestones at twilight"),
    ("kilic", "ornate gleaming steel katana sword held by heroic character in dramatic wind"),
    ("kılıç", "ornate gleaming steel katana sword held by heroic character in dramatic wind"),
    ("tokyo", "moody rainy Tokyo rooftop overlooking glowing neon billboards"),
    ("kapi", "colossal ancient carved stone portal standing above crashing ocean waves"),
    ("kapı", "colossal ancient carved stone portal standing above crashing ocean waves"),
    ("ormanda", "sun-dappled misty emerald ancient forest with volumetric light rays"),
    ("orman", "sun-dappled misty emerald ancient forest with volumetric light rays"),
    ("dag", "snow-capped dramatic alpine mountain peaks emerging through drifting clouds"),
    ("dağ", "snow-capped dramatic alpine mountain peaks emerging through drifting clouds"),
    ("ates", "warm dancing fire flames and glowing embers floating into dusk"),
    ("ateş", "warm dancing fire flames and glowing embers floating into dusk"),
    ("su", "crystal clear flowing water splashing with bright light reflections"),
    ("animasyon", "vibrant 3D animated scene with stylized charming character geometry"),
    ("anime", "crisp 2D anime keyframe illustration with expressive cel-shaded lighting"),
    ("kitap", "glowing open antique book with golden illuminated pages"),
)


def _gemini_keys() -> List[str]:
    keys: List[str] = []
    for k, v in os.environ.items():
        if "GEMINI_API_KEY" in k.upper() and v and v.strip():
            val = v.strip().strip("\"'")
            if val not in keys:
                keys.append(val)
    for p in (
        Path(__file__).resolve().parent / ".env",
        Path.home() / "Desktop" / "PYTHON PROJECTS" / "Fabrika" / "Persona" / ".env",
    ):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k_name, k_val = line.split("=", 1)
                    if "GEMINI_API_KEY" in k_name.upper():
                        val = k_val.strip().strip("\"'")
                        if val and val not in keys:
                            keys.append(val)
        except OSError:
            continue
    return keys


def _tr_lower(text: str) -> str:
    return (text or "").replace("İ", "i").replace("I", "ı").replace("\u0307", "").lower()


def _tr_ascii_fold(text: str) -> str:
    return _tr_lower(text).translate(str.maketrans("çğıöşü", "cgiosu"))


def _is_turkish_text(text: str) -> bool:
    if _TR_CHARS_RE.search(text or ""):
        return True
    fold_words = re.sub(r"[^\w\s]+", " ", _tr_ascii_fold(text)).split()
    return any(w.startswith(_tr_ascii_fold(stem)) for stem, _ in _VISUAL_STEM_MAP for w in fold_words)


def _offline_visual_grounding(prompt: str, style_preset: str) -> Tuple[str, List[str]]:
    """Türkçe veya soyut konuyu ham metin olarak CLIP'e atmak yerine somut İngilizce sahne öğelerine çevirir."""
    from channels_manager import STYLE_MAP

    cleaned = _EMOJI_RE.sub(" ", str(prompt or "")).strip()
    low = re.sub(r"[^\w\s]+", " ", _tr_lower(cleaned))
    folded = re.sub(r"[^\w\s]+", " ", _tr_ascii_fold(cleaned))
    low_words = low.split()
    fold_words = folded.split()
    matches: List[str] = []
    used_spans: set[str] = set()

    for stem, eng in _VISUAL_STEM_MAP:
        fstem = _tr_ascii_fold(stem)
        hit = (
            (" " in stem and (stem in low or fstem in folded))
            or any(w.startswith(stem) for w in low_words)
            or any(w.startswith(fstem) for w in fold_words)
        )
        if hit and eng not in used_spans:
            used_spans.add(eng)
            matches.append(eng)

    stil = STYLE_MAP.get(style_preset, {})
    style_suffix = str(stil.get("prompt_suffix") or "cinematic film still, vivid coherent scene")

    if matches:
        core_en = ", ".join(matches[:6])
        return core_en, [f"wide establishing view of {core_en}, {style_suffix}",
                         f"dramatic medium framing of {core_en}, rich lighting, {style_suffix}",
                         f"atmospheric close-up detail of {core_en}, shallow depth of field, {style_suffix}"]

    # Eşleşme bulunamazsa ancak metin Türkçeyse soyut kelimeleri temizle ve stil bağlamına yaslan
    if _is_turkish_text(cleaned):
        words = [w for w in low.split() if w not in _ABSTRACT_NOISE and len(w) > 2]
        konu_kisa = " ".join(words[:6]) or "coherent thematic scene"
        base = f"concrete visual scene representing '{konu_kisa}', {style_suffix}, clear main subject, no random anatomy, no text"
        return base, [f"wide cinematic shot, {base}", f"medium focal shot, {base}", f"detailed closing shot, {base}"]

    # Doğrudan İngilizce prompt zaten somutsa koru
    return cleaned, [
        f"wide cinematic establishing shot of {cleaned}, {style_suffix}",
        f"detailed medium shot of {cleaned}, {style_suffix}",
        f"dramatic final frame of {cleaned}, {style_suffix}",
    ]


def _cf_credentials() -> Tuple[Optional[str], Optional[str]]:
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
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None, None
    for p in (
        Path(__file__).resolve().parent / ".env",
        Path.home() / "Desktop" / "PYTHON PROJECTS" / "Fabrika" / "Persona" / ".env",
    ):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                if "=" not in line or line.strip().startswith("#"):
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                temiz = v.strip().strip("\"'")
                if not temiz:
                    continue
                if k in ("CLOUDFLARE_API_TOKEN", "CF_API_TOKEN", "APIToken"):
                    token = token or temiz
                elif k in ("CLOUDFLARE_ACCOUNT_ID", "CF_ACCOUNT_ID", "AccountID"):
                    hesap = hesap or temiz
        except OSError:
            continue
        if token and hesap:
            return token, hesap
    return token, hesap


def _normalize_plan_dict(parsed: Dict[str, Any], scene_count: int, cam_hint: str, source_tag: str) -> Optional[Dict[str, Any]]:
    scenes = [s for s in (parsed.get("scenes") or []) if isinstance(s, dict) and s.get("image_prompt")]
    if scenes and parsed.get("narration_text"):
        return {
            "narration_text": str(parsed["narration_text"]).strip(),
            "scenes": scenes[:scene_count],
            "motion_prompt": str(parsed.get("motion_prompt") or scenes[0].get("motion_prompt") or cam_hint).strip(),
            "planner_source": source_tag,
            "simulasyon": False,
        }
    return None


def _parse_plan_json(txt: Any, scene_count: int, cam_hint: str, source_tag: str) -> Optional[Dict[str, Any]]:
    if isinstance(txt, dict):
        return _normalize_plan_dict(txt, scene_count, cam_hint, source_tag)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(txt or "").strip(), flags=re.IGNORECASE)
    bas, son = cleaned.find("{"), cleaned.rfind("}")
    if bas < 0 or son <= bas:
        return None
    parsed = json.loads(cleaned[bas:son + 1])
    return _normalize_plan_dict(parsed, scene_count, cam_hint, source_tag) if isinstance(parsed, dict) else None


def _cloudflare_llm_plan(
    director_prompt: str,
    scene_count: int,
    cam_hint: str,
) -> Optional[Dict[str, Any]]:
    """Cloudflare Workers AI LLM yedek yönetmeni (Render'da 7/24 hazır)."""
    token, hesap = _cf_credentials()
    if not token or not hesap:
        return None
    for model in ("@cf/meta/llama-3.3-70b-instruct-fp8-fast", "@cf/meta/llama-3.1-8b-instruct"):
        url = f"https://api.cloudflare.com/client/v4/accounts/{hesap}/ai/run/{model}"
        body = json.dumps({
            "messages": [
                {"role": "system", "content": "Return ONLY a valid JSON object matching the requested schema. No markdown, no extra commentary."},
                {"role": "user", "content": director_prompt},
            ],
            "max_tokens": 900,
            "temperature": 0.3,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            resp_val = (raw.get("result") or {}).get("response")
            plan = _parse_plan_json(resp_val, scene_count, cam_hint, f"cloudflare:{model.split('/')[-1]}")
            if plan:
                return plan
        except Exception:
            continue
    return None


def _gemini_plan(
    prompt: str,
    style_preset: str,
    camera_motion: str,
    scene_count: int,
    duration_sec: float,
) -> Optional[Dict[str, Any]]:
    from channels_manager import CAMERA_MAP, STYLE_MAP

    stil_ad = STYLE_MAP.get(style_preset, {}).get("ad", style_preset)
    cam_hint = CAMERA_MAP.get(camera_motion, {}).get("prompt", "") or "smooth cinematic camera drift"
    target_words = max(10, min(90, int(round(duration_sec * 2.2))))

    director_prompt = (
        "You are an expert Film & AI Video Director. Convert the user's topic into a cohesive visual video plan.\n"
        f"User topic: {prompt}\n"
        f"Visual style preset: {stil_ad}\n"
        f"Preferred camera motion: {cam_hint}\n"
        f"Number of scenes: {scene_count}, Total duration: {duration_sec:.0f}s (~{target_words} Turkish words for narration).\n\n"
        "STRICT RULES:\n"
        "1. `narration_text` MUST be natural, engaging Turkish matching the duration.\n"
        "2. Each scene's `image_prompt` MUST be in ENGLISH, describing EVERY concrete physical subject, pose, action, environment, "
        "lighting, colors, and composition from the user's topic (NEVER abstract concepts like 'analysis', 'awakening', 'weekly report', and NEVER request text/watermarks).\n"
        "3. `motion_prompt` MUST be 1 concise ENGLISH sentence describing smooth camera + physical motion.\n"
        "4. Return ONLY valid JSON: "
        '{"narration_text": "...", "motion_prompt": "...", "scenes": [{"image_prompt": "...", "motion_prompt": "..."}]}'
    )

    import time

    keys = _gemini_keys()
    if keys:
        body = json.dumps({
            "contents": [{"parts": [{"text": director_prompt}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 900, "responseMimeType": "application/json"},
        }).encode("utf-8")

        t_basla = time.monotonic()
        dead_keys: set[str] = set()
        for model in ("gemini-2.5-flash", "gemini-2.0-flash"):
            for key in keys[:4]:
                if key in dead_keys or (time.monotonic() - t_basla) > 5.5:
                    continue
                url = (
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{urllib.parse.quote(model, safe='')}:generateContent?key={urllib.parse.quote(key, safe='')}"
                )
                req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
                try:
                    with urllib.request.urlopen(req, timeout=4) as resp:
                        raw = json.loads(resp.read().decode("utf-8"))
                    parts = ((raw.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                    txt = "".join(str(p.get("text") or "") for p in parts).strip()
                    plan = _parse_plan_json(txt, scene_count, cam_hint, f"gemini:{model}")
                    if plan:
                        return plan
                except urllib.error.HTTPError as e:
                    if e.code in (400, 403, 404):
                        dead_keys.add(key)
                    continue
                except Exception:
                    continue

    return _cloudflare_llm_plan(director_prompt, scene_count, cam_hint)


def fetch_url_launch_brief(url: str, timeout: int = 8) -> Dict[str, Any]:
    """Link #296 (`product-launch-motion`): Web sitesi URL'sinden güvenli tanıtım özeti çıkarır."""
    import ipaddress
    import socket

    temiz_url = (url or "").strip()
    parsed = urllib.parse.urlparse(temiz_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {"ok": False, "error": "Geçerli bir http(s) URL gerekli."}
    host = parsed.hostname or ""
    if not host or host in ("localhost", "127.0.0.1", "::1"):
        return {"ok": False, "error": "Yerel/özel ağ adreslerine izin verilmez."}
    try:
        for info in socket.getaddrinfo(host, None):
            ip_obj = ipaddress.ip_address(info[4][0])
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast:
                return {"ok": False, "error": "Özel ağ IP hedefi engellendi."}
    except Exception:
        return {"ok": False, "error": "Alan adı çözümlenemedi."}

    req = urllib.request.Request(temiz_url, headers={"User-Agent": "yusasufhin-cockpit/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html_txt = resp.read(160_000).decode("utf-8", errors="ignore")
    except Exception as e:
        return {"ok": False, "error": f"Site okunamadı: {type(e).__name__}"}

    m_title = re.search(r"<title[^>]*>(.*?)</title>", html_txt, re.I | re.S)
    m_desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html_txt, re.I | re.S)
    headings = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<h[12][^>]*>(.*?)</h[12]>", html_txt, re.I | re.S)]
    headings = [re.sub(r"\s+", " ", h) for h in headings if h][:5]
    title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m_title.group(1))).strip() if m_title else host
    desc = re.sub(r"\s+", " ", m_desc.group(1)).strip() if m_desc else ""
    summary = " · ".join([p for p in [title, desc, "; ".join(headings[:3])] if p])
    return {
        "ok": True,
        "url": temiz_url,
        "domain": host,
        "title": title[:140],
        "description": desc[:260],
        "headings": headings,
        "brief": summary[:600] or host,
    }


def plan_visual_scenes(
    prompt: str,
    style_preset: str = "cinematic_realism",
    camera_motion: str = "otomatik",
    scene_count: int = 3,
    duration_sec: float = 5.0,
    negative_prompt: str = "",
    use_llm: bool = True,
) -> Dict[str, Any]:
    """Konudan uyumlu Türkçe anlatım + somut İngilizce sahne/hareket planı üretir."""
    from channels_manager import CAMERA_MAP, STYLE_MAP

    temiz = _EMOJI_RE.sub(" ", str(prompt or "")).strip() or "Sinematik özgün sahne"
    stil = STYLE_MAP.get(str(style_preset or "").strip(), STYLE_MAP["cinematic_realism"])
    cam = CAMERA_MAP.get(str(camera_motion or "").strip(), CAMERA_MAP["otomatik"])
    neg = str(negative_prompt or "").strip() or stil.get("negative_prompt", "")

    if use_llm:
        llm_plan = _gemini_plan(temiz, style_preset, camera_motion, max(1, scene_count), duration_sec)
        if llm_plan:
            style_suffix = stil.get("prompt_suffix", "")
            norm_scenes: List[Dict[str, str]] = []
            for sc in llm_plan["scenes"]:
                ip = str(sc["image_prompt"]).strip()
                mp = str(sc.get("motion_prompt") or llm_plan["motion_prompt"]).strip()
                if style_suffix and style_suffix.split(",")[0].lower() not in ip.lower():
                    ip = f"{ip}, {style_suffix}"
                norm_scenes.append({"image_prompt": ip[:1200], "motion_prompt": mp[:500]})
            return {
                "narration_text": llm_plan["narration_text"],
                "image_prompt": norm_scenes[0]["image_prompt"],
                "motion_prompt": norm_scenes[0]["motion_prompt"],
                "negative_prompt": neg[:400],
                "scenes": norm_scenes,
                "planner_source": llm_plan["planner_source"],
                "simulasyon": False,
            }

    core_en, scene_prompts = _offline_visual_grounding(temiz, style_preset)
    style_suffix = stil.get("prompt_suffix", "")
    cam_motion = cam.get("prompt") or stil.get("motion_default") or "smooth steady cinematic camera drift"
    primary_img = f"{core_en}, {style_suffix}" if (style_suffix and style_suffix.split(",")[0].lower() not in core_en.lower()) else core_en
    mot = f"{cam_motion}, preserve exact reference framing and subject continuity"

    norm_scenes = [
        {"image_prompt": sp[:1200], "motion_prompt": mot[:500]}
        for sp in scene_prompts[:max(1, scene_count)]
    ]
    return {
        "narration_text": temiz,
        "image_prompt": primary_img[:1200],
        "motion_prompt": mot[:500],
        "negative_prompt": neg[:400],
        "scenes": norm_scenes,
        "planner_source": "cevrimdisi_gorsel_harita",
        "simulasyon": False,
    }
