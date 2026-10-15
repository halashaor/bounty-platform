import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .db import connect
from .honors import COLD_DAYS, IMPORTANCE, URGENCY, cold_bonus, medal_key

# Suggested starter tags only: teams add their own tags and projects freely, nothing is limited to this list.
CATEGORIES = ('实验', '数据', '论文', '代码', '讲解', '杂务')
MAX_TAGS = 5
MAX_INTERESTS = 8
# 每个人看到的时间按自己浏览器的时区来（见 zone）。团队时区只在两处用到：浏览器没报时区时的兜底，
# 以及全队共用的「本周」从哪天零点算起（每周收集包）。默认北京时间，可用 BOUNTY_TZ_OFFSET 改。
TEAM_TZ = timezone(timedelta(hours=float(os.environ.get('BOUNTY_TZ_OFFSET', '8'))))
STATUSES = {'open': '待认领', 'active': '进行中', 'review': '待验收', 'done': '已完成'}
KINDS = {'claim': '认领任务', 'submit': '提交成果', 'accept': '验收通过', 'return': '退回修改', 'comment': '讨论', 'settle': '历史结算记录'}

class InvalidAction(ValueError):
    pass


def waited_days(task, at=None):
    """How long an open task has gone unclaimed."""
    created = datetime.fromisoformat(task['created_at'])
    created = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
    return ((at or datetime.now(timezone.utc)) - created).days


def is_cold(task):
    """Still open after COLD_DAYS days, or claimed only after that long: worth 20% more experience."""
    return bool(task['cold']) or (task['status'] == 'open' and waited_days(task) >= COLD_DAYS)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def required(data, key, label, limit=10000):
    value = data.get(key, '').strip()
    if not value or len(value) > limit:
        raise InvalidAction(f'{label}不能为空，且不能超过 {limit} 字。')
    return value


def zone(name):
    """A viewer's IANA time zone (as reported by their browser), or the team zone when it is missing or unknown."""
    if name and len(name) <= 64 and re.fullmatch(r'[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+)*', name):
        try:
            return ZoneInfo(name)
        except (KeyError, ValueError, OSError):   # 没有时区数据库（Windows 未装 tzdata）时也退回团队时区
            pass
    return TEAM_TZ


def parse_tags(raw, limit=MAX_TAGS, noun='标签'):
    """Split free-form tags on commas, enumeration marks or spaces; keep order, drop duplicates."""
    tags = []
    for part in re.split(r'[,，、;；\s]+', raw or ''):
        tag = part.strip().lstrip('#')
        if tag and tag not in tags:
            if len(tag) > 16:
                raise InvalidAction(f'每个{noun}不能超过 16 个字。')
            tags.append(tag)
    if len(tags) > limit:
        raise InvalidAction(f'最多 {limit} 个{noun}。')
    return tags


def parse_deadline(raw, tz=None):
    """A future moment as a UTC string; a value typed without an offset is wall-clock time in tz (the team zone by default)."""
    try:
        deadline = datetime.fromisoformat(raw or '')
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=tz or TEAM_TZ)
        deadline = deadline.astimezone(timezone.utc).isoformat(timespec='seconds')
        if deadline <= now():
            raise ValueError()
    except (ValueError, OverflowError):
        raise InvalidAction('请选择一个还没到的截止时间。')
    return deadline


