/* 提醒：有人提到你、等你验收、等你批延期、被退回要改。
   右上角（手机在底栏上方）弹卡片，点「去看看」或「知道了 / 稍后」才收起，换页面也还在；
   「我的」上的数字、浏览器标签上的 (N) 和小图标上的红点一起变。每分钟问一次服务器，切到后台也问。 */
(() => {
  const box = document.querySelector('.pings[data-alerts-url]');
  if (!box) return;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const PALETTE = ['#2866B1', '#008FBF', '#D98200', '#00A27A', '#E54465', '#9C6B3F', '#1B1D2A'];
  const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const svg = path => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  const MARK = {
    note: svg("<circle cx='12' cy='12' r='3.6'/><path d='M15.6 8.4v4.8a2.4 2.4 0 0 0 4.8 0V12a8.4 8.4 0 1 0-3.3 6.7'/>"),
    talk: svg("<path d='M5.5 5h13A1.5 1.5 0 0 1 20 6.5v8a1.5 1.5 0 0 1-1.5 1.5H12l-5 3.8V16H5.5A1.5 1.5 0 0 1 4 14.5v-8A1.5 1.5 0 0 1 5.5 5z'/>"),
    review: svg("<path d='m5 12.5 4.5 4.5L19 7.5'/>"),
    extend: svg("<circle cx='12' cy='12' r='8'/><path d='M12 7.5V12l3 2'/>"),
    return: svg("<path d='M9 14 4 9l5-5'/><path d='M4 9h10a6 6 0 0 1 0 12h-3'/>"),
  };

  // 本机记两样：收起过的卡片（换设备会再提醒一次）、播过入场动画的卡片。存不了就只在这一页里记。
  const keep = (area, name) => {
    let list = [];
    try { list = JSON.parse(window[area].getItem(name) || '[]'); } catch (error) { /* 隐私模式等 */ }
    const set = new Set(list);
    return {
      has: key => set.has(key),
      add(key) {
        set.add(key);
        try { window[area].setItem(name, JSON.stringify([...set].slice(-300))); } catch (error) { /* 同上 */ }
      },
    };
  };
  const putAway = keep('localStorage', 'yui-alerts-away');
  const shown = keep('localStorage', 'yui-alerts-shown');
  const dots = keep('sessionStorage', 'yui-dots');

  /* ---------- 数字、标签标题、小图标 ---------- */
  const links = [...document.querySelectorAll('a[data-alerts]')];
  const title = document.title.replace(/^\(\d+\) /, '');
  const favicon = document.querySelector('link[rel="icon"]');
  const plainIcon = favicon?.href;
  const dotIcon = plainIcon?.replace(/%3C\/svg%3E$/, "%3Ccircle cx='32' cy='9' r='7.5' fill='%23E54465' stroke='white' stroke-width='2.5'/%3E%3C/svg%3E");
  let count = Number(links[0]?.querySelector('b')?.textContent || 0);

  function setCount(next, fresh) {
    for (const link of links) {
      let mark = link.querySelector('b');
      if (!next) { mark?.remove(); continue; }
      if (!mark) { mark = document.createElement('b'); link.append(mark); }
      mark.setAttribute('aria-label', `${next} 件事等你`);
      if (mark.textContent !== String(next)) {
        mark.textContent = next;
        mark.classList.remove('bump'); void mark.offsetWidth; mark.classList.add('bump');
      }
      if (fresh) { mark.classList.remove('fresh'); void mark.offsetWidth; mark.classList.add('fresh'); }
    }
    document.title = next ? `(${next}) ${title}` : title;
    if (favicon && dotIcon) favicon.href = next ? dotIcon : plainIcon;
    count = next;
  }
  // 这次打开网站后第一次看到、或者比上一页多了，数字扩散一圈；小点同理，同一个状态只闪一次
  let last = 0;
  try { last = Number(sessionStorage.getItem('yui-alerts-last') || 0); } catch (error) { /* 同上 */ }
  const remember = n => { try { sessionStorage.setItem('yui-alerts-last', String(n)); } catch (error) { /* 同上 */ } };
  setCount(count, count > last);
  remember(count);
  for (const dot of document.querySelectorAll('.ndot[data-dot]')) {
    if (!dots.has(dot.dataset.dot)) dot.classList.add('fresh');
  }
  for (const dot of document.querySelectorAll('.ndot[data-dot]')) dots.add(dot.dataset.dot);

  /* ---------- 卡片 ---------- */
  const post = url => fetch(url, {method: 'POST', credentials: 'same-origin',
    headers: {'X-CSRF-Token': csrf, 'X-Requested-With': 'fetch', 'Accept': 'application/json'}});
  const cards = new Map();
  let items = [];
  const rung = new Set();

  function ago(at) {
    const minutes = Math.round((Date.now() - new Date(at)) / 60000);
    if (!(minutes >= 0)) return '';
    if (minutes < 1) return '刚刚';
    if (minutes < 60) return `${minutes} 分钟前`;
    if (minutes < 60 * 24) return `${Math.round(minutes / 60)} 小时前`;
    const day = new Date(at);
    return `${day.getMonth() + 1}/${day.getDate()}`;
  }
  function card(item) {
    const el = document.createElement('article');
    el.className = 'ping';
    el.dataset.kind = item.kind;
    el.setAttribute('role', 'status');
    el.innerHTML = `<span class="ping-ava"><span class="ava" style="--c:${PALETTE[item.who_id % 7]}" aria-hidden="true">${esc(item.who.slice(0, 1))}</span><i>${MARK[item.kind] || MARK.note}</i></span>
      <div class="ping-b"><p class="ping-m"><b>${esc(item.who)}</b>${esc(item.what)}<time>${esc(ago(item.at))}</time></p>
        <p class="ping-h">${esc(item.head)}</p>${item.sub ? `<p class="ping-s">${esc(item.sub)}</p>` : ''}
        <div class="ping-a"><a class="mini dark" href="${esc(item.url)}">${esc(item.go)}</a><button class="mini ghost" type="button">${item.ack ? '知道了' : '稍后'}</button></div></div>`;
    el.querySelector('a').addEventListener('click', () => putAway.add(item.key));
    el.querySelector('button').addEventListener('click', async () => {
      putAway.add(item.key);
      items = items.filter(other => other.key !== item.key);
      if (item.ack) {
        setCount(Math.max(0, count - 1));
        remember(count);
        try { await post(item.ack); } catch (error) { /* 下次刷新会按服务器的数为准 */ }
      }
      render();
    });
    return el;
  }
  function leave(el) {
    el.classList.add('out');
    setTimeout(() => el.remove(), 280);
  }
  function render() {
    const here = location.pathname;
    const open = items.filter(item => {
      if (putAway.has(item.key)) return false;
      if (new URL(item.url, location.href).pathname === here) { putAway.add(item.key); return false; }   // 已经在那一页了
      return true;
    });
    const visible = open.slice(0, 1);   // 一次只摆一张，其余收成「还有 N 件」，不把页面盖满
    const keys = new Set(visible.map(item => item.key));
    for (const [key, el] of cards) {
      if (!keys.has(key)) { leave(el); cards.delete(key); }
    }
    let fresh = false;
    visible.forEach((item, index) => {
      let el = cards.get(item.key);
      if (!el) {
        el = card(item);
        if (!shown.has(item.key)) { el.classList.add('new'); shown.add(item.key); if (!rung.has(item.key)) fresh = true; }
        cards.set(item.key, el);
      }
      const at = box.children[index];
      if (at !== el) box.insertBefore(el, at || null);
    });
    let more = box.querySelector('.ping-more');
    const rest = open.length - visible.length;
    if (rest > 0) {
      if (!more) { more = document.createElement('a'); more.className = 'ping-more'; more.href = box.dataset.mine; }
      more.innerHTML = `还有 <b>${rest}</b> 件等你`;
      box.append(more);
    } else if (more) {
      leave(more);
    }
    if (fresh) window.bounty?.sfx('ping');
  }

  let busy = false;
  async function refresh() {
    if (busy) return;
    busy = true;
    try {
      const reply = await fetch(box.dataset.alertsUrl, {credentials: 'same-origin', headers: {'Accept': 'application/json'}});
      if (reply.ok) {
        const data = await reply.json();
        items = data.items;
        setCount(data.count, data.count > count);
        remember(data.count);
        if (document.hidden) {
          // 在别的标签页：只改标题和小图标，有新的就响一声；卡片等回来再弹，免得动画白放
          const unheard = items.filter(item => !shown.has(item.key) && !putAway.has(item.key) && !rung.has(item.key));
          if (unheard.length) window.bounty?.sfx('ping');
          unheard.forEach(item => rung.add(item.key));
        } else {
          render();
        }
      }
    } catch (error) { /* 没连上就下次再问 */ }
    busy = false;
  }
  refresh();
  setInterval(refresh, 60000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();
