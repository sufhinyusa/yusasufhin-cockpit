/* home_demo.js — Fare Hareketine Duyarlı Sinirsel Alan, 3B Kart Eğimi,
 * Manyetik Butonlar, Canlı Temsili Fabrika Masaüstü Arayüz Animasyonu ve Özellik Filtresi.
 *
 * Performans & Erişilebilirlik:
 * - requestAnimationFrame sekme gizlenince / ekran dışına çıkınca otomatik durur.
 * - prefers-reduced-motion: reduce moduna tam saygı gösterir.
 * - Dokunmatik ekranlarda (pointer: coarse) sade, akıcı otomatik hareket sunar.
 * - Harici CDN kütüphanesi kullanmaz (%100 CSP uyumlu).
 */
(function () {
  'use strict';

  var reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var coarsePointer = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;

  var mouse = { x: window.innerWidth * 0.5, y: window.innerHeight * 0.35, active: false, vx: 0, vy: 0 };
  var auraPos = { x: mouse.x, y: mouse.y };
  var ripples = [];

  /* ── 1. FARE TAKİPLİ IŞIK AURA & SİNİRSEL PARÇACIK ALANI ───────────── */
  function initReactiveField() {
    var canvas = document.getElementById('homeReactiveCanvas');
    var aura = document.getElementById('homeCursorAura');
    if (!canvas || !canvas.getContext) return;
    var ctx = canvas.getContext('2d');
    var w = 0;
    var h = 0;
    var nodes = [];
    var rafId = null;

    function resize() {
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = Math.max(10, Math.floor(w * dpr));
      canvas.height = Math.max(10, Math.floor(h * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      var targetCount = w < 720 ? 34 : 68;
      if (nodes.length !== targetCount) {
        nodes = [];
        for (var i = 0; i < targetCount; i++) {
          nodes.push({
            x: Math.random() * w,
            y: Math.random() * h,
            vx: (Math.random() - 0.5) * 0.55,
            vy: (Math.random() - 0.5) * 0.55,
            r: 1.1 + Math.random() * 1.9,
            hue: i % 3 === 0 ? '45,212,191' : (i % 3 === 1 ? '139,92,246' : '56,189,248')
          });
        }
      }
    }
    resize();
    window.addEventListener('resize', resize);

    if (!coarsePointer) {
      window.addEventListener('pointermove', function (ev) {
        mouse.vx = ev.clientX - mouse.x;
        mouse.vy = ev.clientY - mouse.y;
        mouse.x = ev.clientX;
        mouse.y = ev.clientY;
        mouse.active = true;
      }, { passive: true });

      window.addEventListener('pointerdown', function (ev) {
        if (reducedMotion) return;
        ripples.push({ x: ev.clientX, y: ev.clientY, r: 8, alpha: 0.55 });
        if (ripples.length > 6) ripples.shift();
      }, { passive: true });

      window.addEventListener('pointerleave', function () { mouse.active = false; });
    }

    function step() {
      if (document.hidden) {
        rafId = null;
        return;
      }
      ctx.clearRect(0, 0, w, h);

      var isLight = document.documentElement.getAttribute('data-site-theme') === 'saas';
      var lineBoost = isLight ? 0.22 : 0.34;

      if (aura && !coarsePointer && !reducedMotion) {
        auraPos.x += (mouse.x - auraPos.x) * 0.14;
        auraPos.y += (mouse.y - auraPos.y) * 0.14;
        aura.style.transform = 'translate3d(' + (auraPos.x - 240) + 'px,' + (auraPos.y - 240) + 'px,0)';
        aura.style.opacity = mouse.active ? '1' : '0.45';
      }

      // Dalga halkaları (tıklama etkileşimi)
      for (var k = ripples.length - 1; k >= 0; k--) {
        var rp = ripples[k];
        rp.r += 4.2;
        rp.alpha *= 0.94;
        if (rp.alpha < 0.02) { ripples.splice(k, 1); continue; }
        ctx.beginPath();
        ctx.arc(rp.x, rp.y, rp.r, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(45, 212, 191, ' + rp.alpha.toFixed(3) + ')';
        ctx.lineWidth = 1.4;
        ctx.stroke();
      }

      // Parçacık fiziği + fare çekimi / bükülme
      for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        if (!reducedMotion) {
          if (mouse.active && !coarsePointer) {
            var mdx = mouse.x - n.x;
            var mdy = mouse.y - n.y;
            var mdist = Math.sqrt(mdx * mdx + mdy * mdy) || 1;
            if (mdist < 210) {
              var force = (1 - mdist / 210) * 0.042;
              n.vx += (mdx / mdist) * force + (mouse.vx * 0.0012);
              n.vy += (mdy / mdist) * force + (mouse.vy * 0.0012);
            }
          }
          n.vx *= 0.985;
          n.vy *= 0.985;
          if (Math.abs(n.vx) < 0.14) n.vx += (Math.random() - 0.5) * 0.06;
          if (Math.abs(n.vy) < 0.14) n.vy += (Math.random() - 0.5) * 0.06;
          n.x += n.vx;
          n.y += n.vy;
          if (n.x < 0) { n.x = 0; n.vx *= -1; }
          if (n.x > w) { n.x = w; n.vx *= -1; }
          if (n.y < 0) { n.y = 0; n.vy *= -1; }
          if (n.y > h) { n.y = h; n.vy *= -1; }
        }

        // Fareye bağlı parlak sinaps iplikleri
        if (mouse.active && !coarsePointer) {
          var cdx = mouse.x - n.x;
          var cdy = mouse.y - n.y;
          var cdist = Math.sqrt(cdx * cdx + cdy * cdy);
          if (cdist < 185) {
            ctx.beginPath();
            ctx.moveTo(n.x, n.y);
            ctx.lineTo(mouse.x, mouse.y);
            ctx.strokeStyle = 'rgba(' + n.hue + ',' + ((1 - cdist / 185) * 0.45).toFixed(3) + ')';
            ctx.lineWidth = 1.05;
            ctx.stroke();
          }
        }

        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(' + n.hue + ',' + (isLight ? 0.52 : 0.65) + ')';
        ctx.fill();

        for (var j = i + 1; j < nodes.length; j++) {
          var m = nodes[j];
          var dx = n.x - m.x;
          var dy = n.y - m.y;
          var dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 130) {
            ctx.beginPath();
            ctx.moveTo(n.x, n.y);
            ctx.lineTo(m.x, m.y);
            ctx.strokeStyle = 'rgba(' + n.hue + ',' + ((1 - dist / 130) * lineBoost).toFixed(3) + ')';
            ctx.lineWidth = 0.75;
            ctx.stroke();
          }
        }
      }

      mouse.vx *= 0.8;
      mouse.vy *= 0.8;
      rafId = requestAnimationFrame(step);
    }

    document.addEventListener('visibilitychange', function () {
      if (!document.hidden && !rafId) rafId = requestAnimationFrame(step);
    });
    rafId = requestAnimationFrame(step);
  }

  /* ── 2. 3B PERSPEKTİF EĞİM KARTLARI & MANYETİK BUTONLAR ────────────── */
  function initTiltAndMagnetic() {
    if (reducedMotion || coarsePointer) return;

    document.querySelectorAll('.tilt-card').forEach(function (card) {
      card.addEventListener('pointermove', function (ev) {
        var r = card.getBoundingClientRect();
        var px = (ev.clientX - r.left) / r.width;
        var py = (ev.clientY - r.top) / r.height;
        var rx = (0.5 - py) * 9;
        var ry = (px - 0.5) * 10;
        card.style.setProperty('--mx', (px * 100).toFixed(1) + '%');
        card.style.setProperty('--my', (py * 100).toFixed(1) + '%');
        card.style.transform = 'perspective(900px) rotateX(' + rx.toFixed(2) + 'deg) rotateY(' + ry.toFixed(2) + 'deg) translateY(-4px)';
      });
      card.addEventListener('pointerleave', function () {
        card.style.transform = '';
      });
    });

    document.querySelectorAll('.magnetic-btn').forEach(function (btn) {
      btn.addEventListener('pointermove', function (ev) {
        var r = btn.getBoundingClientRect();
        var dx = (ev.clientX - (r.left + r.width / 2)) * 0.24;
        var dy = (ev.clientY - (r.top + r.height / 2)) * 0.24;
        btn.style.transform = 'translate3d(' + dx.toFixed(1) + 'px,' + dy.toFixed(1) + 'px,0)';
      });
      btn.addEventListener('pointerleave', function () {
        btn.style.transform = '';
      });
    });
  }

  /* ── 3. KAYDIRMA İLE AÇILMA (REVEAL) ────────────────────────────────── */
  function initScrollReveals() {
    var items = document.querySelectorAll('.reveal-on-scroll');
    if (!items.length) return;
    if (reducedMotion || typeof IntersectionObserver === 'undefined') {
      items.forEach(function (el) { el.classList.add('is-visible'); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.08 });
    items.forEach(function (el) { io.observe(el); });
  }

  /* ── 4. HAREKETLİ FABRİKA MASAÜSTÜ ARAYÜZ VİTRİNİ (4 GERÇEK SENARYO) ── */
  var DEMO_SCENES = [
    {
      key: 'learn',
      badge: '🎥 /takip AKTİF • ÖĞRENME MODU',
      ribbon: '🎥 EKRAN KAYDI İZLENİYOR  •  MacOSAXListener + Ses Zaman Çizgisi  •  Mimar & Pythoner Uygulama Yazıyor',
      command: '/takip fatura_aktarma — Ekran kaydımdan bu işi öğren ve tek tıkla çalışan masaüstü uygulaması yaz',
      agent: '🐍 Pythoner + 📐 Mimar',
      reply: '14 tıklama, 3 tarayıcı sekmesi ve sesli açıklamanız çözümlendi. Bağımsız fatura aktarıcı araç yazıldı, G1–G5 test kapılarından geçti.',
      tab: 'kod',
      logs: [
        '[00:01] CursorHaloOverlay & MacOSAXListener başlatıldı',
        '[00:06] 14 UI olayı + ses transkripti zaman çizgisine işlendi',
        '[00:11] Mimar: tool_demo_fatura_aktarici.py mimarisi onaylandı',
        '[00:16] KYS/MR: AST skoru 96/100 • 8/8 pytest çivisi GEÇTİ',
        '[00:18] ✅ Uygulama Fabrika_Products/ altına teslim edildi'
      ],
      rightTitle: '🧩 ÖĞRENİLEN İŞ AKIŞI → YAZILAN UYGULAMA',
      rightBody: [
        { k: 'Kaynak', v: 'Ekran kaydı + fare tıklamaları + sesli anlatım (/takip)' },
        { k: 'Tespit Edilen Adımlar', v: '1) Portal girişi → 2) PDF fatura indir → 3) Tablo ayrıştır → 4) Muhasebe aktar' },
        { k: 'Üretilen Kod', v: 'Bağımsız Python uygulaması + birim testleri (0 çöp)' },
        { k: 'Teslim Durumu', v: 'G1 Kural · G2 Güvenlik · G3 MR · G4 Pytest · G5 Hijyen GEÇTİ' }
      ],
      code:
        'def fatura_is_akisi_yurut(kaynak_klasor: Path) -> dict:\n' +
        '    """/takip kaydından otomatik öğrenilen akış."""\n' +
        '    faturalar = pdf_tablolari_oku(kaynak_klasor)\n' +
        '    dogrulanan = kdv_ve_toplam_denetle(faturalar)\n' +
        '    return excel_ve_api_aktar(dogrulanan)'
    },
    {
      key: 'media',
      badge: '🎬 VİDEO + 🎵 MÜZİK + 🎙️ TTS',
      ribbon: '🎬 YonetmenAgent • FLUX.2 Anahtar Kare → Wan 2.1 I2V • Google Lyria 3.5 Stereo Müzik • YouTube API v3',
      command: '#Yönetmen İstanbul tarihini anlatan 16:9 video, Google Lyria 3.5 epik fon müziği ve Gemini TTS seslendirme üret',
      agent: '🎬 Yönetmen + 🎵 Müzik Hattı',
      reply: 'Anahtar kare FLUX.2 ile üretildi, Wan 2.1 I2V ile canlandırıldı, Lyria 3.5 stereo beste ve Gemini TTS eklenip YouTube SEO paketi hazırlandı.',
      tab: 'reaktor',
      logs: [
        '[00:02] Prompt Director: Türkçe senaryo 3 sinematik sahneye bölündü',
        '[00:07] FLUX.2 Klein 4B anahtar kare üretildi (onaylandı)',
        '[00:14] Wan 2.1 I2V / Kaggle Dual-T4 GPU render tamamlandı',
        '[00:19] Google Lyria 3.5 44.1kHz stereo fon müziği + Gemini TTS eklendi',
        '[00:22] 📺 YouTube Data API v3 yayın paketi hazır'
      ],
      rightTitle: '🎬 ÇOKLU MEDYA PRODÜKSİYON HATTI',
      rightBody: [
        { k: 'Görsel & Video', v: 'FLUX.2 · Z-Image · Wan 2.1/2.2 I2V · LTX-Video · Hyperframes MP4' },
        { k: 'Müzik Modelleri', v: 'Google Lyria 3.5 · Lyria 3 Clip · ElevenLabs · Stable Audio 2 · MusicGen' },
        { k: 'Seslendirme', v: 'Google Gemini Nöral TTS + SRT/ASS otomatik altyazı' },
        { k: 'Dağıtım', v: 'Çoklu YouTube kanalı + Cloudflare R2 kalıcı medya deposu' }
      ],
      code:
        '{\n' +
        '  "video_model": "wan2.1-i2v-14b",\n' +
        '  "music_model": "lyria-3.5 (44.1kHz stereo)",\n' +
        '  "tts_voice": "Gemini Neural TTS (Charon)",\n' +
        '  "youtube_upload": "HMAC-OAuth2 + Resumable API v3"\n' +
        '}'
    },
    {
      key: 'security',
      badge: '🏥 MR KOD HASTANESİ & G1–G5',
      ribbon: '🛡️ Gatekeeper + REA AST Tarayıcı  •  SHA-256 Bütünlük Mührü (790 Dosya)  •  Piknik Çöp Kilidi',
      command: '#KYS son modülü MR Kod Hastanesinden geçir, güvenlik açığı varsa kapat ve G1–G5 teslim kapısından onayla',
      agent: '🏥 KYS (Kod Hastanesi)',
      reply: 'AST karmaşıklık, SSRF/XSS/CSRF ve dosya izinleri (0600) denetlendi. Tüm 5 kapı GEÇTİ; 790 çekirdek dosya SHA-256 ile mühürlendi.',
      tab: 'xai',
      logs: [
        '[00:01] G1 Kural & SHA-256 Bütünlük Mührü doğrulandı (790 dosya)',
        '[00:03] G2 Gatekeeper: eval/exec/shell=True/gizli sızıntı = 0',
        '[00:05] G3 MR Üç Kademe: AST Sağlık 94/100 • KANGREN = 0',
        '[00:08] G4 Pytest Çivileri: 33/33 geçti (0 pencere, 0 sızıntı)',
        '[00:09] G5 Hijyen: Çöp = 0 → KARAR: TESLİM EDİLDİ'
      ],
      rightTitle: '🛡️ ZORLAMA HATTI — 5 MEKANİK TESLİM KAPISI',
      rightBody: [
        { k: 'G1 Kural & Mühür', v: 'Core/ ve kural belgeleri SHA-256 mühürlü; yetkisiz oynama anında onarılır' },
        { k: 'G2 Güvenlik', v: 'Gatekeeper + REA gerçek Python ast.parse taraması' },
        { k: 'G3 MR Kalite', v: 'Üç kademeli karmaşıklık ve sahte-kod engelleme kapısı' },
        { k: 'G4–G5 Test & Hijyen', v: 'Pytest çivileri + Piknik Prensibi (sıfır geçici dosya artığı)' }
      ],
      code:
        'KARAR: TESLIM EDILDI\n' +
        '[GECTI] G1-kural     → SHA-256 mührü güncel\n' +
        '[GECTI] G2-guvenlik  → 0 kritik bulgu\n' +
        '[GECTI] G3-mr        → AST Sağlık 94/100\n' +
        '[GECTI] G4-test      → Tüm pytest çivileri yeşil\n' +
        '[GECTI] G5-hijyen    → 0 geçici çöp'
    },
    {
      key: 'remote',
      badge: '🌐 PORT-443 İKİZ + MECLİS',
      ribbon: '🌐 Mac Masaüstü 1:1 Web İkizi  •  CEO/Mimar/KYS/İK/Sekreter Münazara Meclisi  •  Telegram & Kariyer Avcısı',
      command: '#CEO uzaktan Mac sistemini, Telegram link havuzunu ve Kariyer Avcısı ATS başvurularını özetle',
      agent: '👑 CEO + 📋 Sekreter',
      reply: 'Port-443 köprüsü canlı; 230+ araç hazır. Telegram LinkStore yeni GitHub reposunu analiz etti, Kariyer Avcısı 6 yüksek eşleşmeli ilan çıkardı.',
      tab: 'log',
      logs: [
        '[00:01] VPNPort443Bridge → HTTPS 443 çift yönlü eşzamanlama aktif',
        '[00:03] MasaustuKopruIPC → Web arayüzü Mac penceresiyle 1:1 senkron',
        '[00:05] Münazara Meclisi: CEO · Mimar · KYS · İK · Sekreter hazır',
        '[00:07] RepoIntegrator: Telegram link havuzu yeni aracı doğruladı',
        '[00:09] Jarvis Ses Protokolü + Barge-in + Derin Uyku içselleştirme aktif'
      ],
      rightTitle: '🌐 UZAKTAN KOMUTA & OTONOM EKOSİSTEM',
      rightBody: [
        { k: '1:1 Uzak İkiz', v: 'Telefon/tarayıcıdan Mac Fabrika arayüzünü gerçek zamanlı kontrol (Port 443)' },
        { k: 'Yönetim Meclisi', v: 'CEO, Mimar, KYS, İK, Sekreter + Yazılım, Tasarım, Ar-Ge departmanları' },
        { k: 'Telegram & Repo', v: 'Link havuzundan GitHub projelerini inceleyip güvenli araca dönüştürür' },
        { k: 'Kariyer & Hafıza', v: 'Otonom ATS Kariyer Avcısı, Qdrant semantik hafıza ve derin uyku öğrenmesi' }
      ],
      code:
        'bridge.status   = "ONLINE (HTTPS Port 443)"\n' +
        'desktop_mirror  = "1:1 SYNC (Reaktör + Log + XAI + Sağ Panel)"\n' +
        'voice_protocol  = "Jarvis STT/TTS + Biyometrik Tanıma + Barge-in"\n' +
        'local_accel     = "Apple Silicon MLX/Ollama + Rust fabrika_dsp"'
    }
  ];

  function initFabrikaShowcase() {
    var root = document.getElementById('fabrikaShowcase');
    var canvas = document.getElementById('demoReactorCanvas');
    if (!root || !canvas || !canvas.getContext) return;

    var ctx = canvas.getContext('2d');
    var nodes = [];
    for (var i = 0; i < 240; i++) {
      nodes.push({
        shell: 0.16 + Math.random() * 0.82,
        phi: Math.random() * Math.PI * 2,
        theta: Math.acos(-1 + Math.random() * 2),
        size: i < 48 ? (1.1 + Math.random() * 0.8) : (0.45 + Math.random() * 0.65),
        isCore: i < 48
      });
    }

    var rotY = 0;
    var rotX = 0.25;
    var targetTiltX = 0;
    var targetTiltY = 0;
    var pulse = 0.25;
    var visible = true;
    var rafId = null;

    function resizeReactor() {
      var rect = canvas.parentElement.getBoundingClientRect();
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(10, Math.floor(rect.width * dpr));
      canvas.height = Math.max(10, Math.floor(rect.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resizeReactor();
    window.addEventListener('resize', resizeReactor);

    if (!coarsePointer) {
      root.addEventListener('pointermove', function (ev) {
        var r = root.getBoundingClientRect();
        var nx = ((ev.clientX - r.left) / r.width - 0.5) * 2;
        var ny = ((ev.clientY - r.top) / r.height - 0.5) * 2;
        targetTiltY = nx * 0.65;
        targetTiltX = ny * 0.45;
        pulse = Math.min(1.0, pulse + 0.08);
      }, { passive: true });
    }

    if (typeof IntersectionObserver !== 'undefined') {
      new IntersectionObserver(function (entries) {
        visible = entries[0] && entries[0].isIntersecting;
        if (visible && !rafId) rafId = requestAnimationFrame(renderReactor);
      }, { threshold: 0.05 }).observe(root);
    }

    function renderReactor() {
      if (document.hidden || !visible) {
        rafId = null;
        return;
      }
      var w = canvas.clientWidth || 440;
      var h = canvas.clientHeight || 195;
      ctx.clearRect(0, 0, w, h);

      if (!reducedMotion) {
        rotY += 0.008 + pulse * 0.014;
        rotX += (0.22 + targetTiltX - rotX) * 0.06;
        pulse = Math.max(0.18, pulse * 0.96);
      }

      var cy = h * 0.5;
      var cx = w * 0.5;
      var radius = Math.min(w, h) * (0.37 + pulse * 0.08);
      var cosY = Math.cos(rotY + targetTiltY);
      var sinY = Math.sin(rotY + targetTiltY);
      var cosX = Math.cos(rotX);
      var sinX = Math.sin(rotX);

      // Merkez çekirdek parıltısı
      var g = ctx.createRadialGradient(cx, cy, 2, cx, cy, radius * 1.15);
      g.addColorStop(0, 'rgba(0, 255, 204, 0.34)');
      g.addColorStop(0.45, 'rgba(56, 189, 248, 0.14)');
      g.addColorStop(1, 'rgba(0, 0, 0, 0)');
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(cx, cy, radius * 1.15, 0, Math.PI * 2);
      ctx.fill();

      for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        var r = radius * n.shell;
        var sx = r * Math.sin(n.theta) * Math.cos(n.phi);
        var sy = r * Math.sin(n.theta) * Math.sin(n.phi);
        var sz = r * Math.cos(n.theta);

        var x1 = sx * cosY - sz * sinY;
        var z1 = sx * sinY + sz * cosY;
        var y2 = sy * cosX - z1 * sinX;
        var z2 = sy * sinX + z1 * cosX;

        var scale = 240 / (240 + z2);
        var px = cx + x1 * scale;
        var py = cy + y2 * scale;
        var alpha = Math.max(0.16, Math.min(0.95, (z2 + radius) / (2 * radius)));

        ctx.beginPath();
        ctx.arc(px, py, Math.max(0.5, n.size * scale), 0, Math.PI * 2);
        ctx.fillStyle = n.isCore
          ? ('rgba(0, 255, 204,' + alpha.toFixed(2) + ')')
          : ('rgba(125, 211, 252,' + (alpha * 0.82).toFixed(2) + ')');
        ctx.fill();
      }
      rafId = requestAnimationFrame(renderReactor);
    }
    rafId = requestAnimationFrame(renderReactor);

    /* ── Senaryo Oynatıcı ─────────────────────────────────────────────── */
    var currentIdx = 0;
    var typeTimer = null;
    var autoTimer = null;
    var badgeEl = document.getElementById('demoOrbBadge');
    var ribbonEl = document.getElementById('demoRibbonText');
    var cmdEl = document.getElementById('demoTypedCmd');
    var agentEl = document.getElementById('demoAgentName');
    var replyEl = document.getElementById('demoAgentReply');
    var logBox = document.getElementById('demoLogLines');
    var rTitle = document.getElementById('demoRightTitle');
    var rFacts = document.getElementById('demoRightFacts');
    var rCode = document.getElementById('demoRightCode');
    var sceneBtns = document.querySelectorAll('[data-demo-scene]');

    function playScene(idx) {
      currentIdx = ((idx % DEMO_SCENES.length) + DEMO_SCENES.length) % DEMO_SCENES.length;
      var sc = DEMO_SCENES[currentIdx];
      pulse = 0.85;

      sceneBtns.forEach(function (b, bIdx) {
        var active = bIdx === currentIdx;
        b.classList.toggle('active', active);
        b.setAttribute('aria-pressed', active ? 'true' : 'false');
      });

      if (badgeEl) badgeEl.textContent = sc.badge;
      if (ribbonEl) ribbonEl.textContent = sc.ribbon;
      if (agentEl) agentEl.textContent = sc.agent + ':';
      if (replyEl) replyEl.textContent = sc.reply;
      if (rTitle) rTitle.textContent = sc.rightTitle;
      if (rCode) rCode.textContent = sc.code;

      if (rFacts) {
        rFacts.textContent = '';
        sc.rightBody.forEach(function (item) {
          var row = document.createElement('div');
          row.className = 'demo-fact-row';
          var k = document.createElement('span');
          k.className = 'demo-fact-key';
          k.textContent = item.k;
          var v = document.createElement('strong');
          v.className = 'demo-fact-val';
          v.textContent = item.v;
          row.appendChild(k);
          row.appendChild(v);
          rFacts.appendChild(row);
        });
      }

      if (logBox) {
        logBox.textContent = '';
        sc.logs.forEach(function (line) {
          var div = document.createElement('div');
          div.className = 'demo-log-line';
          div.textContent = line;
          logBox.appendChild(div);
        });
      }

      if (typeTimer) clearInterval(typeTimer);
      if (cmdEl) {
        if (reducedMotion) {
          cmdEl.textContent = sc.command;
        } else {
          cmdEl.textContent = '';
          var pos = 0;
          typeTimer = setInterval(function () {
            pos += 3;
            cmdEl.textContent = sc.command.slice(0, pos);
            if (pos >= sc.command.length) {
              clearInterval(typeTimer);
              typeTimer = null;
            }
          }, 26);
        }
      }
    }

    sceneBtns.forEach(function (btn, idx) {
      btn.addEventListener('click', function () {
        playScene(idx);
        if (autoTimer) { clearInterval(autoTimer); autoTimer = startAutoCycle(); }
      });
    });

    function startAutoCycle() {
      if (reducedMotion) return null;
      return setInterval(function () {
        if (!document.hidden && visible) playScene(currentIdx + 1);
      }, 7500);
    }

    playScene(0);
    autoTimer = startAutoCycle();
  }

  /* ── 5. ÖZELLİK KATALOĞU KATEGORİ FİLTRESİ ─────────────────────────── */
  function initFeatureFilters() {
    var btns = document.querySelectorAll('[data-feat-filter]');
    var cards = document.querySelectorAll('[data-feat-cat]');
    if (!btns.length || !cards.length) return;
    btns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var cat = btn.getAttribute('data-feat-filter') || 'all';
        btns.forEach(function (b) {
          var on = b === btn;
          b.classList.toggle('active', on);
          b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        cards.forEach(function (card) {
          var c = card.getAttribute('data-feat-cat') || '';
          card.hidden = !(cat === 'all' || c === cat);
        });
      });
    });
  }

  function boot() {
    initReactiveField();
    initTiltAndMagnetic();
    initScrollReveals();
    initFabrikaShowcase();
    initFeatureFilters();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
