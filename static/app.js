// Fabrika PWA — Oil UI 3-Tema Motoru, Bento Grid, Link Havuzu, Alancf/alanadisifre & Face ID Yöneticisi
let ws = null;
let reconnectInterval = 2000;
let vapidPublicKey = null;
let authToken = localStorage.getItem('fabrika_token') || null;
let currentPin = '';
let activeAuthMode = 'password'; // 'password' | 'pin'
let currentLinkCategory = 'all';
const PIN_LENGTH = 6;

// 1. Sayfa Başlatma, Tema, Canvas Shader ve Kimlik Denetimi
document.addEventListener('DOMContentLoaded', async () => {
  initOilUiThemeEngine();
  initBackgroundShaderCanvas();
  initSpotlightCards();
  initAuthModeTabs();
  initCredentialsFormEvents();
  initNumpadEvents();
  initChangePinEvents();
  initUIEvents();
  initLinkPoolExplorer();
  initCommandPalette();
  updateBiometricStatusButton();
  await fetchPublicAuthInfo();

  if (authToken) {
    try {
      const res = await fetch('/api/auth/check', {
        headers: { 'Authorization': `Bearer ${authToken}` }
      });
      const data = await res.json();
      if (data.authenticated) {
        hidePinModal();
        startApp();
        return;
      }
    } catch (e) {
      console.warn('Oturum kontrolü yapılamadı:', e);
    }
    authToken = null;
    localStorage.removeItem('fabrika_token');
  }

  showPinModal();
});

function startApp() {
  initWebSocket();
  initServiceWorker();
  fetchSystemStats();
  setInterval(fetchSystemStats, 15000);
}

// 1.2 Oil UI (#164) 3-Yönlü Canlı Tema Motoru
function initOilUiThemeEngine() {
  const savedTheme = localStorage.getItem('fabrika_oil_theme') || 'cyber_hud';
  applyOilTheme(savedTheme);

  document.querySelectorAll('[data-set-theme]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const t = btn.getAttribute('data-set-theme');
      if (t) applyOilTheme(t);
    });
  });
}

function applyOilTheme(themeName) {
  document.documentElement.setAttribute('data-theme', themeName);
  localStorage.setItem('fabrika_oil_theme', themeName);
  document.querySelectorAll('[data-set-theme]').forEach((btn) => {
    if (btn.getAttribute('data-set-theme') === themeName) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });
}

// 1.4 Link #103 (Canvas UI & Paper Shaders) Canlı Sinirsel Arka Plan
function initBackgroundShaderCanvas() {
  const canvas = document.getElementById('bgShaderCanvas');
  if (!canvas || !canvas.getContext) return;
  const ctx = canvas.getContext('2d');
  let width = (canvas.width = window.innerWidth);
  let height = (canvas.height = window.innerHeight);

  window.addEventListener('resize', () => {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  });

  const nodes = Array.from({ length: 34 }, () => ({
    x: Math.random() * width,
    y: Math.random() * height,
    vx: (Math.random() - 0.5) * 0.45,
    vy: (Math.random() - 0.5) * 0.45,
    r: Math.random() * 1.8 + 0.8
  }));

  function render() {
    ctx.clearRect(0, 0, width, height);
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      n.x += n.vx;
      n.y += n.vy;
      if (n.x < 0 || n.x > width) n.vx *= -1;
      if (n.y < 0 || n.y > height) n.vy *= -1;

      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(0, 242, 254, 0.35)';
      ctx.fill();

      for (let j = i + 1; j < nodes.length; j++) {
        const m = nodes[j];
        const dx = n.x - m.x;
        const dy = n.y - m.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 140) {
          ctx.beginPath();
          ctx.moveTo(n.x, n.y);
          ctx.lineTo(m.x, m.y);
          ctx.strokeStyle = `rgba(0, 242, 254, ${(1 - dist / 140) * 0.12})`;
          ctx.lineWidth = 0.8;
          ctx.stroke();
        }
      }
    }
    requestAnimationFrame(render);
  }
  requestAnimationFrame(render);
}

// 1.6 Link #103 (Cursify) & #186 (21st.dev) Spotlight Kart Efektleri
function initSpotlightCards() {
  document.addEventListener('mousemove', (e) => {
    document.querySelectorAll('.spotlight-card').forEach((card) => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      card.style.setProperty('--mouse-x', `${x}px`);
      card.style.setProperty('--mouse-y', `${y}px`);
    });
  });
}

async function fetchPublicAuthInfo() {
  try {
    const res = await fetch('/api/auth/public_info');
    if (!res.ok) return;
    const data = await res.json();
    const userInp = document.getElementById('inputLoginUsername');
    const savedUser = localStorage.getItem('fabrika_username');
    if (userInp && !savedUser && data.default_username) {
      userInp.value = data.default_username;
    }
  } catch (e) {}
}

// 2. Yetkilendirilmiş Güvenli İstek Yardımcısı (authFetch)
async function authFetch(url, options = {}) {
  options.headers = options.headers || {};
  if (authToken) {
    if (options.headers instanceof Headers) {
      options.headers.set('Authorization', `Bearer ${authToken}`);
    } else {
      options.headers['Authorization'] = `Bearer ${authToken}`;
    }
  }
  const res = await fetch(url, options);
  if (res.status === 401) {
    logout(false);
  }
  return res;
}

// 2.5 Giriş Modu Sekmeleri
function initAuthModeTabs() {
  const tabPassword = document.getElementById('tabBtnPassword');
  const tabPin = document.getElementById('tabBtnPin');
  const btnOpenGate = document.getElementById('btnOpenLoginGate');

  if (tabPassword) {
    tabPassword.addEventListener('click', () => switchAuthMode('password'));
  }
  if (tabPin) {
    tabPin.addEventListener('click', () => switchAuthMode('pin'));
  }
  if (btnOpenGate) {
    btnOpenGate.addEventListener('click', () => {
      switchAuthMode('password');
      const passInput = document.getElementById('inputLoginPassword');
      if (passInput) passInput.focus();
    });
  }
}

