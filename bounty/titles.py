"""Titles (称号): unlocked by how someone helps, not by how much. Everything is computed from existing records,
so a title can never drift out of sync; only "already celebrated" and "shown on my nameplate" are stored."""
from .honors import MEDALS
from .service import InvalidAction, now

DEFAULT_PRAISE = '成果验收通过。'
# (key, 名字, 怎么解锁, 需要多少, 印章颜色)。名字两到四个字，盖成印章正好。
TITLES = (
    ('firefighter', '救火队员', '完成 3 个加急任务', 3, '#E54465'),
    ('hardcore', '啃硬骨头', '完成 3 个「面」任务', 3, '#2866B1'),
    ('unsung', '无名英雄', '完成 3 个等了好几天没人接的冷门任务', 3, '#9C6B3F'),
    ('crossover', '跨界选手', '在 3 个不同项目里完成过任务', 3, '#00AEE0'),
    ('helper', '有求必应', '帮过 5 个不同的人', 5, '#00A27A'),
    ('praised', '好评如潮', '收到 5 句验收时的夸奖', 5, '#F39800'),
    ('applause', '掌声雷动', '完成的任务一共收到 10 次鼓掌', 10, '#E54465'),
    ('mentor', '领路人', '你发布的任务成了 2 个人的第一枚勋章', 2, '#00A27A'),
    ('setter', '出题人', '你发布的任务有 5 个被完成', 5, '#2866B1'),
    ('together', '并肩作战', '一起完成 2 个大任务（做完过其中的分工）', 2, '#2866B1'),
    ('captain', '挑大梁', '牵头完成一个大任务', 1, '#E54465'),
    ('complete', '点线面', '集齐六种勋章', len(MEDALS), '#F2B700'),
    ('oneline', '一笔成形', '一笔画通关 12 关', 12, '#00AEE0'),
    ('stamper', '稳如老章', '盖章挑战打出 30 连击', 30, '#1B1D2A'),
)
BY_KEY = {key: dict(key=key, name=name, how=how, need=need, color=color) for key, name, how, need, color in TITLES}


def counts(db, user_id):
    """Current progress toward every title for one person."""
    one = lambda sql, *args: db.execute(sql, args).fetchone()[0] or 0
    mine = 'FROM honors h JOIN tasks t ON t.id=h.task_id WHERE h.user_id=?'
    firsts = '''SELECT t.owner_id,h.user_id FROM honors h JOIN tasks t ON t.id=h.task_id
        WHERE NOT EXISTS (SELECT 1 FROM honors e WHERE e.user_id=h.user_id
                          AND (e.awarded_at<h.awarded_at OR (e.awarded_at=h.awarded_at AND e.task_id<h.task_id)))'''
    return {
        'firefighter': one(f"SELECT COUNT(*) {mine} AND t.urgency='urgent'", user_id),
        'hardcore': one(f"SELECT COUNT(*) {mine} AND t.importance='major'", user_id),
        'unsung': one(f'SELECT COUNT(*) {mine} AND t.cold=1', user_id),
        'crossover': one(f'SELECT COUNT(DISTINCT t.project) {mine}', user_id),
        'helper': one(f'SELECT COUNT(DISTINCT t.owner_id) {mine}', user_id),
        'praised': one(f'''SELECT COUNT(*) {mine} AND (SELECT body FROM events e WHERE e.task_id=h.task_id AND e.kind='accept'
                           ORDER BY e.id DESC LIMIT 1) NOT IN ('', ?)''', user_id, DEFAULT_PRAISE),
        'applause': one('''SELECT COUNT(*) FROM claps c JOIN tasks t ON t.id=c.task_id
                           WHERE t.assignee_id=? AND t.status='done' ''', user_id),
        'mentor': one(f'SELECT COUNT(*) FROM ({firsts}) WHERE owner_id=? AND user_id<>?', user_id, user_id),
        'setter': one("SELECT COUNT(*) FROM tasks WHERE owner_id=? AND status='done'", user_id),
        'together': one('SELECT COUNT(*) FROM big_credits WHERE user_id=? AND pieces>0', user_id),
        'captain': one('SELECT COUNT(*) FROM big_credits WHERE user_id=? AND lead=1', user_id),
        'complete': one('SELECT COUNT(DISTINCT medal_key) FROM honors WHERE user_id=?', user_id),
        'oneline': one('SELECT COUNT(*) FROM lines_solved WHERE user_id=?', user_id),
        'stamper': one("SELECT MAX(combo) FROM game_runs WHERE user_id=? AND game='stamp' AND finished_at IS NOT NULL", user_id),
    }


def board(db, user_id):
    """Every title with this person's progress, in a fixed order so the wall does not reshuffle as titles unlock."""
    have = counts(db, user_id)
    seen = {row['key']: row['seen_at'] for row in db.execute('SELECT key,seen_at FROM titles_seen WHERE user_id=?', (user_id,))}
    chosen = db.execute('SELECT title_key FROM users WHERE id=?', (user_id,)).fetchone()[0]
    items = []
    for key, name, how, need, color in TITLES:
        got = min(have[key], need)
        items.append(dict(key=key, name=name, how=how, need=need, color=color, have=got, done=have[key] >= need,
                          seen=key in seen, seen_at=seen.get(key), chosen=key == chosen))
    return items


def unseen(db, user_id):
    """Titles unlocked but not celebrated yet: they arrive in the mailbox like medals."""
    return [item for item in board(db, user_id) if item['done'] and not item['seen']]


def take_unseen(db, user_id):
    """Mark newly unlocked titles as celebrated and return them (call inside a write transaction)."""
    fresh = unseen(db, user_id)
    db.executemany('INSERT OR IGNORE INTO titles_seen (user_id,key,seen_at) VALUES (?,?,?)',
                   [(user_id, item['key'], now()) for item in fresh])
    return fresh


def chosen_title(db, user_id):
    row = db.execute('SELECT title_key FROM users WHERE id=?', (user_id,)).fetchone()
    return BY_KEY.get(row[0]) if row and row[0] else None


def choose(db, user_id, key):
    """Show one unlocked title on the nameplate, or none."""
    if key and not any(item['key'] == key and item['done'] for item in board(db, user_id)):
        raise InvalidAction('这个称号还没解锁。')
    db.execute('UPDATE users SET title_key=? WHERE id=?', (key or None, user_id))
