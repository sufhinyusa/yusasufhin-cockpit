# -*- coding: utf-8 -*-
"""burc_pipeline.py — 12 burç senaryo + FLUX.2/Wan2.1 istem + SRT/ASS altyazı hattı.

GEMINI_API_KEY varsa Gemini 2.5/2.0 Flash REST API'sinden Türkçe anlatım,
İngilizce FLUX.2 görsel istemi ve İngilizce Wan2.1 hareket istemi alınır.
Anahtar yoksa veya çağrı düşerse çevrimdışı şablon `simulasyon=True` ve
`kaynak="cevrimdisi_sablon"` ile döner; çevrimdışı metin AI üretimi sayılmaz.
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

__all__ = ["BURC_KATALOGU", "burc_listesi", "burc_senaryo_olustur",
           "altyazi_dosyalari_olustur"]

# slug, ad, tarih, element, gorsel_tema, hareket_yonu, varsayilan_ses,
# gorsel_tema_en, hareket_yonu_en, simge (Unicode U+2648..U+2653)
_KATALOG_HAM = [
    ("koc", "Koç", "21 Mart – 19 Nisan", "Ateş", "Kızıl çöl şafağı, koç boynuzu silüeti, cesur figür", "Kameranın sağdan sola ilerleyişi", "Puck", "Crimson desert dawn, ram-horn silhouette, bold heroic figure", "slow right-to-left camera track", "♈"),
    ("boga", "Boğa", "20 Nisan – 20 Mayıs", "Toprak", "Yemyeşil vadi, mermer heykel, dokunsal doku", "Yavaş yukarı pan", "Aoede", "Lush green valley, marble sculpture, tactile textures", "slow upward pan", "♉"),
    ("ikizler", "İkizler", "21 Mayıs – 20 Haziran", "Hava", "İkiz yansımalar, aynalı koridor, hafif ışık", "Hızlı sağa kaydırma", "Puck", "Twin reflections, mirrored corridor, airy light", "quick lateral slide to the right", "♊"),
    ("yengec", "Yengeç", "21 Haziran – 22 Temmuz", "Su", "Ay ışığında kumsal, inci kabuğu, sıcak ev", "Yavaş yaklaşma (dolly in)", "Aoede", "Moonlit beach, pearl shell, warm home interior", "slow dolly in", "♋"),
    ("aslan", "Aslan", "23 Temmuz – 22 Ağustos", "Ateş", "Altın taht odası, aslan gölgesi, dramatik ışık", "Alçaktan yukarı tilt", "Fenrir", "Golden throne room, lion shadow, dramatic light", "low-angle tilt up", "♌"),
    ("basak", "Başak", "23 Ağustos – 22 Eylül", "Toprak", "Buğday tarlası, kristal büyüteç, düzenli geometri", "Mikro detaya yavaş zoom", "Kore", "Wheat field, crystal magnifier, orderly geometry", "slow zoom into a fine detail", "♍"),
    ("terazi", "Terazi", "23 Eylül – 22 Ekim", "Hava", "Dengede süzülen terazi, pastel gök, simetri", "Yatay orbit", "Aoede", "Floating balanced scales, pastel sky, symmetry", "horizontal orbit", "♎"),
    ("akrep", "Akrep", "23 Ekim – 21 Kasım", "Su", "Karanlık su altı, mor ışık, gizemli sembol", "Yavaş dolly out", "Charon", "Dark underwater scene, violet light, mysterious symbol", "slow dolly out", "♏"),
    ("yay", "Yay", "22 Kasım – 21 Aralık", "Ateş", "Yıldızlı gökyüzü, ok ve yay, ufka koşu", "Hızlı ileri sürüş", "Puck", "Starry sky, bow and arrow, sprint toward the horizon", "fast forward tracking shot", "♐"),
    ("oglak", "Oğlak", "22 Aralık – 19 Ocak", "Toprak", "Karlı dağ zirvesi, taş merdiven, keçi silüeti", "Yavaş yukarı çıkış", "Charon", "Snowy mountain summit, stone staircase, goat silhouette", "slow climb upward", "♑"),
    ("kova", "Kova", "20 Ocak – 18 Şubat", "Hava", "Yıldızlı gökyüzünden su boşaltan göksel figür, safir nebula, altın takımyıldızı", "Geniş açıdan içeri zoom", "Puck", "Mythic Aquarius celestial figure pouring glowing water from starry heavens toward Earth, sapphire nebula, golden constellations", "zoom in from a wide angle", "♒"),
    ("balik", "Balık", "19 Şubat – 20 Mart", "Su", "Sualtı rüyası, iki balık, yumuşak mor-mavi", "Serbest yüzme hareketi", "Aoede", "Underwater dreamscape, two fish, soft violet-blue", "free-floating swimming motion", "♓"),
]

BURC_KATALOGU: Dict[str, Dict[str, str]] = {
    h[0]: dict(slug=h[0], kod=h[0], ad=h[1], tarih=h[2], element=h[3], gorsel_tema=h[4],
               hareket_yonu=h[5], varsayilan_ses=h[6], gorsel_tema_en=h[7],
               hareket_yonu_en=h[8], simge=h[9])
    for h in _KATALOG_HAM
}
_KOD_ESLEME = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
_CUMLE_AYIR = re.compile(r"(?<=[.!?…])\s+")


def _kod_normalize(kod: str) -> str:
    """Türkçe karakterli burç adlarını ASCII slug'a çevirir (Koç -> koc)."""
    return (kod or "").strip().translate(_KOD_ESLEME).lower()


