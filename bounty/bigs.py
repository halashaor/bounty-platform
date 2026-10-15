"""大任务：要好几个人一起才能做完的事，由几份「分工」组成。每份分工就是一个普通的小任务（tasks.big_id 指向大任务），
一个人认领、提交、验收、拿勋章，和别的小任务一样；牵头人也能验收分工。

分工都做完后由牵头人收尾：做完过分工的每个人和牵头人各记一笔（big_credits），多得 BONUS 经验，进信箱等着拆；
还没人接的分工离开大任务，变回普通小任务留在「发现」里。"""
from math import ceil, sqrt
from .db import connect
from .honors import MEDALS, medal_key
from .service import InvalidAction, insert_task, now, parse_deadline, required

BONUS = 30
MIN_PIECES = 2
MAX_PIECES = 30
NOTE_LIMIT = 200
CLOSING = ('大家辛苦了', '没有你们做不成', '下次还一起')
DEFAULT_CLOSING = '大家辛苦了。'
EVENTS = {'start': '发起', 'join': '加入', 'piece': '加了分工', 'comment': '讨论', 'close': '收尾',
          'claim': '接下分工', 'submit': '提交分工', 'accept': '分工完成'}


def _piece(db, row):
    """One share from a form row: a title, one tag from the team list, which medal it gives, an optional note."""
    title = (row.get('title') or '').strip()
    note = (row.get('note') or '').strip()
    if not title or len(title) > 120:
        raise InvalidAction('每份分工都要有标题，且不超过 120 字。')
    if len(note) > NOTE_LIMIT:
        raise InvalidAction(f'分工的说明不能超过 {NOTE_LIMIT} 字。')
    tag = (row.get('tag') or '').strip()
    if not db.execute('SELECT 1 FROM org_tags WHERE name=?', (tag,)).fetchone():
        raise InvalidAction(f'给「{title}」选一个团队标签。')
    if row.get('kind') not in MEDALS:
        raise InvalidAction(f'给「{title}」选一个分量。')
    importance, urgency = row['kind'].split('-')
    return dict(title=title, note=note, tag=tag, importance=importance, urgency=urgency)


def _add(db, big, user_id, piece, deadline):
    return insert_task(db, user_id, piece['title'], piece['note'], '', [piece['tag']], big['project'],
                       piece['importance'], piece['urgency'], deadline, big['id'])


def _event(db, big_id, user_id, kind, body=''):
    db.execute('INSERT INTO big_events (big_id,user_id,kind,body,created_at) VALUES (?,?,?,?,?)',
               (big_id, user_id, kind, body, now()))


def _big(db, big_id):
    big = db.execute('SELECT * FROM big_tasks WHERE id=?', (big_id,)).fetchone()
    if not big:
        raise InvalidAction('大任务不存在。')
    return big


def _active(db, big_id):
    big = _big(db, big_id)
    if big['status'] != 'active':
        raise InvalidAction('这个大任务已经收尾了。')
    return big


def is_member(db, big_id, user_id):
    return bool(db.execute('SELECT 1 FROM big_members WHERE big_id=? AND user_id=?', (big_id, user_id)).fetchone())


def create(path, user_id, data, rows, tz=None):
    """rows: the shares typed on the form; completely blank rows are skipped."""
    title = required(data, 'title', '标题', 120)
    goal = required(data, 'goal', '目标', 2000)
    project = (data.get('project') or '').strip()
    if len(project) > 30:
        raise InvalidAction('项目名不能超过 30 个字。')
    deadline = parse_deadline(data.get('deadline'), tz)
    rows = [row for row in rows if (row.get('title') or '').strip() or (row.get('note') or '').strip()]
    if len(rows) < MIN_PIECES:
        raise InvalidAction('大任务至少分成两份分工；一个人就能做完的，发小任务就好。')
    if len(rows) > MAX_PIECES:
        raise InvalidAction(f'一个大任务最多 {MAX_PIECES} 份分工。')
    with connect(path, write=True) as db:
        pieces = [_piece(db, row) for row in rows]
        big_id = db.execute('''INSERT INTO big_tasks (title,goal,project,owner_id,deadline,created_at)
            VALUES (?,?,?,?,?,?)''', (title, goal, project or None, user_id, deadline, now())).lastrowid
        db.execute('INSERT INTO big_members (big_id,user_id,joined_at) VALUES (?,?,?)', (big_id, user_id, now()))
        _event(db, big_id, user_id, 'start', f'分成 {len(pieces)} 份分工')
        big = _big(db, big_id)
        for piece in pieces:
            _add(db, big, user_id, piece, deadline)
        return big_id


def add_piece(path, big_id, user_id, row, tz=None):
    """Anyone in the crew can add a share; they publish it, so they (or the lead) accept it."""
    with connect(path, write=True) as db:
        big = _active(db, big_id)
        if not is_member(db, big_id, user_id):
            raise InvalidAction('先加入这个大任务，才能加分工。')
        if db.execute('SELECT COUNT(*) FROM tasks WHERE big_id=?', (big_id,)).fetchone()[0] >= MAX_PIECES:
            raise InvalidAction(f'一个大任务最多 {MAX_PIECES} 份分工。')
        piece = _piece(db, row)
        if row.get('deadline'):
            deadline = parse_deadline(row['deadline'], tz)
        elif big['deadline'] > now():
            deadline = big['deadline']
        else:
            raise InvalidAction('大任务的目标日期已经过了，给这份分工定一个新的截止时间。')
        task_id = _add(db, big, user_id, piece, deadline)
        _event(db, big_id, user_id, 'piece', piece['title'])
        return task_id


