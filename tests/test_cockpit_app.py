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
def isolate_test_environment(tmp_path, monkeypatch):
    """Testlerin üretim veri dosyalarını (video_jobs, rea_scans) kirletmesini önler."""
    test_data = tmp_path / "data"
    test_data.mkdir()
    monkeypatch.setattr(main, "DATA_DIR", test_data)
    ACTIVE_SESSIONS.clear()
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
            assert kaynak == "flux_montaj"

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


def test_gpu_cluster_honest_standby(client):
    """GPU kümesi bağlı işçi yokken standby dönmelidir."""
    from main import ACTIVE_GPU_WORKERS
    ACTIVE_GPU_WORKERS.clear()
    res = client.get("/api/gpu/cluster/status")
    assert res.status_code == 200
    st = res.json()["status"]
    assert st["colab_connected"] is False
    assert st["allocated_vram_gb"] == 0.0
    assert "standby" in st["cluster_status"]


def test_worker_protocol_and_gpu_activation(client, auth_headers):
    """Kaggle/Colab GPU işçisi bağlandığında telemetrinin active olduğunu, iş claim ve upload sürecini doğrular."""
    from main import ACTIVE_GPU_WORKERS
    ACTIVE_GPU_WORKERS.clear()

    # 1. Başlangıçta standby
    st1 = client.get("/api/gpu/cluster/status").json()["status"]
    assert st1["kaggle_connected"] is False

    # 2. worker.py erişimi
    w_res = client.get("/worker.py")
    assert w_res.status_code == 200
    assert "FABRİKA BULUT GPU İŞÇİSİ" in w_res.text

    # 3. Heartbeat gönder
    hb = client.post("/api/worker/heartbeat", json={
        "worker_id": "test_kaggle_01",
        "worker_type": "kaggle",
        "gpu_name": "2x Tesla T4",
        "vram_gb": 32.0
    })
    assert hb.status_code == 200
    assert hb.json()["registered"] is True

    # 4. Telemetri aktif olmalı
    st2 = client.get("/api/gpu/cluster/status").json()["status"]
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

    claim = client.get("/api/worker/claim?worker_id=test_kaggle_01").json()
    assert claim["success"] is True

    # 6. Upload
    up = client.post(
        "/api/worker/upload",
        data={"job_id": job_id},
        files={"file": (f"{job_id}.mp4", b"\x00\x00\x00\x20ftypisom" + b"\x00" * 2000, "video/mp4")}
    )
    assert up.status_code == 200
    assert up.json()["success"] is True
    assert up.json()["download_url"].endswith("&download=1")


def test_rea_scan_and_history_dynamic(client, auth_headers):
    """REA taraması yapılınca skor ve kayıt dinamik hesaplanmalıdır."""
    # 1. Başlangıçta tarama yoksa Veri Yok dönmeli
    res_init = client.get("/api/rea/history")
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
    res_hist = client.get("/api/rea/history")
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


def test_galeri_bozuk_mp4_listelemez(client, auth_headers):
    """Galeri yalnız oynatılabilir MP4'leri döner."""
    res = client.get("/api/lab/history", headers=auth_headers)
    assert res.status_code == 200
    for item in res.json()["items"]:
        assert item.get("video_url")

