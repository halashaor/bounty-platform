"""耻辱柱：任务发布者（及所属大任务发布者）可按「逾期 / 未达到交付标准 / 其他」把接了任务的人钉上耻辱柱，
仅选「其他」时需要写明理由；钉上后随时可以拔出。所有登录成员在任务详情页和独立的「耻辱柱」页面都能看到动效并可互动抽鞭计数。"""
from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from .db import connect
from .service import InvalidAction, now

REASON_LIMIT = 200
SHAME_KINDS = {
    'overdue': '逾期',
    'rejected': '未达到交付标准',
    'other': '其他',
}
SHAME_DEFAULTS = {
    'overdue': '超过约定截止时间，未按期完成交付',
    'rejected': '提交成果未达到任务交付标准',
    'other': '',
}
_KIND_ALIASES = {'substandard': 'rejected'}


def can_manage(db, task, user_id):
    """任务发布者，或分工所属大任务的发布者，可以钉人或拔出。"""
    if task['owner_id'] == user_id:
        return True
    if task['parent_id']:
        parent = db.execute("SELECT owner_id FROM tasks WHERE id=? AND kind='team'", (task['parent_id'],)).fetchone()
        if parent and parent['owner_id'] == user_id:
            return True
    return False


def _task(db, task_id):
    task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
    if not task:
        raise InvalidAction('任务不存在。')
    return task


def _reason(raw, required=False):
    text = (raw or '').strip()
    if required and not text:
        raise InvalidAction('选择「其他」时请写明钉上耻辱柱的理由。')
    if len(text) > REASON_LIMIT:
        raise InvalidAction(f'理由或说明不能超过 {REASON_LIMIT} 字。')
    return text


def _task_workers(db, task):
    """当前任务中所有接了任务的人（兼容 task_members 与旧 assignee_id）。"""
    rows = db.execute('''SELECT u.id,u.name FROM task_members m JOIN users u ON u.id=m.user_id
        WHERE m.task_id=? ORDER BY m.joined_at,u.id''', (task['id'],)).fetchall()
    people = [dict(row) for row in rows]
    seen = {person['id'] for person in people}
    if task['assignee_id'] and task['assignee_id'] not in seen:
        row = db.execute('SELECT id,name FROM users WHERE id=?', (task['assignee_id'],)).fetchone()
        if row:
            people.append(dict(row))
    return people


def default_kind(db, task):
    if task['deadline'] <= now() and task['status'] != 'done':
        return 'overdue'
    if db.execute("SELECT 1 FROM events WHERE task_id=? AND kind='return' LIMIT 1", (task['id'],)).fetchone():
        return 'rejected'
    return 'overdue'


def candidates(db, task, actor_id):
    """这个任务里目前还能被钉上耻辱柱的成员（不含操作者本人和已经在柱上的人）。"""
    active_ids = {row[0] for row in db.execute(
        "SELECT user_id FROM shame_pins WHERE task_id=? AND status='active'", (task['id'],))}
    return [person for person in _task_workers(db, task)
            if person['id'] != actor_id and person['id'] not in active_ids]