function switchAuthMode(mode) {
  activeAuthMode = mode;
  const tabPassword = document.getElementById('tabBtnPassword');
  const tabPin = document.getElementById('tabBtnPin');
  const credForm = document.getElementById('loginCredentialsForm');
  const pinContainer = document.getElementById('pinModeContainer');
  const statusEl = document.getElementById('pinStatusMsg');

  if (statusEl) {
    statusEl.textContent = '';
    statusEl.className = 'pin-status-msg';
  }

  if (mode === 'pin') {
    if (tabPassword) tabPassword.classList.remove('active');
    if (tabPin) tabPin.classList.add('active');
    if (credForm) credForm.style.display = 'none';
    if (pinContainer) pinContainer.style.display = 'block';
  } else {
    if (tabPin) tabPin.classList.remove('active');
    if (tabPassword) tabPassword.classList.add('active');
    if (pinContainer) pinContainer.style.display = 'none';
    if (credForm) credForm.style.display = 'flex';
  }
}

// 2.8 Kullanıcı Adı & Şifre (.env alanadisifre / Alancf) Giriş Olayları
function initCredentialsFormEvents() {
  const form = document.getElementById('loginCredentialsForm');
  const userInp = document.getElementById('inputLoginUsername');
  const passInp = document.getElementById('inputLoginPassword');
  const toggleBtn = document.getElementById('btnTogglePassVis');

  const savedUser = localStorage.getItem('fabrika_username');
  if (savedUser && userInp) {
    userInp.value = savedUser;
  }

  if (toggleBtn && passInp) {
    toggleBtn.addEventListener('click', (e) => {
      e.preventDefault();
      if (passInp.type === 'password') {
        passInp.type = 'text';
        toggleBtn.textContent = '🙈';
      } else {
        passInp.type = 'password';
        toggleBtn.textContent = '👁️';
      }
    });
  }

  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      await submitCredentialsLogin(false);
    });
  }
}

async function submitCredentialsLogin(enrollBiometricAfter = false) {
  const userInp = document.getElementById('inputLoginUsername');
  const passInp = document.getElementById('inputLoginPassword');
  const statusEl = document.getElementById('pinStatusMsg');

  const username = userInp ? userInp.value.trim() : 'yusuf';
  const password = passInp ? passInp.value.trim() : '';

  if (!password) {
    triggerPinError('Lütfen .env içerisindeki alanadisifre şifrenizi girin.');
    if (passInp) passInp.focus();
    return false;
  }

  if (statusEl) {
    statusEl.textContent = 'Şifre doğrulanıyor...';
    statusEl.className = 'pin-status-msg';
  }

  try {
    let res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });

    // Arka plandaki eski sunucu süreci henüz yeniden başlatılmadıysa /api/auth/verify_pin üzerinden doğrula
    if (res.status === 404) {
      res = await fetch('/api/auth/verify_pin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: password })
      });
    }

    const data = await res.json();

    if (res.ok && data.success && data.token) {
      authToken = data.token;
      localStorage.setItem('fabrika_token', authToken);
      if (username) localStorage.setItem('fabrika_username', username);
      if (passInp) passInp.value = '';

      if (enrollBiometricAfter) {
        await enrollBiometricsDuringLogin();
      }

      if (statusEl) {
        statusEl.textContent = '✅ Giriş Başarılı! Yönlendiriliyorsunuz...';
        statusEl.className = 'pin-status-msg success';
      }
      setTimeout(() => {
        hidePinModal();
        startApp();
      }, 300);
      return true;
    } else {
      triggerPinError(data.detail || 'Hatalı kullanıcı adı veya şifre!');
      return false;
    }
  } catch (err) {
    triggerPinError('Bağlantı hatası: ' + err.message);
    return false;
  }
}

