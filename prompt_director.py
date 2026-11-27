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

import hashlib
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
    # Fantastik, Epik Film & Karakter Öğeleri (Buzzy AI tarzı film senaryoları)
    ("ejderha", "colossal fire-breathing dragon with iridescent obsidian scales, wide leathery wings, and glowing amber eyes"),
    ("grifon", "majestic winged griffin with golden eagle head, feathered wings, and muscular lion body"),
    ("sovalye", "armored medieval knight in weathered engraved steel plate armor and crimson cloak"),
    ("şövalye", "armored medieval knight in weathered engraved steel plate armor and crimson cloak"),
    ("zirh", "intricate engraved silver-steel medieval plate armor"),
    ("zırh", "intricate engraved silver-steel medieval plate armor"),
    ("kale", "towering ancient stone fortress castle overlooking misty emerald cliffs"),
    ("sato", "gothic stone mountain castle rising through golden clouds"),
    ("şato", "gothic stone mountain castle rising through golden clouds"),
    ("buyucu", "robed fantasy mage holding a glowing crystal wooden staff"),
    ("büyücü", "robed fantasy mage holding a glowing crystal wooden staff"),
    ("savasci", "heroic fantasy warrior with distinct scarred face and engraved steel armor"),
    ("savaşçı", "heroic fantasy warrior with distinct scarred face and engraved steel armor"),
    ("astronot", "detailed white-and-gold spacesuit astronaut with reflective visor"),
    ("uzay gemisi", "sleek futuristic starship gliding past luminous planetary rings"),
    ("gece", "dramatic moonlit night atmosphere with cool blue rim lighting"),
    ("gunduz", "bright natural golden-hour daylight streaming across the scene"),
    ("gündüz", "bright natural golden-hour daylight streaming across the scene"),
    ("sis", "atmospheric drifting volumetric mist weaving through the background"),
)


def _gemini_keys() -> List[str]:
    keys: List[str] = []
    for k, v in os.environ.items():
        if "GEMINI_API_KEY" in k.upper() and v and v.strip():
            val = v.strip().strip("\"'")
            if val not in keys:
                keys.append(val)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return keys
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


_EXACT_SHORT_WATER_STEMS = {"su", "suyu", "suyun", "suya", "suda", "sular", "sulari", "suları"}
_UNTRANSLATED_TR_RE = re.compile(
    r"(?:\b(?:bir|ile|veya|icin|gibi|olarak|uzerinde|elinde|burcu|gokyuzu|yeryuzu|bosalt|dokuyor|adam|kadin|sahnede|goster|gosteren|yansiyan|tasiyan)\b|\b[a-z]+(?:iyor|ıyor|uyor|üyor)\b)",
    re.IGNORECASE,
)


def _tr_lower(text: str) -> str:
    return (text or "").replace("İ", "i").replace("I", "ı").replace("\u0307", "").lower()


def _tr_ascii_fold(text: str) -> str:
    return _tr_lower(text).translate(str.maketrans("çğıöşü", "cgiosu"))


def _looks_like_untranslated_turkish(text: str) -> bool:
    """LLM çıktısındaki image_prompt'un İngilizceye çevrilmeden Türkçe kalıp kalmadığını tespit eder."""
    s = (text or "").strip()
    if not s:
        return True
    if _TR_CHARS_RE.search(s):
        return True
    return bool(_UNTRANSLATED_TR_RE.search(_tr_ascii_fold(s)))


def _word_matches_stem(word: str, fold_word: str, stem: str, fstem: str) -> bool:
    if fstem == "su":
        return word in _EXACT_SHORT_WATER_STEMS or fold_word in _EXACT_SHORT_WATER_STEMS
    if len(fstem) <= 3:
        return word == stem or fold_word == fstem or word.startswith(stem)
    return word.startswith(stem) or fold_word.startswith(fstem)


