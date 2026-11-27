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
KINDS = {'claim': '认领任务', 'submit': '提交成果', 'accept': '验收通过', 'return': '退回修改', 'comment': '讨论', 'settle': '历史结算记录',
         'join': '加入', 'leave': '退出', 'split': '拆出分工', 'extend_ask': '申请延期', 'extend': '延期',
         'extend_no': '没同意延期', 'assign': '指定'}
# 谁在做都记在 task_members：小任务谁看到了想做就加入，不限人数；大任务也是加入，可以限人数（在这个范围里），
# 还能拆出分工。一起做的任何一个人都能交，发布者验收时选给谁发勋章
MAX_TEAM = 20


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


def insert_task(db, user_id, title, description, requirements, tags, project, importance, urgency, deadline,
                kind='solo', team_size=None, parent_id=None):
    cursor = db.execute('''INSERT INTO tasks
        (title,description,category,project,importance,urgency,deadline,requirements,owner_id,created_at,kind,team_size,parent_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (title, description, tags[0], project or None, importance, urgency, deadline, requirements, user_id, now(),
         kind, team_size, parent_id))
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
    kind = data.get('kind') or 'solo'
    if kind not in ('solo', 'team'):
        raise InvalidAction('请选择小任务或大任务。')
    team_size = None
    raw = str(data.get('team_size') or '').strip()
    if kind == 'team' and raw:   # 小任务不限人数，传了也不用
        if not raw.isdigit() or not 2 <= int(raw) <= MAX_TEAM:
            raise InvalidAction(f'大任务想要的人数在 2 到 {MAX_TEAM} 之间，或者不限。')
        team_size = int(raw)
    with connect(path, write=True) as db:
        # 指定谁来做：members 可以多选；小任务也接受旧脚本只传一个 assignee
        picked = list(data.get('members') or [])
        if kind == 'solo' and data.get('assignee'):
            picked.append(data['assignee'])
        people = []
        for raw in picked:
            try:
                uid = int(raw)
            except (TypeError, ValueError):
                raise InvalidAction('指定的人不存在。')
            if not 0 < uid < 2 ** 63:
                raise InvalidAction('指定的人不存在。')
            if uid == user_id:
                raise InvalidAction('不能指定自己，想一起做就勾「我也一起做」。')
            person = db.execute('SELECT id,name FROM users WHERE id=?', (uid,)).fetchone()
            if not person:
                raise InvalidAction('指定的人不存在。')
            if uid not in [person['id'] for person in people]:
                people.append(person)
        if team_size and len(people) + bool(data.get('join_self')) > team_size:
            raise InvalidAction('指定的人比想要的人数还多。')
        task_id = insert_task(db, user_id, title, description, requirements, tags, project, importance, urgency, deadline,
                              kind, team_size)
        if data.get('join_self'):   # 发布者自己也一起做
            _join(db, db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone(), user_id)
            db.execute('INSERT INTO events (task_id,user_id,kind,body,created_at) VALUES (?,?,?,?,?)',
                       (task_id, user_id, 'join', '我也一起做。', now()))
        if people:
            for person in people:
                _join(db, db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone(), person['id'])
            if kind == 'solo' and len(people) == 1:
                body = f'指定 {people[0]["name"]} 来做。'
            else:
                body = '指定 ' + '、'.join(person['name'] for person in people) + ' 一起做。'
            db.execute('INSERT INTO events (task_id,user_id,kind,body,created_at) VALUES (?,?,?,?,?)',
                       (task_id, user_id, 'assign', body, now()))
        return task_id


def members_of(db, task_id):
    return [row[0] for row in db.execute('SELECT user_id FROM task_members WHERE task_id=? ORDER BY joined_at,user_id', (task_id,))]


def _join(db, task, user_id):
    """Add someone to a task; the first person in starts it (and fixes whether it counts as a cold task)."""
    db.execute('INSERT OR IGNORE INTO task_members (task_id,user_id,joined_at) VALUES (?,?,?)', (task['id'], user_id, now()))
    if task['status'] == 'open':
        db.execute("UPDATE tasks SET status='active', cold=? WHERE id=?", (int(waited_days(task) >= COLD_DAYS), task['id']))


def act(path, task_id, user_id, action, body='', credit=None):
    """One step of a task: people join (or leave) → anyone in it submits → the publisher accepts, choosing who gets
    the medal (credit: user ids, default everyone in it), or returns it. A small task has no seat limit and claiming
    it is joining it; a big task may cap its seats. A share split off a big task is checked by whoever split it or by
    the big task's publisher, and joining it also joins the big task."""
    body = body.strip()
    if len(body) > 10000:
        raise InvalidAction('内容不能超过 10000 字。')
    with connect(path, write=True) as db:
        task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not task:
            raise InvalidAction('任务不存在。')
        owner = task['owner_id'] == user_id
        status = task['status']
        team = task['kind'] == 'team'
        members = members_of(db, task_id)
        # 从大任务里拆出来的分工：大任务的发布者也能验收
        parent = db.execute('SELECT * FROM tasks WHERE id=?', (task['parent_id'],)).fetchone() if task['parent_id'] else None
        lead = bool(parent) and parent['owner_id'] == user_id
        if action == 'claim':   # 旧的「认领」：小任务就是加入
            if team:
                raise InvalidAction('大任务是好几个人一起做的，点「加入」。')
            action = 'join'
        if action == 'join':
            if user_id in members:
                raise InvalidAction('你已经在里面了。')
            if parent and parent['status'] == 'done':
                raise InvalidAction('大任务已经完成，这份分工不用再做了。')
            if status not in ('open', 'active') or task['deadline'] <= now():
                raise InvalidAction('已经交上去或截止了，不再加人。')
            if task['team_size'] and len(members) >= task['team_size']:
                raise InvalidAction('人已经够了。')
            # 第一个人加入那一刻就定下是不是冷门，之后再怎么退回都不变
            _join(db, task, user_id)
            if parent and parent['status'] in ('open', 'active'):   # 接了大任务的一份分工，也就加入了这个大任务
                _join(db, parent, user_id)
            body = '加入了，一起做。' if members else '接下了，开始做。'
        elif action == 'leave':
            if user_id not in members or status != 'active':
                raise InvalidAction('只有一起做的人能退出；交上去之后就不能退了。')
            db.execute('DELETE FROM task_members WHERE task_id=? AND user_id=?', (task_id, user_id))
            if len(members) == 1:   # 最后一个人也走了：回到没人做的状态
                db.execute("UPDATE tasks SET status='open' WHERE id=?", (task_id,))
            body = '退出了。'
        elif action == 'submit':
            if user_id not in members or status != 'active' or not body:
                raise InvalidAction('只有一起做的人能提交，成果说明不能为空。')
            if db.execute("SELECT 1 FROM tasks WHERE parent_id=? AND status IN ('active','review')", (task_id,)).fetchone():
                raise InvalidAction('还有拆出去的分工在做，等它们交上来再提交。')
            if members == [task['owner_id']] and not (parent and parent['owner_id'] != task['owner_id']):
                raise InvalidAction('只有你自己在做，交上来没人能给你验收；等别人加入再交。')
            db.execute("UPDATE tasks SET status='review' WHERE id=?", (task_id,))
            db.execute("UPDATE extensions SET status='closed' WHERE task_id=? AND status='pending'", (task_id,))
        elif action in ('accept', 'return'):
            if not (owner or lead) or status != 'review':
                raise InvalidAction('仅发布者（或大任务的发布者）可验收待验收的任务。')
            if action == 'return' and not body:
                raise InvalidAction('请填写退回原因。')
            if action == 'accept':
                people = members if credit is None else [uid for uid in members if uid in set(credit)]
                if not people:
                    raise InvalidAction('至少给一个一起做的人发勋章。')
                if set(people) == {user_id}:
                    raise InvalidAction('你自己也在里面时，至少还要发给一个一起做的人。')
                key = medal_key(task)
                bonus = cold_bonus(key) if task['cold'] else 0
                db.executemany('INSERT INTO honors (task_id,user_id,medal_key,awarded_at,bonus) VALUES (?,?,?,?,?)',
                               [(task_id, uid, key, now(), bonus) for uid in people])
                db.execute("UPDATE extensions SET status='closed' WHERE task_id=? AND status='pending'", (task_id,))
            db.execute('UPDATE tasks SET status=? WHERE id=?', ('done' if action == 'accept' else 'active', task_id))
            body = body or '成果验收通过。'
        elif action == 'comment':
            if not body:
                raise InvalidAction('讨论内容不能为空。')
        else:
            raise InvalidAction('未知操作。')
        db.execute('INSERT INTO events (task_id,user_id,kind,body,created_at) VALUES (?,?,?,?,?)',
                   (task_id, user_id, action, body, now()))


def clap(path, task_id, user_id):
    """Teammates applaud a finished task once each; the people who did it cannot applaud themselves."""
    with connect(path, write=True) as db:
        task = db.execute('SELECT status FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not task or task['status'] != 'done':
            raise InvalidAction('只能为已完成的任务鼓掌。')
        if user_id in members_of(db, task_id) or db.execute('SELECT 1 FROM honors WHERE task_id=? AND user_id=?',
                                                             (task_id, user_id)).fetchone():
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
