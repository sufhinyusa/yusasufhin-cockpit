/* lab.js — Kova Lab & Burç Videosu Stüdyosu (Kaggle / Colab GPU I2V + T2V)
 *
 * Uç noktalar:
 *   GET  /api/lab/models        → Modeller ve sürücü durumu
 *   POST /api/lab/generate      → Kaggle / Colab GPU işçi kuyruğu (T2V / I2V / FLUX.2 önizleme)
 *   GET  /api/lab/job/{job_id}  → Canlı iş durumu, önizleme PNG veya bitmiş MP4 takibi
 *   GET  /api/lab/history       → Doğrulanmış MP4 galerisi
 *   GET  /api/burc/list         → 12 burç kataloğu
 *   POST /api/burc/video/generate → Burç senaryo + TTS + SRT/ASS + GPU kuyruğu
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

  window.reauthWithPin = function () {
    try {
      localStorage.removeItem('fabrika_token');
      localStorage.removeItem('cockpit_token');
    } catch (e) { }
    var girilenPin = prompt('🔐 Oturum süresi doldu veya sunucu yeniden başlatıldı.\nLütfen yönetici PIN kodunuzu girin:');
    if (!girilenPin || !girilenPin.trim()) {
      return Promise.resolve('');
    }
    return fetch('/api/auth/verify_pin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin: girilenPin.trim() })
    })
      .then(function (r) { return r.json(); })
      .then(function (resPin) {
        if (resPin && resPin.success && resPin.token) {
          try {
            localStorage.setItem('fabrika_token', resPin.token);
            localStorage.setItem('cockpit_token', resPin.token);
          } catch (e) { }
          return resPin.token;
        }
        alert('Hatalı PIN: ' + ((resPin && (resPin.detail || resPin.message)) || 'Yetkilendirme başarısız.'));
        return '';
      })
      .catch(function () { return ''; });
  };

  window.authFetch = function (url, opts) {
    var options = Object.assign({}, opts || {});
    function _doFetch(tokVal) {
      var headers = Object.assign({}, options.headers || {});
      if (tokVal) headers['Authorization'] = 'Bearer ' + tokVal;
      return fetch(url, Object.assign({}, options, { headers: headers }));
    }
    var cur = token();
    if (!cur) {
      return window.reauthWithPin().then(function (newTok) {
        return _doFetch(newTok);
      });
    }
    return _doFetch(cur).then(function (res) {
      if (res.status === 401) {
        return window.reauthWithPin().then(function (newTok) {
          if (!newTok) return res;
          return _doFetch(newTok);
        });
      }
      return res;
    });
  };

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
      var seciliMod = modeSelectEl ? modeSelectEl.value : 'image_first_preview';
      var imgModelEl = document.getElementById('studioImageModelSelect');
      var seciliImgModel = imgModelEl ? imgModelEl.value : 'flux2-klein';
      var seciliI2v = seciliModelId || (modelSelectEl ? modelSelectEl.value : 'wan2.1-i2v-14b');
      var seciliWorkflow = seciliMod;
      var seciliYontem = 'flux2_resim';
      if (yuklenenGorselBase64 || seciliMod === 'i2v') {
        seciliYontem = 'wan_i2v';
        seciliWorkflow = 'wan_i2v';
      } else if (seciliMod === 'image_then_i2v') {
        seciliYontem = 'image_then_i2v';
      } else if (seciliMod === 't2v') {
        seciliYontem = 't2v_direct';
        seciliWorkflow = 't2v_direct';
      } else {
        seciliYontem = 'flux2_resim';
        seciliWorkflow = 'image_first_preview';
      }

      var payload = {
        model_id: seciliI2v,
        model_ad: seciliModel.ad || seciliI2v || 'Wan 2.1 I2V',
        image_model: seciliImgModel,
        i2v_model: seciliI2v,
        workflow: seciliWorkflow,
        mode: seciliWorkflow,
        method: seciliYontem,
        style_preset: styleSelectEl ? styleSelectEl.value : 'cinematic_realism',
        render_target: 'kaggle_32gb',
        prompt: promptVal,
        negative_prompt: negPromptInputEl ? negPromptInputEl.value.trim() : '',
        image_base64: yuklenenGorselBase64,
        aspect_ratio: aspectSelectEl ? aspectSelectEl.value : '16:9',
        duration: durationSelectEl ? Number(durationSelectEl.value) : 5,
        fps: fpsSelectEl ? Number(fpsSelectEl.value) : 16,
        camera_motion: cameraSelectEl ? cameraSelectEl.value : 'otomatik',
        style: styleSelectEl ? styleSelectEl.value : 'cinematic_realism',
        tts_enabled: sesSecimi !== 'none',
        tts_voice: sesSecimi !== 'none' ? sesSecimi : 'Aoede',
        voice: sesSecimi !== 'none' ? sesSecimi : 'Aoede',
        subtitles_enabled: subtitlesCheckEl ? Boolean(subtitlesCheckEl.checked) : true,
        execution_mode: window._resolveStudioExecMode ? window._resolveStudioExecMode() : 'instant_cloud'
      };

      if (generateBtnEl) {
        generateBtnEl.disabled = true;
        generateBtnEl.textContent = '⏳ Üretiliyor…';
      }
      if (outputBadgeEl) {
        outputBadgeEl.textContent = 'Hazırlanıyor';
        outputBadgeEl.className = 'site-badge site-badge-auto';
      }
      durumYaz('İş (' + payload.model_ad + ') başlatılıyor…', false);

      function _bindKovaPreview(imgJob) {
        var tamOnizleme = imgJob.preview_image_url + '&token=' + encodeURIComponent(t);
        durumYaz('Önizleme görseli hazır! Aşağıdaki görseli beğendiyseniz I2V ile videoya çevirebilirsiniz.', false);
        if (!videoPlaceholderEl) return;
        videoPlaceholderEl.style.display = 'block';
        var chosenI2v = (modelSelectEl && modelSelectEl.value) ? modelSelectEl.value : 'wan2.1-i2v-14b';
        videoPlaceholderEl.innerHTML =
          '<img src="' + esc(tamOnizleme) + '" style="max-width:100%;max-height:300px;border-radius:10px;display:block;margin:0 auto 10px;">' +
          '<button type="button" class="site-btn site-btn-primary" id="labAnimatePreviewBtn">✅ Görseli Beğendim → ' + esc(chosenI2v) + ' Videoya Çevir</button>';
        var ab = document.getElementById('labAnimatePreviewBtn');
        if (ab) {
          ab.onclick = function () {
            yuklenenGorselBase64 = null;
            var i2vKey = (modelSelectEl && modelSelectEl.value) ? modelSelectEl.value : 'wan2.1-i2v-14b';
            if (modeSelectEl) modeSelectEl.value = 'i2v';
            durumYaz('Onaylı görsel ' + i2vKey + ' I2V hattına gönderiliyor...', false);
            fetch('/api/lab/generate', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + t },
              body: JSON.stringify({
                model_id: i2vKey,
                i2v_model: i2vKey,
                model_ad: i2vKey,
                style_preset: styleSelectEl ? styleSelectEl.value : 'cinematic_realism',
                mode: 'video',
                method: 'wan_i2v',
                workflow: 'wan_i2v',
                render_target: 'kaggle_32gb',
                execution_mode: window._resolveStudioExecMode ? window._resolveStudioExecMode() : 'instant_cloud',
                prompt: promptVal || 'smooth organic cinematic camera push and motion',
                duration: durationSelectEl ? Number(durationSelectEl.value) : 5,
                voice: voiceSelectEl ? voiceSelectEl.value : 'Aoede',
                input_image_url: imgJob.preview_image_url
              })
            }).then(function (rr) { return rr.json(); }).then(function (dd) {
              var jj = dd.job || dd.task;
              if (jj && jj.output_url && jj.status !== 'onizleme_hazir') {
                if (outputBadgeEl) outputBadgeEl.textContent = jj.simulasyon ? '⚠️ (simülasyon)' : '✅ Hazır';
                videoyuOynaticiyaBagla(jj); gecmisiYukle();
              } else if (jj && jj.job_id && window.pollLabJob) {
                durumYaz('I2V işi kuyruğa alındı: ' + jj.job_id, false);
                window.pollLabJob(jj.job_id, function (fin) {
                  if (fin.output_url) { videoyuOynaticiyaBagla(fin); gecmisiYukle(); }
                }, function (e) { durumYaz('I2V hatası: ' + e, true); });
              }
            });
          };
        }
      }

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
          var job = res.body.job || res.body.task;
          var simNot = (job && job.simulasyon) ? ' (simülasyon)' : '';
          durumYaz((res.body.message || 'İş başlatıldı!') + simNot, false);
          if (job && job.status === 'onizleme_hazir' && job.preview_image_url) {
            _bindKovaPreview(job);
            gecmisiYukle();
          } else if (job && job.output_url) {
            if (outputBadgeEl) outputBadgeEl.textContent = job.simulasyon ? '⚠️ (simülasyon)' : '✅ Hazır';
            videoyuOynaticiyaBagla(job);
            gecmisiYukle();
          } else if (job && job.job_id && window.pollLabJob) {
            window.pollLabJob(job.job_id, function (guncel) {
              if (guncel.output_url && guncel.status !== 'onizleme_hazir') {
                if (outputBadgeEl) {
                  outputBadgeEl.textContent = guncel.simulasyon ? '⚠️ (simülasyon)' : '✅ GPU Render Tamam';
                }
                durumYaz('Video hazır!', false);
                videoyuOynaticiyaBagla(guncel);
                gecmisiYukle();
              } else if (guncel.preview_image_url) {
                _bindKovaPreview(guncel);
              } else {
                durumYaz('Durum: ' + (guncel.status || 'bekliyor') + ' (' + (guncel.progress_pct || 0) + '%)', false);
              }
            }, function (errMsg) {
              durumYaz('GPU işi başarısız: ' + errMsg, true);
              if (outputBadgeEl) outputBadgeEl.textContent = '❌ Başarısız';
            });
          }
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
            generateBtnEl.textContent = '🎬 Kaggle / Colab GPU\'da Video Üret';
          }
        });
    });

    var previewFluxBtn = document.getElementById('studioPreviewFluxBtn');
    if (previewFluxBtn) {
      previewFluxBtn.addEventListener('click', function () {
        var t = token();
        var promptVal = promptInputEl ? promptInputEl.value.trim() : '';
        if (!t || !promptVal) {
          durumYaz('Önizleme görseli için oturum ve prompt gerekli.', true);
          return;
        }
        var imgKeyEl = document.getElementById('studioImageModelSelect');
        var imgKey = imgKeyEl ? imgKeyEl.value : 'flux2-klein';
        durumYaz('Anahtar görsel (' + imgKey + ') hazırlanıyor...', false);
        fetch('/api/lab/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + t },
          body: JSON.stringify({
            model_id: imgKey,
            image_model: imgKey,
            model_ad: imgKey + ' Önizleme',
            style_preset: styleSelectEl ? styleSelectEl.value : 'cinematic_realism',
            mode: 'flux2_resim',
            method: 'flux2_resim',
            workflow: 'image_first_preview',
            render_target: 'kaggle_32gb',
            execution_mode: window._resolveStudioExecMode ? window._resolveStudioExecMode() : 'instant_cloud',
            prompt: promptVal,
            aspect_ratio: aspectSelectEl ? aspectSelectEl.value : '16:9'
          })
        }).then(function (r) { return r.json(); }).then(function (d) {
          var jj = d.job || d.task;
          if (!d.success || !jj) {
            durumYaz(d.message || 'Önizleme gönderilemedi.', true);
            return;
          }
          function _showLabPrev(guncel) {
            if (!(guncel.preview_image_url && videoPlaceholderEl)) return;
            var u = guncel.preview_image_url + '&token=' + encodeURIComponent(t);
            var i2vKey = (modelSelectEl && modelSelectEl.value) ? modelSelectEl.value : 'wan2.1-i2v-14b';
            videoPlaceholderEl.style.display = 'block';
            videoPlaceholderEl.innerHTML =
              '<img src="' + esc(u) + '" style="max-width:100%;max-height:300px;border-radius:10px;display:block;margin:0 auto 10px;">' +
              '<button type="button" class="site-btn site-btn-primary" id="labFluxApproveBtn">✅ Görseli Beğendim → ' + esc(i2vKey) + ' Videoya Çevir</button>';
            var b = document.getElementById('labFluxApproveBtn');
            if (b) {
              b.onclick = function () {
                fetch('/api/lab/generate', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + t },
                  body: JSON.stringify({
                    model_id: i2vKey,
                    i2v_model: i2vKey,
                    model_ad: i2vKey,
                    style_preset: styleSelectEl ? styleSelectEl.value : 'cinematic_realism',
                    mode: 'video',
                    method: 'wan_i2v',
                    workflow: 'wan_i2v',
                    render_target: 'kaggle_32gb',
                    execution_mode: window._resolveStudioExecMode ? window._resolveStudioExecMode() : 'instant_cloud',
                    prompt: promptVal,
                    duration: durationSelectEl ? Number(durationSelectEl.value) : 5,
                    voice: voiceSelectEl ? voiceSelectEl.value : 'Aoede',
                    input_image_url: guncel.preview_image_url
                  })
                }).then(function (rr) { return rr.json(); }).then(function (resI2v) {
                  var j2 = resI2v.job || resI2v.task;
                  if (j2 && j2.output_url && j2.status !== 'onizleme_hazir') {
                    videoyuOynaticiyaBagla(j2); gecmisiYukle();
                  } else if (j2 && j2.job_id) {
                    durumYaz('Onaylı görsel I2V kuyruğunda: ' + j2.job_id, false);
                    window.pollLabJob(j2.job_id, function (f2) {
                      if (f2.output_url) { videoyuOynaticiyaBagla(f2); gecmisiYukle(); }
                    }, function (e) { durumYaz('I2V hatası: ' + e, true); });
                  }
                });
              };
            }
          }
          if (jj.preview_image_url) {
            durumYaz('Önizleme görseli hazır!', false);
            _showLabPrev(jj);
            gecmisiYukle();
            return;
          }
          durumYaz('Önizleme kuyruğa alındı (' + jj.job_id + '); worker sonucu bekleniyor...', false);
          if (window.pollLabJob) {
            window.pollLabJob(jj.job_id, function (guncel) { _showLabPrev(guncel); }, function (e) { durumYaz('Önizleme hatası: ' + e, true); });
          }
        });
      });
    }
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

    var gpuActiveGroup = '<optgroup label="⚡ Kaggle/Colab GPU Aktif I2V Modelleri (Tutarlı)">' +
      '<option value="wan2.1-i2v-14b">⚡ Wan 2.1 I2V 14B (NF4 4-bit)</option>' +
      '<option value="wan2.2-ti2v-5b">⚡ Wan 2.2 TI2V 5B (Yeni Nesil Hızlı)</option>' +
      '<option value="ltx-video">⚡ LTX-Video I2V (Hızlı Animasyon)</option>' +
      '<option value="cogvideox-5b-i2v">⚡ CogVideoX 5B I2V (3D Animasyon)</option>' +
      '<option value="svd-xt">⚡ Stable Video Diffusion XT (Atmosferik)</option>' +
      '<option value="wan2.1-t2v-1.3b">📝 Wan 2.1 T2V 1.3B (Görselsiz Taslak)</option>' +
      '</optgroup>';
    var tumSelectHtml = gpuActiveGroup;
    if (gercekOps.length) {
      tumSelectHtml += '<optgroup label="🟢 Otomatik Bulut Üretimi">' + gercekOps.join('') + '</optgroup>';
    }
    tumSelectHtml += digerGruplarHtml.join('');

    if (modelSelectEl) {
      modelSelectEl.innerHTML = tumSelectHtml;
      modelSelectEl.value = 'wan2.1-i2v-14b';
      seciliModelId = 'wan2.1-i2v-14b';
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

    // Varsayılan olarak GPU I2V aktif kalır (kullanıcı başka model tıkladıkça güncellenir)
    if (!seciliModelId) {
      var varsayilanId = tumModeller['luma'] ? 'luma' : (tumModeller['leonardo'] ? 'leonardo' : Object.keys(tumModeller)[0]);
      if (varsayilanId) modeliStudyoyaSec(varsayilanId, false);
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
        '⬇️ MP4 İndir' +
        '</a>' +
        '<a class="site-btn site-btn-ghost" href="' + esc(vUrl) + '" target="_blank" rel="noopener" style="padding:8px 12px; font-size:0.78rem;">' +
        '🔗 Aç' +
        '</a>' +
        '<button type="button" class="site-btn site-btn-ghost" style="padding:8px 12px; font-size:0.78rem;" onclick="publishJobToYoutube(\'' + esc(jid) + '\', \'studioHudLog\')">' +
        '📺 YouTube Paketi' +
        '</button>' +
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

window.switchStudioView = function (viewKey) {
  var viewMap = {
    'video': 'viewVideoStudio',
    'channels': 'viewChannelsStudio',
    'burc': 'viewBurcStudio',
    'audio': 'viewAudioStudio',
    'omni': 'viewOmniRoute',
    'humanizer': 'viewHumanizer',
    'gpu': 'viewGpuStudio',
    'wan': 'viewWanStudio'
  };

  var tabMap = {
    'video': 'tabNavVideo',
    'channels': 'tabNavChannels',
    'burc': 'tabNavBurc',
    'audio': 'tabNavAudio',
    'omni': 'tabNavOmni',
    'humanizer': 'tabNavHumanizer',
    'gpu': 'tabNavGpu',
    'wan': 'tabNavWan'
  };

  Object.keys(viewMap).forEach(function (k) {
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
  if (viewKey === 'burc' && window.loadBurcCatalog) {
    window.loadBurcCatalog();
  }
  if ((viewKey === 'video' || viewKey === 'channels' || viewKey === 'burc') && window.loadChannelsCatalog) {
    window.loadChannelsCatalog(viewKey === 'channels');
  }
  if ((viewKey === 'video' || viewKey === 'burc') && window.refreshStudioWorkerWarn) {
    window.refreshStudioWorkerWarn();
  }
  if ((viewKey === 'video' || viewKey === 'audio' || viewKey === 'wan' || viewKey === 'burc') && window.refreshStudioMediaLists) {
    window.refreshStudioMediaLists();
  }
};

// URL Hash Kontrolü (#videoStudio, #channelsStudio, #burcStudio, #audioStudio vb.)
(function initHashView() {
  var h = (window.location.hash || '').toLowerCase();
  if (h.includes('channel') || h.includes('kanal')) window.switchStudioView('channels');
  else if (h.includes('burc')) window.switchStudioView('burc');
  else if (h.includes('audio')) window.switchStudioView('audio');
  else if (h.includes('omni')) window.switchStudioView('omni');
  else if (h.includes('human')) window.switchStudioView('humanizer');
  else if (h.includes('gpu')) window.switchStudioView('gpu');
  else if (h.includes('wan') || h.includes('model')) window.switchStudioView('wan');
  else window.switchStudioView('video');
})();

window.setStudioPrompt = function (promptText) {
  var pInput = document.getElementById('videoPromptInput');
  if (pInput) {
    pInput.value = promptText;
    pInput.focus();
  }
};

var _studioVideoUploadedB64 = null;
var _studioVidImgInput = document.getElementById('studioVideoImageInput');
if (_studioVidImgInput) {
  _studioVidImgInput.addEventListener('change', function () {
    var f = _studioVidImgInput.files && _studioVidImgInput.files[0];
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
var _studioVidClearBtn = document.getElementById('studioVideoClearImgBtn');
if (_studioVidClearBtn) {
  _studioVidClearBtn.addEventListener('click', function () {
    _studioVideoUploadedB64 = null;
    if (_studioVidImgInput) _studioVidImgInput.value = '';
    var w = document.getElementById('studioVideoUploadedWrap');
    if (w) w.hidden = true;
  });
}

function _renderStudioPreviewApprove(task, i2vModel, tok) {
  var stageArea = document.getElementById('studioStageArea');
  var taskBadge = document.getElementById('studioTaskBadge');
  var step2 = document.getElementById('step2');
  var step3 = document.getElementById('step3');
  var step4 = document.getElementById('step4');
  var rawPrev = task.preview_image_url || task.output_url || '';
  var pUrl = rawPrev + (rawPrev.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(tok || '');
  var bekliyorOnay = (task.status === 'onizleme_hazir' || task.mode === 'flux2_resim' || task.method === 'flux2_resim');
  if (step2) step2.className = 'site-pipeline-step done';
  if (step3) step3.className = bekliyorOnay ? 'site-pipeline-step active' : 'site-pipeline-step done';
  if (step4 && !bekliyorOnay) step4.className = 'site-pipeline-step active';
  if (taskBadge) taskBadge.textContent = bekliyorOnay ? '🖼️ Görsel Hazır (Onay Bekliyor)' : '⏳ Görsel Hazır → I2V Üretiliyor';
  if (stageArea) {
    var onayBtnler = bekliyorOnay
      ? '<div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:center; margin-top:10px;">' +
      '<button type="button" id="studioApproveI2vBtn" class="site-btn site-btn-primary">✅ Görseli Beğendim → ' + esc(i2vModel) + ' ile Videoya Çevir</button>' +
      '<button type="button" id="studioRegenImgBtn" class="site-btn site-btn-ghost">🔄 Görseli Yeniden Üret</button>' +
      '</div>'
      : '<p style="margin:8px 0 0; font-size:0.8rem; color:var(--site-accent);">✨ Bu anahtar kare seçili <strong>' + esc(i2vModel) + '</strong> modeline beslendi, MP4 hazırlanıyor…</p>';
    stageArea.innerHTML =
      '<div style="padding:12px; width:100%; text-align:center;">' +
      '<img src="' + esc(pUrl) + '" alt="Anahtar kare önizleme" style="max-width:100%; max-height:340px; border-radius:10px; display:block; margin:0 auto; border:1px solid #334155;">' +
      onayBtnler +
      '</div>';
    var aBtn = document.getElementById('studioApproveI2vBtn');
    if (aBtn) aBtn.onclick = function () { window.handleStudioVideoSubmit(null, 'wan_i2v', rawPrev); };
    var rBtn = document.getElementById('studioRegenImgBtn');
    if (rBtn) rBtn.onclick = function () { window.handleStudioVideoSubmit(null, 'image_first_preview'); };
  }
  if (window.refreshStudioMediaLists) window.refreshStudioMediaLists();
}

function _renderStudioVideoPlayer(task, tok) {
  var stageArea = document.getElementById('studioStageArea');
  var taskBadge = document.getElementById('studioTaskBadge');
  var hudLog = document.getElementById('studioHudLog');
  var outUrl = task.output_url || '';
  var boyut = (task.artifacts && task.artifacts.file_size_bytes) || task.file_size_bytes || 0;
  var boyutKb = boyut ? (Number(boyut) / 1024).toFixed(1) : (task.size_kb ? String(task.size_kb) : '');
  var cozunurluk = (task.artifacts && task.artifacts.resolution) || task.resolution || '';
  var tamUrl = outUrl ? (outUrl + (outUrl.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(tok)) : '';
  var indirUrl = tamUrl ? (tamUrl + '&download=1') : '';
  var thumbUrl = task.preview_image_url ? (task.preview_image_url + (task.preview_image_url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(tok)) : '';
  var hfUrl = task.hyperframes_url ? (task.hyperframes_url + '?token=' + encodeURIComponent(tok)) : '';

  ['step1', 'step2', 'step3', 'step4'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.className = 'site-pipeline-step done';
  });
  var step5 = document.getElementById('step5');
  if (step5) step5.className = 'site-pipeline-step active';

  var simEtiket = task.simulasyon
    ? '⚠️ Bulut Hareket Kurgusu (simülasyon — GPU difüzyonu değil)'
    : '✅ Üretildi (İndirilebilir)';
  if (taskBadge) {
    taskBadge.textContent = simEtiket;
    taskBadge.className = task.simulasyon ? 'site-badge site-badge-auto' : 'site-badge site-badge-free';
  }
  if (hudLog) {
    var kr = task.kalite_raporu || {};
    var oe = task.open_edit_metrics || {};
    hudLog.innerHTML += '<br>• ✅ <strong>VİDEO HAZIR!</strong> <code>' + esc(task.job_id) + '</code>' +
      ' | Kaynak: <strong>' + esc(task.kaynak || task.method || '-') + '</strong>' +
      (task.image_prompt ? '<br>• 🎨 <strong>Görsel Sahne (' + esc(task.planner_source || 'yerel') + '):</strong> <code>' + esc(task.image_prompt) + '</code>' : '') +
      (task.motion_prompt ? '<br>• 🎥 <strong>Hareket:</strong> <code>' + esc(task.motion_prompt) + '</code>' : '') +
      (kr.sure_sn ? '<br>• 🧪 <strong>Link #296 FFmpeg Denetimi:</strong> <code>' + esc(kr.genislik + 'x' + kr.yukseklik + ' · ' + kr.sure_sn + 'sn · ' + (kr.ses ? 'sesli' : 'sessiz')) + '</code>' : '') +
      (oe.checked ? '<br>• 📏 <strong>open-edit Metrik Doğrulama:</strong> <code>' + (oe.clean ? 'temiz' : 'uyarı: ' + esc((oe.unverified_numbers || []).join(', '))) + '</code>' : '');
  }
  if (stageArea) {
    stageArea.innerHTML =
      '<div style="padding:12px; width:100%;">' +
      '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:6px;">' +
      '<span style="background:' + (task.simulasyon ? 'rgba(245,158,11,0.18); color:#fbbf24; border:1px solid rgba(245,158,11,0.45)' : 'rgba(16,185,129,0.2); color:#34d399; border:1px solid rgba(16,185,129,0.45)') + '; padding:4px 10px; border-radius:6px; font-size:0.78rem; font-weight:700;">' + esc(simEtiket) + ' (' + esc(boyutKb ? boyutKb + ' KB' : 'MP4') + ')</span>' +
      '<span style="font-size:0.76rem; color:var(--site-text-dim);">' + esc(cozunurluk || task.aspect_ratio || 'MP4') + ' &bull; <code>' + esc(task.job_id) + '</code></span>' +
      '</div>' +
      '<video controls autoplay playsinline preload="metadata" src="' + esc(tamUrl) + '" style="width:100%; max-height:340px; border-radius:10px; background:#000; display:block; margin-bottom:12px;"></video>' +
      '<div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:center;">' +
      '<a href="' + esc(indirUrl) + '" download="fabrika-video-' + esc(task.job_id) + '.mp4" style="background:#059669; color:#fff; padding:9px 15px; border-radius:8px; font-weight:700; text-decoration:none;">⬇️ MP4 İndir</a>' +
      (thumbUrl ? '<a href="' + esc(thumbUrl) + '" download="kapak-' + esc(task.job_id) + '.png" class="site-btn site-btn-ghost" style="padding:9px 14px;">🖼️ Kapak PNG</a>' : '') +
      (hfUrl ? '<a href="' + esc(hfUrl) + '" target="_blank" rel="noopener" class="site-btn site-btn-ghost" style="padding:9px 14px;">🎞️ HyperFrames HTML5</a>' : '') +
      '<button type="button" class="site-btn site-btn-ghost" style="padding:9px 14px;" onclick="analyzeStudioVideo(\'' + esc(task.job_id) + '\')">🔍 rea-video Analiz</button>' +
      '<button type="button" class="site-btn site-btn-ghost" style="padding:9px 14px;" onclick="requeueStudioJob(\'' + esc(task.job_id) + '\')">🚀 Gerçek Wan2.1 GPU\'ya Yükselt</button>' +
      '<button type="button" class="site-btn site-btn-primary" style="padding:9px 15px;" onclick="publishJobToYoutube(\'' + esc(task.job_id) + '\', \'studioHudLog\')">📤 YouTube Paketi / Yayınla</button>' +
      '</div>' +
      '</div>';
  }
  if (window.refreshStudioMediaLists) window.refreshStudioMediaLists();
  if (window.loadStudioQueue) window.loadStudioQueue();
}

window.handleStudioVideoSubmit = function (e, forcedWorkflow, approvedImageUrl) {
  if (e && e.preventDefault) e.preventDefault();
  var channel = (document.getElementById('videoChannelSelect') || {}).value || 'Tech_AI_Fabrika';
  var wfEl = document.getElementById('videoMethodSelect');
  var workflow = forcedWorkflow || (wfEl ? wfEl.value : 'image_first_preview');
  if (approvedImageUrl && workflow !== 'wan_i2v') workflow = 'wan_i2v';
  if (!approvedImageUrl && _studioVideoUploadedB64 && workflow === 'image_first_preview') {
    workflow = 'wan_i2v';
  }
  var stylePreset = (document.getElementById('videoStyleSelect') || {}).value || 'cinematic_realism';
  var imageModel = (document.getElementById('videoImageModelSelect') || {}).value || 'flux2-klein';
  var i2vModel = (document.getElementById('videoI2vModelSelect') || {}).value || 'wan2.1-i2v-14b';
  var renderTarget = (document.getElementById('videoRenderTarget') || {}).value || 'kaggle_32gb';
  var aspect = (document.getElementById('videoAspectSelect') || {}).value || '16:9';
  var duration = Number((document.getElementById('videoDurationSelect') || {}).value || 5);
  var cameraMotion = (document.getElementById('videoCameraSelect') || {}).value || 'otomatik';
  var voiceVal = (document.getElementById('videoVoiceSelect') || {}).value || 'Aoede';
  var promptVal = ((document.getElementById('videoPromptInput') || {}).value || '').trim();
  var negPromptVal = ((document.getElementById('videoNegPromptInput') || {}).value || '').trim();
  var sourceUrlVal = ((document.getElementById('videoSourceUrlInput') || {}).value || '').trim();
  var execMode = window._resolveStudioExecMode ? window._resolveStudioExecMode() : 'instant_cloud';
  var hudLog = document.getElementById('studioHudLog');
  var taskBadge = document.getElementById('studioTaskBadge');
  var stageArea = document.getElementById('studioStageArea');

  if (!promptVal && !approvedImageUrl && !_studioVideoUploadedB64 && !sourceUrlVal) {
    alert('Lütfen sahne konusunu / promptu girin, hedef URL yazın veya görsel yükleyin.');
    return;
  }

  if (taskBadge) {
    taskBadge.textContent = (execMode === 'instant_cloud' || (execMode === 'auto' && _liveGpuWorkersCount <= 0) || workflow === 'hyperframes_motion' || workflow === 'product_launch')
      ? '⚡ Bulutta Üretiliyor...' : '⏳ Kuyruğa Gönderiliyor...';
    taskBadge.className = 'site-badge site-badge-free';
  }
  if (hudLog) {
    hudLog.innerHTML = '[TUTARLI ÜRETİM BAŞLATILDI]<br>' +
      '• Kanal: <strong>' + esc(channel) + '</strong> | Tarz: <strong>' + esc(stylePreset) + '</strong> | Mod: <code>' + esc(execMode) + '</code><br>' +
      '• Akış: <strong>' + esc(workflow) + '</strong> | Görsel: <strong>' + esc(imageModel) + '</strong> → I2V: <strong>' + esc(i2vModel) + '</strong><br>' +
      (sourceUrlVal ? '• 🌐 Kaynak URL: <code>' + esc(sourceUrlVal) + '</code><br>' : '') +
      '• Konu: "' + esc(promptVal || 'Onaylı görsel hareketi') + '"';
  }

  var step1 = document.getElementById('step1');
  var step2 = document.getElementById('step2');
  var step3 = document.getElementById('step3');
  var step4 = document.getElementById('step4');
  var step5 = document.getElementById('step5');
  if (step1) step1.className = 'site-pipeline-step done';
  if (step2) step2.className = 'site-pipeline-step active';
  if (step3) step3.className = 'site-pipeline-step';
  if (step4) step4.className = 'site-pipeline-step';
  if (step5) step5.className = 'site-pipeline-step';

  window.authFetch('/api/studio/video/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      channel: channel,
      workflow: workflow,
      method: workflow,
      execution_mode: execMode,
      style_preset: stylePreset,
      image_model: imageModel,
      i2v_model: i2vModel,
      render_target: renderTarget,
      aspect_ratio: aspect,
      duration: duration,
      camera_motion: cameraMotion,
      prompt: promptVal || 'organic coherent scene motion from reference image',
      negative_prompt: negPromptVal,
      source_url: sourceUrlVal || null,
      voice: voiceVal,
      image_base64: approvedImageUrl ? null : _studioVideoUploadedB64,
      input_image_url: approvedImageUrl || null
    })
  })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      var liveTok = window.token ? window.token() : '';
      if (!data.success || !data.task) {
        if (hudLog) hudLog.innerHTML += '<br><span style="color:var(--site-danger);">❌ Başlatılamadı: ' + esc(data.detail || data.message || 'Hata') + '</span>';
        if (taskBadge) taskBadge.textContent = '❌ Başarısız';
        return;
      }
      var task = data.task;
      if (hudLog && (task.image_prompt || task.motion_prompt)) {
        hudLog.innerHTML += '<br>• Bilet: <code>' + esc(task.job_id) + '</code> — <em>' + esc(task.message || '') + '</em>' +
          (task.image_prompt ? '<br>• 🎨 <strong>İngilizce Görsel Sahne (' + esc(task.planner_source || 'yerel') + '):</strong> <code>' + esc(task.image_prompt) + '</code>' : '') +
          (task.motion_prompt ? '<br>• 🎥 <strong>Hareket:</strong> <code>' + esc(task.motion_prompt) + '</code>' : '');
      }
      if (task.status === 'onizleme_hazir' && (task.preview_image_url || task.output_url)) {
        _renderStudioPreviewApprove(task, i2vModel, liveTok);
        return;
      }
      if (task.output_url) {
        _renderStudioVideoPlayer(task, liveTok);
        return;
      }
      if (taskBadge) taskBadge.textContent = '⏳ GPU Kuyruğunda';
      if (stageArea) {
        stageArea.innerHTML = '<div style="text-align:center; padding:18px;">' +
          '<div style="font-size:2.2rem; margin-bottom:8px;">🖼️ ⏳</div>' +
          '<strong>GPU İşçisi Bekleniyor / Üretiliyor</strong>' +
          '<p style="margin:6px 0; font-size:0.82rem; color:var(--site-text-dim);">Bilet: <code>' + esc(task.job_id) + '</code> · Model: <strong>' + esc(task.method === 'flux2_resim' ? imageModel : i2vModel) + '</strong></p>' +
          '<button type="button" class="site-btn site-btn-primary" style="margin-top:8px;" onclick="instantRenderQueuedJob(\'' + esc(task.job_id) + '\')">⚡ Beklemeden Anında Bulutta Render Et</button>' +
          '</div>';
      }
      if (window.loadStudioQueue) window.loadStudioQueue();

      if (window.pollLabJob) {
        window.pollLabJob(task.job_id, function (guncel) {
          var pollTok = window.token ? window.token() : '';
          if (guncel.output_url && guncel.status !== 'onizleme_hazir') {
            _renderStudioVideoPlayer(guncel, pollTok);
          } else if (guncel.preview_image_url) {
            _renderStudioPreviewApprove(guncel, i2vModel, pollTok);
          } else if (hudLog) {
            if (taskBadge) taskBadge.textContent = '⏳ ' + (guncel.progress_pct || 0) + '%';
          }
        }, function (errMsg) {
          if (taskBadge) taskBadge.textContent = '⏳ Kuyrukta / Zaman Aşımı';
          if (hudLog) hudLog.innerHTML += '<br><span style="color:var(--site-warning);">⚠️ ' + esc(errMsg) + '</span>';
        });
      }
    })
    .catch(function (err) {
      if (hudLog) hudLog.innerHTML += '<br><span style="color:var(--site-danger);">❌ Ağ Hatası: ' + esc(err.message) + '</span>';
      if (taskBadge) taskBadge.textContent = '❌ Hata';
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
        var isImg = (it.status === 'onizleme_hazir' || /\.png(\?|$)/i.test(u));
        var mediaHtml = isImg
          ? '<img src="' + esc(tam) + '" alt="Önizleme" style="width:100%; max-height:200px; object-fit:contain; border-radius:6px; background:#000; display:block; margin-bottom:8px;" />'
          : '<video controls playsinline preload="none" src="' + esc(tam) + '" style="width:100%; max-height:200px; border-radius:6px; background:#000; display:block; margin-bottom:8px;"></video>';
        html += '<div style="background:#0f172a; border:1px solid #1e293b; border-radius:8px; padding:10px;">' +
          '<div style="display:flex; justify-content:space-between; gap:8px; margin-bottom:6px; flex-wrap:wrap;">' +
          '<code style="font-size:0.72rem; color:#94a3b8;">' + esc(it.job_id) + '</code>' +
          (it.simulasyon ? '<span style="font-size:0.68rem; color:#fbbf24;">⚠️ simülasyon</span>' : '<span style="font-size:0.68rem; color:#34d399;">● hazır</span>') +
          '</div>' +
          (it.prompt ? '<p style="margin:0 0 8px; font-size:0.78rem; color:#cbd5e1;">' + esc(it.prompt) + '</p>' : '') +
          mediaHtml +
          '<div style="display:flex; gap:6px; flex-wrap:wrap;">' +
          '<a href="' + esc(tam + '&download=1') + '" download="fabrika-' + esc(it.job_id) + (isImg ? '.png' : '.mp4') + '" ' +
          'style="background:#059669; color:#fff; padding:7px 12px; border-radius:6px; font-size:0.74rem; font-weight:600; text-decoration:none;">⬇️ İndir</a>' +
          '<button type="button" onclick="requeueStudioJob(\'' + esc(it.job_id) + '\')" ' +
          'style="background:#1e293b; color:#e2e8f0; border:1px solid #334155; padding:7px 10px; border-radius:6px; font-size:0.74rem; cursor:pointer;">🚀 GPU Yükselt</button>' +
          '<span style="font-size:0.7rem; color:#64748b; align-self:center;">' +
          esc(it.resolution || tarih || '') + (boyutKb ? ' · ' + boyutKb + ' KB' : '') + '</span>' +
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


window.switchAudioAction = function (action) {
  currentAudioAction = action;
  var btnMap = {
    'generate_music': 'audioTabMusic',
    'voice_clone_tts': 'audioTabVoice',
    'generate_podcast': 'audioTabPodcast',
    'identify_music': 'audioTabIdentify'
  };

  Object.keys(btnMap).forEach(function (k) {
    var b = document.getElementById(btnMap[k]);
    if (b) {
      if (k === action) b.classList.add('active');
      else b.classList.remove('active');
    }
  });

  var label = document.getElementById('audioPromptLabel');
  var input = document.getElementById('audioPromptInput');
  var paramRow = document.getElementById('audioParamRow');
  var voiceRow = document.getElementById('audioVoiceRow');

  if (action === 'generate_music') {
    label.textContent = 'Müzik İstem Açıklaması';
    input.placeholder = 'Örn: Eğlenceli enerjik Trakya Roman havası ritmi, klarnet ve darbuka solosu...';
    paramRow.style.display = 'grid';
    if (voiceRow) voiceRow.style.display = 'none';
  } else if (action === 'voice_clone_tts') {
    label.textContent = 'Seslendirilecek Metin (Google Gemini 2.5 Nöral TTS)';
    input.placeholder = 'Örn: Merhaba, Fabrika otonom ses stüdyosuna hoş geldiniz...';
    paramRow.style.display = 'none';
    if (voiceRow) voiceRow.style.display = 'block';
  } else if (action === 'generate_podcast') {
    label.textContent = 'Podcast Konusu veya Doküman Özeti (Podcastfy)';
    input.placeholder = 'Örn: Kaggle ve Colab GPU mimarisi ile sıfır maliyetle yapay zeka işletimi...';
    paramRow.style.display = 'none';
    if (voiceRow) voiceRow.style.display = 'block';
  } else if (action === 'identify_music') {
    label.textContent = 'Şarkı Sözleri veya Sosyal Medya İpucu';
    input.placeholder = 'Örn: Aman aman aman kara gözlüm sana yandı benim gönlüm...';
    paramRow.style.display = 'none';
    if (voiceRow) voiceRow.style.display = 'none';
  }
};

window.handleAudioSubmit = function (e) {
  e.preventDefault();
  var inputVal = document.getElementById('audioPromptInput').value.trim();
  var hud = document.getElementById('audioOutputHud');
  var audioBadge = document.getElementById('audioTaskBadge');
  var audioStage = document.getElementById('audioStageArea');
  var genre = document.getElementById('audioGenreSelect').value;
  var bpm = Number(document.getElementById('audioBpmInput').value) || 120;
  var voiceSelectEl = document.getElementById('audioVoiceSelect');
  var voiceVal = voiceSelectEl ? voiceSelectEl.value : 'Aoede';

  if (!inputVal) {
    alert('Lütfen bir metin veya arama terimi girin.');
    return;
  }

  if (audioBadge) {
    audioBadge.textContent = '⏳ Ses Üretiliyor...';
    audioBadge.className = 'site-badge site-badge-free';
  }
  hud.innerHTML = `[SES SENTEZLENİYOR...] Aksiyon: <strong>${esc(currentAudioAction)}</strong> (${esc(voiceVal)}) — Lütfen bekleyin...`;

  var params = {};
  if (currentAudioAction === 'generate_music') {
    params = { prompt: inputVal, genre: genre, bpm: bpm, duration_sec: 8 };
  } else if (currentAudioAction === 'voice_clone_tts') {
    params = { text: inputVal, voice: voiceVal, voice_profile: voiceVal, emotion: 'enerjik' };
  } else if (currentAudioAction === 'generate_podcast') {
    params = { topic: inputVal, voice: voiceVal, length_minutes: 5 };
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
    .then(function (res) { return res.json(); })
    .then(function (resp) {
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
    .catch(function (err) {
      if (audioBadge) audioBadge.textContent = '❌ Ağ Hatası';
      hud.innerHTML = `<span style="color:var(--site-danger);">❌ Ağ Hatası: ${esc(err.message)}</span>`;
    });
};

window.handleOmniRouteSubmit = function (e) {
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
    .then(function (res) { return res.json(); })
    .then(function (resp) {
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
    .catch(function (err) {
      hud.innerHTML = `<span style="color:var(--site-danger);">Ağ Hatası: ${esc(err.message)}</span>`;
    });
};

window.handleHumanizerSubmit = function (e) {
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
    .then(function (res) { return res.json(); })
    .then(function (resp) {
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
    .catch(function (err) {
      hud.innerHTML = `<span style="color:var(--site-danger);">Ağ Hatası: ${esc(err.message)}</span>`;
    });
};

window.refreshGpuStatus = function () {
  var hud = document.getElementById('gpuOutputHud');
  if (!hud) return;
  hud.innerHTML = `[GPU KÜMESİ TELEMETRİSİ SORGULANIYOR...]`;

  fetch('/api/gpu/cluster/status')
    .then(function (res) { return res.json(); })
    .then(function (resp) {
      if (resp.success && resp.status) {
        var s = resp.status;
        var workerHtml = '';
        if (s.workers && s.workers.length > 0) {
          workerHtml = '<br><strong>Bağlı Canlı İşçiler:</strong><ul style="margin:4px 0 0; padding-left:18px;">';
          s.workers.forEach(function (w) {
            workerHtml += `<li><code>${esc(w.worker_id)}</code>: <strong>${esc(w.gpu_name)}</strong> (${esc(w.vram_gb)} GB) - Durum: <span style="color:#10b981;">● ${esc(w.status)}</span></li>`;
          });
          workerHtml += '</ul>';
        }
        var isLive = s.kaggle_connected || s.colab_connected;
        var badge = isLive
          ? '<span class="site-badge site-badge-free" style="background:#10b981; color:#fff;">🟢 Canlı GPU Bağlı</span>'
          : '<span class="site-badge">⚪ Standby (İşçi Bekleniyor — Sıraya Alınır)</span>';

        hud.innerHTML = `🖥️ <strong>GPU Küme Telemetrisi:</strong> ${badge}<br>` +
          `• Durum: <strong>${esc(s.cluster_status || 'standby')}</strong><br>` +
          `• Bağlı vRAM: <strong>${esc(s.allocated_vram_gb !== undefined ? s.allocated_vram_gb : 0)} GB</strong><br>` +
          `• Aktif İşçi Sayısı: <strong>${esc(s.active_workers_count || 0)}</strong><br>` +
          `• Aktif Dağıtım Modu: <code>${esc(s.mode)}</code><br>` +
          `• Not: <em>${esc(s.message || 'Bağlı uzak GPU işçisi yoksa işler güvenli kuyrukta bekler.')}</em>` +
          workerHtml;
      }
    })
    .catch(function (err) {
      hud.innerHTML = `Ağ hatası: ${esc(err.message)}`;
    });
};

window.loadGpuWorkerSetup = function () {
  var tk = (window.token ? window.token() : '') || localStorage.getItem('fabrika_token') || localStorage.getItem('cockpit_token') || '';
  var codeEl = document.getElementById('gpuWorkerCmdCode');
  var hud = document.getElementById('gpuOutputHud');
  if (!tk) {
    alert('İşçi anahtarını (X-Worker-Key) almak için önce oturum açın.');
    return;
  }
  fetch('/api/gpu/worker-setup', { headers: { 'Authorization': 'Bearer ' + tk } })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
    .then(function (res) {
      if (!res.ok || !res.d || !res.d.success) {
        if (hud) hud.innerHTML += '<br><span style="color:var(--site-danger);">❌ İşçi komutu alınamadı.</span>';
        return;
      }
      var cmd = 'curl -sS ' + res.d.worker_script_url + ' -o gpu_worker.py && FABRIKA_WORKER_KEY=' +
        res.d.worker_key + ' python3 gpu_worker.py --server ' + res.d.server + ' --token ' + res.d.worker_key;
      if (codeEl) codeEl.textContent = cmd;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(cmd).catch(function () { });
      }
      if (hud) hud.innerHTML += '<br>• ✅ <strong>Anahtarlı Kaggle/Colab komutu güncellendi ve panoya kopyalandı.</strong>';
    });
};

window.pollLabJob = function (jobId, onUpdate, onFail, maxAttempts) {
  var attempts = 0;
  var limit = maxAttempts || 120;
  var timer = setInterval(function () {
    attempts += 1;
    var tk = (window.token ? window.token() : '') || localStorage.getItem('fabrika_token') || localStorage.getItem('cockpit_token') || '';
    if (!tk) {
      clearInterval(timer);
      if (onFail) onFail('Oturum anahtarı bulunamadı; yeniden giriş yapın.');
      return;
    }
    if (attempts > limit) {
      clearInterval(timer);
      if (onFail) onFail('Zaman aşımı: GPU işçisi yanıt vermedi. Kuyruktan anında bulutta render edebilirsiniz.');
      return;
    }
    var reqFn = window.authFetch || function (u, opts) {
      opts = opts || {};
      opts.headers = Object.assign({ 'Authorization': 'Bearer ' + tk }, opts.headers || {});
      return fetch(u, opts);
    };
    reqFn('/api/lab/job/' + encodeURIComponent(jobId), {})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.success || !data.job) return;
        var j = data.job;
        if (onUpdate) onUpdate(j);
        if (j.gpu_durum === 'basarisiz' || j.status === 'basarisiz' || j.gpu_durum === 'iptal') {
          clearInterval(timer);
          if (onFail) onFail(j.error || 'GPU işi tamamlanamadı.');
          return;
        }
        if (j.output_url || ((j.mode === 'flux2_resim' || j.mode === 'image_first_preview') && j.preview_image_url)) {
          clearInterval(timer);
        }
      })
      .catch(function () { });
  }, 4000);
};

var _burcUploadedB64 = null;
var _burcInputEl = document.getElementById('burcImageInput');
if (_burcInputEl) {
  _burcInputEl.addEventListener('change', function () {
    var f = _burcInputEl.files && _burcInputEl.files[0];
    if (!f) return;
    var r = new FileReader();
    r.onload = function (ev) {
      _burcUploadedB64 = ev.target.result;
      var w = document.getElementById('burcUploadedWrap');
      var img = document.getElementById('burcUploadedImg');
      if (img) img.src = _burcUploadedB64;
      if (w) w.hidden = false;
    };
    r.readAsDataURL(f);
  });
}
var _burcClearBtn = document.getElementById('burcClearImageBtn');
if (_burcClearBtn) {
  _burcClearBtn.addEventListener('click', function () {
    _burcUploadedB64 = null;
    if (_burcInputEl) _burcInputEl.value = '';
    var w = document.getElementById('burcUploadedWrap');
    if (w) w.hidden = true;
  });
}

window.loadBurcCatalog = function () {
  var sel = document.getElementById('burcSignSelect');
  if (!sel || sel.getAttribute('data-loaded') === '1') return;
  fetch('/api/burc/list')
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d || !d.success || !Array.isArray(d.items)) return;
      sel.innerHTML = d.items.map(function (b) {
        var kod = b.kod || b.slug || '';
        var s = kod === 'kova' ? ' selected' : '';
        return '<option value="' + esc(kod) + '"' + s + '>' + esc(b.ad) + ' (' + esc(b.tarih || '') + ' · ' + esc(b.element || '') + ')</option>';
      }).join('');
      sel.setAttribute('data-loaded', '1');
    })
    .catch(function () { });
};

window.handleBurcSubmit = function (forcedMethod, approvedImageUrl) {
  var msgEl = document.getElementById('burcStatusMsg');
  var hudEl = document.getElementById('burcHudLog');
  var badgeEl = document.getElementById('burcOutputBadge');
  var stageEl = document.getElementById('burcStageArea');
  var approveBox = document.getElementById('burcApproveActions');
  var approveBtn = document.getElementById('burcAnimatePreviewBtn');

  var burcKodu = (document.getElementById('burcSignSelect') || {}).value || 'kova';
  var target = (document.getElementById('burcRenderTarget') || {}).value || 'kaggle_32gb';
  var aspect = (document.getElementById('burcAspectSelect') || {}).value || '9:16';
  var sureSn = Number((document.getElementById('burcDurationSelect') || {}).value || 5);
  var konu = ((document.getElementById('burcTopicInput') || {}).value || '').trim();
  var bImgModel = (document.getElementById('burcImageModelSelect') || {}).value || 'flux2-klein';
  var bI2vModel = (document.getElementById('burcI2vModelSelect') || {}).value || 'wan2.1-i2v-14b';

  var rawPromptChecked = !!(document.getElementById('burcRawPromptCheck') || {}).checked;
  var yontem = forcedMethod || 'flux2_resim';
  if (!approvedImageUrl && _burcUploadedB64 && yontem !== 'flux2_resim') {
    yontem = 'wan_i2v';
  }

  var payload = {
    burc_kodu: burcKodu,
    konu: konu,
    raw_prompt: !!(konu && rawPromptChecked),
    sure_sn: sureSn,
    aspect_ratio: aspect,
    render_target: target,
    method: yontem,
    execution_mode: window._resolveStudioExecMode ? window._resolveStudioExecMode() : 'instant_cloud',
    image_model: bImgModel,
    i2v_model: bI2vModel,
    image_base64: approvedImageUrl ? null : _burcUploadedB64,
    input_image_url: approvedImageUrl || null
  };

  if (badgeEl) badgeEl.textContent = '⏳ Hazırlanıyor...';
  if (msgEl) msgEl.textContent = 'Senaryo, seslendirme ve üretim hazırlanıyor...';
  if (approveBox) approveBox.hidden = true;

  window.authFetch('/api/burc/video/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
    .then(function (res) {
      if (!res.ok || !res.d || !res.d.success) {
        throw new Error((res.d && (res.d.detail || res.d.message)) || 'Burç işi başlatılamadı.');
      }
      var tk = window.token ? window.token() : '';
      var job = res.d.task;
      var simBadge = job.metin_simulasyon ? ' <span class="site-badge" style="background:#f59e0b;color:#000;">(simülasyon metin)</span>' : '';
      if (badgeEl) badgeEl.textContent = job.gpu_kuyruk ? '⏳ GPU Kuyruğunda' : '✅ Hazır';
      if (msgEl) msgEl.textContent = res.d.message || 'Burç işi başlatıldı.';
      if (hudEl) {
        var bSahne = (res.d.senaryo && res.d.senaryo.image_prompt) || job.image_prompt || job.prompt || '';
        var bKaynak = (res.d.senaryo && res.d.senaryo.kaynak) || job.senaryo_kaynak || '';
        var metinBaslik = job.raw_prompt ? 'Prompt' : 'Anlatım';
        hudEl.innerHTML = '♈ <strong>' + esc((res.d.burc && res.d.burc.ad) || burcKodu) + '</strong> · Bilet: <code>' + esc(res.d.job_id) + '</code>' + simBadge + '<br>' +
          '• Yöntem: <strong>' + esc(job.method) + '</strong> | Hedef: <strong>' + esc(job.render_target) + '</strong> | Oran: <strong>' + esc(job.aspect_ratio || aspect) + '</strong><br>' +
          '• ' + metinBaslik + ': <em>' + esc((res.d.senaryo && res.d.senaryo.narration_text) || '') + '</em>' +
          (bSahne ? '<br>• 🎨 <strong>Görsel Sahne (' + esc(bKaynak || 'yerel') + '):</strong> <code>' + esc(bSahne) + '</code>' : '');
      }

      function _burcGuncelle(guncel) {
        if (guncel.output_url && guncel.status !== 'onizleme_hazir') {
          var u = guncel.output_url + (guncel.output_url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(tk);
          if (badgeEl) badgeEl.textContent = guncel.simulasyon ? '⚠️ Tamamlandı (simülasyon)' : '✅ Burç Videosu Hazır';
          if (stageEl) {
            stageEl.innerHTML =
              '<video controls autoplay playsinline preload="metadata" src="' + esc(u) + '" style="width:100%;height:auto;max-height:440px;object-fit:contain;border-radius:10px;background:#000;display:block;"></video>' +
              '<div style="width:100%;display:flex;gap:8px;flex-wrap:wrap;justify-content:center;align-items:center;">' +
              '<a href="' + esc(u + '&download=1') + '" download="' + esc(guncel.job_id) + '.mp4" class="site-btn site-btn-primary">⬇️ Burç Videosunu İndir</a>' +
              '<a href="' + esc(u) + '" target="_blank" rel="noopener" class="site-btn site-btn-ghost">🔗 Tam Ekran / Aç</a>' +
              '</div>';
          }
          if (window.refreshStudioMediaLists) window.refreshStudioMediaLists();
          return true;
        }
        if (guncel.preview_image_url) {
          var pUrl = guncel.preview_image_url + (guncel.preview_image_url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(tk);
          if (badgeEl) badgeEl.textContent = '🖼️ Önizleme Görseli Hazır (Onay Bekliyor)';
          if (stageEl) {
            stageEl.innerHTML = '<img src="' + esc(pUrl) + '" alt="Burç önizleme görseli" style="width:100%;max-width:100%;max-height:420px;object-fit:contain;border-radius:10px;display:block;margin:0 auto;">';
          }
          if (approveBox && approveBtn) {
            approveBtn.textContent = '✅ Görseli Beğendim → ' + bI2vModel + ' ile Videoya Çevir';
            approveBox.hidden = false;
            approveBtn.onclick = function () {
              window.handleBurcSubmit('wan_i2v', guncel.preview_image_url);
            };
          }
          return true;
        }
        if (hudEl) {
          hudEl.innerHTML += '<br>• İlerleme: ' + esc(guncel.status || 'bekliyor') + ' (' + esc(guncel.progress_pct || 0) + '%)';
        }
        return false;
      }

      if (_burcGuncelle(job)) return;

      window.pollLabJob(res.d.job_id, function (guncel) { _burcGuncelle(guncel); }, function (errTxt) {
        if (badgeEl) badgeEl.textContent = '⏳ Beklemede';
        if (msgEl) msgEl.textContent = 'Durum: ' + errTxt;
      });
    })
    .catch(function (err) {
      if (badgeEl) badgeEl.textContent = '❌ Hata';
      if (msgEl) msgEl.textContent = err.message;
    });
};

window.handleGpuModeChange = function (newMode) {
  fetch('/api/gpu/cluster/mode', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + (token() || localStorage.getItem('cockpit_token') || '')
    },
    body: JSON.stringify({ mode: newMode })
  })
    .then(function () { window.refreshGpuStatus(); });
};

// ═══════════════════════════════════════════════════════════════════════════
// KAYDIRMALI MODEL/STİL TEPSİLERİ + ÇOKLU YOUTUBE KANALI & YAYIN OTOMASYONU
// ═══════════════════════════════════════════════════════════════════════════
var _studioCatalogCache = null;

function _syncPickerTray(trayId, selectId, items, labelKey, subKey) {
  var tray = document.getElementById(trayId);
  var sel = document.getElementById(selectId);
  if (!tray || !sel || !Array.isArray(items)) return;

  var activeVal = sel.value;
  tray.innerHTML = items.map(function (it) {
    var val = String(it.id || '');
    var text = String(it[labelKey] || it.name || it.ad || val);
    var badge = (subKey && it[subKey]) ? ' · ' + String(it[subKey]) : '';
    var cls = val === activeVal ? 'site-picker-pill active' : 'site-picker-pill';
    return '<button type="button" class="' + cls + '" data-picker-val="' + esc(val) + '">' + esc(text + badge) + '</button>';
  }).join('');

  tray.querySelectorAll('.site-picker-pill').forEach(function (btn) {
    btn.addEventListener('click', function () {
      sel.value = btn.getAttribute('data-picker-val') || '';
      sel.dispatchEvent(new Event('change'));
    });
  });

  if (!sel.getAttribute('data-tray-bound')) {
    sel.addEventListener('change', function () {
      var cur = sel.value;
      tray.querySelectorAll('.site-picker-pill').forEach(function (b) {
        if (b.getAttribute('data-picker-val') === cur) b.classList.add('active');
        else b.classList.remove('active');
      });
    });
    sel.setAttribute('data-tray-bound', '1');
  }
}

function _fillSelectOptions(selectId, items, labelKey) {
  var sel = document.getElementById(selectId);
  if (!sel || !Array.isArray(items)) return;
  var prev = sel.value;
  sel.innerHTML = items.map(function (it) {
    var v = String(it.id || '');
    var txt = String(it[labelKey] || it.name || it.ad || v);
    return '<option value="' + esc(v) + '">' + esc(txt) + '</option>';
  }).join('');
  if (prev && items.some(function (it) { return it.id === prev; })) sel.value = prev;
}

window.applyChannelToStudio = function (channelId, fillDefaultPrompt) {
  if (!_studioCatalogCache || !Array.isArray(_studioCatalogCache.channels)) return;
  var ch = _studioCatalogCache.channels.find(function (c) { return c.id === channelId; });
  if (!ch) return;

  var map = {
    videoStyleSelect: ch.style_preset,
    videoImageModelSelect: ch.image_model,
    videoI2vModelSelect: ch.i2v_model,
    videoMethodSelect: ch.workflow || 'image_first_preview',
    videoAspectSelect: ch.aspect_ratio,
    videoVoiceSelect: ch.voice,
    videoDurationSelect: String(ch.duration || 5),
    videoCameraSelect: ch.camera_motion || 'otomatik'
  };
  Object.keys(map).forEach(function (elId) {
    var el = document.getElementById(elId);
    if (el && map[elId]) {
      el.value = map[elId];
      el.dispatchEvent(new Event('change'));
    }
  });
  var promptEl = document.getElementById('videoPromptInput');
  if (promptEl && ch.default_prompt && (fillDefaultPrompt || !promptEl.value.trim())) {
    promptEl.value = ch.default_prompt;
  }
};

window.loadChannelsCatalog = function (force) {
  if (_studioCatalogCache && !force) return Promise.resolve(_studioCatalogCache);
  return fetch('/api/studio/catalog')
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d || !d.success) return d;
      _studioCatalogCache = d;
      _fillSelectOptions('videoChannelSelect', d.channels, 'name');
      _fillSelectOptions('videoStyleSelect', d.styles, 'ad');
      _fillSelectOptions('videoImageModelSelect', d.image_models, 'ad');
      _fillSelectOptions('videoI2vModelSelect', d.i2v_models, 'ad');
      _fillSelectOptions('chImageModelSelect', d.image_models, 'ad');
      _fillSelectOptions('chI2vModelSelect', d.i2v_models, 'ad');
      _fillSelectOptions('burcImageModelSelect', d.image_models, 'ad');
      _fillSelectOptions('burcI2vModelSelect', d.i2v_models, 'ad');
      _fillSelectOptions('studioImageModelSelect', d.image_models, 'ad');

      _syncPickerTray('videoChannelTray', 'videoChannelSelect', d.channels, 'name', 'handle');
      _syncPickerTray('videoStyleTray', 'videoStyleSelect', d.styles, 'ad');
      _syncPickerTray('videoImageModelTray', 'videoImageModelSelect', d.image_models, 'id');
      _syncPickerTray('videoI2vModelTray', 'videoI2vModelSelect', d.i2v_models, 'id');

      var chSel = document.getElementById('videoChannelSelect');
      if (chSel && !chSel.getAttribute('data-channel-bound')) {
        chSel.addEventListener('change', function () {
          window.applyChannelToStudio(chSel.value, false);
        });
        chSel.setAttribute('data-channel-bound', '1');
        window.applyChannelToStudio(chSel.value, false);
      }

      window.renderChannelsManager(d);
      return d;
    })
    .catch(function () { });
};

window.renderChannelsManager = function (d) {
  var grid = document.getElementById('channelsListGrid');
  var ytBox = document.getElementById('youtubeAuthBox');
  var ytBadge = document.getElementById('ytAuthBadge');
  var yt = (d && d.youtube_auth) || {};
  if (ytBadge) {
    ytBadge.textContent = yt.ready_for_live_upload ? '🟢 YouTube API Bağlı' : '🟡 OAuth Bekliyor (Yerel Paket)';
  }
  if (ytBox) {
    ytBox.innerHTML = '• Durum: <strong>' + esc(yt.ready_for_live_upload ? 'Canlı YouTube API Aktif' : 'Bağlı Değil (Simülasyon Paketi Modu)') + '</strong><br>' +
      '• <code>client_secret.json</code>: <strong>' + (yt.client_secret_present ? 'Mevcut' : 'Yok') + '</strong> | OAuth Token: <strong>' + (yt.oauth_token_present ? 'Mevcut' : 'Yok') + '</strong><br>' +
      '• ' + esc(yt.message || '');
  }
  if (!grid || !d || !Array.isArray(d.channels)) return;
  grid.innerHTML = d.channels.map(function (ch) {
    return '<div class="site-channel-card">' +
      '<div style="display:flex; justify-content:space-between; align-items:flex-start; gap:6px;">' +
      '<div><strong>' + esc(ch.name) + '</strong><div style="font-size:0.74rem; color:var(--site-text-dim);">' + esc(ch.handle || ch.id) + ' · ' + esc(ch.aspect_ratio) + '</div></div>' +
      '<span class="site-badge">' + (ch.youtube_connected ? '🟢 YT Bağlı' : '⚪ Taslak') + '</span>' +
      '</div>' +
      '<div style="font-size:0.75rem; color:var(--site-text-dim); line-height:1.45;">' +
      'Tarz: <strong>' + esc(ch.style_preset) + '</strong><br>' +
      'Görsel: <code>' + esc(ch.image_model) + '</code> → I2V: <code>' + esc(ch.i2v_model) + '</code><br>' +
      'Ses: <strong>' + esc(ch.voice) + '</strong> · Gizlilik: <strong>' + esc(ch.privacy || 'private') + '</strong>' +
      '</div>' +
      '<div style="display:flex; gap:6px; flex-wrap:wrap; margin-top:auto;">' +
      '<button type="button" class="site-btn site-btn-primary" style="padding:6px 10px; font-size:0.75rem; flex:1;" onclick="useChannelInStudio(\'' + esc(ch.id) + '\')">🎬 Stüdyoda Kullan</button>' +
      '<button type="button" class="site-btn site-btn-ghost" style="padding:6px 10px; font-size:0.75rem;" onclick="editChannel(\'' + esc(ch.id) + '\')">✏️</button>' +
      '<button type="button" class="site-btn site-btn-ghost" style="padding:6px 10px; font-size:0.75rem;" onclick="deleteChannel(\'' + esc(ch.id) + '\')">🗑️</button>' +
      '</div>' +
      '</div>';
  }).join('');
};

window.useChannelInStudio = function (chId) {
  var sel = document.getElementById('videoChannelSelect');
  if (sel) {
    sel.value = chId;
    window.applyChannelToStudio(chId, true);
  }
  window.switchStudioView('video');
};

window.editChannel = function (chId) {
  if (!_studioCatalogCache || !Array.isArray(_studioCatalogCache.channels)) return;
  var ch = _studioCatalogCache.channels.find(function (c) { return c.id === chId; });
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
  var form = document.getElementById('channelManagerForm');
  if (form) form.reset();
  document.getElementById('chEditIdInput').value = '';
};

window.handleSaveChannel = function (ev) {
  if (ev && ev.preventDefault) ev.preventDefault();
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
      if (msgEl) msgEl.textContent = '✅ Kanal kaydedildi: ' + (d.channel && d.channel.name);
      window.resetChannelForm();
      window.loadChannelsCatalog(true);
    } else {
      if (msgEl) msgEl.textContent = '❌ ' + ((d && d.detail) || 'Kaydedilemedi');
    }
  }).catch(function (e) { if (msgEl) msgEl.textContent = '❌ ' + e.message; });
};

window.deleteChannel = function (chId) {
  if (!confirm(chId + ' kanal profilini silmek istiyor musunuz?')) return;
  window.authFetch('/api/channels/' + encodeURIComponent(chId), {
    method: 'DELETE'
  }).then(function (r) { return r.json(); }).then(function () {
    window.loadChannelsCatalog(true);
  });
};

window.handleSaveYtSecret = function () {
  var raw = ((document.getElementById('ytSecretJsonInput') || {}).value || '').trim();
  if (!raw) { alert('client_secret.json içeriği gerekli.'); return; }
  window.authFetch('/api/youtube/oauth-secret', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_secret_json: raw })
  }).then(function (r) { return r.json(); }).then(function (d) {
    alert(d.success ? ('✅ ' + d.message) : ('❌ ' + (d.detail || d.message)));
    window.loadChannelsCatalog(true);
  });
};

window.publishJobToYoutube = function (jobId, hudId) {
  var hud = document.getElementById(hudId || 'studioHudLog');
  window.authFetch('/api/youtube/publish/' + encodeURIComponent(jobId), {
    method: 'POST'
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (hud) {
      var b = d.bundle || {};
      hud.innerHTML += '<br>• 📺 <strong>YouTube Paketi:</strong> Başlık: <em>' + esc(b.title || '') + '</em> | Etiketler: <code>' + esc((b.tags || []).join(', ')) + '</code><br>' +
        '• 📡 <strong>Durum:</strong> ' + esc(d.message || d.status || '');
    }
  }).catch(function (e) {
    if (hud) hud.innerHTML += '<br>❌ YouTube paket hatası: ' + esc(e.message);
  });
};

var _liveGpuWorkersCount = 0;

window._resolveStudioExecMode = function () {
  var sel = (document.getElementById('videoExecModeSelect') || {}).value || 'auto';
  if (sel === 'gpu_queue') return 'gpu_queue';
  if (sel === 'instant_cloud') return 'instant_cloud';
  return 'auto';
};

window.refreshStudioWorkerWarn = function () {
  var badge = document.getElementById('studioGpuWorkerWarn');
  fetch('/api/gpu/cluster/status')
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var st = (d && d.status) ? d.status : (d || {});
      var workers = Array.isArray(st.workers) ? st.workers : (Array.isArray(d && d.active_workers) ? d.active_workers : []);
      var n = (typeof st.active_workers_count === 'number') ? st.active_workers_count : workers.length;
      _liveGpuWorkersCount = n;
      if (!badge) return;
      if (n > 0) {
        var g = (workers[0] && workers[0].gpu_name) || 'GPU';
        badge.textContent = '🟢 Canlı GPU İşçisi: ' + n + ' (' + g + ')';
        badge.className = 'site-badge site-badge-free';
      } else {
        badge.textContent = '⚡ GPU İşçisi: 0 (Otomatik Anında Bulut + HyperFrames Aktif)';
        badge.className = 'site-badge site-badge-auto';
      }
    }).catch(function () { });
};

window.loadStudioQueue = function () {
  var listEl = document.getElementById('studioQueueList');
  if (!listEl || !window.authFetch) return;
  var tk = (window.token ? window.token() : '') || localStorage.getItem('cockpit_token') || '';
  if (!tk) return;
  window.authFetch('/api/studio/queue?status=bekliyor&limit=30', {})
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var items = (d && Array.isArray(d.items)) ? d.items : [];
      if (!items.length) {
        listEl.innerHTML = '<div class="site-empty">Bekleyen GPU bileti yok — tüm işler üretildi veya kuyruk temiz.</div>';
        return;
      }
      listEl.innerHTML = items.map(function (it) {
        return '<article class="site-card site-model-card">' +
          '<div style="display:flex; justify-content:space-between; gap:6px; flex-wrap:wrap; margin-bottom:6px;">' +
          '<span class="site-badge site-badge-auto">⏳ ' + esc(it.gpu_durum || 'bekliyor') + '</span>' +
          '<code style="font-size:0.74rem; color:var(--site-text-muted);">' + esc(it.job_id) + '</code>' +
          '</div>' +
          '<h3 style="font-size:0.92rem; margin:0 0 4px;">' + esc(it.channel || it.method || 'Video İşi') + ' · ' + esc(it.aspect_ratio || '16:9') + '</h3>' +
          '<p style="font-size:0.8rem; color:var(--site-text-dim); margin:0 0 10px;">' + esc(it.prompt || '') + '</p>' +
          '<div style="display:flex; gap:8px; flex-wrap:wrap;">' +
          '<button type="button" class="site-btn site-btn-primary" style="padding:7px 12px; font-size:0.78rem;" onclick="instantRenderQueuedJob(\'' + esc(it.job_id) + '\')">⚡ Anında Bulutta Render Et</button>' +
          '<button type="button" class="site-btn site-btn-ghost" style="padding:7px 12px; font-size:0.78rem;" onclick="cancelQueuedJob(\'' + esc(it.job_id) + '\')">✖️ İptal</button>' +
          '</div>' +
          '</article>';
      }).join('');
    }).catch(function () { });
};

window.instantRenderQueuedJob = function (jobId) {
  var hudLog = document.getElementById('studioHudLog');
  var taskBadge = document.getElementById('studioTaskBadge');
  if (taskBadge) taskBadge.textContent = '⚡ Anında Bulutta Render Ediliyor...';
  if (hudLog) hudLog.innerHTML += '<br>• ⚡ Kuyruk bileti <code>' + esc(jobId) + '</code> bulutta anında render ediliyor...';
  window.authFetch('/api/studio/queue/' + encodeURIComponent(jobId) + '/instant-render', { method: 'POST' })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
    .then(function (res) {
      var liveTok = window.token ? window.token() : '';
      if (!res.ok || !res.d || !res.d.task) {
        if (taskBadge) taskBadge.textContent = '❌ Başarısız';
        if (hudLog) hudLog.innerHTML += '<br><span style="color:var(--site-danger);">❌ ' + esc((res.d && res.d.detail) || 'Bulut render başarısız') + '</span>';
        return;
      }
      var t = res.d.task;
      if (t.status === 'onizleme_hazir') {
        _renderStudioPreviewApprove(t, t.i2v_model || 'wan2.1-i2v-14b', liveTok);
      } else {
        _renderStudioVideoPlayer(t, liveTok);
      }
    }).catch(function (e) {
      if (hudLog) hudLog.innerHTML += '<br>❌ ' + esc(e.message);
    });
};

window.requeueStudioJob = function (jobId) {
  var hudLog = document.getElementById('studioHudLog');
  window.authFetch('/api/studio/queue/' + encodeURIComponent(jobId) + '/requeue-gpu', { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (hudLog) hudLog.innerHTML += '<br>• 🚀 <strong>' + esc((d && d.message) || 'GPU kuyruğuna yükseltildi') + '</strong>';
      if (window.loadStudioQueue) window.loadStudioQueue();
    }).catch(function () { });
};

window.cancelQueuedJob = function (jobId) {
  window.authFetch('/api/studio/queue/' + encodeURIComponent(jobId) + '/cancel', { method: 'POST' })
    .then(function () { if (window.loadStudioQueue) window.loadStudioQueue(); })
    .catch(function () { });
};

window.analyzeStudioVideo = function (jobId) {
  var hudLog = document.getElementById('studioHudLog');
  if (hudLog) hudLog.innerHTML += '<br>• 🔍 <strong>rea-video</strong> sahne analizi çalışıyor (<code>' + esc(jobId) + '</code>)...';
  window.authFetch('/api/studio/analyze-video', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId })
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (!hudLog) return;
    if (!d || !d.success) {
      hudLog.innerHTML += '<br>⚠️ Analiz: ' + esc((d && d.detail) || (d && d.error) || 'Bulunamadı');
      return;
    }
    var tel = d.telemetry || {};
    hudLog.innerHTML += '<br>• 📊 <strong>rea-video Şeması:</strong> ' + esc(d.estimated_scenes || 1) + ' sahne | ' +
      esc((tel.genislik || '?') + 'x' + (tel.yukseklik || '?')) + ' · ' + esc(tel.sure_sn || '?') + 'sn · ' +
      'Öneri: <code>' + esc(d.recommended_workflow || 'wan_i2v') + '</code> | Kesimler: <code>' + esc((d.scene_cuts_sec || []).join(', ')) + 's</code>';
  }).catch(function () { });
};

window.handleInstantCloudPreview = function (customPrompt) {
  var promptVal = (typeof customPrompt === 'string' && customPrompt.trim()) ? customPrompt.trim() : (((document.getElementById('videoPromptInput') || {}).value || '').trim());
  if (!promptVal) {
    alert('Hızlı önizleme için sahne konusu/promptu gereklidir.');
    return;
  }
  var channel = (document.getElementById('videoChannelSelect') || {}).value || 'Astroloji_Kova';
  var stylePreset = (document.getElementById('videoStyleSelect') || {}).value || 'cinematic_realism';
  var cameraMotion = (document.getElementById('videoCameraSelect') || {}).value || 'otomatik';
  var aspect = (document.getElementById('videoAspectSelect') || {}).value || '16:9';
  var i2vModel = (document.getElementById('videoI2vModelSelect') || {}).value || 'wan2.1-i2v-14b';
  var hudLog = document.getElementById('studioHudLog');
  var taskBadge = document.getElementById('studioTaskBadge');
  var stageArea = document.getElementById('studioStageArea');

  if (taskBadge) taskBadge.textContent = '⚡ Bulut Görseli Üretiliyor...';
  if (hudLog) hudLog.innerHTML = '[HIZLI BULUT ÖNİZLEME]<br>• Konu: "' + esc(promptVal) + '"<br>• Sahne İngilizce görsel dile çevriliyor ve anahtar kare üretiliyor…';

  window.authFetch('/api/studio/preview-image', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      channel: channel,
      prompt: promptVal,
      style_preset: stylePreset,
      camera_motion: cameraMotion,
      aspect_ratio: aspect
    })
  }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
    .then(function (res) {
      if (!res.ok || !res.d || !res.d.success) {
        if (taskBadge) taskBadge.textContent = '❌ Önizleme Üretilemedi';
        if (hudLog) hudLog.innerHTML += '<br><span style="color:var(--site-danger);">❌ ' + esc((res.d && res.d.detail) || 'Bulut görsel hatası') + '</span>';
        return;
      }
      var d = res.d;
      var curTok = window.token ? window.token() : '';
      var pUrl = d.preview_image_url + '&token=' + encodeURIComponent(curTok);
      if (taskBadge) taskBadge.textContent = '🖼️ Görsel Hazır (Onay Bekliyor)';
      if (hudLog) {
        hudLog.innerHTML += '<br>• ✅ Kaynak: <strong>' + esc(d.provider || 'cloud') + '</strong> (' + esc(d.planner_source || 'yerel') + ')<br>' +
          '• 🎨 <strong>İngilizce Görsel Sahne:</strong> <code>' + esc(d.image_prompt || '') + '</code><br>' +
          '• 🎥 <strong>Önerilen Hareket:</strong> <code>' + esc(d.motion_prompt || '') + '</code>';
      }
      if (stageArea) {
        stageArea.innerHTML =
          '<div style="padding:12px; width:100%; text-align:center;">' +
          '<img src="' + esc(pUrl) + '" alt="Bulut önizleme" style="max-width:100%; max-height:340px; border-radius:10px; display:block; margin:0 auto; border:1px solid #334155;">' +
          '<div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:center; margin-top:10px;">' +
          '<button type="button" id="cloudApproveI2vBtn" class="site-btn site-btn-primary">✅ Görseli Beğendim → ' + esc(i2vModel) + ' ile Videoya Çevir</button>' +
          '<button type="button" class="site-btn site-btn-ghost" onclick="handleInstantCloudPreview()">🔄 Yeniden Üret</button>' +
          '</div>' +
          '</div>';
        var btn = document.getElementById('cloudApproveI2vBtn');
        if (btn) btn.onclick = function () { window.handleStudioVideoSubmit(null, 'wan_i2v', d.preview_image_url); };
      }
    }).catch(function (e) {
      if (taskBadge) taskBadge.textContent = '❌ Hata';
      if (hudLog) hudLog.innerHTML += '<br>❌ ' + esc(e.message);
    });
};

window.handlePlanStoryboard = function () {
  var promptVal = ((document.getElementById('videoPromptInput') || {}).value || '').trim();
  var box = document.getElementById('studioStoryboardBox');
  if (!promptVal || !box) {
    alert('Storyboard için sahne konusu/prompt gerekli.');
    return;
  }
  var stylePreset = (document.getElementById('videoStyleSelect') || {}).value || 'cinematic_realism';
  var cameraMotion = (document.getElementById('videoCameraSelect') || {}).value || 'otomatik';
  var duration = Number((document.getElementById('videoDurationSelect') || {}).value || 15);
  box.hidden = false;
  box.innerHTML = '<span style="font-size:0.8rem;color:var(--site-accent);">⏳ 3 sahneli görsel senaryo planlanıyor…</span>';

  window.authFetch('/api/studio/storyboard', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: promptVal, style_preset: stylePreset, camera_motion: cameraMotion, scene_count: 3, duration: duration })
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (!d || !d.success || !Array.isArray(d.scenes)) {
      box.innerHTML = '<span style="color:var(--site-danger);">' + esc((d && d.detail) || 'Storyboard oluşturulamadı.') + '</span>';
      return;
    }
    var html = '<div style="font-size:0.78rem; margin-bottom:8px;"><strong>🎙️ Türkçe Anlatım (' + esc(d.planner_source || 'yerel') + '):</strong> <em>' + esc(d.narration_text || '') + '</em></div>';
    html += d.scenes.map(function (s, i) {
      return '<div style="border-top:1px solid #1e293b; padding-top:6px; margin-top:6px; font-size:0.74rem;">' +
        '<div><strong>Sahne ' + (i + 1) + ':</strong> <code>' + esc(s.image_prompt) + '</code></div>' +
        '<div style="display:flex; gap:6px; margin-top:4px;">' +
        '<button type="button" class="site-chip-btn" data-sb-idx="' + i + '" data-sb-act="cloud">⚡ Hızlı Önizle</button>' +
        '<button type="button" class="site-chip-btn" data-sb-idx="' + i + '" data-sb-act="gpu">🖼️ GPU\'da Üret</button>' +
        '</div>' +
        '</div>';
    }).join('');
    box.innerHTML = html;
    box.querySelectorAll('[data-sb-idx]').forEach(function (b) {
      b.addEventListener('click', function () {
        var idx = Number(b.getAttribute('data-sb-idx') || 0);
        var sc = d.scenes[idx];
        if (!sc) return;
        if (b.getAttribute('data-sb-act') === 'cloud') {
          window.handleInstantCloudPreview(sc.image_prompt);
        } else {
          var pEl = document.getElementById('videoPromptInput');
          if (pEl) pEl.value = sc.image_prompt;
          window.handleStudioVideoSubmit(null, 'image_first_preview');
        }
      });
    });
  }).catch(function (e) { box.innerHTML = '<span style="color:var(--site-danger);">' + esc(e.message) + '</span>'; });
};

window.handleStartYoutubeOAuth = function () {
  var cid = (document.getElementById('chEditIdInput') || {}).value || '';
  window.authFetch('/api/youtube/oauth/start?channel_id=' + encodeURIComponent(cid), {})
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
    .then(function (res) {
      if (res.ok && res.d && res.d.auth_url) {
        window.open(res.d.auth_url, '_blank', 'noopener');
      } else {
        alert((res.d && res.d.detail) || 'Önce Google Cloud client_secret.json anahtarını kaydedin.\nRedirect URI: ' + ((res.d && res.d.redirect_uri) || ''));
      }
    }).catch(function (e) { alert('OAuth başlatılamadı: ' + e.message); });
};

function _bindStudioUiExtras() {
  var wfSel = document.getElementById('videoMethodSelect');
  var urlWrap = document.getElementById('videoSourceUrlWrap');
  if (wfSel && urlWrap && !wfSel.getAttribute('data-url-bound')) {
    var syncUrlVis = function () {
      var v = wfSel.value || '';
      urlWrap.hidden = !(v === 'product_launch' || v === 'hyperframes_motion');
    };
    wfSel.addEventListener('change', syncUrlVis);
    wfSel.setAttribute('data-url-bound', '1');
    syncUrlVis();
  }
  window.loadChannelsCatalog(false);
  window.refreshStudioWorkerWarn();
  window.loadStudioQueue();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function () {
    setTimeout(_bindStudioUiExtras, 250);
  });
} else {
  setTimeout(_bindStudioUiExtras, 250);
}