def _is_turkish_text(text: str) -> bool:
    if _TR_CHARS_RE.search(text or ""):
        return True
    low_words = re.sub(r"[^\w\s]+", " ", _tr_lower(text)).split()
    fold_words = re.sub(r"[^\w\s]+", " ", _tr_ascii_fold(text)).split()
    for lw, fw in zip(low_words, fold_words):
        for stem, _ in _VISUAL_STEM_MAP:
            if " " in stem:
                continue
            if _word_matches_stem(lw, fw, stem, _tr_ascii_fold(stem)):
                return True
    return False


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

    astroloji_baglami = (style_preset == "astrology_mystic") or any(
        k in folded for k in ("burc", "astroloji", "takimyildiz", "zodiac")
    )

    for stem, eng in _VISUAL_STEM_MAP:
        fstem = _tr_ascii_fold(stem)
        hit = (
            (" " in stem and (stem in low or fstem in folded))
            or any(_word_matches_stem(lw, fw, stem, fstem) for lw, fw in zip(low_words, fold_words))
        )
        if hit:
            if fstem == "kova" and not astroloji_baglami:
                eng = "an ornate water bucket held firmly in hand"
            if eng not in used_spans:
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


def _stable_seed(text: str, explicit_seed: Optional[int] = None) -> int:
    if explicit_seed is not None:
        try:
            v = int(explicit_seed)
            if v > 0:
                return v % 2_147_483_647
        except (TypeError, ValueError):
            pass
    digest = hashlib.sha256((text or "yusasufhin").encode("utf-8")).hexdigest()[:8]
    return (int(digest, 16) % 900_000) + 1000


def _distribute_scene_durations(count: int, total_duration_sec: float) -> List[float]:
    n = max(1, int(count))
    total = max(3.0, min(120.0, float(total_duration_sec or 5.0)))
    base = round(total / n, 2)
    durs = [base] * n
    fark = round(total - sum(durs), 2)
    durs[-1] = round(max(1.5, durs[-1] + fark), 2)
    return durs


def _inject_character_lock(image_prompt: str, character_bible: str) -> str:
    ip = str(image_prompt or "").strip()
    bible = str(character_bible or "").strip()
    if not bible:
        return ip
    ip_low = ip.lower()
    if bible.lower() in ip_low:
        return ip
    stop = {"with", "from", "that", "this", "same", "consistent", "wearing", "holding", "and", "the"}
    tokens = [w for w in re.findall(r"[a-z]{4,}", bible.lower()) if w not in stop]
    if tokens and all(t in ip_low for t in tokens):
        return ip
    return f"Consistent character identity: {bible}; {ip}"


