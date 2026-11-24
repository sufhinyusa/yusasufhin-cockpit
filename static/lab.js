/* lab.js — Birleşik Üretim Stüdyosu (Video, Gemini TTS, YouTube v3, GPU İşçisi, Mac Port-443 Köprüsü)
 *
 * Sıfır yetkisiz 401: Önce /api/auth/check ile oturum doğrulanır; oturum yoksa
 * hiçbir özel API isteği yapılmaz ve temiz giriş kapısı gösterilir.
 */
(function () {
  'use strict';

  var TOKEN_KEY = 'fabrika_token';
  var _liveGpuWorkersCount = 0;
  var _studioCatalogCache = null;
  var _studioVideoUploadedB64 = null;
  var _burcCatalogLoaded = false;

  function token() {
    try { return localStorage.getItem(TOKEN_KEY) || localStorage.getItem('cockpit_token') || ''; } catch (e) { return ''; }
  }
  window.token = token;

  function esc(metin) {
    return String(metin === null || metin === undefined ? '' : metin)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
  window.esc = esc;

  function showAuthGate(msg) {
    var gate = document.getElementById('labAuthGate');
    var shell = document.getElementById('labAppShell');
    var err = document.getElementById('labLoginError');
    if (shell) shell.hidden = true;
    if (gate) gate.hidden = false;
    if (err && msg) err.textContent = msg;
    var inp = document.getElementById('labLoginSecret');
    if (inp) inp.focus();
  }

  function showAppShell() {
    var gate = document.getElementById('labAuthGate');
    var shell = document.getElementById('labAppShell');
    if (gate) gate.hidden = true;
    if (shell) shell.hidden = false;
  }

  window.authFetch = function (url, opts) {
    var options = Object.assign({}, opts || {});
    var cur = token();
    if (!cur) {
      showAuthGate('Oturum gerekli. Lütfen giriş yapın.');
      return Promise.resolve(new Response(JSON.stringify({ detail: 'Yetkilendirme gerekli.' }), { status: 401 }));
    }
    var headers = Object.assign({}, options.headers || {});
    headers['Authorization'] = 'Bearer ' + cur;
    return fetch(url, Object.assign({}, options, { headers: headers })).then(function (res) {
      if (res.status === 401) {
        try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem('cockpit_token'); } catch (e) { }
        showAuthGate('Oturum süresi doldu; lütfen tekrar giriş yapın.');
      }
      return res;
    });
  };

  /* ── GİRİŞ & ÇIKIŞ ──────────────────────────────────────────────────── */
  var loginForm = document.getElementById('labLoginForm');
  if (loginForm) {
    loginForm.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var inp = document.getElementById('labLoginSecret');
      var err = document.getElementById('labLoginError');
      var btn = document.getElementById('labLoginSubmit');
      var val = inp ? inp.value.trim() : '';
      if (!val) { if (err) err.textContent = 'Parola veya 6 haneli PIN girin.'; return; }
      if (err) err.textContent = '';
      if (btn) { btn.disabled = true; btn.textContent = 'Doğrulanıyor…'; }

      var isPin = /^\d{6}$/.test(val);
      fetch(isPin ? '/api/auth/verify_pin' : '/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(isPin ? { pin: val } : { password: val })
      })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (res.ok && res.d && res.d.token) {
            try {
              localStorage.setItem(TOKEN_KEY, res.d.token);
              localStorage.setItem('cockpit_token', res.d.token);
            } catch (e) { }
            if (inp) inp.value = '';
            bootstrapStudio();
          } else {
            if (err) err.textContent = (res.d && (res.d.detail || res.d.message)) || 'Giriş başarısız.';
          }
        })
        .catch(function () { if (err) err.textContent = 'Sunucuya ulaşılamadı.'; })
        .finally(function () { if (btn) { btn.disabled = false; btn.textContent = 'Giriş Yap'; } });
    });
  }

  var logoutBtn = document.getElementById('labLogoutBtn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', function () {
      var tk = token();
      if (tk) fetch('/api/auth/logout', { method: 'POST', headers: { Authorization: 'Bearer ' + tk } }).catch(function () { });
      try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem('cockpit_token'); } catch (e) { }
      showAuthGate('Oturum kapatıldı.');
    });
  }

  /* ── SEKME GEÇİŞİ (5 NET SEKME) ─────────────────────────────────────── */
  window.switchStudioView = function (viewKey) {
    var viewMap = {
      video: 'viewVideoStudio',
      audio: 'viewAudioStudio',
      channels: 'viewChannelsStudio',
      gpu: 'viewGpuStudio',
      mac: 'viewMacStudio'
    };
    var tabMap = {
      video: 'tabNavVideo',
      audio: 'tabNavAudio',
      channels: 'tabNavChannels',
      gpu: 'tabNavGpu',
      mac: 'tabNavMac'
    };
    if (!viewMap[viewKey]) viewKey = 'video';
    Object.keys(viewMap).forEach(function (k) {
      var vEl = document.getElementById(viewMap[k]);
      var tEl = document.getElementById(tabMap[k]);
      if (vEl) vEl.hidden = (k !== viewKey);
      if (tEl) {
        if (k === viewKey) tEl.classList.add('active');
        else tEl.classList.remove('active');
      }
    });

    if (viewKey === 'video') {
      window.loadChannelsCatalog(false);
      window.loadStudioQueue();
      window.loadVideoHistory();
    } else if (viewKey === 'audio') {
      window.loadAudioHistory();
    } else if (viewKey === 'channels') {
      window.loadChannelsCatalog(true);
    } else if (viewKey === 'gpu') {
      window.refreshGpuStatus();
    } else if (viewKey === 'mac') {
      window.refreshMacBridgeStatus();
      window.refreshLabReaHistory();
    }
  };

  /* ── VİDEO STÜDYOSU YARDIMCILARI ────────────────────────────────────── */
  window.setStudioPrompt = function (txt) {
    var el = document.getElementById('videoPromptInput');
    if (el) { el.value = txt; el.focus(); }
  };

  function _bindUploadAndExtras() {
    var imgInp = document.getElementById('studioVideoImageInput');
    if (imgInp && !imgInp.getAttribute('data-bound')) {
      imgInp.setAttribute('data-bound', '1');
      imgInp.addEventListener('change', function () {
        var f = imgInp.files && imgInp.files[0];
        if (!f) return;
        var r = new FileReader();
        r.onload = function (ev) {
          _studioVideoUploadedB64 = ev.target.result;
          var w = document.getElementById('studioVideoUploadedWrap');
          var img = document.getElementById('studioVideoUploadedImg');
          if (img) img.src = _studioVideoUploadedB64;
          if (w) w.hidden = false;
        };
        r.readAsDataURL(f);
      });
    }
    var clr = document.getElementById('studioVideoClearImgBtn');
    if (clr && !clr.getAttribute('data-bound')) {
      clr.setAttribute('data-bound', '1');
      clr.addEventListener('click', function () {
        _studioVideoUploadedB64 = null;
        var inp = document.getElementById('studioVideoImageInput');
        if (inp) inp.value = '';
        var w = document.getElementById('studioVideoUploadedWrap');
        if (w) w.hidden = true;
      });
    }
    var wfSel = document.getElementById('videoMethodSelect');
    var urlWrap = document.getElementById('videoSourceUrlWrap');
    if (wfSel && urlWrap && !wfSel.getAttribute('data-bound')) {
      wfSel.setAttribute('data-bound', '1');
      var syncUrl = function () { urlWrap.hidden = !(wfSel.value === 'product_launch' || wfSel.value === 'hyperframes_motion'); };
      wfSel.addEventListener('change', syncUrl);
      syncUrl();
    }
  }

  function loadBurcCatalog() {
    if (_burcCatalogLoaded) return;
    fetch('/api/burc/list')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var sel = document.getElementById('burcSignSelect');
        if (!sel || !d || !Array.isArray(d.items)) return;
        _burcCatalogLoaded = true;
        sel.innerHTML = '<option value="">— Genel (Burç şablonu yok) —</option>' +
          d.items.map(function (burc) {
            return '<option value="' + esc(burc.slug) + '">' + esc((burc.simge || '') + ' ' + burc.ad + ' (' + burc.tarih + ')') + '</option>';
          }).join('');
      })
      .catch(function () { });
  }

  function _setSteps(doneUpTo, activeIdx) {
    for (var i = 1; i <= 4; i++) {
      var el = document.getElementById('step' + i);
      if (!el) continue;
      if (i <= doneUpTo) el.className = 'site-pipeline-step done';
      else if (i === activeIdx) el.className = 'site-pipeline-step active';
      else el.className = 'site-pipeline-step';
    }
  }

  function _renderPreviewApprove(task, i2vModel, tok) {
    var stage = document.getElementById('studioStageArea');
    var badge = document.getElementById('studioTaskBadge');
    var rawPrev = task.preview_image_url || task.output_url || '';
    var pUrl = rawPrev + (rawPrev.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(tok || '');
    _setSteps(2, 3);
    if (badge) badge.textContent = '🖼️ Görsel Hazır (Onay Bekliyor)';
    if (stage) {
      stage.innerHTML =
        '<div style="padding:10px; width:100%; text-align:center;">' +
        '<img src="' + esc(pUrl) + '" alt="Anahtar kare önizleme">' +
        '<div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:center; margin-top:10px;">' +
        '<button type="button" id="studioApproveI2vBtn" class="site-btn site-btn-primary">✅ Beğendim → ' + esc(i2vModel) + ' ile Videoya Çevir</button>' +
        '<button type="button" id="studioRegenImgBtn" class="site-btn site-btn-ghost">🔄 Yeniden Üret</button>' +
        '</div></div>';
      var aBtn = document.getElementById('studioApproveI2vBtn');
      if (aBtn) aBtn.onclick = function () {
        var mod = (_liveGpuWorkersCount > 0) ? 'gpu_queue' : 'real_i2v';
        window.handleStudioVideoSubmit(null, 'wan_i2v', rawPrev, mod);
      };
      var rBtn = document.getElementById('studioRegenImgBtn');
      if (rBtn) rBtn.onclick = function () { window.handleStudioVideoSubmit(null, 'image_first_preview'); };
    }
  }

  function _renderVideoPlayer(task, tok) {
    var stage = document.getElementById('studioStageArea');
    var badge = document.getElementById('studioTaskBadge');
    var hud = document.getElementById('studioHudLog');
    var outUrl = task.output_url || '';
    var tamUrl = outUrl ? (outUrl + (outUrl.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(tok)) : '';
    var indirUrl = tamUrl ? (tamUrl + '&download=1') : '';
    var boyut = (task.artifacts && task.artifacts.file_size_bytes) || task.file_size_bytes || 0;
    var kb = boyut ? (Number(boyut) / 1024).toFixed(0) + ' KB' : '';
    _setSteps(3, 4);

    var label = task.video_difuzyonu
      ? '✅ Gerçek I2V Video'
      : (task.simulasyon ? '⚠️ Bulut Kurgu (simülasyon)' : '✅ Video Hazır');
    if (badge) {
      badge.textContent = label;
      badge.className = task.simulasyon ? 'site-badge site-badge-auto' : 'site-badge site-badge-free';
    }
    if (hud) {
      hud.innerHTML += '<br>• ✅ <code>' + esc(task.job_id) + '</code> hazır (' + esc(task.kaynak || task.method || '-') + ' ' + esc(kb) + ')';
    }
    if (stage) {
      stage.innerHTML =
        '<div style="padding:8px; width:100%;">' +
        '<video controls autoplay playsinline preload="metadata" src="' + esc(tamUrl) + '" style="background:#000; margin-bottom:10px;"></video>' +
        '<div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:center;">' +
        '<a href="' + esc(indirUrl) + '" download="video-' + esc(task.job_id) + '.mp4" class="site-btn site-btn-primary" style="padding:8px 14px; font-size:0.82rem;">⬇️ MP4 İndir</a>' +
        '<button type="button" class="site-btn site-btn-ghost" style="padding:8px 14px; font-size:0.82rem;" onclick="requeueStudioJob(\'' + esc(task.job_id) + '\')">🚀 GPU Yükselt</button>' +
        '<button type="button" class="site-btn site-btn-ghost" style="padding:8px 14px; font-size:0.82rem;" onclick="publishJobToYoutube(\'' + esc(task.job_id) + '\')">📤 YouTube\'a Yükle</button>' +
        '</div></div>';
    }
    window.loadVideoHistory();
    window.loadStudioQueue();
  }

  window.pollLabJob = function (jobId, onUpdate, onFail, maxAttempts) {
    var tries = 0;
    var limit = maxAttempts || 120;
    var timer = setInterval(function () {
      tries += 1;
      if (tries > limit) {
        clearInterval(timer);
        if (onFail) onFail('Zaman aşımı: GPU işçisi yanıt vermedi.');
        return;
      }
      window.authFetch('/api/lab/job/' + encodeURIComponent(jobId))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data || !data.success || !data.job) return;
          var j = data.job;
          if (onUpdate) onUpdate(j);
          if (j.gpu_durum === 'basarisiz' || j.status === 'basarisiz' || j.gpu_durum === 'iptal') {
            clearInterval(timer);
            if (onFail) onFail(j.error || 'İş tamamlanamadı.');
            return;
          }
          if (j.output_url || ((j.mode === 'flux2_resim' || j.mode === 'image_first_preview') && j.preview_image_url)) {
            clearInterval(timer);
          }
        })
        .catch(function () { });
    }, 4000);
  };

  window.handleStudioVideoSubmit = function (e, forcedWorkflow, approvedImageUrl, forcedExecMode) {
    if (e && e.preventDefault) e.preventDefault();
    var channel = (document.getElementById('videoChannelSelect') || {}).value || 'Tech_AI_Fabrika';
    var workflow = forcedWorkflow || (document.getElementById('videoMethodSelect') || {}).value || 'image_first_preview';
    if (approvedImageUrl && workflow !== 'wan_i2v') workflow = 'wan_i2v';
    if (!approvedImageUrl && _studioVideoUploadedB64 && workflow === 'image_first_preview') workflow = 'wan_i2v';

    var burcSlug = (document.getElementById('burcSignSelect') || {}).value || '';
    var rawCheckEl = document.getElementById('burcRawPromptCheck');
    var rawPrompt = rawCheckEl ? Boolean(rawCheckEl.checked) : true;
    var stylePreset = (document.getElementById('videoStyleSelect') || {}).value || 'cinematic_realism';
    var imageModel = (document.getElementById('videoImageModelSelect') || {}).value || 'flux2-klein';
    var i2vModel = (document.getElementById('videoI2vModelSelect') || {}).value || 'wan2.1-i2v-14b';
    var aspect = (document.getElementById('videoAspectSelect') || {}).value || '16:9';
    var duration = Number((document.getElementById('videoDurationSelect') || {}).value || 5);
    var cameraMotion = (document.getElementById('videoCameraSelect') || {}).value || 'otomatik';
    var voiceVal = (document.getElementById('videoVoiceSelect') || {}).value || 'Aoede';
    var promptVal = ((document.getElementById('videoPromptInput') || {}).value || '').trim();
    var negVal = ((document.getElementById('videoNegPromptInput') || {}).value || '').trim();
    var sourceUrlVal = ((document.getElementById('videoSourceUrlInput') || {}).value || '').trim();
    var execMode = forcedExecMode || (document.getElementById('videoExecModeSelect') || {}).value || 'auto';
    if (!forcedExecMode && workflow === 'wan_i2v' && execMode === 'auto' && _liveGpuWorkersCount <= 0) {
      execMode = 'real_i2v';
    }

    if (!promptVal && !burcSlug && !approvedImageUrl && !_studioVideoUploadedB64 && !sourceUrlVal) {
      alert('Lütfen sahne promptu yazın, bir burç şablonu seçin veya görsel yükleyin.');
      return;
    }

    var badge = document.getElementById('studioTaskBadge');
    var hud = document.getElementById('studioHudLog');
    var stage = document.getElementById('studioStageArea');
    if (badge) { badge.textContent = '⏳ İşleniyor…'; badge.className = 'site-badge site-badge-auto'; }
    if (hud) {
      hud.innerHTML = '• Kanal: <strong>' + esc(channel) + '</strong> · Akış: <code>' + esc(workflow) + '</code> · Mod: <code>' + esc(execMode) + '</code>';
    }
    _setSteps(1, 2);

    var useBurcEndpoint = Boolean(burcSlug) && workflow !== 'product_launch' && workflow !== 'hyperframes_motion';
    var endpoint = useBurcEndpoint ? '/api/burc/video/generate' : '/api/studio/video/generate';
    var payload = useBurcEndpoint
      ? {
          burc_kodu: burcSlug,
          konu: promptVal,
          raw_prompt: rawPrompt,
          sure_sn: duration,
          aspect_ratio: aspect,
          image_model: imageModel,
          i2v_model: i2vModel,
          method: workflow === 'image_first_preview' ? 'flux2_resim' : workflow,
          execution_mode: execMode,
          voice: voiceVal,
          image_base64: approvedImageUrl ? null : _studioVideoUploadedB64,
          input_image_url: approvedImageUrl || null
        }
      : {
          channel: channel,
          workflow: workflow,
          method: workflow,
          execution_mode: execMode,
          style_preset: stylePreset,
          image_model: imageModel,
          i2v_model: i2vModel,
          render_target: 'kaggle_32gb',
          aspect_ratio: aspect,
          duration: duration,
          camera_motion: cameraMotion,
          prompt: promptVal || 'organic coherent scene motion from reference image',
          negative_prompt: negVal,
          source_url: sourceUrlVal || null,
          voice: voiceVal,
          image_base64: approvedImageUrl ? null : _studioVideoUploadedB64,
          input_image_url: approvedImageUrl || null
        };

    window.authFetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        var data = res.d || {};
        var task = data.task || data;
        if (!res.ok || !data.success || !task || !task.job_id) {
          if (badge) badge.textContent = '❌ Başarısız';
          if (hud) hud.innerHTML += '<br><span style="color:var(--site-danger);">❌ ' + esc(data.detail || data.message || 'Üretim başlatılamadı') + '</span>';
          return;
        }
        var tk = token();
        if (hud && task.image_prompt) {
          hud.innerHTML += '<br>• 🎨 Sahne: <code>' + esc(task.image_prompt) + '</code>';
        }
        if (task.status === 'onizleme_hazir' && (task.preview_image_url || task.output_url)) {
          _renderPreviewApprove(task, i2vModel, tk);
          return;
        }
        if (task.output_url) {
          _renderVideoPlayer(task, tk);
          return;
        }
        if (badge) badge.textContent = '⏳ GPU Kuyruğunda';
        if (stage) {
          stage.innerHTML =
            '<div style="text-align:center; padding:16px;">' +
            '<strong>GPU İşçisi Bekleniyor</strong>' +
            '<p style="margin:6px 0; font-size:0.82rem; color:var(--site-text-dim);">Bilet: <code>' + esc(task.job_id) + '</code> · ' + esc(task.message || '') + '</p>' +
            '<button type="button" class="site-btn site-btn-ghost" onclick="instantRenderQueuedJob(\'' + esc(task.job_id) + '\')">🎞️ Anında Bulut Önizleme (Kamera Hareketi)</button>' +
            '</div>';
        }
        window.loadStudioQueue();
        window.pollLabJob(task.job_id, function (guncel) {
          var liveTk = token();
          if (guncel.output_url && guncel.status !== 'onizleme_hazir') _renderVideoPlayer(guncel, liveTk);
          else if (guncel.preview_image_url) _renderPreviewApprove(guncel, i2vModel, liveTk);
        }, function (errMsg) {
          if (badge) badge.textContent = '⏳ Kuyrukta';
          if (hud) hud.innerHTML += '<br>⚠️ ' + esc(errMsg);
        });
      })
      .catch(function (err) {
        if (badge) badge.textContent = '❌ Hata';
        if (hud) hud.innerHTML += '<br><span style="color:var(--site-danger);">❌ ' + esc(err.message) + '</span>';
      });
  };

  window.handleInstantCloudPreview = function (customPrompt) {
    var promptVal = (typeof customPrompt === 'string' && customPrompt.trim())
      ? customPrompt.trim()
      : (((document.getElementById('videoPromptInput') || {}).value || '').trim());
    if (!promptVal) { alert('Önizleme için sahne promptu girin.'); return; }
    var badge = document.getElementById('studioTaskBadge');
    var hud = document.getElementById('studioHudLog');
    var i2vModel = (document.getElementById('videoI2vModelSelect') || {}).value || 'wan2.1-i2v-14b';
    if (badge) badge.textContent = '⚡ Görsel Üretiliyor…';
    if (hud) hud.innerHTML = '• Bulut anahtar kare üretiliyor: "' + esc(promptVal) + '"';

    window.authFetch('/api/studio/preview-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        channel: (document.getElementById('videoChannelSelect') || {}).value || 'Tech_AI_Fabrika',
        prompt: promptVal,
        style_preset: (document.getElementById('videoStyleSelect') || {}).value || 'cinematic_realism',
        camera_motion: (document.getElementById('videoCameraSelect') || {}).value || 'otomatik',
        aspect_ratio: (document.getElementById('videoAspectSelect') || {}).value || '16:9'
      })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok || !res.d || !res.d.success) {
          if (badge) badge.textContent = '❌ Önizleme Hatası';
          if (hud) hud.innerHTML += '<br><span style="color:var(--site-danger);">❌ ' + esc((res.d && res.d.detail) || 'Üretilemedi') + '</span>';
          return;
        }
        if (hud) hud.innerHTML += '<br>• ✅ Sağlayıcı: <strong>' + esc(res.d.provider || 'cloud') + '</strong><br>• 🎨 <code>' + esc(res.d.image_prompt || '') + '</code>';
        _renderPreviewApprove({ status: 'onizleme_hazir', preview_image_url: res.d.preview_image_url }, i2vModel, token());
      })
      .catch(function (err) {
        if (badge) badge.textContent = '❌ Hata';
        if (hud) hud.innerHTML += '<br>❌ ' + esc(err.message);
      });
  };

  window.handlePlanStoryboard = function () {
    var promptVal = ((document.getElementById('videoPromptInput') || {}).value || '').trim();
    var box = document.getElementById('studioStoryboardBox');
    if (!promptVal || !box) { alert('Storyboard için konu/prompt girin.'); return; }
    box.hidden = false;
    box.innerHTML = '<span style="font-size:0.82rem; color:var(--site-accent);">⏳ 3 sahneli storyboard hazırlanıyor…</span>';
    window.authFetch('/api/studio/storyboard', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: promptVal,
        style_preset: (document.getElementById('videoStyleSelect') || {}).value || 'cinematic_realism',
        camera_motion: (document.getElementById('videoCameraSelect') || {}).value || 'otomatik',
        scene_count: 3,
        duration: Number((document.getElementById('videoDurationSelect') || {}).value || 15)
      })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.success || !Array.isArray(d.scenes)) {
          box.innerHTML = '<span style="color:var(--site-danger);">' + esc((d && d.detail) || 'Storyboard oluşturulamadı.') + '</span>';
          return;
        }
        box.innerHTML = '<div style="font-size:0.8rem; margin-bottom:8px;"><strong>🎙️ Anlatım:</strong> <em>' + esc(d.narration_text || '') + '</em></div>' +
          d.scenes.map(function (s, i) {
            return '<div style="border-top:1px solid var(--site-border); padding-top:6px; margin-top:6px; font-size:0.76rem;">' +
              '<strong>Sahne ' + (i + 1) + ':</strong> <code>' + esc(s.image_prompt) + '</code> ' +
              '<button type="button" class="site-chip-btn" style="margin-left:6px;" data-sb-idx="' + i + '">⚡ Önizle</button></div>';
          }).join('');
        box.querySelectorAll('[data-sb-idx]').forEach(function (b) {
          b.addEventListener('click', function () {
            var sc = d.scenes[Number(b.getAttribute('data-sb-idx'))];
            if (sc) window.handleInstantCloudPreview(sc.image_prompt);
          });
        });
      })
      .catch(function (err) { box.innerHTML = '<span style="color:var(--site-danger);">' + esc(err.message) + '</span>'; });
  };

  /* ── KUYRUK & VİDEO GALERİSİ ────────────────────────────────────────── */
  window.loadStudioQueue = function () {
    var el = document.getElementById('studioQueueList');
    if (!el) return;
    window.authFetch('/api/studio/queue?status=bekliyor&limit=30')
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .then(function (d) {
        var items = (d && Array.isArray(d.items)) ? d.items : [];
        if (!items.length) {
          el.innerHTML = '<div class="site-empty">Bekleyen GPU bileti yok.</div>';
          return;
        }
        el.innerHTML = items.map(function (it) {
          return '<article class="site-card">' +
            '<div style="display:flex; justify-content:space-between; gap:6px; margin-bottom:6px; flex-wrap:wrap;">' +
            '<span class="site-badge site-badge-auto">⏳ ' + esc(it.gpu_durum || 'bekliyor') + '</span>' +
            '<code style="font-size:0.74rem; color:var(--site-text-faint);">' + esc(it.job_id) + '</code></div>' +
            '<h3 style="font-size:0.94rem;">' + esc(it.channel || 'Video') + ' · ' + esc(it.aspect_ratio || '16:9') + '</h3>' +
            '<p style="font-size:0.8rem;">' + esc(it.prompt || '') + '</p>' +
            '<div style="display:flex; gap:8px; flex-wrap:wrap;">' +
            '<button type="button" class="site-btn site-btn-primary" style="padding:6px 12px; font-size:0.78rem;" onclick="instantRenderQueuedJob(\'' + esc(it.job_id) + '\')">⚡ Bulutta Render</button>' +
            '<button type="button" class="site-btn site-btn-ghost" style="padding:6px 12px; font-size:0.78rem;" onclick="cancelQueuedJob(\'' + esc(it.job_id) + '\')">✖ İptal</button>' +
            '</div></article>';
        }).join('');
      })
      .catch(function () { el.innerHTML = '<div class="site-empty">Kuyruk okunamadı.</div>'; });
  };

  window.instantRenderQueuedJob = function (jobId) {
    var badge = document.getElementById('studioTaskBadge');
    if (badge) badge.textContent = '⚡ Bulutta İşleniyor…';
    window.authFetch('/api/studio/queue/' + encodeURIComponent(jobId) + '/instant-render', { method: 'POST' })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok || !res.d || !res.d.task) {
          if (badge) badge.textContent = '❌ Başarısız';
          return;
        }
        var t = res.d.task;
        if (t.status === 'onizleme_hazir') _renderPreviewApprove(t, t.i2v_model || 'wan2.1-i2v-14b', token());
        else _renderVideoPlayer(t, token());
      });
  };

  window.requeueStudioJob = function (jobId) {
    window.authFetch('/api/studio/queue/' + encodeURIComponent(jobId) + '/requeue-gpu', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var hud = document.getElementById('studioHudLog');
        if (hud) hud.innerHTML += '<br>• 🚀 ' + esc((d && d.message) || 'GPU kuyruğuna alındı');
        window.loadStudioQueue();
      });
  };

  window.cancelQueuedJob = function (jobId) {
    window.authFetch('/api/studio/queue/' + encodeURIComponent(jobId) + '/cancel', { method: 'POST' })
      .then(function () { window.loadStudioQueue(); });
  };

  window.loadVideoHistory = function () {
    var grid = document.getElementById('studioVideoHistoryGrid');
    if (!grid) return;
    var tk = token();
    window.authFetch('/api/lab/history?limit=24')
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .then(function (data) {
        var items = (data && data.items) || [];
        if (!items.length) {
          grid.innerHTML = '<div class="site-empty">Henüz üretilmiş video yok.</div>';
          return;
        }
        grid.innerHTML = items.map(function (it) {
          var u = it.output_url || '';
          var tam = u ? (u + (u.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(tk)) : '';
          var kb = it.size_kb || (it.file_size_bytes ? Math.round(Number(it.file_size_bytes) / 1024) : 0);
          return '<article class="site-card">' +
            '<div style="display:flex; justify-content:space-between; gap:6px; margin-bottom:8px; flex-wrap:wrap;">' +
            '<span class="site-badge ' + (it.simulasyon ? 'site-badge-auto' : 'site-badge-free') + '">' + esc(it.status || 'hazır') + '</span>' +
            '<span style="font-size:0.74rem; color:var(--site-text-faint);">' + esc(it.resolution || '') + (kb ? ' · ' + kb + ' KB' : '') + '</span></div>' +
            '<video controls playsinline preload="metadata" src="' + esc(tam) + '" style="width:100%; max-height:220px; border-radius:8px; background:#000; margin-bottom:8px;"></video>' +
            '<p style="font-size:0.8rem; margin:0 0 10px;">' + esc(it.prompt || it.job_id) + '</p>' +
            '<div style="display:flex; gap:6px; flex-wrap:wrap;">' +
            '<a href="' + esc(tam + '&download=1') + '" download="video-' + esc(it.job_id) + '.mp4" class="site-btn site-btn-primary" style="padding:6px 12px; font-size:0.78rem;">⬇️ İndir</a>' +
            '<button type="button" class="site-btn site-btn-ghost" style="padding:6px 10px; font-size:0.78rem;" onclick="publishJobToYoutube(\'' + esc(it.job_id) + '\')">📤 YouTube</button>' +
            '<button type="button" class="site-btn site-btn-ghost" style="padding:6px 10px; font-size:0.78rem;" onclick="requeueStudioJob(\'' + esc(it.job_id) + '\')">🚀 GPU</button>' +
            '</div></article>';
        }).join('');
      })
      .catch(function () { grid.innerHTML = '<div class="site-empty">Video geçmişi alınamadı.</div>'; });
  };

  /* ── SESLENDİRME (GERÇEK GEMINI TTS) ────────────────────────────────── */
  window.handleAudioSubmit = function (e) {
    e.preventDefault();
    var text = ((document.getElementById('audioPromptInput') || {}).value || '').trim();
    var voice = (document.getElementById('audioVoiceSelect') || {}).value || 'Aoede';
    var badge = document.getElementById('audioTaskBadge');
    var stage = document.getElementById('audioStageArea');
    var hud = document.getElementById('audioOutputHud');
    if (!text) { alert('Lütfen seslendirilecek metni yazın.'); return; }

    if (badge) badge.textContent = '⏳ Sentezleniyor…';
    if (hud) hud.innerHTML = 'Gemini 2.5 Neural TTS (' + esc(voice) + ') çalıştırılıyor…';

    window.authFetch('/api/audio/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'voice_clone_tts', params: { text: text, voice: voice } })
    })
      .then(function (r) { return r.json(); })
      .then(function (resp) {
        if (!resp || !resp.success || !resp.data || !resp.data.output_url) {
          if (badge) badge.textContent = '❌ Başarısız';
          if (hud) hud.innerHTML = '❌ ' + esc((resp && (resp.detail || resp.error)) || 'Ses üretilemedi.');
          return;
        }
        var d = resp.data;
        var tk = token();
        var tam = d.output_url + (d.output_url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(tk);
        if (badge) {
          badge.textContent = d.simulasyon ? '⚠️ Önizleme (simülasyon)' : '✅ Hazır (WAV)';
          badge.className = d.simulasyon ? 'site-badge site-badge-auto' : 'site-badge site-badge-free';
        }
        if (hud) hud.innerHTML = '✅ Motor: <strong>' + esc(d.engine || '-') + '</strong> · Süre: <strong>' + esc(d.duration_sec || '-') + ' sn</strong>';
        if (stage) {
          stage.innerHTML =
            '<div style="width:100%; padding:10px;">' +
            '<audio controls autoplay preload="metadata" src="' + esc(tam) + '" style="width:100%; margin-bottom:10px;"></audio>' +
            '<a href="' + esc(tam + '&download=1') + '" download="tts-' + esc(d.job_id) + '.wav" class="site-btn site-btn-primary" style="padding:8px 16px; font-size:0.82rem;">⬇️ WAV İndir</a>' +
            '</div>';
        }
        window.loadAudioHistory();
      })
      .catch(function (err) {
        if (badge) badge.textContent = '❌ Hata';
        if (hud) hud.innerHTML = '❌ ' + esc(err.message);
      });
  };

  window.loadAudioHistory = function () {
    var grid = document.getElementById('studioAudioHistoryGrid');
    if (!grid) return;
    var tk = token();
    window.authFetch('/api/audio/history?limit=18')
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .then(function (data) {
        var items = (data && data.items) || [];
        if (!items.length) { grid.innerHTML = '<div class="site-empty">Henüz ses kaydı yok.</div>'; return; }
        grid.innerHTML = items.map(function (it) {
          var u = it.output_url || '';
          var tam = u ? (u + (u.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(tk)) : '';
          return '<article class="site-card">' +
            '<div style="display:flex; justify-content:space-between; gap:6px; margin-bottom:6px;">' +
            '<span class="site-badge ' + (it.simulasyon ? 'site-badge-auto' : 'site-badge-free') + '">' + esc(it.status || 'hazır') + '</span>' +
            '<span style="font-size:0.74rem; color:var(--site-text-faint);">' + esc(it.duration_sec || '') + ' sn</span></div>' +
            '<p style="font-size:0.8rem; margin:0 0 8px;">' + esc(it.prompt || it.job_id) + '</p>' +
            '<audio controls preload="none" src="' + esc(tam) + '" style="width:100%; margin-bottom:8px;"></audio>' +
            '<a href="' + esc(tam + '&download=1') + '" download="' + esc(it.job_id) + '.wav" class="site-btn site-btn-ghost" style="padding:6px 12px; font-size:0.78rem;">⬇️ WAV İndir</a>' +
            '</article>';
        }).join('');
      })
      .catch(function () { grid.innerHTML = '<div class="site-empty">Ses geçmişi alınamadı.</div>'; });
  };

  /* ── YOUTUBE KANALLARI & CANLI YÜKLEME ──────────────────────────────── */
  function _fillSelect(selectId, items, labelKey) {
    var sel = document.getElementById(selectId);
    if (!sel || !Array.isArray(items)) return;
    var prev = sel.value;
    sel.innerHTML = items.map(function (it) {
      return '<option value="' + esc(it.id || '') + '">' + esc(it[labelKey] || it.name || it.ad || it.id) + '</option>';
    }).join('');
    if (prev && items.some(function (it) { return it.id === prev; })) sel.value = prev;
  }

  window.loadChannelsCatalog = function (force) {
    if (_studioCatalogCache && !force) return Promise.resolve(_studioCatalogCache);
    return window.authFetch('/api/studio/catalog')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.success) return d;
        _studioCatalogCache = d;
        _fillSelect('videoChannelSelect', d.channels, 'name');
        _fillSelect('videoStyleSelect', d.styles, 'ad');
        _fillSelect('videoImageModelSelect', d.image_models, 'ad');
        _fillSelect('videoI2vModelSelect', d.i2v_models, 'ad');
        _fillSelect('chImageModelSelect', d.image_models, 'ad');
        _fillSelect('chI2vModelSelect', d.i2v_models, 'ad');
        renderChannelsManager(d);
        return d;
      })
      .catch(function () { });
  };

  function renderChannelsManager(d) {
    var grid = document.getElementById('channelsListGrid');
    var ytBox = document.getElementById('youtubeAuthBox');
    var ytBadge = document.getElementById('ytAuthBadge');
    var yt = (d && d.youtube_auth) || {};
    if (ytBadge) {
      ytBadge.textContent = yt.ready_for_live_upload ? '🟢 Canlı YouTube API Hazır' : '🟡 OAuth Gerekli';
      ytBadge.className = yt.ready_for_live_upload ? 'site-badge site-badge-free' : 'site-badge site-badge-auto';
    }
    if (ytBox) {
      ytBox.innerHTML =
        '• Durum: <strong>' + esc(yt.ready_for_live_upload ? 'Aktif (Saf HTTP Resumable v3)' : 'Bağlı Değil') + '</strong><br>' +
        '• Kalıcılık: <code>' + esc(yt.persistence_mode || 'none') + '</code> · Client Secret: <strong>' + (yt.client_secret_present ? 'Var' : 'Yok') + '</strong> · Token: <strong>' + (yt.oauth_token_present ? 'Var' : 'Yok') + '</strong><br>' +
        '• ' + esc(yt.message || '');
    }
    if (!grid || !Array.isArray(d.channels)) return;
    grid.innerHTML = d.channels.map(function (ch) {
      return '<div class="site-channel-card">' +
        '<div style="display:flex; justify-content:space-between; gap:6px;">' +
        '<div><strong>' + esc(ch.name) + '</strong><div style="font-size:0.75rem; color:var(--site-text-dim);">' + esc(ch.handle || ch.id) + ' · ' + esc(ch.aspect_ratio) + '</div></div>' +
        '<span class="site-badge">' + (ch.youtube_connected ? '🟢 YT' : '⚪ Taslak') + '</span></div>' +
        '<div style="font-size:0.76rem; color:var(--site-text-dim);">' + esc(ch.image_model) + ' → ' + esc(ch.i2v_model) + ' · Ses: ' + esc(ch.voice) + '</div>' +
        '<div style="display:flex; gap:6px; margin-top:auto;">' +
        '<button type="button" class="site-btn site-btn-primary" style="padding:6px 10px; font-size:0.76rem; flex:1;" onclick="useChannelInStudio(\'' + esc(ch.id) + '\')">🎬 Kullan</button>' +
        '<button type="button" class="site-btn site-btn-ghost" style="padding:6px 10px; font-size:0.76rem;" onclick="editChannel(\'' + esc(ch.id) + '\')">✏️</button>' +
        '<button type="button" class="site-btn site-btn-ghost" style="padding:6px 10px; font-size:0.76rem;" onclick="deleteChannel(\'' + esc(ch.id) + '\')">🗑️</button>' +
        '</div></div>';
    }).join('');
  }

  window.useChannelInStudio = function (chId) {
    var sel = document.getElementById('videoChannelSelect');
    if (sel) sel.value = chId;
    window.switchStudioView('video');
  };

  window.editChannel = function (chId) {
    if (!_studioCatalogCache) return;
    var ch = (_studioCatalogCache.channels || []).find(function (c) { return c.id === chId; });
    if (!ch) return;
    document.getElementById('chEditIdInput').value = ch.id || '';
    document.getElementById('chNameInput').value = ch.name || '';
    document.getElementById('chHandleInput').value = ch.handle || '';
    document.getElementById('chStyleSelect').value = ch.style_preset || 'cinematic_realism';
    document.getElementById('chWorkflowSelect').value = ch.workflow || 'image_first_preview';
    document.getElementById('chImageModelSelect').value = ch.image_model || 'flux2-klein';
    document.getElementById('chI2vModelSelect').value = ch.i2v_model || 'wan2.1-i2v-14b';
    document.getElementById('chAspectSelect').value = ch.aspect_ratio || '16:9';
    document.getElementById('chVoiceSelect').value = ch.voice || 'Aoede';
    document.getElementById('chPrivacySelect').value = ch.privacy || 'private';
    document.getElementById('chYoutubeIdInput').value = ch.youtube_channel_id || '';
    document.getElementById('chTagsInput').value = Array.isArray(ch.tags) ? ch.tags.join(', ') : '';
    document.getElementById('chDefaultPromptInput').value = ch.default_prompt || '';
  };

  window.resetChannelForm = function () {
    var f = document.getElementById('channelManagerForm');
    if (f) f.reset();
    document.getElementById('chEditIdInput').value = '';
  };

  window.handleSaveChannel = function (ev) {
    ev.preventDefault();
    var msgEl = document.getElementById('channelFormMsg');
    var payload = {
      id: (document.getElementById('chEditIdInput') || {}).value || undefined,
      name: (document.getElementById('chNameInput') || {}).value,
      handle: (document.getElementById('chHandleInput') || {}).value,
      style_preset: (document.getElementById('chStyleSelect') || {}).value,
      workflow: (document.getElementById('chWorkflowSelect') || {}).value,
      image_model: (document.getElementById('chImageModelSelect') || {}).value,
      i2v_model: (document.getElementById('chI2vModelSelect') || {}).value,
      aspect_ratio: (document.getElementById('chAspectSelect') || {}).value,
      voice: (document.getElementById('chVoiceSelect') || {}).value,
      privacy: (document.getElementById('chPrivacySelect') || {}).value,
      youtube_channel_id: (document.getElementById('chYoutubeIdInput') || {}).value,
      tags: (document.getElementById('chTagsInput') || {}).value,
      default_prompt: (document.getElementById('chDefaultPromptInput') || {}).value
    };
    window.authFetch('/api/channels', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d && d.success) {
        if (msgEl) msgEl.textContent = '✅ Kaydedildi: ' + (d.channel && d.channel.name);
        window.resetChannelForm();
        window.loadChannelsCatalog(true);
      } else {
        if (msgEl) msgEl.textContent = '❌ ' + ((d && d.detail) || 'Kaydedilemedi');
      }
    });
  };

  window.deleteChannel = function (chId) {
    if (!confirm(chId + ' kanalını silmek istiyor musunuz?')) return;
    window.authFetch('/api/channels/' + encodeURIComponent(chId), { method: 'DELETE' })
      .then(function () { window.loadChannelsCatalog(true); });
  };

  window.handleSaveYtSecret = function () {
    var raw = ((document.getElementById('ytSecretJsonInput') || {}).value || '').trim();
    if (!raw) { alert('client_secret.json içeriğini yapıştırın.'); return; }
    window.authFetch('/api/youtube/oauth-secret', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_secret_json: raw })
    }).then(function (r) { return r.json(); }).then(function (d) {
      alert(d.success ? ('✅ ' + d.message) : ('❌ ' + (d.detail || d.message)));
      window.loadChannelsCatalog(true);
    });
  };

  window.handleStartYoutubeOAuth = function () {
    var cid = (document.getElementById('chEditIdInput') || {}).value || '';
    window.authFetch('/api/youtube/oauth/start?channel_id=' + encodeURIComponent(cid))
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (res.ok && res.d && res.d.auth_url) window.open(res.d.auth_url, '_blank', 'noopener');
        else alert((res.d && res.d.detail) || 'Önce client_secret.json kaydedin.');
      });
  };

  window.publishJobToYoutube = function (jobId) {
    var hud = document.getElementById('studioHudLog');
    window.authFetch('/api/youtube/publish/' + encodeURIComponent(jobId), { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var msg = (d.youtube_url ? ('✅ YouTube: ' + d.youtube_url) : (d.message || d.status || 'İşlem tamamlandı'));
        if (hud) hud.innerHTML += '<br>• 📺 ' + esc(msg);
        alert(msg);
      });
  };

  /* ── GPU İŞÇİSİ & DEPOLAMA DURUMU ───────────────────────────────────── */
  window.refreshGpuStatus = function () {
    window.authFetch('/api/gpu/cluster/status')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (resp) {
        if (!resp || !resp.status) return;
        var s = resp.status;
        _liveGpuWorkersCount = Number(s.active_workers_count || 0);
        var topBadge = document.getElementById('topGpuBadge');
        var warn = document.getElementById('studioGpuWorkerWarn');
        var hud = document.getElementById('gpuOutputHud');
        if (topBadge) {
          topBadge.textContent = _liveGpuWorkersCount > 0 ? ('🟢 GPU: ' + _liveGpuWorkersCount) : '⚡ GPU: 0 (Standby)';
          topBadge.className = _liveGpuWorkersCount > 0 ? 'site-badge site-badge-free' : 'site-badge';
        }
        if (warn) {
          warn.textContent = _liveGpuWorkersCount > 0 ? ('🟢 Canlı GPU: ' + _liveGpuWorkersCount) : '⚡ GPU: 0 (Bulut + Kuyruk)';
          warn.className = _liveGpuWorkersCount > 0 ? 'site-badge site-badge-free' : 'site-badge site-badge-auto';
        }
        if (hud) {
          hud.innerHTML =
            '• Durum: <strong>' + esc(s.cluster_status) + '</strong><br>' +
            '• Bağlı vRAM: <strong>' + esc(s.allocated_vram_gb) + ' GB</strong> · İşçi: <strong>' + esc(_liveGpuWorkersCount) + '</strong><br>' +
            '• ' + esc(s.message || '');
        }
      });

    window.authFetch('/api/system/stats')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (st) {
        var sh = document.getElementById('storageStatusHud');
        if (sh && st && st.storage) {
          sh.innerHTML = '💾 Depolama: <strong>' + esc(st.storage.backend) + '</strong> (' + (st.storage.persistent ? 'Kalıcı' : 'Geçici Disk') + ')<br>' + esc(st.storage.message || '');
        }
      });
  };

  window.loadGpuWorkerSetup = function () {
    window.authFetch('/api/gpu/worker-setup')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.success) return;
        var cmd = 'curl -sS ' + d.worker_script_url + ' -o gpu_worker.py && FABRIKA_WORKER_KEY=' +
          d.worker_key + ' python3 gpu_worker.py --server ' + d.server + ' --token ' + d.worker_key;
        var codeEl = document.getElementById('gpuWorkerCmdCode');
        if (codeEl) codeEl.textContent = cmd;
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(cmd).catch(function () { });
      });
  };

  window.handleGpuModeChange = function (newMode) {
    window.authFetch('/api/gpu/cluster/mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: newMode })
    }).then(function () { window.refreshGpuStatus(); });
  };

  /* ── CANLI MAC FABRİKA KÖPRÜSÜ (PORT-443) + AST REA ─────────────────── */
  function _appendMacMsg(role, sender, text) {
    var box = document.getElementById('macChatLog');
    if (!box) return;
    var div = document.createElement('div');
    div.className = 'site-mac-msg ' + role;
    div.innerHTML = '<span class="site-mac-msg-sender">' + esc(sender) + '</span>' + esc(text);
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  window.refreshMacBridgeStatus = function () {
    window.authFetch('/api/bridge/status')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) return;
        var on = Boolean(d.online);
        var topBadge = document.getElementById('topMacBadge');
        var panelBadge = document.getElementById('macPanelBadge');
        if (topBadge) {
          topBadge.textContent = on ? '🟢 Mac Fabrika Bağlı' : '⚪ Mac Çevrimdışı';
          topBadge.className = on ? 'site-badge site-badge-free' : 'site-badge';
        }
        if (panelBadge) {
          panelBadge.textContent = on ? '🟢 Çevrimiçi (Port 443)' : '⚪ Çevrimdışı';
          panelBadge.className = on ? 'site-badge site-badge-free' : 'site-badge';
        }
        var cpuEl = document.getElementById('macCpuVal');
        var ramEl = document.getElementById('macRamVal');
        var seenEl = document.getElementById('macSeenVal');
        if (cpuEl) cpuEl.textContent = (on && d.cpu !== null && d.cpu !== undefined) ? ('%' + d.cpu) : '—';
        if (ramEl) ramEl.textContent = (on && d.ram !== null && d.ram !== undefined) ? ('%' + d.ram) : '—';
        if (seenEl) seenEl.textContent = (d.last_seen_sec_ago !== null && d.last_seen_sec_ago !== undefined) ? (d.last_seen_sec_ago + ' sn önce') : 'Bağlanmadı';
      });
  };

  window.sendQuickMacCmd = function (cmd) {
    var inp = document.getElementById('macCmdInput');
    if (inp) inp.value = cmd;
    window.handleMacCommandSubmit(null);
  };

  window.handleMacCommandSubmit = function (ev) {
    if (ev && ev.preventDefault) ev.preventDefault();
    var inp = document.getElementById('macCmdInput');
    var btn = document.getElementById('macCmdSendBtn');
    var text = inp ? inp.value.trim() : '';
    if (!text) return;
    inp.value = '';
    _appendMacMsg('user', 'Siz', text);
    if (btn) { btn.disabled = true; btn.textContent = '…'; }

    window.authFetch('/api/bridge/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        _appendMacMsg('agent', (d && d.sender) || 'Mac Köprüsü', (d && d.text) || 'Yanıt alınamadı.');
        window.refreshMacBridgeStatus();
      })
      .catch(function (err) { _appendMacMsg('agent', 'Hata', err.message); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = 'Gönder'; } });
  };

  window.refreshLabReaHistory = function () {
    window.authFetch('/api/rea/history')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        var b = document.getElementById('reaHistBadge');
        if (b && d) b.textContent = 'Tarama: ' + (d.toplam_tarama || 0) + (d.ort_skor !== null && d.ort_skor !== undefined ? (' · Ort: ' + d.ort_skor) : '');
      });
  };

  window.handleLabReaScan = function () {
    var code = ((document.getElementById('labReaCodeInput') || {}).value || '').trim();
    var hud = document.getElementById('labReaResultHud');
    if (!code) { alert('Taranacak kodu yapıştırın.'); return; }
    if (hud) hud.textContent = 'AST analizi çalışıyor…';
    window.authFetch('/api/rea/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hedef: code, persona: 'kys' })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (hud) hud.textContent = (d && d.rapor) ? d.rapor : JSON.stringify(d, null, 2);
        window.refreshLabReaHistory();
      })
      .catch(function (err) { if (hud) hud.textContent = 'Hata: ' + err.message; });
  };

  /* ── BAŞLATMA (ÖNCE AUTH KONTROLÜ) ──────────────────────────────────── */
  function bootstrapStudio() {
    showAppShell();
    _bindUploadAndExtras();
    loadBurcCatalog();
    window.refreshGpuStatus();
    window.refreshMacBridgeStatus();

    var h = (window.location.hash || '').toLowerCase();
    if (h.indexOf('channel') >= 0 || h.indexOf('kanal') >= 0) window.switchStudioView('channels');
    else if (h.indexOf('audio') >= 0 || h.indexOf('ses') >= 0) window.switchStudioView('audio');
    else if (h.indexOf('gpu') >= 0) window.switchStudioView('gpu');
    else if (h.indexOf('mac') >= 0 || h.indexOf('fabrika') >= 0) window.switchStudioView('mac');
    else window.switchStudioView('video');
  }

  function init() {
    var tk = token();
    if (!tk) { showAuthGate(''); return; }
    fetch('/api/auth/check', { headers: { Authorization: 'Bearer ' + tk } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (d && d.authenticated) bootstrapStudio();
        else showAuthGate('');
      })
      .catch(function () { showAuthGate(''); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
