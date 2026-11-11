# Fabrika GPU İşçisi — Kaggle / Colab Başlatma Rehberi

Bu klasördeki `gpu_worker.py`, **FLUX.2-klein-4B** (görsel) ve **Wan2.1**
(gerçek video difüzyonu) modellerini Kaggle/Colab GPU'sunda **yerel** çalıştırır.
Kota yok, API ücreti yok, üçüncü taraf servis yok.

---

## Neden bu yol?

Ölçülen engeller (2026-11-11):

| Yol | Sonuç |
|---|---|
| HF ZeroGPU Space'leri (FLUX.2-dev / klein-4B / turbo) | `ZeroGPU runs limit` — kota dolu |
| HF Inference Providers (fal-ai / wavespeed / together) | `402 pre-paid credits` |
| Pollinations | Yalnız `sana` modeli; kenar enerjisi 8.39 (zayıf) |
| Cloudflare Workers AI FLUX.1-schnell | ✅ Çalışıyor (ücretsiz katman) ama FLUX.2 değil |

Kaggle/Colab GPU'su bu sınırların **hiçbirine** takılmaz.

---

## Doğrulanmış modeller ve VRAM

| Model | Parametre | bf16 VRAM | T4 16 GB |
|---|---|---|---|
| `black-forest-labs/FLUX.2-klein-4B` | 3.88 B | ~7.8 GB | ✅ CPU offload ile |
| `Wan-AI/Wan2.1-T2V-1.3B` | 1.42 B | ~2.8 GB | ✅ rahat |
| `Wan-AI/Wan2.1-I2V-14B-480P` | 16.39 B | ~33 GB | ⚠️ sequential offload (yavaş) |

Hepsi `gated=False` — HF onayı beklemeden indirilir.

---

## Kaggle (önerilen — 30 saat/hafta ücretsiz)

1. [kaggle.com](https://kaggle.com) → **Create → New Notebook**
2. Sağ panel → **Accelerator: GPU T4 x2** (veya P100)
3. **Internet: On** (sağ panel → Session options)
4. İlk hücreye yapıştır ve çalıştır:

```python
!git clone https://github.com/sufhinyusa/yusasufhin-cockpit.git
%cd yusasufhin-cockpit
!pip -q install -r requirements-gpu.txt
```

5. İkinci hücre — GPU ve model desteğini doğrula:

```python
!python gpu_worker.py --gpu-kontrol
```

Beklenen çıktı:
```
GPU: Tesla T4  (15.6 GB, kaynak=nvidia-smi)
torch=2.x  diffusers=0.x
Flux2Pipeline: True
WanPipeline: True
WanImageToVideoPipeline: True
```

6. Üçüncü hücre — işçiyi başlat:

```python
!python gpu_worker.py --server https://yusasufhin.com --kalite 480p
```

İşçi 15 saniyede bir kuyruğu yoklar. Sitede **Render Hedefi = Kaggle 32 GB**
seçilerek üretilen her iş otomatik olarak buraya düşer.

---

## Colab

Aynı hücreler çalışır. Fark:

- **Runtime → Change runtime type → T4 GPU**
- Colab T4 oturumu ~12 saatte bir düşer; işçi yeniden başlatılmalı
- Colab ücretsiz planda GPU kotası daha kısa

---

## Kullanım seçenekleri

```bash
# Tek iş al ve çık (test için)
python gpu_worker.py --tek-seferlik

# Yalnız ortamı doğrula, iş alma
python gpu_worker.py --gpu-kontrol

# Yüksek çözünürlük (720p sınıfı)
python gpu_worker.py --kalite 720p

# Daha kaliteli ama yavaş
python gpu_worker.py --t2v-adim 40 --i2v-adim 30

# Sabit işçi kimliği (telemetride tanınması için)
python gpu_worker.py --isci-id kaggle_ana
```

---

## İş akışı

```
Site (yusasufhin.com)
  └─ POST /api/studio/video/generate  { render_target: "kaggle_32gb" }
       ├─ Yerel önizleme hemen üretilir (kullanıcı bekletilmez)
       └─ Kayıt gpu_kuyruk=True ile işaretlenir
                    │
                    ▼
Kaggle/Colab işçisi
  ├─ GET  /api/worker/claim        → işi alır (gpu_kuyruk öncelikli)
  ├─      Wan2.1-T2V-1.3B difüzyonu → gerçek video
  ├─ POST /api/worker/progress     → ilerleme
  └─ POST /api/worker/upload       → MP4'ü siteye yükler
                    │
                    ▼
Site: iş kaydı "tamamlandi (Kaggle Dual-T4 GPU Render)" olur,
      output_url yeni GPU videosunu gösterir
```

---

## Yöntem eşlemesi

| `method` | Model | Ne üretir |
|---|---|---|
| `remotion_cinema`, `blender_wan`, `opus_canvas`, `viral_shorts` | Wan2.1-T2V-1.3B | Gerçek video difüzyonu (metinden) |
| `wan_i2v` | Wan2.1-I2V-14B-480P | Gerçek görselden-videoya difüzyonu |
| `flux2` | FLUX.2-klein-4B | FLUX.2 görseli (3 sn MP4 olarak) |

---

## Dürüstlük notları (Kural 1)

- **Wan2.1-T2V-1.3B** gerçek video difüzyonudur; kareler arası fizik
  sürekliliği vardır. Kare-farkı ile doğrulanabilir.
- **Wan2.1-I2V-14B** 16 GB'a bf16'da sığmaz; `enable_sequential_cpu_offload()`
  ile çalışır ve **5 sn klip ≈ 10–25 dk** sürer. Hızlı değildir.
- İşçi hangi modeli gerçekten çalıştırdığını `engine` alanında bildirir.
- GPU yoksa işçi **çalışmaz** ve bunu açıkça söyler — sahte çıktı üretmez.
- Model indirmeleri ilk çalıştırmada 8–35 GB olabilir; Kaggle'da `/kaggle/working`
  kalıcı değildir, her oturumda yeniden iner.