def join(path, big_id, user_id):
    with connect(path, write=True) as db:
        _active(db, big_id)
        if db.execute('INSERT OR IGNORE INTO big_members (big_id,user_id,joined_at) VALUES (?,?,?)',
                      (big_id, user_id, now())).rowcount:
            _event(db, big_id, user_id, 'join')


def leave(path, big_id, user_id):
    with connect(path, write=True) as db:
        big = _active(db, big_id)
        if big['owner_id'] == user_id:
            raise InvalidAction('牵头人不能退出自己发起的大任务。')
        if db.execute("SELECT 1 FROM tasks WHERE big_id=? AND assignee_id=? AND status IN ('active','review')",
                      (big_id, user_id)).fetchone():
            raise InvalidAction('手上还有这里的分工，做完再退出吧。')
        db.execute('DELETE FROM big_members WHERE big_id=? AND user_id=?', (big_id, user_id))


def comment(path, big_id, user_id, body):
    body = (body or '').strip()
    if not body or len(body) > 10000:
        raise InvalidAction('讨论内容不能为空，且不能超过 10000 字。')
    with connect(path, write=True) as db:
        _big(db, big_id)
        _event(db, big_id, user_id, 'comment', body)


def close(path, big_id, user_id, body=''):
    """The lead wraps up: every finished share counts, unclaimed ones go back to being ordinary tasks."""
    body = (body or '').strip()
    if len(body) > 500:
        raise InvalidAction('收尾的话不能超过 500 字。')
    with connect(path, write=True) as db:
        big = _active(db, big_id)
        if big['owner_id'] != user_id:
            raise InvalidAction('只有牵头人能收尾。')
        state = counts(db, big_id)
        if state['busy']:
            raise InvalidAction('还有分工在做或等验收，等它们完成再收尾。')
        if not state['done']:
            raise InvalidAction('还没有完成的分工，现在不能收尾。')
        db.execute("UPDATE tasks SET big_id=NULL WHERE big_id=? AND status='open'", (big_id,))
        doers = {row['assignee_id']: row['n'] for row in db.execute(
            "SELECT assignee_id,COUNT(*) n FROM tasks WHERE big_id=? AND status='done' GROUP BY assignee_id", (big_id,))}
        people = {**{uid: (0, n) for uid, n in doers.items()}, user_id: (1, doers.get(user_id, 0))}
        stamp = now()
        db.executemany('INSERT INTO big_credits (big_id,user_id,lead,pieces,bonus,awarded_at) VALUES (?,?,?,?,?,?)',
                       [(big_id, uid, lead, n, BONUS, stamp) for uid, (lead, n) in people.items()])
        db.execute("UPDATE big_tasks SET status='done',closing=?,done_at=? WHERE id=?",
                   (body or DEFAULT_CLOSING, stamp, big_id))
        _event(db, big_id, user_id, 'close', body or DEFAULT_CLOSING)
        return sorted(people)


# ---------------- 读 ----------------
def counts(db, big_id):
    row = db.execute('''SELECT COUNT(*) total, COALESCE(SUM(status='done'),0) done, COALESCE(SUM(status='open'),0) open,
        COALESCE(SUM(status IN ('active','review')),0) busy FROM tasks WHERE big_id=?''', (big_id,)).fetchone()
    return dict(row)


def tiles_by_big(db, big_ids, viewer_id=0):
    """One tile per share for the mosaic, in the order the shares were added."""
    tiles = {big_id: [] for big_id in big_ids}
    if not big_ids:
        return tiles
    marks = ','.join('?' * len(big_ids))
    for row in db.execute(f'''SELECT t.big_id,t.id,t.title,t.importance,t.urgency,t.status,t.assignee_id,a.name who
            FROM tasks t LEFT JOIN users a ON a.id=t.assignee_id WHERE t.big_id IN ({marks}) ORDER BY t.id''', list(big_ids)):
        tiles[row['big_id']].append(dict(id=row['id'], title=row['title'], key=medal_key(row), importance=row['importance'],
                                         state='done' if row['status'] == 'done' else 'busy' if row['status'] != 'open' else 'open',
                                         who=row['who'], mine=bool(viewer_id) and row['assignee_id'] == viewer_id))
    return tiles


def grid(count):
    """Columns and rows for a mosaic of `count` tiles, kept around 3:2 so it sits well in a card."""
    count = max(count, 1)
    cols = min(count, ceil(sqrt(count * 1.6)))
    return cols, ceil(count / cols)


