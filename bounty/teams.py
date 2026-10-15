"""大任务：好几个人一起做的任务（tasks.kind='team'）。想做的人「加入」，发布者自己也可以加入；一起做的任何一个人都能
提交成果，发布者验收时选这次给谁发勋章（默认一起做的每个人）。

做的过程中随时可以拆出「分工」：分工就是普通小任务（tasks.parent_id 指向大任务），一个人认领、拿自己的勋章；
接下分工也就加入了大任务。分工不用一开始就拆好，想到再拆，不拆也行。"""
from math import ceil, sqrt
from .db import connect
from .honors import MEDALS, medal_key
from .service import InvalidAction, insert_task, now, parse_deadline

MAX_PIECES = 30
NOTE_LIMIT = 200
# 还能接手的任务（表别名 t）：没人做的，或者在做但人还没满的大任务
JOINABLE = '''(t.status='open' OR (t.kind='team' AND t.status='active' AND (t.team_size IS NULL
    OR (SELECT COUNT(*) FROM task_members m WHERE m.task_id=t.id) < t.team_size)))'''


def split(path, task_id, user_id, row, tz=None):
    """Split a share off a team task: anyone in it (or its publisher) can, any time before it is handed in.
    Whoever splits it off publishes it, so they accept it; the team task's publisher can accept it too."""
    title, note = (row.get('title') or '').strip(), (row.get('note') or '').strip()
    if not title or len(title) > 120:
        raise InvalidAction('分工要有标题，且不超过 120 字。')
    if len(note) > NOTE_LIMIT:
        raise InvalidAction(f'分工的说明不能超过 {NOTE_LIMIT} 字。')
    if row.get('kind') not in MEDALS:
        raise InvalidAction('给分工选一个分量。')
    importance, urgency = row['kind'].split('-')
    with connect(path, write=True) as db:
        task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not task or task['kind'] != 'team':
            raise InvalidAction('只有大任务能拆分工。')
        if task['status'] not in ('open', 'active'):
            raise InvalidAction('交上去之后就不能再拆了。')
        if task['owner_id'] != user_id and not db.execute('SELECT 1 FROM task_members WHERE task_id=? AND user_id=?',
                                                           (task_id, user_id)).fetchone():
            raise InvalidAction('先加入这个大任务，才能拆分工。')
        if db.execute('SELECT COUNT(*) FROM tasks WHERE parent_id=?', (task_id,)).fetchone()[0] >= MAX_PIECES:
            raise InvalidAction(f'一个大任务最多拆 {MAX_PIECES} 份分工。')
        tag = (row.get('tag') or '').strip()
        if not db.execute('SELECT 1 FROM org_tags WHERE name=?', (tag,)).fetchone():
            raise InvalidAction('给分工选一个团队标签。')
        if row.get('deadline'):
            deadline = parse_deadline(row['deadline'], tz)
        elif task['deadline'] > now():
            deadline = task['deadline']
        else:
            raise InvalidAction('大任务已经过了截止时间，给这份分工定一个新的截止时间。')
        piece = insert_task(db, user_id, title, note, '', [tag], task['project'], importance, urgency, deadline, parent_id=task_id)
        db.execute('INSERT INTO events (task_id,user_id,kind,body,created_at) VALUES (?,?,?,?,?)',
                   (task_id, user_id, 'split', title, now()))
        return piece


# ---------------- 读 ----------------
def members_by_task(db, task_ids):
    """Who is in each team task, in the order they joined."""
    found = {task_id: [] for task_id in task_ids}
    if task_ids:
        for row in db.execute(f'''SELECT m.task_id,u.id,u.name,m.joined_at FROM task_members m JOIN users u ON u.id=m.user_id
                WHERE m.task_id IN ({','.join('?' * len(task_ids))}) ORDER BY m.joined_at,u.id''', list(task_ids)):
            found[row['task_id']].append(dict(id=row['id'], name=row['name'], joined_at=row['joined_at']))
    return found


