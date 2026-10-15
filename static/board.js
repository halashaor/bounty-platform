/* 页面级交互：发现页的方向条、两排推荐和任务墙翻页，发布页的实时预览。手感工具来自 ui.js 的 window.bounty。 */
(() => {
  const feel = window.bounty || {play() { return null; }, sfx() {}, toast() {}, motionOn: () => false, A: 'ease', B: 'ease', C: 'ease', D: 'ease'};

  /* ---------- 任务墙：一页 12 张，翻页时整块滑过去 ---------- */
  const canvas = document.querySelector('.wall-canvas');
  if (canvas) {
    const zones = [...canvas.querySelectorAll('.wall-zone')];
    const position = document.querySelector('[data-wall-position]');
    let current = 0;
    const go = step => {
      const target = (current + step + zones.length) % zones.length;
      if (target === current) return;
      zones[current].hidden = true;
      zones[target].hidden = false;
      current = target;
      canvas.dataset.zone = String(current);
      if (position) position.textContent = String(current + 1);
      feel.play(canvas, [{transform: `translateX(${step > 0 ? 40 : -40}px)`, opacity: 0}, {transform: 'none', opacity: 1}], {duration: 260, easing: feel.C});
      feel.sfx('tap');
      const top = canvas.closest('.browse')?.getBoundingClientRect().top;
      if (top < 0) canvas.closest('.browse').scrollIntoView({behavior: feel.motionOn() ? 'smooth' : 'auto'});
    };
    document.querySelector('[data-wall-next]')?.addEventListener('click', () => go(1));
    document.querySelector('[data-wall-prev]')?.addEventListener('click', () => go(-1));
  }

  /* ---------- 两排推荐：换一批、不感兴趣、改方向之后，只把那一排重新发一次牌 ---------- */
  const csrf = () => document.querySelector('meta[name=csrf-token]')?.content || '';
  const laneTicket = {};
  async function refreshLane(lane, batch = 0) {
    const body = document.querySelector(`[data-lane-body="${lane}"]`);
    if (!body) return;
    const ticket = laneTicket[lane] = (laneTicket[lane] || 0) + 1;
    const wantBatch = document.querySelector('[data-lane-more="want"]')?.dataset.batch || 0;
    const fetched = fetch(`/picks/${lane}?batch=${batch}&wb=${wantBatch}`, {headers: {Accept: 'text/html'}}).then(r => r.ok ? r.text() : Promise.reject());
    // 旧牌先收走（和请求同时进行），新牌一张张发出来
    const old = [...body.querySelectorAll('.pick, .lane-empty, .empty')];
    body.style.minHeight = `${body.offsetHeight}px`;
    await Promise.all(old.map((card, i) => feel.play(card, [{transform: 'none', opacity: 1}, {transform: 'translateY(10px) scale(.96)', opacity: 0}], {duration: 150, delay: i * 30, easing: feel.D, fill: 'forwards'})?.finished));
    let html;
    try { html = await fetched; } catch { old.forEach(card => card.getAnimations().forEach(a => a.cancel())); body.style.minHeight = ''; feel.toast('<span>没拿到新的推荐，稍后再试</span>'); return; }
    if (ticket !== laneTicket[lane]) return;   // 连点时只认最后一次
    const next = new DOMParser().parseFromString(html, 'text/html').querySelector(`[data-lane-body="${lane}"]`);
    body.replaceChildren(...next.childNodes);
    body.style.minHeight = '';
    body.querySelectorAll('.pick, .lane-empty, .empty').forEach((card, i) => {
      feel.play(card, [{transform: 'translateY(26px) rotate(-2deg) scale(.94)', opacity: 0}, {transform: 'none', opacity: 1}], {duration: 420, delay: i * 70, easing: feel.B, fill: 'backwards'});
      setTimeout(() => feel.sfx('tap'), i * 70);
    });
    const more = document.querySelector(`[data-lane-more="${lane}"]`);
    if (more) { more.hidden = !body.querySelector('.pick'); more.dataset.batch = String(batch); }
    // 第一排换了以后，如果和第二排撞了同一个任务，第二排也补一次
    if (lane === 'want') {
      const shown = new Set([...body.querySelectorAll('[data-pick]')].map(card => card.dataset.pick));
      if ([...document.querySelectorAll('[data-lane-body="past"] [data-pick]')].some(card => shown.has(card.dataset.pick))) {
        refreshLane('past', Number(document.querySelector('[data-lane-more="past"]')?.dataset.batch || 0));
      }
    }
  }
  document.addEventListener('click', event => {
    const more = event.target.closest('[data-lane-more]');
    if (!more) return;
    event.preventDefault();
    const icon = more.querySelector('svg');
    feel.play(icon, [{transform: 'rotate(0)'}, {transform: 'rotate(360deg)'}], {duration: 520, easing: feel.C});
    refreshLane(more.dataset.laneMore, Number(more.dataset.batch || 0) + 1);
  });
  // 不感兴趣：卡片甩出去，记下来，这一排补一张新的上来
  document.addEventListener('submit', async event => {
    const form = event.target.closest('.pick-x');
    if (!form) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const card = form.closest('.pick');
    const lane = form.closest('[data-lane-body]')?.dataset.laneBody;
    feel.sfx('tap');
    const away = feel.play(card, [{transform: 'none', opacity: 1}, {transform: 'translate(30px,-10px) rotate(8deg) scale(.9)', opacity: 0}], {duration: 240, easing: feel.D, fill: 'forwards'});
    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form), headers: {Accept: 'application/json'}});
      if (!response.ok) throw new Error();
    } catch {
      away?.cancel();
      feel.toast('<span>没记下，稍后再试</span>');
      return;
    }
    await away?.finished;
    const more = document.querySelector(`[data-lane-more="${lane}"]`);
    if (lane) refreshLane(lane, Number(more?.dataset.batch || 0));
    else location.reload();
  }, true);

  /* ---------- 方向条：从团队的标签表里点，颜色从手指按下的地方铺开；停手 0.4 秒后保存并重排第一排 ---------- */
  const dirs = document.querySelector('[data-dirs]');
  if (dirs) {
    const panel = dirs.closest('.dirs');
    const grid = dirs.querySelector('[data-dir-grid]');
    const counter = dirs.querySelector('[data-dirs-count]');
    const clear = dirs.querySelector('[data-dirs-clear]');
    const limit = 8;
    const boxes = () => [...dirs.querySelectorAll('input[type=checkbox][name=tags]')];
    const chosen = () => boxes().filter(box => box.checked).map(box => box.value);
    let timer = null;
    dirs.querySelector('[data-dirs-save]').hidden = true;   // 有脚本时随点随存，不需要保存按钮

    grid.addEventListener('pointerdown', event => {
      const tile = event.target.closest('.dir');
      if (!tile) return;
      const box = tile.getBoundingClientRect();
      tile.style.setProperty('--x', `${event.clientX - box.left}px`);
      tile.style.setProperty('--y', `${event.clientY - box.top}px`);
    });
    grid.addEventListener('change', event => {
      const box = event.target;
      if (box.type !== 'checkbox') return;
      const tile = box.closest('.dir');
      if (box.checked && chosen().length > limit) {
        box.checked = false;
        feel.play(tile, [{transform: 'translateX(-5px)'}, {transform: 'translateX(4px)'}, {transform: 'translateX(-2px)'}, {transform: 'none'}], {duration: 260});
        feel.toast(`<span>最多选 ${limit} 个方向，先取消一个</span>`);
        return;
      }
      react(tile, box.checked);
      changed();
    });
    function react(tile, on) {
      const art = tile.querySelector('.dir-art');
      if (on) {
        art.classList.remove('anim');
        void art.getBoundingClientRect();
        art.classList.add('anim');
        feel.play(tile, [{transform: 'scale(.95)'}, {transform: 'scale(1.04)', offset: .45}, {transform: 'none'}], {duration: 380, easing: feel.C});
        // 连着选，音一个比一个高
        feel.sfx('tick', {pitch: 1 + chosen().length * 0.12});
      } else {
        tile.style.setProperty('--x', '50%');
        tile.style.setProperty('--y', '50%');
        feel.sfx('tap');
      }
    }
    function changed() {
      const tags = chosen();
      counter.textContent = tags.length;
      feel.play(counter, [{transform: 'scale(1.5)'}, {transform: 'scale(1)'}], {duration: 260, easing: feel.B});
      clear.hidden = !tags.length;
      const label = document.querySelector('[data-want-tags]');
      if (label) {
        label.innerHTML = tags.map(tag => {
          const tone = boxes().find(box => box.value === tag)?.closest('.dir')?.style.getPropertyValue('--tone') || '';
          return `<span class="tag" style="--tone:${tone}">${escape(tag)}</span>`;
        }).join('');
      }
      clearTimeout(timer);
      timer = setTimeout(save, 420);
    }
    async function save() {
      const body = new URLSearchParams({csrf: csrf()});
      chosen().forEach(tag => body.append('tags', tag));
      try {
        const response = await fetch(dirs.action, {method: 'POST', body, headers: {Accept: 'application/json'}});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
      } catch (error) {
        feel.toast(`<span>${escape(error.message || '没保存上，稍后再试')}</span>`);
        return;
      }
      refreshLane('want', 0);
    }
    clear.addEventListener('click', () => {
      boxes().forEach(box => { box.checked = false; box.closest('.dir').style.setProperty('--x', '50%'); box.closest('.dir').style.setProperty('--y', '50%'); });
      feel.sfx('tap');
      changed();
    });
    dirs.addEventListener('submit', event => { event.preventDefault(); clearTimeout(timer); save(); });

    dirs.querySelector('[data-dirs-more]')?.addEventListener('click', event => {
      const open = panel.classList.toggle('more');
      event.currentTarget.setAttribute('aria-expanded', String(open));
      event.currentTarget.querySelector('span').textContent = open ? '收起' : event.currentTarget.dataset.label || event.currentTarget.querySelector('span').textContent;
    });
    const moreButton = dirs.querySelector('[data-dirs-more]');
    if (moreButton) moreButton.dataset.label = moreButton.querySelector('span').textContent;
  }

  function escape(text) {
    return String(text).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }

  /* ---------- 发布页：边填边看「发现」里的样子 ---------- */
  const editor = document.querySelector('[data-editor]');
  if (editor) {
    const out = name => document.querySelectorAll(`[data-out="${name}"]`);
    const template = document.querySelector('template[data-medal-template]');
    const medal = key => template.content.querySelector(`[data-key="${key}"]`).innerHTML;
    const names = {'light-normal': '点', 'standard-normal': '线', 'major-normal': '面', 'light-urgent': '点·急', 'standard-urgent': '线·急', 'major-urgent': '面·急'};
    const xp = {light: 10, standard: 30, major: 80};
    const effort = {light: '半天内', standard: '一两天', major: '一周左右'};
    const pickedTags = () => [...editor.querySelectorAll('[name=tags]:checked')].map(box => box.value)
      .concat((editor.querySelector('[name=new_tags]')?.value || '').split(/[,，、;；\s]+/).map(t => t.replace(/^#/, '')).filter(Boolean));
    let lastKey = '';
    const update = () => {
      const value = name => editor.querySelector(`[name=${name}]:checked`)?.value || editor.querySelector(`[name=${name}]`)?.value || '';
      const importance = value('importance') || 'standard';
      const urgency = value('urgency') || 'normal';
      const key = `${importance}-${urgency}`;
      out('title').forEach(el => { el.textContent = value('title') || '任务标题'; });
      out('description').forEach(el => { el.textContent = value('description') || '任务说明会显示在这里。'; });
      const tags = pickedTags().slice(0, 3);
      out('tags').forEach(el => { el.innerHTML = tags.map(t => `<span class="tag">${escape(t)}</span>`).join(''); });
      out('effort').forEach(el => { el.textContent = effort[importance]; });
      out('xp').forEach(el => { el.textContent = `+${urgency === 'urgent' ? xp[importance] * 1.5 : xp[importance]}`; });
      out('medal').forEach(el => { el.textContent = `完成的人得到「${names[key]}」`; });
      if (key !== lastKey) {
        document.querySelector('[data-preview-medal]').innerHTML = medal(key);
        const big = document.querySelector('[data-preview-medal-big]');
        big.innerHTML = medal(key);
        const svg = big.querySelector('svg');
        if (lastKey && feel.motionOn()) { svg.classList.add('anim'); feel.sfx('tap'); }
        lastKey = key;
      }
    };
    editor.addEventListener('input', update);
    editor.addEventListener('change', update);
    update();
    // 最多 5 个标签：勾满了就挡一下
    editor.querySelector('[data-tag-pick]')?.addEventListener('change', event => {
      if (event.target.checked && pickedTags().length > 5) {
        event.target.checked = false;
        feel.play(event.target.closest('.chip'), [{transform: 'translateX(-4px)'}, {transform: 'translateX(3px)'}, {transform: 'none'}], {duration: 220});
        feel.toast('<span>最多 5 个标签</span>');
        update();
        return;
      }
      feel.play(event.target.closest('.chip'), [{transform: 'scale(.9)'}, {transform: 'scale(1)'}], {duration: 200, easing: feel.B});
      feel.sfx('tap');
    });
  }
  /* ---------- 发起大任务：分工一行行加减，右边的拼图跟着变；写了标题的那块先亮起来 ---------- */
  const bigEditor = document.querySelector('[data-big-editor]');
  if (bigEditor) {
    const list = bigEditor.querySelector('[data-piece-list]');
    const rowTemplate = bigEditor.querySelector('template[data-piece-template]');
    const preview = document.querySelector('[data-big-preview]');
    const shapes = Object.fromEntries([...document.querySelector('template[data-tile-template]').content.querySelectorAll('[data-importance]')]
      .map(g => [g.dataset.importance, g.innerHTML]));
    const hues = JSON.parse(document.querySelector('[data-medal-hues]').textContent);
    const rows = () => [...list.querySelectorAll('[data-piece-row]')];
    const MAX = 30;
    let lit = new Set();
    const draw = () => {
      const items = rows().map(row => ({kind: row.querySelector('[name=piece_kind]').value, named: !!row.querySelector('[name=piece_title]').value.trim()}));
      const n = Math.max(items.length, 1);
      const cols = Math.min(n, Math.ceil(Math.sqrt(n * 1.6)));
      const lines = Math.ceil(n / cols);
      const last = items.length - (lines - 1) * cols;
      const svg = preview.querySelector('svg');
      svg.setAttribute('viewBox', `0 0 ${cols * 44 - 4} ${lines * 44 - 4}`);
      const now = new Set();
      svg.innerHTML = items.map((item, i) => {
        const line = Math.floor(i / cols);
        const x = (i % cols) * 44 + (line === lines - 1 ? (cols - last) * 22 : 0);
        if (item.named) now.add(i);
        // 新亮起来的那块弹一下，其余的不重播
        const fresh = item.named && !lit.has(i) ? ' fresh' : '';
        return `<g transform="translate(${x} ${line * 44})"><g class="mt ${item.named ? 'done' : 'open'}${fresh}" style="--c:${hues[item.kind].hue};--i:0">${shapes[item.kind.split('-')[0]]}</g></g>`;
      }).join('');
      svg.querySelectorAll('.fresh').forEach(g => feel.play(g, [{transform: 'scale(.4)', opacity: 0}, {transform: 'scale(1)', opacity: 1}], {duration: 420, easing: feel.B}));
      if (now.size > lit.size) feel.sfx('tap');
      lit = now;
      preview.querySelector('[data-piece-count]').textContent = String(items.filter(item => item.named).length);
      rows().forEach((row, i) => { row.querySelector('.piece-no').textContent = String(i + 1); });
      bigEditor.querySelector('[data-piece-add]').hidden = items.length >= MAX;
    };
    bigEditor.querySelector('[data-piece-add]').addEventListener('click', () => {
      const row = rowTemplate.content.firstElementChild.cloneNode(true);
      list.append(row);
      draw();
      row.querySelector('[name=piece_title]').focus();
      feel.play(row, [{transform: 'translateY(-6px)', opacity: 0}, {transform: 'none', opacity: 1}], {duration: 260, easing: feel.C});
    });
    list.addEventListener('click', event => {
      const button = event.target.closest('[data-piece-remove]');
      if (!button) return;
      const row = button.closest('[data-piece-row]');
      if (rows().length <= 2) {
        // 至少留两份：清空这一行，不删掉
        row.querySelectorAll('input').forEach(input => { input.value = ''; });
        draw();
        feel.toast('<span>大任务至少两份分工</span>');
        return;
      }
      row.remove();
      lit = new Set();
      draw();
      feel.sfx('tap');
    });
    bigEditor.addEventListener('input', draw);
    bigEditor.addEventListener('change', draw);
    draw();
  }
})();
