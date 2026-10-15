/* 积木的立体画法：作品缩略图、零件小图和编辑器共用这一份。
   - 坐标：x、y 以格计（板子 SIZE×SIZE），z 以「层」计，一层半格高。一个零件是 [种类, 颜色, x, y, z, r]：
     (x, y, z) 是它占的那块空间的最小角，r 是水平转了几个 90°。零件的尺寸 [宽, 深, 层数] 由页面上的 #block-data 给出。
   - 2:1 等轴测的正交投影；视角可以绕竖轴转四个方向（view），转视角就是把整个板子转过去再画。
   - 每个零件拆成几块实体，按包围盒的前后关系拓扑排序，从后往前画，结果是纯 SVG 字符串。
   - 页面上的 <svg data-build="{…}"> 和 <svg data-part-icon="种类"> 在加载时自动画好。 */
(() => {
  const D = JSON.parse(document.getElementById('block-data')?.textContent || 'null');
  if (!D) return;
  const SIZE = D.size;
  const LEVEL = 0.5;
  const HX = 10, HY = 5, S = 10 * Math.SQRT2, ZK = S * Math.sqrt(3) / 2, K = ZK / (2 * HY);
  const VIEW = [0.6124, 0.6124, 0.5];   // 指向看的人
  const LIGHT = [0.15, 0.45, 0.88];     // 光从左上方来：顶面最亮，左前面次之，右前面最暗
  const E = 1e-6;
  const n2 = v => Math.round(v * 100) / 100;
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const unit = v => { const l = Math.hypot(...v) || 1; return v.map(c => c / l); };
  const P = (x, y, z) => [(x - y) * HX, (x + y) * HY - z * ZK];
  const pt = p => `${n2(p[0])} ${n2(p[1])}`;

  /* ---------- 颜色：同一种颜色按朝向分出明暗 ---------- */
  const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
  const toHex = c => '#' + c.map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('');
  const mix = (a, b, t) => { const x = rgb(a), y = rgb(b); return toHex(x.map((v, i) => v + (y[i] - v) * t)); };
  const luminance = hex => { const [r, g, b] = rgb(hex).map(v => v / 255); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const tones = new Map();
  function tone(base, b) {
    b = Math.round(Math.max(0, Math.min(1, b)) * 50) / 50;
    const key = base + b;
    if (!tones.has(key)) {
      tones.set(key, luminance(base) < 0.15 ? mix(base, '#FFFFFF', 0.04 + b * 0.26)
        : b > 0.6 ? mix(base, '#FFFFFF', Math.min(1, (b - 0.6) / 0.3) * 0.22)
          : mix(base, '#1B1D2A', Math.min(1, (0.6 - b) / 0.45) * 0.3));
    }
    return tones.get(key);
  }
  const lit = n => dot(unit(n), LIGHT);
  const face = (points, fill) => `<path d="M${points.map(pt).join('L')}Z" fill="${fill}" stroke="${fill}" stroke-width=".35" stroke-linejoin="round"/>`;

  /* ---------- 零件的位置和朝向 ---------- */
  const size = id => D.parts[id] || [1, 1, 1];
  const footprint = (id, r) => { const [w, d] = size(id); return r % 2 ? [d, w] : [w, d]; };
  // 本地坐标 (u, v) 转 r 次：每次 (u, v) → (d − v, u)，宽和深互换
  function turn(u, v, w, d, r) {
    for (let i = 0; i < r; i++) { [u, v] = [d - v, u]; [w, d] = [d, w]; }
    return [u, v];
  }
  function turnVec(a, b, r) {
    for (let i = 0; i < r; i++) [a, b] = [-b, a];
    return [a, b];
  }
  // 换视角：整块板子绕竖轴转 view 次，零件的位置和朝向一起转
  function toView([id, color, x, y, z, r], view) {
    for (let i = 0; i < view; i++) {
      const [, fd] = footprint(id, r);
      [x, y] = [SIZE - (y + fd), x];
      r = (r + 1) % 4;
    }
    return {id, color, x, y, z, r};
  }
  // 视角里的一个点换回板子上的坐标（点是连续的，不是格子）
  function fromView(x, y, view) {
    for (let i = 0; i < view; i++) [x, y] = [y, SIZE - x];
    return [x, y];
  }
  function extent(part) {   // 占的空间：[x0, y0, z0, x1, y1, z1]，z 以层计
    const [fw, fd] = footprint(part[0], part[5]);
    return [part[2], part[3], part[4], part[2] + fw, part[3] + fd, part[4] + size(part[0])[2]];
  }
  const overlapsXY = (a, b) => a[0] < b[3] && b[0] < a[3] && a[1] < b[4] && b[1] < a[4];
  // 落到哪一层：脚下所有零件里最高的那个顶
  function dropLevel(parts, id, x, y, r, skip = -1) {
    const [fw, fd] = footprint(id, r);
    const box = [x, y, 0, x + fw, y + fd, 0];
    return parts.reduce((top, other, i) => i === skip || !overlapsXY(box, extent(other)) ? top : Math.max(top, extent(other)[5]), 0);
  }
  // 重力：按高低顺序，每个零件都落到它下面最高的那个顶上（下面的被拿走，上面的就掉下来）
  function settle(parts) {
    const order = parts.map((_, i) => i).sort((a, b) => parts[a][4] - parts[b][4] || a - b);
    const placed = [];
    for (const i of order) {
      const box = extent(parts[i]);
      parts[i][4] = placed.reduce((top, j) => overlapsXY(box, extent(parts[j])) ? Math.max(top, extent(parts[j])[5]) : top, 0);
      placed.push(i);
    }
    return parts;
  }

  /* ---------- 实体 ---------- */
  function boxSolid(x0, y0, z0, x1, y1, z1, color) {
    return {b: [x0, y0, z0, x1, y1, z1], draw: () =>
      face([P(x0, y1, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y1, z1)], tone(color, LIGHT[1])) +
      face([P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)], tone(color, LIGHT[0])) +
      face([P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)], tone(color, LIGHT[2]))};
  }
  // 竖着的圆柱：侧面按朝向分成几条，越朝光越亮；最后盖上顶面
  function cylinder(cx, cy, z0, z1, rho, color, bands = 6) {
    const [bx, by] = P(cx, cy, z0), [tx, ty] = P(cx, cy, z1);
    const rx = rho * S, ry = rho * S / 2;
    let out = '';
    for (let i = 0; i < bands; i++) {
      const a = Math.PI * i / bands, b = Math.PI * (i + 1) / bands, theta = (a + b) / 2 - Math.PI / 4;
      const fill = tone(color, Math.max(0, lit([Math.cos(theta), Math.sin(theta), 0])));
      const at = (x, y, t) => `${n2(x + rx * Math.cos(t))} ${n2(y + ry * Math.sin(t))}`;
      out += `<path d="M${at(tx, ty, a)}A${n2(rx)} ${n2(ry)} 0 0 1 ${at(tx, ty, b)}L${at(bx, by, b)}A${n2(rx)} ${n2(ry)} 0 0 0 ${at(bx, by, a)}Z" fill="${fill}" stroke="${fill}" stroke-width=".35"/>`;
    }
    const top = tone(color, LIGHT[2]);
    return out + `<ellipse cx="${n2(tx)}" cy="${n2(ty)}" rx="${n2(rx)}" ry="${n2(ry)}" fill="${top}" stroke="${top}" stroke-width=".35"/>`;
  }
  function sphere(cx, cy, cz, rho, color) {
    const [x, y] = P(cx, cy, cz), R = rho * S;
    const c = (dx, dy, r, b) => `<circle cx="${n2(x + dx * R)}" cy="${n2(y + dy * R)}" r="${n2(r * R)}" fill="${tone(color, b)}"/>`;
    return c(0, 0, 1, 0.12) + c(-0.08, -0.08, 0.88, 0.45) + c(-0.2, -0.27, 0.52, 0.72) + c(-0.36, -0.42, 0.13, 0.95);
  }
  function dome(cx, cy, z0, rho, color) {
    const [x, y] = P(cx, cy, z0), R = rho * S;
    const shape = (dx, dy, k, b) => {
      const ox = x + dx * R, oy = y + dy * R, r = k * R;
      return `<path d="M${n2(ox - r)} ${n2(oy)}A${n2(r)} ${n2(r)} 0 0 1 ${n2(ox + r)} ${n2(oy)}A${n2(r)} ${n2(r / 2)} 0 0 1 ${n2(ox - r)} ${n2(oy)}Z" fill="${tone(color, b)}"/>`;
    };
    return shape(0, 0, 1, 0.12) + shape(-0.1, -0.04, 0.86, 0.45) +
      `<ellipse cx="${n2(x - 0.3 * R)}" cy="${n2(y - 0.5 * R)}" rx="${n2(0.3 * R)}" ry="${n2(0.2 * R)}" fill="${tone(color, 0.78)}"/>`;
  }
  function cone(cx, cy, z0, z1, rho, color) {
    const [x, y] = P(cx, cy, z0), [, ay] = P(cx, cy, z1);
    const rx = rho * S, ry = rx / 2, H = y - ay;
    const s = Math.min(0.99, ry / H), c = Math.sqrt(1 - s * s);
    const right = `${n2(x + rx * c)} ${n2(y - ry * s)}`, left = `${n2(x - rx * c)} ${n2(y - ry * s)}`, front = `${n2(x)} ${n2(y + ry)}`;
    return `<path d="M${n2(x)} ${n2(ay)}L${front}A${n2(rx)} ${n2(ry)} 0 0 1 ${left}Z" fill="${tone(color, LIGHT[1])}" stroke="${tone(color, LIGHT[1])}" stroke-width=".35"/>` +
      `<path d="M${n2(x)} ${n2(ay)}L${right}A${n2(rx)} ${n2(ry)} 0 0 1 ${front}Z" fill="${tone(color, LIGHT[0])}" stroke="${tone(color, LIGHT[0])}" stroke-width=".35"/>`;
  }
  const arc = (cu, cz, rho, from, to, steps) =>
    Array.from({length: steps + 1}, (_, i) => { const t = from + (to - from) * i / steps; return [cu + rho * Math.cos(t), cz + rho * Math.sin(t)]; });

  function medalArt(key) {
    const [weight, pace] = key.split('-');
    let art = `<circle cx="50" cy="50" r="50" fill="${D.medals[key]}"/><circle cx="50" cy="50" r="46.6" fill="none" stroke="#fff" stroke-opacity=".5" stroke-width="1.2"/>`;
    if (weight === 'light') art += '<circle cx="50" cy="50" r="16" fill="#1B1D2A"/>';
    else if (weight === 'standard') art += '<circle cx="18" cy="50" r="8" fill="#1B1D2A"/>' + [32, 42.5, 51.5].map(x => `<circle cx="${x}" cy="50" r="4.6" fill="#fff"/>`).join('') +
      '<path d="M59 45.4H92.75V54.6H59A4.6 4.6 0 0 1 59 45.4Z" fill="#fff"/>';
    else art += '<rect x="17" y="31" width="6" height="38" rx="3" fill="#1B1D2A"/><rect x="29.5" y="31" width="4" height="38" fill="#fff"/><rect x="38" y="31" width="7" height="38" fill="#fff"/><path d="M50 7A43 43 0 0 1 50 93Z" fill="#fff"/>';
    if (pace === 'urgent') art += '<circle cx="85" cy="15" r="14" fill="#1B1D2A" stroke="#fff" stroke-width="3"/><text x="85" y="20.2" text-anchor="middle" font-size="14.5" font-weight="700" fill="#fff">急</text>';
    return art;
  }

  /* ---------- 零件的样子：本地坐标里 u 沿宽、v 沿深，高度以格计 ---------- */
  const SHAPES = {
    stud: k => k.round((x, y, z0, z1, c) => cylinder(x, y, z0, z1, 0.34, c, 4)),
    ball: k => k.round((x, y, z0, z1, c) => sphere(x, y, (z0 + z1) / 2, 0.47, c)),
    dome: k => k.round((x, y, z0, z1, c) => dome(x, y, z0, 0.96, c)),
    cylinder: k => k.round((x, y, z0, z1, c) => cylinder(x, y, z0, z1, 0.96, c)),
    'ball-l': k => k.round((x, y, z0, z1, c) => sphere(x, y, (z0 + z1) / 2, 0.96, c)),
    cone: k => k.round((x, y, z0, z1, c) => cone(x, y, z0, z1, 0.96, c)),
    knot(k) {
      k.box(0.3, 0.2, 0, 2.7, 0.8, 0.2);
      const [left, right] = [[1.1, 1.1], [1.9, 1.1]], outer = 0.84, inner = 0.6;
      const circle = ([cu, cz], rho, v, from = 0, to = Math.PI * 2, steps = 32) => arc(cu, cz, rho, from, to, steps).map(([u, z]) => [u, v, z]);
      k.custom(0.26, 0.4, 0.26, 2.74, 0.6, 1.94, () => {
        const near = k.facing([0, -1, 0]) ? 0.4 : 0.6, far = 1 - near;
        const b = lit(k.N([0, near === 0.4 ? -1 : 1, 0])), line = tone(k.color, 0.05);
        const ring = (c, v, shade, edge) => k.flat([circle(c, outer, v), circle(c, inner, v)], k.color, shade, edge);
        // 背面压暗一点露出厚度；正面先画左环再画右环，再把左环在上面交叉的那一段补回最上面，两个环就扣在一起
        const from = 0.5, to = 1.5;
        return ring(left, far, 0.2) + ring(right, far, 0.2) + ring(left, near, b, line) + ring(right, near, b, line) +
          k.flat([[...circle(left, outer, near, from, to, 10), ...circle(left, inner, near, to, from, 10)]], k.color, b) +
          k.line(circle(left, outer, near, from, to, 10), line) + k.line(circle(left, inner, near, from, to, 10), line);
      });
    },
    'beam-3': k => k.box(0, 0, 0, 3, 1, 0.5),
    'beam-6': k => k.box(0, 0, 0, 6, 1, 0.5),
    pillar(k) {
      k.box(0, 0, 0, 1, 1, 0.25);
      k.box(0.15, 0.15, 0.25, 0.85, 0.85, 2.75);
      k.box(0, 0, 2.75, 1, 1, 3);
    },
    stairs(k) {
      for (let i = 0; i < 3; i++) k.box(0, i, i * 0.5, 1, 3, (i + 1) * 0.5);
    },
    fence(k) {
      for (const u of [0, 1.85, 3.7]) k.box(u, 0.35, 0, u + 0.3, 0.65, 1);
      for (const [a, b] of [[0.3, 1.85], [2.15, 3.7]]) {
        k.box(a, 0.42, 0.28, b, 0.58, 0.42);
        k.box(a, 0.42, 0.66, b, 0.58, 0.8);
      }
    },
    arch(k) {
      k.custom(0, 0, 0, 4, 1, 2, () => {
        const hole = arc(2, 0, 1, 0, Math.PI, 14);
        let inner = [];
        for (let i = 0; i < hole.length - 1; i++) {
          const [u0, z0] = hole[i], [u1, z1] = hole[i + 1];
          const m = Math.atan2((z0 + z1) / 2, (u0 + u1) / 2 - 2);
          inner.push({points: [[u0, 0, z0], [u1, 0, z1], [u1, 1, z1], [u0, 1, z0]], n: [-Math.cos(m), 0, -Math.sin(m)]});
        }
        inner = inner.filter(f => k.facing(f.n)).sort((a, b) => k.depth(a.points) - k.depth(b.points));
        const wall = v => [[[0, v, 0], [1, v, 0], ...hole.map(([u, z]) => [4 - u, v, z]), [3, v, 0], [4, v, 0], [4, v, 2], [0, v, 2]]];
        return inner.map(f => k.flat([f.points], k.color, lit(k.N(f.n)))).join('') + k.faces([
          {points: wall(0), n: [0, -1, 0]}, {points: wall(1), n: [0, 1, 0]},
          {points: [[[0, 0, 2], [4, 0, 2], [4, 1, 2], [0, 1, 2]]], n: [0, 0, 1]},
          {points: [[[0, 0, 0], [0, 1, 0], [0, 1, 2], [0, 0, 2]]], n: [-1, 0, 0]},
          {points: [[[4, 0, 0], [4, 1, 0], [4, 1, 2], [4, 0, 2]]], n: [1, 0, 0]},
        ]);
      });
    },
    block: k => k.box(0, 0, 0, 1, 1, 1),
    plate: k => k.box(0, 0, 0, 4, 4, 0.5),
    slope: k => k.convex([
      {points: [[0, 0, 0], [2, 0, 0], [2, 2, 1], [0, 2, 1]], n: [0, -1, 2]},
      {points: [[0, 2, 0], [2, 2, 0], [2, 2, 1], [0, 2, 1]], n: [0, 1, 0]},
      {points: [[0, 0, 0], [0, 2, 0], [0, 2, 1]], n: [-1, 0, 0]},
      {points: [[2, 0, 0], [2, 2, 0], [2, 2, 1]], n: [1, 0, 0]},
    ]),
    quarter(k) {
      const edge = arc(0, 0, 2, 0, Math.PI / 2, 10);
      const faces = [
        {points: [[0, 0, 1], ...edge.map(([u, v]) => [u, v, 1])], n: [0, 0, 1]},
        {points: [[0, 0, 0], [0, 2, 0], [0, 2, 1], [0, 0, 1]], n: [-1, 0, 0]},
        {points: [[0, 0, 0], [2, 0, 0], [2, 0, 1], [0, 0, 1]], n: [0, -1, 0]},
      ];
      for (let i = 0; i < edge.length - 1; i++) {
        const [u0, v0] = edge[i], [u1, v1] = edge[i + 1], m = Math.PI / 40 * (2 * i + 1);
        faces.push({points: [[u0, v0, 0], [u1, v1, 0], [u1, v1, 1], [u0, v0, 1]], n: [Math.cos(m), Math.sin(m), 0]});
      }
      k.convex(faces);
    },
    roof: k => k.convex([
      {points: [[0, 0, 0], [4, 0, 0], [4, 2, 2], [0, 2, 2]], n: [0, -1, 1]},
      {points: [[0, 2, 2], [4, 2, 2], [4, 4, 0], [0, 4, 0]], n: [0, 1, 1]},
      {points: [[0, 0, 0], [0, 2, 2], [0, 4, 0]], n: [-1, 0, 0]},
      {points: [[4, 0, 0], [4, 2, 2], [4, 4, 0]], n: [1, 0, 0]},
    ]),
    'block-l': k => k.box(0, 0, 0, 2, 2, 2),
    // 勋章：站在小底座上的一枚勋章，正面朝外；底座用选的颜色
    medal(k) {
      k.box(0.25, 0.2, 0, 1.75, 0.8, 0.22);
      const rho = 0.8, cu = 1, cz = 1.06;
      k.custom(cu - rho, 0.43, cz - rho, cu + rho, 0.57, cz + rho, () => {
        const near = k.facing([0, -1, 0]) ? 0.43 : 0.57, far = near === 0.43 ? 0.57 : 0.43;
        let e = k.Pdir([1, 0, 0]);
        if (e[0] < 0) e = e.map(c => -c);
        const at = v => {
          const [x, y] = P(...k.L(cu, v, cz)), s = rho / 50;
          return `matrix(${n2(e[0] * s * 1000) / 1000} ${n2(e[1] * s * 1000) / 1000} 0 ${n2(ZK * s * 1000) / 1000} ${n2(x - 50 * e[0] * s)} ${n2(y - 50 * (e[1] + ZK) * s)})`;
        };
        const hue = D.medals[k.part.id.slice(6)];
        const rim = tone(hue, 0.1);
        return [far, (far + near) / 2].map(v => `<g transform="${at(v)}"><circle cx="50" cy="50" r="50" fill="${rim}"/></g>`).join('') +
          `<g transform="${at(near)}">${medalArt(k.part.id.slice(6))}</g>`;
      });
    },
  };

  function solidsOf(part) {   // part 已经在视角坐标里
    const [w, d, h] = size(part.id);
    const color = D.colors[part.color] || '#9A9DA8';
    const z0 = part.z * LEVEL;
    const out = [];
    const L = (u, v, z) => { const [a, b] = turn(u, v, w, d, part.r); return [part.x + a, part.y + b, z0 + z]; };
    const N = n => { const [a, b] = turnVec(n[0], n[1], part.r); return [a, b, n[2]]; };
    const bounds = (u0, v0, z0_, u1, v1, z1_) => {
      const a = L(u0, v0, z0_), b = L(u1, v1, z1_);
      return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), a[2], Math.max(a[0], b[0]), Math.max(a[1], b[1]), b[2]];
    };
    const k = {
      part, color, L, N,
      facing: n => dot(N(n), VIEW) > 1e-4,
      depth: points => points.reduce((sum, p) => sum + dot(L(...p), VIEW), 0) / points.length,
      Pdir: n => { const v = N(n); return [(v[0] - v[1]) * HX, (v[0] + v[1]) * HY - v[2] * ZK]; },
      // 一个平面（可以带洞：多个环，奇偶填充）
      flat: (rings, c, b, line) => {
        const fill = tone(c, b);
        const d_ = rings.map(ring => 'M' + ring.map(p => pt(P(...L(...p)))).join('L') + 'Z').join('');
        return `<path d="${d_}" fill="${fill}" fill-rule="evenodd" stroke="${line || fill}" stroke-width="${line ? 0.5 : 0.35}" stroke-linejoin="round"/>`;
      },
      line: (points, stroke) => `<path d="M${points.map(p => pt(P(...L(...p)))).join('L')}" fill="none" stroke="${stroke}" stroke-width=".5" stroke-linecap="round"/>`,
      faces: list =>list.filter(f => k.facing(f.n)).map(f => k.flat(f.points, color, lit(N(f.n)))).join(''),
      box(u0, v0, z0_, u1, v1, z1_) { out.push(boxSolid(...bounds(u0, v0, z0_, u1, v1, z1_), color)); },
      convex(faces) { out.push({b: bounds(0, 0, 0, w, d, h * LEVEL), draw: () => k.faces(faces.map(f => ({points: [f.points], n: f.n})))}); },
      custom(u0, v0, z0_, u1, v1, z1_, draw) { out.push({b: bounds(u0, v0, z0_, u1, v1, z1_), draw}); },
      round(draw) {
        const b = bounds(0, 0, 0, w, d, h * LEVEL);
        out.push({b, draw: () => draw((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, b[2], b[5], color)});
      },
    };
    (SHAPES[part.id.startsWith('medal-') ? 'medal' : part.id] || SHAPES.block)(k);
    return out;
  }

  /* ---------- 前后排序 ---------- */
  // 屏幕上会不会叠在一起：等轴测里一个盒子的轮廓是六边形，沿三个方向比范围就够了
  const span = ([x0, y0, z0, x1, y1, z1]) => [x0 - y1, x1 - y0, y0 - K * z1, y1 - K * z0, x0 - K * z1, x1 - K * z0];
  const meet = (a, b) => a[0] < b[1] - E && b[0] < a[1] - E && a[2] < b[3] - E && b[2] < a[3] - E && a[4] < b[5] - E && b[4] < a[5] - E;
  const behind = (a, b) => a[3] <= b[0] + E || a[4] <= b[1] + E || a[5] <= b[2] + E;
  function order(solids) {
    const n = solids.length, spans = solids.map(s => span(s.b));
    const next = Array.from({length: n}, () => []), waiting = new Array(n).fill(0);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        if (!meet(spans[i], spans[j])) continue;
        if (behind(solids[i].b, solids[j].b)) { next[i].push(j); waiting[j]++; }
        else if (behind(solids[j].b, solids[i].b)) { next[j].push(i); waiting[i]++; }
      }
    }
    const key = i => { const b = solids[i].b; return b[0] + b[1] + b[2] + (b[3] + b[4] + b[5]) * 0.001; };
    const done = new Array(n).fill(false), out = [];
    let ready = solids.map((_, i) => i).filter(i => !waiting[i]);
    while (out.length < n) {
      if (!ready.length) {   // 互相挡住（不该出现）：先画最远的那个
        let far = -1;
        for (let i = 0; i < n; i++) if (!done[i] && (far < 0 || key(i) < key(far))) far = i;
        ready = [far];
      }
      let best = 0;
      for (let i = 1; i < ready.length; i++) if (key(ready[i]) < key(ready[best])) best = i;
      const i = ready.splice(best, 1)[0];
      if (done[i]) continue;
      done[i] = true;
      out.push(solids[i]);
      for (const j of next[i]) if (--waiting[j] === 0 && !done[j]) ready.push(j);
    }
    return out;
  }

  // 画一组零件（世界坐标），返回排好序的 SVG；tag 时每块实体包一层 <g data-i>，编辑器靠它知道点到了哪个零件
  function paint(parts, view, tag = false) {
    const solids = [];
    parts.forEach((part, i) => solidsOf(toView(part, view)).forEach(s => { s.i = i; solids.push(s); }));
    return order(solids).map(s => tag ? `<g data-i="${s.i}">${s.draw()}</g>` : s.draw()).join('');
  }

  // 底板：选的底色做成一块板，上面一格一个小圆点
  const plateColor = bg => bg === 'paper' || !D.colors[bg] ? '#E4E0D5' : D.colors[bg];
  const skyColor = bg => bg === 'paper' || !D.colors[bg] ? '#F7F6F2' : mix(D.colors[bg], '#FFFFFF', 0.86);
  function base(x0, y0, x1, y1, bg, studs = true) {
    const c = plateColor(bg), t = 0.22;
    let out = boxSolid(x0, y0, -t, x1, y1, 0, c).draw();
    if (studs) {
      const fill = tone(c, 0.55);
      for (let x = x0; x < x1; x++) for (let y = y0; y < y1; y++) {
        const [sx, sy] = P(x + 0.5, y + 0.5, 0);
        out += `<ellipse cx="${n2(sx)}" cy="${n2(sy)}" rx="1.6" ry=".8" fill="${fill}"/>`;
      }
    }
    return out;
  }
  // 地上的影子：光从左前方来，影子往后拖，越高拖得越长；只画落在底板上的那些，叠在一起也不会更黑
  function shadows(parts, view, x0 = 0, y0 = 0) {
    let d = '';
    for (const part of parts) {
      if (part[4] !== 0) continue;
      const v = toView(part, view), [fw, fd] = footprint(v.id, v.r), b = size(v.id)[2] * LEVEL * 0.55, a = b * 0.3;
      const corners = [[v.x - a, v.y - b], [v.x + fw - a, v.y - b], [v.x + fw, v.y], [v.x + fw, v.y + fd], [v.x, v.y + fd], [v.x - a, v.y + fd - b]];
      d += 'M' + corners.map(([x, y]) => pt(P(Math.max(x0, x), Math.max(y0, y), 0))).join('L') + 'Z';
    }
    return d ? `<path d="${d}" fill="#1B1D2A" fill-opacity=".1"/>` : '';
  }
  function bboxOf(boxes) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const [a, b, c, d, e, f] of boxes) {
      for (const [x, y, z] of [[a, b, f], [d, b, f], [a, e, f], [d, e, f], [d, e, c], [a, e, c], [d, b, c]]) {
        const [sx, sy] = P(x, y, z);
        x0 = Math.min(x0, sx); x1 = Math.max(x1, sx); y0 = Math.min(y0, sy); y1 = Math.max(y1, sy);
      }
    }
    return [x0, y0, x1, y1];
  }

  // 一整件作品的缩略图：只截有零件的那一块底板，按作品保存时的视角
  function markup(build, {cls = 'build', label = ''} = {}) {
    const view = build.view || 0, parts = build.parts || [];
    const boxes = parts.map(part => { const v = toView(part, view), [fw, fd] = footprint(v.id, v.r); return [v.x, v.y, v.z * LEVEL, v.x + fw, v.y + fd, (v.z + size(v.id)[2]) * LEVEL]; });
    let [x0, y0, x1, y1] = boxes.length ? [Math.min(...boxes.map(b => b[0])), Math.min(...boxes.map(b => b[1])), Math.max(...boxes.map(b => b[3])), Math.max(...boxes.map(b => b[4]))] : [6, 6, 10, 10];
    [x0, y0, x1, y1] = [Math.max(0, x0 - 1), Math.max(0, y0 - 1), Math.min(SIZE, x1 + 1), Math.min(SIZE, y1 + 1)];
    const [bx0, by0, bx1, by1] = bboxOf([[x0, y0, -0.22, x1, y1, 0], ...boxes]);
    const side = Math.max(bx1 - bx0, by1 - by0) * 1.12 + 8;
    const cx = (bx0 + bx1) / 2, cy = (by0 + by1) / 2;
    const box = `${n2(cx - side / 2)} ${n2(cy - side / 2)} ${n2(side)} ${n2(side)}`;
    const a11y = label ? `role="img" aria-label="${label.replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]))}"` : 'aria-hidden="true"';
    return `<svg xmlns="http://www.w3.org/2000/svg" class="${cls}" viewBox="${box}" ${a11y}><rect x="${n2(cx - side / 2)}" y="${n2(cy - side / 2)}" width="${n2(side)}" height="${n2(side)}" fill="${skyColor(build.bg)}"/>` +
      base(x0, y0, x1, y1, build.bg, side < 260) + shadows(parts, view, x0, y0) + paint(parts, view) + '</svg>';
  }
  // 零件小图：一个零件，按默认朝向，略微转过来一点看得出立体
  function icon(id, color) {
    const [w, d, h] = size(id);
    const part = [id, color || 'ink', 0, 0, 0, 0];
    const [x0, y0, x1, y1] = bboxOf([[0, 0, 0, w, d, h * LEVEL]]);
    const side = Math.max(x1 - x0, y1 - y0) + 4;
    return `<svg class="part-icon" viewBox="${n2((x0 + x1) / 2 - side / 2)} ${n2((y0 + y1) / 2 - side / 2)} ${n2(side)} ${n2(side)}" aria-hidden="true">${paint([part], 0)}</svg>`;
  }

  function mount(root = document) {
    root.querySelectorAll('svg[data-build]').forEach(svg => {
      try {
        const build = JSON.parse(svg.dataset.build);
        const fresh = new DOMParser().parseFromString(markup(build, {cls: svg.getAttribute('class') || 'build', label: svg.getAttribute('aria-label') || ''}), 'image/svg+xml').documentElement;
        svg.replaceWith(document.importNode(fresh, true));
      } catch (error) { /* 数据坏了就留着占位的底色 */ }
    });
    root.querySelectorAll('svg[data-part-icon]').forEach(svg => {
      const fresh = new DOMParser().parseFromString(icon(svg.dataset.partIcon, svg.dataset.color).replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" '), 'image/svg+xml').documentElement;
      fresh.setAttribute('class', svg.getAttribute('class') || 'part-icon');
      svg.replaceWith(document.importNode(fresh, true));
    });
  }

  window.yuiBlocks = {D, SIZE, LEVEL, HX, HY, ZK, P, tone, footprint, size, toView, fromView, extent, dropLevel, settle,
    paint, base, shadows, markup, icon, mount, plateColor, skyColor, solidsOf, bboxOf};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => mount());
  else mount();
})();
