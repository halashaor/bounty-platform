"""Read-only queries behind the discovery page, the team feed and "my tasks"."""
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from .honors import MEDALS, medal_key
from .service import is_cold, now, waited_days
from .teams import JOINABLE


def _parse(value):
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def open_tasks(db, user_id):
    """What this user could take on right now: unclaimed small tasks, and big tasks that still have room for them."""
    return db.execute(f'''SELECT t.*,u.name owner_name,p.title big_title,
            (SELECT COUNT(*) FROM task_members m WHERE m.task_id=t.id) people
        FROM tasks t JOIN users u ON u.id=t.owner_id LEFT JOIN tasks p ON p.id=t.parent_id
        WHERE {JOINABLE} AND t.owner_id<>? AND t.deadline>?
          AND NOT EXISTS(SELECT 1 FROM task_members m WHERE m.task_id=t.id AND m.user_id=?)
        ORDER BY t.deadline,t.id''', (user_id, now(), user_id)).fetchall()


def earned_keys(db, user_id):
    return {row['medal_key'] for row in db.execute('SELECT medal_key FROM honors WHERE user_id=?', (user_id,))}


def tags_by_task(db, task_ids=None):
    """Tags per task in their original order. The whole table is small, so read it once and filter here."""
    wanted = None if task_ids is None else set(task_ids)
    tags = defaultdict(list)
    for row in db.execute('SELECT task_id,tag FROM task_tags ORDER BY rowid'):
        if wanted is None or row['task_id'] in wanted:
            tags[row['task_id']].append(row['tag'])
    return tags


def _grams(text):
    """Character bigrams: good enough to tell "造数据" tasks from "讲图论" tasks without any word list or model."""
    chars = [c for c in (text or '').lower() if c.isalnum()]
    return Counter(a + b for a, b in zip(chars, chars[1:]))


def _cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(value * b.get(gram, 0) for gram, value in a.items())
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def profile(db, user_id):
    """What this person tends to pick up. History (tags, projects, wording) and the directions they picked stay
    apart, so the home page can show one lane for each; dismissals lower both."""
    current = datetime.now(timezone.utc)
    history = db.execute('''SELECT t.id,t.title,t.description,t.project,h.awarded_at at,1.0 base FROM honors h
        JOIN tasks t ON t.id=h.task_id WHERE h.user_id=?
        UNION ALL SELECT t.id,t.title,t.description,t.project,t.created_at,0.5 FROM tasks t
        WHERE (t.assignee_id=? OR t.id IN (SELECT task_id FROM task_members WHERE user_id=?)) AND t.status IN ('active','review')''',
                         (user_id, user_id, user_id)).fetchall()
    tags_of = tags_by_task(db, [row['id'] for row in history])
    tag_weight, project_weight, tag_count, done_texts = Counter(), Counter(), Counter(), []
    for row in history:
        # 越近的经历越算数：两个月前做的任务权重减半
        weight = row['base'] * 0.5 ** ((current - _parse(row['at'])).days / 60)
        for tag in tags_of[row['id']]:
            tag_weight[tag] += weight
            tag_count[tag] += row['base'] == 1.0
        if row['project']:
            project_weight[row['project']] += weight
        if row['base'] == 1.0:
            done_texts.append((row['title'], _grams(row['title'] + row['description'])))
    interests = [row['tag'] for row in db.execute('SELECT tag FROM interests WHERE user_id=?', (user_id,))]
    dismissed = {row['task_id'] for row in db.execute('SELECT task_id FROM dismissals WHERE user_id=?', (user_id,))}
    for tags in tags_by_task(db, list(dismissed)).values():
        for tag in tags:
            tag_weight[tag] -= 0.7
    texts = Counter()
    for _, grams in done_texts:
        texts.update(grams)
    bigs = {row['task_id'] for row in db.execute('SELECT task_id FROM task_members WHERE user_id=?', (user_id,))}
    return dict(tags=tag_weight, tag_count=tag_count, projects=project_weight, interests=set(interests), bigs=bigs,
                dismissed=dismissed, done_texts=done_texts, text=texts, earned=earned_keys(db, user_id))


