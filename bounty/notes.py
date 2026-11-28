"""手帳：每个人的待办和记录，大家都能看到彼此在做什么、卡在哪。
有进展、遇到问题才记一笔，不用每天写；第一行是结论，后面是补充。可以挂在任务上、@ 别人（对方会收到提示），
也可以设成只自己看。遇到问题能顺手发成任务，那个任务做完，问题就算解决了。
加入、拆分工、提交、拿勋章这些任务上的事不用写，自动排进时间线。记录和待办都不删：待办「不做了」只是收起来。"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for
from markupsafe import Markup, escape

from .db import connect
from .honors import medal_key
from .service import InvalidAction, now, zone
from .talk import _named, mentions_of, render

BODY_LIMIT = 10000
TODO_LIMIT = 200
HOW_LIMIT = 2000
PAGE = 30
QUIET_DAYS = 7
KINDS = ('progress', 'problem')
STATES = ('todo', 'doing', 'done', 'dropped')
# 自动排进时间线的任务动态：发布（不含分工）、加入、拆分工、提交；拿到勋章另从 honors 里取
SYNCED = {'claim': '接下', 'join': '加入', 'split': '拆出分工', 'submit': '提交了'}


def _parse(value):
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _text(value, label, limit):
    if not isinstance(value, str):
        raise InvalidAction(f'{label}需要是文字。')
    value = value.strip()
    if not value or len(value) > limit:
        raise InvalidAction(f'{label}不能为空，且不能超过 {limit} 字。')
    return value


def _task_ok(db, task_id):
    if task_id is not None and not db.execute('SELECT 1 FROM tasks WHERE id=?', (task_id,)).fetchone():
        raise InvalidAction('关联的任务不存在。')


def _own(db, table, item_id, user_id, label):
    row = db.execute(f'SELECT * FROM {table} WHERE id=?', (item_id,)).fetchone()
    if not row:
        raise InvalidAction(f'{label}不存在。')
    if row['user_id'] != user_id:
        raise InvalidAction(f'只能改自己的{label}。')
    return row


def _mention(db, note_id, body, author):
    named = _named(db, body, [], author)
    db.executemany('INSERT OR IGNORE INTO note_mentions (note_id,user_id) VALUES (?,?)', [(note_id, uid) for uid in named])
    return named


# ---------------- 写 ----------------
def write(path, user_id, body, kind='progress', task_id=None, private=False, via='web', tz=None):
    """Record one note; returns (note id, ids of the people it names). A private note names nobody."""
    body = _text(body, '记录', BODY_LIMIT)
    if kind not in KINDS:
        raise InvalidAction('记录只分「进展」和「问题」。')
    with connect(path, write=True) as db:
        _task_ok(db, task_id)
        note_id = db.execute('''INSERT INTO notes (user_id,kind,body,task_id,private,via,tz,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)''', (user_id, kind, body, task_id, int(bool(private)), via, tz or None, now(), now())).lastrowid
        return note_id, ([] if private else _mention(db, note_id, body, user_id))


def edit(path, user_id, note_id, body):
    body = _text(body, '记录', BODY_LIMIT)
    with connect(path, write=True) as db:
        note = _own(db, 'notes', note_id, user_id, '记录')
        db.execute('UPDATE notes SET body=?,updated_at=? WHERE id=?', (body, now(), note_id))
        return [] if note['private'] else _mention(db, note_id, body, user_id)


def set_private(path, user_id, note_id, private):
    """Only me ↔ everyone. Going private also withdraws the mentions, so nobody is pointed at a note they cannot open."""
    with connect(path, write=True) as db:
        note = _own(db, 'notes', note_id, user_id, '记录')
        db.execute('UPDATE notes SET private=? WHERE id=?', (int(bool(private)), note_id))
        if private:
            db.execute('DELETE FROM note_mentions WHERE note_id=?', (note_id,))
        else:
            _mention(db, note_id, note['body'], user_id)


def solve(path, user_id, note_id, how=''):
    """Anyone can close a public problem and say how; the one who wrote it can close a private one."""
    how = how.strip() if isinstance(how, str) else ''
    if len(how) > HOW_LIMIT:
        raise InvalidAction(f'怎么解决的，不超过 {HOW_LIMIT} 字。')
    with connect(path, write=True) as db:
        note = db.execute('SELECT * FROM notes WHERE id=?', (note_id,)).fetchone()
        if not note or (note['private'] and note['user_id'] != user_id):
            raise InvalidAction('记录不存在。')
        if note['kind'] != 'problem':
            raise InvalidAction('只有「问题」能标成解决了。')
        if note['solved_at']:
            raise InvalidAction('已经标成解决了。')
        db.execute('UPDATE notes SET solved_at=?,solved_by=?,solution=? WHERE id=?', (now(), user_id, how or None, note_id))


def link_spawn(path, user_id, note_id, task_id):
    """A problem that was published as a task remembers it; when that task is done, the problem counts as solved."""
    with connect(path, write=True) as db:
        note = db.execute('SELECT * FROM notes WHERE id=?', (note_id,)).fetchone()
        task = db.execute('SELECT owner_id FROM tasks WHERE id=?', (task_id,)).fetchone()
        if note and task and note['user_id'] == user_id == task['owner_id'] and note['kind'] == 'problem':
            db.execute('UPDATE notes SET spawned_task_id=? WHERE id=?', (task_id, note_id))


def add_todo(path, user_id, title, task_id=None, private=False, via='web'):
    title = _text(title, '待办', TODO_LIMIT)
    with connect(path, write=True) as db:
        _task_ok(db, task_id)
        return db.execute('''INSERT INTO todos (user_id,title,task_id,private,via,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?)''', (user_id, title, task_id, int(bool(private)), via, now(), now())).lastrowid


def set_todo(path, user_id, todo_id, state=None, private=None, title=None):
    if state is not None and state not in STATES:
        raise InvalidAction('待办的状态只有 todo、doing、done、dropped。')
    with connect(path, write=True) as db:
        todo = _own(db, 'todos', todo_id, user_id, '待办')
        if title is not None:
            db.execute('UPDATE todos SET title=? WHERE id=?', (_text(title, '待办', TODO_LIMIT), todo_id))
        if state is not None and state != todo['state']:
            db.execute('UPDATE todos SET state=?,done_at=? WHERE id=?', (state, now() if state == 'done' else None, todo_id))
        if private is not None:
            db.execute('UPDATE todos SET private=? WHERE id=?', (int(bool(private)), todo_id))
        db.execute('UPDATE todos SET updated_at=? WHERE id=?', (now(), todo_id))
        return dict(db.execute('SELECT * FROM todos WHERE id=?', (todo_id,)).fetchone())


# ---------------- 读 ----------------
NOTE_SELECT = '''SELECT n.*,u.name user_name,t.title task_title,s.title spawned_title,s.status spawned_status,
        v.name solved_name
    FROM notes n JOIN users u ON u.id=n.user_id LEFT JOIN tasks t ON t.id=n.task_id
    LEFT JOIN tasks s ON s.id=n.spawned_task_id LEFT JOIN users v ON v.id=n.solved_by'''


def _decorate(db, rows, viewer):
    """Split the first line off as the headline, mark AI-written notes, work out whether a problem is solved
    (marked solved, or the task it became is done) and who named whom."""
    notes = [dict(row) for row in rows]
    ids = [note['id'] for note in notes]
    named = defaultdict(list)
    if ids:
        for row in db.execute(f'''SELECT m.note_id,u.id,u.name FROM note_mentions m JOIN users u ON u.id=m.user_id
                WHERE m.note_id IN ({','.join('?' * len(ids))}) ORDER BY u.name''', ids):
            named[row['note_id']].append(dict(id=row['id'], name=row['name']))
    spawned = [note['spawned_task_id'] for note in notes if note['spawned_status'] == 'done']
    doers = defaultdict(list)
    if spawned:
        for row in db.execute(f'''SELECT h.task_id,u.name FROM honors h JOIN users u ON u.id=h.user_id
                WHERE h.task_id IN ({','.join('?' * len(spawned))}) ORDER BY h.user_id''', spawned):
            doers[row['task_id']].append(row['name'])
    for note in notes:
        head, _, more = note['body'].strip().partition('\n')
        note.update(head=head.strip(), more=more.strip(), named=named[note['id']], ai=note['via'] == 'cli',
                    mine=note['user_id'] == viewer)
        note['solved'] = bool(note['solved_at']) or note['spawned_status'] == 'done'
        if not note['solved_at'] and note['spawned_status'] == 'done':
            note['solved_name'] = '、'.join(doers[note['spawned_task_id']]) or None
            note['solution'] = f'做完了 #{note["spawned_task_id"]} {note["spawned_title"]}'
    return notes


def _visible(alias='n'):
    return f'({alias}.private=0 OR {alias}.user_id=:viewer)'


def _synced(db, user_id, since, until):
    """What the site already knows this person did on tasks, as small timeline items."""
    items = []
    for row in db.execute('''SELECT t.id,t.title,t.created_at FROM tasks t
            WHERE t.owner_id=? AND t.parent_id IS NULL AND t.created_at>? AND t.created_at<=?''', (user_id, since, until)):
        items.append(dict(at=row['created_at'], verb='发布了', task_id=row['id'], title=row['title']))
    for row in db.execute(f'''SELECT e.kind,e.body,e.created_at,t.id,t.title FROM events e JOIN tasks t ON t.id=e.task_id
            WHERE e.user_id=? AND e.kind IN ({','.join('?' * len(SYNCED))}) AND e.created_at>? AND e.created_at<=?''',
                          (user_id, *SYNCED, since, until)):
        if row['kind'] == 'split':
            items.append(dict(at=row['created_at'], verb='在', task_id=row['id'], title=row['title'], tail=f'里拆出分工「{row["body"]}」'))
        else:
            items.append(dict(at=row['created_at'], verb=SYNCED[row['kind']], task_id=row['id'], title=row['title']))
    for row in db.execute('''SELECT h.awarded_at,t.id,t.title,t.importance,t.urgency FROM honors h JOIN tasks t ON t.id=h.task_id
            WHERE h.user_id=? AND h.awarded_at>? AND h.awarded_at<=?''', (user_id, since, until)):
        items.append(dict(at=row['awarded_at'], verb='', task_id=row['id'], title=row['title'], tail='验收通过',
                          medal=medal_key(row)))
    return items


def timeline(db, owner, viewer, tz, before=None, limit=PAGE):
    """Days with something in them, newest first: the notes this viewer may see, and one quiet line per day for the
    task events. Days with nothing simply do not appear."""
    until = before or '9999'
    rows = db.execute(f'''{NOTE_SELECT} WHERE n.user_id=:owner AND {_visible()} AND n.created_at<:until
        ORDER BY n.created_at DESC,n.id DESC LIMIT :limit''', dict(owner=owner, viewer=viewer, until=until, limit=limit + 1)).fetchall()
    more = len(rows) > limit
    notes = _decorate(db, rows[:limit], viewer)
    # 任务动态只排到最早那条记录为止；记录不多时往回看 60 天
    floor = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    since = notes[-1]['created_at'] if more else min([floor] + [note['created_at'] for note in notes[-1:]])
    days = defaultdict(lambda: dict(notes=[], synced=[]))
    for note in notes:
        days[_parse(note['created_at']).astimezone(tz).date()]['notes'].append(note)
    for item in _synced(db, owner, since, until):
        days[_parse(item['at']).astimezone(tz).date()]['synced'].append(item)
    today = datetime.now(tz).date()
    out = []
    for day in sorted(days, reverse=True):
        entry = days[day]
        items = [dict(type='note', at=note['created_at'], note=note) for note in entry['notes']]
        if entry['synced']:   # 同一天的任务动态合成一行，放在当天最后一件的位置
            entry['synced'].sort(key=lambda item: item['at'])
            items.append(dict(type='synced', at=entry['synced'][-1]['at'], items=entry['synced']))
        items.sort(key=lambda item: item['at'], reverse=True)
        out.append(dict(day=day, num=day.day, label=day_label(day, today), today=day == today, items=items))
    return dict(days=out, older=notes[-1]['created_at'] if more else None)


def day_label(day, today):
    if day == today:
        return '今天'
    if day == today - timedelta(days=1):
        return '昨天'
    week = '周' + '一二三四五六日'[day.weekday()]
    if day.year != today.year:
        return f'{day.year}年{day.month}月 · {week}'
    return week if day.month == today.month else f'{day.month}月 · {week}'


def todos(db, owner, viewer):
    """Open to-dos grouped under the tasks this person is doing (those groups appear even when empty), then the rest;
    what was finished in the last day stays visible, struck through."""
    tasks = db.execute('''SELECT t.id,t.title,t.importance,t.urgency FROM tasks t JOIN task_members m ON m.task_id=t.id
        WHERE m.user_id=? AND t.status IN ('open','active','review') AND t.parent_id IS NULL ORDER BY t.deadline''', (owner,)).fetchall()
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    rows = db.execute('''SELECT d.*,t.title task_title,t.importance,t.urgency FROM todos d LEFT JOIN tasks t ON t.id=d.task_id
        WHERE d.user_id=:owner AND (d.private=0 OR d.user_id=:viewer)
          AND (d.state IN ('todo','doing') OR (d.state='done' AND d.done_at>:recent))
        ORDER BY d.state='done',d.state<>'doing',d.id''', dict(owner=owner, viewer=viewer, recent=recent)).fetchall()
    groups, order = {}, []
    for task in tasks:
        groups[task['id']] = dict(task_id=task['id'], title=task['title'], medal=medal_key(task), items=[])
        order.append(task['id'])
    loose = dict(task_id=None, title='其他', medal=None, items=[])
    for row in rows:
        if row['task_id'] and row['task_id'] not in groups:
            groups[row['task_id']] = dict(task_id=row['task_id'], title=row['task_title'], medal=medal_key(row), items=[])
            order.append(row['task_id'])
        (groups[row['task_id']] if row['task_id'] else loose)['items'].append(dict(row))
    return [groups[key] for key in order] + [loose]


def ago(value):
    seconds = (datetime.now(timezone.utc) - _parse(value)).total_seconds()
    if seconds < 3600:
        return f'{max(int(seconds // 60), 1)} 分钟前'
    if seconds < 86400:
        return f'{int(seconds // 3600)} 小时前'
    return '昨天' if seconds < 172800 else f'{int(seconds // 86400)} 天前'


def team(db, viewer, tz, crew_only=False):
    """The 大家 page: open problems waiting for help, then one card per person (most recently active first), then the
    people who have been quiet for a week, shown only by what they are doing."""
    stuck = [note for note in _decorate(db, db.execute(f'''{NOTE_SELECT} WHERE n.kind='problem' AND n.private=0
        AND n.solved_at IS NULL AND n.user_id<>:viewer AND COALESCE(s.status,'')<>'done'
        ORDER BY n.created_at DESC LIMIT 12''', dict(viewer=viewer)).fetchall(), viewer)]
    crew = {row[0] for row in db.execute('''SELECT DISTINCT b.user_id FROM task_members a JOIN task_members b ON b.task_id=a.task_id
        JOIN tasks t ON t.id=a.task_id WHERE a.user_id=? AND t.status IN ('open','active','review')''', (viewer,))}
    doing = defaultdict(list)
    for row in db.execute('''SELECT m.user_id,t.id,t.title,
            (SELECT d.title FROM todos d WHERE d.user_id=m.user_id AND d.task_id=t.id AND d.state='doing' AND d.private=0
             ORDER BY d.updated_at DESC LIMIT 1) now_doing,
            (SELECT p.title FROM tasks p JOIN task_members q ON q.task_id=p.id
             WHERE p.parent_id=t.id AND q.user_id=m.user_id AND p.status='active' LIMIT 1) piece
        FROM task_members m JOIN tasks t ON t.id=m.task_id
        WHERE t.status IN ('active','review') AND t.parent_id IS NULL ORDER BY t.deadline'''):
        doing[row['user_id']].append(dict(id=row['id'], title=row['title'], now=row['now_doing'] or row['piece']))
    quiet_since = (datetime.now(timezone.utc) - timedelta(days=QUIET_DAYS)).isoformat()
    people, quiet = [], []
    for user in db.execute('''SELECT u.id,u.name,
            (SELECT MAX(n.created_at) FROM notes n WHERE n.user_id=u.id AND n.private=0) noted,
            (SELECT n.tz FROM notes n WHERE n.user_id=u.id AND n.tz IS NOT NULL ORDER BY n.id DESC LIMIT 1) tz,
            (SELECT MAX(e.created_at) FROM events e WHERE e.user_id=u.id) acted
        FROM users u WHERE u.id<>? ORDER BY u.name''', (viewer,)):
        if crew_only and user['id'] not in crew:
            continue
        last_at = max(filter(None, (user['noted'], user['acted'])), default=None)
        card = dict(id=user['id'], name=user['name'], doing=doing[user['id']], last_at=last_at,
                    ago=ago(last_at) if last_at else None, away=_away(user['tz'], tz))
        if not last_at or last_at < quiet_since:
            if card['doing']:
                quiet.append(card)
            continue
        last = db.execute(f'''{NOTE_SELECT} WHERE n.user_id=? AND n.private=0 AND n.kind='progress'
            ORDER BY n.created_at DESC LIMIT 1''', (user['id'],)).fetchone()
        card['last'] = _decorate(db, [last], viewer)[0] if last else None
        people.append(card)
    people.sort(key=lambda card: card['last_at'], reverse=True)
    return dict(stuck=stuck, people=people, quiet=quiet, crew_size=len(crew - {viewer}))


def _away(name, viewer_tz):
    """Their local time, only when it differs from the viewer's by an hour or more; flags the small hours."""
    if not name:
        return None
    theirs = zone(name)
    moment = datetime.now(timezone.utc)
    gap = abs(moment.astimezone(theirs).utcoffset() - moment.astimezone(viewer_tz).utcoffset())
    if gap < timedelta(hours=1):
        return None
    local = moment.astimezone(theirs)
    return dict(time=f'{local:%H:%M}', night=local.hour < 7 or local.hour >= 23)