def insert_task(db, user_id, title, description, requirements, tags, project, importance, urgency, deadline, big_id=None):
    cursor = db.execute('''INSERT INTO tasks
        (title,description,category,project,importance,urgency,deadline,requirements,owner_id,created_at,big_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (title, description, tags[0], project or None, importance, urgency, deadline, requirements, user_id, now(), big_id))
    db.executemany('INSERT INTO task_tags (task_id,tag) VALUES (?,?)', [(cursor.lastrowid, tag) for tag in tags])
    # 发布者写了表里没有的标签：加进团队的标签表末尾，之后团队成员可以写说明、合并或删掉
    for tag in tags:
        db.execute('''INSERT OR IGNORE INTO org_tags (name,position,created_by,created_at)
            SELECT ?,COALESCE(MAX(position),0)+1,?,? FROM org_tags''', (tag, user_id, now()))
    return cursor.lastrowid


def create_task(path, user_id, data, tz=None):
    """tz: the publisher's zone; a deadline typed without an offset means their own wall-clock time."""
    title = required(data, 'title', '标题', 120)
    description = required(data, 'description', '任务说明')
    requirements = required(data, 'requirements', '交付要求')
    # Older forms and scripts send a single "category"; it simply becomes the first tag.
    tags = parse_tags(data.get('tags') or data.get('category', ''))
    project = (data.get('project') or '').strip()
    importance = data.get('importance')
    urgency = data.get('urgency')
    if not tags:
        raise InvalidAction('至少写一个标签，方便同学找到这个任务。')
    if len(project) > 30:
        raise InvalidAction('项目名不能超过 30 个字。')
    if importance not in IMPORTANCE or urgency not in URGENCY:
        raise InvalidAction('请选择有效的任务分量和紧急程度。')
    deadline = parse_deadline(data.get('deadline'), tz)
    with connect(path, write=True) as db:
        return insert_task(db, user_id, title, description, requirements, tags, project, importance, urgency, deadline)


def act(path, task_id, user_id, action, body=''):
    body = body.strip()
    if len(body) > 10000:
        raise InvalidAction('内容不能超过 10000 字。')
    with connect(path, write=True) as db:
        task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not task:
            raise InvalidAction('任务不存在。')
        owner = task['owner_id'] == user_id
        assignee = task['assignee_id'] == user_id
        status = task['status']
        # 大任务的分工：牵头人也能验收（除了自己接的那份）
        lead = bool(task['big_id']) and bool(db.execute('SELECT 1 FROM big_tasks WHERE id=? AND owner_id=?',
                                                        (task['big_id'], user_id)).fetchone())
        if action == 'claim':
            if owner or status != 'open' or task['deadline'] <= now():
                raise InvalidAction('无法认领：任务已被认领、已截止，或由你发布。')
            # 认领那一刻就定下是不是冷门，之后再怎么退回都不变
            db.execute("UPDATE tasks SET assignee_id=?, status='active', cold=? WHERE id=?",
                       (user_id, int(waited_days(task) >= COLD_DAYS), task_id))
            if task['big_id']:   # 接了一份分工，就算加入了这个大任务
                db.execute('INSERT OR IGNORE INTO big_members (big_id,user_id,joined_at) VALUES (?,?,?)',
                           (task['big_id'], user_id, now()))
            body = '已认领，开始处理。'
        elif action == 'submit':
            if not assignee or status != 'active' or not body:
                raise InvalidAction('仅认领人可提交进行中的任务，成果说明不能为空。')
            db.execute("UPDATE tasks SET status='review' WHERE id=?", (task_id,))
        elif action in ('accept', 'return'):
            if not (owner or lead) or assignee or status != 'review':
                raise InvalidAction('仅发布者（或大任务的牵头人）可验收待验收的任务。')
            if action == 'return' and not body:
                raise InvalidAction('请填写退回原因。')
            db.execute('UPDATE tasks SET status=? WHERE id=?', ('done' if action == 'accept' else 'active', task_id))
            body = body or '成果验收通过。'
            if action == 'accept':
                key = medal_key(task)
                db.execute('INSERT INTO honors (task_id,user_id,medal_key,awarded_at,bonus) VALUES (?,?,?,?,?)',
                           (task_id, task['assignee_id'], key, now(), cold_bonus(key) if task['cold'] else 0))
        elif action == 'comment':
            if not body:
                raise InvalidAction('讨论内容不能为空。')
        else:
            raise InvalidAction('未知操作。')
        db.execute('INSERT INTO events (task_id,user_id,kind,body,created_at) VALUES (?,?,?,?,?)',
                   (task_id, user_id, action, body, now()))


def clap(path, task_id, user_id):
    """Teammates applaud a finished task once each; the person who did it cannot applaud themselves."""
    with connect(path, write=True) as db:
        task = db.execute('SELECT status,assignee_id FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not task or task['status'] != 'done':
            raise InvalidAction('只能为已完成的任务鼓掌。')
        if task['assignee_id'] == user_id:
            raise InvalidAction('不能给自己鼓掌。')
        db.execute('INSERT OR IGNORE INTO claps (task_id,user_id,created_at) VALUES (?,?,?)', (task_id, user_id, now()))
        return db.execute('SELECT COUNT(*) FROM claps WHERE task_id=?', (task_id,)).fetchone()[0]


def set_interests(path, user_id, raw):
    """What someone wants to work on, picked from the team's tag list (nobody has to guess what to type)."""
    tags = parse_tags(raw, MAX_INTERESTS, '方向')
    with connect(path, write=True) as db:
        known = {row[0] for row in db.execute('SELECT name FROM org_tags')}
        if any(tag not in known for tag in tags):
            raise InvalidAction('只能从团队的标签表里选方向。')
        db.execute('DELETE FROM interests WHERE user_id=?', (user_id,))
        db.executemany('INSERT INTO interests (user_id,tag) VALUES (?,?)', [(user_id, tag) for tag in tags])
    return tags


def dismiss(path, task_id, user_id):
    """"Not for me": hides the task from this person's picks and lowers similar tags a little."""
    with connect(path, write=True) as db:
        if not db.execute('SELECT 1 FROM tasks WHERE id=?', (task_id,)).fetchone():
            raise InvalidAction('任务不存在。')
        db.execute('INSERT OR IGNORE INTO dismissals (user_id,task_id,created_at) VALUES (?,?,?)', (user_id, task_id, now()))
