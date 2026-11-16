"""寄合: topics where members, and the AIs working for them, ask technical questions and hand work over.
Everyone signed in reads and posts in one shared space; posts are never deleted. A post sent through the JSON API is
marked as coming from the command line. Naming someone (explicit ids, or @名字 in the text) puts the topic in their inbox."""
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from jinja2.utils import urlize
from markupsafe import Markup

from .db import connect
from .service import InvalidAction, now

TITLE_LIMIT = 120
BODY_LIMIT = 10000
MAX_TO = 50
PAGE = 30
PREVIEW = 280

# 和我有关的话题：我开的、我说过话的、点过我名的，或者挂在我发布 / 在做 / 一起做的任务上
INVOLVED = '''(t.user_id=:me
 OR EXISTS (SELECT 1 FROM posts x WHERE x.topic_id=t.id AND x.user_id=:me)
 OR EXISTS (SELECT 1 FROM post_mentions m JOIN posts x ON x.id=m.post_id WHERE x.topic_id=t.id AND m.user_id=:me)
 OR EXISTS (SELECT 1 FROM tasks k WHERE k.id=t.task_id AND :me IN (k.owner_id,k.assignee_id))
 OR EXISTS (SELECT 1 FROM task_members k WHERE k.task_id=t.task_id AND k.user_id=:me))'''
UNREAD = '''p.user_id<>:me AND p.id>COALESCE((SELECT r.post_id FROM topic_reads r WHERE r.topic_id=t.id AND r.user_id=:me),0)'''


def _text(value, label, limit):
    if not isinstance(value, str):
        raise InvalidAction(f'{label}需要是文字。')
    value = value.strip()
    if not value or len(value) > limit:
        raise InvalidAction(f'{label}不能为空，且不能超过 {limit} 字。')
    return value


def _named(db, body, to, author):
    """Who a post calls on: the member ids passed in, plus anyone written as @名字 (the longest matching name wins)."""
    to = list(to or [])
    if len(to) > MAX_TO:
        raise InvalidAction(f'一次最多点 {MAX_TO} 个人。')
    users = db.execute('SELECT id,name FROM users').fetchall()
    known = {row['id'] for row in users}
    missing = [uid for uid in to if uid not in known]
    if missing:
        raise InvalidAction(f'没有编号为 {missing[0]} 的成员。')
    named = set(to)
    for at in re.finditer('@', body):
        hit = max((row for row in users if row['name'] and body.startswith(row['name'], at.end())),
                  key=lambda row: len(row['name']), default=None)
        if hit:
            named.add(hit['id'])
    named.discard(author)
    return sorted(named)


def _seen(db, user_id, topic_id, post_id):
    db.execute('''INSERT INTO topic_reads (user_id,topic_id,post_id) VALUES (?,?,?)
        ON CONFLICT(user_id,topic_id) DO UPDATE SET post_id=MAX(post_id,excluded.post_id)''', (user_id, topic_id, post_id))


def _post(db, topic_id, user_id, body, to, via):
    body = _text(body, '内容', BODY_LIMIT)
    named = _named(db, body, to, user_id)
    post_id = db.execute('INSERT INTO posts (topic_id,user_id,body,via,created_at) VALUES (?,?,?,?,?)',
                         (topic_id, user_id, body, via, now())).lastrowid
    db.executemany('INSERT INTO post_mentions (post_id,user_id) VALUES (?,?)', [(post_id, uid) for uid in named])
    _seen(db, user_id, topic_id, post_id)
    return post_id, named


def start(path, user_id, title, body, task_id=None, to=(), via='web'):
    """Open a topic with its first post; returns (topic id, ids of the people named)."""
    title = _text(title, '标题', TITLE_LIMIT)
    with connect(path, write=True) as db:
        if task_id is not None and not db.execute('SELECT 1 FROM tasks WHERE id=?', (task_id,)).fetchone():
            raise InvalidAction('关联的任务不存在。')
        topic_id = db.execute('INSERT INTO topics (title,user_id,task_id,created_at) VALUES (?,?,?,?)',
                              (title, user_id, task_id, now())).lastrowid
        return topic_id, _post(db, topic_id, user_id, body, to, via)[1]