// 3. PIN Giriş, Numpad ve Biyometrik (Face ID) Olayları
function initNumpadEvents() {
  document.querySelectorAll('.numpad-key').forEach((keyBtn) => {
    keyBtn.addEventListener('click', (e) => {
      e.preventDefault();
      const key = keyBtn.getAttribute('data-key');
      if (key === 'clear') {
        handlePinClear();
      } else if (key === 'backspace') {
        handlePinBackspace();
      } else if (key !== null) {
        handlePinInput(key);
      }
    });
  });

  window.addEventListener('keydown', (e) => {
    const overlay = document.getElementById('pinModalOverlay');
    if (!overlay || !overlay.classList.contains('active')) return;
    if (activeAuthMode !== 'pin') return;
    if (document.activeElement && ['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;

    if (e.key >= '0' && e.key <= '9') {
      handlePinInput(e.key);
    } else if (e.key === 'Backspace') {
      handlePinBackspace();
    } else if (e.key === 'Escape' || e.key.toLowerCase() === 'c') {
      handlePinClear();
    }
  });

  const btnFaceId = document.getElementById('btnFaceIdLogin');
  if (btnFaceId) {
    btnFaceId.addEventListener('click', (e) => {
      e.preventDefault();
      triggerBiometricLogin();
    });
  }
}

function showPinModal(msg = '') {
  const overlay = document.getElementById('pinModalOverlay');
  if (overlay) overlay.classList.add('active');
  currentPin = '';
  updatePinDots();
  const statusEl = document.getElementById('pinStatusMsg');
  if (statusEl) {
    statusEl.textContent = msg;
    statusEl.className = 'pin-status-msg';
  }
  checkAndShowBiometricOption();
}

function hidePinModal() {
  const overlay = document.getElementById('pinModalOverlay');
  if (overlay) overlay.classList.remove('active');
  currentPin = '';
  updatePinDots();
}

function updatePinDots() {
  const dots = document.querySelectorAll('.pin-dot');
  dots.forEach((dot, idx) => {
    if (idx < currentPin.length) {
      dot.classList.add('filled');
      dot.classList.remove('error');
    } else {
      dot.classList.remove('filled', 'error');
    }
  });
}

async function handlePinInput(digit) {
  if (currentPin.length >= PIN_LENGTH) return;
  currentPin += digit;
  updatePinDots();

  if (currentPin.length === PIN_LENGTH) {
    await submitPin();
  }
}

function handlePinBackspace() {
  if (currentPin.length > 0) {
    currentPin = currentPin.slice(0, -1);
    updatePinDots();
    const statusEl = document.getElementById('pinStatusMsg');
    if (statusEl && statusEl.textContent !== 'Doğrulanıyor...') {
      statusEl.textContent = '';
    }
  }
}

function handlePinClear() {
  currentPin = '';
  updatePinDots();
  const statusEl = document.getElementById('pinStatusMsg');
  if (statusEl) statusEl.textContent = '';
}

async function submitPin() {
  const statusEl = document.getElementById('pinStatusMsg');
  if (statusEl) {
    statusEl.textContent = 'Doğrulanıyor...';
    statusEl.className = 'pin-status-msg';
  }

  try {
    const res = await fetch('/api/auth/verify_pin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin: currentPin })
    });
    const data = await res.json();

    if (res.ok && data.success && data.token) {
      authToken = data.token;
      localStorage.setItem('fabrika_token', authToken);
      if (statusEl) {
        statusEl.textContent = '✅ Giriş Başarılı';
        statusEl.className = 'pin-status-msg success';
      }
      setTimeout(() => {
        hidePinModal();
        startApp();
      }, 350);
    } else {
      triggerPinError(data.detail || 'Hatalı PIN kodu!');
    }
  } catch (err) {
    triggerPinError('Bağlantı hatası: ' + err.message);
  }
}

function triggerPinError(msg) {
  const statusEl = document.getElementById('pinStatusMsg');
  const card = document.getElementById('pinCard');
  const dots = document.querySelectorAll('.pin-dot');

  if (statusEl) {
    statusEl.textContent = msg;
    statusEl.className = 'pin-status-msg';
  }

  dots.forEach(d => d.classList.add('error'));
  if (card) {
    card.classList.remove('shake');
    void card.offsetWidth;
    card.classList.add('shake');
  }

  setTimeout(() => {
    currentPin = '';
    updatePinDots();
  }, 750);
}

// 4. Face ID / Biyometrik Kilit Yönetimi
function checkAndShowBiometricOption() {
  const bioBox = document.getElementById('pinBiometricBox');
  const btnFaceId = document.getElementById('btnFaceIdLogin');
  const bioId = localStorage.getItem('fabrika_biometric_id');
  const bioSecret = localStorage.getItem('fabrika_biometric_secret');

  if (bioBox) {
    bioBox.style.display = 'flex';
  }
  if (btnFaceId) {
    if (bioId && bioSecret) {
      btnFaceId.innerHTML = '<span class="face-icon">👤</span> Yüz Kilidi (Face ID / Touch ID) ile Gir';
    } else {
      btnFaceId.innerHTML = '<span class="face-icon">👤</span> Yüz Kilidi (Face ID / Touch ID) Kur ve Gir';
    }
  }
}

async function enrollBiometricsDuringLogin() {
  if (!window.PublicKeyCredential || !authToken) return false;
  try {
    const isAvail = await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
    if (!isAvail) return false;

    const challenge = new Uint8Array(32);
    window.crypto.getRandomValues(challenge);
    const userId = new Uint8Array(16);
    window.crypto.getRandomValues(userId);

    await navigator.credentials.create({
      publicKey: {
        challenge: challenge,
        rp: { name: 'yusasufhin.com — Fabrika HUD' },
        user: {
          id: userId,
          name: localStorage.getItem('fabrika_username') || 'yusuf',
          displayName: 'Yusuf Şahin'
        },
        pubKeyCredParams: [
          { type: 'public-key', alg: -7 },
          { type: 'public-key', alg: -257 }
        ],
        authenticatorSelection: {
          authenticatorAttachment: 'platform',
          userVerification: 'required'
        },
        timeout: 60000
      }
    });

    const res = await authFetch('/api/auth/biometric/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_name: navigator.userAgent.includes('iPhone') ? 'iPhone Face ID' : (navigator.userAgent.includes('Macintosh') ? 'Mac Touch ID' : 'Mobil Cihaz')
      })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      localStorage.setItem('fabrika_biometric_id', data.bio_id);
      localStorage.setItem('fabrika_biometric_secret', data.bio_secret);
      updateBiometricStatusButton();
      checkAndShowBiometricOption();
      return true;
    }
  } catch (e) {
    console.warn('Face ID kurulumu atlandı:', e);
  }
  return false;
}

async function triggerBiometricLogin() {
  const bioId = localStorage.getItem('fabrika_biometric_id');
  const bioSecret = localStorage.getItem('fabrika_biometric_secret');
  const statusEl = document.getElementById('pinStatusMsg');
  const passInp = document.getElementById('inputLoginPassword');

  if (!bioId || !bioSecret) {
    if (passInp && passInp.value.trim()) {
      await submitCredentialsLogin(true);
      return;
    }
    switchAuthMode('password');
    if (statusEl) {
      statusEl.textContent = 'İlk kullanım için şifrenizi (alanadisifre) yazıp tekrar Yüz Kilidi butonuna dokunun.';
      statusEl.className = 'pin-status-msg';
    }
    if (passInp) passInp.focus();
    return;
  }

  if (statusEl) {
    statusEl.textContent = '👤 Yüz Kilidi (Face ID / Touch ID) taranıyor...';
    statusEl.className = 'pin-status-msg';
  }

  try {
    if (window.PublicKeyCredential) {
      try {
        const challenge = new Uint8Array(32);
        window.crypto.getRandomValues(challenge);
        await navigator.credentials.get({
          publicKey: {
            challenge: challenge,
            timeout: 60000,
            userVerification: 'required'
          }
        });
      } catch (credErr) {
        console.warn('Face ID doğrulaması iptal edildi veya başarısız:', credErr);
        if (statusEl) statusEl.textContent = 'Yüz Kilidi iptal edildi. Şifrenizle giriş yapabilirsiniz.';
        return;
      }
    }

    const res = await fetch('/api/auth/biometric/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bio_id: bioId, bio_secret: bioSecret })
    });
    const data = await res.json();

    if (res.ok && data.success && data.token) {
      authToken = data.token;
      localStorage.setItem('fabrika_token', authToken);
      if (statusEl) {
        statusEl.textContent = '✅ Yüz Kilidi Doğrulandı!';
        statusEl.className = 'pin-status-msg success';
      }
      setTimeout(() => {
        hidePinModal();
        startApp();
      }, 350);
    } else {
      triggerPinError(data.detail || 'Biyometrik doğrulama başarısız!');
    }
  } catch (err) {
    triggerPinError('Biyometrik hata: ' + err.message);
  }
}

