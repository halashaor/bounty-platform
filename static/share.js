/* 存成图片和学期绘卷。
   图片在浏览器里现场画：先拼一张纯 SVG（不引用任何外部资源），再画到 canvas 上导出 PNG，不经过服务器。
   手机浏览器经常不支持直接下载，所以导出后先弹出预览，可以长按保存。 */
(() => {
  const feel = window.bounty || {play() { return null; }, sfx() {}, toast() {}, countTo(el, to) { el.textContent = to; return Promise.resolve(); }, motionOn: () => false, B: 'ease', C: 'ease', D: 'ease'};
  const FONT = "'Hiragino Sans','PingFang SC','Noto Sans CJK SC','Source Han Sans SC','Microsoft YaHei',sans-serif";
  const NUM = "'Helvetica Neue',Helvetica,Arial,sans-serif";
  const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const template = document.querySelector('template[data-medal-template]');
  // 把页面里的勋章 SVG 嵌进大图：只改位置和大小
  const medalAt = (key, x, y, size) => (template?.content.querySelector(`[data-key="${key}"]`)?.innerHTML || '')
    .replace('<svg ', `<svg x="${x}" y="${y}" width="${size}" height="${size}" `);
  const today = () => { const d = new Date(); return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`; };

  // 印章：四个字两列、三个字一列，从右往左读
  function sealSvg(name, color, x, y, size) {
    const chars = [...name];
    const cols = chars.length === 4 ? 2 : 1;
    const rows = Math.ceil(chars.length / cols);
    const cell = (size - 24) / Math.max(rows, cols);
    const w = cols * cell + 24;
    const h = rows * cell + 24;
    const text = chars.map((ch, i) => {
      const col = cols - 1 - Math.floor(i / rows);
      const row = i % rows;
      return `<text x="${x + 12 + col * cell + cell / 2}" y="${y + 12 + row * cell + cell * 0.82}" font-size="${cell * 0.9}" font-weight="900" text-anchor="middle" fill="${color}">${esc(ch)}</text>`;
    }).join('');
    return `<g transform="rotate(-6 ${x + w / 2} ${y + h / 2})"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="10" fill="#fff" stroke="${color}" stroke-width="6"/>${text}</g>`;
  }

  function plateImage(d) {
    const W = 1200, H = 720;
    const accent = d.hue === '#F2B700' ? '#2866B1' : '#F2B700';
    const medals = (d.medals || []).slice(0, 3).map((key, i) =>
      `<circle cx="${64 + i * 168 + 70}" cy="${470 + 70}" r="76" fill="#fff"/>${medalAt(key, 64 + i * 168, 470, 140)}`).join('');
    const empty = Array.from({length: 3 - Math.min(3, (d.medals || []).length)}, (_, i) =>
      `<circle cx="${64 + ((d.medals || []).length + i) * 168 + 70}" cy="540" r="66" fill="none" stroke="#fff" stroke-width="5" stroke-dasharray="14 12"/>`).join('');
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
      <style>text{font-family:${FONT}}.num{font-family:${NUM}}</style>
      <defs><clipPath id="c"><rect width="${W}" height="${H}" rx="56"/></clipPath><clipPath id="b"><rect x="780" y="190" width="340" height="340" rx="22"/></clipPath></defs>
      <g clip-path="url(#c)">
        <rect width="${W}" height="${H}" fill="${d.hue}"/>
        ${d.build && window.yuiBlocks ? `<rect x="766" y="176" width="368" height="368" rx="32" fill="#fff"/><g clip-path="url(#b)">${window.yuiBlocks.markup(d.build).replace('<svg ', '<svg x="780" y="190" width="340" height="340" ')}</g>` : `
        <g transform="translate(80 0) scale(4)">
          <path d="M280 180H150A130 130 0 0 1 280 50Z" fill="${accent}"/>
          <circle cx="168" cy="34" r="3.4" fill="#fff"/><circle cx="180" cy="34" r="3.4" fill="#fff"/><circle cx="191" cy="34" r="3.4" fill="#fff"/>
          <path d="M198 34H246" stroke="#fff" stroke-width="6.8" stroke-linecap="round"/><circle cx="152" cy="34" r="7" fill="#1B1D2A"/>
        </g>`}
        ${d.complete ? `<rect x="14" y="14" width="${W - 28}" height="${H - 28}" rx="44" fill="none" stroke="#F2B700" stroke-width="12"/><rect x="34" y="34" width="${W - 68}" height="${H - 68}" rx="30" fill="none" stroke="#fff" stroke-width="3"/>` : ''}
      </g>
      <rect x="64" y="64" width="150" height="56" rx="28" fill="#fff"/><text class="num" x="139" y="102" font-size="30" font-weight="800" text-anchor="middle" fill="#1B1D2A">Lv.${d.level}</text>
      <rect x="226" y="64" width="${40 + [...d.level_name].length * 30}" height="56" rx="28" fill="#1B1D2A"/><text x="${246 + [...d.level_name].length * 15}" y="101" font-size="28" font-weight="800" text-anchor="middle" fill="#fff">${esc(d.level_name)}</text>
      ${d.complete ? `<rect x="${246 + [...d.level_name].length * 30 + 16}" y="64" width="150" height="56" rx="28" fill="#F2B700"/><text x="${246 + [...d.level_name].length * 30 + 91}" y="101" font-size="28" font-weight="800" text-anchor="middle" fill="#1B1D2A">全收集</text>` : ''}
      <text x="64" y="330" font-size="128" font-weight="800" fill="#fff">${esc(d.name)}</text>
      ${d.title ? sealSvg(d.title.name, d.title.color, d.build ? 620 : 1000, 60, d.build ? 120 : 150) : ''}
      ${medals}${empty}
      <text x="64" y="${H - 40}" font-size="24" font-weight="700" fill="#fff" fill-opacity=".85">結 YUI · ${d.total} 枚勋章 · ${d.xp} 经验 · ${today()}</text>
    </svg>`;
    return {svg, w: W, h: H};
  }

  function wrap(text, size) {
    const lines = [];
    let line = '';
    for (const ch of [...text]) {
      line += ch;
      if (line.length >= size) { lines.push(line); line = ''; }
    }
    if (line) lines.push(line);
    return lines.slice(0, 3);
  }

  function recapImage(d) {
    const W = 1080, H = 1350;
    const medals = (d.medals || []).slice(0, 6).map(([key, n], i) =>
      `${medalAt(key, 80 + i * 156, 860, 128)}<text class="num" x="${80 + i * 156 + 64}" y="1030" font-size="30" font-weight="800" text-anchor="middle" fill="#fff">×${n}</text>`).join('');
    const quote = d.quote ? wrap(`「${d.quote.text}」`, 15) : [];
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
      <style>text{font-family:${FONT}}.num{font-family:${NUM}}</style>
      <rect width="${W}" height="${H}" fill="#1B1D2A"/>
      <circle cx="960" cy="120" r="200" fill="#E54465"/><rect x="820" y="1120" width="260" height="260" fill="#2866B1"/>
      <path d="M${W} ${H}H860A220 220 0 0 1 ${W} ${H - 220}Z" fill="#F2B700"/>
      ${[0, 1, 2, 3, 4].map(i => `<circle cx="${560 + i * 30}" cy="110" r="7" fill="#fff"/>`).join('')}
      <rect x="80" y="90" width="${60 + [...d.term].length * 30}" height="60" rx="30" fill="#F2B700"/>
      <text x="${110 + [...d.term].length * 15}" y="131" font-size="30" font-weight="800" text-anchor="middle" fill="#1B1D2A">${esc(d.term)}</text>
      <text x="80" y="280" font-size="96" font-weight="800" fill="#fff">${esc(d.name)}</text>
      <text x="80" y="345" font-size="36" font-weight="700" fill="#fff" fill-opacity=".7">的这一学期</text>
      ${[[d.done, '个任务'], [`+${d.gained}`, '经验'], [d.helped, '位队友']].map(([n, unit], i) =>
        `<text class="num" x="${80 + i * 320}" y="540" font-size="120" font-weight="700" fill="#fff">${n}</text><text x="${80 + i * 320}" y="600" font-size="34" font-weight="700" fill="#fff" fill-opacity=".75">${unit}</text>`).join('')}
      ${d.tag ? `<text x="80" y="740" font-size="40" font-weight="800" fill="#00AEE0">最常做 #${esc(d.tag)}</text>` : ''}
      ${medals}
      ${quote.map((line, i) => `<text x="80" y="${1130 + i * 56}" font-size="42" font-weight="800" fill="#fff">${esc(line)}</text>`).join('')}
      ${d.quote ? `<text x="80" y="${1130 + quote.length * 56 + 10}" font-size="28" font-weight="700" fill="#fff" fill-opacity=".7">— ${esc(d.quote.by)}</text>` : ''}
      <text x="80" y="${H - 70}" font-size="28" font-weight="700" fill="#fff" fill-opacity=".85">結 YUI · Lv.${d.level} ${esc(d.level_name)}</text>
    </svg>`;
    return {svg, w: W, h: H};
  }

  async function savePng({svg, w, h}, filename) {
    const url = URL.createObjectURL(new Blob([svg], {type: 'image/svg+xml;charset=utf-8'}));
    try {
      const img = new Image();
      img.src = url;
      await img.decode();
      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      canvas.getContext('2d').drawImage(img, 0, 0, w, h);
      const png = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
      preview(URL.createObjectURL(png), filename);
    } catch {
      feel.toast('<span>这个浏览器画不出图片，换 Chrome 或 Edge 试试</span>');
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  function preview(src, filename) {
    const dialog = document.createElement('dialog');
    dialog.className = 'share-dialog';
    dialog.innerHTML = `<img alt="${esc(filename)}" src="${src}"><p>手机上长按图片也能保存。</p>
      <div class="share-actions"><a class="btn" download="${esc(filename)}" href="${src}">下载图片</a><button type="button" class="btn btn-line">关闭</button></div>`;
    document.body.append(dialog);
    dialog.querySelector('button').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => { dialog.remove(); URL.revokeObjectURL(src); });
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    dialog.showModal();
    feel.sfx('tap');
  }

  const read = id => { try { return JSON.parse(document.getElementById(id).textContent); } catch { return null; } };
  document.querySelector('[data-save-plate]')?.addEventListener('click', () => {
    const data = read('plate-data');
    if (data) savePng(plateImage(data), `結YUI-名牌-${data.name}.png`);
  });
  document.querySelector('[data-save-recap]')?.addEventListener('click', () => {
    const data = read('recap-data');
    if (data) savePng(recapImage(data), `結YUI-${data.term}绘卷-${data.name}.png`);
  });

  /* ---------- 称号墙：点一下，印章先盖下去再提交 ---------- */
  document.querySelectorAll('[data-title-form]').forEach(form => form.addEventListener('submit', event => {
    const seal = form.querySelector('.hanko');
    const motion = feel.play(seal, [{transform: 'scale(1.5) rotate(-20deg)', opacity: .4}, {transform: 'scale(.92) rotate(-6deg)', opacity: 1, offset: .6}, {transform: 'rotate(-6deg)'}], {duration: 300, easing: feel.D});
    feel.sfx('stamp');
    if (!motion) return;
    event.preventDefault();
    motion.finished.then(() => HTMLFormElement.prototype.submit.call(form));
  }));

  /* ---------- 学期绘卷：翻到哪一屏，哪一屏的内容依次出来，数字从 0 数上去 ---------- */
  const slides = document.querySelectorAll('.slide');
  if (slides.length) {
    if (!('IntersectionObserver' in window) || !feel.motionOn()) slides.forEach(slide => slide.classList.add('in'));
    else {
      const seen = new IntersectionObserver(entries => entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        const slide = entry.target;
        slide.classList.add('in');
        seen.unobserve(slide);
        slide.querySelectorAll('[data-count]').forEach(el => {
          const to = Number(el.dataset.count);
          if (to > 1) feel.countTo(el, to, {from: 0, duration: 900, onTick: k => feel.sfx('tick', {pitch: 1 + k * 0.6})});
        });
      }), {threshold: 0.35});
      slides.forEach(slide => seen.observe(slide));
    }
  }
})();