def reply(path, topic_id, user_id, body, to=(), via='web'):
    """Answer in a topic; returns (post id, ids of the people named)."""
    with connect(path, write=True) as db:
        if not db.execute('SELECT 1 FROM topics WHERE id=?', (topic_id,)).fetchone():
            raise InvalidAction('话题不存在。')
        return _post(db, topic_id, user_id, body, to, via)


def mark_read(path, user_id, topic_id, post_id):
    with connect(path, write=True) as db:
        _seen(db, user_id, topic_id, post_id)


def topic(db, topic_id, viewer):
    row = db.execute('''SELECT t.*,u.name user_name,k.title task_title,k.status task_status,
            (SELECT COUNT(*) FROM posts p WHERE p.topic_id=t.id) posts,
            COALESCE((SELECT r.post_id FROM topic_reads r WHERE r.topic_id=t.id AND r.user_id=?),0) last_read
        FROM topics t JOIN users u ON u.id=t.user_id LEFT JOIN tasks k ON k.id=t.task_id WHERE t.id=?''',
                     (viewer, topic_id)).fetchone()
    return dict(row) if row else None


def _with_names(db, rows):
    """Each post gets the people it named and whether it came through the command line."""
    ids = [row['id'] for row in rows]
    named = {}
    for start_at in range(0, len(ids), 500):
        chunk = ids[start_at:start_at + 500]
        for row in db.execute(f'''SELECT m.post_id,u.id,u.name FROM post_mentions m JOIN users u ON u.id=m.user_id
                WHERE m.post_id IN ({','.join('?' * len(chunk))}) ORDER BY u.name''', chunk):
            named.setdefault(row['post_id'], []).append(dict(id=row['id'], name=row['name']))
    for row in rows:
        row['to'] = named.get(row['id'], [])
        row['ai'] = row['via'] == 'cli'
    return rows


def posts(db, topic_id, after=0, limit=-1):
    return _with_names(db, [dict(row) for row in db.execute('''SELECT p.*,u.name user_name FROM posts p
        JOIN users u ON u.id=p.user_id WHERE p.topic_id=? AND p.id>? ORDER BY p.id LIMIT ?''', (topic_id, after, limit))])


def _previews(db, post_ids):
    rows = _with_names(db, [dict(row) for row in db.execute(f'''SELECT p.id,p.user_id,u.name user_name,p.via,p.body,p.created_at
        FROM posts p JOIN users u ON u.id=p.user_id WHERE p.id IN ({','.join('?' * len(post_ids))})''', post_ids)])
    for row in rows:
        body = ' '.join(re.sub(r'```[^\n]*', ' ', row.pop('body')).split())
        row['preview'] = body if len(body) <= PREVIEW else body[:PREVIEW] + '…'
        row.pop('via')
    return {row['id']: row for row in rows}


def listing(db, viewer, q='', task_id=None, mine=False, limit=PAGE, offset=0):
    """Topics, most recent activity first; unread counts only for topics this person is part of."""
    clauses, values = [], dict(me=viewer)
    if q:
        clauses.append('(t.title LIKE :q OR EXISTS (SELECT 1 FROM posts x WHERE x.topic_id=t.id AND x.body LIKE :q))')
        values['q'] = f'%{q}%'
    if task_id:
        clauses.append('t.task_id=:task'); values['task'] = task_id
    if mine:
        clauses.append(INVOLVED)
    where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    total = db.execute('SELECT COUNT(*) FROM topics t' + where, values).fetchone()[0]
    items = [dict(row) for row in db.execute(f'''SELECT t.*,u.name user_name,k.title task_title,
            (SELECT COUNT(*) FROM posts p WHERE p.topic_id=t.id) posts,
            (SELECT MAX(p.id) FROM posts p WHERE p.topic_id=t.id) last_id,
            {INVOLVED} involved,
            (SELECT COUNT(*) FROM posts p WHERE p.topic_id=t.id AND {UNREAD}) unseen
        FROM topics t JOIN users u ON u.id=t.user_id LEFT JOIN tasks k ON k.id=t.task_id{where}
        ORDER BY last_id DESC LIMIT :limit OFFSET :offset''', dict(values, limit=limit, offset=offset))]
    last = _previews(db, [item['last_id'] for item in items]) if items else {}
    for item in items:
        item['involved'] = bool(item['involved'])
        item['unread'] = item.pop('unseen') if item['involved'] else 0
        item['last'] = last.get(item['last_id'])
    return dict(items=items, total=total, limit=limit, offset=offset,
                next_offset=offset + len(items) if offset + len(items) < total else None)


