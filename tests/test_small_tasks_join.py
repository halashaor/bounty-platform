import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app import MY_TURN, create_app
from bounty import discover, extend, teams, titles
from bounty.db import connect, initialize
from bounty.service import InvalidAction, act, clap, create_task


class SmallTaskJoinTest(unittest.TestCase):
    """小任务不限人数：谁看到想做就加入（认领就是加入），有人在做也能一起；做的人都能交，验收时选给谁发勋章。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'test.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'test'})
        self.clients = []
        for name in ('owner', 'ann', 'bob', 'cat'):
            client = self.app.test_client()
            self.post(client, '/auth/register', {'name': name, 'password': 'test-password'})
            self.clients.append(client)
        self.data = dict(title='调通评测脚本', description='对着日志一起查', requirements='评测能跑通，附说明',
                         tags='代码', importance='standard', urgency='normal',
                         deadline=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat())

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

    def test_anyone_joins_and_each_person_gets_the_medal(self):
        task = create_task(self.path, 1, self.data)
        act(self.path, task, 2, 'claim')
        self.assertEqual((self.row(task)['status'], self.members(task)), ('active', [2]))
        act(self.path, task, 3, 'join')                 # 有人在做也能加入
        act(self.path, task, 4, 'claim')
        act(self.path, task, 1, 'join')                 # 发布者也能一起做
        self.assertEqual(self.members(task), [1, 2, 3, 4])
        with self.assertRaises(InvalidAction):          # 小任务不拆分工
            teams.split(self.path, task, 2, dict(title='写日志解析', tag='代码', kind='light-normal'))
        act(self.path, task, 4, 'leave')
        with self.assertRaises(InvalidAction):          # 退出的人不能交
            act(self.path, task, 4, 'submit', '成果')
        act(self.path, task, 3, 'submit', '跑通了')
        with self.assertRaises(InvalidAction):          # 交上去之后不再加人
            act(self.path, task, 4, 'join')
        with self.assertRaises(InvalidAction):          # 只有发布者验收
            act(self.path, task, 2, 'accept')
        with self.assertRaises(InvalidAction):          # 发布者也在里面：不能只发给自己
            act(self.path, task, 1, 'accept', '', [1])
        act(self.path, task, 1, 'return', '少了说明')
        act(self.path, task, 2, 'submit', '补了说明')
        act(self.path, task, 1, 'accept', '配合得好', [2, 3])
        with connect(self.path) as db:
            got = {row['user_id']: row['medal_key'] for row in db.execute('SELECT * FROM honors WHERE task_id=?', (task,))}
            self.assertEqual(got, {2: 'standard-normal', 3: 'standard-normal'})
            self.assertEqual(titles.counts(db, 2)['together'], 0)     # 大任务的称号不算小任务
        for uid in (1, 2):                              # 做的人不给自己鼓掌
            with self.assertRaises(InvalidAction):
                clap(self.path, task, uid)
        self.assertEqual(clap(self.path, task, 4), 1)
        ann = self.clients[1]
        reply = ann.post('/honors/reveal', data={'csrf': self.csrf(ann)}, headers={'Accept': 'application/json'}).json
        self.assertEqual(reply['awards'][0]['team'], ['bob'])          # 颁奖时说出和谁一起做的
        self.assertIn('2 人一起完成', ann.get(f'/tasks/{task}').text)

    def test_owner_alone_cannot_hand_in_and_deadline_closes_joining(self):
        task = create_task(self.path, 1, {**self.data, 'join_self': '1'})
        self.assertEqual(self.members(task), [1])
        with self.assertRaises(InvalidAction):          # 只有发布者自己在做，交上来没人能验收
            act(self.path, task, 1, 'submit', '成果')
        act(self.path, task, 2, 'join')
        act(self.path, task, 1, 'submit', '成果')
        act(self.path, task, 1, 'accept')
        with connect(self.path) as db:
            self.assertEqual(sorted(r[0] for r in db.execute('SELECT user_id FROM honors WHERE task_id=?', (task,))), [1, 2])
        late = create_task(self.path, 1, self.data)
        act(self.path, late, 2, 'claim')
        with connect(self.path, write=True) as db:
            db.execute('UPDATE tasks SET deadline=? WHERE id=?', ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), late))
        with self.assertRaises(InvalidAction):
            act(self.path, late, 3, 'join')
        act(self.path, late, 2, 'submit', '赶完了')     # 已经在做的仍可提交

    def test_turns_recommendations_and_extensions(self):
        task = create_task(self.path, 1, {**self.data, 'members': ['2']})
        with connect(self.path) as db:
            self.assertIn(task, [row['id'] for row in discover.open_tasks(db, 3)])
            reasons = [r for p in discover.recommend(db, 3, limit=10) if p['task']['id'] == task for r in p['ranked']]
            self.assertIn(('team', '1 人在做 · 可以一起'), reasons)
            self.assertIn(task, [t['id'] for t in discover.my_tasks(db, 2)['yours']])
            self.assertIn(task, [t['id'] for t in db.execute(f'SELECT t.id FROM tasks t WHERE {MY_TURN}', {'me': 2})])
        extend.ask(self.path, task, 2, (datetime.now(timezone.utc) + timedelta(days=6)).isoformat(), '数据晚到', None)
        with self.assertRaises(InvalidAction):          # 自己不能批自己的
            extend.decide(self.path, task, 2, True, '')
        with connect(self.path) as db:
            self.assertIn(task, [t['id'] for t in db.execute(f'SELECT t.id FROM tasks t WHERE {MY_TURN}', {'me': 1})])
        extend.decide(self.path, task, 1, True, '好')
        act(self.path, task, 2, 'submit', '好了')
        with connect(self.path) as db:
            self.assertIn(task, [t['id'] for t in discover.my_tasks(db, 1)['yours']])   # 等发布者验收
            self.assertNotIn(task, [row['id'] for row in discover.open_tasks(db, 3)])

    def test_a_share_of_a_big_task_can_be_done_together(self):
        big = create_task(self.path, 1, {**self.data, 'kind': 'team', 'members': ['2']})
        piece = teams.split(self.path, big, 2, dict(title='造数据', tag='代码', kind='light-normal'))
        act(self.path, piece, 3, 'claim')
        act(self.path, piece, 4, 'join')
        self.assertEqual(self.members(piece), [3, 4])
        self.assertEqual(self.members(big), [2, 3, 4])             # 接下分工也就加入了大任务
        page = self.clients[0].get(f'/tasks/{big}').text
        self.assertIn('2 人', page.split('class="share-list"')[1])
        act(self.path, piece, 4, 'submit', '数据好了')
        act(self.path, piece, 2, 'accept')                          # 拆分工的人验收
        with connect(self.path) as db:
            self.assertEqual(sorted(r[0] for r in db.execute('SELECT user_id FROM honors WHERE task_id=?', (piece,))), [3, 4])

    def test_old_claimers_move_into_members_once(self):
        active = create_task(self.path, 1, self.data)
        done = create_task(self.path, 1, {**self.data, 'title': '旧的做完了'})
        with connect(self.path, write=True) as db:
            stamp = '2026-11-01T08:00:00+00:00'
            db.execute("UPDATE tasks SET assignee_id=2,status='active' WHERE id=?", (active,))
            db.execute("UPDATE tasks SET assignee_id=3,status='done' WHERE id=?", (done,))
            db.execute("INSERT INTO events (task_id,user_id,kind,body,created_at) VALUES (?,2,'claim','已认领，开始处理。',?)", (active, stamp))
            db.execute("INSERT INTO honors (task_id,user_id,medal_key,awarded_at) VALUES (?,3,'standard-normal',?)", (done, stamp))
        initialize(self.path)
        initialize(self.path)
        with connect(self.path) as db:
            joined = db.execute('SELECT joined_at FROM task_members WHERE task_id=? AND user_id=2', (active,)).fetchone()[0]
            self.assertEqual(joined, stamp)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks WHERE assignee_id IS NOT NULL').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM honors').fetchone()[0], 1)
        self.assertEqual((self.members(active), self.members(done)), ([2], [3]))
        act(self.path, active, 2, 'leave')                          # 退出后重启不会把人加回来
        initialize(self.path)
        self.assertEqual((self.members(active), self.row(active)['status']), ([], 'open'))
        self.assertIn('已授予 bob', self.clients[0].get(f'/tasks/{done}').text)

    def test_pages_for_small_tasks(self):
        owner, ann, bob = self.clients[:3]
        made = self.post(owner, '/tasks/new', {**self.data, 'kind': 'solo', 'members': ['2']})
        self.assertIn('任务已发布，交给 ann 了；别人也还能加入。', made.text)
        with connect(self.path) as db:
            task = db.execute('SELECT MAX(id) FROM tasks').fetchone()[0]
        page = bob.get(f'/tasks/{task}').text
        self.assertIn('一起做这个任务？', page)
        self.assertIn(f'/tasks/{task}/join', page)
        self.assertNotIn('拆出一份分工', page)
        self.assertNotIn('大任务', page.split('<main')[1].split('</main>')[0])
        self.post(bob, f'/tasks/{task}/join', {})
        self.assertIn('退出这个任务', bob.get(f'/tasks/{task}').text)
        self.assertIn('你们 2 人在做', ann.get('/mine').text)
        self.assertIn(f'/tasks/{task}"', ann.get('/?scope=claimed&status=').text)
        self.assertIn('2 人', bob.get('/').text.split(f'data-task="{task}"')[1].split('</article>')[0])
        empty = create_task(self.path, 1, {**self.data, 'title': '还没人接'})
        fresh = bob.get(f'/tasks/{empty}').text
        self.assertIn('想接这个任务？', fresh)
        self.assertIn('接下，我来做', fresh)


if __name__ == '__main__':
    unittest.main()