def recommend(db, user_id, limit=3, batch=0, lane='all', exclude=()):
    """Score every claimable task for one person and say why. Nothing is hard-coded per task or per category:
    new projects, tags and kinds of work join in automatically through their tags, project and wording.

    lane='want'  only tasks in the directions this person picked (re-pickable any time on the home page);
    lane='past'  only their own history: tags they finished, projects they joined, tasks worded like theirs;
                 with no history yet it falls back to easy starters and new medals;
    lane='all'   both, used to explain a single task."""
    me = profile(db, user_id)
    current = datetime.now(timezone.utc)
    tasks = [task for task in open_tasks(db, user_id) if task['id'] not in me['dismissed'] and task['id'] not in exclude]
    tags_of = tags_by_task(db, [task['id'] for task in tasks])
    project_start = {row['project']: row['first'] for row in db.execute(
        'SELECT project,MIN(created_at) first FROM tasks WHERE project IS NOT NULL GROUP BY project')}
    newcomer = len(me['done_texts']) < 3
    ranked = []
    for task in tasks:
        key, tags, reasons = medal_key(task), tags_of[task['id']], []
        score, personal = 0.0, False
        # 1) 这次选的方向：命中越多越靠前
        if lane in ('want', 'all'):
            wanted = [tag for tag in tags if tag in me['interests']]
            if wanted:
                score += min(len(wanted), 2) * 2
                personal = True
                reasons.append((3, 'interest', f'你选了「{wanted[0]}」' + (f'和「{wanted[1]}」' if len(wanted) > 1 else '')))
            elif lane == 'want':
                continue
        if lane in ('past', 'all'):
            # 2) 标签：你做过、正在做的
            tag_score = sum(max(me['tags'][tag], 0) for tag in tags)
            if tag_score:
                score += min(tag_score, 3)
                best = max(tags, key=lambda tag: me['tags'][tag])
                if me['tag_count'][best]:
                    personal = True
                    reasons.append((min(tag_score, 3), 'skill', f'你做过 {me["tag_count"][best]} 个「{best}」任务'))
            # 3) 项目：你参与过的项目
            if task['project'] and me['projects'][task['project']]:
                score += min(me['projects'][task['project']], 2) * 0.8
                personal = True
                reasons.append((1.5, 'project', f'你参与过「{task["project"]}」'))
            # 4) 文字相似：和你做过的任务说的是同一类事
            grams = _grams(task['title'] + task['description'])
            similarity = _cosine(grams, me['text'])
            if similarity > 0.12:
                score += similarity * 3
                personal = True
                closest = max(me['done_texts'], key=lambda item: _cosine(grams, item[1]))[0]
                reasons.append((similarity * 3, 'similar', f'和你做过的「{closest}」很像'))
            # 4b) 你在做的大任务里拆出来的分工
            if task['parent_id'] in me['bigs']:
                score += 2
                personal = True
                reasons.append((2.5, 'crew', f'你在「{task["big_title"]}」里'))
        # 5) 人人都成立的：大任务、新项目、勋章、时机
        if task['kind'] == 'team':
            score += 0.6
            reasons.append((1.1, 'team', team_text(task)))
        elif task['parent_id'] and task['parent_id'] not in me['bigs']:
            score += 0.6
            reasons.append((1.1, 'big', f'大任务「{task["big_title"]}」拆出来的一份'))
        if task['project'] and not me['projects'][task['project']] \
                and current - _parse(project_start[task['project']]) < timedelta(days=7):
            score += 0.8
            reasons.append((0.8, 'new-project', f'新项目「{task["project"]}」'))
        if key not in me['earned']:
            score += 2
            reasons.append((2, 'unlock', '拿到你的第一枚勋章' if not me['earned'] else f'能解锁「{MEDALS[key]["name"]}」'))
        if task['urgency'] == 'urgent':
            score += 1.5
            reasons.append((1.5, 'urgent', '急需人手'))
        # 冷门：等了好几天没人接的，往前放一点，接下它的人经验 +20%
        if is_cold(task):
            score += 1.2
            reasons.append((1.6, 'cold', f'等了 {waited_days(task)} 天没人接 · 经验 +20%'))
        if newcomer and task['importance'] == 'light':
            score += 1
            reasons.append((1, 'quick', '半天能做完，适合先上手'))
        left = _parse(task['deadline']) - current
        if left < timedelta(days=2):
            score += 1
        if current - _parse(task['created_at']) < timedelta(days=2):
            score += 0.3
            reasons.append((0.3, 'fresh', '刚刚发布'))
        reasons.append((0, 'due', due_text(left)))
        # 卡片上先说和"你"有关的理由（选了、做过、参与过、内容像）：它们最能说明为什么是你，而不是人人都成立的那句
        mine = {'skill', 'interest', 'project', 'similar', 'crew'}
        reasons.sort(key=lambda reason: -(reason[0] + (1.5 if reason[1] in mine else 0)))
        # 「按你做过的」里，和你经历有关的任务排在只是"人人都适合"的任务前面
        ranked.append((lane == 'past' and not personal, -score, task['deadline'], task['id'], task,
                       [(kind, text) for _, kind, text in reasons], tags))
    ranked.sort(key=lambda item: item[:4])
    if not ranked:
        return []
    start = (batch * limit) % len(ranked)
    pool = [item[4:] for item in ranked[start:] + ranked[:start]]
    # 三张卡尽量各给一个不同的理由、不同的勋章，读起来才像"按你挑的"而不是同一句话说三遍
    picks, used_reasons, used_keys, taken = [], set(), set(), set()
    for strict in (True, False):
        for task, reasons, tags in pool:
            if task['id'] in taken:
                continue
            # 「按你选的方向」第一句永远是命中的方向，几张卡轮着照顾到每个选了的方向；另外两条路按理由种类轮换
            if lane == 'want':
                fresh = [reason for reason in reasons[:1] if reason[1] not in used_reasons]
            else:
                fresh = [reason for reason in reasons if reason[0] not in used_reasons]
            if strict and (not fresh or medal_key(task) in used_keys):
                continue
            chosen = (fresh or reasons)[0]
            picks.append(dict(task=task, tags=tags, reasons=[chosen] + [reason for reason in reasons if reason != chosen],
                              ranked=reasons))
            used_reasons.add(chosen[1] if lane == 'want' else chosen[0])
            used_keys.add(medal_key(task))
            taken.add(task['id'])
            if len(picks) == limit:
                return picks
    return picks


