"""学期绘卷: one page per term that tells a person's term back to them. Terms follow the Chinese university calendar
(春季 Feb–Jul, 秋季 Aug–Jan) on the team clock, so the whole team shares the same boundaries."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from .honors import MEDALS, task_xp
from .progress import level_info
from .service import TEAM_TZ
from .titles import BY_KEY, DEFAULT_PRAISE


def term_of(moment):
    local = moment.astimezone(TEAM_TZ)
    if 2 <= local.month <= 7:
        return f'{local.year}-spring'
    return f'{local.year if local.month >= 8 else local.year - 1}-autumn'


def bounds(term):
    """(start, end) of a term in UTC; None for a malformed key."""
    try:
        year, season = term.split('-')
        year = int(year)
    except ValueError:
        return None
    if season not in ('spring', 'autumn') or not 2000 <= year <= 2100:
        return None
    start = datetime(year, 2 if season == 'spring' else 8, 1, tzinfo=TEAM_TZ)
    end = datetime(year if season == 'spring' else year + 1, 8 if season == 'spring' else 2, 1, tzinfo=TEAM_TZ)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def label(term):
    year, season = term.split('-')
    return f'{year} {"春季" if season == "spring" else "秋季"}学期'


def terms(db, user_id):
    """Every term from this person's first activity until now, newest first."""
    first = db.execute('''SELECT MIN(at) FROM (SELECT awarded_at at FROM honors WHERE user_id=?
        UNION ALL SELECT created_at FROM tasks WHERE owner_id=? OR assignee_id=?)''', (user_id, user_id, user_id)).fetchone()[0]
    current = term_of(datetime.now(timezone.utc))
    if not first:
        return [current]
    found, moment = [], datetime.fromisoformat(first)
    while True:
        term = term_of(moment)
        if term not in found:
            found.append(term)
        if term == current:
            break
        moment = bounds(term)[1] + timedelta(days=1)
    return found[::-1]


def days_left(term):
    return (bounds(term)[1] - datetime.now(timezone.utc)).days


def build(db, user_id, term):
    start, end = bounds(term)
    span = (start.isoformat(), end.isoformat())
    awards = db.execute('''SELECT h.*,t.title,t.project,t.importance,t.urgency,t.kind,t.owner_id,u.name owner,
            (SELECT body FROM events e WHERE e.task_id=h.task_id AND e.kind='accept' ORDER BY e.id DESC LIMIT 1) praise,
            (SELECT COUNT(*) FROM claps c WHERE c.task_id=h.task_id) claps
        FROM honors h JOIN tasks t ON t.id=h.task_id JOIN users u ON u.id=t.owner_id
        WHERE h.user_id=? AND h.awarded_at>=? AND h.awarded_at<? ORDER BY h.awarded_at''', (user_id, *span)).fetchall()
    xp_of = lambda row: task_xp(row['medal_key']) + row['bonus']
    before = sum(xp_of(row) for row in db.execute('SELECT medal_key,bonus FROM honors WHERE user_id=? AND awarded_at<?',
                                                  (user_id, span[0])))
    gained = sum(xp_of(row) for row in awards)
    tags = Counter()
    for row in db.execute('''SELECT x.tag FROM honors h JOIN task_tags x ON x.task_id=h.task_id
            WHERE h.user_id=? AND h.awarded_at>=? AND h.awarded_at<?''', (user_id, *span)):
        tags[row['tag']] += 1
    medals = Counter(row['medal_key'] for row in awards)
    helped = list(dict.fromkeys(row['owner'] for row in awards if row['owner_id'] != user_id))
    praises = [dict(text=row['praise'], by=row['owner'], title=row['title']) for row in awards
               if row['praise'] and row['praise'] != DEFAULT_PRAISE][::-1]
    biggest = max(awards, key=lambda row: (xp_of(row), row['awarded_at']), default=None)
    # 最拼的一周：按团队时区的周一算
    weeks = Counter()
    for row in awards:
        local = datetime.fromisoformat(row['awarded_at']).astimezone(TEAM_TZ)
        weeks[(local - timedelta(days=local.weekday())).date()] += 1
    best_week = max(weeks.items(), key=lambda item: (item[1], item[0]), default=None)
    published = db.execute('''SELECT COUNT(*) FROM tasks t WHERE t.owner_id=? AND t.status='done' AND EXISTS
        (SELECT 1 FROM events e WHERE e.task_id=t.id AND e.kind='accept' AND e.created_at>=? AND e.created_at<?)''',
                           (user_id, *span)).fetchone()[0]
    unlocked = [BY_KEY[row['key']] for row in db.execute(
        'SELECT key FROM titles_seen WHERE user_id=? AND seen_at>=? AND seen_at<? ORDER BY seen_at', (user_id, *span))
        if row['key'] in BY_KEY]
    team = db.execute('''SELECT (SELECT COUNT(*) FROM events e WHERE e.kind='accept' AND e.created_at>=? AND e.created_at<?) done,
        (SELECT COUNT(DISTINCT user_id) FROM honors WHERE awarded_at>=? AND awarded_at<?) people''', span + span).fetchone()
    lines = sum(db.execute(f'SELECT COUNT(*) FROM {table} WHERE user_id=? AND solved_at>=? AND solved_at<?', (user_id, *span)).fetchone()[0]
                for table in ('lines_solved', 'daily_lines'))
    lines += db.execute('SELECT COALESCE(SUM(solved),0) FROM lines_tally WHERE user_id=? AND term=?', (user_id, term)).fetchone()[0]
    stamp = db.execute("""SELECT MAX(score) FROM game_runs WHERE user_id=? AND game='stamp' AND finished_at>=? AND finished_at<?""",
                       (user_id, *span)).fetchone()[0]
    return dict(
        term=term, label=label(term), done=len(awards), gained=gained,
        level_from=level_info(before), level_to=level_info(before + gained),
        medals=[(key, medals[key]) for key in MEDALS if medals[key]], kinds=len(medals),
        helped=helped, tags=tags.most_common(3), praises=praises[:3], claps=sum(row['claps'] for row in awards),
        biggest=dict(title=biggest['title'], key=biggest['medal_key'], owner=biggest['owner'], xp=xp_of(biggest)) if biggest else None,
        best_week=dict(monday=best_week[0], count=best_week[1]) if best_week and best_week[1] > 1 else None,
        published=published, titles=unlocked, bigs=[dict(title=row['title'], lead=row['owner_id'] == user_id) for row in awards if row['kind'] == 'team'], team=dict(team), lines=lines, stamp=stamp or 0,
        first=dict(title=awards[0]['title'], on=awards[0]['awarded_at']) if awards else None,
    )