def crew_by_big(db, big_ids):
    crew = {big_id: [] for big_id in big_ids}
    if not big_ids:
        return crew
    marks = ','.join('?' * len(big_ids))
    for row in db.execute(f'''SELECT m.big_id,u.id,u.name,b.owner_id=u.id lead,
            (SELECT COUNT(*) FROM tasks t WHERE t.big_id=m.big_id AND t.assignee_id=u.id AND t.status='done') done,
            (SELECT COUNT(*) FROM tasks t WHERE t.big_id=m.big_id AND t.assignee_id=u.id AND t.status IN ('active','review')) doing
        FROM big_members m JOIN users u ON u.id=m.user_id JOIN big_tasks b ON b.id=m.big_id
        WHERE m.big_id IN ({marks}) ORDER BY lead DESC,m.joined_at,u.id''', list(big_ids)):
        crew[row['big_id']].append(dict(row))
    return crew


def listing(db, viewer_id, status='active', limit=None):
    """Big tasks with their progress, mosaic and crew. Active ones you joined come first, then by target date;
    finished ones newest first."""
    order = ('joined DESC, b.deadline, b.id' if status == 'active' else 'b.done_at DESC, b.id DESC')
    rows = db.execute(f'''SELECT b.*,u.name owner_name,
            EXISTS(SELECT 1 FROM big_members m WHERE m.big_id=b.id AND m.user_id=?) joined,
            (SELECT COUNT(*) FROM big_members m WHERE m.big_id=b.id) people
        FROM big_tasks b JOIN users u ON u.id=b.owner_id WHERE b.status=? ORDER BY {order}''' +
                      (' LIMIT ?' if limit else ''), (viewer_id, status, *((limit,) if limit else ()))).fetchall()
    ids = [row['id'] for row in rows]
    tiles, crew = tiles_by_big(db, ids, viewer_id), crew_by_big(db, ids)
    items = []
    for row in rows:
        mine = tiles[row['id']]
        items.append(dict(row, tiles=mine, crew=crew[row['id']], total=len(mine),
                          done=sum(t['state'] == 'done' for t in mine), open=sum(t['state'] == 'open' for t in mine),
                          busy=sum(t['state'] == 'busy' for t in mine), lead=row['owner_id'] == viewer_id))
    return items


def ready(item):
    """Every share is finished: the lead can wrap up without leaving anything behind."""
    return item['status'] == 'active' and item['total'] and item['done'] == item['total']


def mine(db, user_id):
    """Active big tasks this person leads or joined."""
    return [item for item in listing(db, user_id) if item['joined']]


def ready_count(db, user_id):
    return sum(1 for item in listing(db, user_id) if item['lead'] and ready(item))


def timeline(db, big_id):
    """Talk on the big task itself, plus the moments shares were taken, handed in and finished."""
    own = db.execute('''SELECT e.kind,e.body,e.created_at,e.user_id,u.name,NULL task_id,NULL task_title
        FROM big_events e JOIN users u ON u.id=e.user_id WHERE e.big_id=?''', (big_id,)).fetchall()
    shares = db.execute('''SELECT e.kind,e.body,e.created_at,e.user_id,u.name,t.id task_id,t.title task_title
        FROM events e JOIN tasks t ON t.id=e.task_id JOIN users u ON u.id=e.user_id
        WHERE t.big_id=? AND e.kind IN ('claim','submit','accept')''', (big_id,)).fetchall()
    return sorted([dict(row) for row in (*own, *shares)], key=lambda row: row['created_at'])


def credits(db, user_id):
    """Finished big tasks this person has a credit in, newest first, each with its mosaic."""
    rows = db.execute('''SELECT c.*,b.title,b.goal,b.closing,b.project,b.done_at,u.name owner_name,
            (SELECT COUNT(*) FROM big_credits x WHERE x.big_id=c.big_id) people
        FROM big_credits c JOIN big_tasks b ON b.id=c.big_id JOIN users u ON u.id=b.owner_id
        WHERE c.user_id=? ORDER BY c.awarded_at DESC,c.big_id DESC''', (user_id,)).fetchall()
    tiles = tiles_by_big(db, [row['big_id'] for row in rows], user_id)
    names = {}
    for row in db.execute(f'''SELECT x.big_id,u.name FROM big_credits x JOIN users u ON u.id=x.user_id
            WHERE x.big_id IN ({','.join('?' * len(rows))}) ORDER BY x.lead DESC,x.pieces DESC,u.id''',
                          [row['big_id'] for row in rows]) if rows else ():
        names.setdefault(row['big_id'], []).append(row['name'])
    return [dict(row, tiles=tiles[row['big_id']], names=names.get(row['big_id'], [])) for row in rows]


def unseen_count(db, user_id):
    return db.execute('SELECT COUNT(*) FROM big_credits WHERE user_id=? AND seen_at IS NULL', (user_id,)).fetchone()[0]


def take_unseen(db, user_id):
    """Credits not opened yet, marked as opened (call inside a write transaction)."""
    fresh = [item for item in credits(db, user_id) if item['seen_at'] is None][::-1]
    db.executemany('UPDATE big_credits SET seen_at=? WHERE big_id=? AND user_id=?',
                   [(now(), item['big_id'], user_id) for item in fresh])
    return fresh

