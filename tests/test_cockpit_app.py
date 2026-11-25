"""
Kalıcı Güvenlik, Dürüstlük ve API Entegrasyon Testleri — yusasufhin_cockpit
"""
import os
import sys
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR))

# Test için güvenli ortam değişkenleri tanımla
os.environ["FABRIKA_GATEWAY_PASSWORD"] = "test_guclu_parola_9988"
os.environ["GATEWAY_PIN"] = "784321"

import main
from main import app, ACTIVE_SESSIONS, FAILED_ATTEMPTS, MEDIA_DIR


@pytest.fixture(autouse=True)
def _ag_bagimliligi_kapat(monkeypatch):
    """Testler AĞA ÇIKMAMALI (2026-11-11).

    `studio/video/generate` gerçek YZ sahne üretimi çağırıyor; testlerde bu
    Pollinations/FLUX'a gidip 60+ sn bekliyordu (hatta rate limit'e takılıyordu).
    Burada sahne üretimi yerel bir PNG'ye kısaltılır: hat, montaj ve etiketleme
    mantığı gerçek kalır, yalnız difüzyon çağrısı taklit edilir.
    """
    try:
        import ai_video_montaj as av
    except Exception:
        return

    def _sahte_sahneleri_uret(prompt, adet, genislik, yukseklik, log=None):
        import tempfile
        from pathlib import Path

        try:
            from PIL import Image, ImageDraw
        except Exception:
            return []
        d = Path(tempfile.mkdtemp(prefix="test_sahne_"))
        yollar = []
        for i in range(min(adet, 2)):
            p = d / f"s{i}.png"
            # Gerçek renkli gradyan + şekil (düz renk değil) — montaj anlamlı kalsın
            im = Image.new("RGB", (genislik, yukseklik), (10 + i * 40, 40, 90))
            dr = ImageDraw.Draw(im)
            for y in range(0, yukseklik, 2):
                oran = y / max(1, yukseklik - 1)
                dr.line([(0, y), (genislik, y)],
                        fill=(int(30 + 180 * oran), int(60 + 90 * oran), 140))
            dr.ellipse([genislik // 4, yukseklik // 4,
                        genislik * 3 // 4, yukseklik * 3 // 4],
                       fill=(200 - i * 60, 150, 80))
            im.save(p, "PNG")
            yollar.append(p)
        _sahte_sahneleri_uret.son_saglayici = "test"
        return yollar

    monkeypatch.setattr(av, "sahneleri_uret", _sahte_sahneleri_uret)


@pytest.fixture(autouse=True)
def isolate_test_environment(tmp_path, monkeypatch):
    """Testlerin üretim veri dosyalarını (video_jobs, rea_scans) kirletmesini önler."""
    test_data = tmp_path / "data"
    test_data.mkdir()
    monkeypatch.setattr(main, "DATA_DIR", test_data)
    ACTIVE_SESSIONS.clear()
    main.REVOKED_TOKENS.clear()
    main._TOKEN_MIN_CREATED_AT = 0.0
    FAILED_ATTEMPTS.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_token(client):
    """Meşru PIN ile geçerli oturum tokenı üretir."""
    res = client.post("/api/auth/verify_pin", json={"pin": "784321"})
    assert res.status_code == 200
    token = res.json()["token"]
    assert token in ACTIVE_SESSIONS
    return token


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


# -----------------------------------------------------------------------------
# 1. AUTH & BACKDOOR ÖNLEME TESTLERİ
# -----------------------------------------------------------------------------
def test_public_info_endpoint(client):
    res = client.get("/api/auth/public_info")
    assert res.status_code == 200
    assert res.json()["status"] == "online"
    assert res.json()["cluster_vram_gb"] == 0.0


def test_backdoor_pin_rejected(client):
    """İfşa olmuş zayıf PIN'ler (192300, 123456 vb.) kesinlikle 401 dönmelidir."""
    for bad_pin in ["192300", "123456", "091091", "999999", "000000"]:
        res = client.post("/api/auth/verify_pin", json={"pin": bad_pin})
        assert res.status_code == 401, f"PIN {bad_pin} reddedilmeliydi"


def test_backdoor_passwords_rejected(client):
    """Tahmin edilebilir sabit şifreler 401 dönmelidir."""
    for bad_pw in ["admin", "123456", "091091", "password", "root"]:
        res = client.post("/api/auth/login", json={"password": bad_pw})
        assert res.status_code == 401, f"Şifre {bad_pw} reddedilmeliydi"


def test_turkish_chars_no_500(client):
    """Türkçe veya özel karakterli parolalar 500 atmamalı, güvenle 401 dönmelidir."""
    res = client.post("/api/auth/login", json={"password": "şifre_çğü_öış"})
    assert res.status_code == 401
    res_pin = client.post("/api/auth/verify_pin", json={"pin": "şifre_ğü"})
    assert res_pin.status_code == 401


def test_legitimate_login(client):
    """Doğru parola ile oturum açılabilmeli ve token TTL kaydedilmelidir."""
    res = client.post("/api/auth/login", json={"password": "test_guclu_parola_9988"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    tok = data["token"]
    assert tok in ACTIVE_SESSIONS
    assert ACTIVE_SESSIONS[tok]["expires_at"] > ACTIVE_SESSIONS[tok]["created_at"]


def test_rate_limiting_locks_out(client):
    """5 ardışık hatalı denemede IP 429 Too Many Requests ile kilitlenmelidir."""
    for _ in range(5):
        res = client.post("/api/auth/verify_pin", json={"pin": "111222"})
        assert res.status_code in (401, 429)
    # 6. istek kilitlenmeli
    res_locked = client.post("/api/auth/verify_pin", json={"pin": "784321"})
    assert res_locked.status_code == 429
    assert "Çok fazla hatalı deneme" in res_locked.json()["message"]


# -----------------------------------------------------------------------------
# 2. YETKİLENDİRME (PROTECTED ENDPOINTS) TESTLERİ
# -----------------------------------------------------------------------------
def test_protected_endpoints_reject_unauthorized(client):
    """Token olmadan durum değiştiren veya korumalı tüm uçlar 401 dönmelidir."""
    endpoints = [
        ("POST", "/api/lab/generate", {"prompt": "x"}),
        ("POST", "/api/studio/video/generate", {}),
        ("POST", "/api/audio/process", {"action": "voice_clone_tts"}),
        ("POST", "/api/gpu/cluster/mode", {"mode": "kaggle_first"}),
        ("POST", "/api/omniroute/generate", {"prompt": "merhaba"}),
        ("POST", "/api/rea/scan", {"code": "x = 1"}),
        ("GET", "/api/media/file?path=test.png", None),
        ("POST", "/api/push/subscribe", {}),
        ("POST", "/api/tunnel/setup_domain", {}),
    ]
    for method, path, payload in endpoints:
        if method == "POST":
            res = client.post(path, json=payload)
        else:
            res = client.get(path)
        assert res.status_code == 401, f"{path} ucu tokensız 401 dönmeliydi, ancak {res.status_code} döndü"


def test_websocket_chat_rejects_unauthorized(client):
    """Token olmadan WebSocket bağlantısı kabul edilmemeli (4401 ile kapanmalıdır)."""
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_text()


def test_real_change_pin(client, auth_headers, monkeypatch, tmp_path):
    """change_pin eski PIN'i geçersiz kılmalı, yeni PIN'i kaydetmeli ve yeni token üretmelidir."""
    # Test ortamını izole et: geçici .env dosyası oluştur (üretim Persona/.env'ine dokunulmaz)
    test_env = tmp_path / ".env"
    test_env.write_text("GATEWAY_PIN=784321\n", encoding="utf-8")
    fake_persona = tmp_path / "Desktop" / "PYTHON PROJECTS" / "Fabrika" / "Persona"
    fake_persona.mkdir(parents=True, exist_ok=True)
    (fake_persona / ".env").write_text("GATEWAY_PIN=784321\n", encoding="utf-8")

    import main
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    res = client.post("/api/auth/change_pin", json={"old_pin": "784321", "new_pin": "651239"}, headers=auth_headers)
    assert res.status_code == 200
    new_token = res.json()["token"]

    # İzole geçici dosyaya yeni PIN yazılmış mı?
    assert "GATEWAY_PIN=651239" in test_env.read_text(encoding="utf-8")

    # Eski token iptal edilmiş olmalı
    res_old = client.get("/api/auth/check", headers=auth_headers)
    assert res_old.status_code == 401

    # Yeni token geçerli olmalı
    res_new = client.get("/api/auth/check", headers={"Authorization": f"Bearer {new_token}"})
    assert res_new.status_code == 200

    # Temizlik: test pinini geri yükle
    os.environ["GATEWAY_PIN"] = "784321"


def test_biometric_returns_501(client):
    """WebAuthn doğrulanmamışsa sahte token dağıtılmamalı, 501 dönmelidir."""
    res_login = client.post("/api/auth/biometric/login", json={"bio_id": "test"})
    assert res_login.status_code == 501
    res_reg = client.post("/api/auth/biometric/register", json={"device_name": "Mac"})
    assert res_reg.status_code == 501


# -----------------------------------------------------------------------------
# 3. GÜVENLİ MEDYA VE DİZİN ATLAMA (PATH TRAVERSAL) TESTLERİ
# -----------------------------------------------------------------------------
def test_media_path_traversal_blocked(client, auth_headers):
    """Kritik sistem dosyaları ve dizin atlama girişimleri kesinlikle engellenmelidir."""
    traversals = [
        "/etc/passwd",
        "/etc/hosts",
        "../../main.py",
        "../data/video_jobs.json",
        ".env",
        "../.env",
    ]
    for p in traversals:
        res = client.get(f"/api/media/file?path={p}", headers=auth_headers)
        assert res.status_code in (403, 404, 415), f"Path {p} için HTTP 200 dönmemeli! Alınan: {res.status_code}"


def test_media_legitimate_file_serving(client, auth_headers, tmp_path):
    """İzinli medya dizinindeki geçerli bir PNG dosyası sunulabilmelidir."""
    test_img = MEDIA_DIR / "test_sample.png"
    test_img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...")
    try:
        res = client.get(f"/api/media/file?path=test_sample.png", headers=auth_headers)
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/png"
        assert res.headers["x-content-type-options"] == "nosniff"
    finally:
        if test_img.exists():
            test_img.unlink()


# -----------------------------------------------------------------------------
# 4. KURAL 1 DÜRÜSTLÜK & DURUM MAKİNESİ TESTLERİ
# -----------------------------------------------------------------------------
def test_studio_video_honest_state(client, auth_headers):
    """Video üretimi gerçek indirilebilir MP4 ve DÜRÜST durum etiketi dönmelidir.

    2026-11-10: Hat iki modlu hale geldi ve ikisi de dürüstçe etiketlenir:
      * `yz_montaj_hazir`      → gerçek YZ sahneleri (FLUX difüzyon), simulasyon=False
      * `onizleme_hazir (simülasyon)` → YZ erişimi yoksa başlık kartı yedeği
    Test ikisini de kabul eder ama etiketin İÇERİKLE tutarlı olmasını şart koşar.
    """
    res = client.post("/api/studio/video/generate", json={
        "channel": "Tech_AI_Fabrika",
        "prompt": "Test sinematik render",
        "method": "remotion_cinema"
    }, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    task = data["task"]
    job_id = task["job_id"]
    mp4_path = MEDIA_DIR / f"{job_id}.mp4"
    try:
        status = str(task["status"])
        kaynak = str((task.get("artifacts") or {}).get("kaynak") or "")

        # Etiket içerikle tutarlı olmalı (Kural 1: sessiz sahte başarı yok)
        if "simülasyon" in status:
            assert task["simulasyon"] is True
            assert kaynak == "baslik_karti"
        else:
            assert status == "yz_montaj_hazir"
            assert task["simulasyon"] is False
            assert kaynak.startswith("yz_montaj") or kaynak == "flux_montaj"

        assert task["output_url"] == f"/api/media/file?path={job_id}.mp4"
        assert task["download_url"] == f"/api/media/file?path={job_id}.mp4&download=1"
        assert mp4_path.exists() and mp4_path.stat().st_size > 20000

        # İndirilen MP4 gerçekten oynatılabilir olmalı (moov atomu)
        from video_render import mp4_gecerli_mi

        assert mp4_gecerli_mi(mp4_path)[0] is True

        # İndirme bağlantısı (download=1) Content-Disposition: attachment dönmeli
        dl_res = client.get(task["download_url"], headers=auth_headers)
        assert dl_res.status_code == 200
        assert "attachment" in dl_res.headers.get("content-disposition", "")
        assert f"{job_id}.mp4" in dl_res.headers.get("content-disposition", "")
    finally:
        if mp4_path.exists():
            mp4_path.unlink()



def test_audio_honest_queue(client, auth_headers):
    """Ses üretimi gerçek indirilebilir WAV dosyası, geçmiş listesi ve Kural 1 etiketi dönmelidir."""
    res = client.post("/api/audio/process", json={
        "action": "generate_music",
        "params": {"prompt": "Roman ritmi", "duration_sec": 3}
    }, headers=auth_headers)
    assert res.status_code == 200
    d = res.json()["data"]
    job_id = d["job_id"]
    wav_path = MEDIA_DIR / f"{job_id}.wav"
    try:
        assert "simülasyon" in d["status"]
        assert d["simulasyon"] is True
        assert d["output_url"] == f"/api/media/file?path={job_id}.wav"
        assert d["download_url"] == f"/api/media/file?path={job_id}.wav&download=1"
        assert wav_path.exists() and wav_path.stat().st_size > 1000

        # Ses geçmişi listelenmeli
        hist_res = client.get("/api/audio/history", headers=auth_headers)
        assert hist_res.status_code == 200
        items = hist_res.json()["items"]
        assert any(it["job_id"] == job_id for it in items)

        # İndirme bağlantısı (download=1) Content-Disposition: attachment dönmeli
        dl_res = client.get(d["download_url"], headers=auth_headers)
        assert dl_res.status_code == 200
        assert "attachment" in dl_res.headers.get("content-disposition", "")
        assert f"{job_id}.wav" in dl_res.headers.get("content-disposition", "")
    finally:
        if wav_path.exists():
            wav_path.unlink()


def test_gpu_cluster_honest_standby(client, auth_headers):
    """GPU kümesi bağlı işçi yokken standby dönmelidir."""
    from main import ACTIVE_GPU_WORKERS
    ACTIVE_GPU_WORKERS.clear()
    res = client.get("/api/gpu/cluster/status", headers=auth_headers)
    assert res.status_code == 200
    st = res.json()["status"]
    assert st["colab_connected"] is False
    assert st["allocated_vram_gb"] == 0.0
    assert "standby" in st["cluster_status"]


def test_worker_protocol_and_gpu_activation(client, auth_headers):
    """Kaggle/Colab GPU işçisi bağlandığında telemetrinin active olduğunu, iş claim ve upload sürecini doğrular."""
    from main import ACTIVE_GPU_WORKERS
    ACTIVE_GPU_WORKERS.clear()
    worker_headers = {"X-Worker-Key": main.get_worker_key()}

    # 1. Başlangıçta standby
    st1 = client.get("/api/gpu/cluster/status", headers=auth_headers).json()["status"]
    assert st1["kaggle_connected"] is False

    # 2. worker.py erişimi
    w_res = client.get("/worker.py")
    assert w_res.status_code == 200
    assert "FABRİKA BULUT GPU İŞÇİSİ" in w_res.text

    # 3. Heartbeat gönder (X-Worker-Key zorunlu)
    hb = client.post("/api/worker/heartbeat", json={
        "worker_id": "test_kaggle_01",
        "worker_type": "kaggle",
        "gpu_name": "2x Tesla T4",
        "vram_gb": 32.0
    }, headers=worker_headers)
    assert hb.status_code == 200
    assert hb.json()["registered"] is True

    # 4. Telemetri aktif olmalı
    st2 = client.get("/api/gpu/cluster/status", headers=auth_headers).json()["status"]
    assert st2["kaggle_connected"] is True
    assert st2["allocated_vram_gb"] == 32.0
    assert "Kaggle Dual-T4" in st2["cluster_status"]

    # 5. İş oluştur ve claim et
    v_res = client.post("/api/studio/video/generate", json={
        "channel": "Tech_AI_Fabrika",
        "prompt": "Test GPU render",
        "render_target": "kaggle_32gb"
    }, headers=auth_headers)
    assert v_res.status_code == 200
    job_id = v_res.json()["task"]["job_id"]

    claim = client.get("/api/worker/claim?worker_id=test_kaggle_01",
                       headers=worker_headers).json()
    assert claim["success"] is True

    # 6. Upload — gerçek geçerli MP4 kutuları (ftyp+moov+mdat) zorunludur
    import video_render
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        mp4_yol = Path(td) / f"{job_id}.mp4"
        r = video_render.video_render_et(
            hedef_mp4=mp4_yol, baslik="GPU Test", prompt="Test",
            genislik=320, yukseklik=180, sure_sn=1.0,
        )
        assert r["basarili"] is True
        up = client.post(
            "/api/worker/upload",
            data={"job_id": job_id},
            files={"file": (f"{job_id}.mp4", mp4_yol.read_bytes(), "video/mp4")},
            headers=worker_headers,
        )
    assert up.status_code == 200
    assert up.json()["success"] is True
    assert up.json()["download_url"].endswith("&download=1")


def test_rea_scan_and_history_dynamic(client, auth_headers):
    """REA taraması yapılınca skor ve kayıt dinamik hesaplanmalıdır."""
    # 1. Başlangıçta tarama yoksa Veri Yok dönmeli
    res_init = client.get("/api/rea/history", headers=auth_headers)
    assert res_init.status_code == 200
    assert res_init.json()["toplam_tarama"] == 0
    assert res_init.json()["ort_skor"] is None

    # 2. Temiz kod tara
    res = client.post("/api/rea/scan", json={"code": "x = 10\ny = 20"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["score"] == 100

    # 3. eval içeren riskli kod tara
    res_bad = client.post("/api/rea/scan", json={"code": "eval('bad')"}, headers=auth_headers)
    assert res_bad.status_code == 200
    assert res_bad.json()["score"] < 100

    # 4. Geçmişi oku — dinamik 2 olmalı
    res_hist = client.get("/api/rea/history", headers=auth_headers)
    assert res_hist.status_code == 200
    h = res_hist.json()
    assert h["toplam_tarama"] == 2
    assert isinstance(h["ort_skor"], (int, float))


def test_gemini_audio_and_no_edge_tts(client, auth_headers):
    """Edge-TTS kullanımının tamamen yasaklandığını ve Google Gemini 2.5 ses motorunu doğrular."""
    import sys
    import gemini_audio

    # 1. Ses profilleri doğrula
    assert "Aoede" in gemini_audio.GEMINI_VOICES
    assert "Puck" in gemini_audio.GEMINI_VOICES
    assert "Charon" in gemini_audio.GEMINI_VOICES
    assert "Kore" in gemini_audio.GEMINI_VOICES
    assert "Fenrir" in gemini_audio.GEMINI_VOICES

    # 2. Kanal ses haritası
    assert gemini_audio.get_channel_gemini_voice("Astroloji_Kova") == "Aoede"
    assert gemini_audio.get_channel_gemini_voice("Tech_AI_Fabrika") == "Puck"
    assert gemini_audio.get_channel_gemini_voice("Belgesel_Sinematik") == "Charon"

    # 3. Video üretimi Gemini seslendirmen seçimiyle çağrılır
    res = client.post("/api/studio/video/generate", json={
        "channel": "Tech_AI_Fabrika",
        "prompt": "Yapay zeka transistör mimarisi",
        "voice": "Puck",
        "render_target": "kaggle_32gb"
    }, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "download_url" in data["task"]
    assert data["task"]["download_url"].endswith("&download=1")
    assert "rendered_mp4" in data["task"]["artifacts"]



# -----------------------------------------------------------------------------
# 5. VİDEO RENDER — "boş video / oynatılamıyor" regresyon kalkanı
#    (2026-11-10: 15 sn timeout + düz renk video kök nedeninin kilitleri)
# -----------------------------------------------------------------------------
def test_bozuk_mp4_reddedilir(tmp_path):
    """Yalnız `ftyp` başlığı olan 2 KB'lık kalıntı geçerli SAYILMAZ."""
    import video_render

    sahte = tmp_path / "yarim.mp4"
    sahte.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 2000)
    gecerli, neden = video_render.mp4_gecerli_mi(sahte)
    assert gecerli is False
    assert "moov" in neden or "küçük" in neden


def test_gecerli_mp4_kabul_edilir(tmp_path):
    """Gerçek render edilmiş MP4 doğrulamadan geçer (ftyp+moov+mdat)."""
    import video_render

    hedef = tmp_path / "gercek.mp4"
    sonuc = video_render.video_render_et(
        hedef_mp4=hedef,
        baslik="Test Kanalı",
        prompt="Bu bir regresyon testi videosudur",
        genislik=320,
        yukseklik=180,
        sure_sn=2.0,
    )
    assert sonuc["basarili"] is True, sonuc.get("hata")
    assert sonuc["boyut"] > 20 * 1024
    assert video_render.mp4_gecerli_mi(hedef)[0] is True


def test_render_metni_kareye_basar(tmp_path):
    """Başlık kartı gerçekten üretilir — video düz renk değil (boş video değil)."""
    import video_render

    kart = video_render.baslik_karti_uret(
        png_yolu=tmp_path / "kart.png",
        baslik="Astroloji Kova",
        prompt="Kova burcu haftalık analizi",
        genislik=320,
        yukseklik=180,
    )
    assert kart is not None and kart.is_file()
    assert kart.stat().st_size > 1000  # metin/şerit içeren PNG


def test_media_bozuk_mp4_422_doner(client, auth_headers, tmp_path, monkeypatch):
    """Bozuk MP4 indirilmeye çalışılırsa sessiz boş oynatıcı değil, dürüst 422."""
    import main as main_mod

    bozuk = main_mod.MEDIA_DIR / "BOZUK-TEST.mp4"
    bozuk.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 2000)
    try:
        res = client.get("/api/media/file?path=BOZUK-TEST.mp4", headers=auth_headers)
        assert res.status_code == 422
        assert "moov" in res.json()["detail"] or "bozuk" in res.json()["detail"]
    finally:
        bozuk.unlink(missing_ok=True)


def test_ai_video_montaj_fonksiyonlari_mevcut():
    """ai_video_montaj modülünün tüm iç fonksiyonları gerçekten tanımlı olmalı.

    2026-11-11: `tesis_durumu` eklenirken `_sahne_promptlari` tanımı yanlışlıkla
    silindi; modül import edildi ama canlıda `name '_sahne_promptlari' is not
    defined` ile yedeğe düştü. Bu test o hata sınıfını kilitler.
    """
    import ai_video_montaj as av

    for ad in ("_hf_token", "_sahne_promptlari", "_ffmpeg", "_sahne_video",
               "montaj_birlestir", "sahneleri_uret", "ai_video_uret", "tesis_durumu"):
        assert hasattr(av, ad), f"ai_video_montaj.{ad} tanımlı değil"
        assert callable(getattr(av, ad)), f"ai_video_montaj.{ad} çağrılabilir değil"

    # Sahne prompt'ları gerçekten üretilmeli (boş liste = sessiz bozulma)
    pl = av._sahne_promptlari("emerald alpine lake", 3)
    assert len(pl) == 3
    assert all("emerald alpine lake" in p for p in pl)


def test_ai_video_uret_hata_mesaji_teshis_icerir(tmp_path, monkeypatch):
    """YZ sahne üretilemezse hata mesajı EKSİK ADIMI söylemeli (belirsiz mesaj yok)."""
    import ai_video_montaj as av

    monkeypatch.setattr(av, "sahneleri_uret", lambda *a, **k: [])
    monkeypatch.setattr(av, "_hf_token", lambda: None)
    monkeypatch.setattr(av, "_cf_kimlik", lambda: (None, None))

    sonuc = av.ai_video_uret(
        hedef_mp4=tmp_path / "x.mp4",
        prompt="test",
        genislik=320,
        yukseklik=180,
        sahne_sayisi=1,
    )
    assert sonuc["basarili"] is False
    assert "CLOUDFLARE" in sonuc["hata"] or "HF_TOKEN" in sonuc["hata"]
    assert sonuc["tesis"]["cloudflare"] is False


def test_gpu_worker_gpu_yoksa_durust_reddeder():
    """GPU yoksa işçi sahte çıktı üretmez, açıkça reddeder (Kural 1)."""
    import gpu_worker as gw

    bilgi = gw.gpu_bilgisi()
    assert isinstance(bilgi, dict)
    assert "var" in bilgi and "ad" in bilgi and "vram_gb" in bilgi
    if not bilgi["var"]:
        assert bilgi["vram_gb"] == 0.0


def test_gpu_worker_cozunurluk_eslemesi():
    """En-boy oranı Wan/FLUX sınırlarına (16'nın katı) çevrilmeli.

    2026-11-11: 832x480 + 33 kare Kaggle T4'te OOM verdi (ölçüldü). Bu yüzden
    varsayılan 480p artık 480x320; 832x480 yalnız `--kalite 832p` ile.
    """
    import gpu_worker as gw

    for oran, beklenen in (
        ("16:9", (480, 320)),
        ("9:16", (320, 480)),
        ("16:9 ", (480, 320)),
    ):
        w, h = gw._cozunurluk(oran, "480p")
        assert (w, h) == beklenen, f"{oran} -> {(w, h)}"
        assert w % 16 == 0 and h % 16 == 0

    # Geniş 480p sınıfı açıkça istendiğinde eski değer
    assert gw._cozunurluk("16:9", "832p") == (832, 480)
    assert gw._cozunurluk("9:16", "720p") == (720, 1280)


def test_gpu_worker_prompt_yoksa_hata():
    """Prompt'suz iş üretilmez — sessiz boş video yok."""
    import gpu_worker as gw

    try:
        gw.gorev_isle({"prompt": "  ", "method": "remotion_cinema"}, {})
    except ValueError as e:
        assert "prompt" in str(e).lower()
    else:
        raise AssertionError("prompt'suz iş kabul edilmemeliydi")


def test_gpu_worker_i2v_gorsel_yoksa_hata():
    """wan_i2v görsel olmadan çalışmaz; dürüst hata verir."""
    import gpu_worker as gw

    try:
        gw.gorev_isle({"prompt": "test", "method": "wan_i2v"}, {})
    except ValueError as e:
        assert "image_path" in str(e) or "görsel" in str(e).lower()
    else:
        raise AssertionError("görselsiz wan_i2v kabul edilmemeliydi")


def test_gpu_worker_model_kimlikleri_dogrulanmis():
    """Model kimlikleri diffusers formatında (model_index.json) olmalı.

    2026-11-11: İlk sürüm `Wan-AI/Wan2.1-T2V-1.3B` kullanıyordu ama o depoda
    `model_index.json` YOK → diffusers pipeline yükleyemez. `-Diffusers` eki
    zorunlu (HF API ile ölçüldü). Bu test o regresyonu kilitler.
    """
    import gpu_worker as gw

    assert gw.FLUX2_KLEIN == "black-forest-labs/FLUX.2-klein-4B"
    assert gw.WAN21_T2V == "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
    assert gw.WAN21_I2V == "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers"

    # Wan depoları diffusers formatında olmak ZORUNDA
    assert gw.WAN21_T2V.endswith("-Diffusers")
    assert gw.WAN21_I2V.endswith("-Diffusers")


def test_worker_claim_gpu_kuyrugunu_oncelikler(client, monkeypatch, tmp_path):
    """`gpu_kuyruk=True` işler claim edilmeli (stüdyo işleri artık yz_montaj_hazir)."""
    import main as main_mod

    jobs_file = tmp_path / "video_jobs.json"
    jobs_file.write_text(json.dumps({"jobs": [{
        "job_id": "JOB-GPU-1",
        "prompt": "gerçek difüzyon testi",
        "method": "remotion_cinema",
        "status": "yz_montaj_hazir",
        "gpu_kuyruk": True,
        "gpu_durum": "bekliyor",
    }]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    w_headers = {"X-Worker-Key": main_mod.get_worker_key()}

    res = client.get("/api/worker/claim?worker_id=test_worker", headers=w_headers)
    assert res.status_code == 200
    veri = res.json()
    assert veri["job"] is not None
    assert veri["job"]["job_id"] == "JOB-GPU-1"
    assert veri["mod"] == "gpu_kuyruk"
    assert veri["job"]["gpu_durum"] == "isleniyor"

    # İkinci çağrıda aynı iş tekrar verilmemeli
    res2 = client.get("/api/worker/claim?worker_id=test_worker2", headers=w_headers)
    assert res2.json()["job"] is None


def test_gpu_hedefleri_kuyruk_isaretler(client, auth_headers, monkeypatch):
    """GPU render hedefi seçilirse iş kaydı gpu_kuyruk=True almalı."""
    import main as main_mod

    assert "kaggle_32gb" in main_mod.GPU_HEDEFLERI
    assert "google_colab" in main_mod.GPU_HEDEFLERI

    res = client.post("/api/studio/video/generate", json={
        "channel": "Tech_AI_Fabrika",
        "prompt": "GPU kuyruk testi",
        "method": "remotion_cinema",
        "render_target": "kaggle_32gb",
    }, headers=auth_headers)
    assert res.status_code == 200
    assert main_mod.GPU_HEDEFLERI  # sabit yerinde

    # Kayıt dosyasında gpu_kuyruk işareti aranır
    jobs_file = main_mod.DATA_DIR / "video_jobs.json"
    if jobs_file.exists():
        data = json.loads(jobs_file.read_text(encoding="utf-8"))
        son = data["jobs"][-1]
        assert son.get("gpu_kuyruk") is True
        assert son.get("gpu_durum") == "bekliyor"


def test_galeri_bozuk_mp4_listelemez(client, auth_headers):
    """Galeri yalnız oynatılabilir MP4'leri döner."""
    res = client.get("/api/lab/history", headers=auth_headers)
    assert res.status_code == 200
    for item in res.json()["items"]:
        assert item.get("video_url")


def test_worker_endpoints_require_worker_key(client):
    """X-Worker-Key olmadan hiçbir /api/worker/* ucu kabul edilmez (403)."""
    assert client.post("/api/worker/heartbeat", json={"worker_id": "x"}).status_code == 403
    assert client.get("/api/worker/claim?worker_id=x").status_code == 403
    assert client.post("/api/worker/progress", json={"job_id": "J1", "progress_pct": 50}).status_code == 403
    assert client.post("/api/worker/upload", data={"job_id": "J1"}).status_code == 403
    assert client.get("/api/worker/input/J1").status_code == 403
    assert client.get("/api/worker/audio/J1").status_code == 403
    assert client.get("/api/worker/subtitle/J1").status_code == 403


def test_worker_upload_rejects_path_traversal_and_invalid_mp4(client, auth_headers):
    """Dizin atlama job_id reddedilir; sahte/yarım MP4 422 alır."""
    import main as main_mod
    wh = {"X-Worker-Key": main_mod.get_worker_key()}

    bad_id = client.post(
        "/api/worker/upload",
        data={"job_id": "../evil"},
        files={"file": ("evil.mp4", b"\x00\x00\x00\x20ftypisom" + b"\x00" * 500, "video/mp4")},
        headers=wh,
    )
    assert bad_id.status_code in (400, 422)

    bad_mp4 = client.post(
        "/api/worker/upload",
        data={"job_id": "JOB-BAD-1"},
        files={"file": ("bad.mp4", b"NOT_AN_MP4", "video/mp4")},
        headers=wh,
    )
    assert bad_mp4.status_code == 422


def test_worker_preview_image_upload_then_i2v_flow(client, auth_headers):
    """FLUX.2 önizleme PNG yüklenir, /api/lab/job/{id} döner ve ardından Wan2.1 I2V kuyruğa girer."""
    import main as main_mod
    wh = {"X-Worker-Key": main_mod.get_worker_key()}

    # 1) FLUX.2 önizleme işi kuyruğa al
    q1 = client.post("/api/lab/generate", json={
        "model_id": "flux2",
        "mode": "flux2_resim",
        "method": "flux2_resim",
        "render_target": "kaggle_32gb",
        "prompt": "cosmos pouring water bucket",
    }, headers=auth_headers)
    assert q1.status_code == 200
    j1 = q1.json()["job"]["job_id"]

    c1 = client.get("/api/worker/claim?worker_id=w1", headers=wh)
    assert c1.status_code == 200
    assert c1.json()["job"]["job_id"] == j1

    # 2) İşçi PNG önizleme yüklesin (media_type=image)
    png_1x1 = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00"
        b"\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    up_png = client.post(
        "/api/worker/upload",
        data={"job_id": j1, "media_type": "image"},
        files={"file": (f"{j1}.png", png_1x1, "image/png")},
        headers=wh,
    )
    assert up_png.status_code == 200
    preview_url = up_png.json()["preview_image_url"]
    assert "path=" in preview_url

    polled = client.get(f"/api/lab/job/{j1}", headers=auth_headers).json()
    assert polled["job"]["status"] == "onizleme_hazir"
    assert polled["job"]["preview_image_url"] == preview_url

    # 3) Beğenilen görseli Wan2.1 I2V'ye gönder
    q2 = client.post("/api/lab/generate", json={
        "model_id": "wan2.1_i2v",
        "mode": "video",
        "method": "wan_i2v",
        "render_target": "kaggle_32gb",
        "prompt": "flowing cosmic water motion",
        "input_image_url": preview_url,
    }, headers=auth_headers)
    assert q2.status_code == 200
    j2 = q2.json()["job"]["job_id"]
    assert q2.json()["job"]["gpu_kuyruk"] is True

    c2 = client.get("/api/worker/claim?worker_id=w1", headers=wh).json()
    assert c2["job"]["job_id"] == j2
    assert c2["job"]["input_image_url"] == f"/api/worker/input/{j2}"

    img_dl = client.get(c2["job"]["input_image_url"], headers=wh)
    assert img_dl.status_code == 200
    assert img_dl.content.startswith(b"\x89PNG")


def test_burc_list_and_burc_video_generate_flow(client, auth_headers, monkeypatch):
    """12 burç kataloğu ve burç videosu + SRT/ASS altyazı GPU kuyruğu çalışır."""
    import main as main_mod
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    wh = {"X-Worker-Key": main_mod.get_worker_key()}

    lst = client.get("/api/burc/list")
    assert lst.status_code == 200
    assert lst.json()["count"] == 12
    assert any(b["kod"] == "kova" for b in lst.json()["items"])
    beklenen_simgeler = {
        "koc": "♈", "boga": "♉", "ikizler": "♊", "yengec": "♋",
        "aslan": "♌", "basak": "♍", "terazi": "♎", "akrep": "♏",
        "yay": "♐", "oglak": "♑", "kova": "♒", "balik": "♓",
    }
    gercek_simgeler = {b["kod"]: b.get("simge") for b in lst.json()["items"]}
    assert gercek_simgeler == beklenen_simgeler

    gen = client.post("/api/burc/video/generate", json={
        "burc_kodu": "kova",
        "konu": "Kariyer ve dönüşüm",
        "sure_sn": 10,
        "method": "burc_video",
        "render_target": "kaggle_32gb",
    }, headers=auth_headers)
    assert gen.status_code == 200
    body = gen.json()
    assert body["success"] is True
    assert body["burc"]["simge"] == "♒"
    assert body["task"]["burc_simge"] == "♒"
    assert body["task"]["gpu_kuyruk"] is True
    assert body["task"]["mode"] == "burc_video"
    assert body["task"]["metin_simulasyon"] is True

    claim = client.get("/api/worker/claim?worker_id=w_burc", headers=wh).json()
    assert claim["job"]["job_id"] == body["job_id"]
    sub_url = claim["job"]["subtitle_url"]
    assert sub_url

    sub_dl = client.get(sub_url, headers=wh)
    assert sub_dl.status_code == 200
    assert len(sub_dl.text.strip()) > 0


def test_static_worker_is_not_fake_drawbox_stub(client):
    """static/worker.py sahte drawbox stub içermez; /worker.py gerçek gpu_worker'ı sunar."""
    static_txt = (Path(__file__).resolve().parent.parent / "static" / "worker.py").read_text(encoding="utf-8")
    assert "drawbox=" not in static_txt
    assert "color=c=" not in static_txt
    assert "gpu_worker" in static_txt

    srv = client.get("/worker.py")
    assert srv.status_code == 200
    assert "FABRİKA BULUT GPU İŞÇİSİ" in srv.text
    assert "wan21_i2v_uret" in srv.text


def test_studio_catalog_and_channels_crud(client, auth_headers, monkeypatch, tmp_path):
    """Katalog gerçek doğrulanmış modelleri listeler; kanal ekleme/silme kalıcıdır."""
    import main as main_mod
    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)

    cat = client.get("/api/studio/catalog", headers=auth_headers)
    assert cat.status_code == 200
    body = cat.json()
    assert body["success"] is True
    img_ids = {m["id"] for m in body["image_models"]}
    i2v_ids = {m["id"] for m in body["i2v_models"]}
    style_ids = {s["id"] for s in body["styles"]}
    wf_ids = {w["id"] for w in body["workflows"]}
    assert {"flux2-klein", "z-image-turbo", "sdxl-turbo", "realvis-xl", "animagine-xl"} <= img_ids
    assert {"wan2.1-i2v-14b", "wan2.2-ti2v-5b", "ltx-video", "cogvideox-5b-i2v", "svd-xt"} <= i2v_ids
    assert {"cinematic_realism", "pixar_3d_animation", "anime_2d", "astrology_mystic"} <= style_ids
    assert {"image_first_preview", "image_then_i2v", "wan_i2v"} <= wf_ids

    created = client.post("/api/channels", json={
        "name": "Masal 3D Atölye",
        "handle": "@masal3d",
        "style_preset": "pixar_3d_animation",
        "image_model": "z-image-turbo",
        "i2v_model": "cogvideox-5b-i2v",
        "workflow": "image_first_preview",
        "aspect_ratio": "16:9",
        "voice": "Puck",
        "tags": "3d, animasyon, hikaye",
    }, headers=auth_headers)
    assert created.status_code == 200
    cid = created.json()["channel"]["id"]

    listed = client.get("/api/channels", headers=auth_headers).json()
    assert any(c["id"] == cid and c["style_preset"] == "pixar_3d_animation" for c in listed["channels"])

    deleted = client.delete(f"/api/channels/{cid}", headers=auth_headers)
    assert deleted.status_code == 200
    assert not any(c["id"] == cid for c in client.get("/api/channels", headers=auth_headers).json()["channels"])


def test_studio_image_first_then_i2v_and_youtube_bundle(client, auth_headers, monkeypatch, tmp_path):
    """Önce Görsel -> Onay -> I2V ve 2 aşamalı I2V + dürüst YouTube OAuth durumu doğrulanır."""
    import shutil
    import subprocess
    import main as main_mod

    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    wh = {"X-Worker-Key": main_mod.get_worker_key()}

    try:
        # 1) Kanal varsayılanlarıyla image_first_preview işi
        q1 = client.post("/api/studio/video/generate", json={
            "channel": "Animasyon_3D",
            "workflow": "image_first_preview",
            "prompt": "Kütüphanede kitap okuyan minik robot",
            "render_target": "kaggle_32gb",
        }, headers=auth_headers)
        assert q1.status_code == 200
        t1 = q1.json()["task"]
        assert t1["method"] == "flux2_resim"
        assert t1["image_model"] == "z-image-turbo"
        assert t1["style_preset"] == "pixar_3d_animation"
        assert "3D CGI" in t1["image_prompt"]

        # Worker Stage 1 PNG önizleme yüklesin
        c1 = client.get("/api/worker/claim?worker_id=w_anim", headers=wh).json()
        assert c1["job"]["image_model"] == "z-image-turbo"
        png_1x1 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00"
            b"\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        up_png = client.post(
            "/api/worker/upload",
            data={"job_id": t1["job_id"], "media_type": "image"},
            files={"file": (f"{t1['job_id']}.png", png_1x1, "image/png")},
            headers=wh,
        )
        assert up_png.status_code == 200
        preview_url = up_png.json()["preview_image_url"]

        # 2) Onaylı görseli özel I2V modeliyle (ltx-video) canlandır + dürüst YouTube paketi
        q2 = client.post("/api/studio/video/generate", json={
            "channel": "Animasyon_3D",
            "workflow": "image_then_i2v",
            "i2v_model": "ltx-video",
            "prompt": "Kütüphanede kitap okuyan minik robot",
            "input_image_url": preview_url,
        }, headers=auth_headers)
        assert q2.status_code == 200
        t2 = q2.json()["task"]
        assert t2["method"] == "wan_i2v"
        assert t2["i2v_model"] == "ltx-video"

        c2 = client.get("/api/worker/claim?worker_id=w_anim", headers=wh).json()
        assert c2["job"]["i2v_model"] == "ltx-video"
        assert c2["job"]["input_image_url"] == f"/api/worker/input/{t2['job_id']}"

        if shutil.which("ffmpeg"):
            mp4_p = tmp_path / "tiny_valid.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                 "-i", "testsrc2=size=640x480:rate=24:duration=2",
                 "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4_p)],
                check=True,
            )
            up_vid = client.post(
                "/api/worker/upload",
                data={"job_id": t2["job_id"], "media_type": "video"},
                files={"file": (f"{t2['job_id']}.mp4", mp4_p.read_bytes(), "video/mp4")},
                headers=wh,
            )
            assert up_vid.status_code == 200

            pub = client.post(f"/api/youtube/publish/{t2['job_id']}", headers=auth_headers)
            assert pub.status_code == 200
            pj = pub.json()
            assert pj["success"] is False
            assert pj["simulasyon"] is True
            assert pj["status"] == "oauth_gerekli"
            assert pj["bundle"]["title"]
            assert "3danimasyon" in pj["bundle"]["tags"]
    finally:
        for tid in (locals().get("t1", {}).get("job_id"), locals().get("t2", {}).get("job_id")):
            if tid:
                for p in main_mod.MEDIA_DIR.glob(f"{tid}*"):
                    p.unlink(missing_ok=True)


def test_gpu_worker_image_then_i2v_dispatch(tmp_path, monkeypatch):
    """gpu_worker image_first_preview ve image_then_i2v modları seçili modelleri çağırır."""
    import gpu_worker as gw

    kayitlar = []
    fake_png = tmp_path / "keyframe.png"
    fake_png.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    fake_mp4 = tmp_path / "anim.mp4"
    fake_mp4.write_bytes(b"FAKE_MP4")

    def fake_img(prompt, model_key, w, h, neg_prompt="", adim=None, tohum=42, log=print):
        kayitlar.append(("img", model_key, w, h))
        p = tmp_path / f"img_{len(kayitlar)}.png"
        p.write_bytes(fake_png.read_bytes())
        return p

    def fake_vid(gorsel_yolu, prompt, model_key, w, h, neg_prompt="", sure_sn=4.0, adim=24, tohum=42, log=print):
        assert gorsel_yolu.is_file()
        kayitlar.append(("i2v", model_key, gorsel_yolu.name))
        return fake_mp4

    monkeypatch.setattr(gw, "secimli_gorsel_uret", fake_img)
    monkeypatch.setattr(gw, "secimli_i2v_uret", fake_vid)

    out1 = gw.gorev_isle({
        "prompt": "anime kılıç ustası",
        "workflow": "image_first_preview",
        "image_model": "animagine-xl",
        "aspect_ratio": "9:16",
    }, {"kalite": "480p"})
    assert out1.is_file()
    assert kayitlar[0] == ("img", "animagine-xl", 320, 480)

    out2 = gw.gorev_isle({
        "prompt": "3D robot kütüphanesi",
        "method": "image_then_i2v",
        "image_model": "z-image-turbo",
        "i2v_model": "cogvideox-5b-i2v",
        "aspect_ratio": "16:9",
    }, {"kalite": "480p"})
    assert out2 == fake_mp4
    assert kayitlar[1][:2] == ("img", "z-image-turbo")
    assert kayitlar[2][:2] == ("i2v", "cogvideox-5b-i2v")


def test_cloudflare_llm_dict_response_and_render_budget(monkeypatch, tmp_path):
    """Cloudflare dict result.response AttributeError vermez ve RENDER modunda 2 sahneli 480p üretir."""
    import json as _json
    import ai_video_montaj as avm
    import hyperframes_motor as hf
    import prompt_director as pd

    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf_tok")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "cf_acc")
    for k in list(os.environ):
        if "GEMINI_API_KEY" in k.upper():
            monkeypatch.delenv(k, raising=False)

    class FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return _json.dumps({
                "success": True,
                "result": {
                    "response": {
                        "narration_text": "Kova burcu kozmik sularla akıyor",
                        "motion_prompt": "smooth cosmic orbit",
                        "scenes": [
                            {"image_prompt": "Aquarius pouring cosmic water above Earth"},
                            {"image_prompt": "Golden constellations over starry clouds"},
                        ],
                    }
                },
            }).encode("utf-8")

    monkeypatch.setattr(pd.urllib.request, "urlopen", lambda req, timeout=10: FakeResp())
    plan = pd.plan_visual_scenes("kova burcu su boşaltıyor", style_preset="astrology_mystic", scene_count=2, use_llm=True)
    assert plan["planner_source"].startswith("cloudflare:")
    assert "aquarius" in plan["image_prompt"].lower()

    monkeypatch.setenv("RENDER", "true")
    seen = []

    def fake_prev(prompt, hedef_png, genislik=1280, yukseklik=720, **kw):
        seen.append((genislik, yukseklik, kw.get("use_planner")))
        hf._kinetic_card_png(hedef_png, "Render 480p", prompt[:60], genislik, yukseklik)
        return {"ok": True, "provider": "test_mock"}

    monkeypatch.setattr(avm, "preview_single_image", fake_prev)
    res = hf.hyperframes_studio_render(
        tmp_path / "out.mp4",
        tmp_path / "out.html",
        prompt="Kova testi",
        image_prompts=["Aquarius water bearer", "Cosmic nebula", "Glowing stars"],
        aspect_ratio="16:9",
        duration_sec=5.0,
    )
    assert res["ok"] is True
    assert res["resolution"] == "854x480"
    assert len(seen) == 2
    assert all(item == (854, 480, False) for item in seen)


def test_prompt_director_grounds_turkish_astroloji_to_english_visuals(monkeypatch):
    """Türkçe soyut istem (ör. Kova burcu analizi) ham halde difüzyona gitmez, İngilizce sahneye çevrilir."""
    import prompt_director as pd
    import ai_video_montaj as avm

    for key in list(os.environ):
        if "GEMINI_API_KEY" in key.upper():
            monkeypatch.delenv(key, raising=False)

    tr_prompt = "♒ Kova Burcu Haftalık Analizi: Gezegen kavuşumları ve sezgisel uyanış dönemi"
    plan = pd.plan_visual_scenes(
        prompt=tr_prompt,
        style_preset="astrology_mystic",
        camera_motion="orbital",
        scene_count=3,
        use_llm=False,
    )
    img_low = plan["image_prompt"].lower()
    assert "aquarius" in img_low
    assert "planet" in img_low or "conjunction" in img_low
    assert "♒" not in img_low
    assert "analizi" not in img_low
    assert "sezgisel" not in img_low

    sahneler = avm._sahne_promptlari(tr_prompt, 3, style_preset="astrology_mystic")
    assert len(sahneler) == 3
    assert all("aquarius" in s.lower() for s in sahneler)


def test_studio_storyboard_preview_stitch_and_oauth(client, auth_headers, monkeypatch, tmp_path):
    """Storyboard, anında önizleme görseli, çoklu klip birleştirme ve OAuth akışı çalışır."""
    import json as _json
    import shutil
    import subprocess
    import ai_video_montaj as avm
    import main as main_mod

    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    created_ids = []
    try:
        sb = client.post("/api/studio/storyboard", json={
            "prompt": "İstanbul Yerebatan Sarnıcı ve mermer sütunlarda meşale ışığı",
            "style_preset": "history_documentary",
            "scene_count": 3,
            "duration": 15,
        }, headers=auth_headers)
        assert sb.status_code == 200
        sb_data = sb.json()
        assert len(sb_data["scenes"]) == 3
        assert any("cistern" in s["image_prompt"].lower() or "istanbul" in s["image_prompt"].lower() for s in sb_data["scenes"])

        png_1x1 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00"
            b"\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        def fake_prev(prompt, hedef, genislik=1280, yukseklik=720, style_preset="cinematic_realism", camera_motion="otomatik"):
            Path(hedef).write_bytes(png_1x1)
            return {
                "ok": True,
                "path": Path(hedef),
                "provider": "cloudflare-flux1-schnell",
                "image_prompt": "Istanbul Basilica Cistern marble columns",
                "motion_prompt": "slow torchlit dolly push",
                "narration_text": prompt,
                "planner_source": "test_mock",
            }

        monkeypatch.setattr(avm, "preview_single_image", fake_prev)
        pv = client.post("/api/studio/preview-image", json={
            "channel": "Belgesel_Sinematik",
            "prompt": "İstanbul Yerebatan Sarnıcı meşale ışıkları",
        }, headers=auth_headers)
        assert pv.status_code == 200
        pv_j = pv.json()
        assert pv_j["success"] is True
        assert pv_j["provider"] == "cloudflare-flux1-schnell"
        created_ids.append(pv_j["job_id"])

        # OAuth client_secret + start link testi
        sec_res = client.post("/api/youtube/oauth-secret", json={
            "client_secret_json": _json.dumps({
                "web": {"client_id": "test-cid.apps.googleusercontent.com", "client_secret": "test-sec"}
            })
        }, headers=auth_headers)
        assert sec_res.status_code == 200
        oa = client.get("/api/youtube/oauth/start?channel_id=Belgesel_Sinematik", headers=auth_headers)
        assert oa.status_code == 200
        assert "accounts.google.com/o/oauth2/auth" in oa.json()["auth_url"]
        assert "test-cid.apps.googleusercontent.com" in oa.json()["auth_url"]

        if shutil.which("ffmpeg"):
            cids = ["ST1_clip", "ST2_clip"]
            created_ids.extend(cids)
            main_mod.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            for cid in cids:
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                     "-i", "testsrc2=size=640x480:rate=24:duration=1",
                     "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                     str(main_mod.MEDIA_DIR / f"{cid}.mp4")],
                    check=True,
                )
            st = client.post("/api/studio/stitch-clips", json={
                "job_ids": cids,
                "channel": "Belgesel_Sinematik",
                "prompt": "Çok sahneli belgesel birleşimi",
                "voice": "none",
            }, headers=auth_headers)
            assert st.status_code == 200
            sj = st.json()["job"]
            created_ids.append(sj["job_id"])
            assert sj["output_url"].startswith("/api/media/file?path=")
            assert (main_mod.MEDIA_DIR / f"{sj['job_id']}.mp4").stat().st_size > 20000
    finally:
        for cid in created_ids:
            for p in main_mod.MEDIA_DIR.glob(f"{cid}*"):
                p.unlink(missing_ok=True)


def test_gpu_worker_medya_birlestir_preserves_audio_duration(tmp_path):
    """Ses video klipten uzunsa video pürüzsüz uzatılır, ses yarıda kesilmez."""
    import shutil
    import subprocess
    import gpu_worker as gw

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        return

    vid = tmp_path / "short.mp4"
    aud = tmp_path / "long.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=12:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vid)],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         str(aud)],
        check=True,
    )
    out = gw._medya_birlestir(vid, aud, None)
    try:
        dur = gw._medya_suresi(out)
        assert dur is not None and dur >= 2.6, f"Ses kesildi: {dur}"
    finally:
        out.unlink(missing_ok=True)


def test_session_hmac_survives_active_session_wipe():
    """ACTIVE_SESSIONS temizlense bile (yeniden başlatma) tok ve tok_pin HMAC token çalışır."""
    import main as main_mod

    for prefix in ("tok", "tok_pin"):
        tok = main_mod.create_session("Yusuf Şahin", prefix=prefix)
        assert "." not in tok.rsplit("_", 2)[1]
        main_mod.ACTIVE_SESSIONS.pop(tok, None)
        assert main_mod.is_session_valid(tok) is True


def test_xfade_gecis_secimi_ardisik_tekrar_etmez(tmp_path):
    """Link #296 (saas-motion-kit): ardışık sahne geçişleri asla aynı efekti tekrarlamaz."""
    import shutil
    import subprocess
    import ai_video_montaj as avm

    assert avm.sec_xfade_gecisleri(0) == []
    gecisler = avm.sec_xfade_gecisleri(8)
    assert len(gecisler) == 8
    for i in range(1, len(gecisler)):
        assert gecisler[i] != gecisler[i - 1]
    assert len(set(gecisler)) >= 4

    if shutil.which("ffmpeg"):
        klipler = []
        for idx in range(3):
            p = tmp_path / f"s{idx}.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                 "-i", "testsrc2=size=320x180:rate=30:duration=2",
                 "-c:v", "libx264", "-crf", "22", "-pix_fmt", "yuv420p", str(p)],
                check=True,
            )
            klipler.append(p)
        hedef = tmp_path / "birlesik.mp4"
        assert avm.montaj_birlestir(klipler, hedef, gecis_sn=0.4, sure_sn=2.0) is True
        assert hedef.stat().st_size > 20 * 1024


