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
# gorsel_tema_en, hareket_yonu_en
_KATALOG_HAM = [
    ("koc", "Koç", "21 Mart – 19 Nisan", "Ateş", "Kızıl çöl şafağı, koç boynuzu silüeti, cesur figür", "Kameranın sağdan sola ilerleyişi", "Puck", "Crimson desert dawn, ram-horn silhouette, bold heroic figure", "slow right-to-left camera track"),
    ("boga", "Boğa", "20 Nisan – 20 Mayıs", "Toprak", "Yemyeşil vadi, mermer heykel, dokunsal doku", "Yavaş yukarı pan", "Aoede", "Lush green valley, marble sculpture, tactile textures", "slow upward pan"),
    ("ikizler", "İkizler", "21 Mayıs – 20 Haziran", "Hava", "İkiz yansımalar, aynalı koridor, hafif ışık", "Hızlı sağa kaydırma", "Puck", "Twin reflections, mirrored corridor, airy light", "quick lateral slide to the right"),
    ("yengec", "Yengeç", "21 Haziran – 22 Temmuz", "Su", "Ay ışığında kumsal, inci kabuğu, sıcak ev", "Yavaş yaklaşma (dolly in)", "Aoede", "Moonlit beach, pearl shell, warm home interior", "slow dolly in"),
    ("aslan", "Aslan", "23 Temmuz – 22 Ağustos", "Ateş", "Altın taht odası, aslan gölgesi, dramatik ışık", "Alçaktan yukarı tilt", "Fenrir", "Golden throne room, lion shadow, dramatic light", "low-angle tilt up"),
    ("basak", "Başak", "23 Ağustos – 22 Eylül", "Toprak", "Buğday tarlası, kristal büyüteç, düzenli geometri", "Mikro detaya yavaş zoom", "Kore", "Wheat field, crystal magnifier, orderly geometry", "slow zoom into a fine detail"),
    ("terazi", "Terazi", "23 Eylül – 22 Ekim", "Hava", "Dengede süzülen terazi, pastel gök, simetri", "Yatay orbit", "Aoede", "Floating balanced scales, pastel sky, symmetry", "horizontal orbit"),
    ("akrep", "Akrep", "23 Ekim – 21 Kasım", "Su", "Karanlık su altı, mor ışık, gizemli sembol", "Yavaş dolly out", "Charon", "Dark underwater scene, violet light, mysterious symbol", "slow dolly out"),
    ("yay", "Yay", "22 Kasım – 21 Aralık", "Ateş", "Yıldızlı gökyüzü, ok ve yay, ufka koşu", "Hızlı ileri sürüş", "Puck", "Starry sky, bow and arrow, sprint toward the horizon", "fast forward tracking shot"),
    ("oglak", "Oğlak", "22 Aralık – 19 Ocak", "Toprak", "Karlı dağ zirvesi, taş merdiven, keçi silüeti", "Yavaş yukarı çıkış", "Charon", "Snowy mountain summit, stone staircase, goat silhouette", "slow climb upward"),
    ("kova", "Kova", "20 Ocak – 18 Şubat", "Hava", "Neon su taşıyıcı, fütüristik şehir, elektrik mavisi", "Geniş açıdan içeri zoom", "Puck", "Neon water bearer, futuristic city, electric blue", "zoom in from a wide angle"),
    ("balik", "Balık", "19 Şubat – 20 Mart", "Su", "Sualtı rüyası, iki balık, yumuşak mor-mavi", "Serbest yüzme hareketi", "Aoede", "Underwater dreamscape, two fish, soft violet-blue", "free-floating swimming motion"),
]

