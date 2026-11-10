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
    """Video üretim isteği gerçek indirilebilir MP4 ve Kural 1 dürüst önizleme etiketi dönmelidir."""
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
        assert "simülasyon" in task["status"]
        assert task["simulasyon"] is True
        assert task["output_url"] == f"/api/media/file?path={job_id}.mp4"
        assert task["download_url"] == f"/api/media/file?path={job_id}.mp4&download=1"
        assert mp4_path.exists() and mp4_path.stat().st_size > 1000

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
