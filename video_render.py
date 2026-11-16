# -*- coding: utf-8 -*-
"""video_render.py — Stüdyo önizleme videosunu GERÇEK, OYNATILABİLİR ve DOĞRULANMIŞ üretir.

NEDEN BU MODÜL VAR (2026-11-10 kök neden):
`studio_controller.py` içindeki eski render hattı iki ayrı kusur taşıyordu:

1. **Oynatılamıyordu.** `subprocess.run(..., timeout=15)` ffmpeg'i 15. saniyede
   öldürüyordu. Render free CPU'da 720p30 kodlama 15 sn'yi aştığı için süreç
   SIGKILL alıyor, MP4'ün `moov` atomu hiç yazılmıyor ve geriye 2 KB'lık
   açılamayan bir dosya kalıyordu ("moov atom not found").
2. **Boştu.** Video `color=...` + iki `drawbox`tan ibaretti; prompt/kanal ile
   hiçbir ilişkisi yoktu. 5 sn 720p düz renk = ~85 KB → "90 KB'ı geçmiyor,
   belli ki boş video" tespiti birebir doğruydu.

Bu modül şunları garanti eder:
* Prompt metni + kanal adı gerçekten kareye basılır (PIL ile başlık kartı).
* Render geçici dosyaya yazılır, `moov` atomu doğrulanır, ancak ondan sonra
  atomik olarak hedefe taşınır — yarım/bozuk MP4 asla yayınlanmaz.
* Süre sınırı gerçek iş yüküne göre (120 sn) verilir; sessiz zaman aşımı yok.
* `-movflags +faststart` ile `moov` dosyanın başına yazılır → tarayıcı
  indirme bitmeden oynamaya başlar.

Dürüstlük (Kural 1): üretilen çıktı tam sinematik prodüksiyon DEĞİLDİR;
prompt metnini taşıyan kılavuz önizlemedir ve kareye "(simülasyon)" yazılır.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("YusasufhinCockpit.VideoRender")

KOK = Path(__file__).resolve().parent

# Yarım kalan MP4'lerin "geçerli" sayılmaması için taban boyut.
MIN_GECERLI_BAYT = 20 * 1024
RENDER_ZAMAN_ASIMI_SN = 120


# -----------------------------------------------------------------------------
# 1. MP4 DOĞRULAMA (ffprobe bağımlılığı yok — Render'da ffprobe olmayabilir)
# -----------------------------------------------------------------------------
def _kutulari_gez(yol: Path) -> List[Tuple[bytes, int, int]]:
    """MP4 üst düzey kutularını (box) döner: (tür, ofset, boyut)."""
    kutular: List[Tuple[bytes, int, int]] = []
    try:
        toplam = yol.stat().st_size
    except OSError:
        return kutular

    with yol.open("rb") as fh:
        ofs = 0
        while ofs + 8 <= toplam:
            fh.seek(ofs)
            bas = fh.read(8)
            if len(bas) < 8:
                break
            boyut = int.from_bytes(bas[:4], "big")
            tur = bas[4:8]
            baslik = 8
            if boyut == 1:  # 64-bit genişletilmiş boyut
                genis = fh.read(8)
                if len(genis) < 8:
                    break
                boyut = int.from_bytes(genis, "big")
                baslik = 16
            elif boyut == 0:  # dosya sonuna kadar
                boyut = toplam - ofs
            if boyut < baslik:
                break
            kutular.append((tur, ofs, boyut))
            ofs += boyut
    return kutular


def mp4_gecerli_mi(yol: Path | str, min_bayt: int = MIN_GECERLI_BAYT) -> Tuple[bool, str]:
    """MP4 gerçekten oynatılabilir mi? (ftyp + moov + mdat atomları + asgari boyut)

    Döner: (gecerli, neden)
    """
    p = Path(yol)
    if not p.is_file():
        return False, "dosya yok"
    try:
        boyut = p.stat().st_size
    except OSError as e:
        return False, f"boyut okunamadı: {e}"
    if boyut < min_bayt:
        return False, f"dosya çok küçük ({boyut} bayt) — yarım kalmış render"

    turler = {t for t, _, _ in _kutulari_gez(p)}
    if b"ftyp" not in turler:
        return False, "ftyp kutusu yok — MP4 başlığı geçersiz"
    if b"moov" not in turler:
        return False, "moov atomu yok — dosya sonlandırılmamış (ffmpeg yarıda kesilmiş)"
    if b"mdat" not in turler:
        return False, "mdat kutusu yok — video verisi yazılmamış"
    return True, "geçerli"



# -----------------------------------------------------------------------------
# 2. BAŞLIK KARTI (gerçek metin içerik — düz renk değil)
# -----------------------------------------------------------------------------
def _font(boyut: int):
    """Türkçe karakterleri (ç ğ ı İ ö ş ü) destekleyen ölçeklenebilir font.

    PIL'in `load_default()` fontu yalnız Latin-1 alt kümesini taşır; "ÖNİZLEME"
    gibi metinler kutucuk (tofu) olarak çiziliyordu. Bu yüzden gerçek bir TTF
    aranır: macOS/Linux/Windows yaygın yolları + repo içi font.
    """
    adaylar = [
        KOK / "static" / "fonts" / "DejaVuSans.ttf",
        KOK / "static" / "fonts" / "DejaVuSans-Bold.ttf",
        # macOS
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        # Linux (Render/Debian)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        # Windows
        "C:/Windows/Fonts/arial.ttf",
    ]
    try:
        from PIL import ImageFont

        for aday in adaylar:
            try:
                if os.path.isfile(str(aday)):
                    return ImageFont.truetype(str(aday), boyut)
            except Exception:
                continue
        # Son çare: ölçeklenebilir varsayılan (Türkçe glif yok → ASCII'ye düşülür)
        try:
            return ImageFont.load_default(size=boyut)
        except TypeError:
            return ImageFont.load_default()
    except Exception:  # Pillow yok
        return None


def _ascii_guvenli(metin: str) -> str:
    """Font Türkçe glif taşımıyorsa kutucuk çizmemek için sadeleştirir."""
    tablo = str.maketrans({
        "ç": "c", "Ç": "C", "ğ": "g", "Ğ": "G", "ı": "i", "İ": "I",
        "ö": "o", "Ö": "O", "ş": "s", "Ş": "S", "ü": "u", "Ü": "U",
        "•": "-", "—": "-", "–": "-", "’": "'", "“": '"', "”": '"',
    })
    return metin.translate(tablo)



def _sar(draw, metin: str, font, azami_genislik: int) -> List[str]:
    """Metni verilen piksel genişliğine göre satırlara böler."""
    kelimeler = metin.split()
    if not kelimeler:
        return []
    satirlar: List[str] = []
    aktif = kelimeler[0]
    for kelime in kelimeler[1:]:
        aday = f"{aktif} {kelime}"
        try:
            genislik = draw.textlength(aday, font=font)
        except Exception:
            genislik = len(aday) * 8
        if genislik <= azami_genislik:
            aktif = aday
        else:
            satirlar.append(aktif)
            aktif = kelime
    satirlar.append(aktif)
    return satirlar


def _ttf_mi(font) -> bool:
    """Font gerçek bir TTF mi (Türkçe glif taşır)? PIL varsayılan fontu değilse evet."""
    return font is not None and hasattr(font, "path")


def _metin(font, metin: str) -> str:
    """TTF yoksa kutucuk çizmemek için metni ASCII'ye indirger."""
    return metin if _ttf_mi(font) else _ascii_guvenli(metin)


