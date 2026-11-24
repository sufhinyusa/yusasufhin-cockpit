/* ============================================================================
 * fabrika_desktop.js — Masaüstü Fabrika (AnaYuz) Uzaktan İkiz Motoru
 * ----------------------------------------------------------------------------
 * Core/ui/reaktor/reaktor_gorsel.py (450 düğümlü 3D Galaksi Reaktör),
 * Core/ui/ust_panel (Log / XAI / Kod / EQ / KaliciHataSeridi),
 * Core/ui/sag_panel (Kaymalı Sağ Çekmece + Kadro/Rapor/Havuz/REA/Kod/Ayarlar),
 * Core/ui/alt_panel (Menlo sohbet, Web Speech STT + SpeechSynthesis TTS).
 * ============================================================================ */

(function () {
  'use strict';

  // Core/ui/theme.py AgentTheme renkleri
  const AGENT_COLORS = {
    CEO: '#00FFCC',
    Mimar: '#FF6B6B',
    IK: '#4ECDC4',
    KYS: '#FFE66D',
    Sekreter: '#8E24AA',
    Sistem: '#38bdf8',
    'Mac Fabrika': '#00FFCC',
    'Mac Fabrika Köprüsü': '#00FFCC',
    'Mac Köprüsü': '#38bdf8'
  };

  function resolveAgentColor(sender) {
    const s = String(sender || '');
    for (const key of Object.keys(AGENT_COLORS)) {
      if (s.toLowerCase().includes(key.toLowerCase())) return AGENT_COLORS[key];
    }
    if (s.includes('Kalite') || s.includes('REA')) return '#FFE66D';
    if (s.includes('Araştırma') || s.includes('Link')) return '#60A5FA';
    if (s.includes('Python')) return '#34D399';
    if (s.includes('Xcoder') || s.includes('Apple')) return '#A78BFA';
    return '#00FFCC';
  }

  // --------------------------------------------------------------------------
  // 1. 3D HOLOGRAFİK GALAKSİ REAKTÖR (ReaktorGorsel.py 1:1 JS Portu — 450 düğüm)
  // --------------------------------------------------------------------------
  const reactorState = {
    currentVolume: 0,
    targetVolume: 0,
    currentFft: 0,
    targetFft: 0,
    rotY: 0,
    rotX: 0,
    speaking: false,
    nodes: []
  };

  function initGalaxyReactor() {
    const canvas = document.getElementById('reaktorCanvas');
    if (!canvas || !canvas.getContext) return;
    const ctx = canvas.getContext('2d');

    const numNodes = 450;
    reactorState.nodes = [];
    for (let i = 0; i < numNodes; i++) {
      const isStructure = i < numNodes * 0.2;
      reactorState.nodes.push({
        shell: 0.1 + Math.random() * 0.85,
        phi: Math.random() * Math.PI * 2,
        theta: Math.acos(-1 + Math.random() * 2),
        size: isStructure ? (0.7 + Math.random() * 0.8) : (0.25 + Math.random() * 0.55),
        isStructure,
        vPhi: (Math.random() - 0.5) * 0.024,
        vTheta: (Math.random() - 0.5) * 0.024,
        vShell: (Math.random() - 0.5) * 0.014
      });
    }

    function resize() {
      const rect = canvas.parentElement.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(10, Math.floor(rect.width * dpr));
      canvas.height = Math.max(10, Math.floor(rect.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();
    window.addEventListener('resize', resize);
    if (typeof ResizeObserver !== 'undefined') {
      new ResizeObserver(resize).observe(canvas.parentElement);
    }

    function frame() {
      if (reactorState.speaking) {
        reactorState.targetVolume = 0.42 + Math.random() * 0.45;
        reactorState.targetFft = 0.35 + Math.random() * 0.5;
      }

      if (reactorState.targetVolume > reactorState.currentVolume) {
        reactorState.currentVolume += (reactorState.targetVolume - reactorState.currentVolume) * 0.55;
      } else {
        reactorState.currentVolume = Math.max(0, reactorState.currentVolume - 0.035);
      }

      if (reactorState.targetFft > reactorState.currentFft) {
        reactorState.currentFft += (reactorState.targetFft - reactorState.currentFft) * 0.65;
      } else {
        reactorState.currentFft = Math.max(0, reactorState.currentFft - 0.045);
      }

      const w = canvas.clientWidth || 560;
      const h = canvas.clientHeight || 220;
      ctx.clearRect(0, 0, w, h);

      const speed = 0.005 + reactorState.currentVolume * 0.022;
      reactorState.rotY += speed;
      reactorState.rotX += speed * 0.5;

      const reactVal = reactorState.currentVolume * 0.6 + reactorState.currentFft * 0.4;
      const baseR = Math.min(w, h) * 0.33;
      const globalRadius = Math.max(48, baseR + reactVal * (baseR * 0.85));

      const cosY = Math.cos(reactorState.rotY);
      const sinY = Math.sin(reactorState.rotY);
      const cosX = Math.cos(reactorState.rotX);
      const sinX = Math.sin(reactorState.rotX);
      const cx = w / 2;
      const cy = h / 2;
      const focal = 800.0;

      const projected = [];
      const structure = [];

      for (let i = 0; i < reactorState.nodes.length; i++) {
        const n = reactorState.nodes[i];
        n.phi += n.vPhi + speed * 0.3;
        n.theta += n.vTheta;
        n.shell += n.vShell;

        if (Math.random() < 0.015) {
          n.vPhi = (Math.random() - 0.5) * 0.024;
          n.vTheta = (Math.random() - 0.5) * 0.024;
          n.vShell = (Math.random() - 0.5) * 0.014;
        }
        if (n.shell >= 0.98) { n.shell = 0.98; n.vShell *= -1; }
        else if (n.shell <= 0.05) { n.shell = 0.05; n.vShell *= -1; }
        if (n.theta <= 0.1) { n.theta = 0.1; n.vTheta *= -1; }
        else if (n.theta >= Math.PI - 0.1) { n.theta = Math.PI - 0.1; n.vTheta *= -1; }

        const r = globalRadius * n.shell;
        const sinT = Math.sin(n.theta);
        const x0 = r * sinT * Math.cos(n.phi);
        const y0 = r * sinT * Math.sin(n.phi);
        const z0 = r * Math.cos(n.theta);

        const y1 = y0 * cosX - z0 * sinX;
        const z1 = y0 * sinX + z0 * cosX;
        const x2 = x0 * cosY + z1 * sinY;
        const z2 = -x0 * sinY + z1 * cosY;

        const scale = focal + z2 > 0 ? focal / (focal + z2) : 0.01;
        const p = {
          px: cx + x2 * scale,
          py: cy + y1 * scale,
          z: z2,
          scale,
          size: n.size,
          isStructure: n.isStructure,
          shell: n.shell
        };
        projected.push(p);
        if (n.isStructure) structure.push(p);
      }

      // İskelet bağlantıları (#0096ff iç, #00ffcc dış)
      const connDist = 28 + reactVal * 26;
      const connDistSq = connDist * connDist;
      ctx.lineWidth = 0.4 + reactVal * 0.55;

      for (let i = 0; i < structure.length; i++) {
        const n1 = structure[i];
        if (n1.z > 50) continue;
        let made = 0;
        for (let j = i + 1; j < structure.length; j++) {
          const n2 = structure[j];
          const dx = n1.px - n2.px;
          if (Math.abs(dx) > connDist) continue;
          const dy = n1.py - n2.py;
          if (Math.abs(dy) > connDist) continue;
          const d2 = dx * dx + dy * dy;
          if (d2 < connDistSq) {
            made++;
            const dist = Math.sqrt(d2);
            const alpha = Math.min(1, (1 - dist / connDist) * (0.32 + reactVal * 1.3));
            if (alpha > 0.04) {
              ctx.strokeStyle = n1.shell < 0.6
                ? `rgba(0, 150, 255, ${alpha.toFixed(2)})`
                : `rgba(0, 255, 204, ${alpha.toFixed(2)})`;
              ctx.beginPath();
              ctx.moveTo(n1.px, n1.py);
              ctx.lineTo(n2.px, n2.py);
              ctx.stroke();
            }
            if (made >= 3) break;
          }
        }
      }

      // Yıldız tozu ve düğümler
      projected.sort((a, b) => b.z - a.z);
      for (let i = 0; i < projected.length; i++) {
        const n = projected[i];
        const depthA = Math.max(0.05, Math.min(1, (500 - n.z) / 1000));
        const a = Math.min(1, depthA * (0.55 + reactVal * 0.7));
        if (n.isStructure) ctx.fillStyle = `rgba(0, 255, 204, ${a.toFixed(2)})`;
        else if (n.shell < 0.4) ctx.fillStyle = `rgba(0, 150, 255, ${a.toFixed(2)})`;
        else ctx.fillStyle = `rgba(210, 245, 255, ${(a * 0.75).toFixed(2)})`;
        const rad = Math.max(0.55, n.size * n.scale * (1.1 + reactVal * 0.55));
        ctx.beginPath();
        ctx.arc(n.px, n.py, rad, 0, Math.PI * 2);
        ctx.fill();
      }

      requestAnimationFrame(frame);
    }

    requestAnimationFrame(frame);
  }

  function pulseReactor(intensity = 0.75, durationMs = 700) {
    reactorState.targetVolume = Math.max(reactorState.targetVolume, intensity);
    reactorState.targetFft = Math.max(reactorState.targetFft, intensity * 0.9);
    setTimeout(() => {
      if (!reactorState.speaking) {
        reactorState.targetVolume = 0;
        reactorState.targetFft = 0;
      }
    }, durationMs);
  }

  // --------------------------------------------------------------------------
  // 2. EQ SPEKTRUM GÖRÜNTÜLEYİCİ (Müzik Modu)
  // --------------------------------------------------------------------------
  function initEqVisualizer() {
    const canvas = document.getElementById('eqCanvas');
    if (!canvas || !canvas.getContext) return;
    const ctx = canvas.getContext('2d');
    const bars = 28;
    const heights = new Array(bars).fill(6);

    function resize() {
      const rect = canvas.parentElement.getBoundingClientRect();
      canvas.width = Math.max(10, Math.floor(rect.width));
      canvas.height = Math.max(10, Math.floor(rect.height));
    }
    resize();
    window.addEventListener('resize', resize);

    function draw() {
      const layer = document.getElementById('ustLayerEq');
      if (layer && layer.classList.contains('active')) {
        const w = canvas.width;
        const h = canvas.height;
        ctx.clearRect(0, 0, w, h);
        const gap = 4;
        const barW = Math.max(4, (w - 40 - gap * (bars - 1)) / bars);
        const activeBoost = reactorState.speaking ? 0.72 : 0.25;
        for (let i = 0; i < bars; i++) {
          const target = 8 + Math.random() * (h * activeBoost);
          heights[i] += (target - heights[i]) * 0.2;
          const x = 20 + i * (barW + gap);
          const y = h - 32 - heights[i];
          const grad = ctx.createLinearGradient(0, y, 0, h - 32);
          grad.addColorStop(0, '#ff00aa');
          grad.addColorStop(0.5, '#00ffcc');
          grad.addColorStop(1, '#0096ff');
          ctx.fillStyle = grad;
          ctx.fillRect(x, y, barW, heights[i]);
        }
      }
      requestAnimationFrame(draw);
    }
    requestAnimationFrame(draw);
  }

  // --------------------------------------------------------------------------
  // 3. ÜST PANEL KATMAN YÖNETİMİ (Reaktör / Log / XAI / Kod / EQ / Hata Şeridi)
  // --------------------------------------------------------------------------
  let currentTopMode = 'reaktor';
  const persistentErrors = new Map();

  function setTopMode(mode) {
    currentTopMode = mode;
    const map = {
      reaktor: 'ustLayerReaktor',
      log: 'ustLayerLog',
      xai: 'ustLayerXai',
      code: 'ustLayerCode',
      eq: 'ustLayerEq'
    };
    Object.keys(map).forEach((k) => {
      const el = document.getElementById(map[k]);
      if (el) el.classList.toggle('active', k === mode);
    });
    document.querySelectorAll('.fab-ust-pill').forEach((btn) => {
      btn.classList.toggle('active', btn.getAttribute('data-ust-mode') === mode);
    });
    const brainBtn = document.getElementById('btnFlowBrain');
    if (brainBtn) {
      brainBtn.classList.toggle('active', mode === 'log' || mode === 'xai');
    }
    if (mode === 'eq') {
      setCenterOrbState('MUSIC');
    } else if (centerOrbState === 'MUSIC') {
      setCenterOrbState(lastMacOnline ? 'ACTIVE' : 'SLEEPING');
    }
  }

  function toggleLogViewer() {
    if (currentTopMode === 'log' || currentTopMode === 'xai') {
      setTopMode('reaktor');
    } else {
      setTopMode('log');
    }
  }

  function appendLog(text, level = 'info') {
    const box = document.getElementById('ustLogScroll');
    if (!box) return;
    const line = document.createElement('div');
    line.className = `fab-log-line ${level}`;
    const ts = new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    line.innerHTML = `<span class="fab-log-time">${ts}</span>${escapeHtmlSimple(text)}`;
    box.appendChild(line);
    while (box.children.length > 400) {
      box.removeChild(box.firstChild);
    }
    box.scrollTop = box.scrollHeight;
  }

  function setXaiStage(stageIndex, detailText) {
    const nodes = document.querySelectorAll('.fab-xai-node');
    nodes.forEach((node, idx) => {
      node.classList.remove('active', 'done');
      if (idx < stageIndex) node.classList.add('done');
      else if (idx === stageIndex) node.classList.add('active');
    });
    const det = document.getElementById('xaiDetailText');
    if (det && detailText) det.textContent = detailText;
  }

  function setCodeViewer(code, title = 'Kod Çıktısı') {
    const pre = document.getElementById('ustCodePre');
    const lbl = document.getElementById('ustCodeLabel');
    if (pre) pre.textContent = code || '';
    if (lbl) lbl.textContent = `💻 ${title}`;
    const drawerEditor = document.getElementById('drawerCodeEditor');
    if (drawerEditor && code) drawerEditor.value = code;
  }

  function showPersistentError(key, message) {
    persistentErrors.set(key, message);
    renderErrorStrip();
  }

  function clearPersistentError(key) {
    if (persistentErrors.delete(key)) {
      renderErrorStrip();
    }
  }

  function renderErrorStrip() {
    const strip = document.getElementById('fabErrorStrip');
    const msgEl = document.getElementById('fabErrorStripText');
    if (!strip || !msgEl) return;
    if (persistentErrors.size === 0) {
      strip.hidden = true;
      return;
    }
    const items = Array.from(persistentErrors.values());
    msgEl.textContent = `⚠️ ${items[items.length - 1]}`;
    strip.hidden = false;
  }

  // --------------------------------------------------------------------------
  // 4. ORTA DURUM ORBU (CenterButtonGorsel) & KAYAN ŞERİT (SeritGorsel)
  // --------------------------------------------------------------------------
  let centerOrbState = 'SLEEPING';
  let lastMacOnline = false;

  function setCenterOrbState(state, progressPct = null) {
    centerOrbState = state;
    const orb = document.getElementById('btnCenterOrb');
    if (!orb) return;
    orb.classList.remove('state-active', 'state-sleeping', 'state-music', 'state-busy');
    if (state === 'ACTIVE') {
      orb.textContent = '🟢 AKTİF';
      orb.classList.add('state-active');
    } else if (state === 'MUSIC') {
      orb.textContent = '🎵 MÜZİK';
      orb.classList.add('state-music');
    } else if (state === 'BUSY') {
      orb.textContent = progressPct !== null ? `⏳ %${progressPct}` : '⏳ İŞLENİYOR';
      orb.classList.add('state-busy');
    } else {
      orb.textContent = '🌙 UYKUDA';
      orb.classList.add('state-sleeping');
    }
  }

  function updateTicker(text) {
    const el = document.getElementById('fabSeritTrack');
    if (el && text) el.textContent = text;
  }

  // --------------------------------------------------------------------------
  // 5. SAĞ PANEL (SagPanelGorsel / #rightDrawer)
  // --------------------------------------------------------------------------
  let currentDrawerTab = 'kadro';
  let lastReportTitle = '📊 BİLGİ & RAPOR PANELİ';
  let lastReportMarkdown = '';

  const DRAWER_TITLES = {
    kadro: '🏛️ ORGANİZASYON & MECLİS KADROSU',
    rapor: '📊 BİLGİ & RAPOR PANELİ',
    havuz: '📚 AR-GE LİNK HAVUZU (229)',
    rea: '🛡️ REA KOD HASTANESİ (AST)',
    kod: '💻 KOD ÖNİZLEME & EDİTÖR',
    ayarlar: '⚙️ AYARLAR & UZAKTAN KÖPRÜ'
  };

  function openRightPanel(tab = null, opts = {}) {
    const win = document.getElementById('fabWindow');
    const backdrop = document.getElementById('fabDrawerBackdrop');
    if (tab) switchDrawerTab(tab);
    if (win) win.classList.add('drawer-open');
    if (backdrop && window.innerWidth <= 960) backdrop.classList.add('active');
    const toggleBtn = document.getElementById('btnToggleRightPanel');
    if (toggleBtn) toggleBtn.classList.add('active');

    if (opts.pulse) {
      pulseDrawerUpdated();
    }
  }

  function closeRightPanel() {
    const win = document.getElementById('fabWindow');
    const backdrop = document.getElementById('fabDrawerBackdrop');
    if (win) win.classList.remove('drawer-open');
    if (backdrop) backdrop.classList.remove('active');
    const toggleBtn = document.getElementById('btnToggleRightPanel');
    if (toggleBtn) toggleBtn.classList.remove('active');
  }

  function toggleRightPanel(tab = null) {
    const win = document.getElementById('fabWindow');
    if (!win) return;
    if (win.classList.contains('drawer-open') && (!tab || tab === currentDrawerTab)) {
      closeRightPanel();
    } else {
      openRightPanel(tab || currentDrawerTab);
    }
  }

  function switchDrawerTab(tab) {
    currentDrawerTab = tab;
    const titleEl = document.getElementById('drawerPanelTitle');
    if (titleEl) {
      titleEl.textContent = tab === 'rapor' ? lastReportTitle : (DRAWER_TITLES[tab] || '📊 BİLGİ & RAPOR PANELİ');
    }
    document.querySelectorAll('.fab-drawer-tab').forEach((btn) => {
      btn.classList.toggle('active', btn.getAttribute('data-drawer-tab') === tab);
    });
    document.querySelectorAll('.fab-drawer-page').forEach((pg) => {
      pg.classList.toggle('active', pg.getAttribute('data-drawer-page') === tab);
    });
    const saveBtn = document.getElementById('btnDrawerSave');
    if (saveBtn) {
      if (tab === 'havuz') saveBtn.textContent = '🔄 YENİLE';
      else if (tab === 'kod') saveBtn.textContent = '🛡️ REA İLE TARA';
      else saveBtn.textContent = '💾 KAYDET';
    }

    if (tab === 'havuz' && typeof window.loadLinkPoolItems === 'function') {
      window.loadLinkPoolItems();
    }
    if (tab === 'rea' && typeof window.fetchReaHistory === 'function') {
      window.fetchReaHistory();
    }
  }

  function pulseDrawerUpdated() {
    const badge = document.getElementById('drawerBadgeUpdated');
    const browser = document.getElementById('drawerReportBrowser');
    if (badge) {
      badge.hidden = false;
      clearTimeout(pulseDrawerUpdated._t1);
      pulseDrawerUpdated._t1 = setTimeout(() => { badge.hidden = true; }, 3500);
    }
    if (browser) {
      browser.classList.add('pulse');
      clearTimeout(pulseDrawerUpdated._t2);
      pulseDrawerUpdated._t2 = setTimeout(() => { browser.classList.remove('pulse'); }, 1800);
    }
  }

  function showReportInDrawer(title, htmlBody, rawText = '') {
    lastReportTitle = title || '📊 BİLGİ & RAPOR PANELİ';
    lastReportMarkdown = rawText || '';
    const box = document.getElementById('drawerReportBrowser');
    if (box) box.innerHTML = htmlBody;
    openRightPanel('rapor', { pulse: true });
  }

  // --------------------------------------------------------------------------
  // 6. SESLİ KOMUT (MicButtonGorsel — Web Speech STT) & HOPARLÖR (TTS)
  // --------------------------------------------------------------------------
  let speakerEnabled = localStorage.getItem('fabrika_speaker_on') === '1';
  let recognition = null;
  let isListening = false;

  function initVoiceControls() {
    const micBtn = document.getElementById('btnMic');
    const spkBtn = document.getElementById('btnSpeaker');

    function syncSpeakerUI() {
      if (!spkBtn) return;
      spkBtn.classList.toggle('active', speakerEnabled);
      spkBtn.textContent = speakerEnabled ? '🔊' : '🔇';
      spkBtn.title = speakerEnabled
        ? 'Hoparlör Açık (Tıkla: Sessize Al)'
        : 'Hoparlör Kapalı (Tıkla: Yanıtları Sesli Oku)';
    }
    syncSpeakerUI();

    if (spkBtn) {
      spkBtn.addEventListener('click', () => {
        speakerEnabled = !speakerEnabled;
        localStorage.setItem('fabrika_speaker_on', speakerEnabled ? '1' : '0');
        if (!speakerEnabled) stopSpeaking();
        syncSpeakerUI();
        appendLog(speakerEnabled ? '🔊 Sesli okuma açıldı (Tarayıcı TTS).' : '🔇 Sesli okuma kapatıldı.', 'info');
      });
    }

    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (micBtn) {
      micBtn.addEventListener('click', () => {
        if (!SpeechRec) {
          appendLog('⚠️ Bu tarayıcı Web Speech API (mikrofon dikte) desteklemiyor.', 'warn');
          if (typeof window.appendMessage === 'function') {
            window.appendMessage('agent', 'Sistem', '⚠️ Bu tarayıcıda yerleşik sesli dikte desteklenmiyor; klavyeden yazabilirsiniz.');
          }
          return;
        }
        if (isListening && recognition) {
          recognition.stop();
          return;
        }
        try {
          recognition = new SpeechRec();
          recognition.lang = 'tr-TR';
          recognition.interimResults = false;
          recognition.maxAlternatives = 1;
          recognition.onstart = () => {
            isListening = true;
            micBtn.classList.add('listening');
            appendLog('🎤 Dinleniyor (tr-TR)...', 'ok');
            pulseReactor(0.65, 2000);
          };
          recognition.onresult = (ev) => {
            const transcript = ev.results && ev.results[0] && ev.results[0][0] ? ev.results[0][0].transcript : '';
            if (transcript) {
              const inp = document.getElementById('chatInput');
              if (inp) {
                inp.value = transcript;
                autoResizeChatInput(inp);
                if (typeof window.sendMessage === 'function') window.sendMessage();
              }
            }
          };
          recognition.onerror = (ev) => {
            appendLog(`🎤 Mikrofon hatası: ${ev.error || 'bilinmiyor'}`, 'warn');
          };
          recognition.onend = () => {
            isListening = false;
            micBtn.classList.remove('listening');
          };
          recognition.start();
        } catch (err) {
          appendLog(`🎤 Mikrofon başlatılamadı: ${err.message}`, 'error');
        }
      });
    }
  }

  function speakText(text) {
    if (!speakerEnabled || !('speechSynthesis' in window)) return;
    const clean = String(text || '')
      .replace(/```[\s\S]*?```/g, ' kod bloğu ')
      .replace(/[`*_#]/g, '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 600);
    if (!clean) return;
    try {
      window.speechSynthesis.cancel();
      const utt = new SpeechSynthesisUtterance(clean);
      utt.lang = 'tr-TR';
      utt.rate = 1.04;
      utt.onstart = () => { reactorState.speaking = true; };
      utt.onend = () => {
        reactorState.speaking = false;
        reactorState.targetVolume = 0;
        reactorState.targetFft = 0;
      };
      utt.onerror = () => { reactorState.speaking = false; };
      window.speechSynthesis.speak(utt);
    } catch (e) {}
  }

  function stopSpeaking() {
    reactorState.speaking = false;
    reactorState.targetVolume = 0;
    reactorState.targetFft = 0;
    if ('speechSynthesis' in window) {
      try { window.speechSynthesis.cancel(); } catch (e) {}
    }
  }

  // --------------------------------------------------------------------------
  // 7. YARDIMCILAR VE OLAY BAĞLANTILARI
  // --------------------------------------------------------------------------
  function escapeHtmlSimple(str) {
    return String(str || '').replace(/[&<>"']/g, (m) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    }[m]));
  }

  function autoResizeChatInput(el) {
    if (!el) return;
    el.style.height = '36px';
    el.style.height = Math.min(120, Math.max(36, el.scrollHeight)) + 'px';
  }

  function initDesktopControls() {
    // Üst Panel mod hapları
    document.querySelectorAll('.fab-ust-pill').forEach((btn) => {
      btn.addEventListener('click', () => {
        const mode = btn.getAttribute('data-ust-mode');
        if (mode) setTopMode(mode);
      });
    });

    // Üst Panel çift tık: Log <-> XAI (UstPanelGorsel.mouseDoubleClickEvent birebir)
    const ustStage = document.getElementById('ustPanelStage');
    if (ustStage) {
      ustStage.addEventListener('dblclick', () => {
        if (currentTopMode === 'log') setTopMode('xai');
        else if (currentTopMode === 'xai') setTopMode('log');
      });
    }

    // HoverFlowBar (👤 ➕ ⚙️ 🧠 ◧)
    const btnBrain = document.getElementById('btnFlowBrain');
    if (btnBrain) {
      btnBrain.addEventListener('click', () => {
        toggleLogViewer();
        if (desktopLive && typeof window.sendUiAction === 'function') {
          window.sendUiAction('toggle_log');
        }
      });
    }

    const btnUser = document.getElementById('btnFlowUser');
    if (btnUser) btnUser.addEventListener('click', () => toggleRightPanel('rapor'));

    const btnAdd = document.getElementById('btnFlowAdd');
    if (btnAdd) btnAdd.addEventListener('click', () => toggleRightPanel('kadro'));

    const btnSettings = document.getElementById('btnFlowSettings');
    if (btnSettings) btnSettings.addEventListener('click', () => toggleRightPanel('ayarlar'));

    const btnToggleRight = document.getElementById('btnToggleRightPanel');
    if (btnToggleRight) {
      btnToggleRight.addEventListener('click', () => {
        const willOpen = !(document.getElementById('fabWindow') || {}).classList?.contains('drawer-open');
        toggleRightPanel();
        if (desktopLive && typeof window.sendUiAction === 'function') {
          window.sendUiAction(willOpen ? 'open_right_panel' : 'close_right_panel');
        }
      });
    }

    // Trafik lambaları (sol üst)
    const tlClose = document.getElementById('btnTlClose');
    if (tlClose) tlClose.addEventListener('click', () => { window.location.href = '/'; });

    const tlMin = document.getElementById('btnTlMin');
    if (tlMin) tlMin.addEventListener('click', () => { window.location.href = '/lab.html'; });

    const tlMax = document.getElementById('btnTlMax');
    if (tlMax) tlMax.addEventListener('click', () => toggleRightPanel());

    // Center Orb
    const centerOrb = document.getElementById('btnCenterOrb');
    if (centerOrb) {
      centerOrb.addEventListener('click', () => {
        if (desktopLive && typeof window.sendUiAction === 'function') {
          if (centerOrbState === 'SLEEPING') window.sendUiAction('wake');
          else if (centerOrbState === 'MUSIC') window.sendUiAction('active_mode');
          else window.sendUiAction('music_mode');
        }
        if (currentTopMode === 'eq') {
          setTopMode('reaktor');
        } else {
          setTopMode('eq');
        }
      });
    }

    // KaliciHataSeridi kapatma (✕)
    const errClose = document.getElementById('btnFabErrorClose');
    if (errClose) {
      errClose.addEventListener('click', () => {
        persistentErrors.clear();
        renderErrorStrip();
      });
    }

    // Log kopyala & temizle
    const btnCopyLogs = document.getElementById('btnCopyLogs');
    if (btnCopyLogs) {
      btnCopyLogs.addEventListener('click', () => {
        const box = document.getElementById('ustLogScroll');
        if (box && navigator.clipboard) {
          navigator.clipboard.writeText(box.innerText).catch(() => {});
          appendLog('📋 Loglar panoya kopyalandı.', 'ok');
        }
      });
    }
    const btnClearLogs = document.getElementById('btnClearLogs');
    if (btnClearLogs) {
      btnClearLogs.addEventListener('click', () => {
        const box = document.getElementById('ustLogScroll');
        if (box) box.innerHTML = '';
      });
    }

    // Kod görüntüleyici -> Sağ Panel Kod sekmesine taşı
    const btnPopCode = document.getElementById('btnPopCodeToDrawer');
    if (btnPopCode) {
      btnPopCode.addEventListener('click', () => openRightPanel('kod', { pulse: true }));
    }

    // Sağ Panel Sekmeleri
    document.querySelectorAll('.fab-drawer-tab').forEach((tabBtn) => {
      tabBtn.addEventListener('click', () => {
        const tab = tabBtn.getAttribute('data-drawer-tab');
        if (tab) switchDrawerTab(tab);
      });
    });

    // Sağ Panel Alt Butonlar (KAPAT / KAYDET)
    const btnCloseDrawer = document.getElementById('btnDrawerClose');
    if (btnCloseDrawer) {
      btnCloseDrawer.addEventListener('click', () => {
        closeRightPanel();
        if (desktopLive && typeof window.sendUiAction === 'function') {
          window.sendUiAction('close_right_panel');
        }
      });
    }

    const backdrop = document.getElementById('fabDrawerBackdrop');
    if (backdrop) backdrop.addEventListener('click', closeRightPanel);

    const btnDrawerSave = document.getElementById('btnDrawerSave');
    if (btnDrawerSave) {
      btnDrawerSave.addEventListener('click', () => {
        if (currentDrawerTab === 'havuz') {
          if (typeof window.loadLinkPoolItems === 'function') window.loadLinkPoolItems();
          pulseDrawerUpdated();
          return;
        }
        if (currentDrawerTab === 'kod') {
          const code = (document.getElementById('drawerCodeEditor') || {}).value || '';
          const reaIn = document.getElementById('reaInput');
          if (reaIn && code.trim()) {
            reaIn.value = code;
            switchDrawerTab('rea');
            const scanBtn = document.getElementById('btnRunReaScan');
            if (scanBtn) scanBtn.click();
          }
          return;
        }
        // Rapor veya kodu metin dosyası olarak indir
        const content = lastReportMarkdown || (document.getElementById('drawerReportBrowser') || {}).innerText || '';
        if (!content.trim()) return;
        const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `fabrika_rapor_${Date.now()}.txt`;
        a.click();
        URL.revokeObjectURL(a.href);
        appendLog('💾 Sağ panel raporu indirildi.', 'ok');
      });
    }

    // Kadro kartları tıklanınca alt yazı alanına #Ajan ön eki koy
    document.querySelectorAll('.fab-org-card[data-agent-tag]').forEach((card) => {
      card.addEventListener('click', () => {
        document.querySelectorAll('.fab-org-card').forEach((c) => c.classList.remove('active'));
        card.classList.add('active');
        const tag = card.getAttribute('data-agent-tag');
        const promptHint = card.getAttribute('data-agent-prompt') || '';
        const inp = document.getElementById('chatInput');
        if (inp && tag) {
          inp.value = `${tag} `;
          inp.placeholder = promptHint || `${tag} ajanına talimat verin...`;
          inp.focus();
          autoResizeChatInput(inp);
        }
        if (window.innerWidth <= 960) closeRightPanel();
      });
    });

    // ChatInputEdit otomatik büyüme + Shift+Enter yeni satır + Esc konuşma durdurma (Mac barge-in dahil)
    const chatInp = document.getElementById('chatInput');
    if (chatInp) {
      chatInp.addEventListener('input', () => autoResizeChatInput(chatInp));
      chatInp.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
          stopSpeaking();
          if (desktopLive && typeof window.sendUiAction === 'function') {
            window.sendUiAction('barge_in');
          }
          appendLog('🛑 Konuşma Durduruldu (Esc / Mac Barge-In)', 'warn');
        }
      });
    }

    // Klavye kısayolu: ⌘\ veya ⌘B Sağ Panel aç-kapa
    window.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === '\\' || e.key.toLowerCase() === 'b')) {
        e.preventDefault();
        toggleRightPanel();
      } else if (e.key === 'Escape') {
        stopSpeaking();
      }
    });
  }

  // --------------------------------------------------------------------------
  // 8. CANLI MAC MASAÜSTÜ AYNA SENKRONİZASYONU (desktop_sync)
  // --------------------------------------------------------------------------
  let desktopLive = false;
  let lastSyncedChatSeq = 0;
  let lastSyncedLogSeq = 0;
  let lastSyncedSidePanelTs = 0;
  let lastOrgSig = '';

  const XAI_STATE_TO_STEP = {
    BOSTA: 0,
    GIRDI_ALINDI: 0,
    FAST_CATCHER: 1,
    JEV_YONLENDIRME: 2,
    SLM_SOHBET: 3,
    BUYUK_MODEL: 3,
    ARAC_ICRA: 3,
    DOGRULAMA: 4,
    TAMAMLANDI: 4
  };

  function sanitizeReportHtml(rawHtml) {
    return String(rawHtml || '')
      .replace(/<script[\s\S]*?<\/script>/gi, '')
      .replace(/\son\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '');
  }

  function renderQuestionCard(card) {
    const box = document.getElementById('fabQuestionCard');
    const titleEl = document.getElementById('fabQuestionTitle');
    const textEl = document.getElementById('fabQuestionText');
    const optsEl = document.getElementById('fabQuestionOptions');
    if (!box || !optsEl) return;
    if (!card || !card.visible || !card.question) {
      box.hidden = true;
      return;
    }
    if (titleEl) titleEl.textContent = card.title || '❓ Fabrika Sorusu';
    if (textEl) textEl.textContent = card.question;
    optsEl.innerHTML = '';
    (card.options || []).forEach((opt) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'fab-question-opt-btn';
      btn.textContent = opt;
      btn.addEventListener('click', () => {
        box.hidden = true;
        if (typeof window.sendUiAction === 'function') {
          window.sendUiAction('answer_question', { choice: opt });
        }
      });
      optsEl.appendChild(btn);
    });
    box.hidden = false;
  }

  function renderOrgAgents(agents) {
    if (!Array.isArray(agents) || !agents.length) return;
    const sig = agents.map((a) => `${a.key}:${a.name}`).join('|');
    if (sig === lastOrgSig) return;
    lastOrgSig = sig;
    const page = document.getElementById('drawerKadroPage');
    if (!page) return;
    const core = agents.filter((a) => a.is_core);
    const dept = agents.filter((a) => !a.is_core);
    const cardHtml = (a) => `
      <button type="button" class="fab-org-card" data-agent-tag="#${escapeHtmlSimple(a.name || a.key)}" data-agent-prompt="#${escapeHtmlSimple(a.name || a.key)} ">
        <div>
          <div class="fab-org-name" style="color:${escapeHtmlSimple(a.color || '#00FFCC')};">${escapeHtmlSimple(a.display_name || a.key)}</div>
          <div class="fab-org-role">${escapeHtmlSimple(a.name || a.key)} • Canlı Mac Kadrosu</div>
        </div>
        <span class="fab-org-badge">Hazır</span>
      </button>`;
    page.innerHTML = `
      <div class="fab-org-section-title core">YÖNETİM KADROSU (CANLI MAC)</div>
      ${core.map(cardHtml).join('')}
      ${dept.length ? `<div class="fab-org-section-title dept">DEPARTMANLAR</div>${dept.map(cardHtml).join('')}` : ''}
    `;
    page.querySelectorAll('.fab-org-card[data-agent-tag]').forEach((card) => {
      card.addEventListener('click', () => {
        page.querySelectorAll('.fab-org-card').forEach((c) => c.classList.remove('active'));
        card.classList.add('active');
        const tag = card.getAttribute('data-agent-tag');
        const inp = document.getElementById('chatInput');
        if (inp && tag) {
          inp.value = `${tag} `;
          inp.focus();
          autoResizeChatInput(inp);
        }
        if (window.innerWidth <= 960) closeRightPanel();
      });
    });
  }

  function applyDesktopSync(state) {
    if (!state || typeof state !== 'object') return;
    desktopLive = Boolean(state.desktop_app_open);

    const syncBadge = document.getElementById('fabDesktopSyncBadge');
    if (syncBadge) {
      syncBadge.textContent = desktopLive ? '🖥️ MAC BİREBİR' : '⚡ KÖPRÜ • 443';
      syncBadge.classList.toggle('live', desktopLive);
    }

    if (!desktopLive) return;

    // 1. Durum orbu, konuşma/işleme ve 3D reaktör
    if (state.is_processing) {
      setCenterOrbState('BUSY');
    } else if (state.center_state) {
      setCenterOrbState(state.center_state);
    }
    reactorState.speaking = Boolean(state.is_speaking || state.is_processing);

    const chatInp = document.getElementById('chatInput');
    if (chatInp && state.placeholder && !chatInp.value) {
      chatInp.placeholder = state.placeholder;
    }

    if (state.error_strip) showPersistentError('mac_desktop_err', state.error_strip);
    else clearPersistentError('mac_desktop_err');

    // 2. Canlı XAI Durum Makinesi
    if (state.xai) {
      const stepIdx = XAI_STATE_TO_STEP[state.xai.state] ?? 0;
      const det = `[${state.xai.state}] ${state.xai.agent || 'CEO'} • ${state.xai.model || ''} • ${state.xai.desc || ''}`;
      setXaiStage(stepIdx, det.trim());
    }

    // 3. Canlı Üst Panel Logları
    if (Array.isArray(state.logs)) {
      state.logs.forEach((l) => {
        if (l && Number(l.seq) > lastSyncedLogSeq) {
          lastSyncedLogSeq = Number(l.seq);
          appendLog(l.text, l.level || 'info');
        }
      });
    }

    // 4. Canlı Alt Panel Sohbet Akışı (tekil seq ile sıfır çift kayıt)
    if (Array.isArray(state.chat_messages)) {
      const box = document.getElementById('messagesBox');
      state.chat_messages.forEach((m) => {
        const seq = Number(m && m.seq);
        if (!seq || seq <= lastSyncedChatSeq) return;
        lastSyncedChatSeq = seq;

        // Web'den iyimser olarak basılmış kullanıcı satırıyla eşleşiyorsa üstüne terfi ettir
        if (m.role === 'user' && box) {
          const pending = box.querySelector('[data-pending-user-text]');
          if (pending && pending.getAttribute('data-pending-user-text') === m.text) {
            pending.removeAttribute('data-pending-user-text');
            pending.setAttribute('data-seq', String(seq));
            return;
          }
        }

        const mediaObj = m.media_url ? { type: 'image', url: m.media_url, file_name: 'mac_cikti.png' } : null;
        if (typeof window.appendMessage === 'function') {
          window.appendMessage(m.role === 'user' ? 'user' : 'agent', m.sender || 'Fabrika', m.text || '', null, mediaObj, { seq, ts: m.ts });
        }

        if (m.role === 'agent') {
          pulseReactor(0.92, 950);
          const codeMatch = String(m.text || '').match(/```(?:[\w+-]*)\n([\s\S]*?)```/);
          if (codeMatch && codeMatch[1]) {
            setCodeViewer(codeMatch[1].trim(), `${m.sender || 'Fabrika'} Kod`);
          }
          speakText(m.text || '');
        }
      });
    }

    // 5. Canlı Sağ Panel (Rapor HTML / Kod / Kapatma)
    if (state.side_panel && Number(state.side_panel.updated_at || 0) > lastSyncedSidePanelTs) {
      lastSyncedSidePanelTs = Number(state.side_panel.updated_at);
      if (state.side_panel.open) {
        if (state.side_panel.mode === 'code' && state.side_panel.code) {
          setCodeViewer(state.side_panel.code, state.side_panel.title || 'Kod Önizleme');
          openRightPanel('kod', { pulse: true });
        } else if (state.side_panel.html) {
          showReportInDrawer(
            state.side_panel.title || '📊 BİLGİ & RAPOR PANELİ',
            sanitizeReportHtml(state.side_panel.html),
            ''
          );
        } else {
          openRightPanel('rapor', { pulse: true });
        }
      } else {
        closeRightPanel();
      }
    }

    // 6. İnteraktif Soru Kartı & Canlı Kadro
    renderQuestionCard(state.question_card);
    renderOrgAgents(state.org_agents);
  }

  // --------------------------------------------------------------------------
  // 9. APP.JS ENTEGRASYON KÖPRÜSÜ (window.FabrikaDesktop)
  // --------------------------------------------------------------------------
  window.FabrikaDesktop = {
    isDesktopLive: () => desktopLive,
    applyDesktopSync,
    resolveAgentColor,
    pulseReactor,
    setTopMode,
    toggleLogViewer,
    appendLog,
    setXaiStage,
    setCodeViewer,
    showPersistentError,
    clearPersistentError,
    setCenterOrbState,
    updateTicker,
    openRightPanel,
    closeRightPanel,
    toggleRightPanel,
    switchDrawerTab,
    showReportInDrawer,
    speakText,
    stopSpeaking,
    autoResizeChatInput,
    onMacStats(data) {
      const macOn = Boolean(data && data.mac_bridge_online);
      lastMacOnline = macOn;
      const hasCpu = data && data.cpu !== null && data.cpu !== undefined;
      const hasRam = data && data.ram !== null && data.ram !== undefined;

      if (centerOrbState !== 'MUSIC' && centerOrbState !== 'BUSY') {
        setCenterOrbState(macOn ? 'ACTIVE' : 'SLEEPING');
      }

      if (macOn) {
        clearPersistentError('mac_offline');
      } else {
        showPersistentError('mac_offline', 'Mac Fabrika köprüsü çevrimdışı — bilgisayarınızda Fabrika açıldığında otomatik bağlanır.');
      }

      const xaiMac = document.getElementById('xaiMacStatus');
      const xaiCpu = document.getElementById('xaiCpuVal');
      const xaiRam = document.getElementById('xaiRamVal');
      const xaiPool = document.getElementById('xaiPoolVal');
      if (xaiMac) xaiMac.textContent = macOn ? '🟢 Çevrimiçi' : '⚪ Çevrimdışı';
      if (xaiCpu) xaiCpu.textContent = hasCpu ? `%${data.cpu}` : '—';
      if (xaiRam) xaiRam.textContent = hasRam ? `%${data.ram}` : '—';
      if (xaiPool && data.link_pool_count !== undefined) xaiPool.textContent = String(data.link_pool_count);

      const cpuTxt = hasCpu ? `CPU %${data.cpu}` : 'CPU —';
      const ramTxt = hasRam ? `RAM %${data.ram}` : 'RAM —';
      const lpTxt = data && data.link_pool_count !== undefined ? `${data.link_pool_count} AR-GE LİNKİ` : 'AR-GE HAVUZU';
      const reaTxt = data && data.rea_score !== null && data.rea_score !== undefined ? `REA ${data.rea_score}/100` : 'REA HAZIR';
      const prefix = macOn ? '🟢 MAC ÇEVRİMİÇİ (PORT 443 HTTPS)' : '⚪ MAC ÇEVRİMDIŞI (BEKLENİYOR)';
      updateTicker(`${prefix}  •  ${cpuTxt}  •  ${ramTxt}  •  ${lpTxt}  •  ${reaTxt}  •  YUSASUFHIN.COM UZAKTAN KOMUTA`);
    },
    onCommandSent(text) {
      pulseReactor(0.85, 900);
      setCenterOrbState('BUSY');
      setXaiStage(1, `Port-443 HTTPS köprüsünden Mac'e iletiliyor: "${String(text).slice(0, 72)}"`);
      appendLog(`⌨️ Komut gönderildi -> ${text}`, 'info');
    },
    onReplyReceived(sender, text, action, media) {
      pulseReactor(0.95, 1100);
      setCenterOrbState(lastMacOnline ? 'ACTIVE' : 'SLEEPING');
      setXaiStage(4, `${sender} yanıtladı${action ? ` (${action})` : ''}.`);
      appendLog(`✅ ${sender}: ${String(text || '').replace(/\s+/g, ' ').slice(0, 140)}`, 'ok');

      // Yanıtta kod bloğu varsa Üst Panel Kod Görüntüleyiciye ve Sağ Panel Kod sekmesine aktar
      const codeMatch = String(text || '').match(/```(?:[\w+-]*)\n([\s\S]*?)```/);
      if (codeMatch && codeMatch[1]) {
        setCodeViewer(codeMatch[1].trim(), `${sender} Kod Çıktısı`);
      }

      // Uzun rapor veya görsel geldiyse Sağ Panel Rapor sekmesini güncelle
      if ((media && media.url) || String(text || '').length > 360 || (action && ['rea_analiz', 'link_havuzu_rapor', 'ekran_goruntusu'].includes(action))) {
        const htmlBody = typeof window.formatMarkdown === 'function' ? window.formatMarkdown(text) : escapeHtmlSimple(text);
        const mediaBlock = (media && media.url)
          ? `<div style="margin-bottom:10px;"><img src="${escapeHtmlSimple(media.url)}" alt="Ekran" style="max-width:100%; border-radius:8px; border:1px solid #1e293b;"></div>`
          : '';
        showReportInDrawer(`📊 ${sender} — ÇIKTI`, `${mediaBlock}<div>${htmlBody}</div>`, text);
      }

      speakText(text);
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    initGalaxyReactor();
    initEqVisualizer();
    initVoiceControls();
    initDesktopControls();
    appendLog('🏭 Fabrika Uzaktan Masaüstü Arayüzü başlatıldı (Port-443 HTTPS Köprüsü).', 'ok');
    setXaiStage(0, 'Komut bekleniyor — üst panelde çift tıklayarak Log ↔ XAI geçişi yapabilirsiniz.');
  });
})();
