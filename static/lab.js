/* lab.js — Kova Lab Doğrudan Video Üretim Stüdyosu (Gerçek Bulut Sürücülü)
 *
 * Uç noktalar:
 *   GET  /api/lab/models    → Kova Lab + Link Havuzu modelleri ve gerçek sürücü durumu
 *   POST /api/lab/generate  → KovaLab Camoufox bulut sürücüleriyle GERÇEK AI video üretimi
 *   GET  /api/lab/history   → Gerçek bulut modelleriyle üretilen videolar galerisi
 */
(function () {
  'use strict';

  var TOKEN_KEY = 'fabrika_token';
  var tabsEl = document.getElementById('labTabs');
  var panelsEl = document.getElementById('labPanels');
  var ozetEl = document.getElementById('labOzet');
  var historyGridEl = document.getElementById('labHistoryGrid');

  var formEl = document.getElementById('labGenerateForm');
  var modelSelectEl = document.getElementById('studioModelSelect');
  var modeSelectEl = document.getElementById('studioModeSelect');
  var promptInputEl = document.getElementById('studioPromptInput');
  var negPromptInputEl = document.getElementById('studioNegPromptInput');
  var aspectSelectEl = document.getElementById('studioAspectSelect');
  var durationSelectEl = document.getElementById('studioDurationSelect');
  var fpsSelectEl = document.getElementById('studioFpsSelect');
  var cameraSelectEl = document.getElementById('studioCameraSelect');
  var styleSelectEl = document.getElementById('studioStyleSelect');
  var voiceSelectEl = document.getElementById('studioVoiceSelect');
  var subtitlesCheckEl = document.getElementById('studioSubtitlesCheck');
  var generateBtnEl = document.getElementById('studioGenerateBtn');
  var statusMsgEl = document.getElementById('studioStatusMsg');

  var activeBadgeEl = document.getElementById('studioActiveBadge');
  var activeTitleEl = document.getElementById('studioActiveModelTitle');
  var activeDescEl = document.getElementById('studioActiveModelDesc');

  var dropzoneEl = document.getElementById('studioDropzone');
  var imageInputEl = document.getElementById('studioImageInput');
  var uploadPromptEl = document.getElementById('studioUploadPrompt');
  var uploadPreviewWrapEl = document.getElementById('studioUploadPreviewWrap');
  var uploadPreviewImgEl = document.getElementById('studioUploadPreviewImg');
  var uploadFileNameEl = document.getElementById('studioUploadFileName');
  var uploadFileSizeEl = document.getElementById('studioUploadFileSize');
  var clearImageBtnEl = document.getElementById('studioClearImageBtn');

  var videoPlayerEl = document.getElementById('studioVideoPlayer');
  var videoPlaceholderEl = document.getElementById('studioVideoPlaceholder');
  var outputBadgeEl = document.getElementById('studioOutputBadge');
  var outputMetaEl = document.getElementById('studioOutputMeta');
  var outputActionsEl = document.getElementById('studioOutputActions');
  var downloadLinkEl = document.getElementById('studioDownloadLink');
  var reuseBtnEl = document.getElementById('studioReuseBtn');
  var metaModelNameEl = document.getElementById('metaModelName');
  var metaResFpsEl = document.getElementById('metaResFps');
  var metaDurScenesEl = document.getElementById('metaDurScenes');
  var metaFileSizeEl = document.getElementById('metaFileSize');

  var tumModeller = {};
  var seciliModelId = null;
  var yuklenenGorselBase64 = null;
  var sonIsKaydi = null;

  function token() {
    try { return localStorage.getItem(TOKEN_KEY); } catch (e) { return null; }
  }

  function esc(metin) {
    return String(metin === null || metin === undefined ? '' : metin)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
  window.esc = esc;

  function bosDurum(mesaj) {
    if (!panelsEl) return;
    panelsEl.innerHTML = '<div class="site-empty">' + esc(mesaj) + '</div>';
  }

  function durumYaz(mesaj, hataMi) {
    if (!statusMsgEl) return;
    statusMsgEl.textContent = mesaj || '';
    statusMsgEl.style.color = hataMi ? 'var(--site-danger)' : 'var(--site-accent)';
  }

  function rozetler(model) {
    var parcalar = [];
    if (model.gercek_uretim) {
      parcalar.push('<span class="site-badge site-badge-free">🟢 Otomatik Sürücü</span>');
    } else if (model.ucretsiz) {
      parcalar.push('<span class="site-badge">Ücretsiz Kota</span>');
    }
    if (!model.gercek_uretim) {
      parcalar.push('<span class="site-badge">Manuel / Harici</span>');
    }
    if (model.havuz_id) parcalar.push('<span class="site-badge site-badge-pool">Havuz #' + esc(model.havuz_id) + '</span>');
    if (model.puan) parcalar.push('<span class="site-badge">★ ' + esc(model.puan) + '</span>');
    if (model.lisans) parcalar.push('<span class="site-badge">' + esc(model.lisans) + '</span>');
    return parcalar.join(' ');
  }

  function modeliStudyoyaSec(modelId, yukariKaydir) {
    var model = tumModeller[modelId];
    if (!model) return;
    seciliModelId = modelId;

    if (modelSelectEl && modelSelectEl.value !== modelId) {
      modelSelectEl.value = modelId;
    }
    if (activeTitleEl) activeTitleEl.textContent = model.ad || model.id;
    if (activeDescEl) activeDescEl.textContent = model.guclu || model.not_ || '';

    var gercekMi = Boolean(model.gercek_uretim);
    if (activeBadgeEl) {
      activeBadgeEl.textContent = gercekMi
        ? ('🟢 Gerçek Bulut Sürücüsü Hazır (' + (model.surucu_dosya || model.id) + ')')
        : ('⚠️ Manuel Model — Otomatik Sürücüsü Yok');
      activeBadgeEl.className = gercekMi ? 'site-badge site-badge-free' : 'site-badge';
    }

    var oz = model.ozellikler || {};
    var sureler = oz.sure_secenekleri || [5, 10];
    var varsayilanSure = oz.varsayilan_sure || model.sure_sn || 5;

    if (durationSelectEl) {
      durationSelectEl.innerHTML = sureler.map(function (sn) {
        var secili = (Number(sn) === Number(varsayilanSure)) ? ' selected' : '';
        return '<option value="' + esc(sn) + '"' + secili + '>' + esc(sn) + ' saniye</option>';
      }).join('');
    }

    var kartlar = document.querySelectorAll('.site-model-card[data-model-id]');
    for (var i = 0; i < kartlar.length; i++) {
      var k = kartlar[i];
      if (k.getAttribute('data-model-id') === modelId) {
        k.classList.add('site-model-card-active');
      } else {
        k.classList.remove('site-model-card-active');
      }
    }

    if (gercekMi) {
      if (generateBtnEl) {
        generateBtnEl.disabled = false;
        generateBtnEl.textContent = '🎬 ' + (model.ad || model.id) + ' İle Gerçek Video Üret';
      }
      durumYaz('“' + (model.ad || model.id) + '” bulut sürücüsü seçildi. Prompt girip gerçek AI videosu üretebilirsiniz (ortalama 45-90 sn).', false);
    } else {
      if (generateBtnEl) {
        generateBtnEl.disabled = false;
        generateBtnEl.textContent = '⚠️ Otomatik Sürücü Yok (Dürüst Kontrol)';
      }
      durumYaz('“' + (model.ad || model.id) + '” için henüz otomatik tarayıcı sürücüsü yok. Sahte video üretilmez; doğrudan üretim için Luma, Leonardo, Kling veya Hailuo seçin.', true);
    }

    if (yukariKaydir) {
      var st = document.getElementById('labStudioSection');
      if (st && st.scrollIntoView) {
        st.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  }

  function gorselDosyasiOku(file) {
    if (!file) return;
    if (!file.type || !file.type.startsWith('image/')) {
      durumYaz('Lütfen geçerli bir görsel dosyası (PNG, JPG, WEBP) seçin.', true);
      return;
    }
    var reader = new FileReader();
    reader.onload = function (ev) {
      yuklenenGorselBase64 = ev.target.result;
      if (uploadPreviewImgEl) uploadPreviewImgEl.src = yuklenenGorselBase64;
      if (uploadFileNameEl) uploadFileNameEl.textContent = file.name || 'yuklenen_gorsel.jpg';
      if (uploadFileSizeEl) uploadFileSizeEl.textContent = Math.round(file.size / 1024) + ' KB';
      if (uploadPromptEl) uploadPromptEl.hidden = true;
      if (uploadPreviewWrapEl) uploadPreviewWrapEl.hidden = false;
      if (modeSelectEl) modeSelectEl.value = 'i2v';
      durumYaz('Görsel yüklendi: Görselden Videoya (I2V) modu etkinleştirildi.', false);
    };
    reader.readAsDataURL(file);
  }

  function gorseliTemizle() {
    yuklenenGorselBase64 = null;
    if (imageInputEl) imageInputEl.value = '';
    if (uploadPreviewImgEl) uploadPreviewImgEl.src = '';
    if (uploadPromptEl) uploadPromptEl.hidden = false;
    if (uploadPreviewWrapEl) uploadPreviewWrapEl.hidden = true;
    if (modeSelectEl && modeSelectEl.value === 'i2v') modeSelectEl.value = 't2v';
  }

  if (dropzoneEl && imageInputEl) {
    dropzoneEl.addEventListener('click', function (ev) {
      if (ev.target && ev.target.id === 'studioClearImageBtn') return;
      imageInputEl.click();
    });
    imageInputEl.addEventListener('change', function () {
      if (imageInputEl.files && imageInputEl.files[0]) {
        gorselDosyasiOku(imageInputEl.files[0]);
      }
    });
    dropzoneEl.addEventListener('dragover', function (ev) {
      ev.preventDefault();
      dropzoneEl.classList.add('site-dropzone-active');
    });
    dropzoneEl.addEventListener('dragleave', function () {
      dropzoneEl.classList.remove('site-dropzone-active');
    });
    dropzoneEl.addEventListener('drop', function (ev) {
      ev.preventDefault();
      dropzoneEl.classList.remove('site-dropzone-active');
      if (ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0]) {
        gorselDosyasiOku(ev.dataTransfer.files[0]);
      }
    });
  }

  if (clearImageBtnEl) {
    clearImageBtnEl.addEventListener('click', function (ev) {
      ev.stopPropagation();
      gorseliTemizle();
    });
  }

  var presetContainer = document.getElementById('studioPromptPresets');
  if (presetContainer) {
    presetContainer.addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-prompt]');
      if (!btn || !promptInputEl) return;
      promptInputEl.value = btn.getAttribute('data-prompt') || '';
      promptInputEl.focus();
    });
  }

  if (modelSelectEl) {
    modelSelectEl.addEventListener('change', function () {
      modeliStudyoyaSec(modelSelectEl.value, false);
    });
  }

  function videoyuOynaticiyaBagla(job) {
    if (!job) return;
    sonIsKaydi = job;
    var t = token();
    var tamUrl = job.video_url + (job.video_url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(t || '');

    if (videoPlaceholderEl) videoPlaceholderEl.style.display = 'none';
    if (videoPlayerEl) {
      videoPlayerEl.style.display = 'block';
      videoPlayerEl.src = tamUrl;
      videoPlayerEl.load();
      var playPromise = videoPlayerEl.play();
      if (playPromise && playPromise.catch) {
        playPromise.catch(function () { /* Tarayıcı kısıtı */ });
      }
    }

    if (outputBadgeEl) {
      outputBadgeEl.textContent = '✅ Gerçek Üretim (' + (job.elapsed_sec || 1) + ' sn)';
      outputBadgeEl.className = 'site-badge site-badge-free';
    }
    if (outputMetaEl) outputMetaEl.hidden = false;
    if (outputActionsEl) outputActionsEl.hidden = false;
    if (metaModelNameEl) metaModelNameEl.textContent = (job.model_ad || job.model_id) + (job.kaynak ? ' [' + job.kaynak + ']' : '');
    if (metaResFpsEl) metaResFpsEl.textContent = (job.resolution || 'HD') + ' @ ' + (job.fps || 24) + ' FPS';
    if (metaDurScenesEl) metaDurScenesEl.textContent = (job.duration || 5) + ' sn';
    if (metaFileSizeEl) metaFileSizeEl.textContent = (job.size_kb || 0) + ' KB';

    if (downloadLinkEl) {
      downloadLinkEl.href = tamUrl;
      downloadLinkEl.setAttribute('download', (job.id || 'kovalab_video') + '.mp4');
    }
  }

  if (reuseBtnEl) {
    reuseBtnEl.addEventListener('click', function () {
      if (!sonIsKaydi) return;
      if (sonIsKaydi.model_id) modeliStudyoyaSec(sonIsKaydi.model_id, false);
      if (promptInputEl) promptInputEl.value = sonIsKaydi.prompt || '';
      if (aspectSelectEl && sonIsKaydi.aspect_ratio) aspectSelectEl.value = sonIsKaydi.aspect_ratio;
      durumYaz('Son üretilen videonun ayarları stüdyoya geri yüklendi.', false);
    });
  }

  if (formEl) {
    formEl.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var t = token();
      if (!t) {
        durumYaz('Oturum bulunamadı. Lütfen ana sayfadan giriş yapın.', true);
        return;
      }

      var promptVal = promptInputEl ? promptInputEl.value.trim() : '';
      if (!promptVal && !yuklenenGorselBase64) {
        durumYaz('Lütfen bir video açıklaması (prompt) yazın veya bir görsel yükleyin.', true);
        if (promptInputEl) promptInputEl.focus();
        return;
      }

      var seciliModel = tumModeller[seciliModelId] || {};
      var sesSecimi = voiceSelectEl ? voiceSelectEl.value : 'none';

      var payload = {
        model_id: seciliModelId || (modelSelectEl ? modelSelectEl.value : 'luma'),
        model_ad: seciliModel.ad || seciliModelId || 'Luma Dream Machine',
        mode: modeSelectEl ? modeSelectEl.value : 't2v',
        prompt: promptVal,
        negative_prompt: negPromptInputEl ? negPromptInputEl.value.trim() : '',
        image_base64: yuklenenGorselBase64,
        aspect_ratio: aspectSelectEl ? aspectSelectEl.value : '16:9',
        duration: durationSelectEl ? Number(durationSelectEl.value) : 5,
        fps: fpsSelectEl ? Number(fpsSelectEl.value) : 24,
        camera_motion: cameraSelectEl ? cameraSelectEl.value : 'otomatik',
        style: styleSelectEl ? styleSelectEl.value : 'sinematik',
        tts_enabled: sesSecimi !== 'none',
        tts_voice: sesSecimi !== 'none' ? sesSecimi : 'tr-TR-AhmetNeural',
        subtitles_enabled: subtitlesCheckEl ? Boolean(subtitlesCheckEl.checked) : true
      };

      if (generateBtnEl) {
        generateBtnEl.disabled = true;
        generateBtnEl.textContent = '⏳ Bulutta Gerçek Video Üretiliyor (45–90 sn)…';
      }
      if (outputBadgeEl) {
        outputBadgeEl.textContent = 'Bulutta Render Ediliyor…';
        outputBadgeEl.className = 'site-badge site-badge-auto';
      }
      durumYaz('Seçilen model (' + payload.model_ad + ') için Camoufox bulut sürücüsü başlatıldı; gerçek AI videosu render ediliyor, lütfen bekleyin…', false);

      fetch('/api/lab/generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + t
        },
        body: JSON.stringify(payload)
      })
        .then(function (r) {
          return r.json().then(function (body) { return { ok: r.ok, body: body }; });
        })
        .then(function (res) {
          if (!res.ok || !res.body || !res.body.success) {
            var hata = (res.body && (res.body.detail || res.body.message)) || 'Video üretimi başarısız oldu.';
            throw new Error(hata);
          }
          durumYaz(res.body.message || 'Gerçek bulut AI videosu başarıyla üretildi!', false);
          videoyuOynaticiyaBagla(res.body.job);
          gecmisiYukle();
        })
        .catch(function (err) {
          durumYaz('Üretim hatası: ' + err.message, true);
          if (outputBadgeEl) {
            outputBadgeEl.textContent = 'Üretilemedi';
            outputBadgeEl.className = 'site-badge';
          }
        })
        .finally(function () {
          if (generateBtnEl) {
            generateBtnEl.disabled = false;
            generateBtnEl.textContent = '🎬 Web Sitemde Video Üret';
          }
        });
    });
  }

  function modelKarti(model) {
    var meta = [];
    if (model.girdi) meta.push('<div>Girdi<strong>' + esc(model.girdi) + '</strong></div>');
    if (model.sure_sn) meta.push('<div>Varsayılan Süre<strong>' + esc(model.sure_sn) + ' sn</strong></div>');
    if (model.gunluk_kota) meta.push('<div>Günlük Kota<strong>' + esc(model.gunluk_kota) + '</strong></div>');
    if (model.kota_notu) meta.push('<div>Kota Notu<strong>' + esc(model.kota_notu) + '</strong></div>');

    var secBtn = '';
    if (model.gercek_uretim) {
      secBtn = '<button type="button" class="site-btn site-btn-primary site-select-model-btn" ' +
        'data-select-model="' + esc(model.id) + '" style="padding:8px 16px;font-size:0.8rem;">' +
        '🎬 Stüdyoda Seç &amp; Üret</button>';
    } else {
      secBtn = '<button type="button" class="site-btn site-btn-ghost site-select-model-btn" ' +
        'data-select-model="' + esc(model.id) + '" style="padding:8px 14px;font-size:0.78rem;">' +
        '🔍 Stüdyoda İncele (Manuel)</button>';
    }

    var disBaglanti = '';
    if (model.site) {
      disBaglanti = '<a class="site-btn site-btn-ghost" style="padding:8px 14px;font-size:0.76rem;" ' +
        'href="' + esc(model.site) + '" target="_blank" rel="noopener noreferrer" title="Modelin Kendi Sitesi / Repo">Siteyi aç ↗</a>';
    }

    return '' +
      '<article class="site-card site-model-card" data-model-id="' + esc(model.id) + '">' +
        '<h3>' + esc(model.ad || model.id) + ' ' + rozetler(model) + '</h3>' +
        (model.guclu ? '<p>' + esc(model.guclu) + '</p>' : '') +
        (meta.length ? '<div class="site-model-meta">' + meta.join('') + '</div>' : '') +
        (model.not_ ? '<p style="font-size:0.78rem;color:var(--site-text-faint);">' + esc(model.not_) + '</p>' : '') +
        '<div style="margin-top:10px; display:flex; gap:8px; flex-wrap:wrap;">' + secBtn + disBaglanti + '</div>' +
      '</article>';
  }

  function panelOlustur(grup, ilkMi) {
    var kartlar = grup.modeller.map(modelKarti).join('');
    return '' +
      '<section class="site-lab-panel" role="tabpanel" id="panel-' + esc(grup.tur) + '"' +
        (ilkMi ? '' : ' hidden') + '>' +
        '<div class="site-model-grid">' + kartlar + '</div>' +
      '</section>';
  }

  function ciz(veri) {
    var gruplar = veri.gruplar || [];
    if (!gruplar.length) {
      if (tabsEl) tabsEl.innerHTML = '';
      bosDurum(veri.mesaj || 'Model kaydı bulunamadı.');
      return;
    }

    tumModeller = {};
    var gercekOps = [];
    var digerGruplarHtml = [];

    gruplar.forEach(function (g) {
      var digerOpts = [];
      (g.modeller || []).forEach(function (m) {
        tumModeller[m.id] = m;
        if (m.gercek_uretim) {
          gercekOps.push('<option value="' + esc(m.id) + '">🟢 ' + esc(m.ad || m.id) + ' (Gerçek Otomatik Bulut Sürücüsü)</option>');
        } else {
          digerOpts.push('<option value="' + esc(m.id) + '">⚪ ' + esc(m.ad || m.id) + ' (Manuel / Harici)</option>');
        }
      });
      if (digerOpts.length) {
        digerGruplarHtml.push('<optgroup label="' + esc(g.etiket) + ' (Manuel / Harici)">' + digerOpts.join('') + '</optgroup>');
      }
    });

    var tumSelectHtml = '';
    if (gercekOps.length) {
      tumSelectHtml += '<optgroup label="🟢 Otomatik Bulut Üretimi (Gerçek AI Sürücülü)">' + gercekOps.join('') + '</optgroup>';
    }
    tumSelectHtml += digerGruplarHtml.join('');

    if (modelSelectEl) {
      modelSelectEl.innerHTML = tumSelectHtml;
    }

    if (ozetEl) {
      ozetEl.innerHTML =
        '<span class="site-badge site-badge-free">' + esc(gercekOps.length) + ' gerçek otomatik bulut sürücüsü</span>' +
        '<span class="site-badge">' + esc(veri.toplam) + ' toplam model</span>' +
        '<span class="site-badge">' + esc(veri.ucretsiz) + ' ücretsiz kota</span>' +
        (veri.havuz_eklenen ? '<span class="site-badge site-badge-pool">' + esc(veri.havuz_eklenen) + ' Link Havuzu projesi</span>' : '') +
        '<span class="site-badge">' + esc(gruplar.length) + ' kategori</span>';
    }

    if (tabsEl) {
      tabsEl.innerHTML = gruplar.map(function (g, i) {
        return '<button class="site-lab-tab" role="tab" type="button" ' +
          'data-tur="' + esc(g.tur) + '" aria-selected="' + (i === 0 ? 'true' : 'false') + '">' +
          esc(g.etiket) + ' <span style="opacity:.6;">' + esc(g.adet) + '</span></button>';
      }).join('');
    }

    if (panelsEl) {
      panelsEl.innerHTML = gruplar.map(function (g, i) { return panelOlustur(g, i === 0); }).join('');
    }

    // Varsayılan olarak Luma veya ilk gerçek sürücülü modeli seç
    var varsayilanId = tumModeller['luma'] ? 'luma' : (tumModeller['leonardo'] ? 'leonardo' : Object.keys(tumModeller)[0]);
    if (varsayilanId) {
      modeliStudyoyaSec(varsayilanId, false);
    }
  }

  if (tabsEl) {
    tabsEl.addEventListener('click', function (ev) {
      var btn = ev.target.closest('.site-lab-tab');
      if (!btn) return;
      var tur = btn.getAttribute('data-tur');
      var tumu = tabsEl.querySelectorAll('.site-lab-tab');
      for (var i = 0; i < tumu.length; i++) {
        tumu[i].setAttribute('aria-selected', tumu[i] === btn ? 'true' : 'false');
      }
      var paneller = document.querySelectorAll('.site-lab-panel');
      for (var p = 0; p < paneller.length; p++) {
        paneller[p].hidden = paneller[p].id !== 'panel-' + tur;
      }
    });
  }

  if (panelsEl) {
    panelsEl.addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-select-model]');
      if (!btn) return;
      var mid = btn.getAttribute('data-select-model');
      modeliStudyoyaSec(mid, true);
    });
  }

  function gecmisiCiz(items) {
    if (!historyGridEl) return;
    if (!items || !items.length) {
      historyGridEl.innerHTML = '<div class="site-empty">Henüz gerçek bulut sürücüsüyle üretilmiş bir video yok. Yukarıdan Luma veya Leonardo seçerek ilk gerçek videonuzu üretin!</div>';
      return;
    }
    var t = token();
    historyGridEl.innerHTML = items.map(function (item) {
      var vUrl = item.video_url + (item.video_url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(t || '');
      return '' +
        '<article class="site-card site-model-card">' +
          '<video controls playsinline preload="metadata" style="width:100%; border-radius:10px; margin-bottom:10px; background:#000; max-height:220px;" src="' + esc(vUrl) + '"></video>' +
          '<h3 style="font-size:0.96rem;">' + esc(item.model_ad || item.model_id) + ' <span class="site-badge site-badge-free">' + esc(item.kaynak || 'bulut') + '</span></h3>' +
          '<p style="font-size:0.82rem; margin-bottom:8px;">' + esc(item.prompt || 'Gerçek Bulut Üretimi') + '</p>' +
          '<div class="site-model-meta">' +
            '<div>Render Süresi<strong>' + esc(item.elapsed_sec || item.duration || 5) + ' sn</strong></div>' +
            '<div>Boyut<strong>' + esc(item.size_kb || 0) + ' KB</strong></div>' +
          '</div>' +
          '<div style="margin-top:8px; display:flex; gap:8px;">' +
            '<a class="site-btn site-btn-ghost" href="' + esc(vUrl) + '" download="' + esc((item.id || 'video') + '.mp4') + '" style="padding:6px 14px; font-size:0.78rem;">⬇️ MP4 İndir</a>' +
          '</div>' +
        '</article>';
    }).join('');
  }

  function gecmisiYukle() {
    var t = token();
    if (!t || !historyGridEl) return;
    fetch('/api/lab/history', { headers: { Authorization: 'Bearer ' + t } })
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .then(function (veri) {
        var items = veri.items || [];
        gecmisiCiz(items);
        if (items.length && !sonIsKaydi) {
          videoyuOynaticiyaBagla(items[0]);
        }
      })
      .catch(function () { /* yoksay */ });
  }

  function yukle() {
    var t = token();
    if (!t) {
      bosDurum('Oturum bulunamadı. Lütfen ana sayfadan giriş yapın.');
      return;
    }
    bosDurum('Model kataloğu ve gerçek bulut sürücüleri yükleniyor…');

    fetch('/api/lab/models', { headers: { Authorization: 'Bearer ' + t } })
      .then(function (r) {
        if (r.status === 401) { throw new Error('Oturum süresi doldu. Yeniden giriş yapın.'); }
        return r.json();
      })
      .then(function (veri) {
        ciz(veri);
        gecmisiYukle();
      })
      .catch(function (hata) { bosDurum('Yüklenemedi: ' + hata.message); });
  }

  yukle();
})();


