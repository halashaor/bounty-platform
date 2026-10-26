"""Small bearer-only JSON adapter over existing task services; no separate workflow or permissions."""
from datetime import datetime, timezone
import sqlite3

from flask import Blueprint, abort, current_app, g, jsonify, request
from werkzeug.exceptions import HTTPException
from . import cli_auth, discover, extend, progress, tags, teams
from .db import connect
from .service import InvalidAction, act, clap, create_task, STATUSES

api = Blueprint('mission_api', __name__, url_prefix='/api/v1')
ACTIONS = ('claim', 'join', 'leave', 'submit', 'accept', 'return', 'comment')


def database():
    return current_app.config['DATABASE']


def ok(data, status=200):
    return jsonify(ok=True, data=data), status


def failure(code, message, status):
    return jsonify(ok=False, error=dict(code=code, message=message)), status


@api.before_request
def authenticate():
    header = request.headers.get('Authorization', '')
    provider = current_app.extensions.get('mission_cli_auth')
    token = header[7:] if header.startswith('Bearer ') else ''
    # Cookie sessions alone never authorize API writes, so cross-site forms cannot act as the CLI.
    g.user = provider['authenticate'](token) if provider and 0 < len(token) <= 2048 else None
    if not g.user:
        return failure('unauthorized', '请运行 mission login 登录，或重新生成命令行访问凭据。', 401)
    if request.view_args and 'task_id' in request.view_args:
        integer(request.view_args['task_id'], 'task_id')
    g.cli_token = token


@api.errorhandler(InvalidAction)
def invalid(error):
    return failure('invalid_action', str(error), 400)


@api.errorhandler(HTTPException)
def http_error(error):
    return failure('http_error', error.description, error.code)


@api.errorhandler(sqlite3.OperationalError)
def database_error(error):
    current_app.logger.exception('API database operation failed')
    return failure('temporarily_unavailable', '操作暂时无法完成；写入可能已生效，请先查询任务再决定是否重试。', 503)


def payload():
    data = request.get_json()
    if not isinstance(data, dict):
        raise InvalidAction('请求正文需要是 JSON 对象。')
    return data


def text(data, name, default=''):
    value = data.get(name, default)
    if not isinstance(value, str):
        raise InvalidAction(f'{name} 需要是文字。')
    return value


def integer(value, name, minimum=1, maximum=2**63 - 1):
    try:
        if isinstance(value, bool) or isinstance(value, float):
            raise ValueError()
        number = int(value)
        if not minimum <= number <= maximum:
            raise ValueError()
        return number
    except (ValueError, TypeError, OverflowError):
        raise InvalidAction(f'{name} 需要是 {minimum}–{maximum} 之间的整数。')


def deadline(data, optional=False):
    raw = text(data, 'deadline')
    if optional and not raw:
        return ''
    try:
        moment = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if moment.tzinfo is None:
            raise ValueError()
        return moment.isoformat()
    except ValueError:
        raise InvalidAction('deadline 需要包含时区，例如 2027-01-20T18:00:00+08:00。')


def task(db, task_id):
    row = db.execute('''SELECT t.*,o.name owner_name,a.name assignee_name FROM tasks t
        JOIN users o ON o.id=t.owner_id LEFT JOIN users a ON a.id=t.assignee_id WHERE t.id=?''', (task_id,)).fetchone()
    if not row:
        abort(404, description='任务不存在。')
    result = dict(row)
    result['tags'] = discover.tags_by_task(db, [task_id])[task_id]
    result['members'] = teams.members_by_task(db, [task_id])[task_id]
    return result


def detail(task_id):
    with connect(database()) as db:
        result = task(db, task_id)
        result['events'] = [dict(r) for r in db.execute('''SELECT e.*,u.name user_name FROM events e
            JOIN users u ON u.id=e.user_id WHERE task_id=? ORDER BY e.id DESC LIMIT 50''', (task_id,))][::-1]
        result['extensions'] = [dict(r) for r in db.execute('SELECT * FROM extensions WHERE task_id=? ORDER BY id', (task_id,))]
        result['pieces'] = [dict(r) for r in db.execute('SELECT id,title,status,assignee_id FROM tasks WHERE parent_id=? ORDER BY id', (task_id,))]
    return result


@api.get('/me')
def me():
    with connect(database()) as db:
        return ok(dict(user=dict(g.user), progress=progress.person_progress(db, g.user['id'])))


@api.post('/logout')
def logout():
    current_app.extensions['mission_cli_auth']['revoke'](g.cli_token)
    return ok(dict(logged_out=True))


@api.get('/members')
def members():
    with connect(database()) as db:
        return ok([dict(r) for r in db.execute('SELECT id,name FROM users ORDER BY name,id')])


@api.get('/tags')
def tag_list():
    with connect(database()) as db:
        return ok(tags.listing(db))


@api.get('/mine')
def mine():
    with connect(database()) as db:
        return ok({key: [dict(r) for r in rows] for key, rows in discover.my_tasks(db, g.user['id']).items()})