def burc_listesi() -> List[Dict[str, str]]:
    """Kataloğun kopyasını döner; çağıran taraf global durumu bozamaz."""
    return [dict(burc) for burc in BURC_KATALOGU.values()]


def _gemini_anahtarlari() -> List[str]:
    """Çoklu hesap GEMINI_API_KEY* havuzunu şelale sırasıyla toplar."""
    try:
        from gemini_audio import collect_gemini_keys
        keys = collect_gemini_keys()
        if keys:
            return keys
    except Exception:
        pass
    anahtarlar: List[str] = []
    for ad, deger in os.environ.items():
        if ad.upper().startswith("GEMINI_API_KEY") and deger and deger.strip():
            temiz = deger.strip().strip('"\'')
            if temiz and temiz not in anahtarlar:
                anahtarlar.append(temiz)
    return anahtarlar


def _gemini_istek(api_key: str, model: str, istem: str,
                  zaman_asimi: int = 10) -> str:
    """Gemini generateContent çağrısı; hata metnine anahtarı sızdırmaz."""
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{urllib.parse.quote(model, safe='')}:generateContent"
           f"?key={urllib.parse.quote(api_key, safe='')}")
    govde = json.dumps({
        "contents": [{"parts": [{"text": istem}]}],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 800,
                             "responseMimeType": "application/json"},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=govde, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=zaman_asimi) as yanit:
            veri = json.loads(yanit.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Gemini HTTP {e.code}") from e
    except Exception as e:
        raise RuntimeError(f"Gemini bağlantı hatası: {type(e).__name__}") from e
    adaylar = veri.get("candidates") or []
    parcalar = ((adaylar[0].get("content") or {}).get("parts") or []) if adaylar else []
    metin = "".join(str(p.get("text") or "") for p in parcalar).strip()
    if not metin:
        raise RuntimeError("Gemini boş yanıt döndürdü")
    return metin


def _oran_tarifi(aspect_ratio: str) -> str:
    oran = (aspect_ratio or "9:16").replace(" ", "")
    if oran == "16:9":
        return "wide horizontal 16:9 widescreen composition"
    if oran == "1:1":
        return "balanced square 1:1 composition"
    return "vertical 9:16 portrait composition"


def _turkce_kaldi_mi(metin: str) -> bool:
    try:
        from prompt_director import _looks_like_untranslated_turkish
        return _looks_like_untranslated_turkish(metin)
    except Exception:
        return bool(re.search(r"[çğıöşüÇĞİÖŞÜ]", metin or "")) or not (metin or "").strip()


def _konuyu_gorsel_sahneye_cevir(konu: str, aspect_ratio: str) -> Tuple[str, List[str]]:
    oran_en = _oran_tarifi(aspect_ratio)
    try:
        from prompt_director import _offline_visual_grounding
        core_en, sahneler = _offline_visual_grounding(konu, "astrology_mystic")
        if core_en:
            temel = f"{core_en}, {oran_en}, mystical cosmic atmosphere, no text, no watermark"
            liste = [f"{s}, {oran_en}, no text, no watermark" for s in sahneler[:3]] or [temel]
            return temel, liste
    except Exception:
        pass
    return f"dramatic celestial cosmic illustration depicting: {konu}, {oran_en}, no text, no watermark", [
        f"wide establishing view depicting: {konu}, cosmic nebula light, {oran_en}, no text, no watermark",
        f"dramatic medium shot focusing on: {konu}, golden zodiac starlight, {oran_en}, no text, no watermark",
    ]


def _json_ayikla(metin: Any) -> Dict[str, Any]:
    """Modelin dict ya da ```json çitli string yanıtını güvenle sözlüğe çevirir."""
    if isinstance(metin, dict):
        return metin
    temiz = re.sub(r"^```(?:json)?\s*", "", str(metin or "").strip(), flags=re.IGNORECASE)
    temiz = re.sub(r"\s*```$", "", temiz)
    bas, son = temiz.find("{"), temiz.rfind("}")
    if bas < 0 or son <= bas:
        raise ValueError("Model yanıtında JSON nesnesi yok")
    veri = json.loads(temiz[bas:son + 1])
    if not isinstance(veri, dict):
        raise ValueError("Model JSON yanıtı nesne değil")
    return veri


def _gemini_istem(burc: Dict[str, str], konu: str, sure_sn: float, dil: str,
                  aspect_ratio: str = "9:16") -> str:
    oran_en = _oran_tarifi(aspect_ratio)
    if konu:
        konu_kurali = (
            f"ZORUNLU ANA SAHNE (Kullanıcı İstemi): {konu}\n"
            "KRİTİK KURAL: Kullanıcının istediği tüm kişileri, nesneleri (ör. elindeki kova/kap), "
            "eylemleri (ör. gökyüzünden yeryüzüne su boşaltma) ve mekanları BİREBİR İngilizce `image_prompt` "
            f"içine koy! {burc['ad']} burcunun ({burc['element']} elementi) kozmik yıldız ışığını sadece "
            "uyumlu atmosfer olarak ekle; kullanıcının istemediği fütüristik şehir, neon vb. alakasız sahneler UYDURMA.\n"
            "Anlatım (`narration_text`) kullanıcının yazdığı konuyu doğrudan korusun; "
            "'kısa bir astroloji molası', tarih aralığı ('20 Ocak - 18 Şubat') veya 'sakin bir anlatım izleyeceksiniz' "
            "gibi kalıp/şablon cümleler ASLA ekleme!\n"
        )
    else:
        konu_kurali = f"Tema: {burc['gorsel_tema']}. Hareket: {burc['hareket_yonu']}.\n"
    return (
        "Sen deneyimli bir sinema & görsel yönetmenisin. Aşağıdaki sahne için "
        f"{sure_sn:.0f} saniyelik kısa video planı üret.\n"
        + ("" if konu else f"Burç: {burc['ad']} ({burc['tarih']}), element: {burc['element']}.\n")
        + f"{konu_kurali}"
        f"Kadro: {oran_en}.\n"
        f"Yanıt dili: {dil}. narration_text bu dilde, sade ve doğrudan konuya sadık olsun; "
        "kalıp giriş/kapanış şablonları ekleme.\n"
        "image_prompt YALNIZCA İNGİLİZCE ve tek ayrıntılı sinematik paragraf olsun; Türkçe kelime KULLANMA, "
        "metin/logo/watermark isteme.\n"
        "motion_prompt YALNIZCA İNGİLİZCE tek cümle kamera ve fiziksel hareket olsun.\n"
        "scenes alanına aynı ana konunun 2 farklı kamera açısından (geniş kurucu plan + yakın dramatik plan) "
        "İngilizce image_prompt dizisi ekle.\n"
        'Yalnızca şu JSON şemasında yanıt ver: {"narration_text": "...", '
        '"image_prompt": "...", "motion_prompt": "...", "scenes": [{"image_prompt": "...", "motion_prompt": "..."}]}'
    )


def _cevrimdisi_sonuc(burc: Dict[str, str], konu: str, dil: str,
                      hata: str, aspect_ratio: str = "9:16") -> Dict[str, Any]:
    """AI olmayan, açıkça etiketli şablon. Kullanıcının yazdığı metne ekstra kalıp eklemez."""
    oran_en = _oran_tarifi(aspect_ratio)
    if konu:
        gorsel_istem, sahne_listesi = _konuyu_gorsel_sahneye_cevir(konu, aspect_ratio)
        anlatim = konu
    else:
        gorsel_istem = (
            f"Cinematic astrology keyframe for {burc['ad']} ({burc['element']} sign), "
            f"{burc['gorsel_tema_en']}, dramatic volumetric light, 35mm film grain, "
            f"no text, no watermark, {oran_en}"
        )
        sahne_listesi = [gorsel_istem]
        anlatim = f"{burc['ad']} ({burc['tarih']}): {burc['gorsel_tema']}."
    uyari = ("GEMINI_API_KEY/Cloudflare LLM yanıt vermedi; bu metin AI üretimi "
             "değildir, çevrimdışı şablondur.")
    if dil != "tr":
        uyari += f" Çevrimdışı şablon yalnızca Türkçe üretir (istenen dil: {dil})."
    hareket = f"{burc['hareket_yonu_en']}, gentle parallax, cinematic 24fps feel"
    return {
        "ok": True, "burc_kodu": burc["slug"], "burc_adi": burc["ad"],
        "simge": burc["simge"],
        "narration_text": anlatim,
        "image_prompt": gorsel_istem,
        "motion_prompt": hareket,
        "scenes": [{"image_prompt": s, "motion_prompt": hareket} for s in sahne_listesi],
        "subtitle_text": anlatim, "simulasyon": True,
        "kaynak": "cevrimdisi_sablon", "uyari": uyari, "hata": hata,
    }


def _senaryo_sahneleri_cikar(veri: Dict[str, Any], gorsel: str, hareket: str) -> List[Dict[str, str]]:
    sahneler: List[Dict[str, str]] = []
    for item in (veri.get("scenes") or []):
        if isinstance(item, dict) and item.get("image_prompt"):
            ip = str(item["image_prompt"]).strip()
            mp = str(item.get("motion_prompt") or hareket).strip()
            if ip and not _turkce_kaldi_mi(ip):
                sahneler.append({"image_prompt": ip, "motion_prompt": mp})
    if not sahneler:
        sahneler = [
            {"image_prompt": f"wide cinematic establishing view of {gorsel}", "motion_prompt": hareket},
            {"image_prompt": f"dramatic medium close-up highlighting {gorsel}", "motion_prompt": hareket},
        ]
    elif len(sahneler) == 1:
        sahneler.append({"image_prompt": f"dramatic medium close-up of {sahneler[0]['image_prompt']}", "motion_prompt": hareket})
    return sahneler[:3]


def burc_senaryo_olustur(burc_kodu: str, konu: str = "", sure_sn: int = 15,
                         dil: str = "tr", aspect_ratio: str = "9:16",
                         raw_prompt: bool = False,
                         camera_motion: str = "otomatik") -> Dict[str, Any]:
    """Burç veya doğrudan kullanıcı promptu için sahne/altyazı istemleri üretir.

    * `raw_prompt=True` ve `konu` doluysa kullanıcı metnine burç kalıbı/metni
      eklemez; `narration_text` kullanıcının girdiği metin olarak korunur ve
      yalnızca sahne görselleri İngilizceye çevrilir.
    """
    import time

    kod = _kod_normalize(burc_kodu)
    burc = BURC_KATALOGU.get(kod)
    if burc is None:
        return {
            "ok": False, "burc_kodu": kod or str(burc_kodu), "burc_adi": "",
            "narration_text": "", "image_prompt": "", "motion_prompt": "",
            "scenes": [], "subtitle_text": "", "simulasyon": True, "kaynak": "gecersiz_kod",
            "hata": (f"Bilinmeyen burç kodu: {burc_kodu!r}. "
                     f"Geçerli kodlar: {', '.join(BURC_KATALOGU)}"),
        }
    try:
        sn = max(3.0, min(120.0, float(sure_sn)))
    except (TypeError, ValueError):
        sn = 15.0
    dil, konu = (dil or "tr").strip().lower(), (konu or "").strip()

    if raw_prompt and konu:
        oran_en = _oran_tarifi(aspect_ratio)
        try:
            from prompt_director import plan_visual_scenes
            plan = plan_visual_scenes(
                prompt=konu,
                style_preset="cinematic_realism",
                camera_motion=camera_motion or "otomatik",
                scene_count=2,
                duration_sec=sn,
                use_llm=True,
            )
            img_p = str(plan.get("image_prompt") or "").strip()
            if img_p and oran_en not in img_p:
                img_p = f"{img_p}, {oran_en}"
            mot_p = str(plan.get("motion_prompt") or "smooth steady cinematic camera motion").strip()
            sahneler = []
            for sc in (plan.get("scenes") or []):
                ip = str((sc or {}).get("image_prompt") or "").strip()
                if ip:
                    if oran_en not in ip:
                        ip = f"{ip}, {oran_en}"
                    sahneler.append({"image_prompt": ip, "motion_prompt": str(sc.get("motion_prompt") or mot_p).strip()})
            if not sahneler:
                sahneler = [{"image_prompt": img_p, "motion_prompt": mot_p}]
            psrc = str(plan.get("planner_source") or "cevrimdisi_gorsel_harita")
            return {
                "ok": True,
                "burc_kodu": kod,
                "burc_adi": burc["ad"],
                "simge": burc["simge"],
                "narration_text": konu,
                "image_prompt": img_p or f"{konu}, {oran_en}",
                "motion_prompt": mot_p,
                "scenes": sahneler,
                "subtitle_text": konu,
                "raw_prompt": True,
                "simulasyon": (psrc == "cevrimdisi_gorsel_harita"),
                "kaynak": f"dogrudan_prompt ({psrc})",
            }
        except Exception as direct_err:
            off = _cevrimdisi_sonuc(burc, konu, dil, f"direct:{type(direct_err).__name__}", aspect_ratio=aspect_ratio)
            off["raw_prompt"] = True
            return off
    anahtarlar = _gemini_anahtarlari()
    son_hata = "GEMINI_API_KEY bulunamadı"
    istem = _gemini_istem(burc, konu, sn, dil, aspect_ratio=aspect_ratio)

    t_basla = time.monotonic()
    dead_keys: set[str] = set()
    for model in ("gemini-4-hydrogen", "gemini-3.5-flash-lite", "gemini-2.5-flash"):
        for anahtar in anahtarlar[:8]:
            if anahtar in dead_keys or (time.monotonic() - t_basla) > 12.0:
                continue
            try:
                veri = _json_ayikla(_gemini_istek(anahtar, model, istem, zaman_asimi=6))
                anlatim = str(veri.get("narration_text") or "").strip()
                gorsel = str(veri.get("image_prompt") or "").strip()
                hareket = str(veri.get("motion_prompt") or "").strip()
                if not (anlatim and gorsel and hareket) or _turkce_kaldi_mi(gorsel):
                    raise ValueError("Gemini yanıtı eksik veya image_prompt Türkçe kaldı")
                return {
                    "ok": True, "burc_kodu": kod, "burc_adi": burc["ad"],
                    "simge": burc["simge"],
                    "narration_text": anlatim, "image_prompt": gorsel,
                    "motion_prompt": hareket,
                    "scenes": _senaryo_sahneleri_cikar(veri, gorsel, hareket),
                    "subtitle_text": anlatim, "simulasyon": False, "kaynak": f"gemini:{model}",
                }
            except Exception as e:
                msg = str(e)
                if "HTTP 400" in msg or "HTTP 403" in msg or "HTTP 404" in msg:
                    dead_keys.add(anahtar)
                son_hata = f"{type(e).__name__}: {msg[:160]}"
                if "HTTP 404" in msg:
                    break
    # Cloudflare Workers AI LLM yedek denemesi
    if os.environ.get("PYTEST_CURRENT_TEST") and not (
        os.environ.get("CLOUDFLARE_API_TOKEN") or os.environ.get("CF_API_TOKEN")
    ):
        return _cevrimdisi_sonuc(burc, konu, dil, son_hata, aspect_ratio=aspect_ratio)
    try:
        from prompt_director import _cf_credentials
        cf_tok, cf_acc = _cf_credentials()
        if cf_tok and cf_acc:
            for model, cf_timeout in (
                ("@cf/meta/llama-3.3-70b-instruct-fp8-fast", 18),
                ("@cf/meta/llama-3.1-8b-instruct", 10),
            ):
                url = f"https://api.cloudflare.com/client/v4/accounts/{cf_acc}/ai/run/{model}"
                req = urllib.request.Request(
                    url,
                    data=json.dumps({
                        "messages": [
                            {"role": "system", "content": "Return ONLY a valid JSON object matching the schema. image_prompt MUST be vivid ENGLISH only."},
                            {"role": "user", "content": istem},
                        ],
                        "max_tokens": 800,
                        "temperature": 0.3,
                    }).encode("utf-8"),
                    headers={"Authorization": f"Bearer {cf_tok}", "Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=cf_timeout) as y:
                        ham_cf = json.loads(y.read().decode("utf-8"))
                    resp_val = (ham_cf.get("result") or {}).get("response")
                    veri = _json_ayikla(resp_val)
                    anlatim = str(veri.get("narration_text") or "").strip()
                    gorsel = str(veri.get("image_prompt") or "").strip()
                    hareket = str(veri.get("motion_prompt") or "").strip()
                    if anlatim and gorsel and hareket and not _turkce_kaldi_mi(gorsel):
                        return {
                            "ok": True, "burc_kodu": kod, "burc_adi": burc["ad"],
                            "simge": burc["simge"],
                            "narration_text": anlatim, "image_prompt": gorsel,
                            "motion_prompt": hareket,
                            "scenes": _senaryo_sahneleri_cikar(veri, gorsel, hareket),
                            "subtitle_text": anlatim,
                            "simulasyon": False,
                            "kaynak": f"cloudflare:{model.split('/')[-1]}",
                        }
                except Exception as cf_err:
                    son_hata = f"{type(cf_err).__name__}: {str(cf_err)[:140]}"
                    continue
    except Exception:
        pass
    return _cevrimdisi_sonuc(burc, konu, dil, son_hata, aspect_ratio=aspect_ratio)


def _cumlelere_ayir(metin: str) -> List[str]:
    temiz = re.sub(r"\s+", " ", (metin or "").strip())
    return [p.strip() for p in _CUMLE_AYIR.split(temiz) if p.strip()] if temiz else []


def _srt_zaman(sn: float) -> str:
    ms = max(0, int(round(sn * 1000)))
    saat, ms = divmod(ms, 3_600_000)
    dakika, ms = divmod(ms, 60_000)
    saniye, ms = divmod(ms, 1000)
    return f"{saat:02d}:{dakika:02d}:{saniye:02d},{ms:03d}"


def _ass_zaman(sn: float) -> str:
    cs = max(0, int(round(sn * 100)))
    saat, cs = divmod(cs, 360_000)
    dakika, cs = divmod(cs, 6_000)
    saniye, cs = divmod(cs, 100)
    return f"{saat}:{dakika:02d}:{saniye:02d}.{cs:02d}"


def _ass_temizle(metin: str) -> str:
    # ASS override blokları ({...}) enjeksiyonunu ve satır sonlarını etkisizleştir.
    return (metin.replace("{", "(").replace("}", ")")
            .replace("\r", " ").replace("\n", "\\N").strip())


def altyazi_dosyalari_olustur(metin: str, sure_sn: float, hedef_srt: Path,
                              hedef_ass: Optional[Path] = None) -> Dict[str, Any]:
    """Metni cümlelere bölüp süreye oranlı SRT ve (istenirse) ASS yazar."""
    cumleler = _cumlelere_ayir(metin)
    if not cumleler:
        raise ValueError("Altyazı için boş metin verildi")
    try:
        toplam = float(sure_sn)
    except (TypeError, ValueError) as e:
        raise ValueError("sure_sn sayısal olmalı") from e
    if toplam <= 0:
        raise ValueError("sure_sn 0'dan büyük olmalı")

    srt_yolu = Path(hedef_srt)
    ass_yolu = Path(hedef_ass) if hedef_ass is not None else None
    if ass_yolu is not None and ass_yolu.resolve() == srt_yolu.resolve():
        raise ValueError("SRT ve ASS aynı dosya olamaz")
    srt_yolu.parent.mkdir(parents=True, exist_ok=True)
    if ass_yolu is not None:
        ass_yolu.parent.mkdir(parents=True, exist_ok=True)

    agirliklar = [len(cumle) + 8 for cumle in cumleler]
    toplam_agirlik = float(sum(agirliklar))
    cues: List[Tuple[float, float, str]] = []
    birikim = 0.0
    for cumle, agirlik in zip(cumleler, agirliklar):
        bas = toplam * (birikim / toplam_agirlik)
        birikim += agirlik
        son = toplam * (birikim / toplam_agirlik)
        cues.append((bas, max(son, min(toplam, bas + 0.01)), cumle))

    srt_satirlari: List[str] = []
    for i, (bas, son, cumle) in enumerate(cues, 1):
        srt_satirlari += [str(i), f"{_srt_zaman(bas)} --> {_srt_zaman(son)}",
                          cumle, ""]
    srt_yolu.write_text("\n".join(srt_satirlari), encoding="utf-8")

    if ass_yolu is not None:
        ass_satirlari = [
            "[Script Info]", "Title: Fabrika Burç Altyazısı", "ScriptType: v4.00+",
            "WrapStyle: 0", "ScaledBorderAndShadow: yes", "PlayResX: 1080",
            "PlayResY: 1920", "", "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Default,DejaVu Sans,54,&H00FFFFFF,&H000000FF,&H00101010,"
            "&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,120,1", "", "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
            "Effect, Text",
        ]
        for bas, son, cumle in cues:
            ass_satirlari.append(
                f"Dialogue: 0,{_ass_zaman(bas)},{_ass_zaman(son)},Default,,"
                f"0,0,0,,{_ass_temizle(cumle)}")
        ass_yolu.write_text("\n".join(ass_satirlari) + "\n", encoding="utf-8")

    return {
        "ok": True, "srt_yolu": str(srt_yolu),
        "ass_yolu": str(ass_yolu) if ass_yolu is not None else None,
        "cue_sayisi": len(cues), "sure_sn": round(toplam, 3),
        "karakter_sayisi": len(metin),
    }