function updateBiometricStatusButton() {
  const btn = document.getElementById('btnToggleBiometrics');
  const bioId = localStorage.getItem('fabrika_biometric_id');
  if (btn) {
    if (bioId) {
      btn.innerHTML = '<span>✅</span> Face ID Aktif (Kapat)';
      btn.style.borderColor = 'rgba(16, 185, 129, 0.4)';
      btn.style.color = 'var(--accent-green)';
    } else {
      btn.innerHTML = '<span>👤</span> Face ID / Biyometrik Kilit';
      btn.style.borderColor = '';
      btn.style.color = '';
    }
  }
}

async function toggleBiometrics() {
  const bioId = localStorage.getItem('fabrika_biometric_id');

  if (bioId) {
    if (confirm('Face ID bu cihazda zaten etkin. Devre dışı bırakmak istiyor musunuz?')) {
      localStorage.removeItem('fabrika_biometric_id');
      localStorage.removeItem('fabrika_biometric_secret');
      updateBiometricStatusButton();
      checkAndShowBiometricOption();
      alert('Face ID biyometrik kilit devre dışı bırakıldı.');
    }
    return;
  }

  if (!window.PublicKeyCredential) {
    alert('Bu tarayıcı veya cihaz WebAuthn / Face ID biyometriğini desteklemiyor.');
    return;
  }

  try {
    const isAvail = await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
    if (!isAvail) {
      alert('Bu cihazda aktif bir Touch ID veya Face ID donanımı bulunamadı.');
      return;
    }

    const ok = await enrollBiometricsDuringLogin();
    if (ok) {
      alert('✅ Face ID / Yüz Kilidi başarıyla etkinleştirildi! Artık giriş ekranında tek dokunuşla açabilirsiniz.');
    } else {
      alert('Face ID kaydı tamamlanamadı.');
    }
  } catch (err) {
    console.warn('Biometric kayıt iptal / hata:', err);
    alert('Face ID kaydı tamamlanamadı: ' + err.message);
  }
}

// 5. Uygulama İçi PIN Değiştirme Olayları
function initChangePinEvents() {
  const modal = document.getElementById('changePinModal');
  const btnOpen = document.getElementById('btnOpenChangePin');
  const btnClose = document.getElementById('btnCloseChangePin');
  const btnCancel = document.getElementById('btnCancelChangePin');
  const btnSubmit = document.getElementById('btnSubmitChangePin');
  const statusEl = document.getElementById('pinChangeStatus');

  const inputOld = document.getElementById('inputOldPin');
  const inputNew = document.getElementById('inputNewPin');
  const inputConfirm = document.getElementById('inputNewPinConfirm');

  function openModal() {
    if (modal) {
      modal.style.display = 'flex';
      if (inputOld) inputOld.value = '';
      if (inputNew) inputNew.value = '';
      if (inputConfirm) inputConfirm.value = '';
      if (statusEl) {
        statusEl.textContent = '';
        statusEl.className = 'pin-change-status';
      }
      if (inputOld) inputOld.focus();
    }
  }

  function closeModal() {
    if (modal) modal.style.display = 'none';
  }

  if (btnOpen) btnOpen.addEventListener('click', openModal);
  if (btnClose) btnClose.addEventListener('click', closeModal);
  if (btnCancel) btnCancel.addEventListener('click', closeModal);

  if (btnSubmit) {
    btnSubmit.addEventListener('click', async () => {
      const oldPin = inputOld ? inputOld.value.trim() : '';
      const newPin = inputNew ? inputNew.value.trim() : '';
      const confirmPin = inputConfirm ? inputConfirm.value.trim() : '';

      if (!oldPin || oldPin.length < 4) {
        statusEl.textContent = 'Lütfen geçerli mevcut PIN kodunuzu girin.';
        statusEl.className = 'pin-change-status error';
        return;
      }

      if (!newPin || newPin.length < 4 || !/^\d+$/.test(newPin)) {
        statusEl.textContent = 'Yeni PIN en az 4 haneli rakamlardan oluşmalıdır.';
        statusEl.className = 'pin-change-status error';
        return;
      }

      if (newPin !== confirmPin) {
        statusEl.textContent = 'Yeni PIN ve PIN Tekrarı birbiriyle uyuşmuyor!';
        statusEl.className = 'pin-change-status error';
        return;
      }

      statusEl.textContent = 'Güncelleniyor...';
      statusEl.className = 'pin-change-status';

      try {
        const res = await authFetch('/api/auth/change_pin', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ old_pin: oldPin, new_pin: newPin })
        });
        const data = await res.json();

        if (res.ok && data.success) {
          authToken = data.token;
          localStorage.setItem('fabrika_token', authToken);
          statusEl.textContent = '✅ ' + (data.message || 'PIN başarıyla değiştirildi!');
          statusEl.className = 'pin-change-status success';
          setTimeout(() => {
            closeModal();
          }, 1200);
        } else {
          statusEl.textContent = '❌ ' + (data.detail || 'Hata oluştu!');
          statusEl.className = 'pin-change-status error';
        }
      } catch (err) {
        statusEl.textContent = '❌ Bağlantı hatası: ' + err.message;
        statusEl.className = 'pin-change-status error';
      }
    });
  }
}

async function logout(callApi = true) {
  if (callApi && authToken) {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${authToken}` }
      });
    } catch (e) {}
  }
  authToken = null;
  localStorage.removeItem('fabrika_token');
  if (ws) {
    ws.close();
    ws = null;
  }
  showPinModal('Oturum kapatıldı. Şifreniz veya Yüz Kilidi ile giriş yapabilirsiniz.');
}

// 6. WebSocket Haberleşme Motoru
function initWebSocket() {
  if (!authToken) return;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/chat?token=${encodeURIComponent(authToken)}`;

  updateConnectionStatus('Bağlanıyor...', 'busy');

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    updateConnectionStatus('Bağlandı (Zero-Trust Korumalı)', 'online');
    reconnectInterval = 2000;
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleIncomingMessage(data);
    } catch (e) {
      appendMessage('agent', 'Fabrika', event.data);
    }
  };

  ws.onclose = (event) => {
    if (event.code === 4001) {
      logout(false);
      return;
    }
    updateConnectionStatus('Koptu, yeniden deneniyor...', 'busy');
    setTimeout(initWebSocket, reconnectInterval);
    reconnectInterval = Math.min(reconnectInterval * 1.5, 15000);
  };

  ws.onerror = (err) => {
    console.error('WebSocket hatası:', err);
  };
}