// ═══════════════════════════════════════════════════════════════════════════
// FABRIKA 2026-11 ÇOK KANALLI STÜDYO, GPU VE OMNIROUTE ETKİLEŞİM MOTORU
// ═══════════════════════════════════════════════════════════════════════════

var currentAudioAction = 'generate_music';

window.switchStudioView = function(viewKey) {
  var viewMap = {
    'video': 'viewVideoStudio',
    'audio': 'viewAudioStudio',
    'omni': 'viewOmniRoute',
    'humanizer': 'viewHumanizer',
    'gpu': 'viewGpuStudio',
    'wan': 'viewWanStudio'
  };

  var tabMap = {
    'video': 'tabNavVideo',
    'audio': 'tabNavAudio',
    'omni': 'tabNavOmni',
    'humanizer': 'tabNavHumanizer',
    'gpu': 'tabNavGpu',
    'wan': 'tabNavWan'
  };

  Object.keys(viewMap).forEach(function(k) {
    var vEl = document.getElementById(viewMap[k]);
    var tEl = document.getElementById(tabMap[k]);
    if (vEl) vEl.hidden = (k !== viewKey);
    if (tEl) {
      if (k === viewKey) tEl.classList.add('active');
      else tEl.classList.remove('active');
    }
  });

  if (viewKey === 'gpu') {
    window.refreshGpuStatus();
  }
};