def test_video_kalite_denetle_siyah_ve_saglikli_video(tmp_path):
    """Link #296 (brag + ffmpeg-skill): siyah/boş kare uyarısı ve akış telemetrisi."""
    import shutil
    import subprocess
    import video_render as vr

    if not shutil.which("ffmpeg"):
        return

    siyah_mp4 = tmp_path / "siyah.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=black:s=640x360:r=24:d=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(siyah_mp4)],
        check=True,
    )
    assert siyah_mp4.stat().st_size > vr.MIN_GECERLI_BAYT
    rapor_siyah = vr.video_kalite_denetle(siyah_mp4, beklenen_oran="16:9")
    assert rapor_siyah["gecerli"] is True
    assert rapor_siyah["ilk_kare_siyah"] is True
    assert rapor_siyah["bos_video"] is True
    assert rapor_siyah["uygun"] is False

    canli_mp4 = tmp_path / "canli.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=size=640x360:rate=24:d=2",
         "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(canli_mp4)],
        check=True,
    )
    rapor_canli = vr.video_kalite_denetle(canli_mp4, beklenen_oran="16:9")
    assert rapor_canli["gecerli"] is True
    assert rapor_canli["uygun"] is True
    assert rapor_canli["bos_video"] is False
    assert rapor_canli["genislik"] == 640
    assert rapor_canli["yukseklik"] == 360
    assert rapor_canli["platform_uyumu"] == "youtube_yatay"