function updateConnectionStatus(text, status) {
  const pillText = document.getElementById('connStatusText');
  const pillDot = document.getElementById('connStatusDot');
  if (pillText) pillText.textContent = text;
  if (pillDot) {
    pillDot.className = `dot ${status}`;
    if (status === 'busy') {
      pillDot.style.backgroundColor = 'var(--accent-orange)';
    } else {
      pillDot.style.backgroundColor = 'var(--accent-green)';
    }
  }
}

function sendMessage() {
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text) return;

  appendMessage('user', 'Siz', text);
  input.value = '';

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'user_message', text: text }));
  } else {
    appendMessage('agent', 'Sistem', '⚠️ Sunucu bağlantısı kapalı, mesaj iletilemedi.');
  }
}

function handleIncomingMessage(msg) {
  if (msg.type === 'agent_reply') {
    appendMessage('agent', msg.sender || 'Fabrika Ajanı', msg.text, msg.action, msg.media);
  } else if (msg.type === 'system_alert') {
    appendMessage('agent', '⚡ Sistem Alarmı', msg.text);
  }
}

function appendMessage(role, sender, text, action = null, media = null) {
  const box = document.getElementById('messagesBox');
  const row = document.createElement('div');
  row.className = `msg-row ${role}`;

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';

  const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  let headerHtml = `<div class="msg-header"><span>${escapeHtml(sender)}</span><span class="msg-time">${timeStr}</span></div>`;
  
  let formatted = formatMarkdown(text);

  let mediaHtml = '';
  if (media && media.type === 'image' && media.url) {
    mediaHtml = renderMediaCard(media.url, media.file_name, media.file_path);
  } else if (text) {
    const imgMatch = text.match(/(\/[\w\-./]+\.(?:png|jpg|jpeg|webp|gif))/i);
    if (imgMatch) {
      const detectedPath = imgMatch[1];
      const encodedUrl = `/api/media/file?path=${encodeURIComponent(detectedPath)}`;
      const fileName = detectedPath.split('/').pop();
      mediaHtml = renderMediaCard(encodedUrl, fileName, detectedPath);
    }
  }

  bubble.innerHTML = `${headerHtml}<div class="msg-content">${formatted}</div>${mediaHtml}`;
  row.appendChild(bubble);
  box.appendChild(row);

  box.scrollTop = box.scrollHeight;
}

function renderMediaCard(url, fileName, fullPath) {
  const safeName = escapeHtml(fileName || 'gorsel.png');
  let safeUrl = url;
  if (authToken && !safeUrl.includes('token=')) {
    safeUrl += (safeUrl.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(authToken);
  }
  const cleanSafeUrl = escapeHtml(safeUrl);
  const safePath = escapeHtml(fullPath || '');
  return `
    <div class="msg-media-box">
      <div class="img-preview-wrapper" onclick="openLightbox('${cleanSafeUrl}', '${safeName}')">
        <img src="${cleanSafeUrl}" alt="${safeName}" class="msg-img-thumb" loading="lazy" onerror="this.onerror=null;this.parentElement.innerHTML='<div class=\\'img-load-error\\'>⚠️ Görsel yüklenemedi (Erişim engeli veya dosya taşınmış)</div>';" />
        <div class="img-overlay">
          <span class="zoom-icon">🔍 Büyüt</span>
        </div>
      </div>
      <div class="img-meta">
        <span class="img-filename" title="${safePath}">📁 ${safeName}</span>
        <div class="img-actions">
          <a href="${cleanSafeUrl}" download="${safeName}" class="btn-img-action" title="İndir">⬇️ İndir</a>
        </div>
      </div>
    </div>
  `;
}

function openLightbox(url, title = 'Ekran Görüntüsü Önizleme') {
  const modal = document.getElementById('imageLightboxModal');
  const img = document.getElementById('lightboxImage');
  const titleEl = document.getElementById('lightboxTitle');
  const dlBtn = document.getElementById('lightboxDownloadBtn');
  if (!modal || !img) return;

  img.src = url;
  if (titleEl) titleEl.textContent = title;
  if (dlBtn) {
    dlBtn.href = url;
    dlBtn.download = title || 'ekran.png';
  }
  modal.style.display = 'flex';
}

function closeLightbox() {
  const modal = document.getElementById('imageLightboxModal');
  const img = document.getElementById('lightboxImage');
  if (modal) modal.style.display = 'none';
  if (img) img.src = '';
}

function formatMarkdown(text) {
  if (!text) return '';
  let escaped = escapeHtml(text);
  escaped = escaped.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
  escaped = escaped.replace(/`([^`]+)`/g, '<code>$1</code>');
  escaped = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  escaped = escaped.replace(/\n/g, '<br/>');
  return escaped;
}

function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return String(text).replace(/[&<>"']/g, (m) => map[m]);
}

// 7. Service Worker & W3C Web Push Bildirimleri
async function initServiceWorker() {
  if ('serviceWorker' in navigator && 'PushManager' in window) {
    try {
      const reg = await navigator.serviceWorker.register('/sw.js');
      const res = await authFetch('/api/push/vapid_public_key');
      const data = await res.json();
      vapidPublicKey = data.public_key;
    } catch (err) {
      console.warn('Service Worker kaydı başarısız:', err);
    }
  }
}

async function requestPushNotification() {
  if (!('Notification' in window)) {
    alert('Bu tarayıcı bildirimleri desteklemiyor.');
    return;
  }

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') {
    alert('Bildirim izni verilmedi. Safari için "Ana Ekrana Ekle" (PWA) modunu kullanmanız önerilir.');
    return;
  }

  try {
    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();

    if (!sub && vapidPublicKey) {
      const convertedKey = urlBase64ToUint8Array(vapidPublicKey);
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: convertedKey
      });
    }

    if (sub) {
      await authFetch('/api/push/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sub)
      });
      alert('✅ Web Push bildirimleri başarıyla aktif edildi! Artık uygulama kapalıyken bile kilit ekranına bildirim düşecek.');
    }
  } catch (err) {
    console.error('Push abonelik hatası:', err);
    alert('Bildirim aboneliği sırasında bir hata oluştu: ' + err.message);
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

// 7.5 Cloudflare yusasufhin.com Otomatik Tünel Kurulumu (Alancf & alansifre)
async function triggerAutomatedCloudflareSetup() {
  appendMessage('agent', '☁️ Cloudflare Otomasyonu', '⏳ `.env` içerisindeki `Alancf` ve `alansifre` bilgilerinizle `yusasufhin.com` kalıcı tünel kurulumu başlatılıyor...');
  try {
    const res = await authFetch('/api/tunnel/setup_domain', { method: 'POST' });
    if (res.status === 404) {
      const cfUrl = 'https://dash.cloudflare.com/argotunnel?aud=&callback=https%3A%2F%2Flogin.cloudflareaccess.org%2FBUPVoEjLOKrAHTTzn9dnVdkumgpciV966zGqUIbe3jE%3D';
      window.open(cfUrl, '_blank');
      appendMessage('agent', '☁️ Cloudflare Otomasyonu', `Cloudflare yetkilendirme penceresi açıldı (\`Alancf\` hesabınızla giriş yapıp \`yusasufhin.com\` alan adını seçin; \`alansifre\` panonuza kopyalandı).\n\n🔗 Bağlantı: ${cfUrl}`);
      return;
    }
    const data = await res.json();
    let msg = data.message || 'İşlem tamamlandı.';
    if (data.auth_url) {
      msg += `\n\n🔗 Otomatik açılmadıysa onay bağlantısı: ${data.auth_url}`;
      window.open(data.auth_url, '_blank');
    }
    appendMessage('agent', '☁️ Cloudflare Otomasyonu', msg);
    fetchSystemStats();
  } catch (err) {
    appendMessage('agent', '☁️ Cloudflare Otomasyonu', '❌ Kurulum tetiklenemedi: ' + err.message);
  }
}

