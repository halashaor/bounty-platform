"""积木: stack parts on a 16×16 board and look at them from an isometric angle that turns four ways. Parts and colours
open with medals (see unlocks.py); builds are saved per person, and one can be shown on the nameplate and the team's
block wall. Drawing happens in the browser (static/iso.js); the server checks a build and lets every part settle."""
import json
from .db import connect
from .honors import MEDALS
from .service import InvalidAction, now
from . import unlocks

BOARD = 16          # 16×16 格
LEVELS = 24         # 最高 24 层，一层半格高
MAX_PARTS = 300
MAX_BUILDS = 30
COLORS = {'ink': '#1B1D2A', 'white': '#FFFFFF', 'sand': '#E6D5B0', 'green': '#00A27A', 'cyan': '#00AEE0',
          'blue': '#2866B1', 'yellow': '#F2B700', 'orange': '#F39800', 'red': '#E54465', 'wood': '#A8764A', 'gold': '#C99A06'}
BACKGROUNDS = {'paper': '#F7F6F2', **COLORS}
# 零件：(宽, 深, 层数)，宽深以格计。摆放时 r 是水平转了几个 90°，转奇数次宽深互换。样子在 static/iso.js 里画
PARTS = {
    'stud': (1, 1, 1), 'ball': (1, 1, 2), 'dome': (2, 2, 2), 'ball-l': (2, 2, 4), 'cylinder': (2, 2, 4), 'cone': (2, 2, 4),
    'knot': (3, 1, 4),
    'beam-3': (3, 1, 1), 'beam-6': (6, 1, 1), 'pillar': (1, 1, 6), 'stairs': (1, 3, 3), 'fence': (4, 1, 2), 'arch': (4, 1, 4),
    'block': (1, 1, 2), 'plate': (4, 4, 1), 'slope': (2, 2, 2), 'roof': (4, 4, 4), 'quarter': (2, 2, 2), 'block-l': (2, 2, 4),
    **{f'medal-{key}': (2, 1, 4) for key in MEDALS},
}
FAMILY = {'点': ('stud', 'ball', 'dome', 'ball-l', 'cylinder', 'cone', 'knot'),
          '线': ('beam-3', 'beam-6', 'pillar', 'stairs', 'fence', 'arch'),
          '面': ('block', 'plate', 'slope', 'roof', 'quarter', 'block-l'),
          '勋章': tuple(f'medal-{key}' for key in MEDALS)}
# 还没有作品时游戏角上摆的样子：只用一开始就有的零件和颜色
SAMPLE = [['block', 'white', 6, 7, 0, 0], ['block', 'white', 6, 7, 0, 0], ['block', 'white', 8, 7, 0, 0], ['block', 'white', 8, 7, 0, 0],
          ['beam-3', 'ink', 6, 7, 0, 0], ['block', 'sand', 7, 9, 0, 0], ['stud', 'ink', 5, 9, 0, 0], ['stud', 'ink', 10, 6, 0, 0],
          ['stud', 'sand', 7, 7, 0, 0]]
# 平面积木时代的零件：(宽, 高) 和变成的立体零件。升级时旧作品按原来的位置摆上板子，后放的叠在先放的上面
FLAT = {'dot-s': (1, 1, 'stud'), 'dot-m': (2, 2, 'ball'), 'dot-l': (4, 4, 'ball-l'), 'ring': (4, 4, 'cylinder'),
        'knot': (4, 2, 'knot'), 'bar-3': (3, 1, 'beam-3'), 'bar-6': (6, 1, 'beam-6'), 'dotline': (5, 1, 'fence'),
        'diag': (4, 4, 'stairs'), 'sq-2': (2, 2, 'block'), 'quarter': (4, 4, 'quarter'), 'half': (4, 2, 'dome'),
        'tri': (4, 4, 'slope'), 'sq-4': (4, 4, 'plate'), **{f'medal-{key}': (3, 3, f'medal-{key}') for key in MEDALS}}


