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

import logging
import os
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
            "hata": f"ffmpeg {RENDER_ZAMAN_ASIMI_SN} sn içinde bitmedi (zaman aşımı)",
        }
    except Exception as e:
        gecici.unlink(missing_ok=True)
        return {"basarili": False, "yol": None, "boyut": 0, "hata": f"ffmpeg çalıştırılamadı: {e}"}

    if proc.returncode != 0:
        gecici.unlink(missing_ok=True)
        kuyruk = (proc.stderr or "").strip().splitlines()[-3:]
        return {
            "basarili": False, "yol": None, "boyut": 0,
            "hata": "ffmpeg hata kodu %s: %s" % (
                proc.returncode, " | ".join(kuyruk) or "çıktı yok"
            ),
        }

    gecerli, neden = mp4_gecerli_mi(gecici)
    if not gecerli:
        gecici.unlink(missing_ok=True)
        return {"basarili": False, "yol": None, "boyut": 0, "hata": f"doğrulama başarısız: {neden}"}

    os.replace(gecici, hedef_mp4)  # atomik: yarım dosya asla hedefte görünmez
    kart.unlink(missing_ok=True)

    return {
        "basarili": True,
        "yol": hedef_mp4,
        "boyut": hedef_mp4.stat().st_size,
        "sure_sn": sure,
        "cozunurluk": f"{genislik}x{yukseklik}",
        "baslik_karti": kart_yolu is not None,
        "hata": None,
    }