def cursor(db):
    return db.execute('SELECT COALESCE(MAX(id),0) FROM posts').fetchone()[0]


def inbox(db, viewer, after=0, upto=None, limit=50):
    """Topics with posts this person has not read yet, newest first: they were named, or it is a topic they are part of.
    Only posts with after < id <= upto count, so a poller that keeps the cursor never misses or repeats one."""
    upto = cursor(db) if upto is None else upto
    items = [dict(row) for row in db.execute(f'''SELECT t.id topic_id,t.title,t.task_id,k.title task_title,
            COUNT(*) unread,MIN(p.id) first_unread,MAX(p.id) last_id,
            MAX(EXISTS (SELECT 1 FROM post_mentions m WHERE m.post_id=p.id AND m.user_id=:me)) mentioned
        FROM topics t JOIN posts p ON p.topic_id=t.id LEFT JOIN tasks k ON k.id=t.task_id
        WHERE p.id>:after AND p.id<=:upto AND {UNREAD} AND {INVOLVED}
        GROUP BY t.id ORDER BY last_id DESC LIMIT :limit''', dict(me=viewer, after=after, upto=upto, limit=limit))]
    last = _previews(db, [item['last_id'] for item in items]) if items else {}
    for item in items:
        item['mentioned'] = bool(item['mentioned'])
        item['last'] = last[item.pop('last_id')]
    return items


def unread_count(db, viewer):
    return db.execute(f'''SELECT COUNT(DISTINCT t.id) FROM topics t JOIN posts p ON p.topic_id=t.id
        WHERE {UNREAD} AND {INVOLVED}''', dict(me=viewer)).fetchone()[0]


def for_task(db, task_id):
    return db.execute('''SELECT t.id,t.title,COUNT(p.id) posts,MAX(p.created_at) last_at FROM topics t
        JOIN posts p ON p.topic_id=t.id WHERE t.task_id=? GROUP BY t.id ORDER BY MAX(p.id) DESC''', (task_id,)).fetchall()


FENCE = re.compile(r'^```[^\n`]*\n(.*?)(?:^```[ \t]*$|\Z)', re.M | re.S)


def _prose(text):
    text = text.strip('\n')
    if not text.strip():
        return Markup('')
    pieces = re.split(r'`([^`\n]+)`', text)
    html = Markup('').join(Markup('<code>{}</code>').format(piece) if i % 2 else
                           Markup(urlize(piece, trim_url_limit=64, rel='noopener noreferrer', target='_blank'))
                           for i, piece in enumerate(pieces))
    return Markup('<p>{}</p>').format(html)


def render(body):
    """Escaped plain text with links, `inline code` and ``` fenced blocks; nothing else is interpreted."""
    parts, last = [], 0
    for block in FENCE.finditer(body):
        parts.append(_prose(body[last:block.start()]))
        parts.append(Markup('<pre><code>{}</code></pre>').format(block.group(1).rstrip('\n')))
        last = block.end()
    parts.append(_prose(body[last:]))
    return Markup('').join(parts)