def _build_offline_characters(prompt: str, character_lock: str, core_en: str, style_preset: str) -> Tuple[str, List[Dict[str, str]]]:
    """Çevrimdışı senaryo için sabit karakter kimlik kartı (Character Bible) üretir."""
    lock_clean = str(character_lock or "").strip()
    if lock_clean:
        if _is_turkish_text(lock_clean):
            lock_en, _ = _offline_visual_grounding(lock_clean, style_preset)
        else:
            lock_en = lock_clean
        return lock_en[:320], [{"name": "Kilitli Karakter", "role": "Ana Karakter", "visual_anchor": lock_en[:240]}]

    folded = _tr_ascii_fold(prompt or "")
    chars: List[Dict[str, str]] = []
    anchors: List[str] = []
    catalog = (
        ("ejderha", "Ejderha", "Yaratık", "colossal fire-breathing dragon with iridescent obsidian scales and glowing amber eyes"),
        ("grifon", "Grifon", "Yaratık", "majestic winged griffin with golden eagle head and lion body"),
        ("sovalye", "Zırhlı Şövalye", "Kahraman", "armored medieval knight in weathered engraved silver-steel plate armor and crimson cloak"),
        ("savasci", "Savaşçı", "Kahraman", "heroic warrior in weathered engraved armor with distinct determined expression"),
        ("buyucu", "Büyücü", "Bilge", "robed fantasy mage carrying a luminous crystal wooden staff"),
        ("robot", "Minik Robot", "Başrol", "expressive compact stylized companion robot with warm glowing cyan eyes and brushed metallic shell"),
        ("baykus", "Baykuş", "Yoldaş", "fluffy expressive horned owl with bright amber eyes"),
        ("astronot", "Astronot", "Kaşif", "astronaut in detailed white-and-gold spacesuit with reflective golden visor"),
        ("adam", "Ana Figür", "Başrol", "heroic robed man with consistent facial features and flowing dark-blue garments"),
        ("kadin", "Ana Figür", "Başrol", "graceful luminous woman with consistent facial features and flowing garments"),
        ("kedi", "Kedi", "Başrol", "distinctive fluffy ginger-and-white cat with bright green eyes"),
        ("kopek", "Köpek", "Başrol", "loyal golden retriever dog with warm expressive eyes"),
    )
    for stem, ad, rol, anc in catalog:
        if stem in folded:
            chars.append({"name": ad, "role": rol, "visual_anchor": anc})
            anchors.append(anc)
            if len(chars) >= 3:
                break

    if not chars:
        first_chunk = (core_en or "").split(",")[0].strip()
        if first_chunk and not _looks_like_untranslated_turkish(first_chunk):
            chars.append({"name": "Ana Özne", "role": "Odak", "visual_anchor": first_chunk[:200]})
            anchors.append(first_chunk[:200])

    bible = "; ".join(anchors)[:360]
    return bible, chars