def test_hyperframes_motor_instant_i2v_and_metrics(tmp_path):
    """Link #296: instant_i2v_motion, verify_onscreen_metrics ve rea_video şema çıkarma."""
    import shutil
    import hyperframes_motor as hf

    m_ok = hf.verify_onscreen_metrics("Yeni motor %40 daha hızlı ve 3 kat verimli", "Kaynak: %40 hız, 3x artış")
    assert m_ok["checked"] is True
    assert len(m_ok["unverified_numbers"]) == 0

    m_warn = hf.verify_onscreen_metrics("Garantili %95 kazanç", "Kısa ürün açıklaması")
    assert m_warn["clean"] is False
    assert any("95" in x for x in m_warn["unverified_numbers"])

    png = hf._kinetic_card_png(tmp_path / "card.png", "Kova Kozmik Sahne", "Astral Su Taşıyıcı", 640, 360)
    assert png.is_file()
    if not shutil.which("ffmpeg"):
        return

    mp4 = tmp_path / "orbit.mp4"
    res = hf.instant_i2v_motion(png, mp4, prompt="slow orbit", camera_motion="orbital", aspect_ratio="16:9", duration_sec=3.0)
    assert res["ok"] is True
    assert res["simulasyon"] is True
    assert res["video_difuzyonu"] is False
    assert mp4.stat().st_size > 20 * 1024
    bp = hf.rea_video_reverse_blueprint(mp4)
    assert bp["ok"] is True
    assert bp["estimated_scenes"] >= 1


