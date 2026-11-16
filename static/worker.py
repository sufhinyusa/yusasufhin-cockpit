#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fabrika GPU işçisi bootstrap'i — FABRİKA BULUT GPU İŞÇİSİ (Kaggle / Colab).

Bu dosya SAHTE ffmpeg drawbox/color kutusu ÜRETMEZ. Tek işi vardır:
gpu_worker.py'yi (yerelde varsa doğrudan, yoksa sunucudan/GitHub'dan indirip)
gerçek FLUX.2 görsel + Wan2.1 video döngüsüyle çalıştırmak.

Kullanım:
  Kaggle/Colab:  !curl -sS https://yusasufhin.com/static/worker.py | python3 - --server https://yusasufhin.com
  Repo içinde:   python3 static/worker.py --server https://yusasufhin.com --token "$FABRIKA_WORKER_KEY"

Anahtar `--token` / `--worker-key` / `FABRIKA_WORKER_KEY` / `FABRIKA_TOKEN`
kaynaklarından birinden gelir ve gpu_worker.py'ye `--token` olarak geçirilir.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

BANNER = "FABRİKA BULUT GPU İŞÇİSİ"
VARSAYILAN_SUNUCU = "https://yusasufhin.com"
GITHUB_RAW = (
    "https://raw.githubusercontent.com/sufhinyusa/"
    "yusasufhin-cockpit/main/gpu_worker.py"
)


def _requests():
    """requests yoksa kurar; gerçek işçi zaten requests'e bağımlı değildir."""
    try:
        import requests
        return requests
    except ImportError:
        print("[GPU Worker] requests kuruluyor...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "requests"],
            check=False,
        )
        import requests
        return requests


def _kok_dizin() -> Path:
    try:
        return Path(__file__).resolve().parent
    except NameError:  # `curl | python3` durumunda __file__ yoktur
        return Path.cwd()


def _yerel_gpu_worker() -> Optional[Path]:
    kok = _kok_dizin()
    adaylar = (kok / "gpu_worker.py", kok.parent / "gpu_worker.py",
               Path.cwd() / "gpu_worker.py")
    for aday in adaylar:
        if aday.is_file():
            try:
                metin = aday.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "def main(" in metin and "gpu_worker.py" in metin:
                return aday
    return None


def _indir_gpu_worker(requests, sunucu: str) -> Optional[Path]:
    """Sunucudan, olmazsa GitHub raw'dan gerçek gpu_worker.py'yi indirir."""
    adaylar = [sunucu.rstrip("/") + "/gpu_worker.py", GITHUB_RAW]
    for url in adaylar:
        try:
            yanit = requests.get(url, timeout=20)
            metin = yanit.text or ""
            if (yanit.status_code == 200 and "def main(" in metin
                    and "gpu_worker.py" in metin
                    and "<!DOCTYPE html" not in metin[:300]):
                hedef = Path(tempfile.gettempdir()) / "fabrika_gpu_worker.py"
                hedef.write_text(metin, encoding="utf-8")
                print(f"[GPU Worker] gpu_worker.py indirildi: {url}")
                return hedef
            print(f"[GPU Worker] {url} geçerli gpu_worker.py döndürmedi "
                  f"(HTTP {yanit.status_code})")
        except Exception as e:
            print(f"[GPU Worker] {url} alınamadı ({type(e).__name__}: {e})")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Fabrika GPU işçisi bootstrap")
    ap.add_argument("--server",
                    default=os.environ.get("FABRIKA_SUNUCU", VARSAYILAN_SUNUCU))
    ap.add_argument("--token", "--worker-key", dest="token",
                    default=os.environ.get("FABRIKA_WORKER_KEY")
                    or os.environ.get("FABRIKA_TOKEN"))
    ap.add_argument("--tek-seferlik", action="store_true")
    ap.add_argument("--gpu-kontrol", action="store_true")
    args, _ = ap.parse_known_args()

    print("=" * 65)
    print(f"  🚀 {BANNER} (KAGGLE / COLAB)")
    print("=" * 65)
    print(f"  🌐 Sunucu : {args.server}")
    print(f"  🔑 Anahtar: {'ayarlı (Bearer + X-Worker-Key)' if args.token else 'YOK'}")
    print("=" * 65)

    token = (args.token or "").strip() or None
    if token:
        os.environ["FABRIKA_WORKER_KEY"] = token
    os.environ.setdefault("FABRIKA_SUNUCU", args.server)

    requests = _requests()
    gpu_yolu = _yerel_gpu_worker() or _indir_gpu_worker(requests, args.server)
    if gpu_yolu is None:
        print("❌ gpu_worker.py bulunamadı. Repoyu klonlayıp tekrar deneyin:")
        print("   git clone https://github.com/sufhinyusa/yusasufhin-cockpit.git")
        return 2

    argv = [str(gpu_yolu), "--server", args.server]
    if token:
        argv += ["--token", token]
    if args.tek_seferlik:
        argv.append("--tek-seferlik")
    if args.gpu_kontrol:
        argv.append("--gpu-kontrol")

    print(f"[GPU Worker] Gerçek FLUX.2/Wan2.1 döngüsü başlıyor: {gpu_yolu}")
    import runpy

    eski_argv = sys.argv
    sys.argv = argv
    try:
        runpy.run_path(str(gpu_yolu), run_name="__main__")
    except SystemExit as e:
        return int(e.code or 0)
    finally:
        sys.argv = eski_argv
    return 0


if __name__ == "__main__":
    sys.exit(main())