// URL Hash Kontrolü (#videoStudio, #audioStudio vb.)
(function initHashView() {
  var h = (window.location.hash || '').toLowerCase();
  if (h.includes('audio')) window.switchStudioView('audio');
  else if (h.includes('omni')) window.switchStudioView('omni');
  else if (h.includes('human')) window.switchStudioView('humanizer');
  else if (h.includes('gpu')) window.switchStudioView('gpu');
  else if (h.includes('wan') || h.includes('model')) window.switchStudioView('wan');
  else window.switchStudioView('video');
})();

window.setStudioPrompt = function(promptText) {
  var pInput = document.getElementById('videoPromptInput');
  if (pInput) {
    pInput.value = promptText;
    pInput.focus();
  }
};

window.handleStudioVideoSubmit = function(e) {
  e.preventDefault();
  var channel = document.getElementById('videoChannelSelect').value;
  var method = document.getElementById('videoMethodSelect').value;
  var renderTarget = document.getElementById('videoRenderTarget').value;
  var aspect = document.getElementById('videoAspectSelect').value;
  var promptVal = document.getElementById('videoPromptInput').value.trim();
  var hudLog = document.getElementById('studioHudLog');
  var taskBadge = document.getElementById('studioTaskBadge');
  var stageArea = document.getElementById('studioStageArea');

  if (!promptVal) {
    alert('Lütfen bir video konusu veya prompt girin.');
    return;
  }

  taskBadge.textContent = 'Render Ediliyor';
  taskBadge.className = 'site-badge site-badge-free';

  hudLog.innerHTML = `[PRODÜKSİYON BAŞLATILDI]<br>` +
    `• Hedef Kanal: <strong>${esc(channel)}</strong><br>` +
    `• Metot: <strong>${esc(method)}</strong><br>` +
    `• Donanım: <strong>${esc(renderTarget)}</strong><br>` +
    `• Konu: "${esc(promptVal)}"<br>` +
    `• Durum: Aşama 1/5 Senaryo hazırlanıyor...`;

  // Aşama 1: Done
  var step1 = document.getElementById('step1');
  var step2 = document.getElementById('step2');
  var step3 = document.getElementById('step3');
  var step4 = document.getElementById('step4');
  var step5 = document.getElementById('step5');

  step1.className = 'site-pipeline-step done';
  step2.className = 'site-pipeline-step active';

  fetch('/api/studio/video/generate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + (token() || localStorage.getItem('cockpit_token') || '')
    },
    body: JSON.stringify({
      channel: channel,
      method: method,
      render_target: renderTarget,
      aspect_ratio: aspect,
      prompt: promptVal
    })
  })
  .then(function(res) { return res.json(); })
  .then(function(data) {
    if (data.success && data.task) {
      var task = data.task;
      step1.className = 'site-pipeline-step done';
      step2.className = 'site-pipeline-step done';
      step3.className = 'site-pipeline-step active';
      step4.className = 'site-pipeline-step';
      step5.className = 'site-pipeline-step';

      taskBadge.textContent = 'Kuyrukta (GPU Bekleniyor)';
      taskBadge.className = 'site-badge site-badge-free';

      hudLog.innerHTML += `<br>• ✅ <strong>Senaryo ve Prompt Analizi Hazırlandı.</strong><br>` +
        `• ⏳ <strong>Prodüksiyon Görevi Kuyruğa Alındı:</strong> <code>${esc(task.job_id)}</code><br>` +
        `• Hedef Donanım: <strong>${esc(renderTarget).toUpperCase()}</strong> | Oran: <strong>${esc(aspect)}</strong><br>` +
        `• 📡 <em>GPU İşçisi (Kaggle Dual-T4 / Colab) sıradaki işi aldığında render otomatik başlayacaktır.</em>`;

      stageArea.innerHTML = `
        <div style="text-align:center; padding:16px;">
          <div style="font-size:2.8rem; margin-bottom:8px;">⏳</div>
          <strong style="color:var(--site-accent);">Görev Bulut Kuyruğuna Yazıldı</strong>
          <p style="margin:4px 0 8px; font-size:0.84rem; color:var(--site-text-dim);">
            Bilet ID: <code>${esc(task.job_id)}</code> | Kanal: <strong>${esc(task.channel)}</strong>
          </p>
          <p style="margin:0 0 12px; font-size:0.78rem; color:var(--site-text-muted);">
            Render Motoru: <strong>${esc(task.method)}</strong> &bull; Donanım: <strong>${esc(task.render_target)}</strong>
          </p>
          <span class="site-badge site-badge-free">Sıraya Alındı (Kural 1 Uyumlu Dürüst Kuyruk)</span>
        </div>
      `;
    } else {
      hudLog.innerHTML += `<br><span style="color:var(--site-danger);">Hata: ${esc(data.error || 'Prodüksiyon başlatılamadı.')}</span>`;
      taskBadge.textContent = 'Hata';
    }
  })
  .catch(function(err) {
    hudLog.innerHTML += `<br><span style="color:var(--site-danger);">Ağ Hatası: ${esc(err.message)}</span>`;
    taskBadge.textContent = 'Hata';
  });
};

