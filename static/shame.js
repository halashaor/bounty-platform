/* 結 YUI · 耻辱柱幽冥哥特动效与三选项表单控制（零外部依赖、防倒置防裁切波纹布面） */
(() => {
  /* ---------- 发布者三选项表单：仅选「其他」时将理由设为必填 ---------- */
  document.querySelectorAll('.shame-pin-form').forEach(form => {
    const input = form.querySelector('input[name="reason"]');
    const radios = form.querySelectorAll('input[name="kind"]');
    if (!input || !radios.length) return;
    const sync = () => {
      const other = form.querySelector('input[name="kind"]:checked')?.value === 'other';
      input.required = other;
      if (!other) input.value = '';
    };
    radios.forEach(radio => radio.addEventListener('change', sync));
    sync();
  });

  const stages = document.querySelectorAll('[data-shame-stage]');
  if (!stages.length) return;

  const SANS = "'Hiragino Sans','PingFang SC','Noto Sans CJK SC','Source Han Sans SC','Microsoft YaHei',sans-serif";
  const SERIF = "'Hiragino Mincho ProN','Yu Mincho','Noto Serif CJK SC','Source Han Serif SC','Songti SC',serif";
  const STAMP_LABELS = { overdue: '逾期', rejected: '未达标', other: '示众' };
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

  const motionEnabled = () => document.documentElement.dataset.motion !== 'off' &&
    !matchMedia('(prefers-reduced-motion: reduce)').matches;
  const soundEnabled = () => {
    try { return localStorage.getItem('bounty-sound') === 'on'; } catch { return false; }
  };

  /* ---------- Web Audio 幽冥音效合成（遵循全站音效开关，默认静音） ---------- */
  let audioCtx = null;
  function getAudio() {
    if (!soundEnabled()) return null;
    if (!audioCtx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      audioCtx = new AC();
      audioCtx.master = audioCtx.createGain();
      audioCtx.master.gain.value = 0.38;
      audioCtx.master.connect(audioCtx.destination);
    }
    if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
    return audioCtx;
  }

  function sfxNailSlam() {
    const ac = getAudio();
    if (!ac) return;
    const t = ac.currentTime;
    const sub = ac.createOscillator(), subG = ac.createGain();
    sub.type = 'triangle';
    sub.frequency.setValueAtTime(145, t); sub.frequency.exponentialRampToValueAtTime(32, t + 0.24);
    subG.gain.setValueAtTime(0.001, t); subG.gain.exponentialRampToValueAtTime(0.76, t + 0.005);
    subG.gain.exponentialRampToValueAtTime(0.001, t + 0.30);
    sub.connect(subG).connect(ac.master);
    sub.start(t); sub.stop(t + 0.32);

    [540, 1185, 1990].forEach((freq, i) => {
      const osc = ac.createOscillator(), g = ac.createGain();
      osc.type = i === 0 ? 'sawtooth' : 'sine';
      osc.frequency.setValueAtTime(freq, t); osc.frequency.exponentialRampToValueAtTime(freq * 0.96, t + 0.38);
      const lp = ac.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 2600;
      g.gain.setValueAtTime(0.001, t); g.gain.exponentialRampToValueAtTime(0.10 / (i + 1), t + 0.004);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.42);
      osc.connect(lp).connect(g).connect(ac.master);
      osc.start(t); osc.stop(t + 0.44);
    });
  }

  function sfxWhipWhoosh() {
    const ac = getAudio();
    if (!ac) return;
    const t = ac.currentTime, dur = 0.17;
    const buf = ac.createBuffer(1, Math.ceil(ac.sampleRate * dur), ac.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * Math.sin((i / data.length) * Math.PI);
    const src = ac.createBufferSource(); src.buffer = buf;
    const f = ac.createBiquadFilter(); f.type = 'bandpass';
    f.frequency.setValueAtTime(310, t); f.frequency.exponentialRampToValueAtTime(1920, t + dur); f.Q.value = 2.4;
    const g = ac.createGain();
    g.gain.setValueAtTime(0.001, t); g.gain.linearRampToValueAtTime(0.22, t + dur * 0.65); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    src.connect(f).connect(g).connect(ac.master);
    src.start(t);
  }

  function sfxWhipCrack(power = 1) {
    const ac = getAudio();
    if (!ac) return;
    const t = ac.currentTime, dur = 0.075;
    const buf = ac.createBuffer(1, Math.ceil(ac.sampleRate * dur), ac.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / data.length, 3.2);
    const src = ac.createBufferSource(); src.buffer = buf;
    const hp = ac.createBiquadFilter(); hp.type = 'bandpass';
    hp.frequency.setValueAtTime(2350 + Math.random() * 450, t); hp.Q.value = 1.15;
    const g = ac.createGain(); g.gain.value = 0.62 * power;
    src.connect(hp).connect(g).connect(ac.master);
    src.start(t);

    const thump = ac.createOscillator(), tg = ac.createGain();
    thump.type = 'sine';
    thump.frequency.setValueAtTime(190, t); thump.frequency.exponentialRampToValueAtTime(55, t + 0.09);
    tg.gain.setValueAtTime(0.001, t); tg.gain.exponentialRampToValueAtTime(0.28 * power, t + 0.004);
    tg.gain.exponentialRampToValueAtTime(0.001, t + 0.10);
    thump.connect(tg).connect(ac.master);
    thump.start(t); thump.stop(t + 0.12);
  }

  function fitEllipsis(c, text, maxW) {
    if (!text) return '';
    if (c.measureText(text).width <= maxW) return text;
    let out = text;
    while (out.length > 1 && c.measureText(out + '…').width > maxW) out = out.slice(0, -1);
    return out + '…';
  }

  function drawCornerFiligree(c, x, y, sx, sy) {
    c.save(); c.translate(x, y); c.scale(sx, sy);
    c.strokeStyle = '#9EA8B8'; c.lineWidth = 1.8;
    c.beginPath(); c.moveTo(0, 26); c.lineTo(0, 0); c.lineTo(26, 0);
    c.moveTo(6, 20); c.quadraticCurveTo(6, 6, 20, 6); c.stroke();
    c.fillStyle = '#C8B08A'; c.beginPath(); c.arc(5, 5, 2.3, 0, Math.PI * 2); c.fill();
    c.restore();
  }

  function mountStage(root) {
    const dataEl = root.querySelector('[data-shame-data]');
    const canvas = root.querySelector('[data-shame-canvas]');
    const wrap = root.querySelector('[data-shame-wrap]');
    if (!dataEl || !canvas || !wrap) return;
    let items;
    try { items = JSON.parse(dataEl.textContent); } catch { return; }
    if (!items || !items.length) return;

    const ctx = canvas.getContext('2d');
    const countEl = root.querySelector('[data-shame-count]');
    const kindEl = root.querySelector('[data-shame-kind]');
    const reasonEl = root.querySelector('[data-shame-reason]');
    const metaEl = root.querySelector('[data-shame-meta]');
    const taskLinkEl = root.querySelector('[data-shame-task]');
    const tabs = root.querySelectorAll('[data-shame-tab]');
    const liftForms = root.querySelectorAll('[data-shame-lift-form]');

    const TEX_W = 640, TEX_H = 330;
    const flagTex = document.createElement('canvas');
    flagTex.width = TEX_W; flagTex.height = TEX_H;

    const COLS = 24;
    const cloth = {
      originX: 220, originY: 110, flagW: 390, flagH: 200,
      y: new Float32Array(COLS + 1), vy: new Float32Array(COLS + 1),
      dx: new Float32Array(COLS + 1), vx: new Float32Array(COLS + 1),
      tilt: new Float32Array(COLS + 1), vtilt: new Float32Array(COLS + 1)
    };

    const spirits = [
      { rx: 0.14, ry: 0.26, scale: 0.90, speed: 0.42, phase: 0.2, vx: 11, alpha: 0.26, x: 140, y: 120 },
      { rx: 0.54, ry: 0.18, scale: 0.72, speed: 0.55, phase: 2.1, vx: -9, alpha: 0.22, x: 520, y: 80 },
      { rx: 0.78, ry: 0.24, scale: 1.02, speed: 0.38, phase: 4.0, vx: -13, alpha: 0.28, x: 760, y: 110 },
      { rx: 0.38, ry: 0.64, scale: 0.64, speed: 0.60, phase: 1.4, vx: 8, alpha: 0.16, x: 360, y: 290 },
      { rx: 0.87, ry: 0.58, scale: 0.76, speed: 0.48, phase: 5.2, vx: -10, alpha: 0.20, x: 840, y: 260 }
    ];
    const skulls = [
      { rx: 0.11, ry: 0.46, r: 21, speed: 0.75, phase: 0.5, vx: 7, alpha: 0.60, tilt: -0.14, x: 110, y: 210 },
      { rx: 0.46, ry: 0.14, r: 15, speed: 0.90, phase: 2.4, vx: -6, alpha: 0.44, tilt: 0.11, x: 440, y: 65 },
      { rx: 0.71, ry: 0.20, r: 23, speed: 0.68, phase: 3.9, vx: -8, alpha: 0.64, tilt: 0.16, x: 690, y: 95 },
      { rx: 0.86, ry: 0.44, r: 17, speed: 0.82, phase: 1.1, vx: -5, alpha: 0.48, tilt: -0.12, x: 830, y: 205 },
      { rx: 0.61, ry: 0.70, r: 14, speed: 0.95, phase: 4.8, vx: 6, alpha: 0.36, tilt: 0.08, x: 580, y: 315 }
    ];
    const ashes = Array.from({ length: 36 }, () => ({
      x: Math.random() * 1000, y: Math.random() * 480,
      vx: -9 - Math.random() * 16, vy: -7 - Math.random() * 13,
      r: 1.0 + Math.random() * 1.9, alpha: 0.18 + Math.random() * 0.4, phase: Math.random() * Math.PI * 2
    }));
    const mistBands = Array.from({ length: 6 }, (_, i) => ({
      x: (i / 6) * 1100, yFactor: 0.78 + (i % 3) * 0.06,
      w: 250 + Math.random() * 200, h: 46 + Math.random() * 32,
      vx: (i % 2 === 0 ? 1 : -1) * (10 + Math.random() * 9), alpha: 0.08 + (i % 2) * 0.04
    }));
    const torchSparks = [];

    let activeIdx = 0;
    let canvasW = 880, canvasH = 450;
    let rafId = 0;
    let lastTs = performance.now();

    const particles = [];
    const rings = [];
    const whipTrail = [];
    const state = {
      phase: 'drop', phaseTime: 0, totalTime: 0, hitstopLeft: 0,
      shakeMag: 0, shakeX: 0, shakeY: 0, pillarCrack: 0,
      nailProgress: 0, nailRecoil: 0, flagDropY: -116, flashAlpha: 0, dyingPulse: 0,
      whipTimer: 0, whipState: 'idle', whipT: 0, whipStyle: 0,
      whipHitDone: false, whipPower: 1, localStrikes: 0, stampPop: null,
      autoLeft: 0, loud: false, restTime: 0
    };
    // 开场钉柱后自动抽 AUTO_LASHES 下就停住，画面静止后不再重画；有人点了才再动。
    // 声音只在有人点的时候响（loud），自动抽打不出声。
    const AUTO_LASHES = 3, REST_AFTER = 1.2;
    let onScreen = true;

    const current = () => items[activeIdx];
    const getTorches = () => [
      { x: canvasW * 0.085, y: canvasH * 0.34, scale: 0.94 },
      { x: canvasW * 0.74,  y: canvasH * 0.32, scale: 0.90 }
    ];

    function rebuildFlagTexture() {
      const item = current();
      const c = flagTex.getContext('2d');
      c.clearRect(0, 0, TEX_W, TEX_H);

      const flagPath = () => {
        c.beginPath();
        c.moveTo(2, 6); c.lineTo(TEX_W - 6, 6);
        c.lineTo(TEX_W - 28, TEX_H * 0.5);
        c.lineTo(TEX_W - 6, TEX_H - 6); c.lineTo(2, TEX_H - 6); c.closePath();
      };

      c.save();
      flagPath();
      c.clip();

      const darkBg = c.createLinearGradient(0, 0, TEX_W, TEX_H);
      darkBg.addColorStop(0, '#1C1F2B'); darkBg.addColorStop(0.5, '#13151F'); darkBg.addColorStop(1, '#0E1018');
      c.fillStyle = darkBg; c.fillRect(0, 0, TEX_W, TEX_H);

      c.fillStyle = '#6A1629';
      c.fillRect(0, 6, TEX_W, 18); c.fillRect(0, TEX_H - 24, TEX_W, 18);
      c.strokeStyle = 'rgba(205,215,228,0.52)'; c.lineWidth = 1.5;
      c.beginPath(); c.moveTo(0, 26); c.lineTo(TEX_W, 26); c.moveTo(0, TEX_H - 26); c.lineTo(TEX_W, TEX_H - 26); c.stroke();

      c.strokeStyle = 'rgba(220,196,156,0.22)'; c.lineWidth = 1;
      for (let x = 60; x < TEX_W - 20; x += 22) {
        [15, TEX_H - 15].forEach(y => {
          c.beginPath(); c.moveTo(x, y - 5); c.lineTo(x + 6, y); c.lineTo(x, y + 5); c.lineTo(x - 6, y); c.closePath(); c.stroke();
        });
      }

      const pLeft = 66, pRight = TEX_W - 40, pTop = 34, pBot = TEX_H - 34;
      const parch = c.createRadialGradient((pLeft + pRight) * 0.48, TEX_H * 0.48, 30, (pLeft + pRight) * 0.5, TEX_H * 0.5, 340);
      parch.addColorStop(0, '#ECE7DC'); parch.addColorStop(0.68, '#DDD5C4'); parch.addColorStop(1, '#BEB29E');
      c.fillStyle = parch;
      c.beginPath(); c.roundRect(pLeft, pTop, pRight - pLeft, pBot - pTop, 6); c.fill();

      c.strokeStyle = 'rgba(26,24,30,0.045)'; c.lineWidth = 1;
      for (let y = pTop + 4; y < pBot; y += 5) { c.beginPath(); c.moveTo(pLeft, y); c.lineTo(pRight, y); c.stroke(); }
      for (let x = pLeft + 6; x < pRight; x += 7) { c.beginPath(); c.moveTo(x, pTop); c.lineTo(x, pBot); c.stroke(); }

      c.strokeStyle = 'rgba(138,24,46,0.13)'; c.lineWidth = 4; c.lineCap = 'round';
      c.beginPath(); c.moveTo(150, 74); c.lineTo(368, 224); c.stroke();
      c.lineWidth = 2.2; c.beginPath(); c.moveTo(245, 62); c.lineTo(445, 178); c.stroke();

      c.strokeStyle = 'rgba(42,38,48,0.45)'; c.lineWidth = 1.4;
      c.strokeRect(pLeft + 8, pTop + 8, pRight - pLeft - 16, pBot - pTop - 16);
      drawCornerFiligree(c, pLeft + 12, pTop + 12, 1, 1);
      drawCornerFiligree(c, pRight - 12, pTop + 12, -1, 1);
      drawCornerFiligree(c, pLeft + 12, pBot - 12, 1, -1);
      drawCornerFiligree(c, pRight - 12, pBot - 12, -1, -1);

      c.fillStyle = '#141722'; c.fillRect(0, 6, 58, TEX_H - 12);
      c.strokeStyle = 'rgba(201,210,220,0.35)'; c.lineWidth = 1.5;
      c.beginPath(); c.moveTo(57, 6); c.lineTo(57, TEX_H - 6); c.stroke();
      c.setLineDash([5, 5]); c.strokeStyle = 'rgba(200,176,138,0.48)';
      c.beginPath(); c.moveTo(49, 26); c.lineTo(49, TEX_H - 26); c.stroke();
      c.setLineDash([]);
      [54, TEX_H - 54].forEach(ry => {
        c.fillStyle = '#8F9AA8'; c.beginPath(); c.arc(28, ry, 4.5, 0, Math.PI * 2); c.fill();
        c.fillStyle = '#DCE4EE'; c.beginPath(); c.arc(26.8, ry - 1.2, 1.5, 0, Math.PI * 2); c.fill();
      });

      const gx = 29, gy = TEX_H * 0.48;
      const ringGrad = c.createRadialGradient(gx - 4, gy - 4, 2, gx, gy, 17);
      ringGrad.addColorStop(0, '#E3EBF4'); ringGrad.addColorStop(0.55, '#8A94A3'); ringGrad.addColorStop(1, '#363C4A');
      c.beginPath(); c.arc(gx, gy, 16, 0, Math.PI * 2); c.fillStyle = ringGrad; c.fill();
      c.beginPath(); c.arc(gx, gy, 9.5, 0, Math.PI * 2); c.fillStyle = '#07080D'; c.fill();

      c.fillStyle = '#6E5A4C'; c.font = '700 15px ' + SERIF;
      c.textAlign = 'center'; c.textBaseline = 'middle';
      c.fillText('✦   耻   辱   柱   示   众   ✦', 298, 66);

      const displayName = (item.name || '无名氏').trim();
      const maxNameW = 356;
      let fontSize = 90;
      while (fontSize > 30) {
        c.font = `900 ${fontSize}px ${SERIF}`;
        if (c.measureText(displayName).width <= maxNameW) break;
        fontSize -= 2;
      }
      c.fillStyle = 'rgba(255,255,255,0.45)'; c.fillText(displayName, 276, 160);
      c.fillStyle = '#12131C'; c.fillText(displayName, 275, 158);

      const stampText = STAMP_LABELS[item.kind] || '示众';
      c.save();
      c.translate(524, 146); c.rotate(0.08);
      c.strokeStyle = '#9E1E38'; c.lineWidth = 4; c.fillStyle = 'rgba(158,30,56,0.09)';
      c.beginPath(); c.roundRect(-36, -36, 72, 72, 8); c.fill(); c.stroke();
      c.strokeStyle = 'rgba(158,30,56,0.45)'; c.lineWidth = 1.2; c.strokeRect(-30, -30, 60, 60);
      c.fillStyle = '#9E1E38'; c.font = `900 ${stampText.length >= 3 ? 21 : 27}px ${SERIF}`;
      c.fillText(stampText, 0, 2);
      c.restore();

      c.fillStyle = '#4B3E36'; c.font = '700 17.5px ' + SANS;
      c.fillText(fitEllipsis(c, (item.display_reason || item.reason || '').trim(), 468), 328, 250);
      c.restore();

      c.strokeStyle = 'rgba(192,204,220,0.42)'; c.lineWidth = 2.4;
      flagPath(); c.stroke();
    }

    function resetCloth() {
      cloth.y.fill(0); cloth.vy.fill(0);
      cloth.dx.fill(0); cloth.vx.fill(0);
      cloth.tilt.fill(0); cloth.vtilt.fill(0);
    }

    function stepCloth(dt, t, nailed) {
      const step = 1 / COLS;
      const ny = new Float32Array(COLS + 1);
      const ndx = new Float32Array(COLS + 1);
      for (let c = 1; c <= COLS; c++) {
        const u = c * step;
        const leftY = cloth.y[c - 1], rightY = c < COLS ? cloth.y[c + 1] : cloth.y[c];
        const windTargetY = nailed
          ? (Math.sin(t * 3.8 - u * 4.5) * 9.0 + Math.cos(t * 6.5 - u * 7.2) * 3.0) * Math.pow(u, 0.85)
          : Math.sin(t * 4.8 - u * 3.8) * 6 * u;
        cloth.vy[c] += ((leftY + rightY - 2 * cloth.y[c]) * 310 + (windTargetY - cloth.y[c]) * 25 - cloth.vy[c] * 4.7) * dt;
        const maxAmpY = 32 * Math.pow(u, 0.7) + 4;
        ny[c] = Math.max(-maxAmpY, Math.min(maxAmpY, cloth.y[c] + cloth.vy[c] * dt));

        const leftX = cloth.dx[c - 1], rightX = c < COLS ? cloth.dx[c + 1] : cloth.dx[c];
        const windTargetX = nailed ? Math.sin(t * 3.8 - u * 4.5 + 0.6) * 3.2 * u : 0;
        cloth.vx[c] += ((leftX + rightX - 2 * cloth.dx[c]) * 250 + (windTargetX - cloth.dx[c]) * 36 - cloth.vx[c] * 6.0) * dt;
        ndx[c] = cloth.dx[c] + cloth.vx[c] * dt;

        const targetTilt = nailed ? Math.cos(t * 3.8 - u * 4.6) * 5.2 * u : 0;
        cloth.vtilt[c] += ((targetTilt - cloth.tilt[c]) * 34 - cloth.vtilt[c] * 5.4) * dt;
        cloth.tilt[c] = Math.max(-13, Math.min(13, cloth.tilt[c] + cloth.vtilt[c] * dt));
      }

      const restStep = cloth.flagW / COLS;
      const minDelta = restStep * 0.75, maxDelta = restStep * 1.11;
      let prevPos = 0;
      cloth.y[0] = 0; cloth.dx[0] = 0; cloth.tilt[0] = 0;
      for (let c = 1; c <= COLS; c++) {
        cloth.y[c] = ny[c];
        const clampedPos = Math.max(prevPos + minDelta, Math.min(prevPos + maxDelta, c * restStep + ndx[c]));
        cloth.dx[c] = clampedPos - c * restStep;
        prevPos = clampedPos;
      }
    }

    function applyClothImpulse(hitX, power = 1, arc = -1) {
      const restStep = cloth.flagW / COLS;
      const hitCol = Math.max(2, Math.min(COLS - 1, Math.round((hitX - cloth.originX) / restStep)));
      for (let c = 1; c <= COLS; c++) {
        const dist = Math.abs(c - hitCol);
        if (dist <= 7) {
          const w = Math.cos((dist / 8) * Math.PI * 0.5), u = c / COLS;
          cloth.vx[c] -= 170 * power * w * (0.45 + 0.55 * u);
          cloth.vy[c] += 210 * arc * power * w * (0.35 + 0.65 * u);
          cloth.vtilt[c] += 110 * -arc * power * w;
        }
      }
    }

    function colGeom(c, dropOffsetY) {
      const u = c / COLS;
      const xBase = cloth.originX + u * cloth.flagW + cloth.dx[c];
      const centerY = cloth.originY + dropOffsetY + cloth.y[c] + u * u * 6;
      return {
        topX: xBase - cloth.tilt[c] * 0.35, topY: centerY - cloth.tilt[c] * 0.25,
        botX: xBase + cloth.tilt[c] * 0.35, botY: centerY + cloth.flagH + cloth.tilt[c] * 0.25
      };
    }

    function spawnNailImpact(x, y) {
      for (let i = 0; i < 24; i++) {
        const ang = Math.random() * Math.PI * 2, spd = 130 + Math.random() * 310;
        particles.push({
          kind: 'wood', x, y, vx: Math.cos(ang) * spd, vy: Math.sin(ang) * spd - 85,
          rot: Math.random() * Math.PI * 2, vrot: (Math.random() - 0.5) * 18,
          w: 6 + Math.random() * 10, h: 2.5 + Math.random() * 3,
          color: i % 3 === 0 ? '#4B3C3A' : i % 3 === 1 ? '#292224' : '#7C6862',
          life: 0, maxLife: 0.45 + Math.random() * 0.42
        });
      }
      for (let i = 0; i < 20; i++) {
        const ang = (Math.random() - 0.5) * Math.PI * 1.4 - Math.PI * 0.15, spd = 210 + Math.random() * 390;
        particles.push({
          kind: 'spark', x, y, vx: Math.cos(ang) * spd, vy: Math.sin(ang) * spd - 75,
          size: 2.4 + Math.random() * 2.8,
          color: i % 3 === 0 ? '#E4F4FF' : i % 3 === 1 ? '#F0C98D' : '#E54465',
          life: 0, maxLife: 0.28 + Math.random() * 0.30
        });
      }
      rings.push({ x, y, r: 8, maxR: 112, color: '#D8EEFF', width: 5.2, life: 0, maxLife: 0.35 });
      rings.push({ x, y, r: 6, maxR: 74, color: '#C93250', width: 3.4, life: 0, maxLife: 0.29 });
    }

    function spawnWhipImpact(x, y, power = 1) {
      const count = Math.round(20 * power);
      for (let i = 0; i < count; i++) {
        const ang = Math.PI * 0.65 + (Math.random() - 0.5) * 1.9, spd = (170 + Math.random() * 350) * power;
        particles.push({
          kind: i % 3 === 0 ? 'thread' : 'spark',
          x: x + (Math.random() - 0.5) * 22, y: y + (Math.random() - 0.5) * 22,
          vx: Math.cos(ang) * spd, vy: Math.sin(ang) * spd - 55,
          rot: Math.random() * Math.PI, vrot: (Math.random() - 0.5) * 20,
          w: 7 + Math.random() * 9, h: 2, size: 2.4 + Math.random() * 2.9,
          color: i % 3 === 0 ? '#DDD5C4' : (i % 2 === 0 ? '#D8EEFF' : '#D43655'),
          life: 0, maxLife: 0.26 + Math.random() * 0.32
        });
      }
      rings.push({ x, y, r: 6, maxR: 84 * power, color: '#E4F4FF', width: 4.4, life: 0, maxLife: 0.24 });
      rings.push({ x, y, r: 10, maxR: 116 * power, color: '#B52442', width: 3.1, life: 0, maxLife: 0.31 });
      const words = ['啪！', '抽！', '罚！', '戒！'];
      state.stampPop = {
        text: words[state.localStrikes % words.length],
        x: x + (Math.random() - 0.5) * 26, y: y - 48 + (Math.random() - 0.5) * 14,
        rot: (Math.random() - 0.5) * 0.28, life: 0, maxLife: 0.52
      };
    }

    function drawTexturedTri(x0, y0, x1, y1, x2, y2, u0, v0, u1, v1, u2, v2) {
      const det = (u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0);
      if (Math.abs(det) < 1e-4) return;
      const cx = (x0 + x1 + x2) / 3, cy = (y0 + y1 + y2) / 3;
      const pad = (x, y) => {
        const dx = x - cx, dy = y - cy, len = Math.hypot(dx, dy) || 1;
        return [x + (dx / len) * 0.6, y + (dy / len) * 0.6];
      };
      const [px0, py0] = pad(x0, y0), [px1, py1] = pad(x1, y1), [px2, py2] = pad(x2, y2);
      ctx.save();
      ctx.beginPath(); ctx.moveTo(px0, py0); ctx.lineTo(px1, py1); ctx.lineTo(px2, py2); ctx.closePath(); ctx.clip();
      const a = ((x1 - x0) * (v2 - v0) - (x2 - x0) * (v1 - v0)) / det;
      const b = ((y1 - y0) * (v2 - v0) - (y2 - y0) * (v1 - v0)) / det;
      const c = ((x2 - x0) * (u1 - u0) - (x1 - x0) * (u2 - u0)) / det;
      const d = ((y2 - y0) * (u1 - u0) - (y1 - y0) * (u2 - u0)) / det;
      ctx.transform(a, b, c, d, x0 - a * u0 - c * v0, y0 - b * u0 - d * v0);
      ctx.drawImage(flagTex, 0, 0);
      ctx.restore();
    }

    function computeWhipPoints() {
      const N = 22, pts = [];
      const styles = [
        { tx: cloth.originX + cloth.flagW * 0.56, ty: cloth.originY + cloth.flagH * 0.50, arc: -1 },
        { tx: cloth.originX + cloth.flagW * 0.62, ty: cloth.originY + cloth.flagH * 0.36, arc: 1 },
        { tx: cloth.originX + cloth.flagW * 0.50, ty: cloth.originY + cloth.flagH * 0.62, arc: -1 }
      ];
      const st = styles[state.whipStyle % styles.length];
      const baseHX = canvasW * 0.91, baseHY = canvasH * 0.56;
      let hx = baseHX, hy = baseHY, tipX = canvasW * 0.79, tipY = canvasH * 0.74;
      let waveAmp = 14, wavePhase = state.totalTime * 2.4, curl = 0.2;

      if (state.whipState === 'idle') {
        hx = baseHX + Math.sin(state.totalTime * 1.8) * 4;
        hy = baseHY + Math.cos(state.totalTime * 1.5) * 4;
        tipX = baseHX - 65 + Math.sin(state.totalTime * 2.2) * 14;
        tipY = canvasH * 0.78 + Math.cos(state.totalTime * 2.0) * 8;
        waveAmp = 12;
      } else if (state.whipState === 'windup') {
        const k = Math.min(1, state.whipT), ease = 1 - Math.pow(1 - k, 2.5);
        hx = baseHX + ease * 28; hy = baseHY - ease * 62;
        tipX = baseHX + 45 + ease * 36; tipY = canvasH * 0.24 - ease * 42 * st.arc;
        waveAmp = 34 * ease; wavePhase = -k * 5.2; curl = 0.75 * ease;
      } else if (state.whipState === 'strike') {
        const k = Math.min(1, state.whipT);
        const swing = Math.min(1, k / 0.62), snapEase = swing < 1 ? Math.pow(swing, 2.6) : 1;
        hx = baseHX + 28 - snapEase * 96; hy = baseHY - 62 + snapEase * 72;
        const startTX = baseHX + 80, startTY = canvasH * 0.20;
        const p = Math.min(1, k / 0.64), pFast = Math.pow(p, 2.1);
        tipX = startTX + (st.tx - startTX) * pFast;
        tipY = startTY + (st.ty - startTY) * pFast + Math.sin(p * Math.PI) * (-78 * st.arc);
        if (k > 0.64) { const over = (k - 0.64) / 0.36; tipX -= over * 24; tipY += over * 20 * st.arc; }
        waveAmp = (1 - Math.abs(k - 0.55)) * 46; wavePhase = k * 9.5;
      } else if (state.whipState === 'recover') {
        const k = Math.min(1, state.whipT), ease = 1 - Math.pow(1 - k, 2.2);
        hx = (baseHX - 68) + 68 * ease; hy = (baseHY + 10) - 10 * ease;
        const fromX = st.tx - 24, fromY = st.ty + 20 * st.arc;
        tipX = fromX + (baseHX - 65 - fromX) * ease;
        tipY = fromY + (canvasH * 0.78 - fromY) * ease + Math.sin(ease * Math.PI) * 35;
        waveAmp = 24 * (1 - ease * 0.6); wavePhase = state.totalTime * 8;
      }

      const ctrlX = (hx + tipX) * 0.5 + (state.whipState === 'windup' ? 50 : -15);
      const ctrlY = (hy + tipY) * 0.5 + (state.whipState === 'strike' ? -58 * st.arc : 48);
      const dx = tipX - hx, dy = tipY - hy, len = Math.hypot(dx, dy) || 1;
      const nx = -dy / len, ny = dx / len;
      for (let i = 0; i <= N; i++) {
        const s = i / N, inv = 1 - s;
        let x = inv * inv * hx + 2 * inv * s * ctrlX + s * s * tipX;
        let y = inv * inv * hy + 2 * inv * s * ctrlY + s * s * tipY;
        const wave = Math.sin(s * 6.2 - wavePhase) * waveAmp * Math.sin(s * Math.PI);
        pts.push({ x: x + nx * wave, y: y + ny * wave + curl * Math.sin(s * Math.PI * 1.5) * 18 });
      }
      return { pts, target: st };
    }

    function drawSpirit(s) {
      const t = state.totalTime;
      ctx.save(); ctx.translate(s.x, s.y); ctx.scale(s.scale, s.scale); ctx.globalAlpha = s.alpha;
      const wave = Math.sin(t * 2.6 + s.phase) * 10, wave2 = Math.cos(t * 3.4 + s.phase) * 7;
      const grad = ctx.createLinearGradient(0, -34, 0, 56);
      grad.addColorStop(0, 'rgba(232,246,255,0.88)'); grad.addColorStop(0.45, 'rgba(176,208,232,0.42)'); grad.addColorStop(1, 'rgba(120,152,188,0)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.moveTo(0, -32);
      ctx.bezierCurveTo(18, -32, 24, -10, 20 + wave * 0.3, 12);
      ctx.bezierCurveTo(18 + wave * 0.6, 32, 24 + wave, 46, 12 + wave, 58);
      ctx.quadraticCurveTo(4 + wave2, 40, -2 + wave * 0.5, 56);
      ctx.quadraticCurveTo(-12 + wave2, 38, -20 + wave * 0.7, 52);
      ctx.bezierCurveTo(-24 + wave * 0.3, 28, -24, -10, -18, -26);
      ctx.bezierCurveTo(-12, -32, -5, -32, 0, -32);
      ctx.closePath(); ctx.fill();
      ctx.fillStyle = 'rgba(10,14,22,0.72)'; ctx.beginPath(); ctx.ellipse(0, -13, 8.5, 11, 0, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#E8F7FF';
      ctx.beginPath(); ctx.arc(-3.2, -14, 1.5, 0, Math.PI * 2); ctx.arc(3.2, -14, 1.5, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
    }

    function drawSkull(k) {
      const t = state.totalTime, r = k.r;
      ctx.save(); ctx.translate(k.x, k.y);
      ctx.rotate(k.tilt + Math.sin(t * k.speed * 0.8 + k.phase) * 0.08);
      ctx.globalAlpha = k.alpha;

      const halo = ctx.createRadialGradient(0, 0, r * 0.2, 0, 0, r * 1.9);
      halo.addColorStop(0, 'rgba(216,238,255,0.22)'); halo.addColorStop(1, 'rgba(216,238,255,0)');
      ctx.fillStyle = halo; ctx.beginPath(); ctx.arc(0, 0, r * 1.9, 0, Math.PI * 2); ctx.fill();

      const bone = ctx.createRadialGradient(-r * 0.25, -r * 0.35, r * 0.1, 0, 0, r * 1.25);
      bone.addColorStop(0, '#F3F5F8'); bone.addColorStop(0.55, '#C8CFD8'); bone.addColorStop(1, '#6C7585');
      ctx.fillStyle = bone; ctx.strokeStyle = 'rgba(15,18,26,0.78)'; ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(0, -r);
      ctx.bezierCurveTo(r * 0.92, -r, r * 1.02, -r * 0.15, r * 0.78, r * 0.28);
      ctx.quadraticCurveTo(r * 0.58, r * 0.42, r * 0.50, r * 0.68);
      ctx.lineTo(r * 0.42, r * 0.95); ctx.lineTo(-r * 0.42, r * 0.95); ctx.lineTo(-r * 0.50, r * 0.68);
      ctx.quadraticCurveTo(-r * 0.58, r * 0.42, -r * 0.78, r * 0.28);
      ctx.bezierCurveTo(-r * 1.02, -r * 0.15, -r * 0.92, -r, 0, -r);
      ctx.closePath(); ctx.fill(); ctx.stroke();

      ctx.strokeStyle = 'rgba(24,28,38,0.45)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(r * 0.28, -r * 0.84); ctx.lineTo(r * 0.16, -r * 0.56); ctx.lineTo(r * 0.24, -r * 0.42); ctx.stroke();

      ctx.fillStyle = '#0A0D14';
      ctx.beginPath(); ctx.ellipse(-r * 0.34, r * 0.04, r * 0.25, r * 0.22, -0.18, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.ellipse(r * 0.34, r * 0.04, r * 0.25, r * 0.22, 0.18, 0, Math.PI * 2); ctx.fill();

      const eyeGlow = 0.55 + Math.sin(t * 4.2 + k.phase) * 0.35;
      ctx.fillStyle = `rgba(210,240,255,${eyeGlow})`;
      ctx.beginPath(); ctx.arc(-r * 0.32, r * 0.05, r * 0.075, 0, Math.PI * 2); ctx.arc(r * 0.32, r * 0.05, r * 0.075, 0, Math.PI * 2); ctx.fill();

      ctx.fillStyle = '#0D1018';
      ctx.beginPath(); ctx.moveTo(0, r * 0.20); ctx.lineTo(r * 0.13, r * 0.48); ctx.lineTo(0, r * 0.43); ctx.lineTo(-r * 0.13, r * 0.48); ctx.closePath(); ctx.fill();

      ctx.strokeStyle = 'rgba(14,17,24,0.75)'; ctx.lineWidth = 1.2;
      [-0.24, -0.08, 0.08, 0.24].forEach(fx => {
        ctx.beginPath(); ctx.moveTo(fx * r, r * 0.66); ctx.lineTo(fx * r, r * 0.94); ctx.stroke();
      });
      ctx.restore();
    }

    function render() {
      const W = canvasW, H = canvasH, t = state.totalTime;
      const flicker = 0.92 + Math.sin(t * 13.7) * 0.04 + Math.cos(t * 21.3) * 0.04;
      ctx.save();
      ctx.clearRect(0, 0, W, H);
      ctx.translate(state.shakeX, state.shakeY);

      // 幽冥暗夜背景 + 远景哥特尖拱
      const bg = ctx.createRadialGradient(W * 0.44, H * 0.42, 20, W * 0.48, H * 0.52, W * 0.78);
      bg.addColorStop(0, '#1B212E'); bg.addColorStop(0.45, '#10131C'); bg.addColorStop(1, '#06070B');
      ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);

      ctx.save();
      ctx.strokeStyle = 'rgba(180,202,226,0.045)'; ctx.lineWidth = 1.5;
      const archW = W * 0.24;
      for (let i = 0; i < 4; i++) {
        const ax = W * (0.14 + i * 0.24), topA = H * 0.07, botA = H * 0.83;
        ctx.beginPath(); ctx.moveTo(ax - archW * 0.42, botA); ctx.lineTo(ax - archW * 0.42, topA + 65);
        ctx.quadraticCurveTo(ax - archW * 0.42, topA + 16, ax, topA);
        ctx.quadraticCurveTo(ax + archW * 0.42, topA + 16, ax + archW * 0.42, topA + 65);
        ctx.lineTo(ax + archW * 0.42, botA); ctx.stroke();
      }
      ctx.restore();

      // 幽白色双火把
      getTorches().forEach((tc, idx) => {
        const fl = flicker + Math.sin(t * 9.5 + idx * 2.7) * 0.05;
        const fx = tc.x, fy = tc.y - 22;
        ctx.save();
        const glow = ctx.createRadialGradient(fx, fy - 12, 4, fx, fy - 8, 170 * tc.scale * fl);
        glow.addColorStop(0, 'rgba(242,251,255,0.42)'); glow.addColorStop(0.24, 'rgba(195,228,248,0.18)');
        glow.addColorStop(0.6, 'rgba(128,166,204,0.06)'); glow.addColorStop(1, 'rgba(10,14,22,0)');
        ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(fx, fy - 8, 170 * tc.scale * fl, 0, Math.PI * 2); ctx.fill();

        ctx.strokeStyle = '#3B4254'; ctx.lineWidth = 3;
        ctx.beginPath(); ctx.moveTo(fx, fy + 8); ctx.lineTo(fx, fy + 62);
        ctx.moveTo(fx - 12, fy + 26); ctx.quadraticCurveTo(fx, fy + 42, fx + 12, fy + 26); ctx.stroke();

        const cupGrad = ctx.createLinearGradient(fx - 14, fy, fx + 14, fy);
        cupGrad.addColorStop(0, '#1E222E'); cupGrad.addColorStop(0.45, '#596277'); cupGrad.addColorStop(1, '#1A1E28');
        ctx.fillStyle = cupGrad;
        ctx.beginPath(); ctx.moveTo(fx - 14, fy - 2); ctx.lineTo(fx + 14, fy - 2);
        ctx.lineTo(fx + 8, fy + 15); ctx.lineTo(fx - 8, fy + 15); ctx.closePath(); ctx.fill();
        ctx.strokeStyle = 'rgba(205,224,242,0.35)'; ctx.lineWidth = 1.2; ctx.stroke();

        const sway = Math.sin(t * 7.2 + idx * 1.9) * 5, sway2 = Math.cos(t * 11.4 + idx) * 4;
        const drawFlame = (w, h, color, ox, alpha) => {
          ctx.save(); ctx.globalAlpha = alpha; ctx.fillStyle = color;
          ctx.beginPath(); ctx.moveTo(fx - w, fy - 1);
          ctx.bezierCurveTo(fx - w * 1.15, fy - h * 0.45, fx + ox * 0.6 - w * 0.3, fy - h * 0.85, fx + ox, fy - h);
          ctx.bezierCurveTo(fx + ox * 0.6 + w * 0.3, fy - h * 0.85, fx + w * 1.15, fy - h * 0.45, fx + w, fy - 1);
          ctx.closePath(); ctx.fill(); ctx.restore();
        };
        drawFlame(13, 55 * fl, '#8DBCE0', sway, 0.38);
        drawFlame(10, 44 * fl, '#D6EEFF', sway * 0.7 + sway2 * 0.3, 0.72);
        drawFlame(6, 28 * fl, '#FFFFFF', sway2 * 0.4, 0.96);
        ctx.restore();
      });

      for (const p of torchSparks) {
        const k = p.life / p.maxLife;
        ctx.save(); ctx.globalAlpha = (1 - k) * 0.85;
        ctx.fillStyle = k < 0.4 ? '#FFFFFF' : '#BCE2FA';
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r * (1 - k * 0.5), 0, Math.PI * 2); ctx.fill(); ctx.restore();
      }

      // 地面祭坛面
      const floorY = H * 0.84;
      const floorGrad = ctx.createLinearGradient(0, floorY, 0, H);
      floorGrad.addColorStop(0, '#0C0F16'); floorGrad.addColorStop(1, '#040508');
      ctx.fillStyle = floorGrad; ctx.fillRect(0, floorY, W, H - floorY);
      ctx.strokeStyle = 'rgba(195,220,242,0.16)'; ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.moveTo(28, floorY); ctx.lineTo(W - 28, floorY); ctx.stroke();

      // 浮空幽灵与雕版骷髅
      spirits.forEach(drawSpirit);
      skulls.forEach(drawSkull);

      // 精致黑檀银纹耻辱柱
      const px = W * 0.22, pw = Math.max(54, Math.min(70, W * 0.08)), topY = H * 0.13, botY = floorY;
      ctx.fillStyle = 'rgba(0,0,0,0.68)';
      ctx.beginPath(); ctx.ellipse(px, botY + 13, pw * 1.48, 17, 0, 0, Math.PI * 2); ctx.fill();

      const baseGrad = ctx.createLinearGradient(px - pw, botY - 28, px + pw, botY + 14);
      baseGrad.addColorStop(0, '#3C4352'); baseGrad.addColorStop(0.45, '#252A36'); baseGrad.addColorStop(1, '#12151D');
      ctx.fillStyle = baseGrad;
      ctx.beginPath();
      ctx.moveTo(px - pw * 0.74, botY - 24); ctx.lineTo(px + pw * 0.74, botY - 24);
      ctx.lineTo(px + pw * 0.9, botY - 8); ctx.lineTo(px + pw * 1.08, botY + 14);
      ctx.lineTo(px - pw * 1.08, botY + 14); ctx.lineTo(px - pw * 0.9, botY - 8);
      ctx.closePath(); ctx.fill(); ctx.strokeStyle = 'rgba(205,224,242,0.22)'; ctx.lineWidth = 1.4; ctx.stroke();

      const wood = ctx.createLinearGradient(px - pw / 2, 0, px + pw / 2, 0);
      wood.addColorStop(0, '#2B313E'); wood.addColorStop(0.14, '#1D181A'); wood.addColorStop(0.44, '#362B2A');
      wood.addColorStop(0.76, '#1B1618'); wood.addColorStop(0.92, '#131319'); wood.addColorStop(1, '#293242');
      ctx.fillStyle = wood;
      ctx.beginPath(); ctx.roundRect(px - pw / 2, topY, pw, botY - topY - 20, [8, 8, 2, 2]); ctx.fill();
      ctx.strokeStyle = 'rgba(205,222,240,0.18)'; ctx.lineWidth = 1.2; ctx.stroke();

      ctx.strokeStyle = 'rgba(6,7,10,0.58)'; ctx.lineWidth = 1.5;
      [-0.3, -0.14, 0.06, 0.22, 0.35].forEach((f, i) => {
        const ox = f * pw;
        ctx.beginPath(); ctx.moveTo(px + ox, topY + 24 + i * 7);
        ctx.bezierCurveTo(px + ox + 2, H * 0.36, px + ox - 2, H * 0.62, px + ox + 1, botY - 28); ctx.stroke();
      });

      ctx.fillStyle = '#2A303E'; ctx.strokeStyle = 'rgba(212,226,242,0.4)'; ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.moveTo(px, topY - 30); ctx.quadraticCurveTo(px + 9, topY - 14, px + 16, topY - 8);
      ctx.lineTo(px - 16, topY - 8); ctx.quadraticCurveTo(px - 9, topY - 14, px, topY - 30); ctx.closePath(); ctx.fill(); ctx.stroke();

      [topY + 44, botY - 68].forEach((by, idx) => {
        const band = ctx.createLinearGradient(px - pw / 2 - 5, by, px + pw / 2 + 5, by);
        band.addColorStop(0, '#3C4456'); band.addColorStop(0.28, '#7A859A');
        band.addColorStop(0.55, '#3E4556'); band.addColorStop(0.85, '#1D212C'); band.addColorStop(1, '#3D475B');
        ctx.fillStyle = band;
        ctx.beginPath(); ctx.roundRect(px - pw / 2 - 5, by, pw + 10, 18, 4); ctx.fill();
        ctx.strokeStyle = 'rgba(216,232,248,0.34)'; ctx.lineWidth = 1.2; ctx.stroke();

        ctx.strokeStyle = 'rgba(232,242,252,0.36)'; ctx.lineWidth = 1;
        ctx.beginPath();
        for (let x = px - pw / 2 + 2; x <= px + pw / 2 - 2; x += 10) {
          ctx.moveTo(x - 4, by + 9); ctx.lineTo(x, by + 4.5); ctx.lineTo(x + 4, by + 9); ctx.lineTo(x, by + 13.5); ctx.closePath();
        }
        ctx.stroke();

        [-0.36, 0, 0.36].forEach(rf => {
          ctx.fillStyle = '#C9D5E4'; ctx.beginPath(); ctx.arc(px + rf * pw, by + 9, 2.8, 0, Math.PI * 2); ctx.fill();
        });
        if (idx === 1) {
          const sway = Math.sin(t * 1.9) * 3.2;
          ctx.strokeStyle = '#6D778A'; ctx.lineWidth = 2.4;
          for (let k = 0; k < 4; k++) {
            ctx.beginPath(); ctx.ellipse(px - pw / 2 - 5 + sway * (k * 0.25), by + 20 + k * 9.5, 3.5, 5.8, 0.1 * k, 0, Math.PI * 2); ctx.stroke();
          }
        }
      });

      const plW = Math.max(92, pw * 1.62), plH = 34, plY = topY - 10;
      ctx.fillStyle = '#141722'; ctx.strokeStyle = '#9E1E38'; ctx.lineWidth = 2.2;
      ctx.beginPath(); ctx.roundRect(px - plW / 2, plY, plW, plH, 7); ctx.fill(); ctx.stroke();
      ctx.strokeStyle = 'rgba(205,220,238,0.45)'; ctx.lineWidth = 1;
      ctx.strokeRect(px - plW / 2 + 4, plY + 4, plW - 8, plH - 8);
      ctx.fillStyle = '#EFE9DD'; ctx.font = '900 16px ' + SERIF;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('耻 辱 柱', px, plY + plH / 2 + 1);

      if (state.pillarCrack > 0) {
        const nx = px + pw * 0.2, ny = cloth.originY + cloth.flagH * 0.48;
        ctx.save(); ctx.globalAlpha = Math.min(1, state.pillarCrack);
        [[[-4, -4], [-20, -24]], [[2, -5], [14, -26]], [[-5, 6], [-22, 22]], [[4, 7], [15, 25]], [[-6, 0], [-25, 3]]].forEach(([a, b]) => {
          ctx.strokeStyle = 'rgba(207,232,250,0.28)'; ctx.lineWidth = 3.2;
          ctx.beginPath(); ctx.moveTo(nx + a[0], ny + a[1]); ctx.lineTo(nx + b[0], ny + b[1]); ctx.stroke();
          ctx.strokeStyle = '#07080B'; ctx.lineWidth = 1.9;
          ctx.beginPath(); ctx.moveTo(nx + a[0], ny + a[1]); ctx.lineTo(nx + b[0], ny + b[1]); ctx.stroke();
        });
        ctx.restore();
      }

      // 高质感旗帜布面
      const dropY = state.phase === 'drop' ? state.flagDropY : 0;
      const restStep = cloth.flagW / COLS;
      for (let c = 0; c < COLS; c++) {
        const L = colGeom(c, dropY), R = colGeom(c + 1, dropY);
        const u0 = (c / COLS) * TEX_W, u1 = ((c + 1) / COLS) * TEX_W;
        drawTexturedTri(L.topX, L.topY, R.topX, R.topY, L.botX, L.botY, u0, 0, u1, 0, u0, TEX_H);
        drawTexturedTri(R.topX, R.topY, R.botX, R.botY, L.botX, L.botY, u1, 0, u1, TEX_H, u0, TEX_H);
        const shadeVal = ((R.topY - L.topY) / restStep) * 0.25 + (1 - (R.topX - L.topX) / restStep) * 0.42;
        if (Math.abs(shadeVal) > 0.025) {
          ctx.save();
          ctx.beginPath(); ctx.moveTo(L.topX, L.topY); ctx.lineTo(R.topX, R.topY);
          ctx.lineTo(R.botX, R.botY); ctx.lineTo(L.botX, L.botY); ctx.closePath();
          const alpha = Math.min(0.28, Math.abs(shadeVal));
          ctx.fillStyle = shadeVal > 0 ? `rgba(6,8,14,${alpha})` : `rgba(224,242,255,${alpha * 0.55})`;
          ctx.fill(); ctx.restore();
        }
      }

      // 棱面雕花锻铁巨钉
      if (state.phase !== 'drop') {
        const targetX = cloth.originX + 18, targetY = cloth.originY + cloth.flagH * 0.48;
        const angle = -0.35;
        const travel = (1 - state.nailProgress) * 160 + state.nailRecoil * 8;
        const tipX = targetX + Math.cos(angle) * travel, tipY = targetY + Math.sin(angle) * travel;
        const fullShaft = 112;
        const visShaft = state.nailProgress > 0.72 ? fullShaft - (state.nailProgress - 0.72) / 0.28 * 80 : fullShaft;
        ctx.save(); ctx.translate(tipX, tipY); ctx.rotate(angle);
        if (state.nailProgress > 0.78) {
          ctx.fillStyle = 'rgba(0,0,0,0.58)'; ctx.beginPath(); ctx.ellipse(-2, 7, 16, 7.5, 0.2, 0, Math.PI * 2); ctx.fill();
        }
        const topF = ctx.createLinearGradient(0, -10, 0, 0);
        topF.addColorStop(0, '#E9F1FA'); topF.addColorStop(0.55, '#9AA6B8'); topF.addColorStop(1, '#586174');
        ctx.fillStyle = topF;
        ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.min(18, visShaft), -9); ctx.lineTo(visShaft, -11); ctx.lineTo(visShaft, 0); ctx.closePath(); ctx.fill();
        const botF = ctx.createLinearGradient(0, 0, 0, 10);
        botF.addColorStop(0, '#3C4354'); botF.addColorStop(0.65, '#1D202C'); botF.addColorStop(1, '#0D0F16');
        ctx.fillStyle = botF;
        ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(visShaft, 0); ctx.lineTo(visShaft, 11); ctx.lineTo(Math.min(18, visShaft), 9); ctx.closePath(); ctx.fill();
        ctx.strokeStyle = '#0B0C12'; ctx.lineWidth = 1.6;
        ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.min(18, visShaft), -9); ctx.lineTo(visShaft, -11); ctx.lineTo(visShaft, 11); ctx.lineTo(Math.min(18, visShaft), 9); ctx.closePath(); ctx.stroke();
        ctx.strokeStyle = 'rgba(240,248,255,0.68)'; ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.moveTo(4, 0); ctx.lineTo(visShaft - 2, 0); ctx.stroke();

        if (visShaft > 26) {
          ctx.strokeStyle = 'rgba(218,196,158,0.62)'; ctx.lineWidth = 1.1;
          for (let x = 20; x < visShaft - 10; x += 14) {
            ctx.beginPath(); ctx.moveTo(x - 4.5, -4.5); ctx.lineTo(x, -7); ctx.lineTo(x + 4.5, -4.5); ctx.lineTo(x, -2); ctx.closePath(); ctx.stroke();
          }
        }
        ctx.fillStyle = '#7C879B'; ctx.strokeStyle = '#12151E'; ctx.lineWidth = 1.4;
        ctx.beginPath(); ctx.roundRect(visShaft - 6, -14, 7, 28, 2); ctx.fill(); ctx.stroke();

        const hg = ctx.createLinearGradient(visShaft, -24, visShaft + 20, 24);
        hg.addColorStop(0, '#F1F6FC'); hg.addColorStop(0.28, '#9DA8BA'); hg.addColorStop(0.68, '#41485A'); hg.addColorStop(1, '#191C26');
        ctx.fillStyle = hg;
        ctx.beginPath(); ctx.roundRect(visShaft, -24, 19, 48, 6); ctx.fill();
        ctx.strokeStyle = '#0C0E15'; ctx.lineWidth = 1.8; ctx.stroke();
        ctx.strokeStyle = 'rgba(235,244,255,0.45)'; ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.moveTo(visShaft + 5.5, -21); ctx.lineTo(visShaft + 5.5, 21); ctx.stroke();
        ctx.strokeStyle = 'rgba(208,184,142,0.75)'; ctx.lineWidth = 1.4;
        ctx.beginPath(); ctx.moveTo(visShaft + 12, -19); ctx.lineTo(visShaft + 12, 19); ctx.stroke();
        [-13, 0, 13].forEach(ry => { ctx.fillStyle = '#E8EEF5'; ctx.beginPath(); ctx.arc(visShaft + 12, ry, 2.1, 0, Math.PI * 2); ctx.fill(); });

        if (state.phase === 'nail_aim') {
          const glint = Math.sin(Math.min(1, state.phaseTime / 0.26) * Math.PI);
          ctx.save(); ctx.translate(visShaft + 9, -14); ctx.fillStyle = `rgba(226,244,255,${glint})`;
          const s = 28 * glint;
          ctx.beginPath(); ctx.moveTo(0, -s); ctx.lineTo(3, -3); ctx.lineTo(s, 0); ctx.lineTo(3, 3);
          ctx.lineTo(0, s); ctx.lineTo(-3, 3); ctx.lineTo(-s, 0); ctx.lineTo(-3, -3); ctx.closePath(); ctx.fill(); ctx.restore();
        }
        ctx.restore();
      }

      // 暗黑雕银皮鞭
      if (state.phase === 'whipping' && motionEnabled()) {
        const { pts } = computeWhipPoints();
        const tip = pts[pts.length - 1];
        if (state.whipState === 'strike') whipTrail.push({ x: tip.x, y: tip.y, life: 0 });
        if (whipTrail.length > 2) {
          ctx.save();
          for (let i = 1; i < whipTrail.length; i++) {
            const a = whipTrail[i - 1], b = whipTrail[i], alpha = Math.max(0, 1 - b.life / 0.16) * 0.76;
            ctx.strokeStyle = `rgba(184,32,62,${alpha})`; ctx.lineWidth = (i / whipTrail.length) * 12; ctx.lineCap = 'round';
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
            ctx.strokeStyle = `rgba(226,244,255,${alpha * 0.88})`; ctx.lineWidth = (i / whipTrail.length) * 3.6;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
          ctx.restore();
        }
        ctx.save(); ctx.lineCap = 'round'; ctx.lineJoin = 'round';
        for (let i = 0; i < pts.length - 1; i++) {
          const s = i / (pts.length - 1);
          ctx.strokeStyle = '#050609'; ctx.lineWidth = (1 - s) * 9.5 + 5;
          ctx.beginPath(); ctx.moveTo(pts[i].x, pts[i].y); ctx.lineTo(pts[i + 1].x, pts[i + 1].y); ctx.stroke();
        }
        for (let i = 0; i < pts.length - 1; i++) {
          const s = i / (pts.length - 1);
          ctx.strokeStyle = s > 0.84 ? '#C93250' : (i % 2 === 0 ? '#3E363B' : '#262126');
          ctx.lineWidth = (1 - s) * 8.5 + 1.8;
          ctx.beginPath(); ctx.moveTo(pts[i].x, pts[i].y); ctx.lineTo(pts[i + 1].x, pts[i + 1].y); ctx.stroke();
        }
        const p0 = pts[0], p2 = pts[2], hAng = Math.atan2(p2.y - p0.y, p2.x - p0.x);
        ctx.save(); ctx.translate(p0.x, p0.y); ctx.rotate(hAng + Math.PI);
        ctx.fillStyle = '#191B24'; ctx.strokeStyle = '#B8C4D4'; ctx.lineWidth = 1.8;
        ctx.beginPath(); ctx.roundRect(-8, -7, 45, 14, 6); ctx.fill(); ctx.stroke();
        ctx.strokeStyle = '#737E90'; ctx.lineWidth = 2;
        for (let x = 2; x <= 26; x += 7) { ctx.beginPath(); ctx.moveTo(x, -6); ctx.lineTo(x + 4, 6); ctx.stroke(); }
        ctx.fillStyle = '#CFD9E6'; ctx.beginPath(); ctx.arc(37, 0, 6.5, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = '#9E1E38'; ctx.beginPath(); ctx.arc(37, 0, 2.6, 0, Math.PI * 2); ctx.fill();
        ctx.restore();

        if (state.whipState === 'strike' && state.whipT > 0.56 && state.whipT < 0.82) {
          const k = 1 - Math.abs(state.whipT - 0.66) / 0.16;
          if (k > 0) {
            ctx.save(); ctx.translate(tip.x, tip.y); ctx.rotate(t * 6);
            const rOut = 42 * k * state.whipPower, rIn = 9 * k;
            ctx.fillStyle = '#EDF7FF'; ctx.strokeStyle = '#C93250'; ctx.lineWidth = 2.4;
            ctx.beginPath();
            for (let i = 0; i < 8; i++) {
              const a = (i * Math.PI) / 4, r = i % 2 === 0 ? rOut : rIn;
              if (i === 0) ctx.moveTo(Math.cos(a) * r, Math.sin(a) * r); else ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r);
            }
            ctx.closePath(); ctx.fill(); ctx.stroke(); ctx.restore();
          }
        }
        ctx.restore();
      }

      // 冷雾与飘浮灰烬
      for (const m of mistBands) {
        const cy = H * m.yFactor;
        const g = ctx.createRadialGradient(m.x, cy, 10, m.x, cy, m.w * 0.55);
        g.addColorStop(0, `rgba(196,222,244,${m.alpha})`); g.addColorStop(1, 'rgba(196,222,244,0)');
        ctx.fillStyle = g; ctx.beginPath(); ctx.ellipse(m.x, cy, m.w * 0.55, m.h, 0, 0, Math.PI * 2); ctx.fill();
      }
      for (const a of ashes) {
        ctx.fillStyle = `rgba(224,238,250,${a.alpha})`; ctx.beginPath(); ctx.arc(a.x, a.y, a.r, 0, Math.PI * 2); ctx.fill();
      }

      // 粒子、拟声字与濒死暗角视野
      for (const r of rings) {
        const k = r.life / r.maxLife, curR = r.r + (r.maxR - r.r) * (1 - Math.pow(1 - k, 2.5));
        ctx.save(); ctx.globalAlpha = (1 - k) * 0.85; ctx.strokeStyle = r.color; ctx.lineWidth = r.width * (1 - k * 0.7);
        ctx.beginPath(); ctx.arc(r.x, r.y, curR, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
      }
      for (const p of particles) {
        const alpha = Math.max(0, 1 - p.life / p.maxLife);
        ctx.save(); ctx.globalAlpha = alpha;
        if (p.kind === 'spark') {
          ctx.fillStyle = p.color; ctx.beginPath(); ctx.arc(p.x, p.y, p.size * (0.4 + alpha * 0.6), 0, Math.PI * 2); ctx.fill();
        } else {
          ctx.translate(p.x, p.y); ctx.rotate(p.rot); ctx.fillStyle = p.color; ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
        }
        ctx.restore();
      }
      if (state.stampPop) {
        const sp = state.stampPop, k = sp.life / sp.maxLife;
        const scale = k < 0.18 ? 0.5 + (k / 0.18) * 0.7 : (k < 0.3 ? 1.2 - ((k - 0.18) / 0.12) * 0.2 : 1);
        const alpha = k < 0.65 ? 1 : 1 - (k - 0.65) / 0.35;
        ctx.save(); ctx.translate(sp.x, sp.y - k * 18); ctx.rotate(sp.rot); ctx.scale(scale, scale);
        ctx.globalAlpha = alpha; ctx.fillStyle = '#C93250'; ctx.strokeStyle = '#E8F4FF'; ctx.lineWidth = 3.5;
        ctx.font = '900 30px ' + SERIF; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.strokeText(sp.text, 0, 0); ctx.fillText(sp.text, 0, 0); ctx.restore();
      }

      const breath = 0.58 + Math.sin(t * 1.45) * 0.08;
      const vig = ctx.createRadialGradient(W * 0.48, H * 0.48, W * 0.22, W * 0.5, H * 0.5, W * 0.66);
      vig.addColorStop(0, 'rgba(0,0,0,0)');
      vig.addColorStop(0.72, `rgba(6,8,14,${breath * 0.45})`);
      vig.addColorStop(1, `rgba(3,4,8,${breath * 0.92})`);
      ctx.fillStyle = vig; ctx.fillRect(0, 0, W, H);

      if (state.dyingPulse > 0.01) {
        const pv = ctx.createRadialGradient(W * 0.5, H * 0.5, W * 0.28, W * 0.5, H * 0.5, W * 0.65);
        pv.addColorStop(0, 'rgba(130,18,40,0)'); pv.addColorStop(1, `rgba(145,20,44,${state.dyingPulse * 0.46})`);
        ctx.fillStyle = pv; ctx.fillRect(0, 0, W, H);
      }
      if (state.flashAlpha > 0.01) {
        ctx.fillStyle = `rgba(220,242,255,${state.flashAlpha})`; ctx.fillRect(0, 0, W, H);
      }
      ctx.restore();
    }

    function triggerWhip(power = 1) {
      if (state.phase !== 'whipping') return;
      state.whipState = 'windup'; state.whipT = 0; state.whipHitDone = false;
      state.whipPower = power; state.whipStyle = (state.whipStyle + 1) % 3; state.whipTimer = 0;
    }

    function update(dt) {
      state.totalTime += dt;
      const t = state.totalTime;
      for (const s of spirits) {
        s.x += s.vx * dt; if (s.x > canvasW + 90) s.x = -90; if (s.x < -90) s.x = canvasW + 90;
        s.y = s.ry * canvasH + Math.sin(t * s.speed + s.phase) * 16;
      }
      for (const k of skulls) {
        k.x += k.vx * dt; if (k.x > canvasW + 70) k.x = -70; if (k.x < -70) k.x = canvasW + 70;
        k.y = k.ry * canvasH + Math.sin(t * k.speed + k.phase) * 13;
      }
      for (const a of ashes) {
        a.x += (a.vx + Math.sin(t * 1.4 + a.phase) * 7) * dt; a.y += a.vy * dt;
        if (a.y < -10) { a.y = canvasH + 10; a.x = Math.random() * canvasW; }
        if (a.x < -10) a.x = canvasW + 10;
      }
      for (const m of mistBands) {
        m.x += m.vx * dt; if (m.x > canvasW + m.w) m.x = -m.w; if (m.x < -m.w) m.x = canvasW + m.w;
      }
      if (Math.random() < 0.45) {
        const tc = getTorches()[Math.random() < 0.5 ? 0 : 1];
        torchSparks.push({
          x: tc.x + (Math.random() - 0.5) * 12, y: tc.y - 24 + (Math.random() - 0.5) * 8,
          vx: (Math.random() - 0.5) * 16, vy: -30 - Math.random() * 40,
          r: 1.1 + Math.random() * 1.7, life: 0, maxLife: 0.7 + Math.random() * 0.75
        });
      }
      for (let i = torchSparks.length - 1; i >= 0; i--) {
        const p = torchSparks[i]; p.life += dt;
        if (p.life >= p.maxLife) { torchSparks.splice(i, 1); continue; }
        p.x += (p.vx + Math.sin(t * 5 + i) * 9) * dt; p.y += p.vy * dt;
      }

      if (state.hitstopLeft > 0) {
        state.hitstopLeft -= dt;
        state.shakeX = (Math.random() - 0.5) * 2 * state.shakeMag;
        state.shakeY = (Math.random() - 0.5) * 2 * state.shakeMag;
        return;
      }
      state.phaseTime += dt;
      state.flashAlpha *= Math.pow(0.02, dt);
      state.dyingPulse *= Math.pow(0.04, dt);
      state.nailRecoil *= Math.pow(0.001, dt);
      if (state.shakeMag > 0.1) {
        state.shakeMag *= Math.pow(0.0015, dt);
        state.shakeX = (Math.random() - 0.5) * 2 * state.shakeMag;
        state.shakeY = (Math.random() - 0.5) * 2 * state.shakeMag;
      } else { state.shakeMag = 0; state.shakeX = 0; state.shakeY = 0; }

      if (state.phase === 'drop') {
        const k = Math.min(1, state.phaseTime / 0.38);
        state.flagDropY = -116 * (1 - (1 - Math.pow(1 - k, 3)));
        stepCloth(dt, t, false);
        if (k >= 1) { state.flagDropY = 0; state.phase = 'nail_aim'; state.phaseTime = 0; }
      } else if (state.phase === 'nail_aim') {
        stepCloth(dt, t, false);
        if (state.phaseTime >= 0.30) { state.phase = 'nail_slam'; state.phaseTime = 0; }
      } else if (state.phase === 'nail_slam') {
        const k = Math.min(1, state.phaseTime / 0.14);
        state.nailProgress = Math.pow(k, 2.8);
        stepCloth(dt, t, k > 0.7);
        if (k >= 1) {
          state.nailProgress = 1; state.nailRecoil = 1; state.pillarCrack = 1;
          state.hitstopLeft = 0.072; state.shakeMag = 6.8; state.flashAlpha = 0.21; state.dyingPulse = 1.0;
          const ix = cloth.originX + 18, iy = cloth.originY + cloth.flagH * 0.48;
          spawnNailImpact(ix, iy);
          applyClothImpulse(ix + 35, 0.72, 1);
          if (state.loud) sfxNailSlam();
          state.phase = 'whipping'; state.phaseTime = 0; state.whipTimer = 0.48;
        }
      } else if (state.phase === 'whipping') {
        stepCloth(dt, t, true);
        if (state.whipState === 'idle') {
          state.whipTimer -= dt;
          if (state.whipTimer <= 0 && state.autoLeft > 0) { state.autoLeft -= 1; state.loud = false; triggerWhip(1); }
        } else if (state.whipState === 'windup') {
          state.whipT += dt / 0.30;
          if (state.whipT >= 1) { state.whipState = 'strike'; state.whipT = 0; if (state.loud) sfxWhipWhoosh(); }
        } else if (state.whipState === 'strike') {
          state.whipT += dt / 0.22;
          if (!state.whipHitDone && state.whipT >= 0.62) {
            state.whipHitDone = true;
            state.localStrikes += 1;
            const { target } = computeWhipPoints();
            const pwr = state.whipPower;
            applyClothImpulse(target.tx, pwr, target.arc);
            spawnWhipImpact(target.tx, target.ty, pwr);
            if (state.loud) sfxWhipCrack(pwr);
            state.shakeMag = Math.max(state.shakeMag, 3.3 * pwr);
            state.flashAlpha = Math.max(state.flashAlpha, 0.08 * pwr);
            state.dyingPulse = Math.max(state.dyingPulse, 0.62 * pwr);
          }
          if (state.whipT >= 1) { state.whipState = 'recover'; state.whipT = 0; }
        } else if (state.whipState === 'recover') {
          state.whipT += dt / 0.32;
          if (state.whipT >= 1) { state.whipState = 'idle'; state.whipT = 0; state.whipTimer = 1.02; }
        }
      }

      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i]; p.life += dt;
        if (p.life >= p.maxLife) { particles.splice(i, 1); continue; }
        p.vy += (p.kind === 'thread' ? 230 : 760) * dt; p.vx *= 0.97;
        p.x += p.vx * dt; p.y += p.vy * dt;
        if (p.rot !== undefined) p.rot += p.vrot * dt;
      }
      for (let i = rings.length - 1; i >= 0; i--) {
        rings[i].life += dt; if (rings[i].life >= rings[i].maxLife) rings.splice(i, 1);
      }
      for (let i = whipTrail.length - 1; i >= 0; i--) {
        whipTrail[i].life += dt; if (whipTrail[i].life > 0.16) whipTrail.splice(i, 1);
      }
      if (state.stampPop) {
        state.stampPop.life += dt; if (state.stampPop.life >= state.stampPop.maxLife) state.stampPop = null;
      }
    }

    function resize() {
      const rect = wrap.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvasW = Math.max(300, Math.round(rect.width));
      canvasH = Math.max(240, Math.round(rect.height));
      canvas.width = canvasW * dpr; canvas.height = canvasH * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      cloth.flagW = Math.min(430, Math.max(185, canvasW * 0.44));
      cloth.flagH = cloth.flagW * (TEX_H / TEX_W);
      cloth.originX = canvasW * 0.22 + 8;
      cloth.originY = canvasH * 0.25;
      spirits.forEach(s => { s.x = s.rx * canvasW; s.y = s.ry * canvasH; });
      skulls.forEach(k => { k.x = k.rx * canvasW; k.y = k.ry * canvasH; });
      if (!rafId) render();
    }

    function syncUI() {
      const item = current();
      if (countEl) countEl.textContent = String(item.lashes);
      if (kindEl) {
        kindEl.textContent = item.kind_label;
        kindEl.className = 'shame-kind' + (item.kind === 'overdue' ? '' : ' ' + item.kind);
      }
      if (reasonEl) {
        reasonEl.textContent = item.has_custom_reason ? `「${item.display_reason}」` : item.display_reason;
      }
      if (metaEl) metaEl.textContent = `由 ${item.by} 钉上耻辱柱 · ${item.time}`;
      if (taskLinkEl && item.task_url) {
        taskLinkEl.href = item.task_url;
        taskLinkEl.textContent = `任务：${item.task_title}`;
      }
      tabs.forEach((btn, idx) => btn.classList.toggle('active', idx === activeIdx));
      liftForms.forEach(form => { form.hidden = Number(form.dataset.shameLiftForm) !== activeIdx; });
      rebuildFlagTexture();
    }

    function startSequence(skipIntro = false) {
      particles.length = 0; rings.length = 0; whipTrail.length = 0;
      state.stampPop = null; state.shakeMag = 0; state.flashAlpha = 0; state.dyingPulse = 0;
      state.hitstopLeft = 0; state.nailRecoil = 0;
      state.whipState = 'idle'; state.whipT = 0; state.whipTimer = 0.24;
      state.autoLeft = skipIntro ? 0 : AUTO_LASHES; state.loud = false; state.restTime = 0;
      resetCloth();
      if (skipIntro || !motionEnabled()) {
        state.phase = 'whipping'; state.phaseTime = 0;
        state.nailProgress = 1; state.pillarCrack = 1; state.flagDropY = 0;
        for (let i = 0; i < 16; i++) stepCloth(1 / 60, i * 0.03, true);
        if (motionEnabled()) triggerWhip(1);
        else render();
      } else {
        state.phase = 'drop'; state.phaseTime = 0;
        state.nailProgress = 0; state.pillarCrack = 0; state.flagDropY = -116;
      }
    }

    function persistLash() {
      const item = current();
      item.lashes += 1;
      if (countEl) countEl.textContent = String(item.lashes);
      if (!item.lash_url) return;
      fetch(item.lash_url, {
        method: 'POST',
        headers: { 'Accept': 'application/json', 'X-CSRF-Token': csrfToken, 'X-Requested-With': 'fetch' }
      }).then(res => res.ok ? res.json() : null).then(data => {
        if (data && typeof data.lashes === 'number') {
          item.lashes = data.lashes;
          if (current() === item && countEl) countEl.textContent = String(data.lashes);
        }
      }).catch(() => {});
    }

    function manualLash() {
      persistLash();
      if (!motionEnabled()) return;
      if (state.phase !== 'whipping') startSequence(true);
      state.loud = true;
      triggerWhip(1.22);
      wake();
    }

    // 有人点了：重新开始画（开场动画也算有人点，有声音）
    function replay() {
      startSequence(false);
      state.loud = true;
      wake();
    }

    tabs.forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = Number(btn.dataset.shameTab);
        if (idx === activeIdx || !items[idx]) return;
        activeIdx = idx;
        syncUI();
        replay();
      });
    });

    root.querySelector('[data-shame-whip]')?.addEventListener('click', manualLash);
    wrap.addEventListener('click', manualLash);
    root.querySelector('[data-shame-replay]')?.addEventListener('click', replay);

    // 抽完、火星和震动都散了，算停住
    const settled = () => state.phase === 'whipping' && state.whipState === 'idle' && state.autoLeft <= 0 &&
      !particles.length && !rings.length && !whipTrail.length && !state.stampPop && state.shakeMag <= 0.1;

    function tick(ts) {
      rafId = 0;
      if (document.hidden || !motionEnabled() || !onScreen) {
        render();
        return;
      }
      const dt = Math.min(0.033, (ts - lastTs) / 1000);
      lastTs = ts;
      update(dt);
      state.restTime = settled() ? state.restTime + dt : 0;
      render();
      if (state.restTime < REST_AFTER) rafId = requestAnimationFrame(tick);
    }

    function ensureRunning() {
      if (!motionEnabled()) {
        if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
        startSequence(true);
        return;
      }
      if (!rafId && !document.hidden && onScreen && state.restTime < REST_AFTER) {
        lastTs = performance.now();
        rafId = requestAnimationFrame(tick);
      }
    }

    function wake() {
      state.restTime = 0;
      ensureRunning();
    }

    // 滚出屏幕就不画，滚回来接着画
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(entries => {
        onScreen = entries[entries.length - 1].isIntersecting;
        ensureRunning();
      }).observe(wrap);
    }

    document.addEventListener('visibilitychange', ensureRunning);
    new MutationObserver(ensureRunning).observe(document.documentElement, { attributes: true, attributeFilter: ['data-motion'] });
    window.addEventListener('resize', resize);

    syncUI();
    resize();
    startSequence(!motionEnabled());
    ensureRunning();
  }

  stages.forEach(mountStage);
})();
