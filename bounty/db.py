import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

TASK_TABLE = '''CREATE TABLE IF NOT EXISTS tasks (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
 category TEXT NOT NULL,
 importance TEXT NOT NULL CHECK(importance IN ('light','standard','major')),
 urgency TEXT NOT NULL CHECK(urgency IN ('normal','urgent')),
 deadline TEXT NOT NULL, requirements TEXT NOT NULL,
 owner_id INTEGER NOT NULL REFERENCES users(id),
 assignee_id INTEGER REFERENCES users(id),
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','active','review','done')),
 created_at TEXT NOT NULL
)'''
# 全新的库里先放的标签：一句说明让大家知道这个方向做什么；团队成员可以随时改、删、加
STARTER_TAGS = (('实验', '跑实验、调参、消融'), ('数据', '造数据、清洗、标注'), ('论文', '读论文、复现、组会分享'),
                ('代码', '写工具、修 bug、加测试'), ('讲解', '讲题、写题解、带新人'), ('杂务', '订场地、做海报、跑腿'))
SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, password TEXT NOT NULL
);
''' + TASK_TABLE + ''';
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),
 user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
 body TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS honors (
 task_id INTEGER NOT NULL REFERENCES tasks(id),
 user_id INTEGER NOT NULL REFERENCES users(id),
 medal_key TEXT NOT NULL,
 awarded_at TEXT NOT NULL, seen_at TEXT,
 PRIMARY KEY(task_id,user_id)
);
CREATE INDEX IF NOT EXISTS honors_by_user ON honors(user_id);
CREATE TABLE IF NOT EXISTS featured_honors (
 user_id INTEGER NOT NULL REFERENCES users(id),
 slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 3),
 medal_key TEXT NOT NULL,
 PRIMARY KEY(user_id,slot), UNIQUE(user_id,medal_key)
);
CREATE TABLE IF NOT EXISTS task_tags (
 task_id INTEGER NOT NULL REFERENCES tasks(id),
 tag TEXT NOT NULL,
 PRIMARY KEY(task_id,tag)
);
CREATE INDEX IF NOT EXISTS task_tags_by_tag ON task_tags(tag);
CREATE TABLE IF NOT EXISTS interests (
 user_id INTEGER NOT NULL REFERENCES users(id),
 tag TEXT NOT NULL,
 PRIMARY KEY(user_id,tag)
);
CREATE TABLE IF NOT EXISTS dismissals (
 user_id INTEGER NOT NULL REFERENCES users(id),
 task_id INTEGER NOT NULL REFERENCES tasks(id),
 created_at TEXT NOT NULL,
 PRIMARY KEY(user_id,task_id)
);
CREATE TABLE IF NOT EXISTS claps (
 task_id INTEGER NOT NULL REFERENCES tasks(id),
 user_id INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 PRIMARY KEY(task_id,user_id)
);
CREATE TABLE IF NOT EXISTS titles_seen (
 user_id INTEGER NOT NULL REFERENCES users(id),
 key TEXT NOT NULL,
 seen_at TEXT NOT NULL,
 PRIMARY KEY(user_id,key)
);
CREATE TABLE IF NOT EXISTS game_runs (
 id INTEGER PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id),
 game TEXT NOT NULL,
 mode TEXT NOT NULL DEFAULT 'normal',
 started_at TEXT NOT NULL,
 finished_at TEXT,
 score INTEGER,
 combo INTEGER
);
CREATE TABLE IF NOT EXISTS daily_lines (
 user_id INTEGER NOT NULL REFERENCES users(id),
 day TEXT NOT NULL,
 level INTEGER NOT NULL,
 solved_at TEXT NOT NULL,
 PRIMARY KEY(user_id,day,level)
);
CREATE TABLE IF NOT EXISTS builds (
 id INTEGER PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id),
 name TEXT NOT NULL,
 bg TEXT NOT NULL,
 parts TEXT NOT NULL,
 view INTEGER NOT NULL DEFAULT 0,
 shown INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS builds_by_user ON builds(user_id);