def test_instant_cloud_wan_i2v_and_aquarius_grounding(client, auth_headers, monkeypatch):
    """Kova su boşaltan adam grounding'i + instant_cloud wan_i2v MP4 + HyperFrames + rea-video."""
    import ai_video_montaj as avm
    import hyperframes_motor as hf
    import main as main_mod
    from prompt_director import plan_visual_scenes

    plan = plan_visual_scenes(
        "kova burcu ile alakalı bir adam elinde gökyüzünden yeryüzüne kovadan su boşaltıyor",
        style_preset="astrology_mystic",
        use_llm=False,
    )
    img_en = plan["image_prompt"].lower()
    assert "aquarius" in img_en
    assert ("man" in img_en or "person" in img_en)
    assert ("water" in img_en or "pouring" in img_en)
    assert "earth" in img_en or "sky" in img_en

    def fast_prev(prompt, hedef_yol, genislik=1280, yukseklik=720, **kw):
        hf._kinetic_card_png(hedef_yol, "Aquarius Frame", prompt[:80], 640, 360)
        return {"ok": True, "provider": "test_mock", "image_prompt": prompt, "motion_prompt": "orbital", "narration_text": "test", "planner_source": "test"}

    monkeypatch.setattr(avm, "preview_single_image", fast_prev)
    created_ids = []
    try:
        r1 = client.post("/api/studio/video/generate", json={
            "channel": "Astroloji_Kova",
            "workflow": "image_first_preview",
            "execution_mode": "instant_cloud",
            "style_preset": "astrology_mystic",
            "aspect_ratio": "16:9",
            "voice": "none",
            "prompt": "kova burcu gökyüzünden su boşaltıyor",
        }, headers=auth_headers)
        assert r1.status_code == 200
        t1 = r1.json()["task"]
        created_ids.append(t1["job_id"])
        assert t1["status"] == "onizleme_hazir"
        assert t1["preview_image_url"]

        r2 = client.post("/api/studio/video/generate", json={
            "channel": "Astroloji_Kova",
            "workflow": "wan_i2v",
            "execution_mode": "instant_cloud",
            "style_preset": "astrology_mystic",
            "aspect_ratio": "16:9",
            "duration": 3,
            "voice": "none",
            "input_image_url": t1["preview_image_url"],
            "prompt": "kova burcu gökyüzünden su boşaltıyor",
        }, headers=auth_headers)
        assert r2.status_code == 200
        t2 = r2.json()["task"]
        created_ids.append(t2["job_id"])
        assert t2["gpu_kuyruk"] is False
        assert t2["simulasyon"] is True
        assert t2["video_difuzyonu"] is False
        assert t2["output_url"].startswith("/api/media/file?path=")
        assert t2["hyperframes_url"] == f"/api/studio/hyperframes/{t2['job_id']}"

        hf_resp = client.get(t2["hyperframes_url"], headers=auth_headers)
        assert hf_resp.status_code == 200
        assert "HyperFrames" in hf_resp.text
        assert "content-security-policy" in hf_resp.headers

        an = client.post("/api/studio/analyze-video", json={"job_id": t2["job_id"]}, headers=auth_headers)
        assert an.status_code == 200
        assert an.json()["success"] is True
    finally:
        for jid in created_ids:
            for p in main_mod.MEDIA_DIR.glob(f"{jid}*"):
                p.unlink(missing_ok=True)


