-- SQLite schema; see bounty/db.py for migrations.
-- Columns that bounty/db.py adds to older databases on startup:
--   tasks.project TEXT, tasks.cold INTEGER NOT NULL DEFAULT 0, tasks.kind TEXT NOT NULL DEFAULT 'solo',
--   tasks.team_size INTEGER, tasks.parent_id INTEGER REFERENCES tasks(id) (plus the index tasks_by_parent ON tasks(parent_id))
--   honors.bonus INTEGER NOT NULL DEFAULT 0
--   users.title_key TEXT, users.notes_seen_at TEXT, users.play_seen TEXT NOT NULL DEFAULT ''
--   game_runs.mode TEXT NOT NULL DEFAULT 'normal'
--   builds.view INTEGER NOT NULL DEFAULT 0 (older flat builds are converted to stacked parts at the same time)

CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, password TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
 category TEXT NOT NULL,
 importance TEXT NOT NULL CHECK(importance IN ('light','standard','major')),
 urgency TEXT NOT NULL CHECK(urgency IN ('normal','urgent')),
 deadline TEXT NOT NULL, requirements TEXT NOT NULL,
 owner_id INTEGER NOT NULL REFERENCES users(id),
 assignee_id INTEGER REFERENCES users(id),
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','active','review','done')),
 created_at TEXT NOT NULL
);
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
CREATE TABLE IF NOT EXISTS topics (
 id INTEGER PRIMARY KEY,
 title TEXT NOT NULL,
 user_id INTEGER NOT NULL REFERENCES users(id),
 task_id INTEGER REFERENCES tasks(id),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS topics_by_task ON topics(task_id);
CREATE TABLE IF NOT EXISTS posts (
 id INTEGER PRIMARY KEY,
 topic_id INTEGER NOT NULL REFERENCES topics(id),
 user_id INTEGER NOT NULL REFERENCES users(id),
 body TEXT NOT NULL,
 via TEXT NOT NULL DEFAULT 'web' CHECK(via IN ('web','cli')),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS posts_by_topic ON posts(topic_id);
CREATE TABLE IF NOT EXISTS post_mentions (
 post_id INTEGER NOT NULL REFERENCES posts(id),
 user_id INTEGER NOT NULL REFERENCES users(id),
 PRIMARY KEY(post_id,user_id)
);
CREATE INDEX IF NOT EXISTS post_mentions_by_user ON post_mentions(user_id);
CREATE TABLE IF NOT EXISTS topic_reads (
 user_id INTEGER NOT NULL REFERENCES users(id),
 topic_id INTEGER NOT NULL REFERENCES topics(id),
 post_id INTEGER NOT NULL,
 PRIMARY KEY(user_id,topic_id)
);
CREATE TABLE IF NOT EXISTS notes (
 id INTEGER PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id),
 kind TEXT NOT NULL DEFAULT 'progress' CHECK(kind IN ('progress','problem')),
 body TEXT NOT NULL,
 task_id INTEGER REFERENCES tasks(id),
 private INTEGER NOT NULL DEFAULT 0,
 spawned_task_id INTEGER REFERENCES tasks(id),
 solved_at TEXT,
 solved_by INTEGER REFERENCES users(id),
 solution TEXT,
 via TEXT NOT NULL DEFAULT 'web' CHECK(via IN ('web','cli')),
 tz TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS notes_by_user ON notes(user_id,created_at);
CREATE INDEX IF NOT EXISTS notes_by_task ON notes(task_id);
CREATE TABLE IF NOT EXISTS note_mentions (
 note_id INTEGER NOT NULL REFERENCES notes(id),
 user_id INTEGER NOT NULL REFERENCES users(id),
 shown_at TEXT,
 seen_at TEXT,
 PRIMARY KEY(note_id,user_id)
);
CREATE INDEX IF NOT EXISTS note_mentions_by_user ON note_mentions(user_id,seen_at);
CREATE TABLE IF NOT EXISTS todos (
 id INTEGER PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id),
 title TEXT NOT NULL,
 task_id INTEGER REFERENCES tasks(id),
 state TEXT NOT NULL DEFAULT 'todo' CHECK(state IN ('todo','doing','done','dropped')),
 private INTEGER NOT NULL DEFAULT 0,
 via TEXT NOT NULL DEFAULT 'web' CHECK(via IN ('web','cli')),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 done_at TEXT
);
CREATE INDEX IF NOT EXISTS todos_by_user ON todos(user_id,state);