def for_task(db, task_id, viewer, limit=8):
    """Notes people wrote about a task: problems still open first, then newest."""
    rows = db.execute(f'''{NOTE_SELECT} WHERE n.task_id=:task AND {_visible()}
        ORDER BY (n.kind='problem' AND n.solved_at IS NULL AND COALESCE(s.status,'')<>'done') DESC,n.created_at DESC
        LIMIT :limit''', dict(task=task_id, viewer=viewer, limit=limit + 1)).fetchall()
    return _decorate(db, rows[:limit], viewer), len(rows) > limit


def mentions(db, user_id, limit=50):
    rows = db.execute(f'''{NOTE_SELECT} JOIN note_mentions m ON m.note_id=n.id
        WHERE m.user_id=? AND n.private=0 ORDER BY n.created_at DESC LIMIT ?''', (user_id, limit)).fetchall()
    notes = _decorate(db, rows, user_id)
    unseen = {row[0] for row in db.execute('SELECT note_id FROM note_mentions WHERE user_id=? AND seen_at IS NULL', (user_id,))}
    for note in notes:
        note['fresh'] = note['id'] in unseen
    return notes


def unseen_count(db, user_id):
    return db.execute('''SELECT COUNT(*) FROM note_mentions m JOIN notes n ON n.id=m.note_id
        WHERE m.user_id=? AND m.seen_at IS NULL AND n.private=0''', (user_id,)).fetchone()[0]