window.switchAudioAction = function(action) {
  currentAudioAction = action;
  var btnMap = {
    'generate_music': 'audioTabMusic',
    'voice_clone_tts': 'audioTabVoice',
    'generate_podcast': 'audioTabPodcast',
    'identify_music': 'audioTabIdentify'
  };

  Object.keys(btnMap).forEach(function(k) {
    var b = document.getElementById(btnMap[k]);
    if (b) {
      if (k === action) b.classList.add('active');
      else b.classList.remove('active');
    }
  });

  var label = document.getElementById('audioPromptLabel');
  var input = document.getElementById('audioPromptInput');
  var paramRow = document.getElementById('audioParamRow');

  if (action === 'generate_music') {
    label.textContent = 'Müzik İstem Açıklaması';
    input.placeholder = 'Örn: Eğlenceli enerjik Trakya Roman havası ritmi, klarnet ve darbuka solosu...';
    paramRow.style.display = 'grid';
  } else if (action === 'voice_clone_tts') {
    label.textContent = 'Seslendirilecek Metin (VoiceStudio)';
    input.placeholder = 'Örn: Merhaba, Fabrika otonom ses stüdyosuna hoş geldiniz...';
    paramRow.style.display = 'none';
  } else if (action === 'generate_podcast') {
    label.textContent = 'Podcast Konusu veya Doküman Özeti (Podcastfy)';
    input.placeholder = 'Örn: Kaggle ve Colab GPU mimarisi ile sıfır maliyetle yapay zeka işletimi...';
    paramRow.style.display = 'none';
  } else if (action === 'identify_music') {
    label.textContent = 'Şarkı Sözleri veya Sosyal Medya İpucu';
    input.placeholder = 'Örn: Aman aman aman kara gözlüm sana yandı benim gönlüm...';
    paramRow.style.display = 'none';
  }
};

