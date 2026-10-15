/* 积木：在 16×16 的板子上一层层往上搭，随便搭，不花任何东西。画法在 iso.js 里。
   - 点零件盒里的零件拿在手上，再点板子放下去（可以连着放）；零件落在下面最高的地方：点到顶面就叠上去，点到侧面就放在它跟前。
     Esc 或再点一次零件就放下手里的。
   - 点板子上的零件选中它，拖着能挪（压在它上面的会掉下来）；R 转、D 再拿一个一样的、Delete 删、方向键挪一格、
     Q / E 转视角、Ctrl+Z 撤销。
   - 没解锁的零件和颜色点了会说怎么解锁：都是靠勋章。
   手感：放下时从上面落下来弹一下，越小的零件音越高；删掉时缩没，上面的零件跟着掉下来。 */
(() => {
  const feel = window.bounty || {play() { return null; }, sfx() {}, toast() {}, motionOn: () => false, B: 'ease', C: 'ease', D: 'ease'};
  const K = window.yuiBlocks;
  const root = document.querySelector('[data-blocks]');
  if (!root || !K) return;
  const {SIZE, LEVEL, HX, HY, ZK, P} = K;
  const TOP = K.D.levels;
  const data = JSON.parse(document.getElementById('blocks-data').textContent);
  const MAX = Number(root.dataset.max) || 300;
  const board = root.querySelector('[data-board]');
  const scene = board.querySelector('[data-scene]');
  const marks = board.querySelector('[data-mark]');
  const sky = board.querySelector('[data-sky]');
  const countEl = root.querySelector('[data-count]');
  const emptyHint = root.querySelector('[data-empty]');
  const nameInput = root.querySelector('[data-name]');
  const showButton = root.querySelector('[data-show-build]');
  const dial = root.querySelector('[data-view-dial]');
  const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const csrf = () => document.querySelector('meta[name=csrf-token]')?.content || '';
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const xy = p => `${p[0].toFixed(2)} ${p[1].toFixed(2)}`;

  let parts = data.build ? data.build.parts.map(part => [...part]) : [];
  let bg = data.build?.bg || 'paper';
  let view = data.build?.view || 0;
  let buildId = data.build?.id || null;
  let hand = null;          // 拿在手上的零件
  let handRot = 0;
  let aim = null;           // 手上的零件现在会落在哪：{x, y, z}
  let color = [...root.querySelectorAll('[data-color]')].map(button => button.dataset.color).find(key => data.colors[key]?.open) || 'ink';
  let selected = -1;
  let hover = -1;
  let drag = null;
  let lastPointer = null;
  let dirty = false;
  const undos = [];

  /* ---------- 画 ---------- */
  // 板子上方留的空：搭得很高时整块板子往后退一点，最高的地方也看得见
  function frame() {
    const tops = parts.map(part => { const v = K.toView(part, view), [fw, fd] = K.footprint(v.id, v.r);
      return [v.x, v.y, v.z * LEVEL, v.x + fw, v.y + fd, (v.z + K.size(v.id)[2]) * LEVEL]; });
    const high = tops.length ? K.bboxOf(tops)[1] : 0;
    const extra = Math.max(0, -92 - (high - 14));
    board.setAttribute('viewBox', `${(-166 - extra * 0.62).toFixed(1)} ${(-92 - extra).toFixed(1)} ${(332 + extra * 1.24).toFixed(1)} ${(268 + extra).toFixed(1)}`);
  }
  function render() {
    frame();
    scene.innerHTML = K.base(0, 0, SIZE, SIZE, bg) + K.shadows(parts, view) + K.paint(parts, view, true);
    sky.setAttribute('fill', K.skyColor(bg));
    countEl.textContent = parts.length;
    emptyHint.hidden = parts.length > 0 || !!hand;
    dial.style.setProperty('--turn', `${view * 90}deg`);
    root.querySelectorAll('.bg-btn').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.bg === bg)));
    paintMarks();
  }
  // 一个零件在当前视角下的外轮廓（六边形）
  function outline(part, cls) {
    const v = K.toView(part, view), [fw, fd] = K.footprint(v.id, v.r);
    const [x0, y0, z0] = [v.x, v.y, v.z * LEVEL], [x1, y1, z1] = [v.x + fw, v.y + fd, (v.z + K.size(v.id)[2]) * LEVEL];
    const points = [[x0, y0, z1], [x1, y0, z1], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y1, z1]].map(p => xy(P(...p)));
    return `<path class="${cls}" d="M${points.join('L')}Z"/>`;
  }
  function paintMarks() {
    let out = '';
    if (hand && aim) {
      const ghost = [hand, color, aim.x, aim.y, aim.z, handRot];
      const v = K.toView(ghost, view), [fw, fd] = K.footprint(v.id, v.r), z = v.z * LEVEL;
      const high = aim.z + K.size(hand)[2] > TOP;
      out += `<path class="landing${high ? ' too-high' : ''}" d="M${[[v.x, v.y], [v.x + fw, v.y], [v.x + fw, v.y + fd], [v.x, v.y + fd]].map(([x, y]) => xy(P(x, y, z))).join('L')}Z"/>`;
      if (!high) out += `<g class="ghost">${K.paint([ghost], view)}</g>`;
    }
    if (!hand && hover >= 0 && hover !== selected && parts[hover]) out += outline(parts[hover], 'hover-line');
    if (selected >= 0 && parts[selected]) out += outline(parts[selected], 'select-line');
    marks.innerHTML = out;
    root.querySelectorAll('[data-tool]').forEach(button => {
      const tool = button.dataset.tool;
      button.disabled = ['paint', 'copy', 'delete'].includes(tool) ? selected < 0
        : tool === 'rotate' ? selected < 0 && !hand : tool === 'undo' ? !undos.length : tool === 'clear' ? !parts.length : false;
    });
  }
  const groups = i => scene.querySelectorAll(`[data-i="${i}"]`);
  function drop(i, from = 14) {   // 从上面落下来，弹一下
    groups(i).forEach(node => feel.play(node, [{transform: `translateY(-${from}px)`, opacity: 0.2}, {transform: 'translateY(1.5px)', opacity: 1, offset: 0.7}, {transform: 'none'}],
      {duration: 300, easing: feel.B}));
  }
  // 重新落一遍；掉下来的零件补一段下落的动画
  function settle() {
    const before = parts.map(part => part[4]);
    K.settle(parts);
    return parts.map((part, i) => before[i] - part[4]);
  }
  function fall(drops) {
    drops.forEach((levels, i) => { if (levels > 0) drop(i, levels * LEVEL * ZK); });
    if (drops.some(levels => levels > 0)) setTimeout(() => feel.sfx('tick', {pitch: 0.6}), 220);
  }
  function remember() {
    undos.push(JSON.stringify({parts, bg}));
    if (undos.length > 100) undos.shift();
    dirty = true;
  }
  function click(id) {   // 越小的零件音越高，像积木"咔哒"一声
    const [w, d, h] = K.size(id);
    feel.sfx('tick', {pitch: 1.7 - Math.min(w * d * h, 16) / 16 * 0.9});
  }

  /* ---------- 指到哪里 ---------- */
  function point(event) {
    const p = board.createSVGPoint();
    p.x = event.clientX;
    p.y = event.clientY;
    const local = p.matrixTransform(board.getScreenCTM().inverse());
    return [local.x, local.y];
  }
  // 从看的人这边沿视线往里找：先碰到哪个零件的顶面就叠上去，碰到侧面就放在它跟前；什么都没碰到就放在地上
  function aimAt(event, id, r, skip = -1) {
    const [sx, sy] = point(event);
    const heights = new Float32Array(SIZE * SIZE);
    let top = 0;
    parts.forEach((part, i) => {
      if (i === skip) return;
      const v = K.toView(part, view), [fw, fd] = K.footprint(v.id, v.r), h = (v.z + K.size(v.id)[2]) * LEVEL;
      for (let x = v.x; x < v.x + fw; x++) for (let y = v.y; y < v.y + fd; y++) heights[x * SIZE + y] = Math.max(heights[x * SIZE + y], h);
      top = Math.max(top, h);
    });
    const at = z => { const a = sx / HX, b = (sy + z * ZK) / HY; return [(a + b) / 2, (b - a) / 2]; };
    let hit = at(0), before = null;
    for (let z = top; z > 0; z -= 0.04) {
      const [fx, fy] = at(z), cx = Math.floor(fx), cy = Math.floor(fy);
      if (cx >= 0 && cy >= 0 && cx < SIZE && cy < SIZE && heights[cx * SIZE + cy] >= z - 1e-6) {
        hit = heights[cx * SIZE + cy] - z < 0.06 || !before ? [fx, fy] : before;
        break;
      }
      before = [fx, fy];
    }
    const [wx, wy] = K.fromView(hit[0], hit[1], view), [fw, fd] = K.footprint(id, r);
    const x = clamp(Math.round(wx - fw / 2), 0, SIZE - fw), y = clamp(Math.round(wy - fd / 2), 0, SIZE - fd);
    return {x, y, z: K.dropLevel(parts, id, x, y, r, skip)};
  }
  const partAt = event => { const node = event.target.closest?.('[data-i]'); return node && scene.contains(node) ? Number(node.dataset.i) : -1; };

  /* ---------- 零件盒、颜色、底板 ---------- */
  function locked(button, item) {
    feel.play(button, [{transform: 'translateX(-4px)'}, {transform: 'translateX(3px)'}, {transform: 'none'}], {duration: 220});
    feel.toast(`<span>「${esc(item.name)}」还没解锁：${esc(item.need)}</span>`, 'locked');
    feel.sfx('return');
  }
  function recolorIcons() {
    root.querySelectorAll('[data-part]').forEach(button => {
      const old = button.querySelector('.part-icon');
      if (!old) return;
      const holder = document.createElement('template');
      holder.innerHTML = K.icon(button.dataset.part, color);
      old.replaceWith(holder.content.firstChild);
    });
  }
  function take(id) {
    hand = id;
    selected = -1;
    aim = null;
    root.querySelectorAll('[data-part]').forEach(other => other.setAttribute('aria-pressed', String(other.dataset.part === hand)));
    board.classList.toggle('holding', !!hand);
    if (hand) click(hand);
    if (hand && lastPointer) aim = aimAt(lastPointer, hand, handRot);
    render();
  }
  root.querySelectorAll('[data-part]').forEach(button => button.addEventListener('click', () => {
    const id = button.dataset.part;
    if (!data.parts[id].open) return locked(button, data.parts[id]);
    feel.play(button, [{transform: 'scale(.9)'}, {transform: 'none'}], {duration: 200, easing: feel.B});
    handRot = 0;
    take(hand === id ? null : id);
  }));
  function setColor(key, button) {
    if (!data.colors[key].open) return locked(button, data.colors[key]);
    color = key;
    root.querySelectorAll('[data-color]').forEach(other => other.setAttribute('aria-checked', String(other.dataset.color === key)));
    recolorIcons();
    feel.play(button, [{transform: 'scale(.8)'}, {transform: 'scale(1.15)', offset: .6}, {transform: 'none'}], {duration: 260, easing: feel.B});
    feel.sfx('tap');
    if (selected >= 0 && parts[selected][1] !== key) { remember(); parts[selected][1] = key; render(); drop(selected, 4); }
    else paintMarks();
  }
  root.querySelectorAll('[data-color]').forEach(button => button.addEventListener('click', () => setColor(button.dataset.color, button)));
  root.querySelectorAll('[data-bg]').forEach(button => button.addEventListener('click', () => {
    if (button.dataset.bg === bg) return;
    remember();
    bg = button.dataset.bg;
    render();
    feel.play(scene, [{opacity: .5}, {opacity: 1}], {duration: 260});
    feel.sfx('tap');
  }));

  /* ---------- 板子：放、选、拖 ---------- */
  board.addEventListener('pointerdown', event => {
    lastPointer = event;
    if (hand) {
      if (parts.length >= MAX) { feel.toast(`<span>一件作品最多 ${MAX} 个零件</span>`); return; }
      aim = aimAt(event, hand, handRot);
      if (aim.z + K.size(hand)[2] > TOP) { feel.toast(`<span>堆得太高了，最高 ${TOP} 层</span>`); feel.sfx('return'); return; }
      remember();
      parts.push([hand, color, aim.x, aim.y, aim.z, handRot]);
      settle();
      render();
      drop(parts.length - 1);
      click(hand);
      aim = aimAt(event, hand, handRot);
      paintMarks();
      return;
    }
    const index = partAt(event);
    selected = index;
    if (index >= 0) {
      event.preventDefault();
      board.setPointerCapture(event.pointerId);
      drag = {index, moved: false};
      feel.sfx('tap');
    }
    paintMarks();
  });
  board.addEventListener('pointermove', event => {
    lastPointer = event;
    if (hand) {
      const next = aimAt(event, hand, handRot);
      if (!aim || next.x !== aim.x || next.y !== aim.y || next.z !== aim.z) { aim = next; paintMarks(); }
      return;
    }
    if (!drag) {
      const index = partAt(event);
      if (index !== hover) { hover = index; paintMarks(); }
      return;
    }
    const part = parts[drag.index];
    const next = aimAt(event, part[0], part[5], drag.index);
    if (next.x === part[2] && next.y === part[3]) return;
    if (next.z + K.size(part[0])[2] > TOP) return;
    if (!drag.moved) { remember(); drag.moved = true; }
    [part[2], part[3], part[4]] = [next.x, next.y, next.z];
    const drops = settle();
    render();
    fall(drops);
    feel.sfx('tick', {pitch: 0.8});
  });
  const stop = () => { drag = null; };
  board.addEventListener('pointerup', stop);
  board.addEventListener('pointercancel', stop);
  board.addEventListener('pointerleave', () => { aim = null; hover = -1; paintMarks(); });

  /* ---------- 工具 ---------- */
  function turnView(step) {
    view = (view + step + 4) % 4;
    dirty = true;
    if (hand && lastPointer) aim = aimAt(lastPointer, hand, handRot);
    render();
    feel.play(scene, [{transform: `translateX(${step * 10}px) scaleX(.94)`, opacity: .4}, {transform: 'none', opacity: 1}], {duration: 280, easing: feel.B});
    feel.sfx('tap');
  }
  function move(step) {   // 方向键按屏幕上的方向挪一格（视角转过来时也一样）
    const part = parts[selected];
    let [dx, dy] = step;
    for (let i = 0; i < view; i++) [dx, dy] = [dy, -dx];
    const [fw, fd] = K.footprint(part[0], part[5]);
    const x = clamp(part[2] + dx, 0, SIZE - fw), y = clamp(part[3] + dy, 0, SIZE - fd);
    const z = K.dropLevel(parts, part[0], x, y, part[5], selected);
    if ((x === part[2] && y === part[3]) || z + K.size(part[0])[2] > TOP) return;
    remember();
    [part[2], part[3], part[4]] = [x, y, z];
    const drops = settle();
    render();
    fall(drops);
    feel.sfx('tick', {pitch: 0.8});
  }
  const tools = {
    rotate() {
      if (hand) {
        handRot = (handRot + 1) % 4;
        if (lastPointer) aim = aimAt(lastPointer, hand, handRot);
        paintMarks();
        feel.sfx('tap');
        return;
      }
      if (selected < 0) return;
      const part = parts[selected];
      const [fw, fd] = K.footprint(part[0], part[5]), cx = part[2] + fw / 2, cy = part[3] + fd / 2;
      const r = (part[5] + 1) % 4, [nw, nd] = K.footprint(part[0], r);
      const x = clamp(Math.round(cx - nw / 2), 0, SIZE - nw), y = clamp(Math.round(cy - nd / 2), 0, SIZE - nd);
      const z = K.dropLevel(parts, part[0], x, y, r, selected);
      if (z + K.size(part[0])[2] > TOP) return;
      remember();
      [part[2], part[3], part[4], part[5]] = [x, y, z, r];
      const drops = settle();
      render();
      fall(drops);
      drop(selected, 5);
      feel.sfx('tap');
    },
    paint() { if (selected >= 0) setColor(color, root.querySelector(`[data-color="${color}"]`)); },
    copy() {   // 再拿一个一样的：同样的零件、朝向和颜色拿在手上
      if (selected < 0) return;
      const [id, c, , , , r] = parts[selected];
      if (data.colors[c]?.open && c !== color) {
        color = c;
        root.querySelectorAll('[data-color]').forEach(other => other.setAttribute('aria-checked', String(other.dataset.color === c)));
        recolorIcons();
      }
      handRot = r;
      take(data.parts[id]?.open ? id : null);
    },
    delete() {
      if (selected < 0) return;
      remember();
      const index = selected;
      selected = -1;
      const done = () => {
        parts.splice(index, 1);
        const drops = settle();
        render();
        fall(drops);
      };
      const motions = [...groups(index)].map(node => feel.play(node, [{transform: 'none', opacity: 1}, {transform: 'translateY(-6px) scale(.6)', opacity: 0}],
        {duration: 160, easing: feel.D, fill: 'forwards'})).filter(Boolean);
      if (motions.length) Promise.all(motions.map(m => m.finished)).then(done); else done();
      feel.sfx('return');
    },
    undo() {
      const last = undos.pop();
      if (!last) return;
      ({parts, bg} = JSON.parse(last));
      selected = -1;
      render();
      feel.sfx('tap');
    },
    clear() {
      if (!parts.length || !confirm('把板子上的零件全部清掉？可以撤销。')) return;
      remember();
      parts = [];
      selected = -1;
      render();
      feel.sfx('return');
    },
    'view-left': () => turnView(-1),
    'view-right': () => turnView(1),
  };
  root.querySelectorAll('[data-tool]').forEach(button => button.addEventListener('click', () => tools[button.dataset.tool]()));
  document.addEventListener('keydown', event => {
    if (event.target.closest('input,textarea')) return;
    const key = event.key;
    if ((event.ctrlKey || event.metaKey) && key.toLowerCase() === 'z') { event.preventDefault(); return tools.undo(); }
    if ((event.ctrlKey || event.metaKey) && key.toLowerCase() === 's') { event.preventDefault(); return save(); }
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (key === 'Escape') { selected = -1; return take(null); }
    if (key === 'r' || key === 'R') return tools.rotate();
    if (key === 'd' || key === 'D') return tools.copy();
    if (key === 'q' || key === 'Q') return turnView(-1);
    if (key === 'e' || key === 'E') return turnView(1);
    if (key === 'Delete' || key === 'Backspace') { event.preventDefault(); return tools.delete(); }
    const step = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}[key];
    if (step && selected >= 0) { event.preventDefault(); move(step); }
  });

  /* ---------- 保存、挂到名牌上 ---------- */
  async function send(url, body) {
    const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf(), Accept: 'application/json'},
      body: JSON.stringify(body || {})});
    const result = await response.json().catch(() => ({error: '出了点问题，稍后再试'}));
    if (!response.ok) throw new Error(result.error || '出了点问题，稍后再试');
    return result;
  }
  async function save() {
    try {
      const result = await send(root.dataset.save, {id: buildId, name: nameInput.value, bg, view, parts});
      const fresh = !buildId;
      buildId = result.id;
      dirty = false;
      if (fresh) {
        showButton.dataset.url = `/play/blocks/${buildId}/show`;
        showButton.hidden = false;
      }
      feel.toast(`<span>「${esc(nameInput.value || '我的作品')}」存好了</span>`);
      feel.sfx('claim');
      feel.play(board, [{transform: 'scale(.985)'}, {transform: 'none'}], {duration: 220, easing: feel.B});
      if (fresh) setTimeout(() => location.assign(result.url), feel.motionOn() ? 700 : 0);   // 作品列表里出现新的这件
    } catch (error) {
      feel.toast(`<span>${esc(error.message)}</span>`);
    }
  }
  root.querySelector('[data-save-build]').addEventListener('click', save);
  showButton.addEventListener('click', async () => {
    if (dirty) await save();
    try {
      const result = await send(showButton.dataset.url);
      showButton.classList.toggle('on', result.shown);
      showButton.setAttribute('aria-pressed', String(result.shown));
      showButton.querySelector('span').textContent = result.shown ? '在名牌上' : '挂到名牌上';
      feel.toast(`<span>${result.shown ? '挂到名牌上了，队友在名牌墙和积木墙上都能看到' : '从名牌上取下来了'}</span>`);
      feel.sfx(result.shown ? 'stamp' : 'tap');
    } catch (error) {
      feel.toast(`<span>${esc(error.message)}</span>`);
    }
  });
  nameInput.addEventListener('input', () => { dirty = true; });
  root.querySelector('[data-delete-build]')?.addEventListener('submit', event => {
    if (!confirm('删掉这件作品？删了就找不回来了。')) event.preventDefault();
    else dirty = false;
  });
  addEventListener('beforeunload', event => { if (dirty && parts.length) { event.preventDefault(); event.returnValue = ''; } });

  root.querySelectorAll('[data-color]').forEach(other => other.setAttribute('aria-checked', String(other.dataset.color === color)));
  recolorIcons();
  render();
  // 打开一件作品时，零件从下往上一个个落回板子上
  if (feel.motionOn()) {
    const order = parts.map((part, i) => i).sort((a, b) => parts[a][4] - parts[b][4] || a - b);
    order.forEach((i, n) => groups(i).forEach(node => feel.play(node, [{transform: 'translateY(-18px)', opacity: 0}, {transform: 'none', opacity: 1}],
      {duration: 320, delay: Math.min(n, 60) * 14, easing: feel.B, fill: 'backwards'})));
  }
})();
