/* 結 YUI · 全站交互与手感
   手感原则：
   - 操作后 100ms 内一定有反馈；状态先保存，动画只是盖在上面的一层，点击或按 Esc 立即跳到结果。
   - 分级：悬停最轻；认领、提交、退回 ≤400ms 且不震；验收、勋章 ≤1s；集齐一套 ≤2s 且只播一次。
   - 打击停顿只用在大节点（60–120ms），震动只震目标元素、横向 ≤3px，绝不震整页。
   - 同一个反馈 10 秒内出现 3 次以上就自动减弱。声音默认关闭，起音短、不加混响。 */
(() => {
  const root = document.documentElement;
  // 只给逐帧截图用：window.__bountyTimeScale = 10 时，计时器和数字滚动一起放慢，和慢放的动画保持同步
  const SLOW = Number(window.__bountyTimeScale) || 1;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const store = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch { /* 隐私模式下不保存偏好 */ } },
  };
  const A = 'cubic-bezier(.2,0,0,1)';      // 稳稳到位
  const B = 'cubic-bezier(.34,1.56,.64,1)'; // 过冲回弹
  const C = 'cubic-bezier(.16,1,.3,1)';     // 快出慢停
  const D = 'cubic-bezier(.4,0,1,1)';       // 加速砸下

  /* ---------- 动效开关 ---------- */
  let quiet = store.get('bounty-motion') === 'off';
  const motionOn = () => !reduced.matches && !quiet;
  const motionToggle = document.querySelector('[data-motion-toggle]');
  function syncMotion() {
    root.dataset.motion = motionOn() ? 'on' : 'off';
    if (motionToggle) {
      motionToggle.setAttribute('aria-pressed', String(!motionOn()));
      motionToggle.title = reduced.matches ? '动效：已随系统关闭' : `动效：${quiet ? '关' : '开'}`;
      motionToggle.disabled = reduced.matches;
    }
    if (!motionOn()) document.getAnimations().forEach(animation => animation.cancel());
  }
  syncMotion();
  reduced.addEventListener('change', syncMotion);
  motionToggle?.addEventListener('click', () => {
    quiet = !quiet;
    store.set('bounty-motion', quiet ? 'off' : 'on');
    syncMotion();
  });

  // 同一种反馈短时间内反复出现就减弱，避免腻
  const recent = {};
  function strength(kind) {
    const now = performance.now();
    recent[kind] = (recent[kind] || []).filter(t => now - t < 10000);
    recent[kind].push(now);
    return recent[kind].length >= 3 ? 0.55 : 1;
  }
  function play(element, frames, options) {
    if (!element || !motionOn()) return null;
    return element.animate(frames, {duration: 300, easing: A, fill: 'none', ...options});
  }

  /* ---------- 声音：Web Audio 现场合成，默认关闭 ---------- */
  let soundOn = store.get('bounty-sound') === 'on';
  const soundToggle = document.querySelector('[data-sound-toggle]');
  const mutedIcon = soundToggle?.innerHTML;
  function syncSound() {
    if (!soundToggle) return;
    soundToggle.setAttribute('aria-pressed', String(soundOn));
    soundToggle.title = `音效：${soundOn ? '开' : '关'}`;
    soundToggle.innerHTML = soundOn
      ? '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 10v4h3l4 3.5v-11L8 10z"/><path d="M15.5 9.5a3.5 3.5 0 0 1 0 5M18 7a7 7 0 0 1 0 10"/></svg>'
      : mutedIcon;
  }
  syncSound();
  soundToggle?.addEventListener('click', () => {
    soundOn = !soundOn;
    store.set('bounty-sound', soundOn ? 'on' : 'off');
    syncSound();
    if (soundOn) sfx('tap');
  });
  let audio = null;
  let lastTick = 0;
  function ctx() {
    if (!audio) {
      const Context = window.AudioContext || window.webkitAudioContext;
      if (!Context) return null;
      audio = new Context();
      audio.master = audio.createGain();
      audio.master.gain.value = 0.3;
      audio.master.connect(audio.destination);
    }
    if (audio.state === 'suspended') audio.resume();
    return audio;
  }
  function tone(ac, {type = 'sine', from, to = from, at = 0, dur, gain = 0.06, filter}) {
    const t = ac.currentTime + at;
    const osc = ac.createOscillator();
    const amp = ac.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(from, t);
    if (to !== from) osc.frequency.exponentialRampToValueAtTime(to, t + dur);
    amp.gain.setValueAtTime(0.0001, t);
    amp.gain.exponentialRampToValueAtTime(gain, t + 0.004);      // 起音 4ms
    amp.gain.exponentialRampToValueAtTime(0.0001, t + dur);       // 指数衰减，不留残响
    let node = osc;
    if (filter) { const f = ac.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = filter; osc.connect(f); node = f; }
    node.connect(amp).connect(ac.master);
    osc.start(t);
    osc.stop(t + dur + 0.02);
  }
  function noise(ac, {at = 0, dur = 0.03, gain = 0.08, band = 1200}) {
    const t = ac.currentTime + at;
    const buffer = ac.createBuffer(1, Math.ceil(ac.sampleRate * dur), ac.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / data.length);
    const src = ac.createBufferSource();
    const f = ac.createBiquadFilter();
    const amp = ac.createGain();
    src.buffer = buffer;
    f.type = 'bandpass'; f.frequency.value = band; f.Q.value = 1.2;
    amp.gain.value = gain;
    src.connect(f).connect(amp).connect(ac.master);
    src.start(t);
  }
  function bell(ac, {freq = 1568, at = 0, dur = 0.4, gain = 0.07}) {
    // 简单 FM：调制比 3.5，像金属小铃
    const t = ac.currentTime + at;
    const carrier = ac.createOscillator();
    const mod = ac.createOscillator();
    const modGain = ac.createGain();
    const amp = ac.createGain();
    carrier.frequency.value = freq;
    mod.frequency.value = freq * 3.5;
    modGain.gain.setValueAtTime(freq * 1.2, t);
    modGain.gain.exponentialRampToValueAtTime(1, t + dur);
    amp.gain.setValueAtTime(0.0001, t);
    amp.gain.exponentialRampToValueAtTime(gain, t + 0.003);
    amp.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    mod.connect(modGain).connect(carrier.frequency);
    carrier.connect(amp).connect(ac.master);
    mod.start(t); carrier.start(t);
    mod.stop(t + dur + 0.02); carrier.stop(t + dur + 0.02);
  }
  function sfx(name, extra = {}) {
    if (!soundOn) return;
    const ac = ctx();
    if (!ac) return;
    const jitter = 1 + (Math.random() - 0.5) * 0.2;
    switch (name) {
      case 'tap': tone(ac, {type: 'triangle', from: 1200, dur: 0.03, gain: 0.03}); break;
      case 'claim': tone(ac, {type: 'triangle', from: 659, dur: 0.06}); tone(ac, {type: 'triangle', from: 880, at: 0.06, dur: 0.09}); break;
      case 'submit': tone(ac, {from: 440, to: 880, dur: 0.09, gain: 0.07}); break;
      case 'return': tone(ac, {type: 'triangle', from: 392, to: 294, dur: 0.16, gain: 0.04, filter: 1500}); break;
      case 'stamp':
        tone(ac, {from: 160, to: 60, dur: 0.08, gain: 0.25});
        noise(ac, {dur: 0.05, gain: 0.06, band: 600});
        [1047, 1319, 1568].forEach((f, i) => tone(ac, {from: f, at: 0.12 + i * 0.07, dur: 0.18, gain: 0.05}));
        break;
      case 'medal': bell(ac, {freq: 1568 * (extra.pitch || 1)}); break;
      case 'set': [523, 659, 784, 1047].forEach((f, i) => tone(ac, {from: f, at: i * 0.09, dur: i === 3 ? 0.5 : 0.14, gain: 0.06})); break;
      case 'level': [523, 784, 1047, 1568].forEach((f, i) => tone(ac, {type: i % 2 ? 'triangle' : 'sine', from: f, at: i * 0.08, dur: i === 3 ? 0.45 : 0.12, gain: 0.06})); break;
      case 'clap': noise(ac, {band: 1200 * jitter}); noise(ac, {at: 0.05, band: 1300 * jitter, gain: 0.06}); break;
      case 'tick': {
        const now = performance.now();
        if (now - lastTick < 66) return;   // 每秒最多 15 跳
        lastTick = now;
        tone(ac, {from: 1200 * (extra.pitch || 1), dur: 0.015, gain: 0.025});
        break;
      }
    }
  }

  /* ---------- 小部件 ---------- */
  // key：同一类提示只留最新的一条（比如连着点几个没解锁的零件）
  function toast(html, key) {
    const shelf = document.querySelector('.toasts');
    if (!shelf) return;
    if (key) shelf.querySelectorAll(`[data-key="${key}"]`).forEach(old => old.remove());
    const item = document.createElement('div');
    if (key) item.dataset.key = key;
    item.className = 'toast';
    item.innerHTML = html;
    shelf.append(item);
    setTimeout(() => item.remove(), 3600);
  }
  // 数字滚动：+1 直接换数加回弹；更多就滚动，结尾回弹
  function countTo(element, to, {from = Number(element.textContent) || 0, duration = 600, onTick} = {}) {
    if (!element) return Promise.resolve();
    if (!motionOn() || to === from) { element.textContent = to; return Promise.resolve(); }
    if (Math.abs(to - from) === 1) {
      element.textContent = to;
      play(element, [{transform: 'scale(1.15)'}, {transform: 'scale(1)'}], {duration: 180, easing: B});
      return Promise.resolve();
    }
    return new Promise(resolve => {
      const start = performance.now();
      let shown = from;
      const step = () => {
        const k = Math.min(1, (performance.now() - start) / (duration * SLOW));
        const eased = 1 - Math.pow(1 - k, 3);
        const value = Math.round(from + (to - from) * eased);
        if (value !== shown) { shown = value; element.textContent = value; onTick?.(k); }
        if (k < 1) requestAnimationFrame(step);
        else { play(element, [{transform: 'scale(1.12)'}, {transform: 'scale(1)'}], {duration: 180, easing: B}); resolve(); }
      };
      requestAnimationFrame(step);
    });
  }
  window.bounty = {sfx, play, toast, countTo, motionOn, strength, A, B, C, D};

  /* ---------- 表单：防重复提交、校验失败时轻轻摇一下 ---------- */
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== 'post') return;
    if (form.dataset.clap !== undefined) return;
    form.setAttribute('aria-busy', 'true');
    form.querySelectorAll('button').forEach(button => button.setAttribute('aria-busy', 'true'));
    const action = form.dataset.actionForm || (form.dataset.quickClaim !== undefined ? 'claim' : '');
    if (action === 'claim') sfx('claim');
    if (action === 'submit') sfx('submit');
    if (action === 'return') sfx('return');
    if (action === 'accept' || action === 'close') sfx('stamp');
  });
  document.addEventListener('invalid', event => {
    const field = event.target;
    field.classList.remove('field-error');
    void field.offsetWidth;
    field.classList.add('field-error');
  }, true);
  document.addEventListener('input', event => event.target.classList?.remove('field-error'));

  // 验收时一键填夸奖
  document.querySelectorAll('[data-praise]').forEach(chip => chip.addEventListener('click', () => {
    const box = chip.closest('form').querySelector('textarea[name=body]');
    box.value = chip.dataset.praise;
    chip.closest('.praise').querySelectorAll('.chip').forEach(other => other.setAttribute('aria-pressed', String(other === chip)));
    play(chip, [{transform: 'scale(.92)'}, {transform: 'scale(1)'}], {duration: 200, easing: B});
    sfx('tap');
  }));

  /* ---------- 刚完成的操作：回执章落下 ---------- */
  const receipt = document.querySelector('[data-confirmed-action]');
  if (receipt) {
    const action = receipt.dataset.confirmedAction;
    // 回执带音效，延到章落地那一帧
    setTimeout(() => sfx(action === 'accept' ? 'stamp' : action === 'return' ? 'return' : action === 'submit' ? 'submit' : 'claim'), 200);
    if (action === 'accept') {
      const reward = document.querySelector('.done-card .medal');
      play(reward, [{transform: 'scale(1.12)'}, {transform: 'scale(1.12)', offset: .35}, {transform: 'scale(1)'}], {duration: 420, easing: B, delay: 260});
    }
  }

  /* ---------- 鼓掌：不刷新页面，挤压回弹 + "+1" 上飘 ---------- */
  document.querySelectorAll('form[data-clap]').forEach(form => form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    if (button.classList.contains('on')) {   // 已经鼓过掌，再点只给一点点反馈
      play(button, [{transform: 'scale(.94)'}, {transform: 'scale(1)'}], {duration: 160, easing: B});
      return;
    }
    const count = button.querySelector('span');
    const k = strength('clap');
    play(button, [{transform: 'scale(1)'}, {transform: `scale(${1 + .15 * k},${1 - .15 * k})`, offset: .2}, {transform: 'scale(1)'}], {duration: 250, easing: B});
    sfx('clap');
    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form), headers: {Accept: 'application/json'}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '没能鼓掌');
      button.classList.add('on');
      button.setAttribute('aria-pressed', 'true');
      countTo(count, data.claps);
      if (k === 1 && motionOn()) {
        const plus = document.createElement('span');
        plus.textContent = '+1';
        plus.style.cssText = 'position:absolute;font:800 12px var(--num);color:var(--ink);pointer-events:none';
        button.style.position = 'relative';
        button.append(plus);
        plus.animate([{transform: 'translate(-50%,0)', opacity: 1, left: '50%', top: '-6px'}, {transform: 'translate(-50%,-18px)', opacity: 0, left: '50%', top: '-6px'}], {duration: 500, easing: A}).finished.then(() => plus.remove());
      }
    } catch (error) {
      toast(`<span>${error.message}</span>`);
    }
  }));

  /* ---------- 领取勋章：按稀有度分档庆祝 ---------- */
  const stage = document.querySelector('[data-honor-reveal]');
  const dialog = document.querySelector('.award-dialog');
  if (stage && dialog) reveal(stage.dataset.honorReveal);

  async function reveal(url) {
    let data;
    try {
      const csrf = document.querySelector('meta[name=csrf-token]').content;
      const response = await fetch(url, {method: 'POST', body: new URLSearchParams({csrf}), headers: {Accept: 'application/json'}});
      data = await response.json();
    } catch { return; }
    const awards = data.awards || [];
    const together = data.bigs || [];
    const fresh = data.titles || [];
    if (!awards.length && !together.length && !fresh.length) return;
    // 柜子（case.js）要先听到"开始颁奖"，等页面上的脚本都跑完再开始
    if (document.readyState === 'loading') await new Promise(resolve => document.addEventListener('DOMContentLoaded', resolve, {once: true}));
    const template = document.querySelector('template[data-medal-template]');
    const medalSvg = key => template.content.querySelector(`[data-key="${key}"]`).innerHTML;
    const items = dialog.querySelector('[data-award-items]');
    const label = dialog.querySelector('[data-award-label]');
    const featureButton = dialog.querySelector('[data-award-feature]');
    // 先一枚枚发勋章，再拼大任务的图，最后一个个盖称号
    const queue = [...awards.map(award => ({type: 'medal', ...award})), ...together.map(big => ({type: 'big', ...big})),
                   ...fresh.map(title => ({type: 'title', ...title}))];
    // 涨经验的是勋章和大任务，它们排在队伍前面
    const gains = queue.filter(item => item.type !== 'title');
    const xpTotal = gains.reduce((sum, item) => sum + item.xp, 0);
    const unlocks = data.unlocks || [];
    const leveled = gains.length && data.after.level > data.before.level;
    let index = 0;
    let skipped = !motionOn();
    let timers = [];
    const later = (fn, ms) => { if (skipped) { fn(); return; } timers.push(setTimeout(fn, ms * SLOW)); };

    // 列表写全：读屏和"看一眼都拿到了什么"都能直接读到
    items.innerHTML = `<ol class="sr-only">${queue.map(item => `<li>${item.type === 'title' ? `称号：${escapeHtml(item.name)}` : item.type === 'big' ? `大任务完成：${escapeHtml(item.title)}` : `${item.name}：${escapeHtml(item.title)}`}</li>`).join('')}</ol><div class="award-show"></div>`;
    const show = items.querySelector('.award-show');
    const counter = () => queue.length > 1 ? `<span class="award-count">${index + 1} / ${queue.length}</span>` : '';

    function summary(final) {
      if (!final || queue.length < 2) return {title: '解锁称号', big: '合力'}[queue[index].type] || '验收通过';
      const parts = [];
      if (awards.length) parts.push(`${awards.length} 枚勋章`);
      if (together.length) parts.push(`${together.length} 个大任务`);
      if (gains.length) parts.push(`+${xpTotal} 经验`);
      if (fresh.length) parts.push(`${fresh.length} 个称号`);
      return `一共 ${parts.join(' · ')}`;
    }

    function render(award, final) {
      const tier = award.debut ? '你的第一枚勋章' : {all: '全收集！六种都齐了', row: `${award.row}集齐！`, new: '新的一种'}[award.tier] || '';
      const praise = award.praise && award.praise !== '成果验收通过。' ? award.praise : '';
      show.innerHTML = `
        <div class="award-medal">${medalSvg(award.medal_key)}<div class="burst">${burstPieces(award)}</div>${award.debut ? '<span class="hanko n1 award-debut" style="--c:#E54465"><i>初</i></span>' : ''}</div>
        ${tier ? `<span class="award-tier${award.tier === 'all' ? ' gold' : ''}">${tier}</span>` : ''}
        <h2 class="award-name" id="award-title">${award.name}</h2>
        <p class="award-kind">「${escapeHtml(award.title)}」 · ${escapeHtml(award.owner)} 验收${award.bonus ? ` · <b>冷门 +${award.bonus}</b>` : ''}</p>
        ${praise ? `<p class="award-praise">${escapeHtml(praise)}<cite>— ${escapeHtml(award.owner)}</cite></p>` : ''}
        <div class="award-meter" data-meter><span class="lv num" data-lv>Lv.${data.before.level}</span><span class="bar" style="--fill:var(--yellow)"><i style="width:${data.before.percent}%"></i></span><em><span data-xp>+0</span> 经验</em></div>
        ${award.opens?.length ? `<p class="award-opens"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="3" y="7" width="18" height="11" rx="5.5"/><path d="M8 10.5v4M6 12.5h4"/></svg><span>縁側解锁：${award.opens.map(escapeHtml).join('、')}</span></p>` : ''}
        ${counter()}`;
      label.textContent = summary(final);
      featureButton.textContent = '放上名牌';
    }

    const meterHtml = () => `<div class="award-meter" data-meter><span class="lv num" data-lv>Lv.${data.before.level}</span><span class="bar" style="--fill:var(--yellow)"><i style="width:${data.before.percent}%"></i></span><em><span data-xp>+0</span> 经验</em></div>`;
    const opensHtml = item => item.opens?.length ? `<p class="award-opens"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="3" y="7" width="18" height="11" rx="5.5"/><path d="M8 10.5v4M6 12.5h4"/></svg><span>縁側解锁：${item.opens.map(escapeHtml).join('、')}</span></p>` : '';

    // 大任务：拼图一块块落下来，自己做的那几块带白点
    function renderBig(big, final) {
      const part = big.lead ? (big.pieces ? `你牵头，还做完了 ${big.pieces} 份` : '你牵头') : `你做完了 ${big.pieces} 份`;
      show.innerHTML = `
        <div class="award-big">${big.mosaic}</div>
        <span class="award-tier">大任务完成</span>
        <h2 class="award-name" id="award-title">${escapeHtml(big.title)}</h2>
        <p class="award-kind">${part} · ${big.people} 个人一起 · ${escapeHtml(big.owner)} 收尾</p>
        ${big.closing ? `<p class="award-praise">${escapeHtml(big.closing)}<cite>— ${escapeHtml(big.owner)}</cite></p>` : ''}
        ${meterHtml()}
        ${opensHtml(big)}
        ${counter()}`;
      label.textContent = summary(final);
      featureButton.textContent = '去看看';
    }

    function bigSequence(big) {
      renderBig(big, index === queue.length - 1);
      const tiles = [...show.querySelectorAll('.award-big .mt')];
      const rest = ['.award-tier', '.award-name', '.award-kind', '.award-praise', '[data-meter]', '.award-opens'].map(q => show.querySelector(q)).filter(Boolean);
      const meter = show.querySelector('[data-meter]');
      if (skipped) {
        finishMeter(meter, big, true);
        return;
      }
      rest.forEach(el => { el.style.opacity = 0; });
      tiles.forEach(tile => { tile.style.opacity = 0; });
      const step = Math.max(50, Math.min(110, 900 / tiles.length));
      tiles.forEach((tile, i) => later(() => {
        tile.style.opacity = 1;
        play(tile, [{transform: 'translateY(-14px) scale(.3)', opacity: 0}, {transform: 'scale(1.12)', opacity: 1, offset: .6}, {transform: 'none'}], {duration: 380, easing: B});
        sfx('tick', {pitch: 1 + i / tiles.length * .6});
      }, 220 + i * step));
      const done = 220 + tiles.length * step + 260;
      later(() => {
        const box = show.querySelector('.award-big');
        play(box, [{transform: 'scale(1)'}, {transform: 'scale(1.05)'}, {transform: 'scale(1)'}], {duration: 420, easing: B});
        flash(box);
        sfx('set');
        rest.forEach((el, i) => {
          el.style.opacity = 1;
          play(el, [{opacity: 0, transform: 'translateY(8px)'}, {opacity: 1, transform: 'none'}], {duration: 280, delay: i * 70, easing: C});
        });
      }, done);
      later(() => finishMeter(meter, big, false), done + 420);
    }

    function renderTitle(title, final) {
      show.innerHTML = `
        <div class="award-seal"><span class="hanko n${title.name.length}" style="--c:${title.color}"><i>${escapeHtml(title.name)}</i></span></div>
        <span class="award-tier">新称号</span>
        <h2 class="award-name" id="award-title">${escapeHtml(title.name)}</h2>
        <p class="award-kind">${escapeHtml(title.how)}</p>
        ${counter()}`;
      label.textContent = summary(final);
      featureButton.textContent = '盖到名牌上';
    }

    function burstPieces(award) {
      if (award.tier === 'plain' && !award.debut) return '';
      const colors = ['#00A27A', '#2866B1', '#1B1D2A', '#F2B700', '#E54465', '#00AEE0', '#F39800', '#1B1D2A'];
      const count = {all: 24, row: 14}[award.tier] || 8;
      const reach = award.tier === 'all' ? 170 : 120;
      return Array.from({length: count}, (_, i) => {
        const angle = (i / count) * Math.PI * 2 + (i % 2) * 0.3;
        const distance = reach + (i % 3) * 30;
        return `<i style="--x:${Math.round(Math.cos(angle) * distance)}px;--y:${Math.round(Math.sin(angle) * distance)}px;--s:${8 + (i % 3) * 6}px;--c:${colors[i % colors.length]};--r:${i % 3 === 1 ? '3px' : '50%'};--rot:${i * 37}deg;--delay:${i * 20}ms"></i>`;
      }).join('');
    }

    function sequence(award) {
      render(award, index === queue.length - 1);
      const medal = show.querySelector('.award-medal');
      const svg = medal.querySelector('.medal');
      const name = show.querySelector('.award-name');
      const tierTag = show.querySelector('.award-tier');
      const meter = show.querySelector('[data-meter]');
      const praise = show.querySelector('.award-praise');
      const seal = show.querySelector('.award-debut');
      const opens = show.querySelector('.award-opens');
      // 总长按稀有度分档：普通 ≈0.8s，新种类 ≈1.5s，集齐一行 ≈3s，全收集再长一点
      const hold = award.tier === 'all' ? 1400 : {plain: 0, new: 400, row: 900}[award.tier];
      if (skipped) {
        svg.classList.remove('anim');
        finishMeter(meter, award, true);
        return;
      }
      [name, tierTag, praise, meter, seal, opens].forEach(el => el && (el.style.opacity = 0));
      // 1) 先停在灰色虚线剪影，让人看清楚"要变成什么"
      svg.style.filter = 'grayscale(1) opacity(.35)';
      later(() => {
        // 2) 打击：放大停住再落回 + 白闪，同时出声
        svg.style.filter = '';
        svg.classList.add('anim');
        play(medal, [{transform: 'scale(.6)'}, {transform: 'scale(1.1)', offset: .55}, {transform: 'scale(1.1)', offset: .7}, {transform: 'scale(1)'}], {duration: 540, easing: C});
        flash(medal);
        sfx('medal', {pitch: award.tier === 'plain' ? 1 : 1.12});
        if (award.tier !== 'plain' || award.debut) medal.classList.add('go');
      }, 360);
      later(() => {
        name.style.opacity = 1;
        play(name, [{transform: 'scaleX(.2)', opacity: 0}, {transform: 'scaleX(1)', opacity: 1}], {duration: 300, easing: B});
        if (tierTag) {
          tierTag.style.opacity = 1;
          play(tierTag, [{transform: 'scale(1.8) rotate(-18deg)', opacity: 0}, {transform: 'scale(1) rotate(-3deg)', opacity: 1}], {duration: 360, easing: B});
          if (award.tier === 'row' || award.tier === 'all') sfx('set');
        }
        if (seal) {   // 第一枚：右上角盖一个「初」
          seal.style.opacity = 1;
          play(seal, [{transform: 'scale(2.2) rotate(-30deg)', opacity: 0}, {transform: 'scale(.9) rotate(-8deg)', opacity: 1, offset: .6}, {transform: 'scale(1) rotate(-8deg)'}], {duration: 380, easing: D});
          later(() => sfx('stamp'), 220);
        }
      }, 620 + hold / 2);
      if (award.tier === 'all') later(() => { play(medal, [{transform: 'scale(1)'}, {transform: 'scale(1.16)'}, {transform: 'scale(1)'}], {duration: 520, easing: B}); sfx('level'); }, 620 + hold / 2 + 380);
      later(() => {
        if (praise) { praise.style.opacity = 1; play(praise, [{opacity: 0, transform: 'translateY(8px)'}, {opacity: 1, transform: 'none'}], {duration: 280, easing: C}); }
        meter.style.opacity = 1;
        finishMeter(meter, award, false);
      }, 860 + hold);
      if (opens) later(() => {
        opens.style.opacity = 1;
        play(opens, [{opacity: 0, transform: 'translateY(6px) scale(.96)'}, {opacity: 1, transform: 'none'}], {duration: 320, easing: B});
        sfx('tap');
      }, 1300 + hold);
    }

    // 称号：印章从高处砸下来，停一下，横向小震
    function titleSequence(title) {
      renderTitle(title, index === queue.length - 1);
      const seal = show.querySelector('.award-seal');
      const name = show.querySelector('.award-name');
      const tierTag = show.querySelector('.award-tier');
      const how = show.querySelector('.award-kind');
      if (skipped) return;
      [seal, name, tierTag, how].forEach(el => { el.style.opacity = 0; });
      later(() => {
        seal.style.opacity = 1;
        play(seal, [{transform: 'translateY(-40px) scale(2.4) rotate(-24deg)', opacity: 0}, {transform: 'scale(.94)', opacity: 1, offset: .5}, {transform: 'scale(.94)', offset: .7}, {transform: 'none'}], {duration: 520, easing: D});
        later(() => {
          sfx('stamp');
          play(show, [{transform: 'translateX(3px)'}, {transform: 'translateX(-3px)'}, {transform: 'translateX(2px)'}, {transform: 'none'}], {duration: 200});
        }, 240);
      }, 260);
      later(() => {
        [tierTag, name, how].forEach((el, i) => {
          el.style.opacity = 1;
          play(el, [{opacity: 0, transform: 'translateY(8px)'}, {opacity: 1, transform: 'none'}], {duration: 280, delay: i * 80, easing: C});
        });
      }, 760);
    }

    function finishMeter(meter, award, instant) {
      const xp = meter.querySelector('[data-xp]');
      const bar = meter.querySelector('.bar i');
      const lv = meter.querySelector('[data-lv]');
      const last = index === gains.length - 1;
      const target = last ? data.after : null;
      const gained = gains.slice(0, index + 1).reduce((sum, a) => sum + a.xp, 0);
      if (instant) {
        xp.textContent = `+${gained}`;
        if (last) applyLevel(meter, lv, bar, true);
        return;
      }
      countTo(xp, gained, {from: gained - award.xp, duration: 500, onTick: k => sfx('tick', {pitch: 1 + k * .5})})
        .then(() => { xp.textContent = `+${gained}`; });
      bar.style.transition = 'width 600ms cubic-bezier(.16,1,.3,1)';
      requestAnimationFrame(() => { bar.style.width = `${last ? target.percent : Math.min(100, data.before.percent + gained / data.before.span * 100)}%`; });
      if (last) later(() => applyLevel(meter, lv, bar, false), 620);
    }

    function applyLevel(meter, lv, bar, instant) {
      if (!leveled) return;
      meter.classList.add('up');
      lv.textContent = `Lv.${data.after.level}`;
      meter.querySelector('em').textContent = `升级！${data.after.name}`;
      bar.style.width = `${data.after.percent}%`;
      if (instant) return;
      // 升级是最大的节点：打击停顿 + 横向小震
      play(lv, [{transform: 'scale(1.6)'}, {transform: 'scale(1.6)', offset: .3}, {transform: 'scale(1)'}], {duration: 420, easing: B});
      play(meter, [{transform: 'translateX(3px)'}, {transform: 'translateX(-3px)'}, {transform: 'translateX(2px)'}, {transform: 'none'}], {duration: 200, delay: 120});
      sfx('level');
    }

    function flash(element) {
      if (!motionOn()) return;
      const glow = document.createElement('span');
      glow.style.cssText = 'position:absolute;inset:-10%;border-radius:50%;background:radial-gradient(circle,rgba(255,255,255,.95),rgba(255,248,220,0) 70%);pointer-events:none';
      element.append(glow);
      glow.animate([{opacity: 0}, {opacity: 1, offset: .2}, {opacity: 0}], {duration: 360, easing: A}).finished.then(() => glow.remove());
    }

    function showItem() {
      const item = queue[index];
      if (item.type === 'title') titleSequence(item); else if (item.type === 'big') bigSequence(item); else sequence(item);
    }

    function next() {
      timers.forEach(clearTimeout);
      timers = [];
      showItem();
      // 一个播完、停一拍再下一个；越稀有停得越久
      const item = queue[index];
      const wait = item.type === 'title' ? 2300 : item.type === 'big' ? 3600 : item.tier === 'all' ? 4300 : {plain: 1900, new: 2500, row: 3400}[item.tier] + (item.debut ? 400 : 0);
      if (index < queue.length - 1) later(() => { index += 1; next(); }, wait);
    }

    function skip() {
      if (skipped) return;
      skipped = true;
      timers.forEach(clearTimeout);
      index = queue.length - 1;
      dialog.getAnimations({subtree: true}).forEach(a => a.finish());
      showItem();
      dialog.querySelector('[data-award-skip]').hidden = true;
    }

    dialog.querySelector('[data-award-skip]').addEventListener('click', skip);
    dialog.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); skipped ? close() : skip(); } });
    dialog.querySelector('.award-stage').addEventListener('click', event => {
      if (!event.target.closest('a,button')) skip();
    });
    dialog.querySelector('[data-close-awards]').addEventListener('click', event => { event.preventDefault(); close(); });
    featureButton.addEventListener('click', async () => {
      const item = queue[index];
      close();
      if (item.type === 'big') {
        location.assign(`/big/${item.big_id}`);
        return;
      }
      if (item.type === 'title') {
        // 称号：直接盖到名牌上，刷新名牌
        const body = new URLSearchParams({csrf: document.querySelector('meta[name=csrf-token]').content, title: item.key});
        const response = await fetch('/honors/title', {method: 'POST', body, headers: {Accept: 'application/json'}}).catch(() => null);
        if (response?.ok) setTimeout(() => location.assign('/honors#titles'), motionOn() ? 900 : 0);
        return;
      }
      const editor = document.querySelector('.shelf-editor');
      if (!editor) return;
      editor.open = true;
      const checked = editor.querySelectorAll('input[name=medals]:checked').length;
      const box = editor.querySelector(`input[name=medals][value="${awards[awards.length - 1].medal_key}"]`);
      if (box && !box.checked && checked < 3) box.checked = true;
      editor.scrollIntoView({behavior: motionOn() ? 'smooth' : 'auto', block: 'center'});
    });

    function close() {
      timers.forEach(clearTimeout);
      skipped = true;
      dialog.close();
      // 收进勋章柜：case.js 让它们从屏幕中央飞回各自的格子；新称号在称号墙上标出来
      if (awards.length) document.dispatchEvent(new CustomEvent('bounty:collected', {detail: {awards}}));
      fresh.forEach(title => document.querySelector(`[data-title-key="${title.key}"]`)?.classList.add('fresh'));
      const mailbox = document.querySelector('.mailbox');
      mailbox?.classList.remove('has-mail');
      mailbox?.querySelector('b')?.remove();
      if (awards.length) {
        toast(`${medalSvg(awards[awards.length - 1].medal_key)}<span>收进勋章柜</span><em>+${xpTotal} 经验${awards.length > 1 ? ` · ×${awards.length}` : ''}</em>`);
        // 这批勋章让縁側多了东西（积木颜色、零件、玩法）：再报一声
        if (unlocks.length) setTimeout(() => {
          toast(`<span>縁側解锁：${unlocks.slice(0, 2).map(escapeHtml).join('、')}${unlocks.length > 2 ? ` 等 ${unlocks.length} 样` : ''}</span>`);
          sfx('set');
        }, motionOn() ? 900 : 0);
      } else if (together.length) {
        toast(`<span>合力纪念收好了</span><em>+${xpTotal} 经验</em>`);
        if (unlocks.length) setTimeout(() => toast(`<span>縁側解锁：${unlocks.slice(0, 2).map(escapeHtml).join('、')}</span>`), motionOn() ? 900 : 0);
      } else {
        toast(`<span class="hanko n${fresh[0].name.length}" style="--c:${fresh[0].color}"><i>${escapeHtml(fresh[0].name)}</i></span><span>解锁了${fresh.length > 1 ? ` ${fresh.length} 个` : ''}称号</span>`);
      }
    }

    dialog.showModal();
    document.dispatchEvent(new CustomEvent('bounty:reveal-start', {detail: {awards}}));
    sfx('stamp');
    next();
  }

  function escapeHtml(text) {
    return String(text ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }
})();