window.handleAudioSubmit = function(e) {
  e.preventDefault();
  var inputVal = document.getElementById('audioPromptInput').value.trim();
  var hud = document.getElementById('audioOutputHud');
  var genre = document.getElementById('audioGenreSelect').value;
  var bpm = Number(document.getElementById('audioBpmInput').value) || 120;

  if (!inputVal) {
    alert('Lütfen bir metin veya arama terimi girin.');
    return;
  }

  hud.innerHTML = `[İŞLENİYOR...] Aksiyon: ${currentAudioAction}`;

  var params = {};
  if (currentAudioAction === 'generate_music') {
    params = { prompt: inputVal, genre: genre, bpm: bpm, duration_sec: 60 };
  } else if (currentAudioAction === 'voice_clone_tts') {
    params = { text: inputVal, voice_profile: 'yusuf_sahin_tr', emotion: 'enerjik' };
  } else if (currentAudioAction === 'generate_podcast') {
    params = { topic: inputVal, length_minutes: 5 };
  } else if (currentAudioAction === 'identify_music') {
    params = { lyrics: inputVal };
  }

  var authHeader = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + (token() || localStorage.getItem('cockpit_token') || '')
  };

  fetch('/api/audio/process', {
    method: 'POST',
    headers: authHeader,
    body: JSON.stringify({ action: currentAudioAction, params: params })
  })
  .then(function(res) { return res.json(); })
  .then(function(resp) {
    if (resp.success && resp.data) {
      var d = resp.data;
      if (currentAudioAction === 'identify_music') {
        if (d.matched) {
          hud.innerHTML = `🎵 <strong>Şarkı Tespiti Sonucu:</strong><br>` +
            `• Başlık: <strong>${esc(d.title || 'Bilinmeyen')}</strong><br>` +
            `• Tür: <strong>${esc(d.genre || '-')}</strong><br>` +
            `• Güven Skoru: <strong>%${Math.round((d.confidence || 0) * 100)}</strong><br>` +
            `• İcracılar: ${d.performers ? esc(d.performers.join(', ')) : 'Belirtilmedi'}`;
        } else {
          hud.innerHTML = `🔍 <strong>Şarkı Tespiti:</strong><br>` +
            `• Durum: ${esc(d.status || 'Tamamlandı')}<br>` +
            `• Sonuç: ${esc(d.message || 'Eşleşen parça bulunamadı.')}`;
        }
      } else if (d.status === 'queued' || (d.message && d.message.includes('kuyruğuna'))) {
        hud.innerHTML = `⏳ <strong>Kuyruğa Alındı (GPU Bekleniyor):</strong><br>` +
          `• Motor: <strong>${esc(d.engine)}</strong><br>` +
          `• Durum: <em>${esc(d.message)}</em><br>` +
          `• Çıktı Formatı: <code>${esc(d.output_format || d.format || 'wav/mp3')}</code><br>` +
          `• Bilgi: Bulut GPU düğümü bağlandığında otomatik işlenecektir.`;
      } else {
        hud.innerHTML = `✅ <strong>Üretim Tamamlandı:</strong><br>` +
          `• Motor: <strong>${esc(d.engine)}</strong><br>` +
          `• Mesaj: ${esc(d.message)}<br>` +
          `• Çıktı Formatı: <code>${esc(d.output_format || d.format || 'wav/mp3')}</code>`;
      }
    } else {
      hud.innerHTML = `<span style="color:var(--site-danger);">Hata: ${esc(resp.detail || resp.error || 'İşlem başarısız veya oturum geçersiz')}</span>`;
    }
  })
  .catch(function(err) {
    hud.innerHTML = `<span style="color:var(--site-danger);">Ağ Hatası: ${esc(err.message)}</span>`;
  });
};

