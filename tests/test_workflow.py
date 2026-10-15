import concurrent.futures
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from app import create_app
from bounty.db import connect, initialize
from bounty import blocks, discover, games, progress, tags, titles, unlocks
from bounty.service import InvalidAction, act, clap, create_task, dismiss, parse_tags, set_interests
from bounty.honors import MEDALS, medal_key


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'test.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'test'})
        self.clients = []
        for name in ('owner', 'worker', 'other'):
            client = self.app.test_client()
            self.post(client, '/auth/register', {'name': name, 'password': 'test-password'})
            self.clients.append(client)
        self.data = dict(title='入门文档', description='整理团队知识', requirements='交付文档链接',
                         category='文档', importance='standard', urgency='normal',
                         deadline=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat())
        self.task_id = create_task(self.path, 1, self.data)

    def tearDown(self):
        self.temp.cleanup()

    def post(self, client, path, data):
        client.get('/auth/login')
        with client.session_transaction() as session:
            csrf = session['csrf']
        return client.post(path, data={**data, 'csrf': csrf}, follow_redirects=True)

    def test_workflow_through_pages(self):
        owner, worker, other = self.clients
        base = f'/tasks/{self.task_id}'
        self.assertIn('入门文档', owner.get('/?category=文档').text)
        self.assertIn('入门文档', owner.get('/?tag=文档').text)
        self.assertNotIn('入门文档', other.get('/mine').text)
        self.post(worker, base + '/claim', {})
        self.assertIn('入门文档', worker.get('/mine').text)
        self.post(worker, base + '/submit', {'body': '第一版 https://example.test/doc'})
        result = self.post(owner, base + '/return', {'body': ''})
        self.assertIn('请填写退回原因', result.text)
        self.post(owner, base + '/return', {'body': '补充安装步骤'})
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM honors').fetchone()[0], 0)
        self.post(worker, base + '/submit', {'body': '修订版，已补充安装步骤'})
        self.post(owner, base + '/accept', {})
        self.assertIn('class="tile" data-collection-key="standard-normal"', worker.get('/honors').text)
        self.assertIn('入门文档', worker.get('/honors').text)
        self.assertNotIn('入门文档', other.get('/honors').text)
        with connect(self.path) as db:
            award = db.execute('SELECT * FROM honors').fetchone()
            self.assertEqual((award['user_id'], award['medal_key']), (2, 'standard-normal'))
        page = self.post(other, base + '/comment', {'body': '<script>alert(1)</script>'})
        self.assertIn('已授予 worker', page.text)
        self.assertIn('第一版', page.text)
        self.assertIn('补充安装步骤', page.text)
        self.assertIn('&lt;script&gt;', page.text)
        self.assertNotIn('<script>alert', page.text)
        with self.assertRaises(InvalidAction):
            act(self.path, self.task_id, 1, 'settle', '重复')

    def test_owner_and_state_guards(self):
        for uid, action in ((1, 'claim'), (3, 'submit'), (3, 'accept'), (3, 'settle')):
            with self.assertRaises(InvalidAction):
                act(self.path, self.task_id, uid, action, '越权')
        act(self.path, self.task_id, 2, 'claim')
        for uid, action in ((3, 'submit'), (2, 'accept'), (1, 'accept'), (3, 'return')):
            with self.assertRaises(InvalidAction):
                act(self.path, self.task_id, uid, action, '越权')
        act(self.path, self.task_id, 2, 'submit', '成果')
        for action in ('accept', 'return', 'settle'):
            with self.assertRaises(InvalidAction):
                act(self.path, self.task_id, 3, action, '越权')
        act(self.path, self.task_id, 1, 'accept')
        with self.assertRaises(InvalidAction):
            act(self.path, self.task_id, 2, 'settle', '越权')

    def test_concurrent_claim_has_one_winner(self):
        def claim(uid):
            try:
                act(self.path, self.task_id, uid, 'claim')
                return True
            except InvalidAction:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, [2, 3]))
        self.assertEqual(sum(results), 1)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)
            self.assertIn(db.execute('SELECT assignee_id FROM tasks').fetchone()[0], (2, 3))

    def test_validation_deadline_and_priority(self):
        for patch in ({'importance': 'invalid'}, {'importance': ''}, {'urgency': 'invalid'},
                      {'urgency': ''}, {'deadline': 'bad'},
                      {'deadline': '2020-01-01T00:00'}, {'title': ''}):
            with self.assertRaises(InvalidAction):
                create_task(self.path, 1, {**self.data, **patch})
        with connect(self.path, write=True) as db:
            db.execute("UPDATE tasks SET deadline='2020-01-01T00:00:00+00:00'")
        with self.assertRaises(InvalidAction):
            act(self.path, self.task_id, 2, 'claim')

    def test_medal_mapping_and_duplicate_acceptance(self):
        for key in MEDALS:
            importance, urgency = key.split('-')
            task_id = create_task(self.path, 1, {**self.data, 'importance': importance,
                                                'urgency': urgency, 'medal_key': 'fake'})
            with connect(self.path) as db:
                task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                self.assertEqual(medal_key(task), key)
            act(self.path, task_id, 2, 'claim')
            act(self.path, task_id, 2, 'submit', '交付')
            def accept(_):
                try:
                    act(self.path, task_id, 1, 'accept')
                    return True
                except InvalidAction:
                    return False
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                self.assertEqual(sum(executor.map(accept, [1, 2])), 1)
            with connect(self.path) as db:
                awards = db.execute('SELECT * FROM honors WHERE task_id=?', (task_id,)).fetchall()
                self.assertEqual(len(awards), 1)
                self.assertEqual(awards[0]['medal_key'], key)
        initialize(self.path)
        initialize(self.path)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM honors').fetchone()[0], 6)
        self.assertEqual(self.clients[1].get('/honors').status_code, 200)

    def test_legacy_migration_keeps_accounts_and_tasks(self):
        legacy = str(Path(self.temp.name) / 'legacy.db')
        with connect(legacy) as db:
            db.executescript("""
                CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT,password TEXT);
                CREATE TABLE tasks(id INTEGER PRIMARY KEY,title TEXT,description TEXT,category TEXT,
                  reward INTEGER NOT NULL,reward_type TEXT NOT NULL,deadline TEXT,requirements TEXT,
                  owner_id INTEGER REFERENCES users(id),assignee_id INTEGER REFERENCES users(id),
                  status TEXT,created_at TEXT,settled_at TEXT,settlement_note TEXT);
                CREATE TABLE events(id INTEGER PRIMARY KEY,task_id INTEGER REFERENCES tasks(id),
                  user_id INTEGER REFERENCES users(id),kind TEXT,body TEXT,created_at TEXT);
                INSERT INTO users VALUES(1,'publisher','hash'),(2,'worker','hash');
                INSERT INTO tasks VALUES(1,'old task','description','文档',1000,'CNY','2027-01-01',
                  'doc',1,2,'done','2026-01-01',NULL,NULL);
                INSERT INTO events VALUES(1,1,1,'accept','accepted','2026-01-02');
            """)
        initialize(legacy)
        initialize(legacy)
        with connect(legacy) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT title FROM tasks').fetchone()[0], 'old task')
            award = db.execute('SELECT * FROM honors').fetchone()
            self.assertEqual((award['user_id'], award['medal_key'], award['awarded_at']),
                             (2, 'standard-normal', '2026-01-02'))
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM honors').fetchone()[0], 1)
        with connect(legacy + '.before-honors.bak') as db:
            self.assertEqual(db.execute('SELECT reward FROM tasks').fetchone()[0], 1000)

    def test_success_feedback_is_confirmed_and_consumed(self):
        owner, worker, other = self.clients
        base = f'/tasks/{self.task_id}'
        failed = self.post(owner, base + '/claim', {})
        self.assertNotIn('data-confirmed-action=', failed.text)
        claimed = self.post(worker, base + '/claim', {})
        self.assertIn('data-confirmed-action="claim"', claimed.text)
        self.assertNotIn('data-confirmed-action=', worker.get(base).text)
        failed = self.post(other, base + '/submit', {'body': 'not my task'})
        self.assertNotIn('data-confirmed-action=', failed.text)
        submitted = self.post(worker, base + '/submit', {'body': '成果'})
        self.assertIn('data-confirmed-action="submit"', submitted.text)

    def test_reveal_is_private_and_atomic(self):
        act(self.path, self.task_id, 2, 'claim')
        act(self.path, self.task_id, 2, 'submit', '成果')
        act(self.path, self.task_id, 1, 'accept')
        self.assertEqual(self.post(self.clients[0], '/honors/reveal', {}).json['awards'], [])
        clients = [self.app.test_client(), self.app.test_client()]
        for client in clients:
            with client.session_transaction() as session:
                session.update(user_id=2, csrf='test')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            batches = list(executor.map(lambda client: client.post('/honors/reveal',
                data={'csrf': 'test', 'user_id': '3'}).json['awards'], clients))
        self.assertEqual(sum(len(batch) for batch in batches), 1)
        self.assertEqual(self.post(self.clients[1], '/honors/reveal', {}).json['awards'], [])
        initialize(self.path)
        self.assertEqual(self.post(self.clients[1], '/honors/reveal', {}).json['awards'], [])
        self.assertEqual(self.clients[1].post('/honors/reveal').status_code, 400)

    def test_featured_medals_are_owned_and_limited(self):
        keys = list(MEDALS)[:4]
        for key in keys:
            importance, urgency = key.split('-')
            task_id = create_task(self.path, 1, {**self.data, 'importance': importance, 'urgency': urgency})
            act(self.path, task_id, 2, 'claim')
            act(self.path, task_id, 2, 'submit', '成果')
            act(self.path, task_id, 1, 'accept')
        self.post(self.clients[1], '/honors/featured', {'medals': keys[:3]})
        rejected = self.post(self.clients[1], '/honors/featured', {'medals': keys})
        self.assertIn('最多展示三种', rejected.text)
        rejected = self.post(self.clients[2], '/honors/featured', {'medals': keys[:1]})
        self.assertIn('只能展示自己已获得', rejected.text)
        with connect(self.path) as db:
            featured = db.execute('SELECT * FROM featured_honors ORDER BY slot').fetchall()
            self.assertEqual([row['medal_key'] for row in featured], keys[:3])
            self.assertTrue(all(row['user_id'] == 2 for row in featured))
        self.post(self.clients[1], '/honors/featured', {})
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM featured_honors').fetchone()[0], 0)

    def test_local_data_directory_session_restart_and_csrf(self):
        directory = Path(self.temp.name) / '独立 数据'
        first = create_app({'TESTING': True, 'DATA_DIR': str(directory)})
        client = first.test_client()
        self.post(client, '/auth/register', {'name': '本地成员', 'password': 'local-password'})
        self.assertTrue((directory / 'bounty.sqlite3').exists())
        self.assertTrue((directory / 'secret.key').exists())
        second = create_app({'TESTING': True, 'DATA_DIR': str(directory)})
        restored = second.test_client()
        restored.set_cookie('session', client.get_cookie('session').value)
        self.assertIn('本地成员', restored.get('/').text)
        self.assertEqual(restored.post('/logout', data={'csrf': '无效令牌'}).status_code, 400)

    def test_demo_database_is_independent_and_idempotent_safe(self):
        from bounty.demo import seed_demo
        path = str(Path(self.temp.name) / 'demo.sqlite3')
        self.assertEqual(seed_demo(path), 27)
        with self.assertRaises(ValueError):
            seed_demo(path)
        with connect(path) as db:
            counts = dict(db.execute('SELECT status,COUNT(*) FROM tasks GROUP BY status').fetchall())
            self.assertEqual(counts, {'open': 15, 'active': 3, 'review': 2, 'done': 7})
            self.assertEqual(db.execute('SELECT COUNT(*) FROM honors').fetchone()[0], 7)
            # 演示里有一部分勋章已经拆开过，其余留在信箱里等颁奖
            self.assertEqual(db.execute('SELECT COUNT(*) FROM honors WHERE seen_at IS NULL').fetchone()[0], 4)
            self.assertEqual(db.execute('SELECT COUNT(DISTINCT project) FROM tasks').fetchone()[0], 5)
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
        app = create_app({'TESTING': True, 'DATABASE': path, 'SECRET_KEY': 'test'})
        client = app.test_client()
        self.post(client, '/auth/login', {'name': '认领人', 'password': 'demo12345'})
        response = client.get('/')
        # 发现页默认只列可认领的任务，一页 12 个
        self.assertEqual(response.text.count('data-task='), 15)
        self.assertEqual(response.text.count('class="wall-zone"'), 2)
        # 演示账号「认领人」选过方向：两排推荐各三张，互不重复
        picks = response.text.split('data-lane-body="want"')[1]
        want, past = picks.split('data-lane-body="past"')
        self.assertEqual(want.count('data-pick='), 3)
        self.assertEqual(past.count('data-pick='), 3)
        ids = lambda html: {part.split('"')[0] for part in html.split('data-pick="')[1:]}
        self.assertFalse(ids(want) & ids(past.split('class="wall"')[0]))

    def test_auth_csrf_and_persistence(self):
        client = self.app.test_client()
        self.assertEqual(client.get('/tasks/new').status_code, 302)
        self.assertEqual(client.post(f'/tasks/{self.task_id}/claim').status_code, 400)
        self.assertIn('用户名或密码不正确', self.post(client, '/auth/login', {'name': 'owner', 'password': 'wrong-password'}).text)
        self.post(client, '/auth/login', {'name': 'owner', 'password': 'test-password'})
        result = self.post(client, '/tasks/new', {**self.data, 'title': '新任务'})
        self.assertIn('新任务', result.text)
        second_app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'test'})
        with connect(second_app.config['DATABASE']) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 2)
            self.assertNotEqual(db.execute('SELECT password FROM users WHERE id=1').fetchone()[0], 'test-password')

    def finish(self, task_id, worker=2, owner=1, body=''):
        act(self.path, task_id, worker, 'claim')
        act(self.path, task_id, worker, 'submit', '成果')
        act(self.path, task_id, owner, 'accept', body)

    def test_tags_and_projects_are_free_form(self):
        self.assertEqual(parse_tags('数据, 图论，PyTorch、 #校赛  数据'), ['数据', '图论', 'PyTorch', '校赛'])
        for raw in ('a b c d e f', '这个标签实在是太长了超过了十六个字的限制'):
            with self.assertRaises(InvalidAction):
                parse_tags(raw)
        with self.assertRaises(InvalidAction):
            create_task(self.path, 1, {**self.data, 'category': '', 'tags': ''})
        task_id = create_task(self.path, 1, {**self.data, 'title': '造模拟赛数据', 'tags': '数据 图论', 'project': '校赛 2026'})
        with connect(self.path) as db:
            self.assertEqual(discover.tags_by_task(db, [task_id])[task_id], ['数据', '图论'])
        owner = self.clients[0]
        card = f'data-task="{task_id}"'
        self.assertIn(card, owner.get('/?tag=图论').text)
        self.assertNotIn(card, owner.get('/?tag=文档').text)
        self.assertIn(card, owner.get('/?project=校赛 2026').text)
        self.assertIn('#图论', owner.get('/').text)

    def test_recommendations_follow_history_interests_and_dismissals(self):
        data_task = create_task(self.path, 1, {**self.data, 'title': '清洗比赛提交记录', 'description': '去掉重复提交和测试账号', 'tags': '数据'})
        self.finish(data_task)
        similar = create_task(self.path, 1, {**self.data, 'title': '清洗题目标签', 'description': '去掉重复和错标的标签', 'tags': '数据'})
        graph = create_task(self.path, 1, {**self.data, 'title': '讲一次图论', 'tags': '图论', 'project': '新人培养'})
        with connect(self.path) as db:
            picks = {pick['task']['id']: dict(pick['reasons']) for pick in discover.recommend(db, 2, limit=10)}
        self.assertIn('skill', picks[similar])
        self.assertIn('new-project', picks[graph])
        set_interests(self.path, 3, '图论')
        with connect(self.path) as db:
            first = discover.recommend(db, 3, limit=1)[0]
        self.assertEqual(first['task']['id'], graph)
        self.assertEqual(first['reasons'][0][0], 'interest')
        dismiss(self.path, graph, 3)
        with connect(self.path) as db:
            self.assertNotIn(graph, [pick['task']['id'] for pick in discover.recommend(db, 3, limit=10)])
            # 自己发布的任务不会推荐给自己
            self.assertFalse(discover.recommend(db, 1, limit=10))

    def test_claps_are_once_per_teammate_and_never_for_yourself(self):
        with self.assertRaises(InvalidAction):
            clap(self.path, self.task_id, 3)
        self.finish(self.task_id)
        with self.assertRaises(InvalidAction):
            clap(self.path, self.task_id, 2)
        self.assertEqual(clap(self.path, self.task_id, 3), 1)
        self.assertEqual(clap(self.path, self.task_id, 3), 1)
        other = self.clients[2]
        other.get('/')
        with other.session_transaction() as session:
            csrf = session['csrf']
        response = other.post(f'/tasks/{self.task_id}/clap', data={'csrf': csrf}, headers={'Accept': 'application/json'})
        self.assertEqual(response.json, {'claps': 1})
        with connect(self.path) as db:
            self.assertEqual(discover.person_stats(db, 2)['claps'], 1)

    def test_experience_levels_and_reveal_tiers(self):
        self.assertEqual([progress.level_floor(n) for n in (1, 2, 3, 4)], [0, 50, 150, 300])
        self.assertEqual(progress.task_xp('light-normal'), 10)
        self.assertEqual(progress.task_xp('major-urgent'), 120)
        self.assertEqual(progress.level_info(49)['level'], 1)
        self.assertEqual(progress.level_info(50)['level'], 2)
        for key in ('light-normal', 'standard-normal', 'major-normal', 'light-normal'):
            importance, urgency = key.split('-')
            self.finish(create_task(self.path, 1, {**self.data, 'importance': importance, 'urgency': urgency}), body='写得很清楚')
        worker = self.clients[1]
        worker.get('/honors')
        with worker.session_transaction() as session:
            csrf = session['csrf']
        result = worker.post('/honors/reveal', data={'csrf': csrf}).json
        self.assertEqual([award['tier'] for award in result['awards']], ['new', 'new', 'row', 'plain'])
        self.assertEqual(result['awards'][2]['row'], '冷色一行')
        self.assertEqual(result['awards'][0]['praise'], '写得很清楚')
        self.assertEqual((result['before']['level'], result['after']['level'], result['after']['xp']), (1, 2, 130))
        with connect(self.path) as db:
            self.assertTrue(progress.person_progress(db, 2)['rows']['normal'])

    def test_team_bundle_fills_matching_slots(self):
        honors = [{'medal_key': key} for key in ('light-urgent', 'standard-normal', 'major-normal', 'light-normal')]
        filled = progress._fill(('urgent', 'standard', 'light'), honors)
        self.assertEqual([honor['medal_key'] for honor in filled], ['light-urgent', 'standard-normal', 'light-normal'])
        self.assertEqual(progress._fill(('major', 'major'), honors)[1], None)
        self.finish(self.task_id)
        with connect(self.path) as db:
            bundles = progress.team_bundles(db)
        self.assertEqual(len(bundles['current']['slots']), 3)
        self.assertLessEqual(bundles['pieces'], bundles['piece_count'])

    def test_naive_deadline_uses_team_timezone(self):
        moment = datetime.now(timezone.utc) + timedelta(days=3)
        naive = moment.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None).isoformat(timespec='minutes')
        task_id = create_task(self.path, 1, {**self.data, 'deadline': naive})
        with connect(self.path) as db:
            stored = datetime.fromisoformat(db.execute('SELECT deadline FROM tasks WHERE id=?', (task_id,)).fetchone()[0])
        self.assertLess(abs((stored - moment).total_seconds()), 61)

    def test_my_tasks_group_by_whose_move_it_is(self):
        returned = create_task(self.path, 1, {**self.data, 'title': '被退回的任务'})
        act(self.path, returned, 2, 'claim')
        act(self.path, returned, 2, 'submit', '第一版')
        act(self.path, returned, 1, 'return', '补测试')
        waiting = create_task(self.path, 1, {**self.data, 'title': '等验收的任务'})
        act(self.path, waiting, 2, 'claim')
        act(self.path, waiting, 2, 'submit', '成果')
        with connect(self.path) as db:
            worker = discover.my_tasks(db, 2)
            owner = discover.my_tasks(db, 1)
        self.assertEqual([task['title'] for task in worker['yours']], ['被退回的任务'])
        self.assertEqual(worker['yours'][0]['last_kind'], 'return')
        self.assertEqual([task['title'] for task in worker['waiting']], ['等验收的任务'])
        self.assertIn('等验收的任务', [task['title'] for task in owner['yours']])
        self.assertIn('入门文档', [task['title'] for task in owner['unclaimed']])
        page = self.clients[1].get('/mine').text
        self.assertIn('被退回，等你改', page)

    def test_two_lanes_keep_picked_directions_apart_from_history(self):
        data_task = create_task(self.path, 1, {**self.data, 'title': '清洗比赛提交记录', 'description': '去掉重复提交', 'tags': '数据'})
        self.finish(data_task)
        more_data = create_task(self.path, 1, {**self.data, 'title': '清洗题目标签', 'description': '去掉重复标签', 'tags': '数据'})
        graph = create_task(self.path, 1, {**self.data, 'title': '讲一次图论', 'tags': '图论'})
        set_interests(self.path, 2, '图论')
        with connect(self.path) as db:
            want = discover.recommend(db, 2, limit=10, lane='want')
            past = discover.recommend(db, 2, limit=10, lane='past', exclude={pick['task']['id'] for pick in want})
            self.assertEqual([pick['task']['id'] for pick in want], [graph])
            self.assertEqual(want[0]['reasons'][0], ('interest', '你选了「图论」'))
            self.assertNotIn(graph, [pick['task']['id'] for pick in past])
            # 第二排先放和你经历有关的任务，理由里不出现"你选了"
            self.assertEqual(past[0]['task']['id'], more_data)
            self.assertEqual(past[0]['reasons'][0][0], 'skill')
            self.assertFalse(any(kind == 'interest' for pick in past for kind, _ in pick['reasons']))
            self.assertEqual(discover.past_tags(db, 2), [('数据', 1)])
            # 方向条就是团队的标签表：起步标签带说明，发布者新写的「图论」排在最后
            options = discover.directions(db, ['图论'])
            self.assertEqual([option['tag'] for option in options][:6], ['实验', '数据', '论文', '代码', '讲解', '杂务'])
            self.assertEqual(options[1]['note'], '造数据、清洗、标注')
            graph_option = next(option for option in options if option['tag'] == '图论')
            self.assertTrue(graph_option['chosen'])
            self.assertEqual((graph_option['example'], graph_option['count']), ('讲一次图论', 1))
        worker = self.clients[1]
        home = worker.get('/').text
        self.assertIn('按你选的方向', home)
        self.assertIn('你常做', home)
        self.assertIn('data-lane-body="want"', worker.get('/picks/want').text)
        self.assertIn('讲一次图论', worker.get('/picks/want').text)
        self.assertNotIn('讲一次图论', worker.get('/picks/past').text)
        self.assertEqual(worker.get('/picks/other').status_code, 404)

    def test_directions_can_be_repicked_any_time(self):
        worker = self.clients[1]
        worker.get('/')
        with worker.session_transaction() as session:
            csrf = session['csrf']
        saved = worker.post('/me/interests', data={'csrf': csrf, 'tags': ['文档', '数据']}, headers={'Accept': 'application/json'})
        self.assertEqual(saved.json, {'interests': ['文档', '数据']})
        # 只能从团队的标签表里选，不能自己写
        made_up = worker.post('/me/interests', data={'csrf': csrf, 'tags': ['我编的方向']}, headers={'Accept': 'application/json'})
        self.assertIn('标签表', made_up.json['error'])
        self.assertNotIn('自己写一个', worker.get('/').text)
        saved = worker.post('/me/interests', data={'csrf': csrf, 'tags': ['论文']}, headers={'Accept': 'application/json'})
        self.assertEqual(saved.json, {'interests': ['论文']})
        cleared = worker.post('/me/interests', data={'csrf': csrf}, headers={'Accept': 'application/json'})
        self.assertEqual(cleared.json, {'interests': []})
        too_many = worker.post('/me/interests', data={'csrf': csrf, 'tags': [str(i) for i in range(9)]}, headers={'Accept': 'application/json'})
        self.assertEqual(too_many.status_code, 400)
        self.assertIn('最多 8 个方向', too_many.json['error'])
        # 方向条一直都在，不只给新人看
        self.post(worker, '/me/interests', {'tags': '数据'})
        self.assertIn('今天想往哪儿使劲', worker.get('/').text)

    def test_times_follow_each_viewers_own_time_zone(self):
        moment = datetime.now(timezone.utc) + timedelta(days=3)
        new_york = moment.astimezone(ZoneInfo('America/New_York'))
        owner = self.clients[0]
        owner.set_cookie('tz', 'America/New_York')
        self.post(owner, '/tasks/new', {**self.data, 'tags': '文档', 'title': '纽约时间截止',
                                         'deadline': new_york.replace(tzinfo=None).isoformat(timespec='minutes')})
        with connect(self.path) as db:
            stored = db.execute("SELECT deadline FROM tasks WHERE title='纽约时间截止'").fetchone()[0]
            task_id = db.execute("SELECT id FROM tasks WHERE title='纽约时间截止'").fetchone()[0]
        self.assertLess(abs((datetime.fromisoformat(stored) - moment).total_seconds()), 61)
        worker = self.clients[1]
        worker.set_cookie('tz', 'Asia/Tokyo')
        tokyo = moment.astimezone(ZoneInfo('Asia/Tokyo'))
        self.assertIn(f'{tokyo:%m/%d %H:%M}', worker.get(f'/tasks/{task_id}').text)
        self.assertIn(f'{new_york:%m/%d %H:%M}', owner.get(f'/tasks/{task_id}').text)
        self.assertIn('data-tz="Asia/Tokyo"', worker.get('/').text)
        # 不认识的时区退回团队时区，也不会出错
        worker.set_cookie('tz', '../../etc/passwd')
        self.assertIn('data-tz=""', worker.get('/').text)
        with connect(self.path) as db:
            for zone_name in ('Pacific/Kiritimati', 'Pacific/Pago_Pago'):
                week = discover.week_summary(db, ZoneInfo(zone_name))
                self.assertEqual(week['today'], datetime.now(ZoneInfo(zone_name)).weekday())

    def test_medal_case_lists_counts_history_and_where_to_get_more(self):
        self.finish(self.task_id)
        second = create_task(self.path, 1, {**self.data, 'title': '第二份文档'})
        self.finish(second, body='写得很清楚')
        create_task(self.path, 1, {**self.data, 'title': '一个加急的大任务', 'importance': 'major', 'urgency': 'urgent'})
        page = self.clients[1].get('/honors').text
        self.assertIn('data-count="2"', page)
        self.assertIn('class="tile locked" data-collection-key="major-urgent"', page)
        self.assertIn('1 个任务能拿', page)
        case = json.loads(page.split('<script type="application/json" id="case-data">')[1].split('</script>')[0])
        self.assertEqual(case['standard-normal']['count'], 2)
        self.assertEqual(case['standard-normal']['back']['quote'], '写得很清楚')
        self.assertEqual([item['title'] for item in case['standard-normal']['history']], ['第二份文档', '入门文档'])
        self.assertEqual(case['major-urgent']['can_get'], 1)
        self.assertIsNone(case['major-urgent']['back'])
        self.assertIn('class="inspect"', page)
        self.assertIn('Lv.', self.clients[1].get('/').text)
        self.assertIn('mini-case', self.clients[1].get('/').text)

    def age(self, task_id, days):
        with connect(self.path, write=True) as db:
            db.execute('UPDATE tasks SET created_at=? WHERE id=?',
                       ((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec='seconds'), task_id))

    def test_cold_tasks_pay_extra_experience(self):
        self.age(self.task_id, 6)
        with connect(self.path) as db:
            pick = next(p for p in discover.recommend(db, 2, limit=10) if p['task']['id'] == self.task_id)
            self.assertIn('cold', dict(pick['reasons']))
        self.assertIn('冷门 +20%', self.clients[1].get('/').text)
        self.finish(self.task_id)
        with connect(self.path) as db:
            honor = db.execute('SELECT * FROM honors WHERE task_id=?', (self.task_id,)).fetchone()
            self.assertEqual(honor['bonus'], 6)                       # 常规 30 经验的 20%
            self.assertEqual(progress.person_progress(db, 2)['xp'], 36)
        # 新鲜的任务不算冷门
        fresh = create_task(self.path, 1, self.data)
        self.finish(fresh)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT bonus FROM honors WHERE task_id=?', (fresh,)).fetchone()[0], 0)

    def test_titles_unlock_from_behaviour_and_arrive_once(self):
        for _ in range(3):
            self.finish(create_task(self.path, 1, {**self.data, 'urgency': 'urgent'}), body='救了急')
        worker = self.clients[1]
        self.assertIn('mailbox has-mail', worker.get('/').text)
        with connect(self.path) as db:
            board = {item['key']: item for item in titles.board(db, 2)}
            self.assertTrue(board['firefighter']['done'])
            self.assertEqual((board['praised']['have'], board['praised']['done']), (3, False))
            self.assertTrue({item['key'] for item in titles.board(db, 1) if item['done']} == set())
        revealed = self.post_json(worker, '/honors/reveal')
        self.assertIn('firefighter', [t['key'] for t in revealed['titles']])
        self.assertEqual(revealed['awards'][0]['debut'], True)
        self.assertEqual(self.post_json(worker, '/honors/reveal')['titles'], [])
        # 只能挂已经解锁的称号
        self.assertEqual(worker.post('/honors/title', data={'csrf': self.csrf(worker), 'title': 'stamper'},
                                     headers={'Accept': 'application/json'}).status_code, 400)
        self.post(worker, '/honors/title', {'title': 'firefighter'})
        page = worker.get('/honors').text
        self.assertIn('plate-seal', page)
        self.assertIn('救火队员', page)
        # 发布者也有自己的称号：发布的任务成了别人的第一枚勋章
        with connect(self.path) as db:
            self.assertEqual(titles.counts(db, 1)['mentor'], 1)

    def test_full_collection_is_its_own_moment(self):
        keys = list(MEDALS)
        for key in keys:
            importance, urgency = key.split('-')
            self.finish(create_task(self.path, 1, {**self.data, 'importance': importance, 'urgency': urgency}))
        awards = self.post_json(self.clients[1], '/honors/reveal')['awards']
        self.assertEqual([a['tier'] for a in awards][-1], 'all')
        self.assertIn('class="plate big complete"', self.clients[1].get('/honors').text)

    def euler(self, board):
        from collections import defaultdict
        _, nodes, edges = board
        adj = defaultdict(list)
        for i, (a, b) in enumerate(edges):
            adj[a].append((b, i)); adj[b].append((a, i))
        odd = [v for v in adj if len(adj[v]) % 2]
        stack, path, used = [odd[0] if odd else edges[0][0]], [], set()
        while stack:
            v = stack[-1]
            while adj[v] and adj[v][-1][1] in used:
                adj[v].pop()
            if adj[v]:
                w, i = adj[v].pop(); used.add(i); stack.append(w)
            else:
                path.append(stack.pop())
        return ','.join(map(str, path[::-1]))

    def award(self, worker, key):
        importance, urgency = key.split('-')
        self.finish(create_task(self.path, 1, {**self.data, 'importance': importance, 'urgency': urgency}), worker=worker)

    def test_one_stroke_is_free_to_replay_and_checked_on_the_server(self):
        stroke = lambda board: [int(n) for n in self.euler(board).split(',')]
        for level, board in enumerate(games.LEVELS, 1):
            self.assertTrue(games.check_stroke(board, stroke(board)), level)
        # 随机出的题由一次随机游走生成，每一道都画得出来
        for seed in range(200):
            self.assertTrue(games.check_stroke(games.random_board(seed), stroke(games.random_board(seed))), seed)
        worker = self.clients[1]
        self.assertEqual(self.post_json(worker, '/play/lines/1', {'stroke': '0,1'}, status=400)['error'], '还没有一笔走完所有的线。')
        # 前三关直接开，之后画完一关开下一关；画过的随便重玩，不花任何东西
        self.assertIn('先画完第 3 关', self.post_json(worker, '/play/lines/4', {'stroke': self.euler(games.LEVELS[3])}, status=400)['error'])
        for _ in range(3):
            solved = self.post_json(worker, '/play/lines/3', {'stroke': self.euler(games.LEVELS[2])})
        self.assertEqual((solved['first'], solved['next']), (False, '/play/lines?level=4'))
        self.assertTrue(self.post_json(worker, '/play/lines/4', {'stroke': self.euler(games.LEVELS[3])})['first'])
        # 每日一笔：全队同一题
        daily = games.daily_board(games.today())
        first = self.post_json(worker, '/play/lines/daily', {'stroke': self.euler(daily)})
        self.assertEqual((first['first'], first['daily']), (True, 1))
        self.assertFalse(self.post_json(worker, '/play/lines/daily', {'stroke': self.euler(daily)})['first'])
        self.assertEqual(self.post_json(self.clients[2], '/play/lines/daily', {'stroke': self.euler(daily)})['daily'], 2)
        # 随机一笔要一共 3 枚勋章
        self.assertEqual(worker.get('/play/lines/random/7').status_code, 302)
        for key in ('light-normal', 'light-normal', 'standard-normal'):
            self.award(2, key)
        self.assertIn('第 7 号', worker.get('/play/lines/random/7').text)
        self.assertIn('/play/lines/random', self.post_json(worker, '/play/lines/random/7', {'stroke': self.euler(games.random_board(7))})['next'])
        with connect(self.path, write=True) as db:
            db.executemany('INSERT OR IGNORE INTO lines_solved (user_id,level,solved_at) VALUES (2,?,?)',
                           [(n, '2026-01-01T00:00:00+00:00') for n in range(1, 13)])
            self.assertEqual(games._new_game_titles(db, 2)[0]['key'], 'oneline')

    def test_stamp_is_free_to_replay_and_rejects_impossible_results(self):
        worker = self.clients[1]
        run = self.post_json(worker, '/play/stamp/start')['run']
        self.assertIn('时间不对', self.post_json(worker, f'/play/stamp/{run}', {'score': 500, 'combo': 5}, status=400)['error'])
        with connect(self.path, write=True) as db:
            db.execute('UPDATE game_runs SET started_at=? WHERE id=?',
                       ((datetime.now(timezone.utc) - timedelta(seconds=31)).isoformat(timespec='seconds'), run))
        self.assertIn('分数不对', self.post_json(worker, f'/play/stamp/{run}', {'score': 10 ** 7, 'combo': 5}, status=400)['error'])
        result = self.post_json(worker, f'/play/stamp/{run}', {'score': 4200, 'combo': 31})
        self.assertEqual(result['best'], {'score': 4200, 'combo': 31, 'runs': 1})
        self.assertEqual(result['titles'][0]['key'], 'stamper')
        self.assertIn('已经结束', self.post_json(worker, f'/play/stamp/{run}', {'score': 9000, 'combo': 31}, status=400)['error'])
        for _ in range(5):   # 不花东西，想玩几局玩几局
            self.post_json(worker, '/play/stamp/start')
        # 玩法跟着勋章开：「急」勋章开加急日，「面」勋章开期末周
        self.assertIn('「急」勋章', self.post_json(worker, '/play/stamp/start', {'mode': 'rush'}, status=400)['error'])
        self.award(2, 'light-urgent')
        self.post_json(worker, '/play/stamp/start', {'mode': 'rush'})
        self.assertIn('「面」', self.post_json(worker, '/play/stamp/start', {'mode': 'finals'}, status=400)['error'])
        self.award(2, 'major-normal')
        started = self.post_json(worker, '/play/stamp/start', {'mode': 'finals'})
        self.assertEqual((started['seconds'], started['mode']), (45, 'finals'))
        with connect(self.path, write=True) as db:
            db.execute('UPDATE game_runs SET started_at=? WHERE id=?',
                       ((datetime.now(timezone.utc) - timedelta(seconds=35)).isoformat(timespec='seconds'), started['run']))
        self.assertIn('时间不对', self.post_json(worker, f"/play/stamp/{started['run']}", {'score': 10, 'combo': 1}, status=400)['error'])
        self.assertIn('期末周', worker.get('/play/stamp?mode=finals').text)

    def test_medals_open_block_parts_and_colours(self):
        worker = self.clients[1]
        with connect(self.path) as db:
            have = unlocks.unlocked(db, 2)
        self.assertEqual({item for item in have if item.startswith(('part:', 'color:'))},
                         {'color:ink', 'color:white', 'part:dot-s', 'part:bar-3', 'part:sq-2'})
        save = lambda parts, bg='paper', build_id=None, client=worker, status=200: client.post(
            '/play/blocks/save', json={'id': build_id, 'name': '小房子', 'bg': bg, 'parts': parts},
            headers={'X-CSRF-Token': self.csrf(client), 'Accept': 'application/json'})
        self.assertEqual(save([['sq-2', 'ink', 0, 0, 0]]).status_code, 200)
        self.assertIn('还没解锁', save([['quarter', 'ink', 0, 0, 0]]).json['error'])
        self.assertIn('还没解锁', save([['sq-2', 'cyan', 0, 0, 0]]).json['error'])
        self.assertIn('外面', save([['bar-3', 'ink', 14, 0, 0]]).json['error'])
        self.assertEqual(save([['bar-3', 'ink', 15, 0, 1]]).status_code, 200)     # 竖着放就放得下
        self.assertIn('不对', save([['sq-2', 'ink', 0, 0, 7]]).json['error'])
        self.assertEqual(worker.post('/play/blocks/save', json={'parts': []}).status_code, 400)   # 没带令牌
        # 拿到「线」勋章：多了青色和长线，颁奖时会说出来
        self.award(2, 'standard-normal')
        revealed = self.post_json(worker, '/honors/reveal')
        self.assertIn('青色', revealed['awards'][0]['opens'])
        self.assertIn('长线', revealed['awards'][0]['opens'])
        self.assertIn('class="new-dot"', worker.get('/').text)
        build = save([['bar-6', 'cyan', 2, 2, 0], ['medal-standard-normal', 'white', 5, 5, 0]], bg='cyan').json['id']
        # 只能改、挂、删自己的作品
        self.assertIn('不存在', save([], build_id=build, client=self.clients[2]).json['error'])
        self.assertTrue(self.post_json(worker, f'/play/blocks/{build}/show')['shown'])
        self.assertIn('plate-build', worker.get('/honors').text)
        play = worker.get('/play').text
        self.assertIn('积木墙', play)
        self.assertNotIn('class="new-dot"', worker.get('/').text)   # 进过游戏角，「新」就收起来
        self.assertIn('小房子', self.clients[2].get('/play').text)
        self.assertFalse(self.post_json(worker, f'/play/blocks/{build}/show')['shown'])
        self.assertEqual(self.post_json(self.clients[2], f'/play/blocks/{build}/show', status=400)['error'], '这件作品不存在。')
        self.post(worker, f'/play/blocks/{build}/delete', {})
        with connect(self.path) as db:
            self.assertEqual(len(blocks.mine(db, 2)), 2)
        self.assertIn('data-blocks', worker.get('/play/blocks').text)

    def test_old_ticket_ledger_is_dropped(self):
        legacy = str(Path(self.temp.name) / 'tickets.sqlite3')
        initialize(legacy)
        with connect(legacy, write=True) as db:
            db.execute('CREATE TABLE tickets (id INTEGER PRIMARY KEY, user_id INTEGER, delta INTEGER, reason TEXT, created_at TEXT)')
            db.execute("INSERT INTO tickets (user_id,delta,reason,created_at) VALUES (1,3,'task','2026-01-01')")
        initialize(legacy)
        with connect(legacy) as db:
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='tickets'").fetchone())

    def test_claps_come_back_as_a_note_once(self):
        self.finish(self.task_id)
        clap(self.path, self.task_id, 1)
        clap(self.path, self.task_id, 3)
        worker = self.clients[1]
        home = worker.get('/').text
        self.assertIn('为你鼓掌', home)
        self.assertIn('owner、other', home.replace('other、owner', 'owner、other'))
        self.assertNotIn('为你鼓掌', worker.get('/').text)

    def test_first_task_is_flagged_for_the_publisher(self):
        act(self.path, self.task_id, 2, 'claim')
        act(self.path, self.task_id, 2, 'submit', '成果')
        self.assertIn('的第一个任务', self.clients[0].get(f'/tasks/{self.task_id}').text)
        act(self.path, self.task_id, 1, 'accept', '欢迎加入')
        self.assertIn('的第一枚勋章', self.clients[2].get(f'/tasks/{self.task_id}').text)
        second = create_task(self.path, 1, self.data)
        act(self.path, second, 2, 'claim')
        self.assertNotIn('的第一个任务', self.clients[0].get(f'/tasks/{second}').text)

    def test_term_recap(self):
        from bounty import recap
        self.assertEqual(recap.term_of(datetime(2026, 1, 20, tzinfo=timezone.utc)), '2025-autumn')
        self.assertEqual(recap.term_of(datetime(2026, 3, 1, tzinfo=timezone.utc)), '2026-spring')
        self.assertEqual(recap.term_of(datetime(2026, 9, 1, tzinfo=timezone.utc)), '2026-autumn')
        self.assertIsNone(recap.bounds('2026-summer'))
        self.finish(self.task_id, body='写得很清楚')
        term = recap.term_of(datetime.now(timezone.utc))
        with connect(self.path) as db:
            data = recap.build(db, 2, term)
        self.assertEqual((data['done'], data['gained'], data['helped']), (1, 30, ['owner']))
        self.assertEqual(data['praises'][0]['text'], '写得很清楚')
        page = self.clients[1].get('/recap').text
        self.assertIn('写得很清楚', page)
        self.assertIn('data-save-recap', page)
        self.assertEqual(self.clients[1].get('/recap?term=nope').status_code, 404)

    def csrf(self, client):
        client.get('/auth/login')
        with client.session_transaction() as session:
            return session['csrf']

    def post_json(self, client, path, data=None, status=200):
        response = client.post(path, data={**(data or {}), 'csrf': self.csrf(client)}, headers={'Accept': 'application/json'})
        self.assertEqual(response.status_code, status, response.text)
        return response.json

    def test_team_tag_list_is_shared_by_members(self):
        owner, worker, other = self.clients
        self.assertEqual(owner.get('/tags').status_code, 200)
        self.assertIn('团队的标签表', owner.get('/tags').text)
        self.assertIn('标签管理', worker.get('/').text)
        self.assertEqual(self.app.test_client().get('/tags').status_code, 302)
        self.assertIn('加上了「图论」', self.post(owner, '/tags', {'name': '图论', 'note': '图算法的讲题和实验'}).text)
        self.assertIn('已经在表里', self.post(owner, '/tags', {'name': '图论'}).text)
        # 发布者从表里勾，也可以写新的；新的自动加进表
        page = self.post(owner, '/tasks/new', {**self.data, 'category': '', 'tags': ['图论', '数据'], 'new_tags': '线段树',
                                               'title': '讲一次线段树'})
        self.assertIn('讲一次线段树', page.text)
        with connect(self.path) as db:
            listing = {row['name']: row for row in tags.listing(db)}
            self.assertEqual(listing['线段树']['used'], 1)
            self.assertEqual(listing['图论']['note'], '图算法的讲题和实验')
            task_id = db.execute("SELECT id FROM tasks WHERE title='讲一次线段树'").fetchone()[0]
            self.assertEqual(discover.tags_by_task(db, [task_id])[task_id], ['图论', '数据', '线段树'])
        self.assertIn('图算法的讲题和实验', worker.get('/').text)    # 方向卡上能看到说明
        set_interests(self.path, 2, '线段树 图论')
        # 合并：线段树并进图论，任务和大家选的方向一起跟过去
        self.assertIn('已经并进「图论」', self.post(owner, '/tags/update', {'name': '线段树', 'note': '', 'rename': '图论'}).text)
        with connect(self.path) as db:
            self.assertEqual(discover.tags_by_task(db, [task_id])[task_id], ['图论', '数据'])
            self.assertEqual([row[0] for row in db.execute('SELECT tag FROM interests WHERE user_id=2')], ['图论'])
            self.assertNotIn('线段树', tags.names(db))
        # 改名、排序、拿掉
        self.post(owner, '/tags/update', {'name': '杂务', 'note': '跑腿', 'rename': '后勤'})
        self.post(owner, '/tags/move', {'name': '后勤', 'step': 'up'})
        with connect(self.path) as db:
            order = tags.names(db)
            self.assertEqual(order.index('后勤') + 1, order.index('讲解'))
        self.post(owner, '/tags/delete', {'name': '图论'})
        with connect(self.path) as db:
            self.assertNotIn('图论', tags.names(db))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM interests WHERE user_id=2').fetchone()[0], 0)
            self.assertEqual(discover.tags_by_task(db, [task_id])[task_id], ['图论', '数据'])   # 已有的任务不受影响
        self.assertIn('图论', owner.get('/tags').text)   # 出现在"挂在任务上但不在表里"
        self.assertEqual(self.post(owner, '/admin/admins', {'name': 'owner', 'on': '1'}).status_code, 404)
        self.assertNotIn('管理员', owner.get('/tags').text)
        self.assertIn('加上了「团队共建」', self.post(worker, '/tags', {'name': '团队共建'}).text)

    def test_existing_tags_become_the_team_list_on_upgrade(self):
        legacy = str(Path(self.temp.name) / 'old-tags.sqlite3')
        initialize(legacy)
        with connect(legacy, write=True) as db:
            db.execute('DROP TABLE org_tags')
            db.execute("INSERT INTO users (name,password) VALUES ('a','x')")
            db.execute("""INSERT INTO tasks (title,description,category,importance,urgency,deadline,requirements,owner_id,created_at)
                VALUES ('t','d','图论','light','normal','2099-01-01','r',1,'2026-01-01')""")
            db.executemany('INSERT INTO task_tags (task_id,tag) VALUES (1,?)', [('图论',), ('数据',)])
            db.execute("INSERT INTO interests (user_id,tag) VALUES (1,'PyTorch')")
        initialize(legacy)
        with connect(legacy) as db:
            self.assertEqual(set(tags.names(db)), {'图论', '数据', 'PyTorch'})

    def test_v11_helpful_marks_become_claps(self):
        self.finish(self.task_id)
        with connect(self.path, write=True) as db:
            db.execute('CREATE TABLE appreciations (task_id INTEGER, user_id INTEGER, created_at TEXT, PRIMARY KEY(task_id,user_id))')
            db.executemany('INSERT INTO appreciations VALUES (?,?,?)', [(self.task_id, 1, '2026-10-14T00:00:00+00:00'),
                                                                        (self.task_id, 3, '2026-10-14T00:00:00+00:00'),
                                                                        (self.task_id, 2, '2026-10-14T00:00:00+00:00')])
        initialize(self.path)
        initialize(self.path)
        with connect(self.path) as db:
            # 自己给自己的那条不算；重复启动不会重复加
            self.assertEqual(sorted(row[0] for row in db.execute('SELECT user_id FROM claps WHERE task_id=?', (self.task_id,))), [1, 3])


    def test_collection_link_finds_same_owned_medal(self):
        self.finish(self.task_id)
        match = create_task(self.path, 1, {**self.data, 'title': '继续整理'})
        wrong = create_task(self.path, 1, {**self.data, 'title': '加急整理', 'urgency': 'urgent'})
        mine = create_task(self.path, 2, {**self.data, 'title': '自己发布'})
        page = self.clients[1].get('/honors').text
        data = json.loads(page.split('<script type="application/json" id="case-data">')[1].split('</script>')[0])
        page = self.clients[1].get(data['standard-normal']['find']).text
        self.assertIn(f'data-task="{match}"', page)
        self.assertNotIn(f'data-task="{wrong}"', page)
        self.assertNotIn(f'data-task="{mine}"', page)

    def test_all_pending_clap_notes_are_displayed(self):
        for n in range(4):
            task = create_task(self.path, 1, {**self.data, 'title': f'鼓掌任务{n}'})
            self.finish(task)
            clap(self.path, task, 3)
        self.assertEqual(self.clients[1].get('/').text.count('为你鼓掌'), 4)
        self.assertNotIn('为你鼓掌', self.clients[1].get('/').text)

    def test_comment_does_not_hide_return_reason(self):
        act(self.path, self.task_id, 2, 'claim')
        act(self.path, self.task_id, 2, 'submit', '成果')
        act(self.path, self.task_id, 1, 'return', '补充边界样例')
        act(self.path, self.task_id, 2, 'comment', '收到')
        page = self.clients[1].get('/mine').text
        self.assertIn('被退回，等你改', page)
        self.assertIn('补充边界样例', page)


if __name__ == '__main__':
    unittest.main()