def team_text(task):
    """How a big task's crew stands, for its recommendation sticker."""
    if task['team_size']:
        return f'大任务 · 还缺 {task["team_size"] - task["people"]} 人'
    return f'大任务 · 已经 {task["people"]} 人在做' if task['people'] else '大任务 · 等第一个人加入'


def due_text(left):
    """Time left, without calendar words: "today" means different days to teammates in different time zones."""
    if left.total_seconds() < 0:
        return '已截止'
    if left.days:
        return f'还有 {left.days} 天截止'
    hours = int(left.total_seconds() // 3600)
    return f'还有 {hours} 小时截止' if hours else '不到 1 小时截止'


def directions(db, chosen=()):
    """What the direction picker offers: the team's own tag list (in the admin's order, with their notes),
    each with how many open tasks carry it and one example."""
    rows = db.execute(f"SELECT id,title FROM tasks t WHERE {JOINABLE} ORDER BY created_at DESC,id DESC").fetchall()
    tags_of = tags_by_task(db, [row['id'] for row in rows])
    count, example = Counter(), {}
    for row in rows:
        for tag in tags_of[row['id']]:
            count[tag] += 1
            example.setdefault(tag, row['title'])
    return [dict(tag=row['name'], note=row['note'], count=count[row['name']], example=example.get(row['name']),
                 chosen=row['name'] in chosen)
            for row in db.execute('SELECT name,note FROM org_tags ORDER BY position,name')]


def past_tags(db, user_id, limit=3):
    """The tags this person has actually finished, most first: the visible basis of the "按你做过的" lane."""
    return [(row['tag'], row['n']) for row in db.execute(
        'SELECT tag,COUNT(*) n FROM honors h JOIN task_tags x ON x.task_id=h.task_id WHERE h.user_id=? '
        'GROUP BY tag ORDER BY n DESC,MAX(h.awarded_at) DESC LIMIT ?', (user_id, limit))]


def team_feed(db, viewer_id, limit=6):
    """Recent completions (with applause) and new tasks, newest first."""
    # 大任务一次发给好几个人：动态里写第一个人，后面「等 N 人」
    done = db.execute('''SELECT 'done' kind,e.created_at at,t.id task_id,t.title,
            (SELECT u.name FROM honors h JOIN users u ON u.id=h.user_id WHERE h.task_id=t.id ORDER BY h.user_id LIMIT 1) who,
            (SELECT COUNT(*) - 1 FROM honors h WHERE h.task_id=t.id) others,
            t.importance || '-' || t.urgency medal_key,
            (SELECT COUNT(*) FROM claps c WHERE c.task_id=t.id) claps,
            EXISTS(SELECT 1 FROM claps c WHERE c.task_id=t.id AND c.user_id=?) clapped,
            EXISTS(SELECT 1 FROM honors h WHERE h.task_id=t.id AND h.user_id=?) mine
        FROM events e JOIN tasks t ON t.id=e.task_id WHERE e.kind='accept' AND t.status='done'
        ORDER BY e.id DESC LIMIT ?''', (viewer_id, viewer_id, limit)).fetchall()
    posted = db.execute('''SELECT 'posted' kind,t.created_at at,t.id task_id,t.title,u.name who,0 others,
            t.importance || '-' || t.urgency medal_key,0 claps,0 clapped,0 mine
        FROM tasks t JOIN users u ON u.id=t.owner_id WHERE t.status='open' ORDER BY t.id DESC LIMIT ?''', (limit,)).fetchall()
    return sorted([dict(row) for row in (*done, *posted)], key=lambda row: row['at'], reverse=True)[:limit]


def week_summary(db, tz=timezone.utc):
    """Team completions this week against last week, plus a per-day histogram, in the viewer's own calendar."""
    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())
    last_monday = monday - timedelta(days=7)
    days = [0] * 7
    this_week = last_week = 0
    since = last_monday.astimezone(timezone.utc).isoformat()   # 库里存的是 UTC 字符串，比较前先换算
    for row in db.execute("SELECT created_at FROM events WHERE kind='accept' AND created_at>=?", (since,)):
        moment = _parse(row['created_at']).astimezone(tz)
        if moment >= monday:
            this_week += 1
            days[(moment.date() - monday.date()).days] += 1
        else:
            last_week += 1
    return dict(count=this_week, previous=last_week, days=days, today=today.weekday())


