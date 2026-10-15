import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app import create_app
from bounty import discover, progress, teams, titles, unlocks
from bounty.db import connect, initialize
from bounty.service import InvalidAction, act, clap, create_task


class TeamTaskTest(unittest.TestCase):
    """大任务：好几个人一起做；发布者也能加入；做的过程中随时可以拆出分工。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'test.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'test'})
        self.clients = []
        for name in ('owner', 'ann', 'bob', 'cat'):
            client = self.app.test_client()
            self.post(client, '/auth/register', {'name': name, 'password': 'test-password'})
            self.clients.append(client)
        self.data = dict(title='办好周六模拟赛', description='题目、数据、机房都要有人管', requirements='按时开赛，赛后发题解',
                         tags='讲解 杂务', project='校赛', importance='major', urgency='normal', kind='team',
                         deadline=(datetime.now(timezone.utc) + timedelta(days=5)).isoformat())

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self, client):
        client.get('/auth/login')
        with client.session_transaction() as session:
            return session['csrf']

    def post(self, client, path, data):
        return client.post(path, data={**data, 'csrf': self.csrf(client)}, follow_redirects=True)

    def row(self, task_id):
        with connect(self.path) as db:
            return db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()

    def members(self, task_id):
        with connect(self.path) as db:
            return [row[0] for row in db.execute('SELECT user_id FROM task_members WHERE task_id=? ORDER BY user_id', (task_id,))]

    def test_people_join_and_the_publisher_can_join_too(self):
        task = create_task(self.path, 1, {**self.data, 'team_size': '3'})
        self.assertEqual((self.row(task)['status'], self.row(task)['kind'], self.row(task)['team_size']), ('open', 'team', 3))
        with self.assertRaises(InvalidAction):          # 大任务不是「认领」，是加入
            act(self.path, task, 2, 'claim')
        act(self.path, task, 2, 'join')
        self.assertEqual(self.row(task)['status'], 'active')
        act(self.path, task, 1, 'join')                 # 发布者自己也一起做
        act(self.path, task, 3, 'join')
        with self.assertRaises(InvalidAction):          # 想要 3 个人，满了
            act(self.path, task, 4, 'join')
        with self.assertRaises(InvalidAction):
            act(self.path, task, 2, 'join')
        self.assertEqual(self.members(task), [1, 2, 3])
        act(self.path, task, 3, 'leave')
        act(self.path, task, 4, 'join')
        for uid in (1, 2, 4):
            act(self.path, task, uid, 'leave')
        self.assertEqual(self.row(task)['status'], 'open')   # 都走了：回到没人做
        # 发的时候就勾上「我也一起做」
        mine = create_task(self.path, 1, {**self.data, 'join_self': '1'})
        self.assertEqual((self.row(mine)['status'], self.members(mine)), ('active', [1]))
        for size in ('1', '21', 'x'):
            with self.assertRaises(InvalidAction):
                create_task(self.path, 1, {**self.data, 'team_size': size})

    def test_shares_can_be_split_off_any_time(self):
        task = create_task(self.path, 1, self.data)
        with self.assertRaises(InvalidAction):          # 没加入不能拆
            teams.split(self.path, task, 2, dict(title='造数据', tag='数据', kind='standard-normal'))
        act(self.path, task, 2, 'join')
        piece = teams.split(self.path, task, 2, dict(title='造数据', tag='数据', kind='standard-urgent', note='E 题 30 组'))
        data = self.row(piece)
        self.assertEqual((data['kind'], data['parent_id'], data['owner_id'], data['urgency'], data['deadline'], data['project']),
                         ('solo', task, 2, 'urgent', self.row(task)['deadline'], '校赛'))
        # 不在大任务里的人接下分工，也就加入了
        act(self.path, piece, 3, 'claim')
        self.assertIn(3, self.members(task))
        act(self.path, piece, 3, 'submit', '数据好了')
        # 分工在做或等验收时，大任务还不能交
        with self.assertRaises(InvalidAction):
            act(self.path, task, 2, 'submit', '成果')
        # 拆分工的人能验收，大任务的发布者也能；别人不行
        with self.assertRaises(InvalidAction):
            act(self.path, piece, 4, 'accept')
        act(self.path, piece, 1, 'accept', '好')
        act(self.path, task, 2, 'submit', '比赛办完了')
        with self.assertRaises(InvalidAction):          # 交上去之后不能再拆
            teams.split(self.path, task, 1, dict(title='晚了', tag='数据', kind='light-normal'))
        self.assertIn('class="share-list"', self.clients[0].get(f'/tasks/{task}').text)

    def test_the_publisher_accepts_and_chooses_who_gets_the_medal(self):
        task = create_task(self.path, 1, {**self.data, 'join_self': '1'})
        act(self.path, task, 2, 'join')
        act(self.path, task, 3, 'join')
        spare = teams.split(self.path, task, 1, dict(title='订机房', tag='杂务', kind='light-normal'))
        with self.assertRaises(InvalidAction):          # 只有一起做的人能交
            act(self.path, task, 4, 'submit', '成果')
        act(self.path, task, 3, 'submit', '办完了')
        with self.assertRaises(InvalidAction):          # 只有发布者能验收
            act(self.path, task, 2, 'accept')
        with self.assertRaises(InvalidAction):          # 发布者也在里面：不能只发给自己
            act(self.path, task, 1, 'accept', '', [1])
        act(self.path, task, 1, 'accept', '辛苦了', [1, 2])
        with connect(self.path) as db:
            got = {row['user_id']: row['medal_key'] for row in db.execute('SELECT * FROM honors WHERE task_id=?', (task,))}
            self.assertEqual(got, {1: 'major-normal', 2: 'major-normal'})
            self.assertEqual(progress.person_progress(db, 2)['xp'], 80)
            self.assertEqual(progress.person_progress(db, 3)['xp'], 0)
            self.assertIsNone(self.row(spare)['parent_id'])    # 没人接的分工变回普通小任务
            self.assertEqual(titles.counts(db, 2)['together'], 1)
            self.assertEqual(titles.counts(db, 1)['captain'], 1)
            self.assertIn('part:knot', unlocks.unlocked(db, 2))
            self.assertNotIn('part:knot', unlocks.unlocked(db, 3))
        with self.assertRaises(InvalidAction):          # 拿了勋章的人不能给自己鼓掌
            clap(self.path, task, 2)
        self.assertEqual(clap(self.path, task, 4), 1)
        # 颁奖时说出和谁一起做的
        ann = self.clients[1]
        reply = ann.post('/honors/reveal', data={'csrf': self.csrf(ann)}, headers={'Accept': 'application/json'}).json
        self.assertEqual(reply['awards'][0]['team'], ['owner'])
        self.assertIn('双环', reply['awards'][0]['opens'])
        page = ann.get('/honors').text
        self.assertIn('一起完成的大任务', page)
        self.assertIn('辛苦了', page)
        done = ann.get(f'/tasks/{task}').text
        self.assertIn('2 人一起完成', done)

    def test_pages_for_a_team_task(self):
        owner, ann, bob, _ = self.clients
        page = self.post(owner, '/tasks/new', {**self.data, 'team_size': '4', 'join_self': '1'})
        self.assertIn('大任务已发布', page.text)
        task = 1
        self.assertIn('kind-switch', owner.get('/tasks/new?kind=team').text)
        self.assertEqual(owner.get('/big/new').status_code, 302)
        home = ann.get('/').text
        self.assertIn('lane-team', home)
        self.assertIn('crew-art', home)
        self.assertIn('办好周六模拟赛', home)
        self.assertIn('加入，一起做', ann.get(f'/tasks/{task}').text)
        self.post(ann, f'/tasks/{task}/join', {})
        page = ann.get(f'/tasks/{task}').text
        self.assertIn('提交成果', page)
        self.assertIn('拆出一份分工', page)
        self.post(ann, f'/tasks/{task}/split', {'title': '造数据', 'tag': '数据', 'kind': 'standard-normal'})
        self.assertIn('class="bigtag"', bob.get('/').text)      # 拆出来的分工在发现里写着属于哪个大任务
        self.assertIn('class="big-crumb"', bob.get('/tasks/2').text)
        self.assertIn('你们 2 人在做', ann.get('/mine').text)
        self.post(ann, f'/tasks/{task}/submit', {'body': '办完了'})
        accept = owner.get(f'/tasks/{task}').text
        self.assertIn('name="credit"', accept)
        self.assertIn('等你验收', owner.get('/mine').text)
        # 勾掉了所有人：不发
        self.assertIn('至少给一个', self.post(owner, f'/tasks/{task}/accept', {'credit_form': '1'}).text)
        self.post(owner, f'/tasks/{task}/accept', {'credit_form': '1', 'credit': ['1', '2'], 'body': '好'})
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM honors WHERE task_id=?', (task,)).fetchone()[0], 2)
        self.assertIn('一起完成的', ann.get('/big').text)

    def test_recommendations_show_team_tasks_and_crew_shares(self):
        task = create_task(self.path, 1, self.data)
        with connect(self.path) as db:
            picks = {pick['task']['id']: pick['ranked'] for pick in discover.recommend(db, 2, limit=10)}
        self.assertIn('team', [kind for kind, _ in picks[task]])
        act(self.path, task, 2, 'join')
        piece = teams.split(self.path, task, 1, dict(title='造数据', tag='数据', kind='standard-normal'))
        with connect(self.path) as db:
            picks = {pick['task']['id']: pick['ranked'] for pick in discover.recommend(db, 2, limit=10, lane='past')}
            self.assertNotIn(task, picks)               # 已经在里面了，不再推荐
            self.assertEqual(picks[piece][0], ('crew', '你在「办好周六模拟赛」里'))


class TeamMigrationTest(unittest.TestCase):
    """前一个版本把大任务放在单独的表里（分工用 tasks.big_id 指过去），honors 也是一个任务一枚；启动时都升级。"""

    def test_container_big_tasks_become_team_tasks(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'old.sqlite3')
            initialize(path)
            with connect(path) as db:
                db.executescript('''
                    INSERT INTO users (id,name,password) VALUES (1,'lead','x'),(2,'ann','x'),(3,'bob','x');
                    CREATE TABLE big_tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL, goal TEXT NOT NULL, project TEXT,
                     owner_id INTEGER NOT NULL REFERENCES users(id), deadline TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
                     closing TEXT, created_at TEXT NOT NULL, done_at TEXT);
                    CREATE TABLE big_members (big_id INTEGER NOT NULL, user_id INTEGER NOT NULL, joined_at TEXT NOT NULL,
                     PRIMARY KEY(big_id,user_id));
                    CREATE TABLE big_events (id INTEGER PRIMARY KEY, big_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                     kind TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE TABLE big_credits (big_id INTEGER NOT NULL, user_id INTEGER NOT NULL, lead INTEGER NOT NULL DEFAULT 0,
                     pieces INTEGER NOT NULL DEFAULT 0, bonus INTEGER NOT NULL DEFAULT 0, awarded_at TEXT NOT NULL, seen_at TEXT,
                     PRIMARY KEY(big_id,user_id));
                    ALTER TABLE tasks ADD COLUMN big_id INTEGER REFERENCES big_tasks(id);
                    INSERT INTO big_tasks VALUES (1,'办校赛','按时开赛','校赛',1,'2030-01-01T00:00:00+00:00','done','谢谢',
                                                  '2026-10-01T00:00:00+00:00','2026-10-10T00:00:00+00:00');
                    INSERT INTO big_members VALUES (1,1,'2026-10-01T00:00:00+00:00'),(1,2,'2026-10-02T00:00:00+00:00');
                    INSERT INTO big_events VALUES (1,1,2,'comment','我来造数据','2026-10-02T00:00:00+00:00');
                    INSERT INTO big_credits VALUES (1,2,0,1,30,'2026-10-10T00:00:00+00:00',NULL);
                    INSERT INTO tasks (id,title,description,category,importance,urgency,deadline,requirements,owner_id,assignee_id,
                                       status,created_at,big_id)
                        VALUES (1,'造数据','d','数据','standard','normal','2030-01-01','r',1,2,'done','2026-10-01T00:00:00+00:00',1);
                    INSERT INTO task_tags VALUES (1,'数据');
                ''')
            # 再模拟更早的 honors：一个任务一枚（task_id 是主键）
            raw = sqlite3.connect(path)
            raw.executescript('''DROP TABLE honors;
                CREATE TABLE honors (task_id INTEGER PRIMARY KEY REFERENCES tasks(id), user_id INTEGER NOT NULL,
                 medal_key TEXT NOT NULL, awarded_at TEXT NOT NULL, seen_at TEXT, bonus INTEGER NOT NULL DEFAULT 0);
                INSERT INTO honors VALUES (1,2,'standard-normal','2026-10-05T00:00:00+00:00','2026-10-05T00:00:00+00:00',0);''')
            raw.close()
            initialize(path)
            with connect(path) as db:
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertFalse(tables & {'big_tasks', 'big_members', 'big_events', 'big_credits'})
                self.assertNotIn('big_id', {row['name'] for row in db.execute('PRAGMA table_info(tasks)')})
                team = db.execute("SELECT * FROM tasks WHERE kind='team'").fetchone()
                self.assertEqual((team['title'], team['status'], team['owner_id']), ('办校赛', 'done', 1))
                self.assertEqual(db.execute('SELECT parent_id FROM tasks WHERE id=1').fetchone()[0], team['id'])
                self.assertEqual([row[0] for row in db.execute('SELECT user_id FROM task_members WHERE task_id=?', (team['id'],))], [2])
                self.assertEqual(db.execute("SELECT body FROM events WHERE task_id=? AND kind='comment'", (team['id'],)).fetchone()[0], '我来造数据')
                # 合力纪念变成「线」勋章：经验和原来一样多（30 + 原来分工的 30）
                self.assertEqual(progress.person_progress(db, 2)['xp'], 60)
                pk = {row['name']: row['pk'] for row in db.execute('PRAGMA table_info(honors)')}
                self.assertEqual((pk['task_id'], pk['user_id']), (1, 2))
                self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())


if __name__ == '__main__':
    unittest.main()