def _normalize_plan_dict(parsed: Dict[str, Any], scene_count: int, cam_hint: str, source_tag: str) -> Optional[Dict[str, Any]]:
    raw_scenes = [s for s in (parsed.get("scenes") or []) if isinstance(s, dict) and s.get("image_prompt")]
    scenes = [
        s for s in raw_scenes
        if not _looks_like_untranslated_turkish(str(s.get("image_prompt") or ""))
    ]
    if scenes and parsed.get("narration_text"):
        raw_bible = str(parsed.get("character_bible") or "").strip()
        if raw_bible and _looks_like_untranslated_turkish(raw_bible):
            raw_bible = ""
        raw_chars: List[Dict[str, str]] = []
        for c in (parsed.get("characters") or []):
            if isinstance(c, dict) and (c.get("name") or c.get("visual_anchor")):
                anc = str(c.get("visual_anchor") or "").strip()
                if anc and not _looks_like_untranslated_turkish(anc):
                    raw_chars.append({
                        "name": str(c.get("name") or "Karakter").strip()[:48],
                        "role": str(c.get("role") or "Başrol").strip()[:48],
                        "visual_anchor": anc[:260],
                    })
        if not raw_bible and raw_chars:
            raw_bible = "; ".join(c["visual_anchor"] for c in raw_chars[:3])[:360]
        style_anchor = str(parsed.get("style_anchor") or "").strip()
        if style_anchor and _looks_like_untranslated_turkish(style_anchor):
            style_anchor = ""
        return {
            "narration_text": str(parsed["narration_text"]).strip(),
            "character_bible": raw_bible[:360],
            "characters": raw_chars[:4],
            "style_anchor": style_anchor[:240],
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
    for model, cf_timeout in (
        ("@cf/meta/llama-3.3-70b-instruct-fp8-fast", 18),
        ("@cf/meta/llama-3.1-8b-instruct", 10),
    ):
        url = f"https://api.cloudflare.com/client/v4/accounts/{hesap}/ai/run/{model}"
        body = json.dumps({
            "messages": [
                {"role": "system", "content": "Return ONLY a valid JSON object matching the requested schema. Every image_prompt MUST be vivid, literal ENGLISH. Never output non-English words in image_prompt."},
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
            with urllib.request.urlopen(req, timeout=cf_timeout) as resp:
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
    character_lock: str = "",
) -> Optional[Dict[str, Any]]:
    from channels_manager import CAMERA_MAP, STYLE_MAP

    stil_ad = STYLE_MAP.get(style_preset, {}).get("ad", style_preset)
    cam_hint = CAMERA_MAP.get(camera_motion, {}).get("prompt", "") or "smooth cinematic camera drift"
    target_words = max(10, min(90, int(round(duration_sec * 2.2))))
    lock_line = f"Locked character description (MUST preserve verbatim in EVERY scene): {character_lock}\n" if character_lock else ""

    director_prompt = (
        "You are an expert Film & AI Video Director. Convert the user's topic into a cohesive multi-shot film plan with strict character consistency.\n"
        f"User topic: {prompt}\n"
        f"{lock_line}"
        f"Visual style preset: {stil_ad}\n"
        f"Preferred camera motion: {cam_hint}\n"
        f"Number of scenes: {scene_count}, Total duration: {duration_sec:.0f}s (~{target_words} Turkish words for narration).\n\n"
        "STRICT RULES:\n"
        "1. `narration_text` MUST be natural, engaging Turkish matching the duration.\n"
        "2. Define `character_bible` (concise ENGLISH physical appearance lock: face, hair, clothing/armor colors, key props) and `characters` array so the EXACT same characters appear identically across every shot.\n"
        "3. Each scene's `image_prompt` MUST be in ENGLISH ONLY, embedding the locked `character_bible` appearance consistently while varying shot framing (`wide`, `medium`, `close-up`) and action cleanly.\n"
        "4. Never drop requested objects or replace them with unrelated cities/objects, never use abstract words like 'analysis', never request text/watermarks.\n"
        "5. `motion_prompt` MUST be 1 concise ENGLISH sentence describing smooth camera + physical motion.\n"
        "6. Return ONLY valid JSON: "
        '{"narration_text": "...", "character_bible": "...", "style_anchor": "...", '
        '"characters": [{"name": "...", "role": "...", "visual_anchor": "..."}], '
        '"motion_prompt": "...", '
        '"scenes": [{"title": "...", "shot_type": "wide|medium|close-up", "image_prompt": "...", "motion_prompt": "..."}]}'
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


def _validate_public_http_url(url_str: str) -> Tuple[bool, str, str]:
    """URL şemasını ve çözümlenen tüm IP'lerin genel (public) ağda olduğunu doğrular (SSRF kalkanı)."""
    import ipaddress
    import socket

    temiz = (url_str or "").strip()
    parsed = urllib.parse.urlparse(temiz)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False, "", "Geçerli bir http(s) URL gerekli."
    host = (parsed.hostname or "").strip().lower()
    if not host or host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local") or host.endswith(".internal"):
        return False, "", "Yerel/özel ağ adreslerine izin verilmez."
    try:
        infos = socket.getaddrinfo(host, None)
        if not infos:
            return False, "", "Alan adı çözümlenemedi."
        for info in infos:
            ip_obj = ipaddress.ip_address(info[4][0])
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_reserved
                or ip_obj.is_multicast
                or ip_obj.is_unspecified
            ):
                return False, "", "Özel ağ IP hedefi engellendi."
    except Exception:
        return False, "", "Alan adı çözümlenemedi."
    return True, host, ""


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """HTTP 301/302/307/308 yönlendirmelerinde dahili IP'lere SSRF atlamasını engeller."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        full_new = urllib.parse.urljoin(req.full_url, newurl)
        ok, _h, err = _validate_public_http_url(full_new)
        if not ok:
            raise urllib.error.URLError(f"Güvensiz yönlendirme engellendi: {err}")
        return super().redirect_request(req, fp, code, msg, headers, full_new)


def fetch_url_launch_brief(url: str, timeout: int = 8) -> Dict[str, Any]:
    """Link #296 (`product-launch-motion`): Web sitesi URL'sinden güvenli tanıtım özeti çıkarır."""
    temiz_url = (url or "").strip()
    ok, host, err = _validate_public_http_url(temiz_url)
    if not ok:
        return {"ok": False, "error": err}

    opener = urllib.request.build_opener(_SafeRedirectHandler())
    req = urllib.request.Request(temiz_url, headers={"User-Agent": "yusasufhin-cockpit/1.0"})
    try:
        with opener.open(req, timeout=timeout) as resp:
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
    character_lock: str = "",
    seed: Optional[int] = None,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """Konudan uyumlu Türkçe anlatım + karakter kilidi (Character Bible) + somut İngilizce sahne/hareket planı üretir."""
    from channels_manager import CAMERA_MAP, STYLE_MAP

    temiz = _EMOJI_RE.sub(" ", str(prompt or "")).strip() or "Sinematik özgün sahne"
    stil = STYLE_MAP.get(str(style_preset or "").strip(), STYLE_MAP["cinematic_realism"])
    cam = CAMERA_MAP.get(str(camera_motion or "").strip(), CAMERA_MAP["otomatik"])
    neg = str(negative_prompt or "").strip() or stil.get("negative_prompt", "")
    style_suffix = stil.get("prompt_suffix", "")
    hedef_sure = max(3.0, min(120.0, float(duration_sec or 5.0)))
    lock_raw = str(character_lock or "").strip()
    shot_labels = ("Açılış (Geniş)", "Gelişme (Orta)", "Odak (Yakın)", "Aksiyon (Dinamik)", "Final (Epik)", "Kapanış")
    shot_types = ("wide", "medium", "close-up", "wide", "medium", "close-up")

    if use_llm:
        llm_plan = _gemini_plan(temiz, style_preset, camera_motion, max(1, scene_count), hedef_sure, character_lock=lock_raw)
        if llm_plan:
            bible = str(llm_plan.get("character_bible") or "").strip()
            chars = list(llm_plan.get("characters") or [])
            if lock_raw and not bible:
                bible, chars = _build_offline_characters(temiz, lock_raw, "", style_preset)
            style_anchor = str(llm_plan.get("style_anchor") or style_suffix).strip()
            durs = _distribute_scene_durations(len(llm_plan["scenes"]), hedef_sure)
            norm_scenes: List[Dict[str, Any]] = []
            for idx, sc in enumerate(llm_plan["scenes"]):
                ip = _inject_character_lock(str(sc["image_prompt"]).strip(), bible)
                mp = str(sc.get("motion_prompt") or llm_plan["motion_prompt"]).strip()
                if style_suffix and style_suffix.split(",")[0].lower() not in ip.lower():
                    ip = f"{ip}, {style_suffix}"
                norm_scenes.append({
                    "index": idx + 1,
                    "title": str(sc.get("title") or shot_labels[idx % len(shot_labels)]).strip()[:60],
                    "shot_type": str(sc.get("shot_type") or shot_types[idx % len(shot_types)]).strip()[:24],
                    "duration_sec": durs[idx],
                    "image_prompt": ip[:1200],
                    "motion_prompt": mp[:500],
                })
            final_seed = _stable_seed(f"{temiz}|{bible}|{style_preset}", seed)
            return {
                "narration_text": llm_plan["narration_text"],
                "character_bible": bible,
                "characters": chars,
                "style_anchor": style_anchor[:240],
                "seed": final_seed,
                "total_duration_sec": round(sum(s["duration_sec"] for s in norm_scenes), 2),
                "image_prompt": norm_scenes[0]["image_prompt"],
                "motion_prompt": norm_scenes[0]["motion_prompt"],
                "negative_prompt": neg[:400],
                "scenes": norm_scenes,
                "planner_source": llm_plan["planner_source"],
                "simulasyon": False,
            }

    core_en, scene_prompts = _offline_visual_grounding(temiz, style_preset)
    bible, chars = _build_offline_characters(temiz, lock_raw, core_en, style_preset)
    cam_motion = cam.get("prompt") or stil.get("motion_default") or "smooth steady cinematic camera drift"
    primary_core = _inject_character_lock(core_en, bible)
    primary_img = f"{primary_core}, {style_suffix}" if (style_suffix and style_suffix.split(",")[0].lower() not in primary_core.lower()) else primary_core
    mot = f"{cam_motion}, preserve exact reference framing and subject continuity"

    req_n = max(1, int(scene_count))
    while len(scene_prompts) < req_n:
        idx = len(scene_prompts)
        framing = ("epic wide view", "dramatic medium action shot", "expressive close-up portrait", "sweeping closing vista")[idx % 4]
        scene_prompts.append(f"{framing} of {core_en}, {style_suffix}")

    durs = _distribute_scene_durations(req_n, hedef_sure)
    norm_scenes = []
    for idx, sp in enumerate(scene_prompts[:req_n]):
        locked_sp = _inject_character_lock(sp, bible)
        norm_scenes.append({
            "index": idx + 1,
            "title": shot_labels[idx % len(shot_labels)],
            "shot_type": shot_types[idx % len(shot_types)],
            "duration_sec": durs[idx],
            "image_prompt": locked_sp[:1200],
            "motion_prompt": mot[:500],
        })
    final_seed = _stable_seed(f"{temiz}|{bible}|{style_preset}", seed)
    return {
        "narration_text": temiz,
        "character_bible": bible,
        "characters": chars,
        "style_anchor": style_suffix[:240],
        "seed": final_seed,
        "total_duration_sec": round(sum(s["duration_sec"] for s in norm_scenes), 2),
        "image_prompt": primary_img[:1200],
        "motion_prompt": mot[:500],
        "negative_prompt": neg[:400],
        "scenes": norm_scenes,
        "planner_source": "cevrimdisi_gorsel_harita",
        "simulasyon": False,
    }


def revise_scene_prompt(
    original_image_prompt: str,
    instruction: str,
    original_motion_prompt: str = "",
    character_bible: str = "",
    style_preset: str = "cinematic_realism",
    camera_motion: str = "otomatik",
    use_llm: bool = True,
) -> Dict[str, Any]:
    """AI Film Canvas'ta tek bir sahneyi sohbet talimatıyla karakter kimliğini bozmadan revize eder."""
    from channels_manager import CAMERA_MAP, STYLE_MAP

    orig_img = str(original_image_prompt or "").strip()
    orig_mot = str(original_motion_prompt or "").strip()
    talimat = _EMOJI_RE.sub(" ", str(instruction or "")).strip()
    bible = str(character_bible or "").strip()
    stil = STYLE_MAP.get(str(style_preset or "").strip(), STYLE_MAP["cinematic_realism"])
    style_suffix = str(stil.get("prompt_suffix") or "").strip()
    cam_hint = CAMERA_MAP.get(str(camera_motion or "").strip(), {}).get("prompt", "") or orig_mot or "smooth cinematic camera motion"

    if not talimat:
        return {
            "image_prompt": _inject_character_lock(orig_img, bible)[:1200],
            "motion_prompt": (orig_mot or cam_hint)[:500],
            "planner_source": "degisiklik_yok",
        }

    if use_llm:
        rev_prompt = (
            "You are revising ONE single shot of an AI film storyboard based on the director's edit request.\n"
            f"Original shot image_prompt: {orig_img}\n"
            f"Original motion_prompt: {orig_mot or cam_hint}\n"
            f"LOCKED character_bible (NEVER alter character face, hair, armor, colors): {bible or 'preserve exact subject'}\n"
            f"Visual style: {style_suffix}\n"
            f"Director edit instruction (may be Turkish or English): {talimat}\n\n"
            "Return ONLY valid JSON: "
            '{"narration_text": "revised", "scenes": [{"image_prompt": "<ENGLISH ONLY revised prompt preserving character_bible>", "motion_prompt": "<1 ENGLISH sentence>"}]}'
        )
        llm_res = None
        keys = _gemini_keys()
        if keys:
            import time as _t
            body = json.dumps({
                "contents": [{"parts": [{"text": rev_prompt}]}],
                "generationConfig": {"temperature": 0.35, "maxOutputTokens": 600, "responseMimeType": "application/json"},
            }).encode("utf-8")
            t0 = _t.monotonic()
            for model in ("gemini-2.5-flash", "gemini-2.0-flash"):
                for key in keys[:3]:
                    if (_t.monotonic() - t0) > 4.5:
                        break
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
                        llm_res = _parse_plan_json(txt, 1, cam_hint, f"gemini:{model}")
                        if llm_res:
                            break
                    except Exception:
                        continue
                if llm_res:
                    break
        if llm_res is None:
            llm_res = _cloudflare_llm_plan(rev_prompt, 1, cam_hint)
        if llm_res and llm_res.get("scenes"):
            new_ip = _inject_character_lock(str(llm_res["scenes"][0]["image_prompt"]).strip(), bible)
            if style_suffix and style_suffix.split(",")[0].lower() not in new_ip.lower():
                new_ip = f"{new_ip}, {style_suffix}"
            new_mp = str(llm_res["scenes"][0].get("motion_prompt") or llm_res.get("motion_prompt") or cam_hint).strip()
            return {
                "image_prompt": new_ip[:1200],
                "motion_prompt": new_mp[:500],
                "planner_source": llm_res.get("planner_source", "llm"),
            }

    # Çevrimdışı/deterministik sahne revizyonu (Türkçe direktifleri somut İngilizceye çevirir)
    folded = _tr_ascii_fold(talimat)
    ekler: List[str] = []
    direktif_haritasi = (
        ("yakin", "intimate dramatic close-up framing"),
        ("genis", "sweeping wide establishing cinematic framing"),
        ("ustten", "high-angle aerial bird's-eye camera perspective"),
        ("alttan", "heroic low-angle upward camera perspective"),
        ("gece", "moonlit deep night lighting with cool silver-blue rim glow"),
        ("gunduz", "bright natural golden-hour daylight"),
        ("gunes", "warm golden sunset rays streaming through atmosphere"),
        ("yagmur", "pouring rain with wet reflective surfaces"),
        ("kar", "drifting winter snowfall and frosty air"),
        ("sis", "thick atmospheric volumetric mist"),
        ("ates", "glowing firelight and floating bright embers"),
        ("karanlik", "moody dark high-contrast chiaroscuro shadows"),
        ("aydinlik", "luminous bright radiant lighting"),
        ("altin", "rich warm golden amber lighting accents"),
        ("mavi", "deep sapphire and cyan atmospheric lighting"),
        ("kirmizi", "dramatic crimson lighting highlights"),
    )
    for kok, eng in direktif_haritasi:
        if kok in folded and eng not in ekler:
            ekler.append(eng)

    if not ekler:
        if _is_turkish_text(talimat):
            t_en, _ = _offline_visual_grounding(talimat, style_preset)
            ekler.append(t_en)
        else:
            ekler.append(talimat)

    birlesik = f"{orig_img}, {', '.join(ekler)}" if orig_img else ", ".join(ekler)
    birlesik = _inject_character_lock(birlesik, bible)
    if style_suffix and style_suffix.split(",")[0].lower() not in birlesik.lower():
        birlesik = f"{birlesik}, {style_suffix}"

    new_mot = orig_mot or cam_hint
    if "yavas" in folded:
        new_mot = f"ultra slow graceful cinematic camera motion, {new_mot}"
    elif "hizli" in folded or "dinamik" in folded:
        new_mot = f"dynamic sweeping action tracking shot, {new_mot}"
    elif "sabit" in folded:
        new_mot = "locked stable camera framing while natural atmosphere moves subtly"

    return {
        "image_prompt": birlesik[:1200],
        "motion_prompt": new_mot[:500],
        "planner_source": "cevrimdisi_sahne_revizyonu",
    }