def install(app):
    path = app.config['DATABASE']
    page = Blueprint('talk', __name__, url_prefix='/talk')
    app.jinja_env.filters['talk_body'] = render

    @app.context_processor
    def talk_badge():
        if not g.get('user'):
            return dict(talk_unread=0)
        with connect(path) as db:
            return dict(talk_unread=unread_count(db, g.user['id']))

    @page.before_request
    def signed_in():
        if not g.get('user'):
            return redirect(url_for('auth', mode='login'))

    def people(db):
        return db.execute('SELECT id,name FROM users WHERE id<>? ORDER BY name,id', (g.user['id'],)).fetchall()

    def named_note(db, named):
        if named:
            names = '、'.join(row['name'] for row in db.execute(
                f'SELECT name FROM users WHERE id IN ({",".join("?" * len(named))}) ORDER BY name', named))
            flash(f'已发出，点了 {names} 的名。', 'success')

    @page.get('')
    def board():
        query = request.args.get('q', '').strip()[:100]
        mine = request.args.get('scope') == 'mine'
        offset = int(request.args['offset']) if request.args.get('offset', '').isdigit() else 0
        with connect(path) as db:
            result = listing(db, g.user['id'], q=query, mine=mine, offset=offset)
            involved = db.execute(f'SELECT COUNT(*) FROM topics t WHERE {INVOLVED}', dict(me=g.user['id'])).fetchone()[0]
            everyone = db.execute('SELECT COUNT(*) FROM topics').fetchone()[0]
        return render_template('talk.html', result=result, query=query, mine=mine, involved=involved, everyone=everyone)

    def compose(status=200):
        form = request.form if request.method == 'POST' else request.args
        task_id = int(form['task']) if form.get('task', '').isdigit() else None
        with connect(path) as db:
            # 能关联的任务：自己发布 / 在做 / 一起做、还没完成的；从任务页过来的那个任务也放进去
            tasks = db.execute('''SELECT DISTINCT t.id,t.title FROM tasks t LEFT JOIN task_members m ON m.task_id=t.id
                WHERE (t.status<>'done' AND (t.owner_id=:me OR t.assignee_id=:me OR m.user_id=:me)) OR t.id=:task
                ORDER BY t.id DESC LIMIT 40''', dict(me=g.user['id'], task=task_id)).fetchall()
            members = people(db)
        return render_template('talk_new.html', tasks=tasks, members=members, form=form, task_id=task_id,
                               picked=form.getlist('to')), status

    @page.get('/new')
    def new():
        return compose()

    @page.post('')
    def create():
        form = request.form
        task_id = int(form['task']) if form.get('task', '').isdigit() else None
        try:
            topic_id, named = start(path, g.user['id'], form.get('title', ''), form.get('body', ''), task_id,
                                    [int(uid) for uid in form.getlist('to') if uid.isdigit()])
        except InvalidAction as error:
            flash(str(error), 'error')
            return compose(400)
        with connect(path) as db:
            named_note(db, named)
        return redirect(url_for('talk.thread', topic_id=topic_id))

    @page.get('/<int:topic_id>')
    def thread(topic_id):
        with connect(path) as db:
            item = topic(db, topic_id, g.user['id'])
            if not item:
                abort(404)
            rows = posts(db, topic_id)
            members = people(db)
        if rows and rows[-1]['id'] > item['last_read']:
            mark_read(path, g.user['id'], topic_id, rows[-1]['id'])
        return render_template('talk_topic.html', topic=item, posts=rows, members=members)

    @page.post('/<int:topic_id>')
    def answer(topic_id):
        try:
            post_id, named = reply(path, topic_id, g.user['id'], request.form.get('body', ''),
                                   [int(uid) for uid in request.form.getlist('to') if uid.isdigit()])
        except InvalidAction as error:
            flash(str(error), 'error')
            return redirect(url_for('talk.thread', topic_id=topic_id) + '#reply')
        with connect(path) as db:
            named_note(db, named)
        return redirect(url_for('talk.thread', topic_id=topic_id) + f'#p{post_id}')

    app.register_blueprint(page)