def tiles_by_parent(db, task_ids, viewer_id=0):
    """One mosaic tile per share split off each team task, in the order they were split off."""
    tiles = {task_id: [] for task_id in task_ids}
    if task_ids:
        for row in db.execute(f'''SELECT t.parent_id,t.id,t.title,t.importance,t.urgency,t.status,t.assignee_id,a.name who
                FROM tasks t LEFT JOIN users a ON a.id=t.assignee_id WHERE t.parent_id IN ({','.join('?' * len(task_ids))})
                ORDER BY t.id''', list(task_ids)):
            tiles[row['parent_id']].append(dict(
                id=row['id'], title=row['title'], key=medal_key(row), importance=row['importance'], who=row['who'],
                state='done' if row['status'] == 'done' else 'busy' if row['status'] != 'open' else 'open',
                mine=bool(viewer_id) and row['assignee_id'] == viewer_id))
    return tiles


def grid(count):
    """Columns and rows for a mosaic of `count` tiles, kept around 3:2 so it sits well in a card."""
    count = max(count, 1)
    cols = min(count, ceil(sqrt(count * 1.6)))
    return cols, ceil(count / cols)


def listing(db, viewer_id, statuses=('open', 'active', 'review')):
    """Team tasks with who is in them and their shares. Ones you are in or published come first, then ones you
    can still join, then by deadline; finished ones newest first."""
    marks = ','.join('?' * len(statuses))
    rows = db.execute(f'''SELECT t.*,u.name owner_name,
            EXISTS(SELECT 1 FROM task_members m WHERE m.task_id=t.id AND m.user_id=?) joined,
            (SELECT MAX(e.created_at) FROM events e WHERE e.task_id=t.id AND e.kind='accept') done_at
        FROM tasks t JOIN users u ON u.id=t.owner_id WHERE t.kind='team' AND t.status IN ({marks})''',
                      (viewer_id, *statuses)).fetchall()
    ids = [row['id'] for row in rows]
    members, tiles = members_by_task(db, ids), tiles_by_parent(db, ids, viewer_id)
    items = []
    for row in rows:
        people = members[row['id']]
        left = None if row['team_size'] is None else max(row['team_size'] - len(people), 0)
        items.append(dict(row, members=people, tiles=tiles[row['id']], mine=row['owner_id'] == viewer_id, left=left,
                          open_seat=row['status'] in ('open', 'active') and left != 0 and row['deadline'] > now(),
                          pieces_done=sum(t['state'] == 'done' for t in tiles[row['id']])))
    if statuses == ('done',):
        return sorted(items, key=lambda item: item['done_at'] or '', reverse=True)
    return sorted(items, key=lambda item: (not (item['joined'] or item['mine']), not item['open_seat'], item['deadline']))


def together(db, user_id):
    """Team tasks this person got a medal for, newest first, with everyone who did it."""
    rows = db.execute('''SELECT h.*,t.title,t.owner_id,u.name owner_name,
            (SELECT body FROM events e WHERE e.task_id=t.id AND e.kind='accept' ORDER BY e.id DESC LIMIT 1) praise
        FROM honors h JOIN tasks t ON t.id=h.task_id JOIN users u ON u.id=t.owner_id
        WHERE h.user_id=? AND t.kind='team' ORDER BY h.awarded_at DESC,h.task_id DESC''', (user_id,)).fetchall()
    crew = {}
    for row in db.execute(f'''SELECT h.task_id,u.id,u.name FROM honors h JOIN users u ON u.id=h.user_id
            WHERE h.task_id IN ({','.join('?' * len(rows))}) ORDER BY u.id''', [row['task_id'] for row in rows]) if rows else ():
        crew.setdefault(row['task_id'], []).append(dict(id=row['id'], name=row['name']))
    return [dict(row, crew=crew.get(row['task_id'], [])) for row in rows]
