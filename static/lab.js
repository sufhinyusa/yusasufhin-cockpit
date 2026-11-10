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
    var t = token() || localStorage.getItem('cockpit_token') || '';
    var rawUrl = job.video_url || job.output_url || '';
    if (!rawUrl) return;
    var tamUrl = rawUrl + (rawUrl.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(t);
    var indirUrl = tamUrl + '&download=1';

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
      outputBadgeEl.textContent = '✅ Üretildi — İndirmeye Hazır';
      outputBadgeEl.className = 'site-badge site-badge-free';
    }
    if (outputMetaEl) outputMetaEl.hidden = false;
    if (outputActionsEl) outputActionsEl.hidden = false;
    if (metaModelNameEl) metaModelNameEl.textContent = (job.model_ad || job.channel || job.model_id || 'Fabrika Video') + (job.status ? ' [' + job.status + ']' : '');
    if (metaResFpsEl) metaResFpsEl.textContent = (job.resolution || '1920x1080') + ' @ ' + (job.fps || 30) + ' FPS';
    if (metaDurScenesEl) metaDurScenesEl.textContent = (job.duration || 5) + ' sn';
    var kbVal = job.size_kb || (job.file_size_bytes ? Math.max(1, Math.round(Number(job.file_size_bytes) / 1024)) : 0);
    if (metaFileSizeEl) metaFileSizeEl.textContent = kbVal + ' KB';

    if (downloadLinkEl) {
      downloadLinkEl.href = indirUrl;
      downloadLinkEl.setAttribute('download', (job.id || job.job_id || 'kovalab_video') + '.mp4');
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
    var studioGridEl = document.getElementById('studioVideoHistoryGrid');
    if (!items || !items.length) {
      var bosHtml = '<div class="site-empty">Henüz üretilmiş bir video bulunmuyor. Yukarıdaki formdan "Video Prodüksiyonunu Başlat" butonuna basarak ilk videonuzu üretin!</div>';
      if (historyGridEl) historyGridEl.innerHTML = bosHtml;
      if (studioGridEl) studioGridEl.innerHTML = bosHtml;
      return;
    }
    var t = token() || localStorage.getItem('cockpit_token') || '';
    var kartlarHtml = items.map(function (item) {
      var rawUrl = item.output_url || item.video_url || '';
      var vUrl = rawUrl ? (rawUrl + (rawUrl.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(t)) : '';
      var dlUrl = vUrl ? (vUrl + '&download=1') : '#';
      var jid = item.job_id || item.id || 'video';
      var baslik = item.channel || item.model_ad || item.method || item.model_id || 'Fabrika Video';
      var durumEtiket = item.status || item.kaynak || 'onizleme_hazir (simülasyon)';
      var kb = item.size_kb || (item.file_size_bytes ? Math.max(1, Math.round(Number(item.file_size_bytes) / 1024)) : 0);
      var coz = item.resolution || '1920x1080';
      return '' +
        '<article class="site-card site-model-card">' +
          '<div style="display:flex; justify-content:space-between; align-items:center; gap:6px; margin-bottom:8px; flex-wrap:wrap;">' +
            '<span class="site-badge site-badge-free">✅ ÜRETİLDİ (İndirilebilir)</span>' +
            '<code style="font-size:0.74rem; color:var(--site-text-muted);">' + esc(jid) + '</code>' +
          '</div>' +
          (vUrl ? '<video controls playsinline preload="metadata" style="width:100%; border-radius:10px; margin-bottom:10px; background:#000; max-height:220px;" src="' + esc(vUrl) + '"></video>' : '') +
          '<h3 style="font-size:0.96rem; margin:0 0 4px;">' + esc(baslik) + '</h3>' +
          '<p style="font-size:0.82rem; margin:0 0 8px; color:var(--site-text-dim);">' + esc(item.prompt || 'Sinematik Video Üretimi') + '</p>' +
          '<div class="site-model-meta">' +
            '<div>Durum<strong>' + esc(durumEtiket) + '</strong></div>' +
            '<div>Çözünürlük<strong>' + esc(coz) + '</strong></div>' +
            '<div>Boyut<strong>' + esc(kb) + ' KB</strong></div>' +
          '</div>' +
          '<div style="margin-top:10px; display:flex; gap:8px; flex-wrap:wrap;">' +
            '<a href="' + esc(dlUrl) + '" download="fabrika-video-' + esc(jid) + '.mp4" ' +
               'style="background:#059669; color:#fff; padding:8px 14px; border-radius:8px; font-size:0.8rem; font-weight:600; text-decoration:none; display:inline-block;">' +
               '⬇️ Videoyu İndir (MP4)' +
            '</a>' +
            '<a class="site-btn site-btn-ghost" href="' + esc(vUrl) + '" target="_blank" rel="noopener" style="padding:8px 12px; font-size:0.78rem;">' +
               '🔗 Yeni Sekmede Aç' +
            '</a>' +
          '</div>' +
        '</article>';
    }).join('');
    if (historyGridEl) historyGridEl.innerHTML = kartlarHtml;
    if (studioGridEl) studioGridEl.innerHTML = kartlarHtml;
  }

  function sesGecmisiniCiz(items) {
    var audioGridEl = document.getElementById('studioAudioHistoryGrid');
    if (!audioGridEl) return;
    if (!items || !items.length) {
      audioGridEl.innerHTML = '<div class="site-empty">Henüz üretilmiş bir ses/müzik dosyası yok. Yukarıdaki formdan "Sentezle &amp; Üret" butonuna basarak ilk ses dosyanızı üretin!</div>';
      return;
    }
    var t = token() || localStorage.getItem('cockpit_token') || '';
    audioGridEl.innerHTML = items.map(function (item) {
      var rawUrl = item.output_url || '';
      var aUrl = rawUrl ? (rawUrl + (rawUrl.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(t)) : '';
      var dlUrl = aUrl ? (aUrl + '&download=1') : '#';
      var jid = item.job_id || 'ses';
      var kb = item.size_kb || (item.file_size_bytes ? Math.max(1, Math.round(Number(item.file_size_bytes) / 1024)) : 0);
      var sure = item.duration_sec || 6;
      var durumEtiket = item.status || 'onizleme_hazir (simülasyon)';
      return '' +
        '<article class="site-card site-model-card">' +
          '<div style="display:flex; justify-content:space-between; align-items:center; gap:6px; margin-bottom:8px; flex-wrap:wrap;">' +
            '<span class="site-badge site-badge-free">✅ SES ÜRETİLDİ (İndirilebilir)</span>' +
            '<code style="font-size:0.74rem; color:var(--site-text-muted);">' + esc(jid) + '</code>' +
          '</div>' +
          '<h3 style="font-size:0.95rem; margin:0 0 4px;">🎵 ' + esc(item.action || 'Ses Üretimi') + '</h3>' +
          '<p style="font-size:0.82rem; margin:0 0 8px; color:var(--site-text-dim);">' + esc(item.prompt || 'Ses Sentezi') + '</p>' +
          (aUrl ? '<audio controls preload="metadata" src="' + esc(aUrl) + '" style="width:100%; margin-bottom:10px;"></audio>' : '') +
          '<div class="site-model-meta">' +
            '<div>Durum<strong>' + esc(durumEtiket) + '</strong></div>' +
            '<div>Süre<strong>' + esc(sure) + ' sn</strong></div>' +
            '<div>Boyut<strong>' + esc(kb) + ' KB</strong></div>' +
          '</div>' +
          '<div style="margin-top:10px; display:flex; gap:8px; flex-wrap:wrap;">' +
            '<a href="' + esc(dlUrl) + '" download="fabrika-ses-' + esc(jid) + '.wav" ' +
               'style="background:#059669; color:#fff; padding:8px 14px; border-radius:8px; font-size:0.8rem; font-weight:600; text-decoration:none; display:inline-block;">' +
               '⬇️ Sesi İndir (.WAV)' +
            '</a>' +
            '<a class="site-btn site-btn-ghost" href="' + esc(aUrl) + '" target="_blank" rel="noopener" style="padding:8px 12px; font-size:0.78rem;">' +
               '🔗 Yeni Sekmede Aç' +
            '</a>' +
          '</div>' +
        '</article>';
    }).join('');
  }

  function gecmisiYukle() {
    var t = token() || localStorage.getItem('cockpit_token') || '';
    fetch('/api/lab/history', { headers: t ? { Authorization: 'Bearer ' + t } : {} })
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .then(function (veri) {
        var items = veri.items || [];
        gecmisiCiz(items);
        if (items.length && !sonIsKaydi) {
          videoyuOynaticiyaBagla(items[0]);
        }
      })
      .catch(function () { /* yoksay */ });

    fetch('/api/audio/history', { headers: t ? { Authorization: 'Bearer ' + t } : {} })
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .then(function (veri) {
        sesGecmisiniCiz(veri.items || []);
      })
      .catch(function () { /* yoksay */ });
  }
  window.refreshStudioMediaLists = gecmisiYukle;

  function yukle() {
    var t = token();
    if (!t) {
      bosDurum('Oturum bulunamadı. Lütfen ana sayfadan giriş yapın.');
      return;
    }
    bosDurum('Model kataloğu ve gerçek bulut sürücüleri yükleniyor…');
    gecmisiYukle();

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
  if ((viewKey === 'video' || viewKey === 'audio' || viewKey === 'wan') && window.refreshStudioMediaLists) {
    window.refreshStudioMediaLists();
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

  taskBadge.textContent = '⏳ Video Üretiliyor...';
  taskBadge.className = 'site-badge site-badge-free';

  hudLog.innerHTML = `[PRODÜKSİYON BAŞLATILDI]<br>` +
    `• Hedef Kanal: <strong>${esc(channel)}</strong><br>` +
    `• Metot: <strong>${esc(method)}</strong><br>` +
    `• Donanım: <strong>${esc(renderTarget)}</strong><br>` +
    `• Konu: "${esc(promptVal)}"<br>` +
    `• Durum: Aşama 1/5 Senaryo ve MP4 Video hazırlanıyor...`;

  var step1 = document.getElementById('step1');
  var step2 = document.getElementById('step2');
  var step3 = document.getElementById('step3');
  var step4 = document.getElementById('step4');
  var step5 = document.getElementById('step5');

  step1.className = 'site-pipeline-step done';
  step2.className = 'site-pipeline-step active';

  var tok = (window.token ? window.token() : '') || localStorage.getItem('fabrika_token') || localStorage.getItem('cockpit_token') || '';

  fetch('/api/studio/video/generate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + tok
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
      var outUrl = task.output_url || '';
      var boyut = (task.artifacts && task.artifacts.file_size_bytes) ? task.artifacts.file_size_bytes : 0;
      var boyutKb = boyut ? (boyut / 1024).toFixed(1) : '';
      var cozunurluk = (task.artifacts && task.artifacts.resolution) ? task.artifacts.resolution : '';
      var tamUrl = outUrl ? (outUrl + (outUrl.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(tok)) : '';
      var indirUrl = tamUrl ? (tamUrl + '&download=1') : '';

      if (outUrl) {
        step1.className = 'site-pipeline-step done';
        step2.className = 'site-pipeline-step done';
        step3.className = 'site-pipeline-step done';
        step4.className = 'site-pipeline-step done';
        step5.className = 'site-pipeline-step';

        taskBadge.textContent = '✅ Üretildi (İndirilebilir)';
        taskBadge.className = 'site-badge site-badge-free';

        hudLog.innerHTML += `<br>• ✅ <strong>VİDEO ÜRETİLDİ!</strong> <code>${esc(task.job_id)}</code><br>` +
          `• Boyut: <strong>${esc(boyutKb ? boyutKb + ' KB' : String(boyut) + ' bayt')}</strong> | Çözünürlük: <strong>${esc(cozunurluk)}</strong><br>` +
          `• Durum: <strong>${esc(task.status)}</strong><br>` +
          `• <em>${esc(task.message || '')}</em>`;

        stageArea.innerHTML = `
          <div style="padding:12px; width:100%;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:6px;">
              <span style="background:rgba(16,185,129,0.2); color:#34d399; border:1px solid rgba(16,185,129,0.45); padding:4px 10px; border-radius:6px; font-size:0.78rem; font-weight:700;">
                ✅ VİDEO ÜRETİLDİ (${esc(boyutKb ? boyutKb + ' KB' : 'MP4')})
              </span>
              <span style="font-size:0.76rem; color:var(--site-text-dim);">
                Çözünürlük: <strong>${esc(cozunurluk || 'MP4')}</strong> &bull; <code>${esc(task.job_id)}</code>
              </span>
            </div>
            <video controls autoplay playsinline preload="metadata" src="${esc(tamUrl)}"
                   style="width:100%; max-height:340px; border-radius:10px; background:#000; display:block; margin-bottom:12px;">
              Tarayıcınız video etiketini desteklemiyor.
            </video>
            <div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:center;">
              <a href="${esc(indirUrl)}" download="fabrika-video-${esc(task.job_id)}.mp4"
                 style="background:#059669; color:#fff; padding:10px 18px; border-radius:8px; font-weight:700; text-decoration:none; display:inline-block;">
                ⬇️ Videoyu İndir (MP4)
              </a>
              <a href="${esc(tamUrl)}" target="_blank" rel="noopener"
                 style="background:#1e293b; color:#e2e8f0; padding:10px 18px; border-radius:8px; font-weight:600; text-decoration:none; display:inline-block; border:1px solid #334155;">
                🔗 Yeni Sekmede Aç
              </a>
            </div>
            <p style="margin:10px 0 0; font-size:0.74rem; color:var(--site-text-muted); text-align:center;">
              Bilet: <code>${esc(task.job_id)}</code> &bull; Motor: <strong>${esc(task.method)}</strong> &bull;
              Durum: <strong>${esc(task.status)}</strong>
            </p>
          </div>
        `;
        if (window.refreshStudioMediaLists) window.refreshStudioMediaLists();
      } else {
        step1.className = 'site-pipeline-step done';
        step2.className = 'site-pipeline-step active';

        taskBadge.textContent = '⏳ Kuyrukta (Dosya Henüz Yok)';
        taskBadge.className = 'site-badge site-badge-free';

        hudLog.innerHTML += `<br>• ⚠️ <strong>MP4 Dosyası Henüz Üretilmedi — Kuyrukta:</strong> <code>${esc(task.job_id)}</code><br>` +
          `• Hedef Donanım: <strong>${esc(renderTarget).toUpperCase()}</strong> | Oran: <strong>${esc(aspect)}</strong><br>` +
          `• 📡 <em>${esc(task.message || 'GPU İşçisi sıradaki işi aldığında render başlayacaktır.')}</em>`;

        stageArea.innerHTML = `
          <div style="text-align:center; padding:16px;">
            <div style="font-size:2.4rem; margin-bottom:8px;">⏳</div>
            <strong style="color:#f59e0b;">MP4 Dosyası Henüz Üretilmedi (Kuyrukta)</strong>
            <p style="margin:4px 0 8px; font-size:0.84rem; color:var(--site-text-dim);">
              Bilet ID: <code>${esc(task.job_id)}</code> | Kanal: <strong>${esc(task.channel)}</strong>
            </p>
            <span class="site-badge site-badge-free">Durum: ${esc(task.status || 'queued')}</span>
          </div>
        `;
      }
    } else {
      hudLog.innerHTML += `<br><span style="color:var(--site-danger);">❌ Üretilemedi: ${esc(data.detail || data.error || 'Prodüksiyon başlatılamadı.')}</span>`;
      taskBadge.textContent = '❌ Üretilemedi';
    }
  })
  .catch(function(err) {
    hudLog.innerHTML += `<br><span style="color:var(--site-danger);">❌ Ağ Hatası: ${esc(err.message)}</span>`;
    taskBadge.textContent = '❌ Hata';
  });
};

/**
 * ÜRETİLEN VİDEOLAR GALERİSİ (2026-11-10)
 * Kullanıcı şikayeti: "üretilenleri sitede bulamıyorum indirme linki gibi bir şey koy"
 * Her iş için oynatıcı + indirme linki gösterir. Yalnız output_url'i olan
 * (gerçekten üretilmiş) videolar listelenir — sahte kayıt gösterilmez.
 */
window.loadVideoHistory = function () {
  var kutu = document.getElementById('videoHistoryList');
  if (!kutu) return;
  var tk = token() || localStorage.getItem('cockpit_token') || '';

  kutu.innerHTML = '<p style="margin:0; font-size:0.8rem; color:var(--site-text-muted);">Yükleniyor...</p>';

  fetch('/api/lab/history?limit=24', {
    headers: tk ? { 'Authorization': 'Bearer ' + tk } : {}
  })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var items = (data && data.items) || [];
      if (!items.length) {
        kutu.innerHTML = '<p style="margin:0; font-size:0.8rem; color:var(--site-text-muted);">' +
          'Henüz üretilmiş video yok. Yukarıdaki formdan ilk videonuzu üretin.</p>';
        return;
      }
      var html = '';
      items.forEach(function (it) {
        var u = it.output_url || '';
        var tam = u ? (u + (u.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(tk)) : '';
        var boyutKb = it.file_size_bytes ? Math.round(Number(it.file_size_bytes) / 1024) : '';
        var tarih = (it.created_at || '').toString().slice(0, 16);
        html += '<div style="background:#0f172a; border:1px solid #1e293b; border-radius:8px; padding:10px;">' +
          '<div style="display:flex; justify-content:space-between; gap:8px; margin-bottom:8px;">' +
            '<code style="font-size:0.72rem; color:#94a3b8;">' + esc(it.job_id) + '</code>' +
            '<span style="font-size:0.7rem; color:#64748b;">' + esc(tarih) + '</span>' +
          '</div>' +
          (it.prompt ? '<p style="margin:0 0 8px; font-size:0.78rem; color:#cbd5e1;">' + esc(it.prompt) + '</p>' : '') +
          '<video controls playsinline preload="none" src="' + esc(tam) + '" ' +
                 'style="width:100%; max-height:200px; border-radius:6px; background:#000; display:block; margin-bottom:8px;"></video>' +
          '<div style="display:flex; gap:6px; flex-wrap:wrap;">' +
            '<a href="' + esc(tam) + '" download="fabrika-' + esc(it.job_id) + '.mp4" ' +
               'style="background:#059669; color:#fff; padding:7px 12px; border-radius:6px; font-size:0.74rem; font-weight:600; text-decoration:none;">⬇️ İndir</a>' +
            '<a href="' + esc(tam) + '" target="_blank" rel="noopener" ' +
               'style="background:#1e293b; color:#e2e8f0; border:1px solid #334155; padding:7px 12px; border-radius:6px; font-size:0.74rem; font-weight:600; text-decoration:none;">🔗 Aç</a>' +
            '<span style="font-size:0.7rem; color:#64748b; align-self:center;">' +
              esc(it.resolution || '') + (boyutKb ? ' · ' + boyutKb + ' KB' : '') + '</span>' +
          '</div>' +
        '</div>';
      });
      kutu.innerHTML = html;
    })
    .catch(function (e) {
      kutu.innerHTML = '<p style="margin:0; font-size:0.8rem; color:var(--site-danger);">' +
        'Geçmiş yüklenemedi: ' + esc(e.message) + '</p>';
    });
};

// Sayfa açılışında galeriyi doldur
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function () { setTimeout(window.loadVideoHistory, 600); });
} else {
  setTimeout(window.loadVideoHistory, 600);
}


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
  var audioBadge = document.getElementById('audioTaskBadge');
  var audioStage = document.getElementById('audioStageArea');
  var genre = document.getElementById('audioGenreSelect').value;
  var bpm = Number(document.getElementById('audioBpmInput').value) || 120;

  if (!inputVal) {
    alert('Lütfen bir metin veya arama terimi girin.');
    return;
  }

  if (audioBadge) {
    audioBadge.textContent = '⏳ Ses Üretiliyor...';
    audioBadge.className = 'site-badge site-badge-free';
  }
  hud.innerHTML = `[SES SENTEZLENİYOR...] Aksiyon: <strong>${esc(currentAudioAction)}</strong> — Lütfen bekleyin...`;

  var params = {};
  if (currentAudioAction === 'generate_music') {
    params = { prompt: inputVal, genre: genre, bpm: bpm, duration_sec: 8 };
  } else if (currentAudioAction === 'voice_clone_tts') {
    params = { text: inputVal, voice_profile: 'yusuf_sahin_tr', emotion: 'enerjik' };
  } else if (currentAudioAction === 'generate_podcast') {
    params = { topic: inputVal, length_minutes: 5 };
  } else if (currentAudioAction === 'identify_music') {
    params = { lyrics: inputVal };
  }

  var tok = (window.token ? window.token() : '') || localStorage.getItem('fabrika_token') || localStorage.getItem('cockpit_token') || '';
  var authHeader = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + tok
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
        if (audioBadge) audioBadge.textContent = d.matched ? '✅ Şarkı Bulundu' : '🔍 Sonuç Yok';
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
      } else if (d.output_url) {
        var tamSesUrl = d.output_url + (d.output_url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(tok);
        var indirSesUrl = (d.download_url || (d.output_url + '&download=1')) + '&token=' + encodeURIComponent(tok);
        var sesBoyutKb = d.size_kb || (d.file_size_bytes ? (d.file_size_bytes / 1024).toFixed(1) : '');

        if (audioBadge) {
          audioBadge.textContent = '✅ Ses Üretildi (İndirilebilir)';
          audioBadge.className = 'site-badge site-badge-free';
        }

        hud.innerHTML = `✅ <strong>SES DOSYASI ÜRETİLDİ!</strong> <code>${esc(d.job_id || '')}</code><br>` +
          `• Motor: <strong>${esc(d.engine || '')}</strong><br>` +
          `• Boyut: <strong>${esc(sesBoyutKb ? sesBoyutKb + ' KB' : '')}</strong> | Süre: <strong>${esc(d.duration_sec || '')} sn</strong><br>` +
          `• Durum: <strong>${esc(d.status || '')}</strong><br>` +
          `• Mesaj: <em>${esc(d.message || '')}</em>`;

        if (audioStage) {
          audioStage.innerHTML = `
            <div style="background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.35); border-radius:10px; padding:14px;">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:6px;">
                <span style="background:rgba(16,185,129,0.2); color:#34d399; padding:3px 10px; border-radius:6px; font-size:0.78rem; font-weight:700;">
                  ✅ SES ÜRETİLDİ (${esc(sesBoyutKb ? sesBoyutKb + ' KB' : 'WAV')})
                </span>
                <span style="font-size:0.75rem; color:var(--site-text-dim);">
                  Süre: <strong>${esc(d.duration_sec || '')} sn</strong> &bull; <code>${esc(d.job_id || '')}</code>
                </span>
              </div>
              <audio controls autoplay preload="metadata" src="${esc(tamSesUrl)}" style="width:100%; height:40px; margin-bottom:10px;"></audio>
              <div style="display:flex; gap:8px; flex-wrap:wrap;">
                <a href="${esc(indirSesUrl)}" download="fabrika-ses-${esc(d.job_id || 'audio')}.wav"
                   style="background:#059669; color:#fff; padding:8px 16px; border-radius:8px; font-weight:700; font-size:0.82rem; text-decoration:none; display:inline-block;">
                  ⬇️ Sesi İndir (.WAV)
                </a>
                <a href="${esc(tamSesUrl)}" target="_blank" rel="noopener"
                   style="background:#1e293b; color:#e2e8f0; padding:8px 14px; border-radius:8px; font-weight:600; font-size:0.82rem; text-decoration:none; display:inline-block; border:1px solid #334155;">
                  🔗 Yeni Sekmede Aç
                </a>
              </div>
            </div>
          `;
        }
        if (window.refreshStudioMediaLists) window.refreshStudioMediaLists();
      } else {
        if (audioBadge) audioBadge.textContent = '❌ Ses Üretilemedi';
        hud.innerHTML = `⚠️ <strong>Ses Dosyası Üretilemedi:</strong><br>` +
          `• Motor: <strong>${esc(d.engine || '-')}</strong><br>` +
          `• Durum: <em>${esc(d.message || d.status || 'Dosya oluşturulamadı')}</em>`;
      }
    } else {
      if (audioBadge) audioBadge.textContent = '❌ Hata';
      hud.innerHTML = `<span style="color:var(--site-danger);">❌ Hata: ${esc(resp.detail || resp.error || 'İşlem başarısız veya oturum geçersiz')}</span>`;
    }
  })
  .catch(function(err) {
    if (audioBadge) audioBadge.textContent = '❌ Ağ Hatası';
    hud.innerHTML = `<span style="color:var(--site-danger);">❌ Ağ Hatası: ${esc(err.message)}</span>`;
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
      var workerHtml = '';
      if (s.workers && s.workers.length > 0) {
        workerHtml = '<br><strong>Bağlı Canlı İşçiler:</strong><ul style="margin:4px 0 0; padding-left:18px;">';
        s.workers.forEach(function(w) {
          workerHtml += `<li><code>${esc(w.worker_id)}</code>: <strong>${esc(w.gpu_name)}</strong> (${esc(w.vram_gb)} GB) - Durum: <span style="color:#10b981;">● ${esc(w.status)}</span></li>`;
        });
        workerHtml += '</ul>';
      }
      var isLive = s.kaggle_connected || s.colab_connected;
      var badge = isLive ? '<span class="site-badge site-badge-free" style="background:#10b981; color:#fff;">🟢 Canlı GPU Bağlı</span>' : '<span class="site-badge">⚪ Standby (GPU Bekleniyor)</span>';
      
      hud.innerHTML = `🖥️ <strong>GPU Küme Telemetrisi:</strong> ${badge}<br>` +
        `• Durum: <strong>${esc(s.cluster_status || 'standby')}</strong><br>` +
        `• Toplam GPU vRAM: <strong>${esc(s.allocated_vram_gb !== undefined ? s.allocated_vram_gb : s.total_gpu_vram_gb)} GB</strong><br>` +
        `• Aktif Dağıtım Modu: <code>${esc(s.mode)}</code><br>` +
        `• Bilgi: <em>${esc(s.message || 'Bulut GPU kuyruğu hazır.')}</em>` +
        workerHtml;
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
