# Ücretsiz Bulut Barındırma & Oracle Cloud Always Free ARM Kurulum Rehberi (2026)

Bu depo hem **Render (512 MB + Cloudflare R2)** hem de **Oracle Cloud Always Free ARM** (kalıcı disk, yüksek RAM) veya **Hugging Face Spaces Docker** üzerinde doğrudan çalışır.

---

## 1. Güncel Ücretsiz Barındırma Karşılaştırması (2026 Sonu)

| Platform | Ücretsiz Kaynak | Kalıcı Disk | Uyuma (Cold Start) | Öne Çıkan Artı / Eksi |
|---|---|---|---|---|
| **Oracle Cloud Always Free (ARM A1)** | **2 OCPU + 12 GB RAM** *(Haziran 2026'da 4 OCPU/24 GB'dan yarıya indirildi)* + 200 GB Block Storage | ✅ **200 GB kalıcı** | ❌ **7/24 uyanık** | En güçlü ücretsiz VPS; FFmpeg + kalıcı YouTube token + medya tek yerde. *Eksisi:* Popüler bölgelerde (Frankfurt/US) ARM kapasitesi çabuk dolar; kart doğrulaması ister. |
| **Hugging Face Spaces (Docker SDK)** | **2 vCPU + 16 GB RAM** | ⚠️ Geçici (50 GB ephemera) | ⚠️ 48 saat pasifse uyur | `Dockerfile` doğrudan çalışır, 16 GB RAM bol. *Eksisi:* Özel alan adı (`yusasufhin.com`) için Cloudflare Worker proxy gerekir, disk geçicidir. |
| **Render Free + Cloudflare R2** | 512 MB RAM + **R2 10 GB ücretsiz** | ⚠️ Disk geçici, **R2 kalıcı** | ⚠️ 15 dk pasifse uyur | Sıfır kurulum zahmeti; mevcut alan adınız zaten bağlı. R2 + `YOUTUBE_*` env eklendiğinde veri kaybı biter; ağır GPU işi Kaggle'a gider. |
| **Google Cloud e2-micro Always Free** | 1 GB RAM + 30 GB disk (US bölgeleri) | ✅ 30 GB kalıcı | ❌ 7/24 uyanık | Aylık 1 GB egress sınırı vardır (video indirme için R2 gerekir). |

---

## 2. Oracle Cloud Always Free ARM Kurulumu (Ubuntu 24.04 ARM64)

### Adım 1: Sunucuyu oluşturun
1. Oracle Cloud Free Tier hesabı açın (kapasite için Frankfurt doluysa **Marseille, Milan, Stockholm veya Amsterdam** bölgeleri daha rahat bulunur).
2. **Compute → Instances → Create Instance**:
   - Image: **Ubuntu 24.04 Minimal aarch64**
   - Shape: **VM.Standard.A1.Flex** → **2 OCPU, 12 GB RAM** (kapasite hatası verirse önce 1 OCPU / 6 GB deneyip sonra büyütün)
   - Boot volume: **100–200 GB**

### Adım 2: Docker & Depoyu kurun
```bash
sudo apt update && sudo apt install -y docker.io git
sudo usermod -aG docker $USER
newgrp docker

git clone https://github.com/sufhinyusa/yusasufhin-cockpit.git
cd yusasufhin-cockpit
```

### Adım 3: `.env` dosyasını hazırlayın (`chmod 600 .env`)
```env
FABRIKA_GATEWAY_PASSWORD=GUCLU_PAROLANIZ
GATEWAY_PIN=6_HANELI_PIN
BRIDGE_SECRET=MAC_KOPRU_SIRRI_VEYA_PAROLA
SESSION_SIGNING_SECRET=UZUN_RASTGELE_HEX
FABRIKA_WORKER_KEY=UZUN_GPU_ISCI_ANAHTARI

# Ses & Görsel & Video
GEMINI_API_KEY=...
HF_TOKEN=...
CLOUDFLARE_API_TOKEN=...
CLOUDFLARE_ACCOUNT_ID=...

# İsteğe Bağlı: Kalıcı Cloudflare R2 Medya Deposu (10 GB Ücretsiz)
# R2_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
# R2_BUCKET=yusasufhin-media
# R2_ACCESS_KEY_ID=...
# R2_SECRET_ACCESS_KEY=...

# İsteğe Bağlı: İletişim Formu Telegram Bildirimi
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_CHAT_ID=...
```

### Adım 4: Konteyneri kalıcı diskle başlatın
```bash
docker build -t yusasufhin-cockpit .
docker run -d --name cockpit --restart unless-stopped \
  --env-file .env \
  -p 127.0.0.1:27491:27491 \
  -v $(pwd)/storage:/app/storage \
  -v $(pwd)/data:/app/data \
  yusasufhin-cockpit
```

### Adım 5: Sıfır Açık Port ile `yusasufhin.com` Bağlama (Cloudflare Tunnel)
Sunucuda firewall/80/443 açmanıza bile gerek kalmaz:
```bash
# Cloudflare Zero Trust -> Networks -> Tunnels üzerinden aldığınız token ile:
docker run -d --name cloudflared --restart unless-stopped \
  --network host \
  cloudflare/cloudflared:latest tunnel --no-autoupdate run --token <CF_TUNNEL_TOKEN>
```
Cloudflare panelinde `yusasufhin.com` → `http://127.0.0.1:27491` yönlendirmesini seçtiğiniz anda siteniz **12 GB RAM + 200 GB kalıcı disk** üzerinde 7/24 yayına geçer.

---

## 3. Render'da Kalmak İsterseniz Kalıcılık İçin Yapılacak 2 Şey
1. Cloudflare Dashboard → **R2** → ücretsiz bucket oluşturun ve `R2_ENDPOINT_URL`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` değişkenlerini Render Environment'a ekleyin.
2. YouTube OAuth tamamlandıktan sonra oluşan `youtube_token.json` içeriğini `YOUTUBE_TOKEN_JSON` ve `client_secret.json` içeriğini `YOUTUBE_CLIENT_SECRET_JSON` olarak Render Environment'a ekleyin — sunucu yeniden başlasa bile kanallarınızın YouTube bağlantısı hiç kopmaz.