def person_stats(db, user_id):
    row = db.execute('''SELECT COUNT(*) done, COUNT(DISTINCT NULLIF(t.owner_id,h.user_id)) helped,
            (SELECT COUNT(*) FROM claps c JOIN honors h2 ON h2.task_id=c.task_id WHERE h2.user_id=?) claps,
            (SELECT COUNT(*) FROM tasks WHERE owner_id=?) posted
        FROM honors h JOIN tasks t ON t.id=h.task_id WHERE h.user_id=?''', (user_id, user_id, user_id)).fetchone()
    return dict(row)


def my_tasks(db, user_id):
    """Group a person's tasks by whose move it is, newest activity first."""
    rows = db.execute('''SELECT t.*,u.name owner_name,a.name assignee_name,b.title big_title,b.owner_id big_owner,
            EXISTS(SELECT 1 FROM extensions x WHERE x.task_id=t.id AND x.status='pending') asks_extend,
            EXISTS(SELECT 1 FROM task_members m WHERE m.task_id=t.id AND m.user_id=:me) member,
            (SELECT COUNT(*) FROM task_members m WHERE m.task_id=t.id) people,
            (SELECT kind FROM events e WHERE e.task_id=t.id AND e.kind IN ('claim','submit','return','accept') ORDER BY e.id DESC LIMIT 1) state_kind,
            (SELECT body FROM events e WHERE e.task_id=t.id AND e.kind='return' ORDER BY e.id DESC LIMIT 1) return_reason,
            (SELECT kind FROM events e WHERE e.task_id=t.id ORDER BY e.id DESC LIMIT 1) last_kind,
            (SELECT body FROM events e WHERE e.task_id=t.id ORDER BY e.id DESC LIMIT 1) last_body,
            (SELECT x.name FROM events e JOIN users x ON x.id=e.user_id WHERE e.task_id=t.id ORDER BY e.id DESC LIMIT 1) last_name,
            (SELECT created_at FROM events e WHERE e.task_id=t.id ORDER BY e.id DESC LIMIT 1) last_at
        FROM tasks t JOIN users u ON u.id=t.owner_id LEFT JOIN users a ON a.id=t.assignee_id LEFT JOIN tasks b ON b.id=t.parent_id
        WHERE t.owner_id=:me OR t.assignee_id=:me OR member OR (t.status='review' AND b.owner_id=:me AND b.status<>'done')
            OR (t.kind='solo' AND t.status='active' AND asks_extend AND t.assignee_id<>:me AND b.owner_id=:me)
        ORDER BY COALESCE(last_at,t.created_at) DESC,t.id DESC''', dict(me=user_id)).fetchall()
    groups = {'yours': [], 'waiting': [], 'unclaimed': [], 'done': []}
    for task in rows:
        team = task['kind'] == 'team'
        mine_to_do = task['status'] == 'active' and (task['member'] if team else task['assignee_id'] == user_id)
        # 大任务由发布者验收；从大任务里拆出来的分工，大任务的发布者也能验收
        mine_to_check = task['status'] == 'review' and (task['owner_id'] == user_id if team else
                                                        task['assignee_id'] != user_id and user_id in (task['owner_id'], task['big_owner']))
        mine_to_reply = task['status'] == 'active' and task['asks_extend'] and (task['owner_id'] == user_id if team else
                            task['assignee_id'] != user_id and user_id in (task['owner_id'], task['big_owner']))
        if mine_to_do or mine_to_check or mine_to_reply:
            groups['yours'].append(task)
        elif task['status'] in ('active', 'review'):
            groups['waiting'].append(task)
        elif task['status'] == 'open':
            groups['unclaimed'].append(task)
        else:
            groups['done'].append(task)
    groups['done'] = groups['done'][:10]
    return groups