def unseen(db, user_id, limit=20):
    """Mentions not read yet, newest first; they stay until the note or 提到我 is opened."""
    rows = db.execute(f'''{NOTE_SELECT} JOIN note_mentions m ON m.note_id=n.id
        WHERE m.user_id=? AND m.seen_at IS NULL AND n.private=0 ORDER BY n.created_at DESC LIMIT ?''', (user_id, limit)).fetchall()
    return _decorate(db, rows, user_id)


def mark_seen(path, user_id, note_ids=None):
    with connect(path, write=True) as db:
        if note_ids is None:
            db.execute('UPDATE note_mentions SET seen_at=? WHERE user_id=? AND seen_at IS NULL', (now(), user_id))
        else:
            db.executemany('UPDATE note_mentions SET seen_at=? WHERE user_id=? AND note_id=? AND seen_at IS NULL',
                           [(now(), user_id, note_id) for note_id in note_ids])


def body_html(text, named, viewer):
    """Same plain-text rendering as 寄合 (links, `code`, fenced blocks), with @names picked out."""
    html = str(render(text))
    for person in sorted(named, key=lambda p: -len(p['name'])):
        tag = escape('@' + person['name'])
        cls = 'mref me' if person['id'] == viewer else 'mref'
        html = html.replace(str(tag), str(Markup('<span class="{}">{}</span>').format(cls, tag)))
    return Markup(html)