const FALLBACK_LINK_POOL = [
  { id: 164, category: 'tasarim_ui', title: 'Oil UI — 3-Yönlü Otonom Web Tasarım Motoru', url: 'https://github.com/oil-oil/oil-ui', summary: 'Tek bir tahmine takılmak yerine 3 özgün tasarım yönü (Cyber HUD, Jiro Glass, Minimal Gold) kurgular ve canlı karşılaştırma sunar.' },
  { id: 173, category: 'tasarim_ui', title: 'jiro.build & 21st.dev — Üst Düzey Tasarım Bileşenleri', url: 'https://jiro.build', summary: '1.300+ tasarım şablonu, Spotlight kartlar, ⌘K komut paletleri ve modern cam efektli arayüz bileşenleri.' },
  { id: 153, category: 'tasarim_ui', title: 'BentoGrids & 60fps.design — Telemetri Izgara Mimarisi', url: 'https://bentogrids.com', summary: 'Komuta merkezleri için Bento Grid düzenleri ve 60fps akıcı mikro etkileşimler.' },
  { id: 103, category: 'tasarim_ui', title: 'Canvas UI, Paper Shaders & Cursify', url: 'https://github.com/DavidHDev/canvas-ui', summary: 'Canlı sinirsel ağ arka plan kanvası ve fare imlecini takip eden Spotlight ışık efektleri.' },
  { id: 66, category: 'ajan_mimari', title: 'PilotDeck 2.0 — Otonom Ajan İşletim Sistemi', url: 'https://github.com/OpenBMB/PilotDeck', summary: 'Tsinghua THUNLP & OpenBMB tarafından geliştirilen modelden bağımsız ajan çalışma alanı.' },
  { id: 48, category: 'guvenlik', title: 'REA — Tersine Mühendislik ve Siber Kalkan Ajanı', url: 'https://x.com/so_ainsight/status/2110364065822646570', summary: 'AST tabanlı kod analizi, paket dekonstrüksiyonu ve kalıcı zafiyet hafızası.' },
  { id: 229, category: 'yapay_zeka', title: 'Qwen 3.8 27B / 35B-A3B — Yerel MLX & MTP Hızlandırma', url: 'https://youtu.be/h_KqS4GtU3I', summary: 'Apple Silicon Unified Memory üzerinde yüksek akıl yürütme ve çoklu token tahmini.' },
  { id: 220, category: 'medya_ses', title: 'Ming-3.0-TTS & Kokoro — Gerçek Zamanlı Ses Sentezi', url: 'https://x.com/ryrenz/status/2112695882730688543', summary: 'Düşük gecikmeli yerel ses klonlama ve doğal konuşma sentezi.' }
];

// 7.8 Link Havuzu Gezgini (229 Proje)
function initLinkPoolExplorer() {
  const modal = document.getElementById('linkPoolModal');
  const btnHeader = document.getElementById('btnOpenLinkPoolHeader');
  const btnSidebar = document.getElementById('btnOpenLinkPoolSidebar');
  const cardBento = document.getElementById('bentoCardLinkPool');
  const chipOpen = document.getElementById('chipOpenLinkPool');
  const btnClose = document.getElementById('btnCloseLinkPool');
  const searchInp = document.getElementById('linkPoolSearchInput');

  function openPool() {
    if (modal) {
      modal.style.display = 'flex';
      loadLinkPoolItems();
      if (searchInp) searchInp.focus();
    }
  }

  if (btnHeader) btnHeader.addEventListener('click', openPool);
  if (btnSidebar) btnSidebar.addEventListener('click', openPool);
  if (cardBento) cardBento.addEventListener('click', openPool);
  if (chipOpen) chipOpen.addEventListener('click', openPool);
  if (btnClose) btnClose.addEventListener('click', () => { if (modal) modal.style.display = 'none'; });

  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) modal.style.display = 'none';
    });
  }

  if (searchInp) {
    let debounceTimer = null;
    searchInp.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(loadLinkPoolItems, 220);
    });
  }

  document.querySelectorAll('.link-cat-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.link-cat-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentLinkCategory = btn.getAttribute('data-cat') || 'all';
      loadLinkPoolItems();
    });
  });
}

