#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fabrika Kaggle Dual-T4 & Google Colab Otonom GPU İşçisi (Link #226)
------------------------------------------------------------------
Kaggle'ın 30 saat/hafta ücretsiz sunduğu 32 GB Dual Tesla T4 GPU'larını
ve Google Colab GPU'larını yusasufhin.com video fabrikasına bağlar.

Kullanım:
  Kaggle veya Colab'da tek satırda çalıştırın:
    !curl -sS https://yusasufhin.com/worker.py | python3
"""
import os
import sys
import time
import json
import shutil
import subprocess
import argparse

# 1. Gerekli paketleri otomatik yükle
def ensure_packages():
    pkgs = []
    try:
        import requests
    except ImportError:
        pkgs.append("requests")
    if pkgs:
        print(f"[GPU Worker] Gerekli kütüphaneler kuruluyor: {pkgs}...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q"] + pkgs, check=False)

ensure_packages()
import requests

# 2. Donanım Tespiti (Tesla T4 / Dual GPU)
def detect_hardware():
    info = {"gpu_name": "CPU Yalnızca", "vram_gb": 0.0, "device_count": 0, "has_nvenc": False}
    try:
        import torch
        if torch.cuda.is_available():
            count = torch.cuda.device_count()
            total_vram = sum(torch.cuda.get_device_properties(i).total_memory / (1024**3) for i in range(count))
            gpu_names = [torch.cuda.get_device_name(i) for i in range(count)]
            info["gpu_name"] = " + ".join(gpu_names)
            info["vram_gb"] = round(total_vram, 1)
            info["device_count"] = count
    except Exception:
        pass

    # NVENC kontrolü
    try:
        r = subprocess.run(["ffmpeg", "-encoders"], capture_output=True, text=True)
        if "h264_nvenc" in r.stdout:
            info["has_nvenc"] = True
    except Exception:
        pass

    return info

def main():
    parser = argparse.ArgumentParser(description="Fabrika GPU Worker")
    parser.add_argument("--server", default=os.environ.get("FABRIKA_SERVER", "https://yusasufhin.com"), help="Fabrika Sunucu Adresi")
    parser.add_argument("--type", default=os.environ.get("WORKER_TYPE", "kaggle" if os.path.exists("/kaggle") else "colab"), help="İşçi Tipi (kaggle/colab)")
    args, _ = parser.parse_known_args()

    server_url = args.server.rstrip("/")
    worker_type = args.type
    worker_id = f"{worker_type}_{int(time.time())}_{os.urandom(2).hex()}"
    hw = detect_hardware()

    print("=" * 65)
    print("  🚀 FABRİKA BULUT GPU İŞÇİSİ (KAGGLE / COLAB)")
    print("=" * 65)
    print(f"  🌐 Hedef Sunucu  : {server_url}")
    print(f"  🆔 İşçi Kimliği  : {worker_id}")
    print(f"  ⚡ Tespit Edilen : {hw['gpu_name']} ({hw['vram_gb']} GB vRAM)")
    print(f"  🎞️ NVENC Donanım : {'✅ Aktif' if hw['has_nvenc'] else '⚪ Yazılımsal (libx264)'}")
    print("=" * 65)

    last_hb = 0
    work_dir = os.path.expanduser("~/fabrika_gpu_work")
    os.makedirs(work_dir, exist_ok=True)

    while True:
        now = time.time()
        # 1. Heartbeat gönder (her 15 saniyede bir)
        if now - last_hb >= 15:
            try:
                requests.post(
                    f"{server_url}/api/worker/heartbeat",
                    json={
                        "worker_id": worker_id,
                        "worker_type": worker_type,
                        "gpu_name": hw["gpu_name"],
                        "vram_gb": hw["vram_gb"],
                        "status": "ready"
                    },
                    timeout=8
                )
                last_hb = now
            except Exception as e:
                print(f"[Worker] Heartbeat gönderilemedi ({e}), 5sn sonra tekrar denenecek...")
                time.sleep(5)
                continue

        # 2. Kuyruktan iş talep et
        try:
            r = requests.get(f"{server_url}/api/worker/claim?worker_id={worker_id}", timeout=10)
            res = r.json()
            job = res.get("job")
            if not job:
                time.sleep(5)
                continue

            jid = job.get("job_id") or job.get("id")
            prompt = job.get("prompt") or job.get("topic") or "Fabrika Video"
            channel = job.get("channel") or "Tech_AI_Fabrika"
            aspect = job.get("aspect_ratio") or "16:9"
            print(f"\n🎬 [YENİ GÖREV ALINDI] {jid} | Kanal: {channel} | Konu: '{prompt[:60]}'")

            # Aşama 1: İlerleme bildir (%20 Seslendirme)
            requests.post(f"{server_url}/api/worker/progress", json={"job_id": jid, "progress_pct": 20, "stage": "Google Gemini Nöral Seslendirme"}, timeout=5)

            # Seslendirme üret (Google Gemini 2.5 Nöral TTS - Microsoft Edge Kesinlikle Yasaktır)
            voice = "Aoede" if "Astroloji" in channel else "Puck"
            speech_file = os.path.join(work_dir, f"{jid}_narration.wav")
            out_mp4 = os.path.join(work_dir, f"{jid}.mp4")

            try:
                r_aud = requests.post(
                    f"{server_url}/api/audio/process",
                    json={"action": "voice_clone_tts", "params": {"prompt": prompt, "voice": voice}},
                    timeout=25
                )
                if r_aud.status_code == 200:
                    aud_data = r_aud.json().get("data", {})
                    out_aud_url = aud_data.get("output_url")
                    if out_aud_url:
                        if not out_aud_url.startswith("http"):
                            out_aud_url = f"{server_url}{out_aud_url}"
                        r_down = requests.get(out_aud_url, timeout=30)
                        if r_down.status_code == 200 and len(r_down.content) > 1000:
                            with open(speech_file, "wb") as f_sp:
                                f_sp.write(r_down.content)
            except Exception as e_aud:
                print(f"[Worker] Google Gemini seslendirme isteği hatası: {e_aud}")

            # Ses süresini ölç
            dur = 6.0
            has_speech = os.path.exists(speech_file) and os.path.getsize(speech_file) > 1000
            if has_speech:
                try:
                    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", speech_file], text=True).strip()
                    dur = max(3.0, round(float(out), 2))
                except Exception:
                    pass

            # Aşama 2: İlerleme bildir (%50 GPU Render)
            requests.post(f"{server_url}/api/worker/progress", json={"job_id": jid, "progress_pct": 50, "stage": "Dual-T4 GPU Render & Kurgu"}, timeout=5)

            is_vertical = (aspect == "9:16")
            res_str = "1080x1920" if is_vertical else "1920x1080"
            color_bg = "#080c14"
            accent_col = "0x38bdf8"
            w_val = 1080 if is_vertical else 1920

            vcodec = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20"] if hw["has_nvenc"] else ["-c:v", "libx264", "-preset", "fast", "-crf", "22"]
            vf = f"color=c={color_bg}:s={res_str}:d={dur}:r=30,drawbox=x=60:y=180:w={w_val-120}:h=90:color={accent_col}@0.3:t=fill,drawbox=x=60:y=280:w={w_val-120}:h=6:color={accent_col}:t=fill"

            audio_args = ["-i", speech_file] if has_speech else ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}:sample_rate=44100"]

            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", vf,
                *audio_args,
                *vcodec,
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                out_mp4
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Aşama 3: Sunucuya yükle (%90)
            requests.post(f"{server_url}/api/worker/progress", json={"job_id": jid, "progress_pct": 90, "stage": "Sunucuya Yükleniyor"}, timeout=5)
            with open(out_mp4, "rb") as f_up:
                r_up = requests.post(f"{server_url}/api/worker/upload", data={"job_id": jid}, files={"file": (f"{jid}.mp4", f_up, "video/mp4")}, timeout=120)
                if r_up.status_code == 200:
                    print(f"✅ [GÖREV TAMAMLANDI VE YÜKLENDİ] {jid} (Boyut: {os.path.getsize(out_mp4)/1024:.1f} KB)")
                else:
                    print(f"⚠️ [Yükleme Hatası] HTTP {r_up.status_code}: {r_up.text}")

            # Temizlik
            for f_clean in (speech_file, out_mp4):
                if os.path.exists(f_clean):
                    os.remove(f_clean)

        except Exception as err:
            print(f"[Worker Döngü Hatası]: {err}")
            time.sleep(5)

if __name__ == "__main__":
    main()

