"""What medals unlock in 縁側 (the game corner). Nothing is ever spent: once a medal is in the case, what it opened stays open.

- Each medal kind's colour becomes a building-block colour (点 green, 线 cyan, 面 blue, the urgent ones yellow / orange / red),
  and the full set adds gold.
- More 点 / 线 / 面 medals (either urgency) open more round / line / plane block parts; your medals themselves become parts.
- The small games open a mode or a stamp style here and there, chosen to match: an urgent medal opens 「加急日」.
- Finishing a big task together opens one more part.
"""
from .honors import MEDALS
from .service import now

ELEMENT = {'light': '点', 'standard': '线', 'major': '面'}

# (id, 分类, 名字, 条件)。条件：('free',) / ('kind', 勋章) / ('element', 点线面, 枚数) / ('total', 枚数)
#                               / ('urgent',) / ('trio',) / ('complete',) / ('title',) / ('big', 个数)
ITEMS = (
    ('color:ink', 'color', '墨色', ('free',)),
    ('color:white', 'color', '白色', ('free',)),
    ('color:green', 'color', '绿色', ('kind', 'light-normal')),
    ('color:cyan', 'color', '青色', ('kind', 'standard-normal')),
    ('color:blue', 'color', '蓝色', ('kind', 'major-normal')),
    ('color:yellow', 'color', '黄色', ('kind', 'light-urgent')),
    ('color:orange', 'color', '橙色', ('kind', 'standard-urgent')),
    ('color:red', 'color', '红色', ('kind', 'major-urgent')),
    ('color:gold', 'color', '金色', ('complete',)),
    ('part:dot-s', 'part', '小点', ('free',)),
    ('part:bar-3', 'part', '短线', ('free',)),
    ('part:sq-2', 'part', '方块', ('free',)),
    ('part:dot-m', 'part', '圆点', ('element', 'light', 1)),
    ('part:bar-6', 'part', '长线', ('element', 'standard', 1)),
    ('part:quarter', 'part', '扇形', ('element', 'major', 1)),
    ('part:dotline', 'part', '点线', ('element', 'standard', 2)),
    ('part:half', 'part', '半圆', ('element', 'major', 2)),
    ('part:dot-l', 'part', '大圆', ('element', 'light', 3)),
    ('part:tri', 'part', '三角', ('element', 'major', 3)),
    ('part:diag', 'part', '斜线', ('element', 'standard', 4)),
    ('part:ring', 'part', '圆环', ('element', 'light', 5)),
    ('part:sq-4', 'part', '大方块', ('element', 'major', 5)),
    ('part:knot', 'part', '双环', ('big', 1)),
    *((f'part:medal-{key}', 'part', f'勋章「{info["name"]}」', ('kind', key)) for key, info in MEDALS.items()),
    ('mode:rush', 'mode', '盖章挑战「加急日」', ('urgent',)),
    ('mode:finals', 'mode', '盖章挑战「期末周」', ('element', 'major', 1)),
    ('style:good', 'style', '印章「好」', ('total', 3)),
    ('style:great', 'style', '印章「赞」', ('total', 8)),
    ('style:dlm', 'style', '印章「点线面」', ('trio',)),
    ('style:title', 'style', '用称号当印章', ('title',)),
    ('random', 'random', '随机一笔（无限出题）', ('total', 3)),
)
BY_ID = {item[0]: item for item in ITEMS}


def need_text(req):
    kind = req[0]
    if kind == 'free':
        return '一开始就有'
    if kind == 'kind':
        return f'拿到「{MEDALS[req[1]]["name"]}」勋章'
    if kind == 'element':
        return f'拿到{"" if req[2] == 1 else f" {req[2]} 枚"}「{ELEMENT[req[1]]}」勋章（急不急都算）'
    if kind == 'total':
        return f'一共拿到 {req[1]} 枚勋章'
    if kind == 'big':
        return f'一起完成{"一" if req[1] == 1 else f" {req[1]} "}个大任务'
    return {'urgent': '拿到任意一枚「急」勋章', 'trio': '点、线、面各拿到一枚',
            'complete': '集齐六种勋章', 'title': '解锁任意一个称号'}[kind]


def need_short(req):
    """A few characters for tight spots such as the parts box."""
    kind = req[0]
    if kind == 'kind':
        return f'「{MEDALS[req[1]]["name"]}」'
    if kind == 'element':
        return f'「{ELEMENT[req[1]]}」×{req[2]}'
    if kind == 'total':
        return f'勋章×{req[1]}'
    if kind == 'big':
        return f'大任务×{req[1]}'
    return {'free': '', 'urgent': '任一「急」', 'trio': '点线面各一', 'complete': '集齐六种', 'title': '任一称号'}[kind]


def met(req, counts, titles=0, bigs=0):
    kind = req[0]
    element = lambda name: counts.get(f'{name}-normal', 0) + counts.get(f'{name}-urgent', 0)
    if kind == 'free':
        return True
    if kind == 'kind':
        return counts.get(req[1], 0) > 0
    if kind == 'element':
        return element(req[1]) >= req[2]
    if kind == 'total':
        return sum(counts.values()) >= req[1]
    if kind == 'urgent':
        return any(counts.get(f'{name}-urgent', 0) for name in ELEMENT)
    if kind == 'trio':
        return all(element(name) for name in ELEMENT)
    if kind == 'complete':
        return all(counts.get(key, 0) for key in MEDALS)
    if kind == 'title':
        return titles > 0
    if kind == 'big':
        return bigs >= req[1]
    return False


def standing(db, user_id):
    counts = {row['medal_key']: row['n'] for row in db.execute(
        'SELECT medal_key,COUNT(*) n FROM honors WHERE user_id=? GROUP BY medal_key', (user_id,))}
    titles = db.execute('SELECT COUNT(*) FROM titles_seen WHERE user_id=?', (user_id,)).fetchone()[0]
    bigs = db.execute('SELECT COUNT(*) FROM big_credits WHERE user_id=?', (user_id,)).fetchone()[0]
    return counts, titles, bigs


def unlocked(db, user_id):
    counts, titles, bigs = standing(db, user_id)
    return {item[0] for item in ITEMS if met(item[3], counts, titles, bigs)}


def board(db, user_id):
    """Every item with whether it is open, what opens it, and whether it is new since the last visit."""
    counts, titles, bigs = standing(db, user_id)
    seen = set(filter(None, db.execute('SELECT play_seen FROM users WHERE id=?', (user_id,)).fetchone()[0].split(',')))
    return [dict(id=id_, kind=kind, name=name, need=need_text(req), short=need_short(req), open=met(req, counts, titles, bigs),
                 new=met(req, counts, titles, bigs) and req[0] != 'free' and id_ not in seen)
            for id_, kind, name, req in ITEMS]


def new_count(db, user_id):
    return sum(1 for item in board(db, user_id) if item['new'])


def mark_seen(db, user_id):
    db.execute('UPDATE users SET play_seen=? WHERE id=?', (','.join(sorted(unlocked(db, user_id))), user_id))


def opened_by(counts_before, counts_after, titles_before=0, titles_after=None, bigs_before=0, bigs_after=None):
    """Names of the things that just opened between two states (for the award ceremony)."""
    titles_after = titles_before if titles_after is None else titles_after
    bigs_after = bigs_before if bigs_after is None else bigs_after
    return [name for _, _, name, req in ITEMS if req[0] != 'free' and met(req, counts_after, titles_after, bigs_after)
            and not met(req, counts_before, titles_before, bigs_before)]