async function loadLinkPoolItems() {
  const grid = document.getElementById('linkPoolGrid');
  const searchInp = document.getElementById('linkPoolSearchInput');
  if (!grid) return;

  const q = (searchInp ? searchInp.value.trim() : '').toLowerCase();
  grid.innerHTML = '<p class="placeholder-text">⏳ Ar-Ge Link Havuzu taranıyor...</p>';

  try {
    const url = `/api/links/pool?q=${encodeURIComponent(q)}&category=${encodeURIComponent(currentLinkCategory)}`;
    const res = await authFetch(url);
    let items = [];
    if (res.ok) {
      const data = await res.json();
      items = data.items || [];
    } else {
      items = FALLBACK_LINK_POOL.filter(it =>
        (currentLinkCategory === 'all' || it.category === currentLinkCategory) &&
        (!q || `${it.title} ${it.summary}`.toLowerCase().includes(q))
      );
    }

    if (!items.length) {
      grid.innerHTML = '<p class="placeholder-text">Eşleşen proje bulunamadı.</p>';
      return;
    }

    grid.innerHTML = items.map((item) => `
      <div class="link-pool-card">
        <div class="link-pool-card-top">
          <span class="link-id-badge">#${escapeHtml(String(item.id))}</span>
          <span class="link-cat-tag">${escapeHtml(item.category.replace('_', ' ').toUpperCase())}</span>
        </div>
        <h4>${escapeHtml(item.title)}</h4>
        <p>${escapeHtml(item.summary || 'Açıklama mevcut değil.')}</p>
        <div class="link-pool-card-actions">
          ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener" class="btn-link-visit">🔗 Kaynağı Aç</a>` : ''}
          <button type="button" class="btn-link-analyze" onclick="sendLinkToAgent(${Number(item.id)}, '${escapeHtml(item.title.replace(/'/g, ''))}')">⚡ Ajanla Analiz Et</button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    grid.innerHTML = `<p class="placeholder-text">Hata: ${escapeHtml(err.message)}</p>`;
  }
}

window.sendLinkToAgent = function(linkId, linkTitle) {
  const modal = document.getElementById('linkPoolModal');
  if (modal) modal.style.display = 'none';
  const input = document.getElementById('chatInput');
  if (input) {
    input.value = `Link #${linkId} (${linkTitle}) projesini incele ve link havuzu raporu hazırla`;
    sendMessage();
  }
};

// 7.9 ⌘K Komut Paleti (Link #173 jiro.build)
function initCommandPalette() {
  const modal = document.getElementById('cmdPaletteModal');
  const btnOpen = document.getElementById('btnOpenCmdPalette');
  const btnClose = document.getElementById('btnCloseCmdPalette');
  const input = document.getElementById('cmdPaletteInput');

  function openCmd() {
    if (modal) {
      modal.style.display = 'flex';
      if (input) {
        input.value = '';
        filterCmdItems('');
        input.focus();
      }
    }
  }

  function closeCmd() {
    if (modal) modal.style.display = 'none';
  }

  if (btnOpen) btnOpen.addEventListener('click', openCmd);
  if (btnClose) btnClose.addEventListener('click', closeCmd);
  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeCmd();
    });
  }

  window.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      if (modal && modal.style.display === 'flex') closeCmd();
      else openCmd();
    }
  });

  if (input) {
    input.addEventListener('input', () => filterCmdItems(input.value));
  }

  document.querySelectorAll('.cmd-item').forEach((item) => {
    item.addEventListener('click', () => {
      const cmd = item.getAttribute('data-cmd');
      closeCmd();
      if (cmd === 'open_link_pool') {
        const m = document.getElementById('linkPoolModal');
        if (m) { m.style.display = 'flex'; loadLinkPoolItems(); }
      } else if (cmd === 'setup_cloudflare') {
        triggerAutomatedCloudflareSetup();
      } else if (cmd === 'open_rea') {
        const m = document.getElementById('reaModal');
        if (m) { m.style.display = 'flex'; fetchReaHistory(); }
      } else if (cmd === 'theme_cyber') {
        applyOilTheme('cyber_hud');
      } else if (cmd === 'theme_jiro') {
        applyOilTheme('jiro_glass');
      } else if (cmd === 'theme_minimal') {
        applyOilTheme('minimal_gold');
      } else if (cmd === 'screenshot') {
        const chatInp = document.getElementById('chatInput');
        if (chatInp) { chatInp.value = 'ekran görüntüsü al'; sendMessage(); }
      }
    });
  });
}

function filterCmdItems(query) {
  const q = (query || '').trim().toLowerCase();
  document.querySelectorAll('.cmd-item').forEach((item) => {
    const txt = item.textContent.toLowerCase();
    item.style.display = (!q || txt.includes(q)) ? 'flex' : 'none';
  });
}