window.handleOmniRouteSubmit = function(e) {
  e.preventDefault();
  var promptVal = document.getElementById('omniPromptInput').value.trim();
  var hud = document.getElementById('omniOutputHud');
  if (!promptVal) return;

  hud.innerHTML = `[OMNIROUTE ŞELALESİ ÇALIŞIYOR...] Model aranıyor ($0.00)...`;

  var authHeader = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + (token() || localStorage.getItem('cockpit_token') || '')
  };

  fetch('/api/omniroute/generate', {
    method: 'POST',
    headers: authHeader,
    body: JSON.stringify({ prompt: promptVal })
  })
  .then(function(res) { return res.json(); })
  .then(function(resp) {
    if (resp.success && resp.result) {
      var r = resp.result;
      var simBadge = r.simulasyon ? '<span class="site-badge" style="background:#f59e0b;color:#000;">Kılavuz Simülasyon</span>' : '<span class="site-badge" style="background:#10b981;color:#fff;">Canlı Çıkarım</span>';
      hud.innerHTML = `⚡ <strong>OmniRoute Yanıtı ($0.00):</strong> ${simBadge}<br>` +
        `• Model: <strong>${esc(r.display_name)}</strong> (Tier ${esc(r.tier)})<br>` +
        `• Sağlayıcı: ${esc(r.provider)}<br>` +
        `• Gecikme: <strong>${esc(r.latency_ms)} ms</strong><br>` +
        `• Maliyet: <strong>$0.00 (Tamamen Ücretsiz)</strong><br><br>` +
        `<div style="color:var(--site-text); white-space:pre-wrap;">${esc(r.content)}</div>`;
    } else {
      hud.innerHTML = `<span style="color:var(--site-danger);">Hata: ${esc(resp.detail || 'Çıkarım başarısız')}</span>`;
    }
  })
  .catch(function(err) {
    hud.innerHTML = `<span style="color:var(--site-danger);">Ağ Hatası: ${esc(err.message)}</span>`;
  });
};