def pin(path, task_id, actor_id, target_user_id, reason='', kind='overdue'):
    kind = _KIND_ALIASES.get(kind, kind)
    if kind not in SHAME_KINDS:
        raise InvalidAction('请选择有效的上柱类型。')
    reason = _reason(reason, required=(kind == 'other'))
    if kind != 'other':
        reason = ''
    try:
        uid = int(target_user_id)
    except (TypeError, ValueError):
        raise InvalidAction('请选择要钉上耻辱柱的人。')
    with connect(path, write=True) as db:
        task = _task(db, task_id)
        if not can_manage(db, task, actor_id):
            raise InvalidAction('只有任务发布者才能把人钉上耻辱柱。')
        if uid == actor_id:
            raise InvalidAction('不能把自己钉上耻辱柱。')
        workers = {person['id']: person['name'] for person in _task_workers(db, task)}
        if uid not in workers:
            raise InvalidAction('只能钉接了这个任务的人。')
        if db.execute("SELECT 1 FROM shame_pins WHERE task_id=? AND user_id=? AND status='active'",
                      (task_id, uid)).fetchone():
            raise InvalidAction(f'{workers[uid]} 已经在这个任务的耻辱柱上了。')
        ts = now()
        pin_id = db.execute('''INSERT INTO shame_pins (task_id,user_id,pinned_by,kind,reason,status,lashes,created_at)
            VALUES (?,?,?,?,?,'active',0,?)''', (task_id, uid, actor_id, kind, reason, ts)).lastrowid
        label = SHAME_KINDS[kind]
        body = f'把 {workers[uid]} 钉上了耻辱柱（{label}）：{reason}' if reason else f'把 {workers[uid]} 钉上了耻辱柱（{label}）。'
        db.execute('INSERT INTO events (task_id,user_id,kind,body,created_at) VALUES (?,?,?,?,?)',
                   (task_id, actor_id, 'shame_pin', body, ts))
        return pin_id


def lift(path, pin_id, actor_id, note=''):
    note = _reason(note, required=False)
    with connect(path, write=True) as db:
        row = db.execute('''SELECT s.*,u.name target_name FROM shame_pins s JOIN users u ON u.id=s.user_id
            WHERE s.id=?''', (pin_id,)).fetchone()
        if not row:
            raise InvalidAction('这条耻辱柱记录不存在。')
        if row['status'] != 'active':
            raise InvalidAction('钉子已经拔出来了。')
        task = _task(db, row['task_id'])
        if not can_manage(db, task, actor_id) and row['pinned_by'] != actor_id:
            raise InvalidAction('只有任务发布者才能拔出钉子。')
        ts = now()
        db.execute("UPDATE shame_pins SET status='lifted',lifted_by=?,lifted_at=?,lift_note=? WHERE id=?",
                   (actor_id, ts, note, pin_id))
        body = f'把 {row["target_name"]} 从耻辱柱上拔了出来。' + (f' {note}' if note else '')
        db.execute('INSERT INTO events (task_id,user_id,kind,body,created_at) VALUES (?,?,?,?,?)',
                   (row['task_id'], actor_id, 'shame_unpin', body, ts))
        return row['task_id'], row['target_name']


def lash(path, pin_id):
    with connect(path, write=True) as db:
        row = db.execute("SELECT id,status FROM shame_pins WHERE id=?", (pin_id,)).fetchone()
        if not row or row['status'] != 'active':
            raise InvalidAction('这条记录已经不在耻辱柱上了。')
        db.execute("UPDATE shame_pins SET lashes=lashes+1 WHERE id=? AND status='active'", (pin_id,))
        return db.execute('SELECT lashes FROM shame_pins WHERE id=?', (pin_id,)).fetchone()[0]


# ---------------- 读 ----------------
_PIN_SELECT = '''SELECT s.*,
        u.name user_name,
        p.name pinned_by_name,
        l.name lifted_by_name,
        t.title task_title,
        t.owner_id task_owner_id,
        t.parent_id task_parent_id,
        (SELECT owner_id FROM tasks pt WHERE pt.id=t.parent_id AND pt.kind='team') parent_owner_id
    FROM shame_pins s
    JOIN users u ON u.id=s.user_id
    JOIN users p ON p.id=s.pinned_by
    LEFT JOIN users l ON l.id=s.lifted_by
    JOIN tasks t ON t.id=s.task_id'''


def _decorate(rows, viewer_id=None):
    items = []
    for row in rows:
        item = dict(row)
        item['kind_label'] = SHAME_KINDS.get(item['kind'], '其他')
        raw_reason = (item['reason'] or '').strip()
        item['display_reason'] = raw_reason or SHAME_DEFAULTS.get(item['kind'], '') or '另有违约事由'
        item['has_custom_reason'] = bool(raw_reason)
        item['can_lift'] = bool(viewer_id) and (
            item['pinned_by'] == viewer_id
            or item['task_owner_id'] == viewer_id
            or item['parent_owner_id'] == viewer_id
        )
        items.append(item)
    return items


