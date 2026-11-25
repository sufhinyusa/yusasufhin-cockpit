/* site.js — yusasufhin.com genel vitrin, isteğe bağlı yönetici girişi, iletişim formu ve tema
 *
 * Önemli: Ana sayfa ziyaretçilere HER ZAMAN doğrudan açılır; giriş kapısı asla otomatik
 * olarak sayfayı bloke etmez. Yönetici girişi yalnızca footer'daki düğmeye basıldığında
 * veya /?login=1 ile açılır; giriş başarılı olunca doğrudan /lab.html stüdyosuna geçilir.
 */
(function () {
  'use strict';

  var TOKEN_KEY = 'fabrika_token';
  var THEME_KEY = 'site_theme';

  var gate = document.getElementById('siteGate');
  var form = document.getElementById('siteGateForm');
  var errorBox = document.getElementById('siteGateError');
  var submitBtn = document.getElementById('siteGateSubmit');
  var passInput = document.getElementById('sitePass');
  var studioQuickLink = document.getElementById('studioQuickLink');

  function getToken() {
    try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; }
  }

  function showGate(message) {
    if (!gate) return;
    gate.hidden = false;
    if (errorBox) errorBox.textContent = message || '';
    if (passInput) {
      passInput.value = '';
      passInput.focus();
    }
  }

  function hideGate() {
    if (gate) gate.hidden = true;
    if (errorBox) errorBox.textContent = '';
  }

  function checkOptionalSession() {
    var t = getToken();
    if (!t) return;
    fetch('/api/auth/check', { headers: { Authorization: 'Bearer ' + t } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.authenticated && studioQuickLink) {
          studioQuickLink.hidden = false;
        }
      })
      .catch(function () { /* sessiz geç */ });
  }

  if (form) {
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var userEl = document.getElementById('siteUsername');
      var usernameVal = userEl ? userEl.value.trim() : '';
      var secretVal = passInput ? passInput.value.trim() : '';
      if (!secretVal) {
        if (errorBox) errorBox.textContent = 'Lütfen parola veya PIN girin.';
        return;
      }
      if (errorBox) errorBox.textContent = '';
      if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Doğrulanıyor…'; }

      var isPin = (!usernameVal && /^\d{6}$/.test(secretVal));
      var endpoint = isPin ? '/api/auth/verify_pin' : '/api/auth/login';
      var bodyPayload = isPin ? { pin: secretVal } : { username: usernameVal, password: secretVal };

      fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bodyPayload)
      })
        .then(function (r) {
          return r.json().then(function (body) { return { ok: r.ok, body: body }; });
        })
        .then(function (res) {
          if (res.ok && res.body && res.body.token) {
            try {
              localStorage.setItem(TOKEN_KEY, res.body.token);
              localStorage.setItem('cockpit_token', res.body.token);
            } catch (e) { /* yoksay */ }
            window.location.href = '/lab.html';
          } else {
            var msg = (res.body && (res.body.detail || res.body.message)) || 'Giriş başarısız.';
            if (errorBox) errorBox.textContent = msg;
          }
        })
        .catch(function () {
          if (errorBox) errorBox.textContent = 'Sunucuya ulaşılamadı. Bağlantınızı kontrol edin.';
        })
        .finally(function () {
          if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'Panele Gir'; }
        });
    });
  }

  var openGateBtn = document.getElementById('openGateBtn');
  if (openGateBtn) {
    openGateBtn.addEventListener('click', function () {
      var t = getToken();
      if (t) {
        fetch('/api/auth/check', { headers: { Authorization: 'Bearer ' + t } })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) {
            if (d && d.authenticated) window.location.href = '/lab.html';
            else showGate();
          })
          .catch(function () { showGate(); });
      } else {
        showGate();
      }
    });
  }

  var cancelBtn = document.getElementById('siteGateCancel');
  if (cancelBtn) cancelBtn.addEventListener('click', hideGate);

  if (gate) {
    gate.addEventListener('click', function (ev) {
      if (ev.target === gate) hideGate();
    });
    window.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && !gate.hidden) hideGate();
    });
  }

  /* ── İletişim Formu (/api/contact) ──────────────────────────────────── */
  var contactForm = document.getElementById('siteContactForm');
  var contactStatus = document.getElementById('contactStatus');
  var contactBtn = document.getElementById('contactSubmitBtn');
  if (contactForm) {
    contactForm.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var nameEl = document.getElementById('contactName');
      var emailEl = document.getElementById('contactEmail');
      var msgEl = document.getElementById('contactMsg');
      var payload = {
        name: nameEl ? nameEl.value.trim() : '',
        email: emailEl ? emailEl.value.trim() : '',
        message: msgEl ? msgEl.value.trim() : ''
      };
      if (payload.name.length < 2) {
        if (contactStatus) { contactStatus.textContent = '⚠️ Lütfen adınızı girin (en az 2 karakter).'; contactStatus.style.color = 'var(--site-danger)'; }
        if (nameEl) nameEl.focus();
        return;
      }
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(payload.email)) {
        if (contactStatus) { contactStatus.textContent = '⚠️ Lütfen geçerli bir e-posta adresi girin.'; contactStatus.style.color = 'var(--site-danger)'; }
        if (emailEl) emailEl.focus();
        return;
      }
      if (payload.message.length < 10) {
        if (contactStatus) { contactStatus.textContent = '⚠️ Lütfen en az 10 karakterlik bir mesaj yazın.'; contactStatus.style.color = 'var(--site-danger)'; }
        if (msgEl) msgEl.focus();
        return;
      }
      if (contactStatus) { contactStatus.textContent = ''; contactStatus.style.color = ''; }
      if (contactBtn) { contactBtn.disabled = true; contactBtn.textContent = 'Gönderiliyor…'; }

      fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
        .then(function (r) {
          return r.json().then(function (body) { return { ok: r.ok, body: body }; });
        })
        .then(function (res) {
          if (res.ok && res.body && res.body.success) {
            contactForm.reset();
            if (contactStatus) {
              contactStatus.style.color = 'var(--site-accent)';
              contactStatus.textContent = '';
              var txt = document.createTextNode((res.body.notified ? '✅ ' : 'ℹ️ ') + (res.body.message || 'Mesajınız kaydedildi.'));
              contactStatus.appendChild(txt);
              if (!res.body.notified && res.body.mailto_fallback_url) {
                var br = document.createElement('br');
                var a = document.createElement('a');
                a.href = res.body.mailto_fallback_url;
                a.textContent = '✉️ E-posta Uygulamasıyla Hemen Gönder →';
                a.style.cssText = 'display:inline-block; margin-top:8px; color:var(--site-accent); font-weight:700; text-decoration:underline;';
                contactStatus.appendChild(br);
                contactStatus.appendChild(a);
              }
            }
          } else {
            if (contactStatus) {
              contactStatus.textContent = '⚠️ ' + ((res.body && (res.body.detail || res.body.message)) || 'Gönderilemedi.');
              contactStatus.style.color = 'var(--site-danger)';
            }
          }
        })
        .catch(function () {
          if (contactStatus) {
            contactStatus.textContent = '⚠️ Sunucuya ulaşılamadı. Doğrudan e-posta ile ulaşabilirsiniz.';
            contactStatus.style.color = 'var(--site-danger)';
          }
        })
        .finally(function () {
          if (contactBtn) { contactBtn.disabled = false; contactBtn.textContent = 'Mesajı Gönder'; }
        });
    });
  }

  /* ── Tema (Açık / Koyu) ─────────────────────────────────────────────── */
  function applyTheme(name) {
    var safe = (name === 'saas') ? 'saas' : 'cyber';
    document.documentElement.setAttribute('data-site-theme', safe);
    try { localStorage.setItem(THEME_KEY, safe); } catch (e) { /* yoksay */ }
    var buttons = document.querySelectorAll('[data-site-theme-btn]');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].setAttribute('aria-pressed',
        buttons[i].getAttribute('data-site-theme-btn') === safe ? 'true' : 'false');
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

  /* ── Sabit üst bar yüksekliğini her ekranda piksel-tam eşitle ───────── */
  function syncNavOffset() {
    var nav = document.querySelector('.site-nav');
    if (nav && nav.offsetHeight > 0) {
      document.documentElement.style.setProperty('--site-nav-offset', (nav.offsetHeight + 8) + 'px');
    }
  }
  syncNavOffset();
  window.addEventListener('resize', syncNavOffset);
  window.addEventListener('orientationchange', function () { setTimeout(syncNavOffset, 150); });
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', syncNavOffset);
  }

  if (gate) {
    checkOptionalSession();
    if (window.location.search && window.location.search.indexOf('login=1') >= 0) {
      showGate();
    }
  }
})();