def test_product_launch_ssrf_rejected_and_queue_instant_render(client, auth_headers, monkeypatch):
    """SSRF URL engellenir ve kuyruktaki iş /api/studio/queue/{id}/instant-render ile anında MP4 olur."""
    import ai_video_montaj as avm
    import hyperframes_motor as hf
    import main as main_mod

    bad = client.post("/api/studio/video/generate", json={
        "channel": "Tech_AI_Fabrika",
        "workflow": "product_launch",
        "source_url": "http://127.0.0.1:8080/internal",
        "prompt": "Lansman testi",
        "voice": "none",
    }, headers=auth_headers)
    assert bad.status_code == 400

    def fast_prev(prompt, hedef_yol, genislik=1280, yukseklik=720, **kw):
        hf._kinetic_card_png(hedef_yol, "Queue Render", prompt[:80], 640, 360)
        return {"ok": True, "provider": "test_mock"}

    monkeypatch.setattr(avm, "preview_single_image", fast_prev)
    created_ids = []
    try:
        q = client.post("/api/studio/video/generate", json={
            "channel": "Tech_AI_Fabrika",
            "workflow": "image_then_i2v",
            "execution_mode": "gpu_queue",
            "aspect_ratio": "16:9",
            "duration": 3,
            "voice": "none",
            "prompt": "Kuyruk dönüşüm testi",
        }, headers=auth_headers)
        assert q.status_code == 200
        qt = q.json()["task"]
        created_ids.append(qt["job_id"])
        assert qt["gpu_kuyruk"] is True
        assert qt["gpu_durum"] == "bekliyor"

        ql = client.get("/api/studio/queue?status=bekliyor", headers=auth_headers)
        assert ql.status_code == 200
        assert any(it["job_id"] == qt["job_id"] for it in ql.json()["items"])

        conv = client.post(f"/api/studio/queue/{qt['job_id']}/instant-render", headers=auth_headers)
        assert conv.status_code == 200
        ct = conv.json()["task"]
        assert ct["gpu_kuyruk"] is False
        assert ct["output_url"].startswith("/api/media/file?path=")
    finally:
        for jid in created_ids:
            for p in main_mod.MEDIA_DIR.glob(f"{jid}*"):
                p.unlink(missing_ok=True)


def test_auto_execution_mode_and_cache_version_consistency(client, auth_headers, monkeypatch):
    """execution_mode='auto' işçisiz bulutta anında render eder, işçi bağlıyken GPU kuyruğuna yönlendirir."""
    import ai_video_montaj as avm
    import hyperframes_motor as hf
    import main as main_mod

    def fast_prev(prompt, hedef_yol, genislik=1280, yukseklik=720, **kw):
        hf._kinetic_card_png(hedef_yol, "Auto Mode Frame", prompt[:60], 640, 360)
        return {"ok": True, "provider": "test_mock"}

    monkeypatch.setattr(avm, "preview_single_image", fast_prev)
    created_ids = []
    try:
        main_mod.ACTIVE_GPU_WORKERS.clear()

        auto_studio = client.post("/api/studio/video/generate", json={
            "channel": "Astroloji_Kova",
            "workflow": "image_then_i2v",
            "execution_mode": "auto",
            "aspect_ratio": "16:9",
            "duration": 3,
            "voice": "none",
            "prompt": "Kova burcu kozmik sahne",
        }, headers=auth_headers)
        assert auto_studio.status_code == 200
        st_task = auto_studio.json()["task"]
        created_ids.append(st_task["job_id"])
        assert st_task["gpu_kuyruk"] is False
        assert st_task["output_url"].startswith("/api/media/file?path=")

        auto_burc = client.post("/api/burc/video/generate", json={
            "burc_kodu": "kova",
            "konu": "Kariyer ve dönüşüm",
            "sure_sn": 3,
            "method": "image_then_i2v",
            "execution_mode": "auto",
        }, headers=auth_headers)
        assert auto_burc.status_code == 200
        b_task = auto_burc.json()["task"]
        created_ids.append(b_task["job_id"])
        assert b_task["gpu_kuyruk"] is False
        assert b_task["output_url"].startswith("/api/media/file?path=")

        # Canlı GPU işçisi kalp atışı göndermişse `auto` gerçek GPU kuyruğuna alır
        wh = {"X-Worker-Key": main_mod.get_worker_key()}
        hb = client.post("/api/worker/heartbeat", json={
            "worker_id": "kaggle_live_t4",
            "worker_type": "kaggle",
            "gpu_name": "Tesla T4",
            "vram_gb": 16.0,
            "status": "idle",
        }, headers=wh)
        assert hb.status_code == 200

        gpu_studio = client.post("/api/studio/video/generate", json={
            "channel": "Astroloji_Kova",
            "workflow": "image_then_i2v",
            "execution_mode": "auto",
            "aspect_ratio": "16:9",
            "duration": 3,
            "voice": "none",
            "prompt": "Canlı işçi kuyruk yönlendirmesi",
        }, headers=auth_headers)
        assert gpu_studio.status_code == 200
        g_task = gpu_studio.json()["task"]
        created_ids.append(g_task["job_id"])
        assert g_task["gpu_kuyruk"] is True
        assert g_task["gpu_durum"] == "bekliyor"

        sw_txt = (Path(__file__).resolve().parent.parent / "static" / "sw.js").read_text(encoding="utf-8")
        lab_txt = (Path(__file__).resolve().parent.parent / "static" / "lab.html").read_text(encoding="utf-8")
        idx_txt = (Path(__file__).resolve().parent.parent / "static" / "index.html").read_text(encoding="utf-8")
        fab_txt = (Path(__file__).resolve().parent.parent / "static" / "fabrika.html").read_text(encoding="utf-8")
        site_css = (Path(__file__).resolve().parent.parent / "static" / "site.css").read_text(encoding="utf-8")
        styles_css = (Path(__file__).resolve().parent.parent / "static" / "styles.css").read_text(encoding="utf-8")
        assert "/lab.js?v=33" in sw_txt
        assert "/lab.js?v=33" in lab_txt
        assert "/site.css?v=30" in idx_txt and "/site.css?v=30" in lab_txt
        assert "/styles.css?v=9" in fab_txt
        assert "fabrika-pwa-v33-mobile" in sw_txt
        assert "fabrika-pwa-v33-mobile" in lab_txt
        assert "fabrika-pwa-v33-mobile" in fab_txt
        fab_js = (Path(__file__).resolve().parent.parent / "static" / "fabrika_desktop.js").read_text(encoding="utf-8")
        assert "window.sendUiAction(willWake ? 'wake' : 'sleep')" in fab_js
        assert "sendUiAction('music_mode')" not in fab_js
        assert "♈ Burç" not in lab_txt and "♈ Astroloji" not in lab_txt
        lab_js = (Path(__file__).resolve().parent.parent / "static" / "lab.js").read_text(encoding="utf-8")
        assert "'♈ <strong>'" not in lab_js
        assert "burc.simge" in lab_js
        assert "burcRawPromptCheck" in lab_txt
        assert "[hidden] { display: none !important; }" in site_css
        assert "overflow-x: clip;" in site_css
        assert "flex-direction: column;" in site_css
        assert ".site-picker-tray" in site_css and "min-width: 0" in site_css
        assert "overflow-y: auto" in styles_css and "touch-action: pan-x" in styles_css
    finally:
        main_mod.ACTIVE_GPU_WORKERS.clear()
        for jid in created_ids:
            for p in main_mod.MEDIA_DIR.glob(f"{jid}*"):
                p.unlink(missing_ok=True)


def test_burc_prompt_parity_cloudflare_dict_and_video_stage_layout(monkeypatch):
    """Burç senaryosu kullanıcı konusunu image_prompt'a taşır, CF dict/Türkçe LLM hatasını reddeder."""
    import json as _json
    import burc_pipeline as bp
    import prompt_director as pd

    for k in list(os.environ):
        if "GEMINI_API_KEY" in k.upper():
            monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("CF_API_TOKEN", raising=False)

    konu = "elinde kova olan bir adam gökyüzünden yeryüzüne su boşaltıyor"

    # 1. Çevrimdışı şablon bile özel konuyu fütüristik şehir şablonuyla ezmemeli ve kalıp metin yazmamalıdır.
    off = bp.burc_senaryo_olustur("kova", konu=konu, sure_sn=15, dil="tr", aspect_ratio="16:9")
    assert off["ok"] is True
    assert off["simulasyon"] is True
    assert off["narration_text"] == konu
    for yasak in ("astroloji molası", "etkisini taşır", "neon su taşıyıcı", "fütüristik şehir", "sakin bir anlatım"):
        assert yasak not in off["narration_text"].lower()
    img_low = off["image_prompt"].lower()
    assert "futuristic city" not in img_low
    assert "16:9" in img_low
    assert ("water" in img_low or "pitcher" in img_low or "pouring" in img_low)
    assert len(off.get("scenes") or []) >= 2

    # 1b. raw_prompt=True kullanıcının metnini aynen korur; 'kova' + 'burc' yoksa bucket olarak çevirir.
    raw_res = bp.burc_senaryo_olustur("kova", konu=konu, sure_sn=15, dil="tr", aspect_ratio="16:9", raw_prompt=True)
    assert raw_res["raw_prompt"] is True
    assert raw_res["narration_text"] == konu
    assert raw_res["subtitle_text"] == konu
    assert "bucket" in raw_res["image_prompt"].lower()
    assert "16:9" in raw_res["image_prompt"]

    # 2. Cloudflare dict yanıtı .strip() ile çökmez; 70B İngilizce sahneyi döner.
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-tok")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "cf-acc")

    class FakeResp:
        def __init__(self, payload):
            self._p = payload
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return _json.dumps(self._p).encode("utf-8")

    def fake_urlopen(req, timeout=10):
        return FakeResp({
            "success": True,
            "result": {
                "response": {
                    "narration_text": "Gökyüzünden yeryüzüne bereketli sular boşalıyor.",
                    "image_prompt": "mythic robed man in starry night heavens pouring water from an ornate glowing bucket down to planet Earth",
                    "motion_prompt": "slow cosmic orbit around the pouring water stream",
                    "scenes": [
                        {"image_prompt": "wide celestial view of a man in the heavens holding an ornate glowing bucket pouring water down toward Earth", "motion_prompt": "slow orbit"},
                        {"image_prompt": "close-up of luminous water cascading from an ornate golden bucket in starry space", "motion_prompt": "gentle push-in"},
                    ],
                }
            },
        })

    monkeypatch.setattr(bp.urllib.request, "urlopen", fake_urlopen)
    cf_res = bp.burc_senaryo_olustur("kova", konu=konu, sure_sn=15, dil="tr", aspect_ratio="16:9")
    assert cf_res["simulasyon"] is False
    assert cf_res["kaynak"].startswith("cloudflare:")
    assert "bucket" in cf_res["image_prompt"].lower() and "earth" in cf_res["image_prompt"].lower()
    assert len(cf_res["scenes"]) == 2

    # 3. prompt_director küçük LLM'in Türkçe image_prompt döndürmesini reddeder ve 'sun' kelimesini 'su' sanmaz.
    assert pd._looks_like_untranslated_turkish("Bir adam gökyüzünde kova ile su boşaltıyor") is True
    assert pd._looks_like_untranslated_turkish("A celestial man pouring water from an ornate bucket above planet Earth") is False
    assert pd._is_turkish_text("sunset over surface") is False
    assert pd._normalize_plan_dict({
        "narration_text": "Türkçe anlatım",
        "scenes": [{"image_prompt": "Bir adam gökyüzünde duruyor"}],
    }, 2, "orbit", "cloudflare:llama-3.1-8b") is None


def test_no_pollinations_no_text_card_and_real_i2v_character_animation(client, auth_headers, monkeypatch, tmp_path):
    """Pollinations tamamen kapalı, görsel üretimi düşerse metin kartı üretilmez ve real_i2v zoom/pan ile sahtelenmez."""
    import ai_video_montaj as avm
    import hyperframes_motor as hf
    import main as main_mod

    avm_src = (Path(__file__).resolve().parent.parent / "ai_video_montaj.py").read_text(encoding="utf-8")
    assert "image.pollinations.ai" not in avm_src

    # 1. Tüm gerçek görsel sağlayıcıları başarısızken ne preview ne studio text card PNG basmaz
    monkeypatch.setattr(avm, "preview_single_image", lambda *a, **k: {"ok": False, "provider": None, "error": "kota dolu"})
    hf_fail = hf.hyperframes_studio_render(tmp_path / "fail.mp4", tmp_path / "fail.html", "prompt metni", ["test prompt"])
    assert hf_fail["ok"] is False
    assert not (tmp_path / "fail.mp4").exists()

    main_mod.ACTIVE_GPU_WORKERS.clear()
    fail_prev = client.post("/api/burc/video/generate", json={
        "burc_kodu": "kova",
        "konu": "elinde kova olan bir adam gökyüzünden yeryüzüne su boşaltıyor",
        "raw_prompt": True,
        "method": "flux2_resim",
        "execution_mode": "auto",
    }, headers=auth_headers)
    assert fail_prev.status_code == 502

    # 2. Onaylı görselde execution_mode='real_i2v' iken LTX başarısızsa zoom/pan YAPILMAZ, GPU kuyruğuna alınır
    fake_png = tmp_path / "approved.png"
    hf._kinetic_card_png(fake_png, "Onaylı Kare", "Test", 320, 180)
    up_bytes = fake_png.read_bytes()
    monkeypatch.setattr(hf, "cloud_real_i2v_animate", lambda *a, **k: {"ok": False, "error": "HF_TOKEN yok"})

    called_zoom = {"n": 0}
    orig_zoom = hf.instant_i2v_motion

    def spy_zoom(*a, **k):
        called_zoom["n"] += 1
        return orig_zoom(*a, **k)

    monkeypatch.setattr(hf, "instant_i2v_motion", spy_zoom)
    created_ids = []
    try:
        import base64
        b64_img = "data:image/png;base64," + base64.b64encode(up_bytes).decode("ascii")
        q_real = client.post("/api/burc/video/generate", json={
            "burc_kodu": "kova",
            "konu": "adam kovadan su boşaltıyor",
            "raw_prompt": True,
            "method": "wan_i2v",
            "execution_mode": "real_i2v",
            "image_base64": b64_img,
        }, headers=auth_headers)
        assert q_real.status_code == 200
        qd = q_real.json()
        created_ids.append(qd["job_id"])
        assert called_zoom["n"] == 0
        assert qd["gpu_kuyruk"] is True
        assert qd["needs_gpu_worker"] is True

        # 3. LTX ZeroGPU I2V başarılıysa gerçek video_difuzyonu=True ve simulasyon=False döner
        def fake_ltx(src_img, hedef_mp4, **kw):
            hf.instant_i2v_motion(src_img, hedef_mp4, duration_sec=3.0)
            return {
                "ok": True,
                "path": hedef_mp4,
                "file_size_bytes": hedef_mp4.stat().st_size,
                "resolution": "854x480",
                "duration_sec": 3.0,
                "kalite": {"gecerli": True},
                "simulasyon": False,
                "video_difuzyonu": True,
                "kaynak": "ltx-video-distilled-i2v",
            }

        monkeypatch.setattr(hf, "cloud_real_i2v_animate", fake_ltx)
        ok_real = client.post("/api/burc/video/generate", json={
            "burc_kodu": "kova",
            "konu": "adam kovadan su boşaltıyor",
            "raw_prompt": True,
            "method": "wan_i2v",
            "execution_mode": "real_i2v",
            "image_base64": b64_img,
        }, headers=auth_headers)
        assert ok_real.status_code == 200
        od = ok_real.json()
        created_ids.append(od["job_id"])
        assert od["gpu_kuyruk"] is False
        assert od["simulasyon"] is False
        assert od["video_difuzyonu"] is True
        assert od["task"]["kaynak"] == "ltx-video-distilled-i2v"
    finally:
        for jid in created_ids:
            for p in main_mod.MEDIA_DIR.glob(f"{jid}*"):
                p.unlink(missing_ok=True)


