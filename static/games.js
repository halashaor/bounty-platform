/* 縁側的两个小游戏，随便玩，不花任何东西。手感工具（音效、动画、数字滚动）来自 ui.js 的 window.bounty。
   - 一笔画：拖着或一个点一个点地连，走完所有的线就提交给服务器检查。固定关卡、每日一笔、随机一笔共用这一套。
   - 盖章挑战：几十秒的节奏游戏。完美判定时打击停顿 70ms、单子横向小震，连击每 10 下倍数涨一档。 */
(() => {
  const feel = window.bounty || {play() { return null; }, sfx() {}, toast() {}, countTo(el, to) { el.textContent = to; return Promise.resolve(); }, motionOn: () => false, A: 'ease', B: 'ease', C: 'ease', D: 'ease'};
  const csrf = () => document.querySelector('meta[name=csrf-token]')?.content || '';
  const HUES = ['#E54465', '#F39800', '#F2B700', '#00A27A', '#00AEE0', '#2866B1'];
  const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const hanko = title => `<span class="hanko n${[...title.name].length}" style="--c:${title.color}"><i>${esc(title.name)}</i></span>`;
  async function post(url, fields = {}) {
    const body = new URLSearchParams({csrf: csrf(), ...fields});
    const response = await fetch(url, {method: 'POST', body, headers: {Accept: 'application/json'}});
    const data = await response.json().catch(() => ({error: '出了点问题，稍后再试'}));
    if (!response.ok) throw new Error(data.error || '出了点问题，稍后再试');
    return data;
  }
  /* ================= 一笔画 ================= */
  const board = document.querySelector('[data-board]');
  if (board) lines();
  function lines() {
    const level = JSON.parse(document.getElementById('level-data').textContent);
    const {nodes, edges} = level;
    const trail = board.querySelector('[data-trail]');
    const rubber = board.querySelector('[data-rubber]');
    const nodeEls = [...board.querySelectorAll('[data-node]')];
    const edgeEls = [...board.querySelectorAll('[data-edge]')];
    const progress = document.querySelector('[data-progress]');
    const undoButton = document.querySelector('[data-undo]');
    const resetButton = document.querySelector('[data-reset]');
    const solvedBox = document.querySelector('[data-solved]');
    const path = [];
    const used = [];
    let dragging = false;
    let done = false;
    const edgeBetween = (a, b) => edges.findIndex(([x, y], i) => !used.includes(i) && ((x === a && y === b) || (x === b && y === a)));
    const degree = nodes.map((_, n) => edges.filter(([a, b]) => a === n || b === n).length);

    function point(event) {
      const p = board.createSVGPoint();
      p.x = event.clientX;
      p.y = event.clientY;
      return p.matrixTransform(board.getScreenCTM().inverse());
    }
    function nearest(p, radius = 9) {
      let best = null;
      let bestDistance = radius;
      nodes.forEach(([x, y], n) => {
        const d = Math.hypot(p.x - x, p.y - y);
        if (d < bestDistance) { best = n; bestDistance = d; }
      });
      return best;
    }
    function paint() {
      progress.textContent = used.length;
      undoButton.disabled = resetButton.disabled = !path.length || done;
      nodeEls.forEach((el, n) => {
        el.classList.toggle('on', path.includes(n));
        el.classList.toggle('end', n === path[path.length - 1]);
        el.classList.toggle('stuck', !done && n === path[path.length - 1] && used.length < edges.length &&
          !edges.some(([a, b], i) => !used.includes(i) && (a === n || b === n)));
      });
      edgeEls.forEach((el, i) => el.classList.toggle('used', used.includes(i)));
    }
    function start(n) {
      path.push(n);
      feel.play(nodeEls[n], [{r: 3.8}, {r: 6.4}, {r: 3.8}], {duration: 260, easing: feel.B});
      feel.sfx('tap');
      paint();
    }
    function step(to) {
      const from = path[path.length - 1];
      const i = edgeBetween(from, to);
      if (i < 0) return false;
      used.push(i);
      path.push(to);
      const [x1, y1] = nodes[from];
      const [x2, y2] = nodes[to];
      const seg = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      Object.entries({x1, y1, x2, y2}).forEach(([k, v]) => seg.setAttribute(k, v));
      seg.setAttribute('class', 'trail');
      seg.style.stroke = HUES[(used.length - 1) % HUES.length];
      const length = Math.hypot(x2 - x1, y2 - y1);
      seg.style.strokeDasharray = length;
      trail.append(seg);
      feel.play(seg, [{strokeDashoffset: length}, {strokeDashoffset: 0}], {duration: 140, easing: feel.C});
      feel.play(nodeEls[to], [{r: 3.8}, {r: 6}, {r: 3.8}], {duration: 240, easing: feel.B});
      // 越接近完成音越高
      feel.sfx('tick', {pitch: 1 + used.length / edges.length});
      paint();
      if (used.length === edges.length) finish();
      else if (!edges.some(([a, b], k) => !used.includes(k) && (a === to || b === to))) {
        feel.play(nodeEls[to], [{transform: 'translateX(1.5px)'}, {transform: 'translateX(-1.5px)'}, {transform: 'none'}], {duration: 200});
        feel.sfx('return');
      }
      return true;
    }
    function undo() {
      if (!path.length || done) return;
      if (used.length) { used.pop(); trail.lastElementChild?.remove(); }
      path.pop();
      feel.sfx('tap');
      paint();
    }
    function reset() {
      path.length = 0;
      used.length = 0;
      trail.replaceChildren();
      paint();
    }

    board.addEventListener('pointerdown', event => {
      if (done) return;
      const n = nearest(point(event), 11);
      if (n === null) return;
      event.preventDefault();
      board.setPointerCapture(event.pointerId);
      if (!path.length) start(n);
      else if (n === path[path.length - 1]) { /* 从终点接着画 */ }
      else if (!step(n)) {
        // 点回上一个点 = 撤销一步；点别处给个"不行"的提示
        if (n === path[path.length - 2]) undo();
        else feel.play(nodeEls[n], [{transform: 'translateX(1.5px)'}, {transform: 'translateX(-1.5px)'}, {transform: 'none'}], {duration: 180});
      }
      dragging = true;
    });
    board.addEventListener('pointermove', event => {
      if (!dragging || done || !path.length) return;
      const p = point(event);
      const [x, y] = nodes[path[path.length - 1]];
      rubber.setAttribute('x1', x); rubber.setAttribute('y1', y);
      rubber.setAttribute('x2', p.x); rubber.setAttribute('y2', p.y);
      rubber.classList.add('show');
      const n = nearest(p, 6.5);
      if (n === null || n === path[path.length - 1]) return;
      if (!step(n) && n === path[path.length - 2] && used.length) undo();   // 拖回去也是撤销
    });
    const stop = () => { dragging = false; rubber.classList.remove('show'); };
    board.addEventListener('pointerup', stop);
    board.addEventListener('pointercancel', stop);
    undoButton.addEventListener('click', undo);
    resetButton.addEventListener('click', () => { reset(); feel.sfx('tap'); });
    document.querySelector('[data-hint]').addEventListener('click', () => {
      const odd = degree.map((d, n) => d % 2 ? n : -1).filter(n => n >= 0);
      if (!odd.length) feel.toast('<span>每个点都连着偶数条线：从哪里出发都行，最后会回到起点。</span>');
      else {
        odd.forEach(n => nodeEls[n].classList.add('odd'));
        feel.toast('<span>标出来的两个点连着奇数条线：从其中一个出发，到另一个结束。</span>');
      }
      feel.sfx('tap');
    });
    document.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'z') { event.preventDefault(); undo(); }
    });

    async function finish() {
      done = true;
      paint();
      let result;
      try {
        result = await post(board.dataset.solve, {stroke: path.join(',')});
      } catch (error) {
        done = false;
        feel.toast(`<span>${esc(error.message)}</span>`);
        return;
      }
      // 通关：线一条条亮一遍，点依次弹起来，印章砸下
      board.classList.add('cleared');
      [...trail.children].forEach((seg, i) => feel.play(seg, [{strokeWidth: 3.2}, {strokeWidth: 6}, {strokeWidth: 3.2}], {duration: 360, delay: i * 45, easing: feel.B}));
      nodeEls.forEach((el, i) => feel.play(el, [{r: 3.8}, {r: 6.6}, {r: 3.8}], {duration: 320, delay: 200 + i * 40, easing: feel.B}));
      feel.sfx('set');
      setTimeout(() => showSolved(result), feel.motionOn() ? 520 : 0);
    }
    function showSolved(result) {
      solvedBox.hidden = false;
      const current = document.querySelector('.lvl.now');
      current?.classList.add('solved');
      // 下一关的锁当场打开，不用刷新
      const locked = current?.closest('li')?.nextElementSibling?.querySelector('.lvl.locked');
      if (locked && result.next) locked.outerHTML = `<a class="lvl" href="${result.next}">${Number(current.textContent) + 1}</a>`;
      const count = document.querySelector(`[data-count="${level.kind}"]`);
      if (count) count.textContent = level.kind === 'daily' ? `${result.label} ${result.solved} / ${result.total}` : `画完 ${result.solved} / ${result.total}`;
      const actions = solvedBox.querySelector('[data-solved-actions]');
      const text = solvedBox.querySelector('[data-solved-text]');
      if (level.kind === 'daily') {
        document.querySelector('[data-daily-count]')?.replaceChildren(String(result.daily));
        text.textContent = result.solved === result.total
          ? `${result.label}的 ${result.total} 关全画完了！一共 ${result.daily} 人全画完。明天零点换新的一套。`
          : `一笔走完 ${edges.length} 条线。${result.label}画完 ${result.solved} / ${result.total} 关，下一关更难一点。`;
      } else if (level.kind === 'random') {
        text.textContent = `一笔走完 ${edges.length} 条线。`;
      } else {
        text.textContent = result.solved === result.total ? `全部 ${result.total} 关都画完了！` : `一笔走完 ${edges.length} 条线。已经画完 ${result.solved} / ${result.total} 关。`;
      }
      let html = '';
      if (result.next) html += `<a class="btn" href="${result.next}">${level.kind === 'random' ? '再来一题' : '下一关'}</a>`;
      html += '<button type="button" class="btn btn-line" data-replay>再画一次</button>';
      actions.innerHTML = html;
      if (result.titles?.length) actions.insertAdjacentHTML('beforebegin', `<div class="solved-titles">${result.titles.map(t => `${hanko(t)}<span>解锁称号「${esc(t.name)}」</span>`).join('')}</div>`);
      feel.play(solvedBox.querySelector('.solved-stamp'), [{transform: 'scale(2.4) rotate(-24deg)', opacity: 0}, {transform: 'scale(.92) rotate(-8deg)', opacity: 1, offset: .6}, {transform: 'rotate(-8deg)'}], {duration: 420, easing: feel.D});
      feel.play(solvedBox, [{opacity: 0, transform: 'translateY(12px)'}, {opacity: 1, transform: 'none'}], {duration: 320, easing: feel.C});
      setTimeout(() => feel.sfx('stamp'), 200);
      actions.querySelector('[data-replay]').addEventListener('click', () => {
        solvedBox.hidden = true;
        solvedBox.querySelector('.solved-titles')?.remove();
        board.classList.remove('cleared');
        done = false;
        reset();
      });
    }
    paint();
  }

  /* ================= 盖章挑战 ================= */
  const stage = document.querySelector('[data-stamp-game]');
  if (stage) stampGame();
  function stampGame() {
    let SECONDS = 30;
    let cfg = {speed: 1, urgent: 0.18, void: 0.15};
    let maxSlips = 72;
    const belt = stage.querySelector('[data-belt]');
    const stamper = stage.querySelector('[data-stamper]');
    const judge = stage.querySelector('[data-judge]');
    const scoreEl = stage.querySelector('[data-score]');
    const comboEl = stage.querySelector('[data-combo]');
    const comboBox = stage.querySelector('[data-combo-box]');
    const multEl = stage.querySelector('[data-mult]');
    const timeEl = stage.querySelector('[data-time]');
    const cover = stage.querySelector('[data-cover]');
    const result = stage.querySelector('[data-result]');
    const WORDS = ['造数据', '写题解', '复现 baseline', '跑消融', '整理题单', '修评测机', '标注样例', '讲图论', '对比 GNN', '查内存', '清洗数据', '改报名表', '读论文', '加单测', '订机房', '写纪要'];
    let run = null;
    let slips = [];
    let raf = 0;
    let state = 'idle';
    let clock = 0;        // 游戏时间（打击停顿时不走）
    let last = 0;
    let freezeUntil = 0;
    let nextSpawn = 0;
    let score = 0, combo = 0, best = 0, perfect = 0, good = 0, miss = 0, spawned = 0, lastSecond = SECONDS;
    const width = () => belt.clientWidth;
    const scale = () => Math.max(0.6, Math.min(1.2, width() / 900));
    const mult = () => Math.min(3, 1 + Math.floor(combo / 10) * 0.5);

    // 玩法和印章样式：玩法每局开始时交给服务器，印章只是好看，记在这台设备上
    const modeInput = () => stage.querySelector('input[name=mode]:checked');
    const styleInput = () => stage.querySelector('input[name=style]:checked');
    try {
      const saved = localStorage.getItem('bounty-stamp-style');
      const input = saved && stage.querySelector(`input[name=style][value="${saved}"]:not(:disabled)`);
      if (input) input.checked = true;
    } catch { /* 隐私模式下不记 */ }
    function paintStyle() {
      const input = styleInput();
      const head = stamper.querySelector('.stamper-head i');
      head.className = `face-${input.value}`;
      head.style.setProperty('--c', input.dataset.color || '');
      head.innerHTML = input.value === 'dlm' ? stage.querySelector('.face-dlm').innerHTML : esc(input.dataset.text);
      try { localStorage.setItem('bounty-stamp-style', input.value); } catch { /* 隐私模式下不记 */ }
    }
    function paintMode() {
      const label = modeInput().closest('.pick-mode');
      document.querySelector('[data-mode-label]').textContent = label.dataset.name;
      document.querySelector('[data-best]').textContent = label.dataset.bestScore;
      document.querySelector('[data-best-combo]').textContent = label.dataset.bestCombo;
    }
    stage.addEventListener('change', event => {
      if (event.target.name === 'style') { paintStyle(); feel.sfx('tap'); }
      if (event.target.name === 'mode') { paintMode(); feel.sfx('tap'); }
    });
    paintStyle();

    async function begin() {
      if (state === 'starting' || state === 'playing') return;
      state = 'starting';
      try {
        run = await post(stage.dataset.start, {mode: modeInput().value});
      } catch (error) {
        state = 'idle';
        feel.toast(`<span>${esc(error.message)}</span>`);
        return;
      }
      SECONDS = run.seconds;
      cfg = run;
      maxSlips = Math.floor(SECONDS * 2.4);
      cover.hidden = true;
      result.hidden = true;
      slips.forEach(s => s.el.remove());
      slips = [];
      score = combo = best = perfect = good = miss = spawned = 0;
      clock = 0; nextSpawn = 0.6; lastSecond = SECONDS; freezeUntil = 0;
      paintHud();
      // 3、2、1
      for (const n of ['3', '2', '1']) {
        say(n, 'count');
        feel.sfx('tick', {pitch: 1});
        await new Promise(resolve => setTimeout(resolve, 520));
      }
      say('开始！', 'go');
      feel.sfx('claim');
      state = 'playing';
      last = performance.now();
      raf = requestAnimationFrame(loop);
    }

    function spawn() {
      const t = clock / SECONDS;
      const roll = Math.random();
      const kind = clock > 4 && roll < cfg.void ? 'void' : roll < cfg.void + cfg.urgent ? 'urgent' : 'normal';
      const el = document.createElement('div');
      el.className = `slip ${kind}`;
      el.innerHTML = `<b>${kind === 'void' ? '退回' : kind === 'urgent' ? '加急' : '任务单'}</b><span>${WORDS[spawned % WORDS.length]}</span><i class="slip-target"></i>`;
      belt.append(el);
      const speed = (250 + 270 * t) * cfg.speed * scale() * (kind === 'urgent' ? 1.45 : 1);
      slips.push({el, kind, x: width() + 90, speed, stamped: false, passed: false, half: el.offsetWidth / 2});
      spawned += 1;
      // 期末周：时不时一口气来两三张
      const gap = Math.max(0.5, 1.15 - 0.6 * t) / cfg.speed * (0.8 + Math.random() * 0.4);
      nextSpawn = clock + (run.mode === 'finals' && Math.random() < 0.3 ? Math.max(0.42, gap * 0.45) : gap);
    }

    function loop(now) {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (now >= freezeUntil) {
        clock += dt;
        if (clock >= nextSpawn && clock < SECONDS - 0.8 && spawned < maxSlips) spawn();
        const center = width() / 2;
        slips.forEach(slip => {
          slip.x -= slip.speed * dt;
          slip.el.style.transform = `translate(${slip.x - slip.half}px,-50%)`;
          // 普通单子过了印章还没盖：漏了
          if (!slip.stamped && !slip.passed && slip.x < center - 46) {
            slip.passed = true;
            if (slip.kind !== 'void') { breakCombo('漏了'); slip.el.classList.add('missed'); }
          }
        });
        slips = slips.filter(slip => { if (slip.x < -120) { slip.el.remove(); return false; } return true; });
        const left = Math.max(0, SECONDS - clock);
        timeEl.style.width = `${left / SECONDS * 100}%`;
        stage.classList.toggle('hurry', left < 5);
        if (left < 5 && Math.ceil(left) < lastSecond) { lastSecond = Math.ceil(left); feel.sfx('tick', {pitch: 1.6}); }
        if (left <= 0) return end();
      }
      raf = requestAnimationFrame(loop);
    }

    function hit() {
      if (state !== 'playing') return;
      // 印章砸下来
      feel.play(stamper, [{transform: 'translate(-50%,0)'}, {transform: 'translate(-50%,46px)', offset: .35}, {transform: 'translate(-50%,46px)', offset: .55}, {transform: 'translate(-50%,0)'}], {duration: 170, easing: 'linear'});
      const center = width() / 2;
      const slip = slips.filter(s => !s.stamped).sort((a, b) => Math.abs(a.x - center) - Math.abs(b.x - center))[0];
      const off = slip ? Math.abs(slip.x - center) : Infinity;
      if (!slip || off > 46) { breakCombo('空盖'); feel.sfx('tap'); return; }
      slip.stamped = true;
      const mark = document.createElement('i');
      mark.className = 'slip-mark';
      mark.style.left = `${slip.half + (center - slip.x)}px`;
      const style = styleInput();
      mark.className = `slip-mark face-${style.value}`;
      mark.style.setProperty('--c', style.dataset.color || '');
      if (style.value === 'dlm') mark.innerHTML = stage.querySelector('.face-dlm').innerHTML;
      else mark.textContent = style.dataset.text;
      slip.el.append(mark);
      if (slip.kind === 'void') {
        slip.el.classList.add('wrong');
        breakCombo('盖错了');
        feel.sfx('return');
        return;
      }
      const isPerfect = off <= 11;
      const isGood = off <= 28;
      if (!isGood) { slip.el.classList.add('off'); breakCombo('偏了'); feel.sfx('tap'); return; }
      combo += 1;
      best = Math.max(best, combo);
      const base = (isPerfect ? 100 : 50) * (slip.kind === 'urgent' ? 2 : 1);
      score += Math.round(base * mult());
      if (isPerfect) {
        perfect += 1;
        // 完美：打击停顿 70ms + 单子横向小震 + 墨点溅开
        freezeUntil = performance.now() + 70;
        feel.play(slip.el, [{marginLeft: '3px'}, {marginLeft: '-3px'}, {marginLeft: '2px'}, {marginLeft: '0px'}], {duration: 160});
        splash(slip.el, mark);
        say('完美！', 'perfect');
      } else {
        good += 1;
        say('不错', 'good');
      }
      slip.el.classList.add(isPerfect ? 'perfect' : 'good');
      feel.sfx('stamp');
      if (combo % 10 === 0) {
        feel.sfx('set');
        feel.play(comboBox, [{transform: 'scale(1)'}, {transform: 'scale(1.35) rotate(-4deg)'}, {transform: 'none'}], {duration: 420, easing: feel.B});
        stage.classList.add('levelup');
        setTimeout(() => stage.classList.remove('levelup'), 600);
      }
      paintHud(true);
    }

    function splash(slipEl, mark) {
      if (!feel.motionOn()) return;
      for (let i = 0; i < 6; i++) {
        const dot = document.createElement('i');
        dot.className = 'ink';
        const angle = (i / 6) * Math.PI * 2 + Math.random();
        dot.style.left = mark.style.left;
        slipEl.append(dot);
        dot.animate([{transform: 'translate(-50%,-50%) scale(.6)', opacity: 1},
          {transform: `translate(calc(-50% + ${Math.cos(angle) * 34}px),calc(-50% + ${Math.sin(angle) * 34}px)) scale(1)`, opacity: 0}],
        {duration: 420, easing: feel.C}).finished.then(() => dot.remove());
      }
    }

    function breakCombo(text) {
      miss += 1;
      if (combo >= 5) say(`${text} · 连击断了`, 'miss'); else say(text, 'miss');
      combo = 0;
      paintHud();
    }

    function paintHud(bump) {
      scoreEl.textContent = score;
      comboEl.textContent = combo;
      multEl.textContent = `×${mult()}`;
      comboBox.classList.toggle('hot', combo >= 10);
      if (bump) feel.play(comboEl, [{transform: 'scale(1.35)'}, {transform: 'none'}], {duration: 180, easing: feel.B});
    }

    function say(text, kind) {
      judge.textContent = text;
      judge.className = `judge ${kind}`;
      feel.play(judge, [{transform: 'translate(-50%,6px) scale(.7)', opacity: 0}, {transform: 'translate(-50%,0) scale(1.08)', opacity: 1, offset: .4}, {transform: 'translate(-50%,0) scale(1)', opacity: 1, offset: .8}, {transform: 'translate(-50%,-6px)', opacity: 0}],
        {duration: kind === 'count' ? 500 : 620, easing: feel.C, fill: 'forwards'});
    }

    async function end() {
      state = 'over';
      cancelAnimationFrame(raf);
      say('时间到', 'go');
      feel.sfx('level');
      const fields = {score: String(score), combo: String(best)};
      result.querySelector('[data-final]').textContent = score;
      result.querySelector('[data-final-combo]').textContent = best;
      result.querySelector('[data-final-perfect]').textContent = perfect;
      result.querySelector('[data-final-good]').textContent = good;
      result.querySelector('[data-final-miss]').textContent = miss;
      const titlesBox = result.querySelector('[data-result-titles]');
      titlesBox.innerHTML = '';
      const label = result.querySelector('[data-result-label]');
      label.textContent = '结束';
      try {
        const data = await post(run.finish, fields);
        document.querySelector('[data-best]').textContent = data.best.score;
        document.querySelector('[data-best-combo]').textContent = data.best.combo;
        if (data.record) { label.textContent = '新纪录！'; label.classList.add('gold'); }
        else label.classList.remove('gold');
        result.querySelector('[data-result-nudge]').hidden = data.recent < 5;
        const pick = modeInput().closest('.pick-mode');
        pick.dataset.bestScore = data.best.score;
        pick.dataset.bestCombo = data.best.combo;
        titlesBox.innerHTML = (data.titles || []).map(t => `<div class="solved-titles">${hanko(t)}<span>解锁称号「${esc(t.name)}」</span></div>`).join('');
      } catch (error) {
        label.textContent = '没记上分';
        feel.toast(`<span>${esc(error.message)}</span>`);
      }
      setTimeout(() => {
        result.hidden = false;
        feel.play(result.querySelector('.cover-card'), [{transform: 'scale(.9) translateY(14px)', opacity: 0}, {transform: 'none', opacity: 1}], {duration: 420, easing: feel.B});
        feel.countTo(result.querySelector('[data-final]'), score, {from: 0, duration: 800, onTick: k => feel.sfx('tick', {pitch: 1 + k})});
        state = 'idle';
      }, feel.motionOn() ? 700 : 0);
    }

    stage.querySelector('[data-go]')?.addEventListener('click', event => { event.stopPropagation(); begin(); });
    stage.querySelector('[data-again]').addEventListener('click', event => { event.stopPropagation(); begin(); });
    stage.querySelector('[data-change]').addEventListener('click', event => {
      event.stopPropagation();
      result.hidden = true;
      cover.hidden = false;
      feel.play(cover.querySelector('.cover-card'), [{transform: 'translateY(10px)', opacity: 0}, {transform: 'none', opacity: 1}], {duration: 300, easing: feel.C});
    });
    stage.addEventListener('pointerdown', event => {
      if (state !== 'playing' || event.target.closest('a,button')) return;
      event.preventDefault();
      hit();
    });
    document.addEventListener('keydown', event => {
      if (state !== 'playing' || !(event.code === 'Space' || event.key === 'Enter') || event.repeat) return;
      event.preventDefault();
      hit();
    });
  }
})();
