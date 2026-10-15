"""Daily housekeeping: clear out records that nothing reads any more, so the database stops growing with time.
Medals, tasks someone worked on, talk, titles and builds are never touched. Runs at most once per team day (the first
request of the day starts it) and can be run by hand with `manage.py cleanup`.

- 盖章挑战: a run has to end within 15 minutes, so one still unfinished after a day was abandoned. Finished runs older
  than KEEP_DAYS are thinned to the ones still counted: each person's best score and longest combo per mode, and
  their best score in each term (for the 学期绘卷).
- 一笔画: once a day's levels can no longer be caught up on, its records become a per-term count in lines_tally
  (the title and the term recap only need how many).
- 「不感兴趣」 marks on tasks that are finished or past their deadline (those are never recommended again).
- Tasks nobody took: still open KEEP_DAYS after the deadline, nobody joined, nothing split off, and nobody but the
  publisher ever wrote on it.
"""
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from .db import connect
from .games import recent_days, today
from .recap import term_of

KEEP_DAYS = 30


def run(path, force=False):
    """Sweep once per team day; returns what was removed, or None when today's sweep already happened."""
    with connect(path, write=True) as db:
        done = db.execute("SELECT value FROM meta WHERE key='cleaned_on'").fetchone()
        if done and done[0] == today() and not force:
            return None
        removed = sweep(db, datetime.now(timezone.utc))
        db.execute("INSERT INTO meta (key,value) VALUES ('cleaned_on',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (today(),))
    if any(removed.values()):
        # 删掉的多了才整理文件；有人正在写就下次再说
        try:
            with closing(sqlite3.connect(path, timeout=1)) as raw:
                pages = raw.execute('PRAGMA page_count').fetchone()[0]
                free = raw.execute('PRAGMA freelist_count').fetchone()[0]
                if free > 256 and free * 4 > pages:
                    raw.execute('VACUUM')
                raw.execute('PRAGMA optimize')
        except sqlite3.OperationalError:
            pass
    return removed


def sweep(db, moment):
    stamp = lambda days: (moment - timedelta(days=days)).isoformat(timespec='seconds')
    removed = {}
    removed['unfinished_runs'] = db.execute('DELETE FROM game_runs WHERE finished_at IS NULL AND started_at<?',
                                            (stamp(1),)).rowcount

    runs = db.execute('SELECT id,user_id,game,mode,score,combo,finished_at FROM game_runs WHERE finished_at IS NOT NULL ORDER BY id').fetchall()
    best = {}
    for row in runs:
        term = term_of(datetime.fromisoformat(row['finished_at']))
        for key, value in (((row['user_id'], row['game'], row['mode'], 'score'), row['score'] or 0),
                           ((row['user_id'], row['game'], row['mode'], 'combo'), row['combo'] or 0),
                           ((row['user_id'], row['game'], term), row['score'] or 0)):
            if key not in best or value > best[key][0]:
                best[key] = (value, row['id'])
    keep = {run_id for _, run_id in best.values()}
    thin = [(row['id'],) for row in runs if row['finished_at'] < stamp(KEEP_DAYS) and row['id'] not in keep]
    db.executemany('DELETE FROM game_runs WHERE id=?', thin)
    removed['old_runs'] = len(thin)

    first = min(recent_days())
    old = db.execute('SELECT user_id,solved_at FROM daily_lines WHERE day<?', (first,)).fetchall()
    tally = Counter((row['user_id'], term_of(datetime.fromisoformat(row['solved_at']))) for row in old)
    db.executemany('''INSERT INTO lines_tally (user_id,term,solved) VALUES (?,?,?)
        ON CONFLICT(user_id,term) DO UPDATE SET solved=solved+excluded.solved''', [(*key, n) for key, n in tally.items()])
    removed['daily_lines'] = db.execute('DELETE FROM daily_lines WHERE day<?', (first,)).rowcount

    removed['dismissals'] = db.execute('''DELETE FROM dismissals WHERE task_id IN
        (SELECT id FROM tasks WHERE status='done' OR deadline<?)''', (stamp(0),)).rowcount

    stale = [(row['id'],) for row in db.execute('''SELECT t.id FROM tasks t
        WHERE t.status='open' AND t.assignee_id IS NULL AND t.deadline<?
          AND NOT EXISTS (SELECT 1 FROM task_members m WHERE m.task_id=t.id)
          AND NOT EXISTS (SELECT 1 FROM tasks c WHERE c.parent_id=t.id)
          AND NOT EXISTS (SELECT 1 FROM honors h WHERE h.task_id=t.id)
          AND NOT EXISTS (SELECT 1 FROM claps c WHERE c.task_id=t.id)
          AND NOT EXISTS (SELECT 1 FROM events e WHERE e.task_id=t.id AND e.user_id<>t.owner_id)''', (stamp(KEEP_DAYS),))]
    for table, column in (('dismissals', 'task_id'), ('task_tags', 'task_id'), ('events', 'task_id'), ('tasks', 'id')):
        db.executemany(f'DELETE FROM {table} WHERE {column}=?', stale)
    removed['stale_tasks'] = len(stale)
    return removed