# -----------------------------------------------------------------------------
# 5. GÜVENLİK, MAC PORT-443 KÖPRÜSÜ, GERÇEK AST REA, YOUTUBE V3 & VİTRİN TESTLERİ
# -----------------------------------------------------------------------------
def test_media_bypass_blocked_and_private_read_endpoints_require_auth(client):
    """/static/media atlatması 403 dönmeli ve tüm özel okuma API'leri tokensız 401 dönmelidir."""
    assert client.get("/static/media/secret.mp4").status_code == 403
    assert client.get("/media/secret.mp4").status_code == 403

    private_reads = [
        "/api/lab/history",
        "/api/audio/history",
        "/api/links/pool",
        "/api/channels",
        "/api/studio/catalog",
        "/api/system/stats",
        "/api/rea/history",
        "/api/gpu/cluster/status",
        "/api/video/tesis",
        "/api/bridge/status",
    ]
    for url in private_reads:
        r = client.get(url)
        assert r.status_code == 401, f"{url} tokensız 401 dönmeliydi, alınan: {r.status_code}"
    assert client.post("/api/bridge/command", json={"text": "merhaba"}).status_code == 401


def test_mac_port443_bridge_and_websocket_relay(client, auth_headers, auth_token):
    """Mac Port-443 köprüsü kapalıyken dürüst çevrimdışı döner; açıkken gerçek komut ve telemetri taşır."""
    import threading
    import time
    from mac_bridge import bridge_hub

    bridge_hub.reset()
    try:
        # 1. Geçersiz sırla poll reddedilir
        assert client.post("/api/bridge/poll", json={}).status_code == 401
        assert client.post("/api/bridge/poll", json={}, headers={"X-Fabrika-Bridge-Secret": "yanlis"}).status_code == 401

        # 2. Çevrimdışıyken komut beklemeden mac_offline döner
        off = client.post("/api/bridge/command", json={"text": "durum"}, headers=auth_headers)
        assert off.status_code == 200
        assert off.json()["mac_online"] is False
        assert off.json()["status"] == "mac_offline"

        # 3. Mac köprüsü geçerli sırla kalp atışı gönderir
        bridge_hdr = {"X-Fabrika-Bridge-Secret": "test_guclu_parola_9988"}
        p1 = client.post(
            "/api/bridge/poll",
            json={"stats": {"cpu": 23.4, "ram": 58.1, "link_pool_count": 247, "named_tunnel_active": True}},
            headers=bridge_hdr,
        )
        assert p1.status_code == 200
        assert p1.json()["ok"] is True

        st = client.get("/api/system/stats", headers=auth_headers).json()
        assert st["mac_bridge_online"] is True
        assert st["cpu"] == 23.4
        assert st["ram"] == 58.1

        # 4. Arka planda Mac yanıtlayıcı ile gerçek komut-yanıt akışı
        def _fake_mac_worker():
            import time as _t
            for _ in range(30):
                tasks = bridge_hub.handle_poll(stats={"cpu": 25.0, "ram": 60.0})
                if tasks:
                    cid = tasks[0]["id"]
                    bridge_hub.handle_poll(replies=[{
                        "id": cid,
                        "sender": "⚡ Açık Uygulamalar",
                        "text": "Chrome, VS Code açık",
                        "action": "acik_uygulamalar",
                    }])
                    return
                _t.sleep(0.05)

        th = threading.Thread(target=_fake_mac_worker, daemon=True)
        th.start()
        cmd_res = client.post(
            "/api/bridge/command",
            json={"text": "açık uygulamalar neler", "timeout_sec": 5},
            headers=auth_headers,
        )
        th.join(timeout=3)
        assert cmd_res.status_code == 200
        cd = cmd_res.json()
        assert cd["success"] is True
        assert cd["mac_online"] is True
        assert "Chrome" in cd["text"]

        # 5. WebSocket welcome mesajı app.js'in gösterdiği `system_alert` türünde olmalı
        with client.websocket_connect(f"/ws/chat?token={auth_token}") as ws:
            welcome = json.loads(ws.receive_text())
            assert welcome["type"] == "system_alert"
    finally:
        bridge_hub.reset()




def test_rea_ast_accepts_hedef_and_detects_real_issues(client, auth_headers):
    """REA tarayıcısı `hedef` parametresini AST ile analiz eder (boş geçip 100 vermez)."""
    bad_py = "import os, pickle\nos.system('id')\npickle.loads(data)\napi_key = 'sk-1234567890abcdef'\n"
    res = client.post("/api/rea/scan", json={"hedef": bad_py, "persona": "kys"}, headers=auth_headers)
    assert res.status_code == 200
    d = res.json()
    assert d["mode"] == "python_ast"
    assert d["score"] <= 20
    assert d["vulnerabilities_found"] >= 3
    assert "AST" in d["rapor"]


def test_youtube_http_resumable_uploader_and_env_persistence(monkeypatch, tmp_path):
    """YouTube yükleyici google-api-python-client olmadan env token ile çalışır ve resumable MP4 yükler."""
    import youtube_uploader as yu

    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "cid-test")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "csec-test")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "ref-test")

    st = yu.youtube_status(tmp_path)
    assert st["ready_for_live_upload"] is True
    assert st["persistence_mode"] == "env"
    assert st["transport"] == "http_resumable_v3"

    fake_mp4 = tmp_path / "demo.mp4"
    fake_mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1024)

    class FakeHttpResp:
        def __init__(self, status_code=200, payload=None, headers=None):
            self.status_code = status_code
            self.ok = 200 <= status_code < 300
            self._payload = payload or {}
            self.headers = headers or {}
            self.text = json.dumps(self._payload)

        def json(self):
            return self._payload

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return FakeHttpResp(200, {"access_token": "acc-123"})
        if "upload/youtube/v3/videos" in url:
            return FakeHttpResp(200, {}, headers={"Location": "https://upload.example/session/1"})
        return FakeHttpResp(200, {})

    def fake_put(url, **kw):
        assert url == "https://upload.example/session/1"
        return FakeHttpResp(200, {"id": "yt_vid_999"})

    monkeypatch.setattr(yu.requests, "post", fake_post)
    monkeypatch.setattr(yu.requests, "put", fake_put)

    up = yu.upload_video_resumable(
        fake_mp4,
        {"job_id": "J1", "channel_id": "Tech_AI_Fabrika", "title": "Demo", "description": "Test", "tags": ["ai"], "privacy": "private"},
        tmp_path,
    )
    assert up["success"] is True
    assert up["simulasyon"] is False
    assert up["youtube_video_id"] == "yt_vid_999"
    assert up["youtube_url"] == "https://www.youtube.com/watch?v=yt_vid_999"


def test_public_homepage_clean_html_seo_and_contact_form(client):
    """Ana sayfa kilit ekranıyla açılmamalı, kırık div içermemeli, SEO & iletişim formu çalışmalıdır."""
    idx = client.get("/")
    assert idx.status_code == 200
    html = idx.text
    assert 'property="og:title"' in html
    assert 'id="projeler"' in html
    assert 'id="siteContactForm"' in html
    assert 'id="siteHub"' not in html
    assert "Alancf" not in html and "alanadisifre" not in html
    # Dengeli div sayısı (erken kapanan site-shell yok)
    assert html.count("<div") == html.count("</div>")

    site_js = client.get("/site.js").text
    assert "if (!t) { showGate()" not in site_js

    assert client.get("/robots.txt").status_code == 200
    assert "Sitemap:" in client.get("/robots.txt").text
    assert client.get("/sitemap.xml").status_code == 200

    bad = client.post("/api/contact", json={"name": "A", "email": "bozuk", "message": "kısa"})
    assert bad.status_code == 400

    good = client.post("/api/contact", json={
        "name": "Test Müşteri",
        "email": "musteri@example.com",
        "message": "Yapay zeka otomasyon projesi hakkında bilgi almak istiyorum.",
    })
    assert good.status_code == 200
    assert good.json()["success"] is True


def test_contact_notifier_email_inbox_and_mobile_fixed_nav(client, auth_headers, monkeypatch):
    """İletişim formu e-posta/Telegram durumunu dürüstçe raporlar, gelen kutusuna yazar ve mobil sabit bar mevcuttur."""
    import contact_notifier as cn

    # Yetkisiz gelen kutusu reddedilmeli
    assert client.get("/api/contact/messages").status_code == 401

    # 1. Hiçbir canlı kanal tanımlı değilken dürüstçe inbox_only + mailto fallback döner
    for k in ("RESEND_API_KEY", "SMTP_HOST", "SMTP_USER", "SMTP_PASS", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(main, "get_secret_from_env", lambda k: os.environ.get(k))
    main.CONTACT_RATE.clear()

    r1 = client.post("/api/contact", json={
        "name": "Ayşe Yılmaz",
        "email": "ayse@example.com",
        "message": "Kurumsal otomasyon sistemi hakkında görüşmek istiyorum.",
    })
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["email_sent"] is False
    assert d1["telegram_sent"] is False
    assert d1["delivery_channel"] == "inbox_only"
    assert d1["mailto_fallback_url"].startswith("mailto:ys@yusasufhin.com?")

    inbox = client.get("/api/contact/messages", headers=auth_headers)
    assert inbox.status_code == 200
    assert inbox.json()["count"] >= 1
    assert inbox.json()["items"][0]["name"] == "Ayşe Yılmaz"
    assert inbox.json()["notifier"]["any_live_channel"] is False

    # 2. RESEND_API_KEY tanımlıysa gerçek HTTP e-posta gönderimi yapılır
    monkeypatch.setenv("RESEND_API_KEY", "re_test_123456")

    class FakeResendResp:
        ok = True
        status_code = 200
        text = '{"id":"email_1"}'

    called = {"url": None, "to": None}

    def fake_post(url, **kw):
        called["url"] = url
        called["to"] = (kw.get("json") or {}).get("to")
        return FakeResendResp()

    monkeypatch.setattr(cn.requests, "post", fake_post)
    r2 = client.post("/api/contact", json={
        "name": "Mehmet Demir",
        "email": "mehmet@example.com",
        "message": "Video otomasyon projesi için teklif almak istiyorum.",
    })
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["email_sent"] is True
    assert d2["delivery_channel"] == "email"
    assert called["url"] == "https://api.resend.com/emails"
    assert called["to"] == ["ys@yusasufhin.com"]

    # 3. Mobil sabit üst menü, iOS safe-area ve mobil alt sekme çubuğu CSS/HTML'de doğrulanır
    css = (REPO_DIR / "static" / "site.css").read_text(encoding="utf-8")
    assert "position: fixed;" in css
    assert "env(safe-area-inset-top)" in css
    assert ".site-mobile-tabbar" in css
    lab_html = (REPO_DIR / "static" / "lab.html").read_text(encoding="utf-8")
    assert 'id="labMobileTabbar"' in lab_html
    assert 'id="contactInboxList"' in lab_html


def test_remote_fabrika_desktop_twin_ui_panels_and_routes(client):
    """Uzaktan Fabrika arayüzü (v27): Üst/Alt/Sağ panel, 3D Reaktör, XAI ve rotalar eksiksiz olmalı."""
    for path, mime_part in (
        ("/fabrika", "text/html"),
        ("/fabrika.html", "text/html"),
        ("/fabrika_desktop.css", "text/css"),
        ("/fabrika_desktop.js", "javascript"),
    ):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} beklenmedik durum döndü: {resp.status_code}"
        assert mime_part in resp.headers.get("content-type", "")
        assert "no-cache" in resp.headers.get("cache-control", "")

    fab_html = (REPO_DIR / "static" / "fabrika.html").read_text(encoding="utf-8")
    for token in (
        'id="fabWindow"',
        'id="ustPanel"',
        'id="reaktorCanvas"',
        'id="ustLayerLog"',
        'id="ustLayerXai"',
        'id="ustLayerCode"',
        'id="ustLayerEq"',
        'id="fabErrorStrip"',
        'id="fabSeritTrack"',
        'id="btnCenterOrb"',
        'id="btnFlowUser"',
        'id="btnFlowAdd"',
        'id="btnFlowSettings"',
        'id="btnFlowBrain"',
        'id="messagesBox"',
        'class="fab-console"',
        'id="chatInput"',
        'id="btnMic"',
        'id="btnSpeaker"',
        'id="rightDrawer"',
        'id="drawerPanelTitle"',
        'id="drawerBadgeUpdated"',
        'id="btnDrawerClose"',
        'data-drawer-page="kadro"',
        'data-drawer-page="rapor"',
        'data-drawer-page="havuz"',
        'data-drawer-page="rea"',
        'data-drawer-page="kod"',
        'data-drawer-page="ayarlar"',
    ):
        assert token in fab_html, f"fabrika.html içinde eksik masaüstü bileşeni: {token}"

    desk_js = (REPO_DIR / "static" / "fabrika_desktop.js").read_text(encoding="utf-8")
    assert "const numNodes = 450;" in desk_js
    assert "#00FFCC" in desk_js and "#FF6B6B" in desk_js and "#FFE66D" in desk_js
    assert "window.FabrikaDesktop" in desk_js

    lab_html = (REPO_DIR / "static" / "lab.html").read_text(encoding="utf-8")
    assert 'href="/fabrika"' in lab_html