BURC_KATALOGU: Dict[str, Dict[str, str]] = {
    h[0]: dict(slug=h[0], kod=h[0], ad=h[1], tarih=h[2], element=h[3], gorsel_tema=h[4],
               hareket_yonu=h[5], varsayilan_ses=h[6], gorsel_tema_en=h[7],
               hareket_yonu_en=h[8])
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
    """Yalnızca ortam değişkenlerinden GEMINI_API_KEY* değerlerini toplar."""
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


def _json_ayikla(metin: str) -> Dict[str, Any]:
    """Modelin ```json çitlerini ve çevresindeki metni temizleyip JSON okur."""
    temiz = re.sub(r"^```(?:json)?\s*", "", metin.strip(), flags=re.IGNORECASE)
    temiz = re.sub(r"\s*```$", "", temiz)
    bas, son = temiz.find("{"), temiz.rfind("}")
    if bas < 0 or son <= bas:
        raise ValueError("Gemini yanıtında JSON nesnesi yok")
    veri = json.loads(temiz[bas:son + 1])
    if not isinstance(veri, dict):
        raise ValueError("Gemini JSON yanıtı nesne değil")
    return veri


def _gemini_istem(burc: Dict[str, str], konu: str, sure_sn: float, dil: str) -> str:
    ek = f"\nKullanıcı konusu: {konu}" if konu else ""
    return (
        "Sen deneyimli bir astroloji video senaristisin. Aşağıdaki burç için "
        f"{sure_sn:.0f} saniyelik kısa video üret.\n"
        f"Burç: {burc['ad']} ({burc['tarih']}), element: {burc['element']}.\n"
        f"Tema: {burc['gorsel_tema']}. Hareket: {burc['hareket_yonu']}.{ek}\n"
        f"Yanıt dili: {dil}. narration_text bu dilde, akıcı, 2-4 cümle olsun; "
        "abartılı kehanet ve tıbbi/finansal tavsiye verme.\n"
        "image_prompt İNGİLİZCE ve FLUX.2 için ayrıntılı tek paragraf olsun; "
        "metin/logo/watermark isteme, sinematik ışık ve kompozisyon tarif et.\n"
        "motion_prompt İNGİLİZCE ve Wan2.1 I2V için tek cümle kamera hareketi olsun.\n"
        'Yalnızca şu JSON şemasında yanıt ver: {"narration_text": "...", '
        '"image_prompt": "...", "motion_prompt": "..."}'
    )


def _cevrimdisi_sonuc(burc: Dict[str, str], konu: str, dil: str,
                      hata: str) -> Dict[str, Any]:
    """AI olmayan, açıkça etiketli şablon. simulasyon=True her zaman korunur."""
    ek = f" {konu}" if konu else ""
    anlatim = (
        f"{burc['ad']} burcu için kısa bir astroloji molası.{ek} "
        f"{burc['tarih']} aralığında doğanlar {burc['element']} elementinin "
        f"etkisini taşır. Bu videoda {burc['gorsel_tema'].lower()} teması ve "
        f"{burc['hareket_yonu'].lower()} eşliğinde sakin bir anlatım izleyeceksiniz."
    )
    uyari = ("GEMINI_API_KEY yok veya Gemini yanıt vermedi; bu metin AI üretimi "
             "değildir, çevrimdışı şablondur.")
    if dil != "tr":
        uyari += f" Çevrimdışı şablon yalnızca Türkçe üretir (istenen dil: {dil})."
    return {
        "ok": True, "burc_kodu": burc["slug"], "burc_adi": burc["ad"],
        "narration_text": anlatim,
        "image_prompt": (
            f"Cinematic astrology keyframe for {burc['ad']} ({burc['element']} sign), "
            f"{burc['gorsel_tema_en']}, dramatic volumetric light, 35mm film grain, "
            "no text, no watermark, vertical 9:16 composition"),
        "motion_prompt": f"{burc['hareket_yonu_en']}, gentle parallax, cinematic 24fps feel",
        "subtitle_text": anlatim, "simulasyon": True,
        "kaynak": "cevrimdisi_sablon", "uyari": uyari, "hata": hata,
    }


def burc_senaryo_olustur(burc_kodu: str, konu: str = "", sure_sn: int = 15,
                         dil: str = "tr") -> Dict[str, Any]:
    """Burç için anlatım + FLUX.2/Wan2.1 istemleri + altyazı metni üretir.

    Gemini anahtarı varsa 2.5 Flash, sonra 2.0 Flash denenir. Anahtar yoksa
    veya tüm çağrılar başarısızsa çevrimdışı şablon `simulasyon=True` ile döner.
    """
    kod = _kod_normalize(burc_kodu)
    burc = BURC_KATALOGU.get(kod)
    if burc is None:
        return {
            "ok": False, "burc_kodu": kod or str(burc_kodu), "burc_adi": "",
            "narration_text": "", "image_prompt": "", "motion_prompt": "",
            "subtitle_text": "", "simulasyon": True, "kaynak": "gecersiz_kod",
            "hata": (f"Bilinmeyen burç kodu: {burc_kodu!r}. "
                     f"Geçerli kodlar: {', '.join(BURC_KATALOGU)}"),
        }
    try:
        sn = max(3.0, min(120.0, float(sure_sn)))
    except (TypeError, ValueError):
        sn = 15.0
    dil, konu = (dil or "tr").strip().lower(), (konu or "").strip()
    anahtarlar = _gemini_anahtarlari()
    son_hata = "GEMINI_API_KEY bulunamadı"
    istem = _gemini_istem(burc, konu, sn, dil)

    for model in ("gemini-2.5-flash", "gemini-2.0-flash"):
        for anahtar in anahtarlar[:3]:
            try:
                veri = _json_ayikla(_gemini_istek(anahtar, model, istem))
                anlatim = str(veri.get("narration_text") or "").strip()
                gorsel = str(veri.get("image_prompt") or "").strip()
                hareket = str(veri.get("motion_prompt") or "").strip()
                if not (anlatim and gorsel and hareket):
                    raise ValueError("Gemini yanıtında zorunlu alanlar eksik")
                return {
                    "ok": True, "burc_kodu": kod, "burc_adi": burc["ad"],
                    "narration_text": anlatim, "image_prompt": gorsel,
                    "motion_prompt": hareket, "subtitle_text": anlatim,
                    "simulasyon": False, "kaynak": f"gemini:{model}",
                }
            except Exception as e:  # her anahtar/model denenir, son hata raporlanır
                son_hata = f"{type(e).__name__}: {str(e)[:160]}"
    return _cevrimdisi_sonuc(burc, konu, dil, son_hata)


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