def active_for_task(db, task_id, viewer_id=None):
    rows = db.execute(_PIN_SELECT + " WHERE s.task_id=? AND s.status='active' ORDER BY s.id DESC",
                      (task_id,)).fetchall()
    return _decorate(rows, viewer_id)


def active_all(db, viewer_id=None):
    rows = db.execute(_PIN_SELECT + " WHERE s.status='active' ORDER BY s.id DESC").fetchall()
    return _decorate(rows, viewer_id)


def recent_lifted(db, limit=20):
    rows = db.execute(_PIN_SELECT + " WHERE s.status='lifted' ORDER BY s.lifted_at DESC,s.id DESC LIMIT ?",
                      (limit,)).fetchall()
    return _decorate(rows)


def active_count(db):
    return db.execute("SELECT COUNT(*) FROM shame_pins WHERE status='active'").fetchone()[0]


def latest_active(db):
    """最新一个还在柱上的编号。「大家」的小点只在有人新上柱、这台设备还没看过耻辱柱页时亮，不是有人在柱上就一直亮。"""
    return db.execute("SELECT COALESCE(MAX(id),0) FROM shame_pins WHERE status='active'").fetchone()[0]


def _safe_next(raw, fallback):
    if raw and raw.startswith('/') and not raw.startswith('//'):
        return raw
    return fallback


def install(app):
    path = app.config['DATABASE']
    page = Blueprint('shame', __name__)

    @app.context_processor
    def shame_badge():
        if not g.get('user'):
            return dict(shame_latest=0, shame_kinds=SHAME_KINDS)
        with connect(path) as db:
            return dict(shame_latest=latest_active(db), shame_kinds=SHAME_KINDS)

    @page.before_request
    def signed_in():
        if not g.get('user'):
            if request.accept_mimetypes.best == 'application/json':
                return jsonify(error='请先登录。'), 401
            return redirect(url_for('auth', mode='login'))

    @page.get('/shame')
    def board():
        with connect(path) as db:
            active = active_all(db, g.user['id'])
            lifted = recent_lifted(db, 20)
        return render_template('shame.html', active=active, lifted=lifted)

    @page.post('/tasks/<int:task_id>/shame/pin')
    def pin_task(task_id):
        try:
            pin(path, task_id, g.user['id'], request.form.get('user_id', ''),
                request.form.get('reason', ''), request.form.get('kind', 'overdue'))
            flash('已经钉上耻辱柱，所有人进这个任务页都能看到。', 'success')
        except InvalidAction as error:
            flash(str(error), 'error')
        return redirect(url_for('detail', task_id=task_id) + '#shame')

    @page.post('/shame/<int:pin_id>/lift')
    def lift_pin(pin_id):
        fallback = url_for('shame.board')
        try:
            task_id, target_name = lift(path, pin_id, g.user['id'], request.form.get('note', ''))
            fallback = url_for('detail', task_id=task_id)
            flash(f'已经把 {target_name} 从耻辱柱上拔出来了。', 'success')
        except InvalidAction as error:
            flash(str(error), 'error')
        return redirect(_safe_next(request.form.get('next', ''), fallback))

    @page.post('/shame/<int:pin_id>/lash')
    def lash_pin(pin_id):
        wants_json = request.accept_mimetypes.best == 'application/json' or request.headers.get('X-Requested-With') == 'fetch'
        try:
            count = lash(path, pin_id)
        except InvalidAction as error:
            if wants_json:
                return jsonify(error=str(error)), 400
            flash(str(error), 'error')
            return redirect(_safe_next(request.form.get('next', ''), url_for('shame.board')))
        if wants_json:
            return jsonify(lashes=count)
        return redirect(_safe_next(request.form.get('next', ''), url_for('shame.board')))

    app.register_blueprint(page)