window.handleHumanizerSubmit = function(e) {
  e.preventDefault();
  var textVal = document.getElementById('humanizerInput').value.trim();
  var hud = document.getElementById('humanizerOutputHud');
  if (!textVal) return;

  hud.innerHTML = `[ANTI-SLOP FİLTRESİ ÇALIŞIYOR...]`;

  var authHeader = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + (token() || localStorage.getItem('cockpit_token') || '')
  };

  fetch('/api/humanizer/clean', {
    method: 'POST',
    headers: authHeader,
    body: JSON.stringify({ text: textVal })
  })
  .then(function(res) { return res.json(); })
  .then(function(resp) {
    if (resp.success) {
      var a = resp.analysis;
      var skorText = a.human_score !== null ? `%${a.human_score}` : 'Metin Yok';
      hud.innerHTML = `🌿 <strong>İnsanilik Analizi:</strong> ${esc(skorText)} (${a.is_organic ? '✅ Organik' : '⚠️ Robotik kalıplar temizlendi'})<br>` +
        `• Temizlenen AI Kalıp Sayısı: <strong>${esc(a.slop_count)} adet</strong><br><br>` +
        `<strong>Arındırılmış İnsan Metni:</strong><br><br>` +
        `<span style="color:var(--site-text); font-family:var(--site-font); font-size:0.92rem; white-space:pre-wrap;">${esc(resp.cleaned_text)}</span>`;
    } else {
      hud.innerHTML = `<span style="color:var(--site-danger);">Hata: ${esc(resp.detail || 'İşlem başarısız')}</span>`;
    }
  })
  .catch(function(err) {
    hud.innerHTML = `<span style="color:var(--site-danger);">Ağ Hatası: ${esc(err.message)}</span>`;
  });
};