def test_live_desktop_mirror_poll_sync_and_ui_actions(client, auth_headers, monkeypatch):
    """v28: Mac masaüstü durumu poll->status->WS desktop_sync ve uzaktan ui_action akışı."""
    from mac_bridge import bridge_hub

    monkeypatch.setenv("BRIDGE_SECRET", "v28-bridge-secret")
    bridge_hub.reset()
    try:
        # 1. Mac köprüsü masaüstü penceresi açık durumunu poll ile bildirir
        desk_payload = {
            "desktop_app_open": True,
            "rev": 7,
            "chat_seq": 2,
            "log_seq": 1,
            "center_state": "ACTIVE",
            "active_agent": "CEO",
            "is_processing": False,
            "is_speaking": False,
            "chat_messages": [
                {"seq": 1, "role": "user", "sender": "⌨️ Sen", "text": "selam", "ts": "22:50"},
                {"seq": 2, "role": "agent", "sender": "CEO", "text": "Merhaba kurucu!", "ts": "22:50"},
            ],
            "logs": [{"seq": 1, "text": "CEO yanıtladı", "level": "info", "ts": "22:50:01"}],
            "xai": {"state": "TAMAMLANDI", "agent": "CEO", "model": "Qwen3", "desc": "Hazır"},
            "side_panel": {"open": True, "title": "Rapor", "mode": "report", "html": "<b>Canlı</b>", "updated_at": 123.4},
            "question_card": {"visible": True, "title": "Onay", "question": "Başlasın mı?", "options": ["Evet", "Hayır"]},
            "org_agents": [{"key": "CEO", "display_name": "CEO", "name": "Ermiş", "color": "#00FFCC", "is_core": True}],
        }
        r_poll = client.post(
            "/api/bridge/poll",
            headers={"X-Fabrika-Bridge-Secret": "v28-bridge-secret"},
            json={"stats": {"cpu": 18.5, "ram": 52.0, "desktop_app_open": True}, "replies": [], "desktop_state": desk_payload},
        )
        assert r_poll.status_code == 200

        r_st = client.get("/api/bridge/status", headers=auth_headers)
        assert r_st.status_code == 200
        st = r_st.json()
        assert st["online"] is True
        assert st["desktop_app_open"] is True
        assert st["desktop_state"]["chat_messages"][-1]["text"] == "Merhaba kurucu!"

        # 2. Uzaktan UI eylemi kuyruğa alınır ve sonraki Mac poll çağrısında teslim edilir
        r_act = client.post(
            "/api/bridge/action",
            headers=auth_headers,
            json={"action": "answer_question", "payload": {"choice": "Evet"}},
        )
        assert r_act.status_code == 200
        assert r_act.json()["ok"] is True

        r_poll2 = client.post(
            "/api/bridge/poll",
            headers={"X-Fabrika-Bridge-Secret": "v28-bridge-secret"},
            json={"stats": {"cpu": 19.0, "ram": 52.1, "desktop_app_open": True}, "replies": [], "desktop_state": desk_payload},
        )
        assert r_poll2.status_code == 200
        tasks = r_poll2.json()["tasks"]
        assert len(tasks) == 1
        assert tasks[0]["kind"] == "ui_action"
        assert tasks[0]["action"] == "answer_question"
        assert tasks[0]["payload"]["choice"] == "Evet"

        # 3. WebSocket açılışında mevcut canlı masaüstü durumu (desktop_sync) hemen gönderilir
        tok = auth_headers["Authorization"].split(" ", 1)[1]
        with client.websocket_connect(f"/ws/chat?token={tok}") as ws:
            w1 = ws.receive_json()
            assert w1["type"] == "system_alert"
            w2 = ws.receive_json()
            assert w2["type"] == "desktop_sync"
            assert w2["state"]["desktop_app_open"] is True
            ws.send_json({"type": "ui_action", "action": "barge_in", "payload": {}})
            ack = ws.receive_json()
            assert ack["type"] == "ui_action_ack"
            assert ack["ok"] is True

        fab_html = (REPO_DIR / "static" / "fabrika.html").read_text(encoding="utf-8")
        desk_js = (REPO_DIR / "static" / "fabrika_desktop.js").read_text(encoding="utf-8")
        assert 'id="fabQuestionCard"' in fab_html
        assert "applyDesktopSync" in desk_js and "sendUiAction" in desk_js
    finally:
        bridge_hub.reset()




def test_v29_direct_mail_relay_and_security_hardening(client, auth_headers, monkeypatch, tmp_path):
    """v29: Mac Gmail TLS rölesi, OAuth state CSRF kalkanı, SSRF 302 engeli, proxy IP ve güvenlik başlıkları."""
    import threading
    import time
    import urllib.error
    import urllib.parse
    import main as main_mod
    import prompt_director as pd
    from channels_manager import ChannelStore
    from mac_bridge import bridge_hub

    # 1. Güvenlik başlıkları (HSTS, CSP frame-ancestors, Permissions-Policy)
    r_idx = client.get("/")
    assert r_idx.status_code == 200
    assert "max-age=31536000" in r_idx.headers.get("strict-transport-security", "")
    assert "frame-ancestors 'none'" in r_idx.headers.get("content-security-policy", "")
    assert "camera=()" in r_idx.headers.get("permissions-policy", "")

    # 2. Proxy IP sahteciliği koruması: onrender.com üzerinden sahte CF-Connecting-IP yoksayılır, sağdaki genel XFF alınır
    class _FakeClient:
        host = "10.204.11.8"

    class _FakeReq:
        client = _FakeClient()
        headers = {
            "host": "yusasufhin-cockpit.onrender.com",
            "cf-connecting-ip": "1.1.1.1",
            "x-forwarded-for": "9.9.9.9, 198.51.100.42, 10.204.11.8",
        }

    assert main_mod.get_client_ip(_FakeReq()) == "198.51.100.42"

    # 3. YouTube OAuth state HMAC-CSRF koruması: imzasız/sahte state reddedilir, imzalı state tek kullanımlıktır
    store = ChannelStore(tmp_path)
    store.save_client_secret(json.dumps({
        "web": {"client_id": "cid.apps.googleusercontent.com", "client_secret": "csec_test_999"}
    }))
    assert ((tmp_path / "youtube_auth" / "client_secret.json").stat().st_mode & 0o777) == 0o600
    auth_url = store.build_oauth_authorize_url("Tech_AI_Fabrika", "https://yusasufhin.com/api/youtube/oauth/callback")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
    signed_state = qs["state"][0]
    with pytest.raises(ValueError):
        store._verify_and_consume_oauth_state("Tech_AI_Fabrika", "csec_test_999")
    assert store._verify_and_consume_oauth_state(signed_state, "csec_test_999") == "Tech_AI_Fabrika"
    with pytest.raises(ValueError):
        store._verify_and_consume_oauth_state(signed_state, "csec_test_999")  # replay engellenmeli

    # 4. SSRF HTTP 302 yönlendirme kalkanı: genel URL'den 127.0.0.1'e yönlendirme engellenir
    handler = pd._SafeRedirectHandler()
    orig_req = urllib.request.Request("https://example.com/start")
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(orig_req, None, 302, "Found", {}, "http://127.0.0.1:27491/ping")

    # 5. ys@yusasufhin.com Mac Port-443 Rölesi: config kaydı (0600) + canlı Mac rölesinden doğrudan mail teslimi
    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    monkeypatch.setenv("BRIDGE_SECRET", "v29-sec")
    monkeypatch.setenv("RENDER", "true")
    for k in ("RESEND_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(main_mod, "get_secret_from_env", lambda k: "v29-sec" if k == "BRIDGE_SECRET" else None)

    bridge_hub.reset()
    try:
        # Mac çevrimiçi olarak kalp atışı gönderir
        client.post(
            "/api/bridge/poll",
            headers={"X-Fabrika-Bridge-Secret": "v29-sec"},
            json={"stats": {"cpu": 10.0, "ram": 40.0, "smtp_ready": True}, "replies": []},
        )
        r_cfg = client.post(
            "/api/contact/config",
            headers=auth_headers,
            json={"smtp_pass": "abcd efgh ijkl mnop", "to_email": "ys@yusasufhin.com"},
        )
        assert r_cfg.status_code == 200
        assert ((tmp_path / ".mail_secrets.json").stat().st_mode & 0o777) == 0o600

        # Mac arka plan iş parçacığı poll ile contact_email görevini alıp gerçek iletim onayı döner
        def _mac_worker():
            for _ in range(40):
                time.sleep(0.03)
                tasks = bridge_hub.handle_poll(
                    stats={"cpu": 10.0, "ram": 40.0, "smtp_ready": True},
                    replies=[],
                )
                for t in tasks:
                    if t.get("kind") == "contact_email":
                        assert t["payload"]["to_email"] == "ys@yusasufhin.com"
                        bridge_hub.handle_poll(
                            stats={"cpu": 10.0, "ram": 40.0, "smtp_ready": True},
                            replies=[{"id": t["id"], "email_sent": True, "provider": "mac_gmail_relay"}],
                        )
                        return

        t_worker = threading.Thread(target=_mac_worker, daemon=True)
        t_worker.start()

        r_contact = client.post("/api/contact", json={
            "name": "Caner Kaya",
            "email": "caner@firma.com",
            "message": "Merhaba, doğrudan ys@yusasufhin.com adresine ulaşan teklif mesajıdır.",
        })
        t_worker.join(timeout=3.0)
        assert r_contact.status_code == 200
        dc = r_contact.json()
        assert dc["email_sent"] is True
        assert "ys@yusasufhin.com" in dc["message"]
    finally:
        bridge_hub.reset()


def test_v30_rbac_users_recipients_music_and_interactive_home(client, auth_headers, monkeypatch, tmp_path):
    """v30: Çoklu yönetici/kullanıcı RBAC, çoklu e-posta alıcısı, Lyria 3.5 müzik stüdyosu ve interaktif ana sayfa."""
    import time
    import main as main_mod
    import music_studio as ms

    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_mod, "MEDIA_DIR", tmp_path / "media")

    # 1. İnteraktif ana sayfa + hareketli Fabrika arayüzü + 3 butonlu yönetici paneli
    r_home = client.get("/")
    assert r_home.status_code == 200
    assert 'id="homeReactiveCanvas"' in r_home.text
    assert 'id="fabrikaShowcase"' in r_home.text
    assert 'id="fabrika-ozellikler"' in r_home.text
    assert r_home.text.count("<div") == r_home.text.count("</div>")

    r_panel = client.get("/panel")
    assert r_panel.status_code == 200
    for bid in ("hubCardFabrika", "hubCardVideo", "hubCardMuzik", "fabrikaUsersSlot", "videoUsersSlot", "muzikUsersSlot"):
        assert bid in r_panel.text

    # 2. Yönetici & kullanıcı ekleme (PBKDF2 hash + 0600 izin + bölüm bazlı 403 zorlama)
    r_u = client.post(
        "/api/admin/users",
        headers=auth_headers,
        json={
            "username": "ali.video",
            "display_name": "Ali Video",
            "password": "GucluParola123!",
            "role": "user",
            "sections": ["video"],
        },
    )
    assert r_u.status_code == 200
    users_file = tmp_path / ".users.json"
    assert (users_file.stat().st_mode & 0o777) == 0o600
    assert "GucluParola123!" not in users_file.read_text(encoding="utf-8")

    # Kullanıcı girişi ve rol/bölüm izolasyonu
    r_login = client.post("/api/auth/login", json={"username": "ali.video", "password": "GucluParola123!"})
    assert r_login.status_code == 200
    u_tok = r_login.json()["token"]
    u_hdr = {"Authorization": f"Bearer {u_tok}"}

    chk = client.get("/api/auth/check", headers=u_hdr)
    assert chk.status_code == 200 and chk.json()["role"] == "user" and chk.json()["sections"] == ["video"]
    assert client.get("/api/studio/catalog", headers=u_hdr).status_code == 200
    assert client.get("/api/music/models", headers=u_hdr).status_code == 403
    assert client.get("/api/bridge/status", headers=u_hdr).status_code == 403
    assert client.get("/api/admin/users", headers=u_hdr).status_code == 403
    assert client.get("/api/contact/recipients", headers=u_hdr).status_code == 403

    # Ek yönetici ekleme ve kullanıcı silindiğinde oturumun anında feshi
    r_adm = client.post(
        "/api/admin/users",
        headers=auth_headers,
        json={"username": "zeynep.admin", "password": "AdminParola456!", "role": "admin"},
    )
    assert r_adm.status_code == 200
    r_adm_login = client.post("/api/auth/login", json={"username": "zeynep.admin", "password": "AdminParola456!"})
    adm2_hdr = {"Authorization": f"Bearer {r_adm_login.json()['token']}"}
    assert client.get("/api/admin/users", headers=adm2_hdr).status_code == 200

    assert client.delete("/api/admin/users/ali.video", headers=adm2_hdr).status_code == 200
    assert client.get("/api/studio/catalog", headers=u_hdr).status_code == 401  # oturum anında iptal!

    # 3. Çoklu e-posta alıcısı ekleme / silme / son alıcı koruması + çoklu iletim
    r_rec0 = client.get("/api/contact/recipients", headers=auth_headers)
    assert r_rec0.status_code == 200 and "ys@yusasufhin.com" in r_rec0.json()["recipients"]
    assert client.post("/api/contact/recipients", headers=auth_headers, json={"email": "bozuk-mail"}).status_code == 400
    r_add = client.post("/api/contact/recipients", headers=auth_headers, json={"email": "ekip@yusasufhin.com"})
    assert r_add.status_code == 200 and r_add.json()["recipients"] == ["ys@yusasufhin.com", "ekip@yusasufhin.com"]

    yakalanan_to: list = []
    from mac_bridge import bridge_hub
    monkeypatch.setattr(
        bridge_hub,
        "relay_contact_email",
        lambda payload, **kw: (yakalanan_to.append(payload.get("to_emails")) or {"email_sent": True, "provider": "mac_gmail_relay"}),
    )
    for k in ("RESEND_API_KEY", "SMTP_PASS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(main_mod, "get_secret_from_env", lambda k: None)
    r_ct = client.post("/api/contact", json={"name": "Deniz Arslan", "email": "deniz@ornek.com", "message": "Çoklu alıcı test mesajı gönderiliyor."})
    assert r_ct.status_code == 200 and r_ct.json()["email_sent"] is True
    assert yakalanan_to[-1] == ["ys@yusasufhin.com", "ekip@yusasufhin.com"]

    assert client.delete("/api/contact/recipients?email=ekip@yusasufhin.com", headers=auth_headers).status_code == 200
    assert client.delete("/api/contact/recipients?email=ys@yusasufhin.com", headers=auth_headers).status_code == 400

    # 4. Çoklu Model Müzik Stüdyosu (anahtar eksikse dürüst red + Lyria 3.5 monkeypatch üretimi)
    r_mm = client.get("/api/music/models", headers=auth_headers)
    assert r_mm.status_code == 200
    ids = [m["id"] for m in r_mm.json()["models"]]
    assert "lyria-3.5" in ids and "elevenlabs-music" in ids and "stable-audio-2" in ids and "replicate-musicgen" in ids

    r_no_key = client.post("/api/music/generate", headers=auth_headers, json={"model_id": "lyria-3.5", "prompt": "Epik piyano bestesi"})
    assert r_no_key.status_code == 400 and "GEMINI_API_KEY" in r_no_key.json()["detail"]

    r_mk = client.post("/api/music/config", headers=auth_headers, json={"GEMINI_API_KEY": "fake-gemini-key-test"})
    assert r_mk.status_code == 200
    assert ((tmp_path / ".music_secrets.json").stat().st_mode & 0o777) == 0o600

    monkeypatch.setattr(ms, "_generate_google_lyria", lambda mid, key, prompt: (b"ID3" + b"\x00" * 2048, "mp3", "[Verse 1]\nFabrika sahnede"))
    r_mg = client.post("/api/music/generate", headers=auth_headers, json={"model_id": "lyria-3.5", "prompt": "Sinematik piyano ve yaylılar", "duration_sec": 30})
    assert r_mg.status_code == 200
    jid = r_mg.json()["job"]["job_id"]
    son_job = None
    for _ in range(30):
        time.sleep(0.05)
        rj = client.get(f"/api/music/job/{jid}", headers=auth_headers)
        son_job = rj.json()["job"]
        if son_job["status"] == "completed":
            break
    assert son_job is not None and son_job["status"] == "completed"
    assert son_job["audio_url"] and son_job["audio_url"].startswith("/api/media/file?path=mus_")
    assert client.get(son_job["audio_url"], headers=auth_headers).status_code == 200
    r_mh = client.get("/api/music/history", headers=auth_headers)
    assert r_mh.status_code == 200 and any(x["job_id"] == jid for x in r_mh.json()["items"])

















def test_v32_api_waterfall_leaked_and_quota_failover(client, auth_headers, monkeypatch, tmp_path):
    """v32: Çoklu hesap API şelalesi — 403 sızdırılmış ve 429 kota dolu anahtarları atlar, sıradaki hesaba geçer."""
    import time
    import api_waterfall as aw
    import main as main_mod
    import music_studio as ms

    aw.reset_all_health()
    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_mod, "MEDIA_DIR", tmp_path / "media")

    env_map = {
        "GEMINI_API_KEY": "leaked-key-0",
        "GEMINI_API_KEY_1": "quota-key-1",
        "GEMINI_API_KEY_2": "working-key-2",
        "ELEVENLABS_API_KEY": "el-working-key",
    }
    monkeypatch.setattr(main_mod, "get_secret_from_env", lambda k: env_map.get(k))

    denenen_keys = []

    def _fake_lyria(model_id, api_key, prompt):
        denenen_keys.append(api_key)
        if api_key == "leaked-key-0":
            raise aw.WaterfallProviderError(403, 'Your API key was reported as leaked. Please use another API key.')
        if api_key == "quota-key-1":
            raise aw.WaterfallProviderError(429, 'RESOURCE_EXHAUSTED: quota exceeded')
        return (b"ID3" + b"\x00" * 2048, "mp3", "[Chorus]\nŞelale Çalıştı")

    monkeypatch.setattr(ms, "_generate_google_lyria", _fake_lyria)

    # 1. İlk çağrı: leaked-key-0 (403) -> quota-key-1 (429) -> working-key-2 (BAŞARI)
    r1 = client.post("/api/music/generate", headers=auth_headers, json={"model_id": "lyria-3.5", "prompt": "Şelale testi"})
    assert r1.status_code == 200
    jid1 = r1.json()["job"]["job_id"]
    j1 = None
    for _ in range(30):
        time.sleep(0.04)
        j1 = client.get(f"/api/music/job/{jid1}", headers=auth_headers).json()["job"]
        if j1["status"] == "completed":
            break
    assert j1 is not None and j1["status"] == "completed"
    assert j1["used_key_label"] == "GEMINI_API_KEY_2"
    assert denenen_keys == ["leaked-key-0", "quota-key-1", "working-key-2"]

    # 2. İkinci çağrı: engelli & soğumadaki anahtarları hiç çağırmadan doğrudan GEMINI_API_KEY_2'yi kullanmalı
    denenen_keys.clear()
    r2 = client.post("/api/music/generate", headers=auth_headers, json={"model_id": "lyria-3.5", "prompt": "İkinci parça"})
    assert r2.status_code == 200
    jid2 = r2.json()["job"]["job_id"]
    j2 = None
    for _ in range(30):
        time.sleep(0.04)
        j2 = client.get(f"/api/music/job/{jid2}", headers=auth_headers).json()["job"]
        if j2["status"] == "completed":
            break
    assert j2 is not None and j2["status"] == "completed"
    assert denenen_keys == ["working-key-2"]

    # 3. /api/music/waterfall ham anahtar sızdırmadan sağlık raporunu döner
    rwf = client.get("/api/music/waterfall", headers=auth_headers)
    assert rwf.status_code == 200
    wf_txt = rwf.text
    for secret in env_map.values():
        assert secret not in wf_txt
    gem_wf = rwf.json()["providers"]["GEMINI_API_KEY"]
    assert gem_wf["total_keys"] == 3 and gem_wf["healthy_keys"] == 1 and gem_wf["leaked_or_invalid_keys"] == 1 and gem_wf["cooldown_keys"] == 1

    # 4. Çapraz model auto_waterfall: tüm Gemini anahtarları başarısız olursa ElevenLabs'e geçer
    monkeypatch.setattr(ms, "_generate_google_lyria", lambda mid, k, p: (_ for _ in ()).throw(aw.WaterfallProviderError(403, "paid tier required")))
    monkeypatch.setattr(ms, "_generate_elevenlabs_music", lambda k, p, d: (b"ID3" + b"\x01" * 2048, "mp3", ""))
    r3 = client.post("/api/music/generate", headers=auth_headers, json={"model_id": "auto_waterfall", "prompt": "Otomatik şelale"})
    assert r3.status_code == 200
    jid3 = r3.json()["job"]["job_id"]
    j3 = None
    for _ in range(30):
        time.sleep(0.04)
        j3 = client.get(f"/api/music/job/{jid3}", headers=auth_headers).json()["job"]
        if j3["status"] == "completed":
            break
    assert j3 is not None and j3["status"] == "completed"
    assert j3["model_id"] == "elevenlabs-music" and j3["used_key_label"] == "ELEVENLABS_API_KEY"

    # 5. Şelale sıfırlama ucu + panelden çoklu satır anahtar ekleme
    r_rst = client.post("/api/music/waterfall/reset", headers=auth_headers)
    assert r_rst.status_code == 200 and r_rst.json()["providers"]["GEMINI_API_KEY"]["healthy_keys"] if "providers" in r_rst.json() else r_rst.json()["waterfall"]["providers"]["GEMINI_API_KEY"]["healthy_keys"] == 3
    r_cfg = client.post(
        "/api/music/config",
        headers=auth_headers,
        json={"append": True, "GEMINI_API_KEY": "panel-key-a\npanel-key-b"},
    )
    assert r_cfg.status_code == 200 and r_cfg.json()["waterfall"]["providers"]["GEMINI_API_KEY"]["total_keys"] == 5
    aw.reset_all_health()


