/* site.js — yusasufhin.com genel yüz: giriş kapısı, hub, tema, canvas arka plan
 *
 * Oturum sözleşmesi: mevcut Fabrika dashboard'u ile AYNI anahtar kullanılır
 * (`fabrika_token`), böylece giriş bir kez yapılır ve /fabrika.html'e geçişte
 * yeniden kimlik sorulmaz.
 */
(function () {
  'use strict';

  var TOKEN_KEY = 'fabrika_token';
  var USER_KEY = 'fabrika_username';
  var THEME_KEY = 'site_theme';

  var gate = document.getElementById('siteGate');
  var hub = document.getElementById('siteHub');
  var form = document.getElementById('siteGateForm');
  var errorBox = document.getElementById('siteGateError');
  var submitBtn = document.getElementById('siteGateSubmit');
  var userInput = document.getElementById('siteUser');
  var passInput = document.getElementById('sitePass');

  function token() {
    try { return localStorage.getItem(TOKEN_KEY); } catch (e) { return null; }
  }

  function showGate(message) {
    if (hub) hub.hidden = true;
    if (gate) gate.hidden = false;
    if (errorBox && message) errorBox.textContent = message;
    if (userInput && !userInput.value) {
      try {
        var saved = localStorage.getItem(USER_KEY);
        if (saved) userInput.value = saved;
      } catch (e) { /* yoksay */ }
    }
    if (passInput) passInput.focus();
  }

  function showHub() {
    if (gate) gate.hidden = true;
    if (hub) hub.hidden = false;
    var who = document.getElementById('siteHubUser');
    if (who) {
      var saved = '';
      try { saved = localStorage.getItem(USER_KEY) || ''; } catch (e) { saved = ''; }
      who.textContent = saved;
    }
  }

  /* ── Oturum doğrulama ───────────────────────────────────────────────── */
  function checkSession() {
    var t = token();
    if (!t) { showGate(); return; }
    fetch('/api/auth/check', { headers: { Authorization: 'Bearer ' + t } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.authenticated) { showHub(); } else { showGate(); }
      })
      .catch(function () { showGate(); });
  }

  /* ── Giriş ──────────────────────────────────────────────────────────── */
  if (form) {
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (errorBox) errorBox.textContent = '';
      if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Doğrulanıyor…'; }

      fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: userInput ? userInput.value.trim() : '',
          password: passInput ? passInput.value : ''
        })
      })
        .then(function (r) {
          return r.json().then(function (body) { return { ok: r.ok, body: body }; });
        })
        .then(function (res) {
          if (res.ok && res.body && res.body.token) {
            try {
              localStorage.setItem(TOKEN_KEY, res.body.token);
              localStorage.setItem(USER_KEY, userInput ? userInput.value.trim() : '');
            } catch (e) { /* yoksay */ }
            if (passInput) passInput.value = '';
            showHub();
          } else {
            var msg = (res.body && (res.body.detail || res.body.message)) || 'Giriş başarısız.';
            if (errorBox) errorBox.textContent = msg;
          }
        })
        .catch(function () {
          if (errorBox) errorBox.textContent = 'Sunucuya ulaşılamadı. Bağlantınızı kontrol edin.';
        })
        .finally(function () {
          if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'Giriş Yap'; }
        });
    });
  }

  ['openGateBtn', 'heroGateBtn'].forEach(function (id) {
    var btn = document.getElementById(id);
    if (btn) btn.addEventListener('click', function () { showGate(); });
  });

  var cancelBtn = document.getElementById('siteGateCancel');
  if (cancelBtn) cancelBtn.addEventListener('click', function () {
    if (gate) gate.hidden = true;
    if (errorBox) errorBox.textContent = '';
  });

  var logoutBtn = document.getElementById('siteLogoutBtn');
  if (logoutBtn) logoutBtn.addEventListener('click', function () {
    var t = token();
    if (t) {
      fetch('/api/auth/logout', { method: 'POST', headers: { Authorization: 'Bearer ' + t } })
        .catch(function () { /* yoksay */ });
    }
    try {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    } catch (e) { /* yoksay */ }
    showGate('Oturum kapatıldı.');
  });

  /* ── Tema (Link #164 Oil UI) ────────────────────────────────────────── */
  function applyTheme(name) {
    document.documentElement.setAttribute('data-site-theme', name);
    try { localStorage.setItem(THEME_KEY, name); } catch (e) { /* yoksay */ }
    var buttons = document.querySelectorAll('[data-site-theme-btn]');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].setAttribute('aria-pressed',
        buttons[i].getAttribute('data-site-theme-btn') === name ? 'true' : 'false');
    }
  }

  var themeButtons = document.querySelectorAll('[data-site-theme-btn]');
  for (var i = 0; i < themeButtons.length; i++) {
    themeButtons[i].addEventListener('click', function () {
      applyTheme(this.getAttribute('data-site-theme-btn'));
    });
  }

  var savedTheme = 'cyber';
  try { savedTheme = localStorage.getItem(THEME_KEY) || 'cyber'; } catch (e) { savedTheme = 'cyber'; }
  applyTheme(savedTheme);

  checkSession();
})();

/* ── Canlı canvas arka plan (Link #103) ───────────────────────────────── */
(function () {
  'use strict';
  var canvas = document.getElementById('siteCanvas');
  if (!canvas || !canvas.getContext) return;

  var ctx = canvas.getContext('2d');
  var nodes = [];
  var raf = null;

  function accent() {
    var styles = getComputedStyle(document.documentElement);
    return (styles.getPropertyValue('--site-accent') || '#2dd4bf').trim();
  }

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    var count = Math.min(56, Math.round((canvas.width * canvas.height) / 26000));
    nodes = [];
    for (var n = 0; n < count; n++) {
      nodes.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
        r: Math.random() * 1.6 + 0.6
      });
    }
  }

  function draw() {
    var color = accent();
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (var a = 0; a < nodes.length; a++) {
      var p = nodes[a];
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < 0 || p.x > canvas.width) p.vx *= -1;
      if (p.y < 0 || p.y > canvas.height) p.vy *= -1;

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.55;
      ctx.fill();

      for (var b = a + 1; b < nodes.length; b++) {
        var q = nodes[b];
        var dx = p.x - q.x;
        var dy = p.y - q.y;
        var dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 132) {
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(q.x, q.y);
          ctx.strokeStyle = color;
          ctx.globalAlpha = (1 - dist / 132) * 0.16;
          ctx.lineWidth = 0.7;
          ctx.stroke();
        }
      }
    }
    ctx.globalAlpha = 1;
    raf = requestAnimationFrame(draw);
  }

  resize();
  draw();

  window.addEventListener('resize', function () {
    if (raf) cancelAnimationFrame(raf);
    resize();
    draw();
  });
})();