window.refreshGpuStatus = function() {
  var hud = document.getElementById('gpuOutputHud');
  hud.innerHTML = `[GPU KÜMESİ TELEMETRİSİ SORGULANIYOR...]`;

  fetch('/api/gpu/cluster/status')
  .then(function(res) { return res.json(); })
  .then(function(resp) {
    if (resp.success && resp.status) {
      var s = resp.status;
      hud.innerHTML = `🖥️ <strong>GPU Küme Telemetrisi:</strong><br>` +
        `• Durum: <strong>${esc(s.cluster_status || 'standby')}</strong><br>` +
        `• Tahsis Edilen vRAM: <strong>${esc(s.allocated_vram_gb !== undefined ? s.allocated_vram_gb : s.total_gpu_vram_gb)} GB</strong><br>` +
        `• Aktif Dağıtım Modu: <code>${esc(s.mode)}</code><br>` +
        `• Bilgi: <em>${esc(s.message || 'Bulut GPU kuyruğu hazır.')}</em>`;
    }
  })
  .catch(function(err) {
    hud.innerHTML = `Ağ hatası: ${esc(err.message)}`;
  });
};

window.handleGpuModeChange = function(newMode) {
  fetch('/api/gpu/cluster/mode', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + (token() || localStorage.getItem('cockpit_token') || '')
    },
    body: JSON.stringify({ mode: newMode })
  })
  .then(function() { window.refreshGpuStatus(); });
};
