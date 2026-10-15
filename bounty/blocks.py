"""积木: a free building board made of the same dots, lines and planes as the medals. Parts and colours open with medals
(see unlocks.py); builds are saved per person, and one can be shown on the nameplate and the team's block wall."""
import json
from .db import connect
from .honors import MEDALS
from .service import InvalidAction, now
from . import unlocks

BOARD = 16          # 16×16 格，每格 10 个单位
MAX_PARTS = 160
MAX_BUILDS = 30
COLORS = {'ink': '#1B1D2A', 'white': '#FFFFFF', 'green': '#00A27A', 'cyan': '#00AEE0', 'blue': '#2866B1',
          'yellow': '#F2B700', 'orange': '#F39800', 'red': '#E54465', 'gold': '#C99A06'}
BACKGROUNDS = {'paper': '#F7F6F2', **COLORS}
# 零件：(宽, 高) 以格计；形状画在以中心为原点的坐标里，颜色用 currentColor，旋转时绕中心转
PARTS = {
    'dot-s': (1, 1, '<circle r="3.4"/>'),
    'dot-m': (2, 2, '<circle r="10"/>'),
    'dot-l': (4, 4, '<circle r="20"/>'),
    'ring': (4, 4, '<circle r="16.5" fill="none" stroke="currentColor" stroke-width="7"/>'),
    'knot': (4, 2, '<circle cx="-6.5" r="7.2" fill="none" stroke="currentColor" stroke-width="3.6"/>'
                   '<circle cx="6.5" r="7.2" fill="none" stroke="currentColor" stroke-width="3.6"/>'),
    'bar-3': (3, 1, '<rect x="-15" y="-3.5" width="30" height="7" rx="3.5"/>'),
    'bar-6': (6, 1, '<rect x="-30" y="-3.5" width="60" height="7" rx="3.5"/>'),
    'dotline': (5, 1, '<circle cx="-21" r="3"/><circle cx="-13" r="3"/><circle cx="-5" r="3"/><rect x="1" y="-3" width="23" height="6" rx="3"/>'),
    'diag': (4, 4, '<path d="M-16 16 16 -16" fill="none" stroke="currentColor" stroke-width="7" stroke-linecap="round"/>'),
    'sq-2': (2, 2, '<rect x="-10" y="-10" width="20" height="20"/>'),
    'quarter': (4, 4, '<path d="M-20 20V-20A40 40 0 0 1 20 20Z"/>'),
    'half': (4, 2, '<path d="M-20 10A20 20 0 0 1 20 10Z"/>'),
    'tri': (4, 4, '<path d="M-20 20V-20L20 20Z"/>'),
    'sq-4': (4, 4, '<rect x="-20" y="-20" width="40" height="40"/>'),
    **{f'medal-{key}': (3, 3, None) for key in MEDALS},   # 勋章零件用页面上的勋章图形
}
FAMILY = {'点': ('dot-s', 'dot-m', 'dot-l', 'ring', 'knot'), '线': ('bar-3', 'bar-6', 'dotline', 'diag'),
          '面': ('sq-2', 'quarter', 'half', 'tri', 'sq-4'), '勋章': tuple(f'medal-{key}' for key in MEDALS)}


def footprint(part, r):
    w, h, _ = PARTS[part]
    return (h, w) if r % 2 else (w, h)


def palette(db, user_id):
    """Parts and colours for the editor: everything, with what is open and what would open the rest."""
    items = {item['id']: item for item in unlocks.board(db, user_id)}
    parts = [dict(family=family, id=part, name=items[f'part:{part}']['name'], open=items[f'part:{part}']['open'],
                  need=items[f'part:{part}']['need'], short=items[f'part:{part}']['short'],
                  w=PARTS[part][0], h=PARTS[part][1], shape=PARTS[part][2])
             for family, members in FAMILY.items() for part in members]
    colors = [dict(id=name, hex=hex_, name=items[f'color:{name}']['name'], open=items[f'color:{name}']['open'],
                   need=items[f'color:{name}']['need']) for name, hex_ in COLORS.items()]
    return parts, colors


def clean(db, user_id, name, bg, parts):
    """Check a build before saving: only open parts and colours, every part inside the board."""
    have = unlocks.unlocked(db, user_id)
    name = (name or '').strip()[:20] or '我的作品'
    if bg not in BACKGROUNDS or (bg != 'paper' and f'color:{bg}' not in have):
        raise InvalidAction('这个底色还没解锁。')
    if not isinstance(parts, list) or len(parts) > MAX_PARTS:
        raise InvalidAction(f'一件作品最多 {MAX_PARTS} 个零件。')
    kept = []
    for item in parts:
        if not (isinstance(item, list) and len(item) == 5):
            raise InvalidAction('零件数据不对。')
        part, color, x, y, r = item
        if part not in PARTS or color not in COLORS or not all(isinstance(v, int) for v in (x, y, r)) or r not in range(4):
            raise InvalidAction('零件数据不对。')
        if f'part:{part}' not in have or f'color:{color}' not in have:
            raise InvalidAction('用到了还没解锁的零件或颜色。')
        w, h = footprint(part, r)
        if not (0 <= x <= BOARD - w and 0 <= y <= BOARD - h):
            raise InvalidAction('有零件放到板子外面了。')
        kept.append([part, color, x, y, r])
    return name, bg, kept


def save(path, user_id, build_id, name, bg, parts):
    with connect(path, write=True) as db:
        name, bg, parts = clean(db, user_id, name, bg, parts)
        data = json.dumps(parts, separators=(',', ':'))
        if build_id:
            if not db.execute('SELECT 1 FROM builds WHERE id=? AND user_id=?', (build_id, user_id)).fetchone():
                raise InvalidAction('这件作品不存在。')
            db.execute('UPDATE builds SET name=?,bg=?,parts=?,updated_at=? WHERE id=?', (name, bg, data, now(), build_id))
            return build_id
        if db.execute('SELECT COUNT(*) FROM builds WHERE user_id=?', (user_id,)).fetchone()[0] >= MAX_BUILDS:
            raise InvalidAction(f'最多存 {MAX_BUILDS} 件作品，先删掉一件旧的。')
        return db.execute('INSERT INTO builds (user_id,name,bg,parts,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                          (user_id, name, bg, data, now(), now())).lastrowid


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
    return dict(id=row['id'], name=row['name'], bg=row['bg'], parts=json.loads(row['parts']), shown=bool(row['shown']),
                updated_at=row['updated_at'])


def mine(db, user_id):
    return [load(row) for row in db.execute('SELECT * FROM builds WHERE user_id=? ORDER BY updated_at DESC,id DESC', (user_id,))]


def shown_by_user(db):
    """Each person's nameplate build, for nameplates and the team's block wall."""
    return {row['user_id']: dict(load(row), owner=row['owner']) for row in db.execute(
        'SELECT b.*,u.name owner FROM builds b JOIN users u ON u.id=b.user_id WHERE b.shown=1 ORDER BY b.updated_at DESC')}