def baslik_karti_uret(
    png_yolu: Path,
    baslik: str,
    prompt: str,
    genislik: int,
    yukseklik: int,
    vurgu: Tuple[int, int, int] = (56, 189, 248),
) -> Optional[Path]:
    """Prompt metnini taşıyan PNG başlık kartı üretir. Pillow yoksa None döner."""
    try:
        from PIL import Image, ImageDraw
    except Exception as e:  # pragma: no cover - bağımlılık yoksa
        logger.warning("[VideoRender] Pillow yok, başlık kartı atlanıyor: %s", e)
        return None

    img = Image.new("RGB", (genislik, yukseklik), (10, 15, 29))
    draw = ImageDraw.Draw(img)

    # Dikey gradyan zemin (düz renk yerine derinlik)
    ust = (12, 18, 34)
    alt = (26, 38, 66)
    for y in range(yukseklik):
        oran = y / max(1, yukseklik - 1)
        renk = tuple(int(ust[i] + (alt[i] - ust[i]) * oran) for i in range(3))
        draw.line([(0, y), (genislik, y)], fill=renk)

    # Vurgu şeritleri
    draw.rectangle([0, 0, genislik, 6], fill=vurgu)
    draw.rectangle([0, yukseklik - 6, genislik, yukseklik], fill=vurgu)

    kenar = int(genislik * 0.08)
    ic_genislik = genislik - 2 * kenar

    f_kanal = _font(max(18, int(yukseklik * 0.045)))
    f_baslik = _font(max(26, int(yukseklik * 0.085)))
    f_alt = _font(max(14, int(yukseklik * 0.030)))

    y_imlec = int(yukseklik * 0.16)
    if f_kanal is not None:
        draw.text((kenar, y_imlec), _metin(f_kanal, baslik.upper()[:48]), font=f_kanal, fill=vurgu)
        y_imlec += int(yukseklik * 0.09)

    if f_baslik is not None:
        for satir in _sar(draw, _metin(f_baslik, prompt.strip()), f_baslik, ic_genislik)[:4]:
            draw.text((kenar, y_imlec), satir, font=f_baslik, fill=(238, 244, 255))
            y_imlec += int(yukseklik * 0.105)

    if f_alt is not None:
        # Dürüstlük etiketi (Kural 1): bu bir kılavuz önizlemedir.
        draw.text(
            (kenar, yukseklik - int(yukseklik * 0.11)),
            _metin(f_alt, "KILAVUZ ÖNİZLEME • (simülasyon)"),
            font=f_alt,
            fill=(148, 163, 184),
        )

    png_yolu.parent.mkdir(parents=True, exist_ok=True)
    img.save(png_yolu, "PNG")
    return png_yolu


