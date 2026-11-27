/* 手帳：@ 提示、记一笔时的 @ 补全、长补充折叠、待办打勾。
   操作先落库再动画；动效开关关掉时 CSS 动画全站一起停。 */
(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const PALETTE = ['#2866B1', '#008FBF', '#D98200', '#00A27A', '#E54465', '#9C6B3F', '#1B1D2A'];
  const esc = text => String(text).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const icon = path => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  const AT = icon("<circle cx='12' cy='12' r='3.6'/><path d='M15.6 8.4v4.8a2.4 2.4 0 0 0 4.8 0V12a8.4 8.4 0 1 0-3.3 6.7'/>");
  const post = (url, body) => fetch(url, {method: 'POST', body, credentials: 'same-origin',
    headers: {'X-CSRF-Token': csrf, 'X-Requested-With': 'fetch', 'Accept': 'application/json'}});

  /* ---------- 有人 @ 你：右上角弹一张卡，10 秒后自己收起；红点留到看过为止 ---------- */
  const box = document.querySelector('.pings[data-pings]');
  // 「我的」上的数字 = 轮到你的任务 + 还没看的 @
  function badge(unseen) {
    const nav = document.querySelector('.nav a[data-waiting]');
    const count = Number(nav?.dataset.waiting || 0) + unseen;
    for (const link of [nav, document.querySelector('.tabbar a[href="' + nav?.getAttribute('href') + '"]')]) {
      if (!link) continue;
      let mark = link.querySelector('b');
      if (!count) { mark?.remove(); continue; }
      if (!mark) { mark = document.createElement('b'); link.append(mark); }
      if (mark.textContent !== String(count)) {
        mark.textContent = count;
        mark.classList.remove('bump'); void mark.offsetWidth; mark.classList.add('bump');
      }
    }
  }
  function dismiss(card) {
    card.classList.add('out');
    setTimeout(() => card.remove(), 300);
  }
  function show(item) {
    const card = document.createElement('article');
    card.className = 'ping';
    card.setAttribute('role', 'status');
    const color = PALETTE[item.who_id % 7];
    card.innerHTML = `<span class="ping-ava"><span class="ava" style="--c:${color}" aria-hidden="true">${esc(item.who.slice(0, 1))}</span><i>${AT}</i></span>
      <div class="ping-b"><p class="ping-m"><b>${esc(item.who)}</b>在手帳里提到了你<time>刚刚</time></p>
        <p class="ping-h">${esc(item.head)}</p>
        <div class="ping-a"><a class="mini dark" href="${esc(item.url)}">去看看</a><button class="mini ghost" type="button">知道了</button></div></div>
      <i class="ping-bar" aria-hidden="true"></i>`;
    card.querySelector('button').addEventListener('click', () => { post(item.seen_url); dismiss(card); refresh(); });
    let timer = setTimeout(() => dismiss(card), 10600);
    card.addEventListener('mouseenter', () => clearTimeout(timer));
    card.addEventListener('focusin', () => clearTimeout(timer));
    card.addEventListener('mouseleave', () => { timer = setTimeout(() => dismiss(card), 4000); });
    box.append(card);
  }
  let busy = false;
  async function refresh() {
    if (!box || busy || document.hidden) return;
    busy = true;
    try {
      const reply = await fetch(box.dataset.pings, {credentials: 'same-origin', headers: {'Accept': 'application/json'}});
      if (reply.ok) {
        const data = await reply.json();
        data.items.reverse().forEach(show);
        badge(data.unseen);
      }
    } catch (error) { /* 没连上就下次再问 */ }
    busy = false;
  }
  if (box) {
    refresh();
    setInterval(refresh, 60000);
    document.addEventListener('visibilitychange', refresh);
  }

  /* ---------- 长补充折起来，只露三行 ---------- */
  for (const block of document.querySelectorAll('[data-fold]')) {
    const lineHeight = parseFloat(getComputedStyle(block).lineHeight) || 24;
    if (block.scrollHeight <= lineHeight * 3.6) continue;
    block.classList.add('folded');
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'unfold';
    more.textContent = '展开';
    more.addEventListener('click', () => { block.classList.remove('folded'); more.remove(); });
    block.after(more);
  }

  /* ---------- 待办：组标题右边的 + 打开这一组的输入框 ---------- */
  for (const plus of document.querySelectorAll('[data-todo-plus]')) {
    plus.addEventListener('click', () => {
      const form = plus.closest('.tgroup').querySelector('.todo-add');
      form.hidden = false;
      form.querySelector('input[name=title]').focus();
    });
  }

  /* ---------- 待办打勾：不刷新页面 ---------- */
  for (const form of document.querySelectorAll('[data-todo-form]')) {
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const row = form.closest('.todo');
      const input = form.querySelector('input[name=state]');
      const button = form.querySelector('button');
      const next = input.value;
      const before = row.className;
      row.classList.remove('todo', 'doing', 'done');
      row.classList.add('todo', next === 'done' ? 'done' : 'todo', 'pop');
      setTimeout(() => row.classList.remove('pop'), 450);
      try {
        const reply = await post(form.action, new FormData(form));
        if (!reply.ok) throw new Error();
        input.value = next === 'done' ? 'todo' : 'done';
        button.setAttribute('aria-label', (next === 'done' ? '标回没做：' : '做完了：') + row.querySelector('.todo-t').textContent.trim());
        row.querySelector('.todo-more')?.toggleAttribute('hidden', next === 'done');
      } catch (error) {
        row.className = before;
        window.bounty?.toast?.('<span>没保存上，稍后再试</span>');
      }
    });
  }

  /* ---------- 记一笔：⌘/Ctrl + 回车记下；打 @ 先列一起做的人 ---------- */
  const jot = document.querySelector('[data-jot]');
  if (!jot) return;
  const area = jot.querySelector('textarea');
  const people = JSON.parse(jot.querySelector('[data-people]')?.textContent || '[]');
  const grow = () => { area.style.height = 'auto'; area.style.height = Math.min(area.scrollHeight + 2, innerHeight * 0.5) + 'px'; };
  area.addEventListener('input', grow);
  let menu = null, picks = [], index = 0, start = -1;
  function closeMenu() { menu?.remove(); menu = null; start = -1; }
  function choose(person) {
    const caret = area.selectionStart;
    area.value = area.value.slice(0, start + 1) + person.name + ' ' + area.value.slice(caret);
    const at = start + person.name.length + 2;
    area.setSelectionRange(at, at);
    closeMenu();
    area.focus();
  }
  function render() {
    if (!picks.length) { closeMenu(); return; }
    if (!menu) {
      menu = document.createElement('ul');
      menu.className = 'mpick';
      menu.setAttribute('role', 'listbox');
      document.body.append(menu);
    }
    const crew = picks.filter(p => p.crew), rest = picks.filter(p => !p.crew);
    const row = (p, i) => `<li role="option" data-i="${i}" aria-selected="${i === index}"><span class="ava" style="--c:${PALETTE[p.id % 7]}" aria-hidden="true">${esc(p.name.slice(0, 1))}</span><b>${esc(p.name)}</b></li>`;
    const ordered = [...crew, ...rest];
    picks = ordered;
    menu.innerHTML = (crew.length ? '<p>一起做任务的</p>' + crew.map((p, i) => row(p, i)).join('') : '')
      + (rest.length ? (crew.length ? '<p>其他人</p>' : '') + rest.map((p, i) => row(p, crew.length + i)).join('') : '');
    const rect = area.getBoundingClientRect();
    menu.style.left = Math.min(rect.left + 8, innerWidth - 232) + 'px';
    menu.style.top = Math.min(rect.bottom + 4, innerHeight - 200) + 'px';
    menu.querySelectorAll('li').forEach(li => li.addEventListener('mousedown', event => { event.preventDefault(); choose(picks[+li.dataset.i]); }));
  }
  area.addEventListener('input', () => {
    const before = area.value.slice(0, area.selectionStart);
    const match = before.match(/@([^\s@]{0,20})$/);
    if (!match) { closeMenu(); return; }
    start = before.length - match[0].length;
    const word = match[1];
    picks = people.filter(p => p.name.includes(word)).slice(0, 8);
    index = 0;
    render();
  });
  area.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); jot.requestSubmit(); return; }
    if (!menu) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      index = (index + (event.key === 'ArrowDown' ? 1 : picks.length - 1)) % picks.length;
      render();
    } else if ((event.key === 'Enter' || event.key === 'Tab') && !event.isComposing) {
      event.preventDefault();
      choose(picks[index]);
    } else if (event.key === 'Escape') {
      closeMenu();
    }
  });
  area.addEventListener('blur', () => setTimeout(closeMenu, 120));
})();
