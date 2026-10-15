"""大任务：好几个人一起做的任务（tasks.kind='team'）。想做的人「加入」，发布者自己也可以加入；一起做的任何一个人都能
提交成果，发布者验收时选这次给谁发勋章（默认一起做的每个人）。

做的过程中随时可以拆出「分工」：分工就是普通小任务（tasks.parent_id 指向大任务），一个人认领、拿自己的勋章；
接下分工也就加入了大任务。分工不用一开始就拆好，想到再拆，不拆也行。"""
from markupsafe import Markup
from .db import connect
from .honors import MEDALS
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


def share_counts(db, task_ids):
    """(finished, all) shares split off each team task."""
    counts = {task_id: (0, 0) for task_id in task_ids}
    if task_ids:
        for row in db.execute(f'''SELECT parent_id,SUM(status='done') done,COUNT(*) total FROM tasks
                WHERE parent_id IN ({','.join('?' * len(task_ids))}) GROUP BY parent_id''', list(task_ids)):
            counts[row['parent_id']] = (row['done'], row['total'])
    return counts


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
    members, shares = members_by_task(db, ids), share_counts(db, ids)
    items = []
    for row in rows:
        people = members[row['id']]
        left = None if row['team_size'] is None else max(row['team_size'] - len(people), 0)
        items.append(dict(row, members=people, mine=row['owner_id'] == viewer_id, left=left,
                          open_seat=row['status'] in ('open', 'active') and left != 0 and row['deadline'] > now(),
                          pieces_done=shares[row['id']][0], pieces=shares[row['id']][1]))
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


def wave_art(status, members, team_size=None, cls='', fit='xMaxYMid slice', inside=False, width=400, height=180):
    """The big-task drawing for a medal-coloured field (400×180, white and ink only): 青海波 scales piled up from
    the bottom, one scale per seat. The pile fills its bottom row first, then the row above (each row one shorter,
    sitting in the gaps), and the scales shrink as the pile grows. Joined people are white scales (the first one
    ink), open seats are outlines (one spare when the size is open), so the missing ones sit on top. Handed in:
    only the people's scales, with a small ink sun above; done: a large white sun behind the pile.
    Scales carry --i (piling order) for the drop-in animation. inside=True keeps the whole pile in the box;
    otherwise the right edge crops it. width/height set the box (the default is the card's colour field)."""
    settled = status in ('review', 'done')
    seats = max(members, 1) if settled else max(team_size or members + 1, members, 1)
    seats = min(seats, 21)
    rows = 1
    while rows * (rows + 1) // 2 < seats:
        rows += 1
    r = min(46.0, width * (0.46 if inside else 0.31) / rows, height * 0.75 / rows)
    right = width - r - 4 if inside else width - r * 0.35
    spots = [(right - r * k - 2 * r * i, height + 8 - r * k) for k in range(rows) for i in range(rows - k)][:seats]
    top_x, top_y = spots[-1]
    parts = []
    if status == 'done':
        sun = max(50.0, r * 1.7)
        parts.append(f'<circle class="fl" style="--fx:-6px;--fy:4px" cx="{top_x - r * 0.4:.1f}" cy="{top_y - r * 0.5:.1f}" r="{sun:.1f}" fill="#fff"/>')
    elif status == 'review':
        parts.append(f'<circle class="fl" style="--fy:-6px" cx="{top_x:.1f}" cy="{top_y - r * 1.55:.1f}" r="{r * 0.5:.1f}" fill="#1B1D2A"/>')
    line = max(2.0, r * 0.075)
    for order, (x, y) in sorted(enumerate(spots), key=lambda item: (item[1][1], item[0])):
        joined = order < members
        lead = order == 0 and members > 0
        fill = '#1B1D2A' if lead else '#fff' if joined else 'var(--hue)'
        ring = '#fff' if lead else 'var(--hue)' if joined else 'rgba(255,255,255,.5)'
        shape = [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{fill}" stroke="var(--hue)" stroke-width="{line * 1.3:.1f}"/>']
        shape += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r * k:.1f}" fill="none" stroke="{ring}" stroke-width="{line:.1f}"/>' for k in (0.72, 0.46, 0.2)]
        if not joined:
            shape.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r - line:.1f}" fill="none" stroke="#fff" stroke-opacity=".7" '
                         f'stroke-width="{line:.1f}" stroke-dasharray="{line * 2:.1f} {line * 1.6:.1f}"/>')
        parts.append(f'<g class="wave" style="--i:{order}">{"".join(shape)}</g>')
    return Markup(f'<svg class="pick-art crew-art{" " + cls if cls else ""}" viewBox="0 0 {width} {height}" preserveAspectRatio="{fit}" '
                  f'aria-hidden="true">{"".join(parts)}</svg>')