# -----------------------------------------------------------------------------
# 3. RENDER (geçici dosya → doğrulama → atomik taşıma)
# -----------------------------------------------------------------------------
def _ffmpeg_bul() -> str:
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


def video_render_et(
    hedef_mp4: Path,
    baslik: str,
    prompt: str,
    genislik: int,
    yukseklik: int,
    sure_sn: float,
    ses_yolu: Optional[Path] = None,
    vurgu: Tuple[int, int, int] = (56, 189, 248),
    pilot_frekans: int = 440,
) -> Dict[str, Any]:
    """Oynatılabilir önizleme MP4'ü üretir ve doğrular.

    Döner: {"basarili": bool, "yol": Path|None, "boyut": int, "hata": str|None}
    """
    hedef_mp4 = Path(hedef_mp4)
    hedef_mp4.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef_mp4.with_name(hedef_mp4.stem + ".part.mp4")
    kart = hedef_mp4.with_name(hedef_mp4.stem + "_kart.png")

    sure = max(2.0, float(sure_sn))
    ffmpeg = _ffmpeg_bul()

    kart_yolu = baslik_karti_uret(
        kart, baslik=baslik, prompt=prompt,
        genislik=genislik, yukseklik=yukseklik, vurgu=vurgu,
    )

    cmd: List[str] = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]

    if kart_yolu is not None:
        # Statik kart + yavaş zum (zoompan) → gerçek hareket, boş kare değil
        cmd += ["-loop", "1", "-framerate", "30", "-t", f"{sure:.3f}", "-i", str(kart_yolu)]
        filtre = (
            f"[0:v]scale={genislik}:{yukseklik},"
            f"zoompan=z='min(zoom+0.0009,1.10)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={genislik}x{yukseklik}:fps=30,"
            f"fade=t=in:st=0:d=0.6,fade=t=out:st={max(0.0, sure - 0.6):.3f}:d=0.6,"
            f"format=yuv420p[v]"
        )
    else:
        # Pillow yoksa bile metin yerine hareketli geometri (dürüst yedek)
        cmd += [
            "-f", "lavfi",
            "-i", f"color=c=0x0a0f1d:s={genislik}x{yukseklik}:d={sure:.3f}:r=30",
        ]
        filtre = (
            f"[0:v]drawbox=x=40:y=120:w={genislik - 80}:h=80:"
            f"color=0x38bdf8@0.35:t=fill,"
            f"drawbox=x=40:y=200:w={genislik - 80}:h=6:color=0x38bdf8:t=fill,"
            f"format=yuv420p[v]"
        )

    if ses_yolu is not None and Path(ses_yolu).is_file() and Path(ses_yolu).stat().st_size > 500:
        cmd += ["-i", str(ses_yolu)]
        ses_harita = "1:a"
    else:
        cmd += ["-f", "lavfi", "-i",
                f"sine=frequency={pilot_frekans}:duration={sure:.3f}:sample_rate=44100"]
        ses_harita = "1:a"

    cmd += [
        "-filter_complex", filtre,
        "-map", "[v]", "-map", ses_harita,
        "-t", f"{sure:.3f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-shortest",
        str(gecici),
    ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=RENDER_ZAMAN_ASIMI_SN
        )
    except subprocess.TimeoutExpired:
        gecici.unlink(missing_ok=True)
        return {
            "basarili": False, "yol": None, "boyut": 0,
            "simulasyon": True, "kaynak": "baslik_karti",
            "engine": "PIL baslik karti + ffmpeg zoompan (onizleme)",
            "hata": f"ffmpeg {RENDER_ZAMAN_ASIMI_SN} sn içinde bitmedi (zaman aşımı)",
        }
    except Exception as e:
        gecici.unlink(missing_ok=True)
        return {
            "basarili": False, "yol": None, "boyut": 0,
            "simulasyon": True, "kaynak": "baslik_karti",
            "engine": "PIL baslik karti + ffmpeg zoompan (onizleme)",
            "hata": f"ffmpeg çalıştırılamadı: {e}",
        }

    if proc.returncode != 0:
        gecici.unlink(missing_ok=True)
        kuyruk = (proc.stderr or "").strip().splitlines()[-3:]
        return {
            "basarili": False, "yol": None, "boyut": 0,
            "simulasyon": True, "kaynak": "baslik_karti",
            "engine": "PIL baslik karti + ffmpeg zoompan (onizleme)",
            "hata": "ffmpeg hata kodu %s: %s" % (
                proc.returncode, " | ".join(kuyruk) or "çıktı yok"
            ),
        }

    gecerli, neden = mp4_gecerli_mi(gecici)
    if not gecerli:
        gecici.unlink(missing_ok=True)
        return {
            "basarili": False, "yol": None, "boyut": 0,
            "simulasyon": True, "kaynak": "baslik_karti",
            "engine": "PIL baslik karti + ffmpeg zoompan (onizleme)",
            "hata": f"doğrulama başarısız: {neden}",
        }

    os.replace(gecici, hedef_mp4)  # atomik: yarım dosya asla hedefte görünmez
    kart.unlink(missing_ok=True)

    return {
        "basarili": True,
        "yol": hedef_mp4,
        "boyut": hedef_mp4.stat().st_size,
        "sure_sn": sure,
        "cozunurluk": f"{genislik}x{yukseklik}",
        "baslik_karti": kart_yolu is not None,
        # Kural 1: bu çıktı gerçek video difüzyonu değil, açıkça etiketli önizleme.
        "simulasyon": True,
        "kaynak": "baslik_karti",
        "engine": (
            "PIL baslik karti + ffmpeg zoompan (onizleme)"
            if kart_yolu is not None
            else "ffmpeg hareketli geometri (onizleme, Pillow yok)"
        ),
        "hata": None,
    }