@api.get('/tasks')
def task_list():
    limit = integer(request.args.get('limit', '50'), 'limit', maximum=100)
    offset = integer(request.args.get('offset', '0'), 'offset', minimum=0)
    clauses, values = [], []
    for key, allowed in [('status', STATUSES), ('kind', ('solo', 'team'))]:
        value = request.args.get(key)
        if value:
            if value not in allowed:
                raise InvalidAction(f'{key} 无效。')
            clauses.append(f't.{key}=?'); values.append(value)
    for key in ('owner_id', 'assignee_id', 'parent_id'):
        if request.args.get(key):
            clauses.append(f't.{key}=?'); values.append(integer(request.args[key], key))
    for key in ('project',):
        if request.args.get(key):
            clauses.append(f't.{key}=?'); values.append(request.args[key])
    if request.args.get('tag'):
        clauses.append('t.id IN (SELECT task_id FROM task_tags WHERE tag=?)'); values.append(request.args['tag'])
    if request.args.get('q'):
        clauses.append('(t.title LIKE ? OR t.description LIKE ?)'); values.extend(['%' + request.args['q'] + '%'] * 2)
    where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    with connect(database()) as db:
        total = db.execute('SELECT COUNT(*) FROM tasks t' + where, values).fetchone()[0]
        ids = [r[0] for r in db.execute('SELECT t.id FROM tasks t' + where + ' ORDER BY t.id DESC LIMIT ? OFFSET ?',
                                      [*values, limit, offset])]
        items = [task(db, task_id) for task_id in ids]
    return ok(dict(items=items, total=total, limit=limit, offset=offset,
                   next_offset=offset + len(items) if offset + len(items) < total else None))


@api.get('/tasks/<int:task_id>')
def task_detail(task_id):
    return ok(detail(task_id))


@api.get('/tasks/<int:task_id>/events')
def events(task_id):
    after = integer(request.args.get('after', '0'), 'after', minimum=0)
    limit = integer(request.args.get('limit', '50'), 'limit', maximum=100)
    with connect(database()) as db:
        task(db, task_id)
        items = [dict(r) for r in db.execute('''SELECT e.*,u.name user_name FROM events e
            JOIN users u ON u.id=e.user_id WHERE task_id=? AND e.id>? ORDER BY e.id LIMIT ?''', (task_id, after, limit + 1))]
    more = len(items) > limit; items = items[:limit]
    return ok(dict(items=items, next_after=items[-1]['id'] if more else None))


@api.post('/tasks')
def publish():
    data = payload()
    fields = ('title', 'description', 'requirements', 'project', 'importance', 'urgency', 'kind')
    values = {key: text(data, key) for key in fields if key in data}
    for key, value in dict(kind='solo', importance='standard', urgency='normal').items():
        values.setdefault(key, value)
    raw_tags = data.get('tags', '')
    if isinstance(raw_tags, list) and all(isinstance(tag, str) for tag in raw_tags):
        raw_tags = ' '.join(raw_tags)
    if not isinstance(raw_tags, str):
        raise InvalidAction('tags 需要是文字或文字数组。')
    values.update(tags=raw_tags, deadline=deadline(data))
    for key in ('assignee', 'team_size'):
        if data.get(key) is not None:
            values[key] = str(integer(data[key], key))
    selected = data.get('members', [])
    if not isinstance(selected, list):
        raise InvalidAction('members 需要是成员编号数组。')
    values['members'] = [integer(uid, 'members') for uid in selected]
    if 'join_self' in data and not isinstance(data['join_self'], bool):
        raise InvalidAction('join_self 需要是 true 或 false。')
    values['join_self'] = '1' if data.get('join_self') else ''
    task_id = create_task(database(), g.user['id'], values, timezone.utc)
    return ok(detail(task_id), 201)


@api.post('/tasks/<int:task_id>/actions')
def action(task_id):
    data = payload(); name = text(data, 'action')
    if name not in ACTIONS:
        raise InvalidAction('action 无效。')
    credit = data.get('credit')
    if credit is not None:
        if not isinstance(credit, list):
            raise InvalidAction('credit 需要是成员编号数组。')
        credit = [integer(uid, 'credit') for uid in credit]
    act(database(), task_id, g.user['id'], name, text(data, 'body'), credit)
    return ok(detail(task_id))


@api.post('/tasks/<int:task_id>/extensions/<move>')
def extension(task_id, move):
    data = payload(); note = text(data, 'body')
    if move == 'ask':
        extend.ask(database(), task_id, g.user['id'], deadline(data), note, timezone.utc)
    elif move == 'push':
        extend.push(database(), task_id, g.user['id'], deadline(data), note, timezone.utc)
    elif move in ('approve', 'reject'):
        extend.decide(database(), task_id, g.user['id'], move == 'approve', note)
    else:
        abort(404, description='延期操作不存在。')
    return ok(detail(task_id))


@api.post('/tasks/<int:task_id>/pieces')
def split(task_id):
    data = payload()
    values = {key: text(data, key) for key in ('title', 'note', 'tag', 'kind')}
    values['deadline'] = deadline(data, optional=True)
    piece_id = teams.split(database(), task_id, g.user['id'], values, timezone.utc)
    return ok(detail(piece_id), 201)


@api.post('/tasks/<int:task_id>/clap')
def applaud(task_id):
    return ok(dict(claps=clap(database(), task_id, g.user['id'])))


def install(app):
    cli_auth.install(app)
    app.register_blueprint(api)
