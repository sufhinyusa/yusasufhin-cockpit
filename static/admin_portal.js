/* admin_portal.js — 3-Buton Yönetici Merkezi (Fabrika / Video / Müzik),
 * Bölüm İçi Kullanıcı & Yönetici Yönetimi, Çoklu E-posta Alıcıları ve Müzik Stüdyosu.
 *
 * Güvenlik: Güvenilmeyen tüm veriler `textContent` / `esc` ile işlenir; olaylar
 * delegasyonla bağlanır (satır içi onclick string enjeksiyonu yoktur).
 */
(function () {
  'use strict';

  var _session = { role: null, sections: [], username: '', display_name: '', is_owner: false };
  var _musicModels = [];
  var _musicPollTimer = null;

  var SECTION_META = {
    fabrika: { label: 'Fabrika', icon: '🏭', warn: true },
    video: { label: 'Video', icon: '🎬', warn: false },
    muzik: { label: 'Müzik', icon: '🎵', warn: false }
  };

  function esc(v) {
    return String(v === null || v === undefined ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  function af(url, opts) {
    return window.authFetch ? window.authFetch(url, opts) : fetch(url, opts);
  }

  function isAdmin() {
    return _session && _session.role === 'admin';
  }

  function hasSection(sec) {
    if (isAdmin()) return true;
    var secs = (_session && Array.isArray(_session.sections)) ? _session.sections : [];
    return secs.indexOf(sec) >= 0;
  }

  /* ── OTURUM BİLGİSİNİ UYGULA (3-BUTON YÖNETİCİ / KULLANICI GÖRÜNÜMÜ) ─── */
  window.applySessionToStudio = function (sess) {
    _session = Object.assign({ role: 'user', sections: [], username: '', display_name: '', is_owner: false }, sess || {});
    var admin = isAdmin();
    var canFab = hasSection('fabrika');
    var canVid = hasSection('video');
    var canMus = hasSection('muzik');

    var roleBadge = document.getElementById('topUserRoleBadge');
    if (roleBadge) {
      roleBadge.textContent = (admin ? '👑 Yönetici: ' : '👤 Kullanıcı: ') + (_session.display_name || _session.username || 'Oturum');
      roleBadge.className = admin ? 'site-badge site-badge-free' : 'site-badge';
    }

    // Üst bar ve 3 ana portal kartı görünürlüğü
    var cardFab = document.getElementById('hubCardFabrika');
    var cardVid = document.getElementById('hubCardVideo');
    var cardMus = document.getElementById('hubCardMuzik');
    if (cardFab) cardFab.hidden = !canFab;
    if (cardVid) cardVid.hidden = !canVid;
    if (cardMus) cardMus.hidden = !canMus;

    var topFabLink = document.getElementById('topFabrikaUiLink');
    if (topFabLink) topFabLink.hidden = !canFab;
    var topMac = document.getElementById('topMacBadge');
    if (topMac) topMac.hidden = !canFab;

    // Sekme izinleri
    var tabPerm = {
      tabNavHub: true,
      tabNavMac: canFab,
      tabNavVideo: canVid,
      tabNavMusic: canMus,
      tabNavAudio: canMus || canVid,
      tabNavChannels: canVid,
      tabNavGpu: canVid,
      mobTabHub: true,
      mobTabMac: canFab,
      mobTabVideo: canVid,
      mobTabMusic: canMus,
      mobTabChannels: canVid
    };
    Object.keys(tabPerm).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.hidden = !tabPerm[id];
    });

    // Yöneticiye özel kartlar (kullanıcı ekleme slotları, e-posta alıcıları, müzik API anahtarları)
    document.querySelectorAll('[data-admin-only="1"]').forEach(function (el) {
      el.hidden = !admin;
    });

    if (admin) {
      renderUserSectionSlot('fabrikaUsersSlot', 'fabrika');
      renderUserSectionSlot('videoUsersSlot', 'video');
      renderUserSectionSlot('muzikUsersSlot', 'muzik');
      window.refreshAllUserLists();
      window.loadContactRecipients();
    }
  };

  window.getStudioSession = function () { return _session; };

  /* ── HER BÖLÜM İÇİNDE KULLANICI / YÖNETİCİ EKLEME BİLEŞENİ ──────────── */
  function renderUserSectionSlot(slotId, sectionKey) {
    var slot = document.getElementById(slotId);
    if (!slot || !isAdmin()) return;
    var meta = SECTION_META[sectionKey] || { label: sectionKey, icon: '👤', warn: false };

    slot.innerHTML =
      '<div class="site-card" style="margin-top:20px; border-color:color-mix(in srgb, var(--site-accent) 34%, var(--site-border));">' +
      '  <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:12px;">' +
      '    <div>' +
      '      <h3 style="margin:0 0 3px; font-size:1.05rem;">👥 ' + esc(meta.icon + ' ' + meta.label) + ' Bölümü — Kullanıcı &amp; Yönetici Ekle</h3>' +
      '      <p style="margin:0; font-size:0.8rem; color:var(--site-text-dim);">Bu bölüme erişebilecek kullanıcı veya yeni yönetici ekleyin, yetkileri düzenleyin ya da silin.</p>' +
      '    </div>' +
      '    <button type="button" class="site-btn site-btn-ghost" data-refresh-users="' + esc(sectionKey) + '" style="padding:6px 12px; font-size:0.78rem;">🔄 Yenile</button>' +
      '  </div>' +
      '  <form class="site-user-add-form" data-section-form="' + esc(sectionKey) + '" autocomplete="off">' +
      '    <div class="site-studio-row-3">' +
      '      <div class="site-field"><label>Kullanıcı Adı</label><input type="text" name="username" class="site-input" required minlength="3" maxlength="32" placeholder="orn: ahmet.video" autocomplete="off"></div>' +
      '      <div class="site-field"><label>Görünen Ad</label><input type="text" name="display_name" class="site-input" maxlength="60" placeholder="Örn: Ahmet Yılmaz"></div>' +
      '      <div class="site-field"><label>Parola (en az 8 karakter)</label><input type="password" name="password" class="site-input" required minlength="8" placeholder="Güçlü parola" autocomplete="new-password"></div>' +
      '    </div>' +
      '    <div class="site-studio-row-2" style="align-items:center; margin-top:4px;">' +
      '      <div class="site-field">' +
      '        <label>Hesap Rolü</label>' +
      '        <select name="role" class="site-select" data-role-select="' + esc(sectionKey) + '">' +
      '          <option value="user" selected>👤 Kullanıcı (Seçili Bölümler)</option>' +
      '          <option value="admin">👑 Yönetici (Tüm Bölümler + Kullanıcı Ekleme)</option>' +
      '        </select>' +
      '      </div>' +
      '      <div class="site-field">' +
      '        <label>Erişim İzinleri</label>' +
      '        <div style="display:flex; gap:12px; flex-wrap:wrap; padding:8px 0;">' +
      '          <label style="display:inline-flex; align-items:center; gap:5px; margin:0; text-transform:none; letter-spacing:0; cursor:pointer; font-size:0.84rem;"><input type="checkbox" name="sec_fabrika" value="fabrika"' + (sectionKey === 'fabrika' ? ' checked' : '') + ' style="width:auto;"> 🏭 Fabrika</label>' +
      '          <label style="display:inline-flex; align-items:center; gap:5px; margin:0; text-transform:none; letter-spacing:0; cursor:pointer; font-size:0.84rem;"><input type="checkbox" name="sec_video" value="video"' + (sectionKey === 'video' ? ' checked' : '') + ' style="width:auto;"> 🎬 Video</label>' +
      '          <label style="display:inline-flex; align-items:center; gap:5px; margin:0; text-transform:none; letter-spacing:0; cursor:pointer; font-size:0.84rem;"><input type="checkbox" name="sec_muzik" value="muzik"' + (sectionKey === 'muzik' ? ' checked' : '') + ' style="width:auto;"> 🎵 Müzik</label>' +
      '        </div>' +
      '      </div>' +
      '    </div>' +
      (sectionKey === 'fabrika'
        ? '<p style="margin:0 0 10px; font-size:0.78rem; color:#fbbf24;">⚠️ Not: <strong>Fabrika</strong> yetkisi verilen kullanıcılar bilgisayarınızdaki canlı Mac Fabrika köprüsüne komut gönderebilir.</p>'
        : '') +
      '    <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">' +
      '      <button type="submit" class="site-btn site-btn-primary" style="padding:8px 16px; font-size:0.84rem;">➕ Kullanıcı / Yönetici Ekle</button>' +
      '      <span class="site-user-form-msg" style="font-size:0.8rem; color:var(--site-text-dim);" aria-live="polite"></span>' +
      '    </div>' +
      '  </form>' +
      '  <div class="site-user-list-wrap" data-user-list="' + esc(sectionKey) + '" style="margin-top:14px; display:flex; flex-direction:column; gap:8px;">' +
      '    <div class="site-empty">Kullanıcılar yükleniyor…</div>' +
      '  </div>' +
      '</div>';

    var form = slot.querySelector('form');
    if (form) {
      form.addEventListener('submit', function (ev) {
        ev.preventDefault();
        handleCreateUserSubmit(form);
      });
    }
    var refBtn = slot.querySelector('[data-refresh-users]');
    if (refBtn) {
      refBtn.addEventListener('click', function () { window.refreshAllUserLists(); });
    }
  }

  function handleCreateUserSubmit(form) {
    var msgEl = form.querySelector('.site-user-form-msg');
    var username = (form.elements.username.value || '').trim();
    var displayName = (form.elements.display_name.value || '').trim();
    var password = form.elements.password.value || '';
    var role = form.elements.role.value || 'user';
    var sections = [];
    if (form.elements.sec_fabrika && form.elements.sec_fabrika.checked) sections.push('fabrika');
    if (form.elements.sec_video && form.elements.sec_video.checked) sections.push('video');
    if (form.elements.sec_muzik && form.elements.sec_muzik.checked) sections.push('muzik');

    if (msgEl) { msgEl.textContent = '⏳ Oluşturuluyor…'; msgEl.style.color = 'var(--site-text-dim)'; }
    af('/api/admin/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: username,
        display_name: displayName || username,
        password: password,
        role: role,
        sections: role === 'admin' ? ['fabrika', 'video', 'muzik'] : sections
      })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (res.ok && res.d && res.d.success) {
          form.reset();
          var secKey = form.getAttribute('data-section-form');
          var chk = form.elements['sec_' + secKey];
          if (chk) chk.checked = true;
          if (msgEl) { msgEl.textContent = '✅ "' + res.d.user.username + '" eklendi (' + res.d.user.role + ').'; msgEl.style.color = 'var(--site-accent)'; }
          window.refreshAllUserLists();
        } else {
          if (msgEl) { msgEl.textContent = '⚠️ ' + ((res.d && (res.d.detail || res.d.message)) || 'Eklenemedi.'); msgEl.style.color = 'var(--site-danger)'; }
        }
      })
      .catch(function (err) {
        if (msgEl) { msgEl.textContent = '❌ Hata: ' + err.message; msgEl.style.color = 'var(--site-danger)'; }
      });
  }

  window.refreshAllUserLists = function () {
    if (!isAdmin()) return;
    af('/api/admin/users')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !Array.isArray(d.users)) return;
        var allUsers = d.users;
        ['fabrika', 'video', 'muzik'].forEach(function (secKey) {
          var box = document.querySelector('[data-user-list="' + secKey + '"]');
          if (!box) return;
          var filtered = allUsers.filter(function (u) {
            return u.role === 'admin' || (Array.isArray(u.sections) && u.sections.indexOf(secKey) >= 0);
          });
          renderUserRows(box, filtered, secKey);
        });
        var countBadge = document.getElementById('hubUsersCountBadge');
        if (countBadge) countBadge.textContent = '👥 ' + (allUsers.length + 1) + ' Hesap (Kurucu + ' + allUsers.length + ')';
      })
      .catch(function () { });
  };

  function renderUserRows(container, users, sectionKey) {
    container.textContent = '';
    if (!users.length) {
      var empty = document.createElement('div');
      empty.className = 'site-empty';
      empty.textContent = 'Bu bölümde henüz ek kullanıcı/yönetici yok (Kurucu her zaman tam yetkilidir).';
      container.appendChild(empty);
      return;
    }
    users.forEach(function (u) {
      var row = document.createElement('div');
      row.style.cssText = 'display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; padding:10px 12px; border:1px solid var(--site-border); border-radius:10px; background:color-mix(in srgb, var(--site-bg-soft) 72%, transparent);';

      var left = document.createElement('div');
      var title = document.createElement('div');
      title.style.cssText = 'display:flex; align-items:center; gap:8px; flex-wrap:wrap;';
      var strong = document.createElement('strong');
      strong.textContent = (u.display_name || u.username) + ' (@' + u.username + ')';
      var rBadge = document.createElement('span');
      rBadge.className = u.role === 'admin' ? 'site-badge site-badge-free' : 'site-badge';
      rBadge.textContent = u.role === 'admin' ? '👑 Yönetici' : '👤 Kullanıcı';
      title.appendChild(strong);
      title.appendChild(rBadge);
      if (!u.active) {
        var pas = document.createElement('span');
        pas.className = 'site-badge';
        pas.style.color = 'var(--site-danger)';
        pas.textContent = 'Pasif';
        title.appendChild(pas);
      }
      var secs = document.createElement('div');
      secs.style.cssText = 'font-size:0.76rem; color:var(--site-text-dim); margin-top:4px;';
      secs.textContent = 'Bölümler: ' + (u.sections || []).map(function (s) {
        return SECTION_META[s] ? (SECTION_META[s].icon + ' ' + SECTION_META[s].label) : s;
      }).join(' · ');
      left.appendChild(title);
      left.appendChild(secs);

      var actions = document.createElement('div');
      actions.style.cssText = 'display:flex; gap:6px; flex-wrap:wrap;';

      var toggleBtn = document.createElement('button');
      toggleBtn.type = 'button';
      toggleBtn.className = 'site-chip-btn';
      toggleBtn.textContent = u.active ? '⏸️ Askıya Al' : '▶️ Aktifleştir';
      toggleBtn.addEventListener('click', function () {
        af('/api/admin/users/' + encodeURIComponent(u.username), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ active: !u.active })
        }).then(function () { window.refreshAllUserLists(); });
      });

      var delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'site-chip-btn';
      delBtn.style.color = 'var(--site-danger)';
      delBtn.textContent = '🗑️ Sil';
      delBtn.addEventListener('click', function () {
        if (!confirm('"' + u.username + '" kullanıcısını silmek istediğinize emin misiniz? Aktif oturumları anında kapatılır.')) return;
        af('/api/admin/users/' + encodeURIComponent(u.username), { method: 'DELETE' })
          .then(function () { window.refreshAllUserLists(); });
      });

      actions.appendChild(toggleBtn);
      actions.appendChild(delBtn);
      row.appendChild(left);
      row.appendChild(actions);
      container.appendChild(row);
    });
  }

  /* ── ÇOKLU E-POSTA ALICI YÖNETİMİ (/api/contact/recipients) ──────────── */
  window.loadContactRecipients = function () {
    if (!isAdmin()) return;
    var wrap = document.getElementById('contactRecipientsChips');
    if (!wrap) return;
    af('/api/contact/recipients')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !Array.isArray(d.recipients)) return;
        renderRecipientChips(wrap, d.recipients);
      })
      .catch(function () { });
  };

  function renderRecipientChips(wrap, recipients) {
    wrap.textContent = '';
    recipients.forEach(function (email) {
      var pill = document.createElement('span');
      pill.style.cssText = 'display:inline-flex; align-items:center; gap:6px; padding:5px 10px; border-radius:999px; border:1px solid var(--site-border-strong); background:color-mix(in srgb, var(--site-accent) 10%, transparent); font-size:0.8rem;';
      var txt = document.createElement('span');
      txt.textContent = '✉️ ' + email;
      pill.appendChild(txt);
      if (recipients.length > 1) {
        var rm = document.createElement('button');
        rm.type = 'button';
        rm.textContent = '✕';
        rm.title = 'Alıcıyı kaldır';
        rm.style.cssText = 'border:0; background:transparent; color:var(--site-danger); cursor:pointer; font-weight:700; padding:0 2px;';
        rm.addEventListener('click', function () {
          af('/api/contact/recipients?email=' + encodeURIComponent(email), { method: 'DELETE' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
              if (d && Array.isArray(d.recipients)) renderRecipientChips(wrap, d.recipients);
              if (window.loadContactInbox) window.loadContactInbox();
            });
        });
        pill.appendChild(rm);
      }
      wrap.appendChild(pill);
    });
  }

  window.handleAddContactRecipient = function () {
    var inp = document.getElementById('newRecipientEmailInput');
    var st = document.getElementById('recipientStatusMsg');
    var val = inp ? inp.value.trim() : '';
    if (!val) { if (st) st.textContent = '⚠️ Bir e-posta adresi girin.'; return; }
    if (st) st.textContent = '⏳ Ekleniyor…';
    af('/api/contact/recipients', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: val })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (res.ok && res.d && res.d.success) {
          if (inp) inp.value = '';
          if (st) { st.textContent = '✅ Alıcı eklendi (' + res.d.recipients.length + ' aktif adres).'; st.style.color = 'var(--site-accent)'; }
          var wrap = document.getElementById('contactRecipientsChips');
          if (wrap) renderRecipientChips(wrap, res.d.recipients);
          if (window.loadContactInbox) window.loadContactInbox();
        } else {
          if (st) { st.textContent = '⚠️ ' + ((res.d && res.d.detail) || 'Eklenemedi.'); st.style.color = 'var(--site-danger)'; }
        }
      })
      .catch(function (err) { if (st) st.textContent = '❌ Hata: ' + err.message; });
  };

  /* ── ÇOKLU MODEL MÜZİK STÜDYOSU (/api/music/* + ŞELALE) ─────────────── */
  window.loadMusicStudio = function () {
    if (!hasSection('muzik')) return;
    af('/api/music/models')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !Array.isArray(d.models)) return;
        _musicModels = d.models;
        renderMusicModels(d.models);
        if (d.waterfall) renderMusicWaterfall(d.waterfall);
      })
      .catch(function () { });
    window.loadMusicHistory();
  };

  function renderMusicWaterfall(wf) {
    var box = document.getElementById('musicWaterfallSummary');
    if (!box || !wf || !wf.providers) return;
    box.textContent = '';
    Object.keys(wf.providers).forEach(function (k) {
      var p = wf.providers[k];
      var chip = document.createElement('span');
      chip.className = p.healthy_keys > 0 ? 'site-badge site-badge-free' : 'site-badge';
      var shortName = k.replace('_API_KEY', '').replace('_API_TOKEN', '');
      var extra = '';
      if (p.leaked_or_invalid_keys > 0) extra += ' · ' + p.leaked_or_invalid_keys + ' engelli';
      if (p.cooldown_keys > 0) extra += ' · ' + p.cooldown_keys + ' soğumada';
      chip.textContent = shortName + ': ' + p.healthy_keys + '/' + p.total_keys + ' hesap' + extra;
      box.appendChild(chip);
    });
  }

  window.resetMusicWaterfall = function () {
    var st = document.getElementById('musicKeySaveStatus');
    af('/api/music/waterfall/reset', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.waterfall) renderMusicWaterfall(d.waterfall);
        if (d && Array.isArray(d.models)) renderMusicModels(d.models);
        if (st) { st.textContent = '🔄 Şelale sağlık tablosu sıfırlandı (' + (d.cleared_count || 0) + ' kayıt).'; st.style.color = 'var(--site-accent)'; }
      })
      .catch(function () { });
  };

  function renderMusicModels(models) {
    var sel = document.getElementById('musicModelSelect');
    var grid = document.getElementById('musicModelsStatusGrid');
    var badge = document.getElementById('musicReadyCountBadge');
    var readyN = models.filter(function (m) { return m.ready; }).length;
    if (badge) {
      badge.textContent = readyN > 0 ? ('🟢 ' + readyN + '/' + models.length + ' Model Hazır') : ('⚙️ 0/' + models.length + ' Anahtar Gerekli');
      badge.className = readyN > 0 ? 'site-badge site-badge-free' : 'site-badge';
    }
    if (sel) {
      var prev = sel.value;
      sel.textContent = '';
      models.forEach(function (m) {
        var opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = (m.ready ? '🟢 ' : '🔑 ') + m.name + ' (' + m.status_text + ')';
        sel.appendChild(opt);
      });
      if (prev) sel.value = prev;
    }
    if (grid) {
      grid.textContent = '';
      models.forEach(function (m) {
        var card = document.createElement('div');
        card.style.cssText = 'border:1px solid var(--site-border); border-radius:10px; padding:10px 12px; background:color-mix(in srgb, var(--site-bg-soft) 72%, transparent);';
        var top = document.createElement('div');
        top.style.cssText = 'display:flex; justify-content:space-between; gap:6px; align-items:center; flex-wrap:wrap;';
        var nm = document.createElement('strong');
        nm.style.fontSize = '0.84rem';
        nm.textContent = m.name;
        var st = document.createElement('span');
        st.className = m.ready ? 'site-badge site-badge-free' : 'site-badge';
        st.style.fontSize = '0.7rem';
        st.textContent = m.status_text;
        top.appendChild(nm);
        top.appendChild(st);
        var desc = document.createElement('p');
        desc.style.cssText = 'margin:5px 0 0; font-size:0.76rem; color:var(--site-text-dim);';
        desc.textContent = m.description;
        card.appendChild(top);
        card.appendChild(desc);
        grid.appendChild(card);
      });
    }
  }

  var _musicRefAudioB64 = null;
  var _musicRefAudioJobId = null;

  window.useTrackAsMusicRef = function (jobId, promptText, taskType) {
    _musicRefAudioJobId = jobId;
    _musicRefAudioB64 = null;
    var taskSel = document.getElementById('musicTaskSelect');
    if (taskSel) taskSel.value = taskType || 'cover';
    var modelSel = document.getElementById('musicModelSelect');
    if (modelSel) modelSel.value = 'gpu-acestep-1.5';
    window.toggleMusicRefAudioRow();
    var hint = document.getElementById('musicRefAudioSelectedHint');
    if (hint) hint.textContent = '🎵 Referans parça seçildi: ' + jobId;
    var pEl = document.getElementById('musicPromptInput');
    if (pEl && promptText && !pEl.value.trim()) pEl.value = promptText;
    if (pEl) pEl.focus();
  };

  window.setMusicPrompt = function (txt) {
    var el = document.getElementById('musicPromptInput');
    if (el) { el.value = txt; el.focus(); }
  };

  window.insertLyricsTag = function (tag) {
    var el = document.getElementById('musicLyricsInput');
    var chk = document.getElementById('musicVocalsCheck');
    if (chk) chk.checked = true;
    if (!el) return;
    var cur = el.value || '';
    el.value = (cur && !cur.endsWith('\n') ? cur + '\n\n' : cur) + tag;
    el.focus();
  };

  window.toggleMusicRefAudioRow = function () {
    var task = (document.getElementById('musicTaskSelect') || {}).value || 'text2music';
    var wrap = document.getElementById('musicRefAudioWrap');
    if (wrap) wrap.hidden = (task === 'text2music');
  };

  window.handleGenerateSongLyrics = function () {
    var topic = ((document.getElementById('musicPromptInput') || {}).value || '').trim();
    var genre = ((document.getElementById('musicGenreSelect') || {}).value || '').trim();
    var mood = ((document.getElementById('musicMoodSelect') || {}).value || '').trim();
    var lang = ((document.getElementById('musicVocalLangSelect') || {}).value || 'tr').trim();
    var dur = parseInt(((document.getElementById('musicDurationSelect') || {}).value || '60'), 10);
    var hud = document.getElementById('musicOutputHud');
    var lyricsEl = document.getElementById('musicLyricsInput');
    var chk = document.getElementById('musicVocalsCheck');
    if (!topic) {
      if (hud) hud.textContent = '⚠️ Önce üst kutuya şarkının temasını veya konusunu yazın.';
      return;
    }
    if (hud) hud.textContent = '✨ AI şarkı sözü yazılıyor ([Verse]/[Chorus] yapısında)…';
    af('/api/music/lyrics/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic: topic, genre: genre, mood: mood, vocal_language: lang, duration_sec: dur })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok || !res.d || !res.d.success) {
          if (hud) hud.textContent = '⚠️ Söz üretilemedi: ' + ((res.d && res.d.detail) || 'Hata');
          return;
        }
        if (lyricsEl) lyricsEl.value = res.d.lyrics || '';
        if (chk) chk.checked = true;
        if (hud) hud.textContent = '✅ Şarkı sözleri hazırlandı (' + (res.d.used_key_label || 'Gemini') + '). İstediğiniz gibi düzenleyip üretebilirsiniz.';
      })
      .catch(function (err) {
        if (hud) hud.textContent = '❌ Söz üretim hatası: ' + err.message;
      });
  };

  (function _bindMusicRefAudioInput() {
    document.addEventListener('change', function (ev) {
      if (!ev.target || ev.target.id !== 'musicRefAudioInput') return;
      var f = ev.target.files && ev.target.files[0];
      if (!f) { _musicRefAudioB64 = null; return; }
      var reader = new FileReader();
      reader.onload = function () { _musicRefAudioB64 = reader.result || null; };
      reader.readAsDataURL(f);
    });
  })();

  window.handleMusicGenerateSubmit = function (ev) {
    if (ev && ev.preventDefault) ev.preventDefault();
    var modelId = (document.getElementById('musicModelSelect') || {}).value || 'gpu-acestep-1.5';
    var prompt = ((document.getElementById('musicPromptInput') || {}).value || '').trim();
    var genre = ((document.getElementById('musicGenreSelect') || {}).value || '').trim();
    var mood = ((document.getElementById('musicMoodSelect') || {}).value || '').trim();
    var duration = parseInt(((document.getElementById('musicDurationSelect') || {}).value || '60'), 10);
    var instrumental = !((document.getElementById('musicVocalsCheck') || {}).checked);
    var lyrics = ((document.getElementById('musicLyricsInput') || {}).value || '').trim();
    var vocalLanguage = ((document.getElementById('musicVocalLangSelect') || {}).value || 'tr').trim();
    var bpmRaw = ((document.getElementById('musicBpmInput') || {}).value || '').trim();
    var keyScale = ((document.getElementById('musicKeyScaleInput') || {}).value || '').trim();
    var musicTask = ((document.getElementById('musicTaskSelect') || {}).value || 'text2music').trim();
    var hud = document.getElementById('musicOutputHud');
    var badge = document.getElementById('musicTaskBadge');
    var btn = document.getElementById('startMusicBtn');

    if (!prompt) {
      if (hud) hud.textContent = '⚠️ Lütfen müzik tarzını ve temasını tarif eden bir prompt yazın.';
      return;
    }
    if (btn) { btn.disabled = true; btn.textContent = '🎼 Üretiliyor…'; }
    if (badge) badge.textContent = 'Çalışıyor…';
    if (hud) hud.textContent = 'Gerçek müzik modeline istek gönderiliyor (' + modelId + ')…';

    var payload = {
      model_id: modelId,
      prompt: prompt,
      genre: genre,
      mood: mood,
      duration_sec: duration,
      instrumental: instrumental,
      lyrics: lyrics,
      vocal_language: vocalLanguage,
      key_scale: keyScale,
      music_task: musicTask
    };
    if (bpmRaw) payload.bpm = parseInt(bpmRaw, 10);
    if (musicTask !== 'text2music') {
      if (_musicRefAudioB64) payload.ref_audio_base64 = _musicRefAudioB64;
      else if (_musicRefAudioJobId) payload.ref_music_job_id = _musicRefAudioJobId;
      var covRaw = ((document.getElementById('musicCoverStrengthInput') || {}).value || '').trim();
      var rsRaw = ((document.getElementById('musicRepaintStartInput') || {}).value || '').trim();
      var reRaw = ((document.getElementById('musicRepaintEndInput') || {}).value || '').trim();
      if (covRaw) payload.audio_cover_strength = parseFloat(covRaw);
      if (rsRaw) payload.repaint_start = parseFloat(rsRaw);
      if (reRaw) payload.repaint_end = parseFloat(reRaw);
    }

    af('/api/music/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok || !res.d || !res.d.success) {
          if (badge) badge.textContent = 'Eksik / Hata';
          if (hud) hud.textContent = '⚠️ ' + ((res.d && res.d.detail) || 'Müzik başlatılamadı.');
          return;
        }
        var job = res.d.job;
        if (job.status === 'queued_gpu') {
          if (badge) { badge.textContent = '⚡ GPU Kuyruğunda'; badge.className = 'site-badge site-badge-auto'; }
          if (hud) hud.textContent = '⚡ ' + (job.model_name || 'Kaggle GPU Müzik') + ' kuyruğuna alındı (' + job.job_id + '). GPU işçisi bağlıysa otomatik üretilip yüklenecektir…';
        } else {
          if (hud) hud.textContent = '🎼 İş başlatıldı (' + job.job_id + ' · ' + job.model_name + '). Ses dosyası hazırlanıyor…';
        }
        pollMusicJob(job.job_id);
      })
      .catch(function (err) {
        if (hud) hud.textContent = '❌ Hata: ' + err.message;
      })
      .finally(function () {
        if (btn) { btn.disabled = false; btn.textContent = '🎼 Gerçek Müzik Üret'; }
      });
  };

  function pollMusicJob(jobId) {
    if (_musicPollTimer) clearInterval(_musicPollTimer);
    var tries = 0;
    _musicPollTimer = setInterval(function () {
      tries += 1;
      if (tries > 240) { clearInterval(_musicPollTimer); return; }
      af('/api/music/job/' + encodeURIComponent(jobId))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d || !d.job) return;
          var job = d.job;
          var badge = document.getElementById('musicTaskBadge');
          var hud = document.getElementById('musicOutputHud');
          var stage = document.getElementById('musicStageArea');
          if (job.status === 'queued_gpu') {
            var pct = Number(job.progress_pct || 0);
            var stg = job.current_stage || 'Kaggle/Colab GPU müzik işçisi bekleniyor';
            var mLabel = job.model_name || (job.model_id === 'gpu-acestep-1.5' ? 'Kaggle GPU ACE-Step 1.5' : 'Kaggle GPU Müzik');
            if (badge) { badge.textContent = pct > 0 ? ('⚡ GPU %' + pct) : '⚡ GPU Kuyruğunda'; badge.className = 'site-badge site-badge-auto'; }
            if (hud) {
              var workerHint = job.gpu_worker_online === false
                ? '\n💡 Şu an canlı GPU işçisi bağlı değil: GPU sekmesinden Kaggle Notebook\'u başlattığınızda bu parça otomatik üretilecektir.'
                : '';
              hud.textContent = '⚡ ' + mLabel + ' (' + job.job_id + ') — ' + stg + (pct > 0 ? (' (%' + pct + ')') : '') + workerHint;
            }
            return;
          }
          if (job.status === 'completed') {
            clearInterval(_musicPollTimer);
            if (badge) { badge.textContent = '✅ Tamamlandı'; badge.className = 'site-badge site-badge-free'; }
            var keyInfo = job.used_key_label ? (' · Hesap: ' + job.used_key_label) : '';
            var traceTxt = (Array.isArray(job.waterfall_trace) && job.waterfall_trace.length > 1)
              ? ('\n🌊 Şelale: ' + job.waterfall_trace.join(' → '))
              : '';
            if (hud) hud.textContent = '✅ ' + job.model_name + ' ile üretildi' + keyInfo + '.' + traceTxt + (job.lyrics ? ('\n\nŞarkı Sözleri / Yapı:\n' + job.lyrics) : '');
            if (stage && job.audio_url) {
              var tk = window.token ? window.token() : '';
              var src = job.audio_url + (tk ? ('&token=' + encodeURIComponent(tk)) : '');
              stage.textContent = '';
              var wrap = document.createElement('div');
              wrap.style.cssText = 'width:100%; padding:14px; text-align:center;';
              var audio = document.createElement('audio');
              audio.controls = true;
              audio.src = src;
              audio.style.width = '100%';
              var dl = document.createElement('a');
              dl.href = src + '&download=1';
              dl.className = 'site-btn site-btn-primary';
              dl.style.cssText = 'margin-top:10px; padding:8px 16px; font-size:0.82rem; display:inline-flex;';
              dl.textContent = '⬇️ Müziği İndir (' + (job.filename || 'parca.mp3') + ')';
              wrap.appendChild(audio);
              wrap.appendChild(dl);
              stage.appendChild(wrap);
            }
            window.loadMusicHistory();
          } else if (job.status === 'delegated_mac') {
            clearInterval(_musicPollTimer);
            if (badge) badge.textContent = '💻 Mac Köprüsünde';
            if (hud) hud.textContent = '💻 Mac Fabrika yanıtı: ' + (job.lyrics || 'İletildi.');
          } else if (job.status === 'failed') {
            clearInterval(_musicPollTimer);
            if (badge) badge.textContent = '❌ Başarısız';
            var fTrace = (Array.isArray(job.waterfall_trace) && job.waterfall_trace.length)
              ? ('\n🌊 Denenen Şelale: ' + job.waterfall_trace.join(' → '))
              : '';
            if (hud) hud.textContent = '❌ Üretim başarısız: ' + (job.error || 'Bilinmeyen hata') + fTrace;
            window.loadMusicStudio();
          }
        });
    }, 2500);
  }

  window.loadMusicHistory = function () {
    var grid = document.getElementById('studioMusicHistoryGrid');
    if (!grid || !hasSection('muzik')) return;
    af('/api/music/history?limit=24')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !Array.isArray(d.items) || !d.items.length) {
          grid.innerHTML = '<div class="site-empty">Henüz üretilmiş müzik parçası yok. Yukarıdan bir model seçip üretebilirsiniz.</div>';
          return;
        }
        var tk = window.token ? window.token() : '';
        grid.textContent = '';
        d.items.forEach(function (it) {
          var card = document.createElement('article');
          card.className = 'site-card';
          card.style.padding = '14px';
          var h = document.createElement('div');
          h.style.cssText = 'display:flex; justify-content:space-between; gap:8px; margin-bottom:6px; flex-wrap:wrap;';
          var st = document.createElement('strong');
          st.style.fontSize = '0.86rem';
          st.textContent = it.model_name || it.model_id;
          var dt = document.createElement('span');
          dt.style.cssText = 'font-size:0.74rem; color:var(--site-text-faint);';
          dt.textContent = (it.duration_sec || 30) + ' sn';
          h.appendChild(st); h.appendChild(dt);

          var p = document.createElement('p');
          p.style.cssText = 'margin:0 0 10px; font-size:0.8rem; color:var(--site-text-dim);';
          p.textContent = it.prompt || '';

          card.appendChild(h);
          card.appendChild(p);
          if (it.audio_url) {
            var src = it.audio_url + (tk ? ('&token=' + encodeURIComponent(tk)) : '');
            var au = document.createElement('audio');
            au.controls = true;
            au.src = src;
            au.style.width = '100%';
            var dl = document.createElement('a');
            dl.href = src + '&download=1';
            dl.className = 'site-chip-btn';
            dl.style.cssText = 'text-decoration:none; display:inline-block; margin-top:8px; margin-right:6px;';
            dl.textContent = '⬇️ İndir';
            var covBtn = document.createElement('button');
            covBtn.type = 'button';
            covBtn.className = 'site-chip-btn';
            covBtn.style.marginTop = '8px';
            covBtn.textContent = '🔁 Cover / Uzat';
            covBtn.onclick = function () { window.useTrackAsMusicRef(it.job_id, it.prompt || '', 'cover'); };
            card.appendChild(au);
            card.appendChild(dl);
            card.appendChild(covBtn);
          }
          grid.appendChild(card);
        });
      });
  };

  window.saveMusicApiKeys = function (appendMode) {
    var st = document.getElementById('musicKeySaveStatus');
    var payload = { append: appendMode !== false };
    var map = {
      GEMINI_API_KEY: 'musicKeyGemini',
      ELEVENLABS_API_KEY: 'musicKeyElevenlabs',
      STABILITY_API_KEY: 'musicKeyStability',
      REPLICATE_API_TOKEN: 'musicKeyReplicate'
    };
    var any = false;
    Object.keys(map).forEach(function (k) {
      var el = document.getElementById(map[k]);
      var v = el ? el.value.trim() : '';
      if (v) { payload[k] = v; any = true; }
    });
    if (!any) {
      if (st) st.textContent = '⚠️ En az bir sağlayıcı anahtarı girin.';
      return;
    }
    if (st) st.textContent = '⏳ Şelaleye kaydediliyor…';
    af('/api/music/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (res.ok && res.d && res.d.success) {
          Object.keys(map).forEach(function (k) {
            var el = document.getElementById(map[k]);
            if (el) el.value = '';
          });
          if (st) { st.textContent = '✅ Anahtarlar 0600 izinle şelaleye eklendi ve soğuma sıfırlandı!'; st.style.color = 'var(--site-accent)'; }
          if (Array.isArray(res.d.models)) renderMusicModels(res.d.models);
          if (res.d.waterfall) renderMusicWaterfall(res.d.waterfall);
        } else {
          if (st) { st.textContent = '⚠️ ' + ((res.d && res.d.detail) || 'Kaydedilemedi.'); st.style.color = 'var(--site-danger)'; }
        }
      })
      .catch(function (err) { if (st) st.textContent = '❌ Hata: ' + err.message; });
  };
})();