# -----------------------------------------------------------------------------
# 4. RENDER SONRASI KALİTE VE İLK-KARE DENETİMİ (Link #296: brag + ffmpeg-skill)
# -----------------------------------------------------------------------------
def _ffprobe_bul() -> Optional[str]:
    """Sistemde varsa `ffprobe` yürütülebilir dosya yolunu döner."""
    aday = shutil.which("ffprobe")
    if aday:
        return aday
    ffmpeg_yol = Path(_ffmpeg_bul())
    kardes = ffmpeg_yol.with_name("ffprobe")
    if kardes.is_file():
        return str(kardes)
    return None


def _medya_akislari_tara(mp4_yolu: Path) -> Dict[str, Any]:
    """ffprobe (yoksa ffmpeg -i) ile çözünürlük, fps, süre, kodek ve ses bilgisi döner."""
    sonuc: Dict[str, Any] = {
        "genislik": 0, "yukseklik": 0, "fps": 0.0,
        "sure_sn": 0.0, "video_codec": None, "ses_var": False,
    }
    ffprobe = _ffprobe_bul()
    if ffprobe:
        try:
            r = subprocess.run(
                [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(mp4_yolu)],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0 and r.stdout.strip():
                veri = json.loads(r.stdout)
                sonuc["sure_sn"] = round(float((veri.get("format") or {}).get("duration") or 0.0), 2)
                for s in veri.get("streams") or []:
                    if s.get("codec_type") == "video" and not sonuc["genislik"]:
                        sonuc["genislik"] = int(s.get("width") or 0)
                        sonuc["yukseklik"] = int(s.get("height") or 0)
                        sonuc["video_codec"] = s.get("codec_name")
                        fps_ham = str(s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1")
                        if "/" in fps_ham:
                            pay, payda = fps_ham.split("/", 1)
                            if float(payda or 0) > 0:
                                sonuc["fps"] = round(float(pay) / float(payda), 2)
                    elif s.get("codec_type") == "audio":
                        sonuc["ses_var"] = True
                return sonuc
        except Exception as e_fp:
            logger.debug("[VideoRender] ffprobe taraması atlandı: %s", e_fp)

    try:
        r2 = subprocess.run(
            [_ffmpeg_bul(), "-hide_banner", "-i", str(mp4_yolu)],
            capture_output=True, text=True, timeout=15,
        )
        bilgi = r2.stderr or ""
        m_dur = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", bilgi)
        if m_dur:
            sonuc["sure_sn"] = round(int(m_dur.group(1)) * 3600 + int(m_dur.group(2)) * 60 + float(m_dur.group(3)), 2)
        m_vid = re.search(r"Video:\s*([a-zA-Z0-9_]+).*?,\s*(\d{2,5})x(\d{2,5})", bilgi)
        if m_vid:
            sonuc["video_codec"] = m_vid.group(1)
            sonuc["genislik"] = int(m_vid.group(2))
            sonuc["yukseklik"] = int(m_vid.group(3))
        m_fps = re.search(r"(\d+(?:\.\d+)?)\s*fps\b", bilgi)
        if m_fps:
            sonuc["fps"] = round(float(m_fps.group(1)), 2)
        sonuc["ses_var"] = "Audio:" in bilgi
    except Exception as e_ff:
        logger.debug("[VideoRender] ffmpeg bilgi taraması atlandı: %s", e_ff)
    return sonuc


def _kare_istatistik(mp4_yolu: Path, an_sn: float) -> Optional[Dict[str, float]]:
    """Belirli saniyeden tek kare çıkarır ve ortalama parlaklık ile piksel standart sapmasını hesaplar."""
    try:
        from PIL import Image, ImageStat
    except Exception:
        return None
    cmd = [
        _ffmpeg_bul(), "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, float(an_sn)):.3f}",
        "-i", str(mp4_yolu),
        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=15)
        if r.returncode != 0 or len(r.stdout) < 100:
            return None
        im = Image.open(io.BytesIO(r.stdout)).convert("RGB")
        st = ImageStat.Stat(im)
        r_m, g_m, b_m = st.mean[:3]
        luma = 0.2126 * r_m + 0.7152 * g_m + 0.0722 * b_m
        max_std = max(st.stddev[:3])
        return {"mean_luma": round(luma, 2), "max_stddev": round(max_std, 2)}
    except Exception as e_kr:
        logger.debug("[VideoRender] Kare istatistiği hatası (%.2fs): %s", an_sn, e_kr)
        return None


def video_kalite_denetle(
    yol: Path | str,
    beklenen_oran: Optional[str] = None,
) -> Dict[str, Any]:
    """MP4 çıkışını yapı, ilk-kare parlaklık/düzlük (brag) ve akış telemetrisi (ffmpeg-skill) açısından denetler."""
    p = Path(yol)
    gecerli, neden = mp4_gecerli_mi(p)
    if not gecerli:
        return {
            "gecerli": False, "uygun": False, "neden": neden, "uyarilar": [neden],
            "genislik": 0, "yukseklik": 0, "fps": 0.0, "sure_sn": 0.0,
            "video_codec": None, "ses_var": False,
            "ilk_kare_siyah": False, "ilk_kare_duz": False, "bos_video": False,
            "platform_uyumu": "bilinmiyor",
        }

    meta = _medya_akislari_tara(p)
    sure_sn = float(meta.get("sure_sn") or 0.0)
    w, h = int(meta.get("genislik") or 0), int(meta.get("yukseklik") or 0)

    ilk = _kare_istatistik(p, 0.0)
    orta_an = min(max(0.25, sure_sn * 0.5), max(0.25, sure_sn - 0.1)) if sure_sn > 0.5 else 0.0
    orta = _kare_istatistik(p, orta_an) if orta_an > 0 else ilk

    ilk_duz = bool(ilk and ilk["max_stddev"] < 2.5)
    ilk_siyah = bool(ilk and ilk["mean_luma"] < 8.0 and ilk["max_stddev"] < 10.0)
    orta_duz = bool(orta and orta["max_stddev"] < 2.5)
    orta_siyah = bool(orta and orta["mean_luma"] < 8.0 and orta["max_stddev"] < 10.0)
    bos_video = bool((ilk_duz and (orta is None or orta_duz)) or (ilk_siyah and orta is not None and orta_siyah))

    uyarilar: List[str] = []
    if bos_video:
        uyarilar.append("İlk ve orta kareler düz/siyah — boş render şüphesi")
    elif ilk_duz or ilk_siyah:
        uyarilar.append("İlk kare koyu/düz (fade-in veya kararmış giriş karesi)")

    if beklenen_oran and w > 0 and h > 0:
        oran_temiz = beklenen_oran.strip()
        if oran_temiz == "9:16" and w > h:
            uyarilar.append(f"Çözünürlük ({w}x{h}) 9:16 dikey hedefiyle uyumsuz")
        elif oran_temiz == "16:9" and h > w:
            uyarilar.append(f"Çözünürlük ({w}x{h}) 16:9 yatay hedefiyle uyumsuz")

    platform_uyumu = "reels_shorts_tiktok" if (h > w and w > 0) else ("youtube_yatay" if w > 0 else "bilinmiyor")
    return {
        "gecerli": True,
        "uygun": not bos_video,
        "neden": "; ".join(uyarilar) if uyarilar else "geçerli",
        "uyarilar": uyarilar,
        **meta,
        "ilk_kare_siyah": ilk_siyah,
        "ilk_kare_duz": ilk_duz,
        "bos_video": bos_video,
        "platform_uyumu": platform_uyumu,
    }

