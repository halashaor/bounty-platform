"""任务延期：做的人在进行中申请，验收人回复；验收人也能给待认领、进行中的任务直接延期。
分工由发布者或大任务发布者回复，不能自己回复自己的申请。大任务发布者自己也一起做时，直接延期。
每个任务同时只留一个待回复申请；直接延期、提交成果或验收通过时关掉它，延期不改勋章、经验和分工的截止时间。"""
from .db import connect
from .service import InvalidAction, now, parse_deadline

NOTE_LIMIT = 200


def checker(db, task, user_id):
    if task['kind'] == 'team':
        return task['owner_id'] == user_id
    if task['assignee_id'] == user_id:
        return False
    return task['owner_id'] == user_id or bool(task['parent_id'] and db.execute(
        "SELECT 1 FROM tasks WHERE id=? AND kind='team' AND owner_id=?", (task['parent_id'], user_id)).fetchone())


def _task(db, task_id):
    task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
    if not task:
        raise InvalidAction('任务不存在。')
    return task


def _note(raw, required=False):
    text = (raw or '').strip()
    if required and not text:
        raise InvalidAction('说一句为什么要延期。')
    if len(text) > NOTE_LIMIT:
        raise InvalidAction(f'延期的理由或回复不能超过 {NOTE_LIMIT} 字。')
    return text


def _deadline(task, raw, tz):
    try:
        deadline = parse_deadline(raw, tz)
    except InvalidAction:
        raise InvalidAction('新的截止时间要比现在的晚。')
    if deadline <= task['deadline']:
        raise InvalidAction('新的截止时间要比现在的晚。')
    return deadline


def _event(db, task_id, user_id, kind, body):
    db.execute('INSERT INTO events (task_id,user_id,kind,body,created_at) VALUES (?,?,?,?,?)',
               (task_id, user_id, kind, body, now()))


def ask(path, task_id, user_id, raw_deadline, reason, tz):
    reason = _note(reason, required=True)
    with connect(path, write=True) as db:
        task = _task(db, task_id)
        doing = db.execute('SELECT 1 FROM task_members WHERE task_id=? AND user_id=?', (task_id, user_id)).fetchone() \
            if task['kind'] == 'team' else task['assignee_id'] == user_id
        if task['status'] != 'active' or not doing or checker(db, task, user_id):
            raise InvalidAction('只有正在做的人能申请延期，验收人可以直接延期。')
        if pending(db, task_id):
            raise InvalidAction('已经有一个延期申请在等回复了。')
        deadline = _deadline(task, raw_deadline, tz)
        db.execute('''INSERT INTO extensions (task_id,user_id,old_deadline,new_deadline,reason,status,created_at)
            VALUES (?,?,?,?,?,'pending',?)''', (task_id, user_id, task['deadline'], deadline, reason, now()))
        _event(db, task_id, user_id, 'extend_ask', reason)


def decide(path, task_id, user_id, approve: bool, note=''):
    note = _note(note)
    with connect(path, write=True) as db:
        task = _task(db, task_id)
        if task['status'] != 'active' or not checker(db, task, user_id):
            raise InvalidAction('只有验收人能回复进行中任务的延期申请。')
        request = pending(db, task_id)
        if not request:
            raise InvalidAction('没有待回复的延期申请。')
        if approve:
            if request['new_deadline'] <= now():
                raise InvalidAction('申请的时间已经过了，让对方重新申请。')
            if request['new_deadline'] <= task['deadline']:
                raise InvalidAction('新的截止时间要比现在的晚。')
            db.execute('UPDATE tasks SET deadline=? WHERE id=?', (request['new_deadline'], task_id))
        db.execute('UPDATE extensions SET status=?,decided_by=?,decided_at=? WHERE id=?',
                   ('approved' if approve else 'rejected', user_id, now(), request['id']))
        _event(db, task_id, user_id, 'extend' if approve else 'extend_no', note or ('同意延期。' if approve else '这次先不延。'))


def push(path, task_id, user_id, raw_deadline, note, tz):
    note = _note(note)
    with connect(path, write=True) as db:
        task = _task(db, task_id)
        if task['status'] not in ('open', 'active') or not checker(db, task, user_id):
            raise InvalidAction('只有验收人能给待认领或进行中的任务延期。')
        deadline = _deadline(task, raw_deadline, tz)
        db.execute("UPDATE extensions SET status='closed' WHERE task_id=? AND status='pending'", (task_id,))
        db.execute('''INSERT INTO extensions
            (task_id,user_id,old_deadline,new_deadline,reason,status,created_at,decided_by,decided_at)
            VALUES (?,?,?,?,?,'approved',?,?,?)''',
                   (task_id, user_id, task['deadline'], deadline, note, now(), user_id, now()))
        db.execute('UPDATE tasks SET deadline=? WHERE id=?', (deadline, task_id))
        _event(db, task_id, user_id, 'extend', note or '把截止时间往后延了。')


# ---------------- 读 ----------------
def pending(db, task_id):
    return db.execute('''SELECT x.*,u.name FROM extensions x JOIN users u ON u.id=x.user_id
        WHERE x.task_id=? AND x.status='pending' ORDER BY x.id LIMIT 1''', (task_id,)).fetchone()


def approved(db, task_id):
    return db.execute("SELECT * FROM extensions WHERE task_id=? AND status='approved' ORDER BY id", (task_id,)).fetchall()