def test_v33_locked_camera_real_tts_kaggle_music_and_button_audit(client, auth_headers, monkeypatch, tmp_path):
    """v33: Sabit kadrajda sıfır kamera kayması, Gemini 3.8 + Edge TTS, Kaggle GPU MusicGen ve tüm buton uçları."""
    import struct
    import wave
    import hyperframes_motor as hf
    import ai_video_montaj as avm
    import gemini_audio as ga
    import gpu_worker as gw
    import main as main_mod
    import music_studio as ms

    # 1. Sabit kadraj (`wind_cloth_glow` / `locked` / `static` / `sabit`) kesinlikle z='1.0' olmalı, aşağı/yukarı kaymamalı!
    for locked_mode in ("wind_cloth_glow", "locked", "static", "sabit"):
        filt = hf._kamera_filtre_ifadesi(locked_mode, 150, 1280, 720)
        assert "zoompan=z='1.0':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'" in filt
        assert "cos(" not in filt and "sin(" not in filt and "on/" not in filt

    avm_src = (Path(__file__).resolve().parent.parent / "ai_video_montaj.py").read_text(encoding="utf-8")
    assert 'mod in ("wind_cloth_glow", "locked", "static", "sabit")' in avm_src
    vr_src = (Path(__file__).resolve().parent.parent / "video_render.py").read_text(encoding="utf-8")
    assert "anullsrc=r=44100:cl=mono" in vr_src
    assert "sine=frequency=" not in vr_src

    # 2. Gemini 3.8 Flash TTS + ücretsiz Edge Neural TTS yedeği (eski 2.5 preview kapalı!)
    ga_src = (Path(__file__).resolve().parent.parent / "gemini_audio.py").read_text(encoding="utf-8")
    assert "gemini-3.8-flash-tts" in ga_src
    assert "gemini-2.5-flash-preview-tts" not in ga_src
    assert "edge_tts" in ga_src

    # voice_clone_tts tüm gerçek TTS motorları çökerse sahte sinüs/chiptune bip sesi DÖNMEMELİ!
    monkeypatch.setattr(ga, "synthesize_gemini_speech", lambda *a, **k: (None, 0.0))
    orig_isfile = os.path.isfile
    monkeypatch.setattr(main_mod.os.path, "isfile", lambda p: False if str(p) == "/usr/bin/say" else orig_isfile(p))
    r_tts_fail = client.post(
        "/api/audio/process",
        headers=auth_headers,
        json={"action": "voice_clone_tts", "params": {"prompt": "Merhaba dünya", "voice": "Aoede"}},
    )
    assert r_tts_fail.status_code == 200
    assert r_tts_fail.json()["success"] is False
    assert "sahte bip" in r_tts_fail.json()["detail"].lower() or "yanıt vermedi" in r_tts_fail.json()["detail"].lower()

    # 3. Kaggle GPU Ücretsiz Yerel AI Müzik (MusicGen) tam uçtan uca turu:
    #    POST /api/music/generate (gpu-musicgen) → GET /api/worker/claim?mod=musicgen → POST /api/worker/upload (audio) → GET /api/music/job/{id}
    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    ms._MUSIC_JOBS.clear()
    r_models = client.get("/api/music/models", headers=auth_headers)
    assert r_models.status_code == 200
    model_ids = [m["id"] for m in r_models.json()["models"]]
    assert "gpu-musicgen" in model_ids

    r_gen = client.post(
        "/api/music/generate",
        headers=auth_headers,
        json={"model_id": "gpu-musicgen", "prompt": "Epik orkestra ve elektronik synth", "duration_sec": 15},
    )
    assert r_gen.status_code == 200
    mjob = r_gen.json()["job"]
    mjid = mjob["job_id"]
    assert mjob["status"] == "queued_gpu"

    # Video stüdyosu kuyruğunda müzik işi görünmemeli
    r_vq = client.get("/api/studio/queue", headers=auth_headers)
    assert r_vq.status_code == 200
    assert all(it.get("job_id") != mjid for it in r_vq.json()["items"])

    # GPU işçisi `?mod=musicgen` ile işi çekmeli
    wh = {"X-Worker-Key": main_mod.get_worker_key()}
    r_claim = client.get("/api/worker/claim?worker_id=kaggle_t4_music&mod=musicgen", headers=wh)
    assert r_claim.status_code == 200
    claimed = r_claim.json()["job"]
    assert claimed is not None and claimed["job_id"] == mjid
    assert claimed["method"] == "musicgen"

    # İlerleme bildirimi `/api/music/job/{id}` içine yansımalı
    r_prog = client.post(
        "/api/worker/progress",
        headers=wh,
        json={"job_id": mjid, "progress_pct": 55, "stage": "MusicGen 32kHz üretiliyor"},
    )
    assert r_prog.status_code == 200
    r_poll_mid = client.get(f"/api/music/job/{mjid}", headers=auth_headers)
    assert r_poll_mid.status_code == 200
    assert r_poll_mid.json()["job"]["progress_pct"] == 55

    # Gerçek WAV oluştur ve `/api/worker/upload` ile `media_type="audio"` olarak yükle
    wav_file = tmp_path / f"{mjid}.wav"
    with wave.open(str(wav_file), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(32000)
        wf.writeframes(struct.pack("<hh", 0, 0) * 1600)

    uploaded_media = main_mod.MEDIA_DIR / f"{mjid}.wav"
    try:
        r_up = client.post(
            "/api/worker/upload",
            headers=wh,
            data={"job_id": mjid, "media_type": "audio"},
            files={"file": (f"{mjid}.wav", wav_file.read_bytes(), "audio/wav")},
        )
        assert r_up.status_code == 200
        up_json = r_up.json()
        assert up_json["success"] is True and up_json["media_type"] == "audio"
        assert up_json["audio_url"] == f"/api/media/file?path={mjid}.wav"

        r_poll_done = client.get(f"/api/music/job/{mjid}", headers=auth_headers)
        assert r_poll_done.status_code == 200
        done_job = r_poll_done.json()["job"]
        assert done_job["status"] == "completed"
        assert done_job["audio_url"] == f"/api/media/file?path={mjid}.wav"

        r_dl = client.get(done_job["audio_url"], headers=auth_headers)
        assert r_dl.status_code == 200 and r_dl.content[:4] == b"RIFF"

        r_hist = client.get("/api/music/history", headers=auth_headers)
        assert r_hist.status_code == 200
        assert any(it["job_id"] == mjid for it in r_hist.json()["items"])
    finally:
        uploaded_media.unlink(missing_ok=True)

    # 4. gpu_worker.py MusicGen sabitleri ve fonksiyonu doğrulanmalı
    assert gw.MUSICGEN_MEDIUM == "facebook/musicgen-medium"
    assert callable(gw.muzik_uret)

    # 5. Bilinmeyen `/api/*` uçları index.html 200 yerine JSON 404 dönmeli
    r_404 = client.get("/api/olmayan_bir_uc_v33")
    assert r_404.status_code == 404
    assert "detail" in r_404.json()

    # 6. Sayfa & buton bütünlüğü kontrolleri (HTML + JS + 4 adım tutarlılığı)
    root_dir = Path(__file__).resolve().parent.parent / "static"
    idx_html = (root_dir / "index.html").read_text(encoding="utf-8")
    assert "Dört mekanik adımda" in idx_html
    assert "Beş mekanik adımda" not in idx_html
    fab_js = (root_dir / "fabrika_desktop.js").read_text(encoding="utf-8")
    assert "Mac Fabrika masaüstü bağlı değil" in fab_js
    app_js = (root_dir / "app.js").read_text(encoding="utf-8")
    assert "event.code === 4403" in app_js
    assert "VAPID anahtarı tanımlı değil" in app_js
    lab_html = (root_dir / "lab.html").read_text(encoding="utf-8")
    assert "switchStudioView('audio')" in lab_html
    assert "Gemini 3.8" in lab_html

    # 7. Tüm ana sayfalar ve buton arkası GET uçları 200 dönmeli (kırık uç yok)
    for page_path in ("/", "/lab.html", "/fabrika", "/panel", "/Fabrika_GPU_Renderer.ipynb", "/surum.json"):
        rp = client.get(page_path)
        assert rp.status_code == 200, f"{page_path} failed: {rp.status_code}"
    for api_path in (
        "/api/auth/public_info",
        "/api/burc/list",
        "/api/music/models",
        "/api/music/waterfall",
        "/api/music/history",
        "/api/studio/queue",
        "/api/audio/history",
        "/api/gpu/cluster/status",
        "/api/youtube/status",
        "/api/channels",
        "/api/admin/users",
        "/api/contact/messages",
        "/api/contact/recipients",
        "/api/bridge/status",
        "/api/links/pool",
        "/api/system/stats",
        "/api/rea/history",
    ):
        ra = client.get(api_path, headers=auth_headers)
        assert ra.status_code == 200, f"{api_path} failed: {ra.status_code}"
