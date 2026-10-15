"""Two growth lines that rise together: experience/level (by workload) and the medal collection (by kind).

Plus one shared line for the whole team: a weekly bundle filled by anyone's accepted tasks.
"""
from datetime import datetime, timedelta, timezone
from .honors import MEDALS, XP, task_xp  # noqa: F401  (XP 和 task_xp 也从这里给页面用)
from .service import TEAM_TZ

LEVEL_NAMES = ((1, '新来的帮手'), (2, '搭把手'), (4, '靠谱队友'), (6, '主力'), (9, '顶梁柱'), (12, '传说中的帮手'))
ROWS = {'normal': ('冷色一行', ('light-normal', 'standard-normal', 'major-normal')),
        'urgent': ('暖色一行', ('light-urgent', 'standard-urgent', 'major-urgent'))}


def level_floor(level):
    """Total experience needed to reach a level: 0, 50, 150, 300, 500 … (each step 50 more than the last)."""
    return 25 * level * (level - 1)


def level_info(xp):
    level = 1
    while xp >= level_floor(level + 1):
        level += 1
    floor, ceiling = level_floor(level), level_floor(level + 1)
    name = [label for start, label in LEVEL_NAMES if level >= start][-1]
    return dict(xp=xp, level=level, name=name, into=xp - floor, span=ceiling - floor, to_next=ceiling - xp,
                percent=round((xp - floor) * 100 / (ceiling - floor)))


def big_xp(db, user_id):
    """Experience from finished big tasks (the wrap-up bonus), on top of each share's own medal."""
    return db.execute('SELECT COALESCE(SUM(bonus),0) FROM big_credits WHERE user_id=?', (user_id,)).fetchone()[0]


def person_progress(db, user_id):
    rows_ = db.execute('SELECT medal_key,bonus FROM honors WHERE user_id=?', (user_id,)).fetchall()
    keys = [row['medal_key'] for row in rows_]
    counts = {key: keys.count(key) for key in MEDALS}
    rows = {name: all(counts[key] for key in members) for name, (_, members) in ROWS.items()}
    xp = sum(task_xp(row['medal_key']) + row['bonus'] for row in rows_) + big_xp(db, user_id)
    return dict(level_info(xp), counts=counts,
                kinds=sum(1 for n in counts.values() if n), total=len(keys), rows=rows, complete=all(rows.values()))


def everyone_levels(db):
    totals = {}
    for row in db.execute('SELECT user_id,medal_key,bonus FROM honors'):
        totals[row['user_id']] = totals.get(row['user_id'], 0) + task_xp(row['medal_key']) + row['bonus']
    for row in db.execute('SELECT user_id,SUM(bonus) bonus FROM big_credits GROUP BY user_id'):
        totals[row['user_id']] = totals.get(row['user_id'], 0) + row['bonus']
    return {user_id: level_info(xp) for user_id, xp in totals.items()}


# 团队收集包：每周一个，按勋章种类凑，不看项目或标签，所以新接进来的研发任务一样能往里填。
BUNDLES = (
    ('热身包', ('light', 'light', 'standard')),
    ('救火包', ('urgent', 'urgent', 'light')),
    ('攻坚包', ('major', 'standard', 'standard')),
    ('全能包', ('light', 'standard', 'major')),
)
SLOT_LABEL = {'light': '点', 'standard': '线', 'major': '面', 'urgent': '急'}
# 团队每完成一个收集包，首页的几何构图就多拼上一块；拼满后从头再来一轮。
PIECES = 8


def week_start(moment=None):
    """Monday 00:00 on the team clock. The bundle is shared, so everyone must agree on when a week turns over,
    wherever they are; it is returned in UTC because the database compares UTC strings."""
    moment = (moment or datetime.now(timezone.utc)).astimezone(TEAM_TZ)
    day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return (day - timedelta(days=day.weekday())).astimezone(timezone.utc)


def _fill(slots, honors):
    """Greedy: urgent slots take urgent medals first, then the remaining slots match by importance."""
    filled = [None] * len(slots)
    pool = list(honors)
    for index, slot in sorted(enumerate(slots), key=lambda item: item[1] != 'urgent'):
        for honor in pool:
            importance, urgency = honor['medal_key'].split('-')
            if (slot == 'urgent' and urgency == 'urgent') or slot == importance:
                filled[index] = honor
                pool.remove(honor)
                break
    return filled


def bundle_for(db, start):
    name, slots = BUNDLES[start.astimezone(TEAM_TZ).isocalendar()[1] % len(BUNDLES)]
    honors = db.execute('''SELECT h.medal_key,h.awarded_at,u.name who,t.title FROM honors h
        JOIN users u ON u.id=h.user_id JOIN tasks t ON t.id=h.task_id
        WHERE h.awarded_at>=? AND h.awarded_at<? ORDER BY h.awarded_at''',
        (start.isoformat(), (start + timedelta(days=7)).isoformat())).fetchall()
    filled = _fill(slots, honors)
    return dict(name=name, slots=[dict(need=slot, label=SLOT_LABEL[slot], honor=honor) for slot, honor in zip(slots, filled)],
                done=all(filled), count=sum(1 for honor in filled if honor))


def team_bundles(db):
    """This week's bundle, plus how many weekly bundles the team has completed in total (for the assembling picture)."""
    start = week_start()
    first = db.execute('SELECT MIN(awarded_at) FROM honors').fetchone()[0]
    completed = 0
    if first:
        week = week_start(datetime.fromisoformat(first))
        while week < start:
            completed += bundle_for(db, week)['done']
            week += timedelta(days=7)
    current = bundle_for(db, start)
    total = completed + current['done']
    return dict(current=current, completed=total, pieces=total % PIECES if total % PIECES or not total else PIECES,
                rounds=(total - 1) // PIECES if total else 0, piece_count=PIECES)
