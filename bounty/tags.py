"""团队的标签表：一个组织自己定"我们做的都是什么"。团队成员维护（加、写说明、排序、改名或合并、删除），
发布者发任务时从表里挑，表里没有的也可以写一个新的，它会自动加进来，之后团队成员可以整理。
大家选「想做的方向」时只能从这张表里点，不用自己想该输入什么。"""
from .db import connect
from .service import InvalidAction, now, parse_tags

NOTE_LIMIT = 40


def listing(db):
    """The team's tags in the admin's order, with a note and how much each is used."""
    return [dict(row) for row in db.execute('''SELECT o.name,o.note,o.position,
            (SELECT COUNT(*) FROM task_tags x JOIN tasks t ON t.id=x.task_id WHERE x.tag=o.name AND t.status='open') open,
            (SELECT COUNT(*) FROM task_tags x WHERE x.tag=o.name) used,
            (SELECT COUNT(*) FROM interests i WHERE i.tag=o.name) fans
        FROM org_tags o ORDER BY o.position,o.name''')]


def names(db):
    return [row['name'] for row in db.execute('SELECT name FROM org_tags ORDER BY position,name')]


def _member(db, user_id):
    if not db.execute('SELECT 1 FROM users WHERE id=?', (user_id,)).fetchone():
        raise InvalidAction('请先登录。')


def _one(raw):
    tags = parse_tags(raw, 1, '标签')
    if not tags:
        raise InvalidAction('标签名不能为空。')
    return tags[0]


def _note(raw):
    note = (raw or '').strip()
    if len(note) > NOTE_LIMIT:
        raise InvalidAction(f'说明不能超过 {NOTE_LIMIT} 个字。')
    return note


def add(path, user_id, name, note=''):
    with connect(path, write=True) as db:
        _member(db, user_id)
        name, note = _one(name), _note(note)
        if db.execute('SELECT 1 FROM org_tags WHERE name=?', (name,)).fetchone():
            raise InvalidAction(f'「{name}」已经在表里了。')
        position = db.execute('SELECT COALESCE(MAX(position),0) FROM org_tags').fetchone()[0] + 1
        db.execute('INSERT INTO org_tags (name,note,position,created_by,created_at) VALUES (?,?,?,?,?)',
                   (name, note, position, user_id, now()))
        return name


def update(path, user_id, name, note='', rename=''):
    """Change the note; a new name renames the tag everywhere, or merges it into an existing one."""
    with connect(path, write=True) as db:
        _member(db, user_id)
        if not db.execute('SELECT 1 FROM org_tags WHERE name=?', (name,)).fetchone():
            raise InvalidAction('这个标签不在表里。')
        note = _note(note)
        target = _one(rename) if rename.strip() else name
        db.execute('UPDATE org_tags SET note=? WHERE name=?', (note, name))
        if target == name:
            return name, False
        merged = bool(db.execute('SELECT 1 FROM org_tags WHERE name=?', (target,)).fetchone())
        for table, key in (('task_tags', 'task_id'), ('interests', 'user_id')):
            db.execute(f'UPDATE OR IGNORE {table} SET tag=? WHERE tag=?', (target, name))
            db.execute(f'DELETE FROM {table} WHERE tag=?', (name,))   # 合并时两边都有的，留一份
        db.execute('UPDATE tasks SET category=? WHERE category=?', (target, name))
        if merged:
            db.execute("UPDATE org_tags SET note=CASE WHEN note='' THEN ? ELSE note END WHERE name=?", (note, target))
            db.execute('DELETE FROM org_tags WHERE name=?', (name,))
        else:
            db.execute('UPDATE org_tags SET name=? WHERE name=?', (target, name))
        return target, merged


def move(path, user_id, name, step):
    """Swap with the neighbour above (step -1) or below (step 1)."""
    with connect(path, write=True) as db:
        _member(db, user_id)
        order = names(db)
        if name not in order:
            raise InvalidAction('这个标签不在表里。')
        i = order.index(name)
        j = i + (1 if step > 0 else -1)
        if 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
            db.executemany('UPDATE org_tags SET position=? WHERE name=?', [(k + 1, tag) for k, tag in enumerate(order)])


def remove(path, user_id, name):
    """Take a tag off the list. Tasks that already carry it keep it (it is history); nobody can pick it as a direction any more."""
    with connect(path, write=True) as db:
        _member(db, user_id)
        if not db.execute('DELETE FROM org_tags WHERE name=?', (name,)).rowcount:
            raise InvalidAction('这个标签不在表里。')
        db.execute('DELETE FROM interests WHERE tag=?', (name,))