def head_html(text, named, viewer):
    html = str(escape(text))
    for person in sorted(named, key=lambda p: -len(p['name'])):
        tag = escape('@' + person['name'])
        cls = 'mref me' if person['id'] == viewer else 'mref'
        html = html.replace(str(tag), str(Markup('<span class="{}">{}</span>').format(cls, tag)))
    return Markup(html)


# ---------------- 页面 ----------------
def install(app):
    path = app.config['DATABASE']
    page = Blueprint('notes', __name__, url_prefix='/notes')
    app.jinja_env.filters['note_body'] = lambda note: body_html(note['more'], note['named'], g.user['id'])
    app.jinja_env.filters['note_head'] = lambda note: head_html(note['head'], note['named'], g.user['id'])
    app.jinja_env.filters['hm'] = lambda value: f'{_parse(value).astimezone(g.get("tz") or timezone.utc):%H:%M}' if value else ''

    def task_progress(task_id):
        with connect(path) as db:
            return for_task(db, task_id, g.user['id'])

    app.jinja_env.globals['task_progress'] = task_progress

    @page.before_request
    def signed_in():
        if not g.get('user'):
            return redirect(url_for('auth', mode='login'))

    def wants_json():
        return request.accept_mimetypes.best == 'application/json' or request.headers.get('X-Requested-With') == 'fetch'

    def my_tasks(db):
        return db.execute('''SELECT t.id,t.title,t.importance,t.urgency FROM tasks t JOIN task_members m ON m.task_id=t.id
            WHERE m.user_id=? AND t.status IN ('open','active','review') AND t.parent_id IS NULL ORDER BY t.deadline''',
                          (g.user['id'],)).fetchall()

    def show(owner):
        before = request.args.get('before', '')
        with connect(path) as db:
            person = db.execute('SELECT id,name FROM users WHERE id=?', (owner,)).fetchone()
            if not person:
                abort(404)
            data = timeline(db, owner, g.user['id'], g.tz, before or None)
            groups = todos(db, owner, g.user['id'])
            tasks = my_tasks(db) if owner == g.user['id'] else []
            people = db.execute('SELECT id,name FROM users ORDER BY name').fetchall()
            crew = {row[0] for row in db.execute('''SELECT DISTINCT b.user_id FROM task_members a
                JOIN task_members b ON b.task_id=a.task_id JOIN tasks t ON t.id=a.task_id
                WHERE a.user_id=? AND t.status IN ('open','active','review')''', (g.user['id'],))}
        return render_template('notes.html', person=person, mine=owner == g.user['id'], data=data, groups=groups,
                               tasks=tasks, before=before, fresh=request.args.get('new', type=int),
                               solved=request.args.get('solved', type=int),
                               people=[dict(id=p['id'], name=p['name'], crew=p['id'] in crew)
                                       for p in people if p['id'] != g.user['id']])

    @page.get('')
    def mine():
        return show(g.user['id'])

    @page.get('/u/<int:user_id>')
    def person(user_id):
        if user_id == g.user['id']:
            return redirect(url_for('notes.mine'))
        return show(user_id)

    @page.get('/team')
    def everyone():
        crew_only = request.args.get('scope') == 'crew'
        with connect(path) as db:
            data = team(db, g.user['id'], g.tz, crew_only)
        return render_template('notes_team.html', data=data, crew_only=crew_only)

    @page.get('/at')
    def at_me():
        # 手帳和寄合里提到我的放在一起按时间排；打开这页算看过手帳里的 @，寄合的要点进话题才算读过
        with connect(path) as db:
            items = [('note', note) for note in mentions(db, g.user['id'])]
            items += [('talk', post) for post in mentions_of(db, g.user['id'])]
        items.sort(key=lambda item: item[1]['created_at'], reverse=True)
        mark_seen(path, g.user['id'])
        return render_template('notes_at.html', items=items[:50])

    @page.get('/n/<int:note_id>')
    def go(note_id):
        with connect(path) as db:
            note = db.execute('SELECT user_id,private FROM notes WHERE id=?', (note_id,)).fetchone()
        if not note or (note['private'] and note['user_id'] != g.user['id']):
            abort(404)
        mark_seen(path, g.user['id'], [note_id])
        target = url_for('notes.mine') if note['user_id'] == g.user['id'] else url_for('notes.person', user_id=note['user_id'])
        return redirect(f'{target}#n{note_id}')

    @page.post('')
    def create():
        form = request.form
        task_id = int(form['task']) if form.get('task', '').isdigit() else None
        kind = 'problem' if form.get('kind') == 'problem' else 'progress'
        try:
            note_id, named = write(path, g.user['id'], form.get('body', ''), kind, task_id, form.get('private') == '1',
                                   tz=g.get('tz_name') or None)
        except InvalidAction as error:
            flash(str(error), 'error')
            return redirect(url_for('notes.mine'))
        if named:
            with connect(path) as db:
                names = '、'.join(row['name'] for row in db.execute(
                    f'SELECT name FROM users WHERE id IN ({",".join("?" * len(named))}) ORDER BY name', named))
            flash(f'记下了，{names} 会收到提示。', 'success')
        if kind == 'problem' and form.get('spawn') == '1':
            head, _, more = form.get('body', '').strip().partition('\n')
            with connect(path) as db:
                task = db.execute('SELECT project FROM tasks WHERE id=?', (task_id,)).fetchone() if task_id else None
            return redirect(url_for('new_task', title=head.strip()[:120], description=(more.strip() or head.strip())[:10000],
                                    project=(task['project'] or '') if task else '', from_note=note_id))
        return redirect(url_for('notes.mine', new=note_id) + f'#n{note_id}')

    def back_to(note_id, owner, **args):
        target = url_for('notes.mine', **args) if owner == g.user['id'] else url_for('notes.person', user_id=owner, **args)
        return redirect(f'{target}#n{note_id}')

    def owner_of(note_id):
        with connect(path) as db:
            row = db.execute('SELECT user_id FROM notes WHERE id=?', (note_id,)).fetchone()
        if not row:
            abort(404)
        return row['user_id']

    @page.post('/<int:note_id>/edit')
    def change(note_id):
        try:
            edit(path, g.user['id'], note_id, request.form.get('body', ''))
        except InvalidAction as error:
            flash(str(error), 'error')
        return back_to(note_id, owner_of(note_id))

    @page.post('/<int:note_id>/private')
    def hide(note_id):
        try:
            set_private(path, g.user['id'], note_id, request.form.get('private') == '1')
        except InvalidAction as error:
            flash(str(error), 'error')
        return back_to(note_id, owner_of(note_id))

    @page.post('/<int:note_id>/solve')
    def close(note_id):
        try:
            solve(path, g.user['id'], note_id, request.form.get('how', ''))
        except InvalidAction as error:
            flash(str(error), 'error')
            return back_to(note_id, owner_of(note_id))
        return back_to(note_id, owner_of(note_id), solved=note_id)

    @page.post('/todos')
    def new_todo():
        task_id = int(request.form['task']) if request.form.get('task', '').isdigit() else None
        try:
            todo_id = add_todo(path, g.user['id'], request.form.get('title', ''), task_id)
        except InvalidAction as error:
            if wants_json():
                return jsonify(ok=False, error=str(error)), 400
            flash(str(error), 'error')
            return redirect(url_for('notes.mine'))
        if wants_json():
            return jsonify(ok=True, id=todo_id)
        return redirect(url_for('notes.mine') + '#todos')

    @page.post('/todos/<int:todo_id>')
    def update_todo(todo_id):
        form = request.form
        private = None if 'private' not in form else form.get('private') == '1'
        try:
            todo = set_todo(path, g.user['id'], todo_id, form.get('state') or None, private)
        except InvalidAction as error:
            if wants_json():
                return jsonify(ok=False, error=str(error)), 400
            flash(str(error), 'error')
            return redirect(url_for('notes.mine') + '#todos')
        if wants_json():
            return jsonify(ok=True, state=todo['state'], private=bool(todo['private']))
        return redirect(url_for('notes.mine') + '#todos')

    @page.post('/n/<int:note_id>/seen')
    def seen(note_id):
        mark_seen(path, g.user['id'], [note_id])
        return jsonify(ok=True)

    app.register_blueprint(page)