// 8. UI Etkinlikleri
function initUIEvents() {
  const input = document.getElementById('chatInput');
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
  });

  const sendBtn = document.getElementById('btnSend');
  if (sendBtn) sendBtn.addEventListener('click', sendMessage);

  const pushBtn = document.getElementById('btnEnablePush');
  if (pushBtn) pushBtn.addEventListener('click', requestPushNotification);

  const btnToggleBio = document.getElementById('btnToggleBiometrics');
  if (btnToggleBio) btnToggleBio.addEventListener('click', toggleBiometrics);

  const btnAutoCf = document.getElementById('btnAutoSetupCf');
  if (btnAutoCf) btnAutoCf.addEventListener('click', triggerAutomatedCloudflareSetup);

  const btnBentoCf = document.getElementById('btnBentoCfSetup');
  if (btnBentoCf) btnBentoCf.addEventListener('click', triggerAutomatedCloudflareSetup);

  const btnToggleBento = document.getElementById('btnToggleBento');
  const bentoDash = document.getElementById('bentoDashboard');
  if (btnToggleBento && bentoDash) {
    btnToggleBento.addEventListener('click', () => {
      bentoDash.classList.toggle('collapsed');
    });
  }

  const btnLockApp = document.getElementById('btnLockApp');
  if (btnLockApp) {
    btnLockApp.addEventListener('click', () => {
      logout(true);
    });
  }

  const menuToggle = document.getElementById('menuToggle');
  const sidebar = document.getElementById('sidebar');
  const sidebarBackdrop = document.getElementById('sidebarBackdrop');
  const btnCloseSidebar = document.getElementById('btnCloseSidebar');

  function openSidebar() {
    if (sidebar) sidebar.classList.add('open');
    if (sidebarBackdrop) sidebarBackdrop.classList.add('active');
  }

  function closeSidebar() {
    if (sidebar) sidebar.classList.remove('open');
    if (sidebarBackdrop) sidebarBackdrop.classList.remove('active');
  }

  if (menuToggle) {
    menuToggle.addEventListener('click', () => {
      if (sidebar && sidebar.classList.contains('open')) {
        closeSidebar();
      } else {
        openSidebar();
      }
    });
  }

  if (btnCloseSidebar) btnCloseSidebar.addEventListener('click', closeSidebar);
  if (sidebarBackdrop) sidebarBackdrop.addEventListener('click', closeSidebar);

  document.querySelectorAll('.person-item').forEach((item) => {
    item.addEventListener('click', () => {
      document.querySelectorAll('.person-item').forEach(p => p.classList.remove('active'));
      item.classList.add('active');
      const prompt = item.getAttribute('data-agent-prompt');
      if (prompt) {
        const chatInp = document.getElementById('chatInput');
        if (chatInp) chatInp.placeholder = `${item.querySelector('.person-name').textContent.trim()} ajanına talimat verin...`;
      }
      if (window.innerWidth <= 768) {
        closeSidebar();
      }
    });
  });

  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', () => {
      const messagesBox = document.getElementById('messagesBox');
      if (messagesBox) {
        setTimeout(() => {
          messagesBox.scrollTop = messagesBox.scrollHeight;
        }, 120);
      }
    });
  }

  // Quick Chips
  document.querySelectorAll('.chip[data-prompt]').forEach((chip) => {
    chip.addEventListener('click', () => {
      const prompt = chip.getAttribute('data-prompt');
      if (prompt) {
        document.getElementById('chatInput').value = prompt;
        sendMessage();
      }
    });
  });

  // 9. REA Güvenlik Radarı Modalı
  const reaModal = document.getElementById('reaModal');
  const btnOpenRea = document.getElementById('btnOpenRea');
  const bentoCardRea = document.getElementById('bentoCardRea');
  const btnCloseRea = document.getElementById('btnCloseRea');
  const btnRunReaScan = document.getElementById('btnRunReaScan');

  function openReaModal() {
    if (reaModal) {
      reaModal.style.display = 'flex';
      fetchReaHistory();
    }
  }

  if (btnOpenRea) btnOpenRea.addEventListener('click', openReaModal);
  if (bentoCardRea) bentoCardRea.addEventListener('click', openReaModal);

  if (btnCloseRea && reaModal) {
    btnCloseRea.addEventListener('click', () => {
      reaModal.style.display = 'none';
    });
  }

  if (reaModal) {
    reaModal.addEventListener('click', (e) => {
      if (e.target === reaModal) reaModal.style.display = 'none';
    });
  }

  if (btnRunReaScan) {
    btnRunReaScan.addEventListener('click', async () => {
      const inputVal = document.getElementById('reaInput').value.trim();
      const personaVal = document.getElementById('reaPersonaSelect').value;
      const resultBox = document.getElementById('reaResultBox');

      if (!inputVal) {
        alert('Lütfen taranacak bir kod bloğu veya dosya yolu girin.');
        return;
      }

      resultBox.innerHTML = '<p class="placeholder-text">⏳ REA AST ve zafiyet analizi yürütülüyor...</p>';

      try {
        const res = await authFetch('/api/rea/scan', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ hedef: inputVal, persona: personaVal })
        });
        const data = await res.json();
        if (data.rapor) {
          resultBox.innerHTML = `<div>${formatMarkdown(data.rapor)}</div>`;
        } else {
          resultBox.innerHTML = `<pre><code>${escapeHtml(JSON.stringify(data, null, 2))}</code></pre>`;
        }
        fetchReaHistory();
      } catch (err) {
        resultBox.innerHTML = `<p style="color: var(--accent-red);">❌ Tarama hatası: ${escapeHtml(err.message)}</p>`;
      }
    });
  }

  // 10. Görsel Lightbox Modal Kapatma Olayları
  const btnCloseLightbox = document.getElementById('btnCloseLightbox');
  const lightboxModal = document.getElementById('imageLightboxModal');
  if (btnCloseLightbox) {
    btnCloseLightbox.addEventListener('click', closeLightbox);
  }
  if (lightboxModal) {
    lightboxModal.addEventListener('click', (e) => {
      if (e.target === lightboxModal) closeLightbox();
    });
  }
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeLightbox();
      if (reaModal) reaModal.style.display = 'none';
      const lpModal = document.getElementById('linkPoolModal');
      if (lpModal) lpModal.style.display = 'none';
      const cmdModal = document.getElementById('cmdPaletteModal');
      if (cmdModal) cmdModal.style.display = 'none';
    }
  });
}

async function fetchReaHistory() {
  try {
    const res = await authFetch('/api/rea/history');
    const data = await res.json();
    if (data.toplam_tarama !== undefined) {
      document.getElementById('reaTotalScans').textContent = data.toplam_tarama;
      document.getElementById('reaAvgScore').textContent = data.ort_skor;
      document.getElementById('reaRepeats').textContent = data.tekrarlayan_zafiyet_sayisi;
    }
  } catch (e) {
    console.warn('REA hafıza geçmişi alınamadı:', e);
  }
}

async function fetchSystemStats() {
  try {
    const res = await authFetch('/api/system/stats');
    const data = await res.json();
    if (data.cpu !== undefined) {
      document.getElementById('sysCpu').textContent = `CPU: %${data.cpu}`;
      document.getElementById('sysRam').textContent = `RAM: %${data.ram}`;
      const bCpuVal = document.getElementById('bentoCpuVal');
      const bRamVal = document.getElementById('bentoRamVal');
      const bCpuBar = document.getElementById('bentoCpuBar');
      const bRamBar = document.getElementById('bentoRamBar');
      if (bCpuVal) bCpuVal.textContent = `%${data.cpu}`;
      if (bRamVal) bRamVal.textContent = `%${data.ram}`;
      if (bCpuBar) bCpuBar.style.width = `${Math.min(100, data.cpu)}%`;
      if (bRamBar) bRamBar.style.width = `${Math.min(100, data.ram)}%`;
    }
    if (data.link_pool_count !== undefined) {
      const lpEl = document.getElementById('bentoLinkCount');
      if (lpEl) lpEl.textContent = data.link_pool_count;
    }
    if (data.rea_score !== undefined) {
      const rsEl = document.getElementById('bentoReaScore');
      if (rsEl) rsEl.textContent = data.rea_score;
    }
    if (data.tunnel) {
      const subEl = document.getElementById('bentoTunnelSub');
      if (subEl) {
        if (data.tunnel.named_tunnel_active === 'true') {
          subEl.textContent = '🟢 Kalıcı Cloudflare Tüneli Aktif';
        } else if (data.tunnel.cloudflare_url) {
          subEl.textContent = data.tunnel.cloudflare_url.replace('https://', '');
        }
      }
    }
  } catch (e) {}
}
