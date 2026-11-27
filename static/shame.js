/* 結 YUI · 耻辱柱 Canvas 物理动效（零外部依赖，严格单调波纹布面，绝不裁字或倒置） */
(() => {
  const stages = document.querySelectorAll('[data-shame-stage]');
  if (!stages.length) return;

  const SANS = "'Hiragino Sans','PingFang SC','Noto Sans CJK SC','Source Han Sans SC','Microsoft YaHei',sans-serif";
  const SERIF = "'Hiragino Mincho ProN','Yu Mincho','Noto Serif CJK SC','Source Han Serif SC','Songti SC',serif";
  const STAMP_LABELS = { overdue: '逾期', rejected: '退回', other: '示众' };
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

  const motionEnabled = () => document.documentElement.dataset.motion !== 'off' &&
    !matchMedia('(prefers-reduced-motion: reduce)').matches;
  const soundEnabled = () => {
    try { return localStorage.getItem('bounty-sound') === 'on'; } catch { return false; }
  };

  /* ---------- Web Audio 合成音效（遵循全站音效开关，默认静音） ---------- */
  let audioCtx = null;
  function getAudio() {
    if (!soundEnabled()) return null;
    if (!audioCtx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      audioCtx = new AC();
      audioCtx.master = audioCtx.createGain();
      audioCtx.master.gain.value = 0.36;
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
    sub.frequency.setValueAtTime(175, t);
    sub.frequency.exponentialRampToValueAtTime(38, t + 0.16);
    subG.gain.setValueAtTime(0.001, t);
    subG.gain.exponentialRampToValueAtTime(0.7, t + 0.005);
    subG.gain.exponentialRampToValueAtTime(0.001, t + 0.22);
    sub.connect(subG).connect(ac.master);
    sub.start(t); sub.stop(t + 0.24);

    [680, 1420].forEach((freq, i) => {
      const osc = ac.createOscillator(), g = ac.createGain();
      osc.type = i === 0 ? 'square' : 'sine';
      osc.frequency.setValueAtTime(freq, t);
      osc.frequency.exponentialRampToValueAtTime(freq * 0.92, t + 0.14);
      g.gain.setValueAtTime(0.001, t);
      g.gain.exponentialRampToValueAtTime(0.12 / (i + 1), t + 0.003);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.16);
      osc.connect(g).connect(ac.master);
      osc.start(t); osc.stop(t + 0.18);
    });
  }

  function sfxWhipWhoosh() {
    const ac = getAudio();
    if (!ac) return;
    const t = ac.currentTime, dur = 0.16;
    const buf = ac.createBuffer(1, Math.ceil(ac.sampleRate * dur), ac.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * Math.sin((i / data.length) * Math.PI);
    const src = ac.createBufferSource(); src.buffer = buf;
    const f = ac.createBiquadFilter(); f.type = 'bandpass';
    f.frequency.setValueAtTime(360, t); f.frequency.exponentialRampToValueAtTime(1850, t + dur); f.Q.value = 2.2;
    const g = ac.createGain();
    g.gain.setValueAtTime(0.001, t); g.gain.linearRampToValueAtTime(0.22, t + dur * 0.65); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    src.connect(f).connect(g).connect(ac.master);
    src.start(t);
  }

  function sfxWhipCrack(power = 1) {
    const ac = getAudio();
    if (!ac) return;
    const t = ac.currentTime, dur = 0.07;
    const buf = ac.createBuffer(1, Math.ceil(ac.sampleRate * dur), ac.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / data.length, 3.2);
    const src = ac.createBufferSource(); src.buffer = buf;
    const hp = ac.createBiquadFilter(); hp.type = 'bandpass';
    hp.frequency.setValueAtTime(2400 + Math.random() * 450, t); hp.Q.value = 1.1;
    const g = ac.createGain(); g.gain.value = 0.62 * power;
    src.connect(hp).connect(g).connect(ac.master);
    src.start(t);

    const thump = ac.createOscillator(), tg = ac.createGain();
    thump.type = 'sine';
    thump.frequency.setValueAtTime(205, t); thump.frequency.exponentialRampToValueAtTime(65, t + 0.08);
    tg.gain.setValueAtTime(0.001, t); tg.gain.exponentialRampToValueAtTime(0.28 * power, t + 0.004);
    tg.gain.exponentialRampToValueAtTime(0.001, t + 0.09);
    thump.connect(tg).connect(ac.master);
    thump.start(t); thump.stop(t + 0.1);
  }

  function fitEllipsis(c, text, maxW) {
    if (!text) return '';
    if (c.measureText(text).width <= maxW) return text;
    let out = text;
    while (out.length > 1 && c.measureText(out + '…').width > maxW) out = out.slice(0, -1);
    return out + '…';
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

    const TEX_W = 600, TEX_H = 310;
    const flagTex = document.createElement('canvas');
    flagTex.width = TEX_W; flagTex.height = TEX_H;

    const COLS = 24;
    const cloth = {
      originX: 220, originY: 110, flagW: 360, flagH: 186,
      y: new Float32Array(COLS + 1), vy: new Float32Array(COLS + 1),
      dx: new Float32Array(COLS + 1), vx: new Float32Array(COLS + 1),
      tilt: new Float32Array(COLS + 1), vtilt: new Float32Array(COLS + 1)
    };

    let activeIdx = 0;
    let canvasW = 860, canvasH = 430;
    let rafId = 0;
    let lastTs = performance.now();

    const particles = [];
    const rings = [];
    const whipTrail = [];
    const state = {
      phase: 'drop', phaseTime: 0, totalTime: 0, hitstopLeft: 0,
      shakeMag: 0, shakeX: 0, shakeY: 0, pillarCrack: 0,
      nailProgress: 0, nailRecoil: 0, flagDropY: -115, flashAlpha: 0,
      whipTimer: 0, whipState: 'idle', whipT: 0, whipStyle: 0,
      whipHitDone: false, whipPower: 1, localStrikes: 0, stampPop: null
    };

    const current = () => items[activeIdx];

    function rebuildFlagTexture() {
      const item = current();
      const c = flagTex.getContext('2d');
      c.clearRect(0, 0, TEX_W, TEX_H);

      const flagPath = () => {
        c.beginPath();
        c.moveTo(2, 6);
        c.lineTo(TEX_W - 4, 6);
        c.lineTo(TEX_W - 26, TEX_H * 0.5);
        c.lineTo(TEX_W - 4, TEX_H - 6);
        c.lineTo(2, TEX_H - 6);
        c.closePath();
      };

      c.save();
      flagPath();
      c.clip();

      const grad = c.createLinearGradient(0, 0, TEX_W, TEX_H);
      grad.addColorStop(0, '#FDF7EC');
      grad.addColorStop(0.55, '#F6ECD8');
      grad.addColorStop(1, '#EADAC0');
      c.fillStyle = grad;
      c.fillRect(0, 0, TEX_W, TEX_H);

      c.strokeStyle = 'rgba(75,52,36,0.04)'; c.lineWidth = 1;
      for (let y = 10; y < TEX_H; y += 6) { c.beginPath(); c.moveTo(0, y); c.lineTo(TEX_W, y); c.stroke(); }
      for (let x = 8; x < TEX_W; x += 8) { c.beginPath(); c.moveTo(x, 0); c.lineTo(x, TEX_H); c.stroke(); }

      c.fillStyle = '#E54465';
      c.fillRect(0, 6, TEX_W, 15);
      c.fillRect(0, TEX_H - 21, TEX_W, 15);
      c.fillStyle = '#1B1D2A';
      c.fillRect(0, 21, TEX_W, 3);
      c.fillRect(0, TEX_H - 24, TEX_W, 3);

      c.fillStyle = '#252736';
      c.fillRect(0, 6, 54, TEX_H - 12);
      c.strokeStyle = 'rgba(242,183,0,0.48)'; c.lineWidth = 2; c.setLineDash([6, 5]);
      c.beginPath(); c.moveTo(46, 18); c.lineTo(46, TEX_H - 18); c.stroke();
      c.setLineDash([]);

      const gx = 27, gy = TEX_H * 0.48;
      c.beginPath(); c.arc(gx, gy, 15, 0, Math.PI * 2); c.fillStyle = '#C49240'; c.fill();
      c.beginPath(); c.arc(gx, gy, 9, 0, Math.PI * 2); c.fillStyle = '#161823'; c.fill();

      c.strokeStyle = 'rgba(166,28,56,0.12)'; c.lineWidth = 4; c.lineCap = 'round';
      c.beginPath(); c.moveTo(140, 74); c.lineTo(350, 218); c.stroke();
      c.lineWidth = 2.5;
      c.beginPath(); c.moveTo(230, 62); c.lineTo(415, 168); c.stroke();

      c.fillStyle = '#8A6B52'; c.font = '700 16px ' + SANS;
      c.textAlign = 'center'; c.textBaseline = 'middle';
      c.fillText('—  耻  辱  柱  示  众  —', 284, 54);

      const displayName = (item.name || '无名氏').trim();
      const maxNameW = 344;
      let fontSize = 86;
      while (fontSize > 30) {
        c.font = `900 ${fontSize}px ${SERIF}`;
        if (c.measureText(displayName).width <= maxNameW) break;
        fontSize -= 2;
      }
      c.fillStyle = '#1B1D2A';
      c.fillText(displayName, 258, 148);

      const stampText = STAMP_LABELS[item.kind] || '示众';
      c.save();
      c.translate(496, 134); c.rotate(0.08);
      c.strokeStyle = '#E54465'; c.lineWidth = 4.5; c.fillStyle = 'rgba(229,68,101,0.10)';
      c.beginPath(); c.roundRect(-34, -34, 68, 68, 10); c.fill(); c.stroke();
      c.fillStyle = '#E54465'; c.font = '900 26px ' + SERIF;
      c.fillText(stampText, 0, 2);
      c.restore();

      c.fillStyle = '#5D4837'; c.font = '700 18px ' + SANS;
      c.fillText(fitEllipsis(c, (item.reason || '').trim(), 448), 308, 240);

      c.restore();

      c.strokeStyle = '#1B1D2A'; c.lineWidth = 3;
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
          ? (Math.sin(t * 4.4 - u * 4.6) * 9.5 + Math.cos(t * 7.2 - u * 7.5) * 3.2) * Math.pow(u, 0.85)
          : Math.sin(t * 5.0 - u * 3.8) * 6 * u;
        cloth.vy[c] += ((leftY + rightY - 2 * cloth.y[c]) * 320 + (windTargetY - cloth.y[c]) * 26 - cloth.vy[c] * 4.8) * dt;
        const maxAmpY = 34 * Math.pow(u, 0.7) + 4;
        ny[c] = Math.max(-maxAmpY, Math.min(maxAmpY, cloth.y[c] + cloth.vy[c] * dt));

        const leftX = cloth.dx[c - 1], rightX = c < COLS ? cloth.dx[c + 1] : cloth.dx[c];
        const windTargetX = nailed ? Math.sin(t * 4.4 - u * 4.6 + 0.6) * 3.5 * u : 0;
        cloth.vx[c] += ((leftX + rightX - 2 * cloth.dx[c]) * 260 + (windTargetX - cloth.dx[c]) * 38 - cloth.vx[c] * 6.2) * dt;
        ndx[c] = cloth.dx[c] + cloth.vx[c] * dt;

        const targetTilt = nailed ? Math.cos(t * 4.4 - u * 4.8) * 5.5 * u : 0;
        cloth.vtilt[c] += ((targetTilt - cloth.tilt[c]) * 36 - cloth.vtilt[c] * 5.5) * dt;
        cloth.tilt[c] = Math.max(-14, Math.min(14, cloth.tilt[c] + cloth.vtilt[c] * dt));
      }

      const restStep = cloth.flagW / COLS;
      const minDelta = restStep * 0.74, maxDelta = restStep * 1.12;
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
          const w = Math.cos((dist / 8) * Math.PI * 0.5);
          const u = c / COLS;
          cloth.vx[c] -= 175 * power * w * (0.45 + 0.55 * u);
          cloth.vy[c] += 220 * arc * power * w * (0.35 + 0.65 * u);
          cloth.vtilt[c] += 115 * -arc * power * w;
        }
      }
    }

    function colGeom(c, dropOffsetY) {
      const u = c / COLS;
      const xBase = cloth.originX + u * cloth.flagW + cloth.dx[c];
      const centerY = cloth.originY + dropOffsetY + cloth.y[c] + u * u * 6;
      return {
        topX: xBase - cloth.tilt[c] * 0.35,
        topY: centerY - cloth.tilt[c] * 0.25,
        botX: xBase + cloth.tilt[c] * 0.35,
        botY: centerY + cloth.flagH + cloth.tilt[c] * 0.25
      };
    }

    function spawnNailImpact(x, y) {
      for (let i = 0; i < 24; i++) {
        const ang = Math.random() * Math.PI * 2, spd = 130 + Math.random() * 320;
        particles.push({
          kind: 'wood', x, y, vx: Math.cos(ang) * spd, vy: Math.sin(ang) * spd - 85,
          rot: Math.random() * Math.PI * 2, vrot: (Math.random() - 0.5) * 18,
          w: 6 + Math.random() * 10, h: 2.5 + Math.random() * 3,
          color: i % 3 === 0 ? '#9C6B3F' : i % 3 === 1 ? '#C7925B' : '#5E3D28',
          life: 0, maxLife: 0.45 + Math.random() * 0.4
        });
      }
      for (let i = 0; i < 16; i++) {
        const ang = (Math.random() - 0.5) * Math.PI * 1.4 - Math.PI * 0.15, spd = 210 + Math.random() * 380;
        particles.push({
          kind: 'spark', x, y, vx: Math.cos(ang) * spd, vy: Math.sin(ang) * spd - 75,
          size: 2.5 + Math.random() * 2.8, color: i % 2 === 0 ? '#FFE27A' : '#FF6B4A',
          life: 0, maxLife: 0.28 + Math.random() * 0.28
        });
      }
      rings.push({ x, y, r: 8, maxR: 104, color: '#FFE27A', width: 5.5, life: 0, maxLife: 0.34 });
      rings.push({ x, y, r: 6, maxR: 68, color: '#E54465', width: 3.5, life: 0, maxLife: 0.28 });
    }

    function spawnWhipImpact(x, y, power = 1) {
      const count = Math.round(18 * power);
      for (let i = 0; i < count; i++) {
        const ang = Math.PI * 0.65 + (Math.random() - 0.5) * 1.9, spd = (170 + Math.random() * 340) * power;
        particles.push({
          kind: i % 3 === 0 ? 'thread' : 'spark',
          x: x + (Math.random() - 0.5) * 22, y: y + (Math.random() - 0.5) * 22,
          vx: Math.cos(ang) * spd, vy: Math.sin(ang) * spd - 55,
          rot: Math.random() * Math.PI, vrot: (Math.random() - 0.5) * 20,
          w: 7 + Math.random() * 9, h: 2, size: 2.4 + Math.random() * 3,
          color: i % 3 === 0 ? '#F7EAD2' : (i % 2 === 0 ? '#F2B700' : '#E54465'),
          life: 0, maxLife: 0.25 + Math.random() * 0.3
        });
      }
      rings.push({ x, y, r: 6, maxR: 80 * power, color: '#fff', width: 4.5, life: 0, maxLife: 0.24 });
      rings.push({ x, y, r: 10, maxR: 110 * power, color: '#E54465', width: 3.2, life: 0, maxLife: 0.3 });
      const words = ['啪！', '抽！', '督！', '醒！'];
      state.stampPop = {
        text: words[state.localStrikes % words.length],
        x: x + (Math.random() - 0.5) * 26, y: y - 46 + (Math.random() - 0.5) * 14,
        rot: (Math.random() - 0.5) * 0.3, life: 0, maxLife: 0.5
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
        if (k > 0.64) {
          const over = (k - 0.64) / 0.36;
          tipX -= over * 24; tipY += over * 20 * st.arc;
        }
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

    function render() {
      const W = canvasW, H = canvasH;
      ctx.save();
      ctx.clearRect(0, 0, W, H);
      ctx.translate(state.shakeX, state.shakeY);

      // 背景
      const bg = ctx.createRadialGradient(W * 0.42, H * 0.46, 26, W * 0.46, H * 0.5, W * 0.72);
      bg.addColorStop(0, '#2C2233'); bg.addColorStop(0.5, '#1B1D2A'); bg.addColorStop(1, '#11121B');
      ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);

      ctx.save();
      ctx.strokeStyle = 'rgba(255,255,255,0.035)'; ctx.lineWidth = 1.5;
      const rWave = 32;
      for (let row = 0; row < 3; row++) {
        const cy = H - 18 - row * 22, offset = (row % 2) * rWave;
        for (let cx = -rWave + offset; cx < W + rWave; cx += rWave * 2) {
          ctx.beginPath(); ctx.arc(cx, cy, rWave, Math.PI, 0); ctx.stroke();
          ctx.beginPath(); ctx.arc(cx, cy, rWave * 0.64, Math.PI, 0); ctx.stroke();
        }
      }
      ctx.restore();

      const floorY = H * 0.84;
      const floorGrad = ctx.createLinearGradient(0, floorY, 0, H);
      floorGrad.addColorStop(0, 'rgba(0,0,0,0.42)'); floorGrad.addColorStop(1, 'rgba(0,0,0,0.72)');
      ctx.fillStyle = floorGrad; ctx.fillRect(0, floorY, W, H - floorY);
      ctx.strokeStyle = 'rgba(229,68,101,0.22)'; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(32, floorY); ctx.lineTo(W - 32, floorY); ctx.stroke();

      // 耻辱柱
      const px = W * 0.22, pw = Math.max(52, Math.min(68, W * 0.08));
      const topY = H * 0.11, botY = floorY;
      ctx.fillStyle = 'rgba(0,0,0,0.5)';
      ctx.beginPath(); ctx.ellipse(px, floorY + 13, pw * 1.35, 15, 0, 0, Math.PI * 2); ctx.fill();

      const plinth = ctx.createLinearGradient(px - pw, botY - 24, px + pw, botY + 14);
      plinth.addColorStop(0, '#4E5263'); plinth.addColorStop(0.5, '#353847'); plinth.addColorStop(1, '#222431');
      ctx.fillStyle = plinth;
      ctx.beginPath();
      ctx.moveTo(px - pw * 0.8, botY - 18); ctx.lineTo(px + pw * 0.8, botY - 18);
      ctx.lineTo(px + pw * 1.04, botY + 14); ctx.lineTo(px - pw * 1.04, botY + 14); ctx.closePath();
      ctx.fill(); ctx.strokeStyle = 'rgba(255,255,255,0.14)'; ctx.lineWidth = 1.4; ctx.stroke();

      const wood = ctx.createLinearGradient(px - pw / 2, 0, px + pw / 2, 0);
      wood.addColorStop(0, '#2B1B14'); wood.addColorStop(0.28, '#5C3A28');
      wood.addColorStop(0.52, '#6F4832'); wood.addColorStop(0.82, '#3D251A'); wood.addColorStop(1, '#21130D');
      ctx.fillStyle = wood;
      ctx.beginPath(); ctx.roundRect(px - pw / 2, topY, pw, botY - topY - 12, [10, 10, 2, 2]); ctx.fill();

      ctx.strokeStyle = 'rgba(20,10,6,0.36)'; ctx.lineWidth = 1.5;
      [-0.3, -0.12, 0.09, 0.25, 0.36].forEach((f, i) => {
        const ox = f * pw;
        ctx.beginPath(); ctx.moveTo(px + ox, topY + 16 + i * 8);
        ctx.bezierCurveTo(px + ox + 2, H * 0.35, px + ox - 3, H * 0.6, px + ox + 1, botY - 22); ctx.stroke();
      });

      [topY + 44, botY - 58].forEach(by => {
        const band = ctx.createLinearGradient(px - pw / 2 - 4, by, px + pw / 2 + 4, by);
        band.addColorStop(0, '#1D1F2B'); band.addColorStop(0.35, '#4A4E61');
        band.addColorStop(0.7, '#2A2D3D'); band.addColorStop(1, '#151722');
        ctx.fillStyle = band;
        ctx.beginPath(); ctx.roundRect(px - pw / 2 - 4, by, pw + 8, 15, 4); ctx.fill();
        ctx.strokeStyle = 'rgba(255,255,255,0.16)'; ctx.lineWidth = 1; ctx.stroke();
        [-0.32, 0, 0.32].forEach(rf => {
          ctx.fillStyle = '#898FA6'; ctx.beginPath(); ctx.arc(px + rf * pw, by + 7.5, 2.6, 0, Math.PI * 2); ctx.fill();
        });
      });

      const plW = Math.max(88, pw * 1.52), plH = 32, plY = topY - 8;
      ctx.fillStyle = '#1B1D2A'; ctx.strokeStyle = '#E54465'; ctx.lineWidth = 2.4;
      ctx.beginPath(); ctx.roundRect(px - plW / 2, plY, plW, plH, 8); ctx.fill(); ctx.stroke();
      ctx.fillStyle = '#F7EAD2'; ctx.font = '900 16px ' + SERIF;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('耻 辱 柱', px, plY + plH / 2 + 1);

      if (state.pillarCrack > 0) {
        const nx = px + pw * 0.2, ny = cloth.originY + cloth.flagH * 0.48;
        ctx.save(); ctx.globalAlpha = Math.min(1, state.pillarCrack);
        ctx.strokeStyle = '#140B07'; ctx.lineWidth = 2.1;
        [[[-4, -4], [-20, -24]], [[2, -5], [14, -26]], [[-5, 6], [-22, 22]], [[4, 7], [15, 25]], [[-6, 0], [-25, 3]]].forEach(([a, b]) => {
          ctx.beginPath(); ctx.moveTo(nx + a[0], ny + a[1]); ctx.lineTo(nx + b[0], ny + b[1]); ctx.stroke();
        });
        ctx.restore();
      }

      // 物理布面旗帜
      const dropY = state.phase === 'drop' ? state.flagDropY : 0;
      const restStep = cloth.flagW / COLS;
      for (let c = 0; c < COLS; c++) {
        const L = colGeom(c, dropY), R = colGeom(c + 1, dropY);
        const u0 = (c / COLS) * TEX_W, u1 = ((c + 1) / COLS) * TEX_W;
        drawTexturedTri(L.topX, L.topY, R.topX, R.topY, L.botX, L.botY, u0, 0, u1, 0, u0, TEX_H);
        drawTexturedTri(R.topX, R.topY, R.botX, R.botY, L.botX, L.botY, u1, 0, u1, TEX_H, u0, TEX_H);
        const shadeVal = ((R.topY - L.topY) / restStep) * 0.24 + (1 - (R.topX - L.topX) / restStep) * 0.42;
        if (Math.abs(shadeVal) > 0.025) {
          ctx.save();
          ctx.beginPath(); ctx.moveTo(L.topX, L.topY); ctx.lineTo(R.topX, R.topY);
          ctx.lineTo(R.botX, R.botY); ctx.lineTo(L.botX, L.botY); ctx.closePath();
          const alpha = Math.min(0.24, Math.abs(shadeVal));
          ctx.fillStyle = shadeVal > 0 ? `rgba(18,16,28,${alpha})` : `rgba(255,250,238,${alpha * 0.7})`;
          ctx.fill(); ctx.restore();
        }
      }

      // 大粗铁钉
      if (state.phase !== 'drop') {
        const targetX = cloth.originX + 16, targetY = cloth.originY + cloth.flagH * 0.48;
        const angle = -0.36;
        const travel = (1 - state.nailProgress) * 155 + state.nailRecoil * 8;
        const tipX = targetX + Math.cos(angle) * travel, tipY = targetY + Math.sin(angle) * travel;
        const fullShaft = 104;
        const visShaft = state.nailProgress > 0.72 ? fullShaft - (state.nailProgress - 0.72) / 0.28 * 78 : fullShaft;
        ctx.save(); ctx.translate(tipX, tipY); ctx.rotate(angle);
        if (state.nailProgress > 0.8) {
          ctx.fillStyle = 'rgba(0,0,0,0.45)'; ctx.beginPath(); ctx.ellipse(-2, 7, 15, 7, 0.2, 0, Math.PI * 2); ctx.fill();
        }
        const sg = ctx.createLinearGradient(0, -10, 0, 10);
        sg.addColorStop(0, '#B9C0D4'); sg.addColorStop(0.32, '#6E748A'); sg.addColorStop(0.75, '#343848'); sg.addColorStop(1, '#181A24');
        ctx.fillStyle = sg;
        ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.min(18, visShaft), -8);
        ctx.lineTo(visShaft, -10); ctx.lineTo(visShaft, 10); ctx.lineTo(Math.min(18, visShaft), 8); ctx.closePath();
        ctx.fill(); ctx.strokeStyle = '#12131C'; ctx.lineWidth = 1.8; ctx.stroke();
        ctx.strokeStyle = 'rgba(255,255,255,0.42)'; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(Math.min(14, visShaft), -3.5); ctx.lineTo(visShaft - 2, -4.5); ctx.stroke();
        const hg = ctx.createLinearGradient(visShaft, -22, visShaft + 18, 22);
        hg.addColorStop(0, '#E0E5F2'); hg.addColorStop(0.3, '#8890A8'); hg.addColorStop(0.72, '#3C4052'); hg.addColorStop(1, '#1A1C26');
        ctx.fillStyle = hg;
        ctx.beginPath(); ctx.roundRect(visShaft - 3, -22, 18, 44, 6); ctx.fill();
        ctx.strokeStyle = '#11121A'; ctx.lineWidth = 2; ctx.stroke();
        ctx.fillStyle = 'rgba(255,255,255,0.32)'; ctx.beginPath(); ctx.roundRect(visShaft + 9, -19, 4, 38, 2); ctx.fill();
        if (state.phase === 'nail_aim') {
          const glint = Math.sin(Math.min(1, state.phaseTime / 0.24) * Math.PI);
          ctx.save(); ctx.translate(visShaft + 7, -13); ctx.fillStyle = `rgba(255,245,196,${glint})`;
          const s = 24 * glint;
          ctx.beginPath(); ctx.moveTo(0, -s); ctx.lineTo(3, -3); ctx.lineTo(s, 0); ctx.lineTo(3, 3);
          ctx.lineTo(0, s); ctx.lineTo(-3, 3); ctx.lineTo(-s, 0); ctx.lineTo(-3, -3); ctx.closePath(); ctx.fill();
          ctx.restore();
        }
        ctx.restore();
      }

      // 皮鞭（动效开启且已钉上后显示）
      if (state.phase === 'whipping' && motionEnabled()) {
        const { pts } = computeWhipPoints();
        const tip = pts[pts.length - 1];
        if (state.whipState === 'strike') whipTrail.push({ x: tip.x, y: tip.y, life: 0 });
        if (whipTrail.length > 2) {
          ctx.save();
          for (let i = 1; i < whipTrail.length; i++) {
            const a = whipTrail[i - 1], b = whipTrail[i];
            const alpha = Math.max(0, 1 - b.life / 0.16) * 0.72;
            ctx.strokeStyle = `rgba(229,68,101,${alpha})`; ctx.lineWidth = (i / whipTrail.length) * 11; ctx.lineCap = 'round';
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
            ctx.strokeStyle = `rgba(255,244,209,${alpha * 0.85})`; ctx.lineWidth = (i / whipTrail.length) * 3.8;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
          ctx.restore();
        }
        ctx.save(); ctx.lineCap = 'round'; ctx.lineJoin = 'round';
        for (let i = 0; i < pts.length - 1; i++) {
          const s = i / (pts.length - 1);
          ctx.strokeStyle = '#0E0F17'; ctx.lineWidth = (1 - s) * 10 + 5;
          ctx.beginPath(); ctx.moveTo(pts[i].x, pts[i].y); ctx.lineTo(pts[i + 1].x, pts[i + 1].y); ctx.stroke();
        }
        for (let i = 0; i < pts.length - 1; i++) {
          const s = i / (pts.length - 1);
          ctx.strokeStyle = s > 0.84 ? '#E54465' : (i % 2 === 0 ? '#784830' : '#583220');
          ctx.lineWidth = (1 - s) * 9 + 1.8;
          ctx.beginPath(); ctx.moveTo(pts[i].x, pts[i].y); ctx.lineTo(pts[i + 1].x, pts[i + 1].y); ctx.stroke();
        }
        const p0 = pts[0], p2 = pts[2], hAng = Math.atan2(p2.y - p0.y, p2.x - p0.x);
        ctx.save(); ctx.translate(p0.x, p0.y); ctx.rotate(hAng + Math.PI);
        ctx.fillStyle = '#2B1A13'; ctx.strokeStyle = '#F2B700'; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.roundRect(-8, -7, 44, 14, 6); ctx.fill(); ctx.stroke();
        ctx.strokeStyle = '#9C6B3F'; ctx.lineWidth = 2;
        for (let x = 2; x <= 26; x += 7) { ctx.beginPath(); ctx.moveTo(x, -6); ctx.lineTo(x + 4, 6); ctx.stroke(); }
        ctx.fillStyle = '#F2B700'; ctx.beginPath(); ctx.arc(36, 0, 6.5, 0, Math.PI * 2); ctx.fill();
        ctx.restore();

        if (state.whipState === 'strike' && state.whipT > 0.56 && state.whipT < 0.82) {
          const k = 1 - Math.abs(state.whipT - 0.66) / 0.16;
          if (k > 0) {
            ctx.save(); ctx.translate(tip.x, tip.y); ctx.rotate(state.totalTime * 6);
            const rOut = 40 * k * state.whipPower, rIn = 9 * k;
            ctx.fillStyle = '#FFF6D6'; ctx.strokeStyle = '#E54465'; ctx.lineWidth = 2.4;
            ctx.beginPath();
            for (let i = 0; i < 8; i++) {
              const a = (i * Math.PI) / 4, r = i % 2 === 0 ? rOut : rIn;
              if (i === 0) ctx.moveTo(Math.cos(a) * r, Math.sin(a) * r);
              else ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r);
            }
            ctx.closePath(); ctx.fill(); ctx.stroke(); ctx.restore();
          }
        }
        ctx.restore();
      }

      // 粒子与光效
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
        ctx.globalAlpha = alpha; ctx.fillStyle = '#E54465'; ctx.strokeStyle = '#fff'; ctx.lineWidth = 4;
        ctx.font = '900 30px ' + SERIF; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.strokeText(sp.text, 0, 0); ctx.fillText(sp.text, 0, 0); ctx.restore();
      }
      if (state.flashAlpha > 0.01) {
        ctx.save(); ctx.fillStyle = `rgba(255,244,220,${state.flashAlpha})`; ctx.fillRect(0, 0, W, H); ctx.restore();
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
      if (state.hitstopLeft > 0) {
        state.hitstopLeft -= dt;
        state.shakeX = (Math.random() - 0.5) * 2 * state.shakeMag;
        state.shakeY = (Math.random() - 0.5) * 2 * state.shakeMag;
        return;
      }
      state.phaseTime += dt;
      state.flashAlpha *= Math.pow(0.02, dt);
      state.nailRecoil *= Math.pow(0.001, dt);
      if (state.shakeMag > 0.1) {
        state.shakeMag *= Math.pow(0.0015, dt);
        state.shakeX = (Math.random() - 0.5) * 2 * state.shakeMag;
        state.shakeY = (Math.random() - 0.5) * 2 * state.shakeMag;
      } else { state.shakeMag = 0; state.shakeX = 0; state.shakeY = 0; }

      if (state.phase === 'drop') {
        const k = Math.min(1, state.phaseTime / 0.36);
        state.flagDropY = -115 * (1 - (1 - Math.pow(1 - k, 3)));
        stepCloth(dt, state.totalTime, false);
        if (k >= 1) { state.flagDropY = 0; state.phase = 'nail_aim'; state.phaseTime = 0; }
      } else if (state.phase === 'nail_aim') {
        stepCloth(dt, state.totalTime, false);
        if (state.phaseTime >= 0.28) { state.phase = 'nail_slam'; state.phaseTime = 0; }
      } else if (state.phase === 'nail_slam') {
        const k = Math.min(1, state.phaseTime / 0.14);
        state.nailProgress = Math.pow(k, 2.8);
        stepCloth(dt, state.totalTime, k > 0.7);
        if (k >= 1) {
          state.nailProgress = 1; state.nailRecoil = 1; state.pillarCrack = 1;
          state.hitstopLeft = 0.072; state.shakeMag = 6.8; state.flashAlpha = 0.22;
          const ix = cloth.originX + 16, iy = cloth.originY + cloth.flagH * 0.48;
          spawnNailImpact(ix, iy);
          applyClothImpulse(ix + 35, 0.7, 1);
          sfxNailSlam();
          state.phase = 'whipping'; state.phaseTime = 0; state.whipTimer = 0.45;
        }
      } else if (state.phase === 'whipping') {
        stepCloth(dt, state.totalTime, true);
        if (state.whipState === 'idle') {
          state.whipTimer -= dt;
          if (state.whipTimer <= 0) triggerWhip(1);
        } else if (state.whipState === 'windup') {
          state.whipT += dt / 0.3;
          if (state.whipT >= 1) { state.whipState = 'strike'; state.whipT = 0; sfxWhipWhoosh(); }
        } else if (state.whipState === 'strike') {
          state.whipT += dt / 0.22;
          if (!state.whipHitDone && state.whipT >= 0.62) {
            state.whipHitDone = true;
            state.localStrikes += 1;
            const { target } = computeWhipPoints();
            const pwr = state.whipPower;
            applyClothImpulse(target.tx, pwr, target.arc);
            spawnWhipImpact(target.tx, target.ty, pwr);
            sfxWhipCrack(pwr);
            state.shakeMag = Math.max(state.shakeMag, 3.2 * pwr);
            state.flashAlpha = Math.max(state.flashAlpha, 0.08 * pwr);
          }
          if (state.whipT >= 1) { state.whipState = 'recover'; state.whipT = 0; }
        } else if (state.whipState === 'recover') {
          state.whipT += dt / 0.32;
          if (state.whipT >= 1) { state.whipState = 'idle'; state.whipT = 0; state.whipTimer = 0.95; }
        }
      }

      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i]; p.life += dt;
        if (p.life >= p.maxLife) { particles.splice(i, 1); continue; }
        p.vy += (p.kind === 'thread' ? 240 : 780) * dt; p.vx *= 0.97;
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
      cloth.flagW = Math.min(400, Math.max(180, canvasW * 0.44));
      cloth.flagH = cloth.flagW * (TEX_H / TEX_W);
      cloth.originX = canvasW * 0.22 + 8;
      cloth.originY = canvasH * 0.25;
      if (!motionEnabled()) render();
    }

    function syncUI() {
      const item = current();
      if (countEl) countEl.textContent = String(item.lashes);
      if (kindEl) {
        kindEl.textContent = item.kind_label;
        kindEl.className = 'shame-kind' + (item.kind === 'overdue' ? '' : ' ' + item.kind);
      }
      if (reasonEl) reasonEl.textContent = `「${item.reason}」`;
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
      state.stampPop = null; state.shakeMag = 0; state.flashAlpha = 0;
      state.hitstopLeft = 0; state.nailRecoil = 0;
      state.whipState = 'idle'; state.whipT = 0; state.whipTimer = 0.22;
      resetCloth();
      if (skipIntro || !motionEnabled()) {
        state.phase = 'whipping'; state.phaseTime = 0;
        state.nailProgress = 1; state.pillarCrack = 1; state.flagDropY = 0;
        for (let i = 0; i < 16; i++) stepCloth(1 / 60, i * 0.03, true);
        if (motionEnabled()) triggerWhip(1);
        else render();
      } else {
        state.phase = 'drop'; state.phaseTime = 0;
        state.nailProgress = 0; state.pillarCrack = 0; state.flagDropY = -115;
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
      triggerWhip(1.22);
    }

    tabs.forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = Number(btn.dataset.shameTab);
        if (idx === activeIdx || !items[idx]) return;
        activeIdx = idx;
        syncUI();
        startSequence(false);
      });
    });

    root.querySelector('[data-shame-whip]')?.addEventListener('click', manualLash);
    wrap.addEventListener('click', manualLash);
    root.querySelector('[data-shame-replay]')?.addEventListener('click', () => startSequence(false));

    function tick(ts) {
      rafId = 0;
      if (document.hidden || !motionEnabled()) {
        render();
        return;
      }
      const dt = Math.min(0.033, (ts - lastTs) / 1000);
      lastTs = ts;
      update(dt);
      render();
      rafId = requestAnimationFrame(tick);
    }

    function ensureRunning() {
      if (!motionEnabled()) {
        if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
        startSequence(true);
        return;
      }
      if (!rafId && !document.hidden) {
        lastTs = performance.now();
        rafId = requestAnimationFrame(tick);
      }
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