def footprint(part, r):
    w, d, _ = PARTS[part]
    return (d, w) if r % 2 else (w, d)


def extent(item):
    """(x0, y0, z0, x1, y1, z1) of a placed part; z counts levels."""
    part, _, x, y, z, r = item
    w, d = footprint(part, r)
    return x, y, z, x + w, y + d, z + PARTS[part][2]


def landing(parts, item):
    """The level a part comes to rest on: the highest top among the parts beneath its footprint."""
    x0, y0, _, x1, y1, _ = extent(item)
    return max((top for a, b, _, c, d, top in map(extent, parts) if a < x1 and x0 < c and b < y1 and y0 < d), default=0)


def settle(parts):
    """Gravity, the same rule the editor uses: from the lowest up, each part rests on the highest top beneath it."""
    placed = []
    for i in sorted(range(len(parts)), key=lambda i: (parts[i][4], i)):
        parts[i][4] = landing(placed, parts[i])
        placed.append(parts[i])
    return parts


def palette(db, user_id):
    """Parts and colours for the editor: everything, with what is open and what would open the rest."""
    items = {item['id']: item for item in unlocks.board(db, user_id)}
    parts = [dict(family=family, id=part, name=items[f'part:{part}']['name'], open=items[f'part:{part}']['open'],
                  need=items[f'part:{part}']['need'], short=items[f'part:{part}']['short'], size=PARTS[part])
             for family, members in FAMILY.items() for part in members]
    colors = [dict(id=name, hex=hex_, name=items[f'color:{name}']['name'], open=items[f'color:{name}']['open'],
                   need=items[f'color:{name}']['need']) for name, hex_ in COLORS.items()]
    return parts, colors


def page_data():
    """What static/iso.js needs to draw builds on any page."""
    return dict(size=BOARD, levels=LEVELS, parts=PARTS, colors=COLORS, medals={key: info['hue'] for key, info in MEDALS.items()})


def clean(db, user_id, name, bg, parts, view, kept=()):
    """Check a build before saving: only open parts and colours (or ones already in this build), all on the board,
    nothing stacked past the top. Parts settle the same way they do in the editor."""
    have = unlocks.unlocked(db, user_id) | {f'part:{item[0]}' for item in kept} | {f'color:{item[1]}' for item in kept}
    name = (name or '').strip()[:20] or '我的作品'
    if bg not in BACKGROUNDS or (bg != 'paper' and f'color:{bg}' not in have):
        raise InvalidAction('这个底色还没解锁。')
    if view not in range(4):
        raise InvalidAction('视角不对。')
    if not isinstance(parts, list) or len(parts) > MAX_PARTS:
        raise InvalidAction(f'一件作品最多 {MAX_PARTS} 个零件。')
    tidy = []
    for item in parts:
        if not (isinstance(item, list) and len(item) == 6):
            raise InvalidAction('零件数据不对。')
        part, color, x, y, z, r = item
        if part not in PARTS or color not in COLORS or not all(type(v) is int for v in (x, y, z, r)) or r not in range(4) or z < 0:
            raise InvalidAction('零件数据不对。')
        if f'part:{part}' not in have or f'color:{color}' not in have:
            raise InvalidAction('用到了还没解锁的零件或颜色。')
        w, d = footprint(part, r)
        if not (0 <= x <= BOARD - w and 0 <= y <= BOARD - d):
            raise InvalidAction('有零件放到板子外面了。')
        tidy.append([part, color, x, y, min(z, LEVELS), r])
    settle(tidy)
    if any(extent(item)[5] > LEVELS for item in tidy):
        raise InvalidAction(f'堆得太高了，最高 {LEVELS} 层。')
    return name, bg, tidy