CREATE TABLE IF NOT EXISTS org_tags (
 name TEXT PRIMARY KEY,
 note TEXT NOT NULL DEFAULT '',
 position INTEGER NOT NULL DEFAULT 0,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_members (
 task_id INTEGER NOT NULL REFERENCES tasks(id),
 user_id INTEGER NOT NULL REFERENCES users(id),
 joined_at TEXT NOT NULL,
 PRIMARY KEY(task_id,user_id)
);
CREATE INDEX IF NOT EXISTS task_members_by_user ON task_members(user_id);
CREATE TABLE IF NOT EXISTS lines_tally (
 user_id INTEGER NOT NULL REFERENCES users(id),
 term TEXT NOT NULL,
 solved INTEGER NOT NULL,
 PRIMARY KEY(user_id,term)
);
CREATE TABLE IF NOT EXISTS meta (
 key TEXT PRIMARY KEY,
 value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lines_solved (
 user_id INTEGER NOT NULL REFERENCES users(id),
 level INTEGER NOT NULL,
 solved_at TEXT NOT NULL,
 PRIMARY KEY(user_id,level)
);
CREATE TABLE IF NOT EXISTS extensions (
 id INTEGER PRIMARY KEY,
 task_id INTEGER NOT NULL REFERENCES tasks(id),
 user_id INTEGER NOT NULL REFERENCES users(id),
 old_deadline TEXT NOT NULL,
 new_deadline TEXT NOT NULL,
 reason TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','closed')),
 created_at TEXT NOT NULL,
 decided_by INTEGER REFERENCES users(id),
 decided_at TEXT
);
CREATE INDEX IF NOT EXISTS extensions_by_task ON extensions(task_id);
'''



@contextmanager
def connect(path, write=False):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    try:
        if write:
            db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(path):
    with connect(path) as db:
        db.execute('PRAGMA journal_mode = WAL')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(tasks)')}
        if 'reward' in columns:
            # Preserve the former monetary records in a one-time SQLite backup.
            backup = Path(str(path) + '.before-honors.bak')
            if not backup.exists():
                with closing(sqlite3.connect(backup)) as target:
                    db.backup(target)
            db.execute('PRAGMA foreign_keys = OFF')
            db.execute('BEGIN IMMEDIATE')
            db.execute(TASK_TABLE.replace('IF NOT EXISTS tasks', 'tasks_honors'))
            db.execute('''INSERT INTO tasks_honors
                (id,title,description,category,importance,urgency,deadline,requirements,
                 owner_id,assignee_id,status,created_at)
                SELECT id,title,description,category,'standard','normal',deadline,requirements,
                       owner_id,assignee_id,status,created_at FROM tasks''')
            db.execute('DROP TABLE tasks')
            db.execute('ALTER TABLE tasks_honors RENAME TO tasks')
            if db.execute('PRAGMA foreign_key_check').fetchone():
                raise RuntimeError('数据库迁移失败：存在无效归属。')
            db.commit()
            db.execute('PRAGMA foreign_keys = ON')
        tables = {row['name'] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        new_tag_table = 'org_tags' not in tables
        # 早期版本的「游戏券」账本：游戏角现在改成用勋章解锁，这张表只是从勋章推出来的，直接去掉
        db.execute('DROP TABLE IF EXISTS tickets')
        db.execute('DROP TABLE IF EXISTS daily_solved')   # 早期的每日一题，已经换成每天 6 关的 daily_lines
        if 'game_runs' in tables and 'mode' not in {row['name'] for row in db.execute('PRAGMA table_info(game_runs)')}:
            db.execute("ALTER TABLE game_runs ADD COLUMN mode TEXT NOT NULL DEFAULT 'normal'")
        db.executescript(SCHEMA)
        if 'seen_at' not in {row['name'] for row in db.execute('PRAGMA table_info(honors)')}:
            db.execute('ALTER TABLE honors ADD COLUMN seen_at TEXT')
        task_columns = {row['name'] for row in db.execute('PRAGMA table_info(tasks)')}
        if 'project' not in task_columns:
            db.execute('ALTER TABLE tasks ADD COLUMN project TEXT')
        if 'cold' not in task_columns:   # 等了好几天才有人接的任务，完成时多给经验
            db.execute('ALTER TABLE tasks ADD COLUMN cold INTEGER NOT NULL DEFAULT 0')
        if 'kind' not in task_columns:     # solo 小任务（一个人做）/ team 大任务（好几个人一起做）
            db.execute("ALTER TABLE tasks ADD COLUMN kind TEXT NOT NULL DEFAULT 'solo'")
        if 'team_size' not in task_columns:   # 大任务想要几个人；空 = 不限
            db.execute('ALTER TABLE tasks ADD COLUMN team_size INTEGER')
        if 'parent_id' not in task_columns:   # 从大任务里拆出来的分工：属于哪个大任务
            db.execute('ALTER TABLE tasks ADD COLUMN parent_id INTEGER REFERENCES tasks(id)')
        db.execute('CREATE INDEX IF NOT EXISTS tasks_by_parent ON tasks(parent_id)')
        if 'bonus' not in {row['name'] for row in db.execute('PRAGMA table_info(honors)')}:
            db.execute('ALTER TABLE honors ADD COLUMN bonus INTEGER NOT NULL DEFAULT 0')
        if {row['name']: row['pk'] for row in db.execute('PRAGMA table_info(honors)')}.get('user_id') == 0:
            _honors_per_person(db)
        user_columns = {row['name'] for row in db.execute('PRAGMA table_info(users)')}
        if 'title_key' not in user_columns:
            db.execute('ALTER TABLE users ADD COLUMN title_key TEXT')
        if 'is_admin' in user_columns:
            db.execute('ALTER TABLE users DROP COLUMN is_admin')
        if 'play_seen' not in user_columns:   # 上次进游戏角时已经解锁了哪些：多出来的在导航上标「新」
            db.execute("ALTER TABLE users ADD COLUMN play_seen TEXT NOT NULL DEFAULT ''")
        if 'notes_seen_at' not in user_columns:
            # 老用户从现在开始收纸条，不把以前的鼓掌一股脑翻出来
            db.execute('ALTER TABLE users ADD COLUMN notes_seen_at TEXT')
            db.execute("UPDATE users SET notes_seen_at=strftime('%Y-%m-%dT%H:%M:%S+00:00','now')")
        if 'appreciations' in tables:
            # 旧版 v1.1.0 的「有帮助」标记：意思和鼓掌一样，升级时变成鼓掌（原表留着不动）
            db.execute('''INSERT OR IGNORE INTO claps (task_id,user_id,created_at)
                SELECT a.task_id,a.user_id,a.created_at FROM appreciations a JOIN tasks t ON t.id=a.task_id
                WHERE t.status='done' AND t.assignee_id<>a.user_id''')
        # Older tasks had one fixed category; it becomes their first tag so search and recommendations keep working.
        db.execute('INSERT OR IGNORE INTO task_tags (task_id,tag) SELECT id,category FROM tasks WHERE id NOT IN (SELECT task_id FROM task_tags)')
        if new_tag_table:
            # 团队标签表第一次出现：已经在用的标签都收进来；全新的库先放几个起步标签，团队成员之后随意改
            stamp = "strftime('%Y-%m-%dT%H:%M:%S+00:00','now')"
            db.execute(f'''INSERT OR IGNORE INTO org_tags (name,position,created_at)
                SELECT tag,ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC,tag),{stamp} FROM
                (SELECT tag FROM task_tags UNION ALL SELECT tag FROM interests) GROUP BY tag''')
            if not db.execute('SELECT 1 FROM org_tags').fetchone():
                db.executemany(f'INSERT INTO org_tags (name,note,position,created_at) VALUES (?,?,?,{stamp})',
                               [(name, note, i) for i, (name, note) in enumerate(STARTER_TAGS, 1)])
        if 'big_tasks' in tables:
            _big_tasks_become_team_tasks(db)
        if 'view' not in {row['name'] for row in db.execute('PRAGMA table_info(builds)')}:
            # 积木从平面换成立体：旧作品换成立体零件，作品记下保存时的视角
            from .blocks import upgrade_flat
            db.execute('ALTER TABLE builds ADD COLUMN view INTEGER NOT NULL DEFAULT 0')
            upgrade_flat(db)
        # Also resumes safely if startup was interrupted after the table migration.
        db.execute('''INSERT OR IGNORE INTO honors (task_id,user_id,medal_key,awarded_at)
            SELECT t.id,t.assignee_id,t.importance || '-' || t.urgency,
                   COALESCE((SELECT MAX(created_at) FROM events WHERE task_id=t.id AND kind='accept'),t.created_at)
            FROM tasks t WHERE t.status='done' AND t.assignee_id IS NOT NULL''')


def _honors_per_person(db):
    """Older honors were keyed by task alone (one medal per task); a big task gives one to everyone who did it."""
    db.commit()
    db.execute('BEGIN IMMEDIATE')
    db.execute('''CREATE TABLE honors_people (
     task_id INTEGER NOT NULL REFERENCES tasks(id),
     user_id INTEGER NOT NULL REFERENCES users(id),
     medal_key TEXT NOT NULL,
     awarded_at TEXT NOT NULL, seen_at TEXT,
     bonus INTEGER NOT NULL DEFAULT 0,
     PRIMARY KEY(task_id,user_id)
    )''')
    db.execute('''INSERT INTO honors_people (task_id,user_id,medal_key,awarded_at,seen_at,bonus)
        SELECT task_id,user_id,medal_key,awarded_at,seen_at,bonus FROM honors''')
    db.execute('DROP TABLE honors')
    db.execute('ALTER TABLE honors_people RENAME TO honors')
    db.execute('CREATE INDEX IF NOT EXISTS honors_by_user ON honors(user_id)')
    db.commit()


def _big_tasks_become_team_tasks(db):
    """A short-lived version kept big tasks in their own tables, with shares pointing at them through tasks.big_id.
    Each one becomes a team task; its shares, members and talk move over, and a finished one's credits become medals
    (「线」 is worth the same 30 experience the credit gave)."""
    db.commit()
    db.execute('BEGIN IMMEDIATE')
    events = {'comment': 'comment', 'join': 'join', 'piece': 'split', 'close': 'accept'}
    for big in db.execute('SELECT * FROM big_tasks ORDER BY id').fetchall():
        tag = db.execute('''SELECT x.tag FROM task_tags x JOIN tasks t ON t.id=x.task_id WHERE t.big_id=?
            GROUP BY x.tag ORDER BY COUNT(*) DESC,x.tag LIMIT 1''', (big['id'],)).fetchone()
        tag = tag[0] if tag else (db.execute('SELECT name FROM org_tags ORDER BY position LIMIT 1').fetchone() or ['杂务'])[0]
        members = [row['user_id'] for row in db.execute('SELECT user_id FROM big_members WHERE big_id=? AND user_id<>?',
                                                        (big['id'], big['owner_id']))]
        status = 'done' if big['status'] == 'done' else 'active' if members else 'open'
        task_id = db.execute('''INSERT INTO tasks (title,description,category,project,importance,urgency,deadline,requirements,
                owner_id,status,created_at,kind) VALUES (?,?,?,?,'standard','normal',?,?,?,?,?,'team')''',
            (big['title'], big['goal'], tag, big['project'], big['deadline'], big['goal'], big['owner_id'], status,
             big['created_at'])).lastrowid
        db.execute('INSERT INTO task_tags (task_id,tag) VALUES (?,?)', (task_id, tag))
        db.execute('''INSERT INTO task_members (task_id,user_id,joined_at) SELECT ?,user_id,joined_at FROM big_members
            WHERE big_id=? AND user_id<>?''', (task_id, big['id'], big['owner_id']))
        db.execute('UPDATE tasks SET parent_id=? WHERE big_id=?', (task_id, big['id']))
        for event in db.execute('SELECT * FROM big_events WHERE big_id=? ORDER BY id', (big['id'],)).fetchall():
            if event['kind'] in events:
                db.execute('INSERT INTO events (task_id,user_id,kind,body,created_at) VALUES (?,?,?,?,?)',
                           (task_id, event['user_id'], events[event['kind']], event['body'], event['created_at']))
        db.execute('''INSERT OR IGNORE INTO honors (task_id,user_id,medal_key,awarded_at,seen_at,bonus)
            SELECT ?,user_id,'standard-normal',awarded_at,seen_at,0 FROM big_credits WHERE big_id=?''', (task_id, big['id']))
    db.execute('DROP INDEX IF EXISTS tasks_by_big')
    db.execute('ALTER TABLE tasks DROP COLUMN big_id')
    for table in ('big_credits', 'big_events', 'big_members', 'big_tasks'):
        db.execute(f'DROP TABLE {table}')
    db.commit()