def save(path, user_id, build_id, name, bg, parts, view=0):
    with connect(path, write=True) as db:
        kept = ()
        if build_id:
            row = db.execute('SELECT parts FROM builds WHERE id=? AND user_id=?', (build_id, user_id)).fetchone()
            if not row:
                raise InvalidAction('这件作品不存在。')
            kept = json.loads(row['parts'])
        name, bg, parts = clean(db, user_id, name, bg, parts, view, kept)
        data = json.dumps(parts, separators=(',', ':'))
        if build_id:
            db.execute('UPDATE builds SET name=?,bg=?,parts=?,view=?,updated_at=? WHERE id=?', (name, bg, data, view, now(), build_id))
            return build_id
        if db.execute('SELECT COUNT(*) FROM builds WHERE user_id=?', (user_id,)).fetchone()[0] >= MAX_BUILDS:
            raise InvalidAction(f'最多存 {MAX_BUILDS} 件作品，先删掉一件旧的。')
        return db.execute('INSERT INTO builds (user_id,name,bg,parts,view,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                          (user_id, name, bg, data, view, now(), now())).lastrowid


def show(path, user_id, build_id):
    """Put one build on the nameplate (or take it down when it is already there)."""
    with connect(path, write=True) as db:
        row = db.execute('SELECT shown FROM builds WHERE id=? AND user_id=?', (build_id, user_id)).fetchone()
        if not row:
            raise InvalidAction('这件作品不存在。')
        db.execute('UPDATE builds SET shown=0 WHERE user_id=?', (user_id,))
        if not row['shown']:
            db.execute('UPDATE builds SET shown=1 WHERE id=?', (build_id,))
        return not row['shown']


def delete(path, user_id, build_id):
    with connect(path, write=True) as db:
        if not db.execute('DELETE FROM builds WHERE id=? AND user_id=?', (build_id, user_id)).rowcount:
            raise InvalidAction('这件作品不存在。')


def load(row):
    return dict(id=row['id'], name=row['name'], bg=row['bg'], parts=json.loads(row['parts']), view=row['view'],
                shown=bool(row['shown']), updated_at=row['updated_at'])


def mine(db, user_id):
    return [load(row) for row in db.execute('SELECT * FROM builds WHERE user_id=? ORDER BY updated_at DESC,id DESC', (user_id,))]


def shown_by_user(db):
    """Each person's nameplate build, for nameplates and the team's block wall."""
    return {row['user_id']: dict(load(row), owner=row['owner']) for row in db.execute(
        'SELECT b.*,u.name owner FROM builds b JOIN users u ON u.id=b.user_id WHERE b.shown=1 ORDER BY b.updated_at DESC')}


def from_flat(parts):
    """A build from the flat board: each old part becomes its solid counterpart around the same spot, in the old
    back-to-front order, so overlapping pieces end up stacked. Whatever would rise past the top is left out."""
    solid = []
    for part, color, x, y, r in parts:
        if part not in FLAT or color not in COLORS:
            continue
        w, h, new = FLAT[part]
        cx, cy = x + (h if r % 2 else w) / 2, y + (w if r % 2 else h) / 2
        fw, fd = footprint(new, r)
        item = [new, color, min(max(round(cx - fw / 2), 0), BOARD - fw), min(max(round(cy - fd / 2), 0), BOARD - fd), 0, r % 4]
        item[4] = landing(solid, item)
        if extent(item)[5] <= LEVELS:
            solid.append(item)
    return solid


def upgrade_flat(db):
    """One-time move from the flat board: convert saved builds, and carry over which parts people have already seen
    so the 「新」 marks only point at parts that are actually new."""
    for row in db.execute('SELECT id,parts FROM builds').fetchall():
        parts = json.loads(row['parts'])
        if parts and len(parts[0]) == 5:
            db.execute('UPDATE builds SET parts=? WHERE id=?', (json.dumps(from_flat(parts), separators=(',', ':')), row['id']))
    renamed = {f'part:{old}': f'part:{new}' for old, (_, _, new) in FLAT.items()}
    for row in db.execute("SELECT id,play_seen FROM users WHERE play_seen<>''").fetchall():
        seen = [renamed.get(item, item) for item in row['play_seen'].split(',')]
        db.execute('UPDATE users SET play_seen=? WHERE id=?', (','.join(sorted(set(seen))), row['id']))
