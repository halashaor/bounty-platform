import concurrent.futures
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app import MY_TURN, create_app
from bounty import discover, extend, progress, teams
from bounty.db import connect, initialize
from bounty.service import InvalidAction, act, create_task


class Forms(HTMLParser):
    """检查新增表单的选中项和嵌套，免得提交时串到别的动作。"""
    def __init__(self, html):
        super().__init__()
        self.depth = self.max_depth = 0
        self.inputs = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.depth += 1
            self.max_depth = max(self.max_depth, self.depth)
        elif tag == 'input':
            self.inputs.append(attrs)

    def handle_endtag(self, tag):
        if tag == 'form':
            self.depth -= 1


class ExtendAssignTest(unittest.TestCase):
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
                         category='文档', importance='standard', urgency='normal', deadline=self.future(2))
        self.task_id = create_task(self.path, 1, self.data)
        self.base = f'/tasks/{self.task_id}'

    def tearDown(self):
        self.temp.cleanup()

    def future(self, days):
        return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec='seconds')

    def post(self, client, path, data):
        client.get('/auth/login')
        with client.session_transaction() as session:
            csrf = session['csrf']
        return client.post(path, data={**data, 'csrf': csrf}, follow_redirects=True)

    def row(self, task_id=None):
        with connect(self.path) as db:
            return db.execute('SELECT * FROM tasks WHERE id=?', (task_id or self.task_id,)).fetchone()

    def records(self, task_id=None):
        with connect(self.path) as db:
            return db.execute('SELECT * FROM extensions WHERE task_id=? ORDER BY id', (task_id or self.task_id,)).fetchall()

    def events(self, task_id=None):
        with connect(self.path) as db:
            return db.execute('SELECT * FROM events WHERE task_id=? ORDER BY id', (task_id or self.task_id,)).fetchall()

    def claim_and_ask(self):
        act(self.path, self.task_id, 2, 'claim')
        extend.ask(self.path, self.task_id, 2, self.future(4), '数据还没到', timezone.utc)

    def test_solo_assignment_follows_the_existing_workflow(self):
        task = create_task(self.path, 1, {**self.data, 'assignee': '2'})
        row = self.row(task)
        self.assertEqual((row['status'], row['assignee_id'], row['cold']), ('active', 2, 0))
        self.assertEqual([(e['kind'], e['user_id'], e['body']) for e in self.events(task)], [('assign', 1, '指定 worker 来做。')])
        with self.assertRaises(InvalidAction):
            act(self.path, task, 3, 'claim')
        with connect(self.path) as db:
            self.assertNotIn(task, [row['id'] for row in discover.open_tasks(db, 3)])
        self.assertNotIn(f'data-task="{task}"', self.clients[2].get('/').text)
        act(self.path, task, 2, 'submit', '文档好了')
        act(self.path, task, 1, 'accept')
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT user_id FROM honors WHERE task_id=?', (task,)).fetchone()[0], 2)
            self.assertEqual(progress.person_progress(db, 2)['xp'], 30)

    def test_assignment_rejects_self_unknown_and_invalid_ids_atomically(self):
        for kind in ('solo', 'team'):
            for uid in ('1', '9999', 'bad', '-1', '9' * 100):
                with self.subTest(kind=kind, uid=uid), self.assertRaises(InvalidAction):
                    create_task(self.path, 1, {**self.data, 'kind': kind, 'assignee': uid, 'members': [uid]})
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 1)

    def test_team_assignment_deduplicates_and_checks_capacity(self):
        task = create_task(self.path, 1, {**self.data, 'kind': 'team', 'members': ['2', '3', '2'], 'team_size': '2'})
        self.assertEqual(self.row(task)['status'], 'active')
        with connect(self.path) as db:
            self.assertEqual([p['id'] for p in teams.members_by_task(db, [task])[task]], [2, 3])
        self.assertEqual(self.events(task)[0]['body'], '指定 worker、other 一起做。')
        with self.assertRaisesRegex(InvalidAction, '指定的人比想要的人数还多。'):
            create_task(self.path, 1, {**self.data, 'kind': 'team', 'members': ['2', '3'], 'team_size': '2', 'join_self': '1'})
        together = create_task(self.path, 1, {**self.data, 'kind': 'team', 'members': ['2'], 'team_size': '2', 'join_self': '1'})
        self.assertEqual([e['kind'] for e in self.events(together)], ['join', 'assign'])
        spare = create_task(self.path, 1, {**self.data, 'kind': 'team', 'members': ['2'], 'team_size': '2'})
        act(self.path, spare, 3, 'join')
        self.assertEqual(self.row(spare)['status'], 'active')

    def test_assignment_reads_only_the_fields_for_its_kind(self):
        solo = create_task(self.path, 1, {**self.data, 'members': ['1', '999']})
        team = create_task(self.path, 1, {**self.data, 'kind': 'team', 'assignee': '1'})
        self.assertEqual((self.row(solo)['status'], self.row(solo)['assignee_id']), ('open', None))
        self.assertEqual(self.row(team)['status'], 'open')
        self.assertEqual(self.events(solo), [])
        self.assertEqual(self.events(team), [])

    def test_assignment_pages_flash_and_keep_choices_on_error(self):
        owner = self.clients[0]
        fields = Forms(owner.get('/tasks/new').text).inputs
        choices = [i['value'] for i in fields if i.get('name') in ('assignee', 'members')]
        self.assertIn('2', choices)
        self.assertIn('3', choices)
        self.assertNotIn('1', choices)
        page = owner.get('/tasks/new').text
        self.assertIn('worker', page)
        self.assertIn('other', page)
        # 页面导航本来就显示自己，只检查指定人选里没有自己
        form = page.split('指定谁来做')[1].split('<div class="two team-only">')[0]
        self.assertNotIn('owner', form)
        failed = self.post(owner, '/tasks/new', {**self.data, 'title': '', 'assignee': '2', 'members': ['2', '3']})
        selected = [(i.get('name'), i.get('value')) for i in Forms(failed.text).inputs if 'checked' in i]
        self.assertIn(('assignee', '2'), selected)
        self.assertIn(('members', '2'), selected)
        self.assertIn(('members', '3'), selected)
        assigned = self.post(owner, '/tasks/new', {**self.data, 'assignee': '2'})
        self.assertIn('任务已发布，交给 worker 了。', assigned.text)
        team = self.post(owner, '/tasks/new', {**self.data, 'kind': 'team', 'members': ['2', '3'], 'assignee': '1'})
        self.assertIn('大任务已发布，指定的人已经加进来了。', team.text)
        with connect(self.path) as db:
            task = db.execute('SELECT MAX(id) FROM tasks').fetchone()[0]
            self.assertEqual([p['id'] for p in teams.members_by_task(db, [task])[task]], [2, 3])

    def test_ask_validates_role_reason_deadline_and_duplicate(self):
        act(self.path, self.task_id, 2, 'claim')
        for uid, date, reason in ((2, self.future(1), '没做完'), (2, self.data['deadline'], '没做完'),
                                  (2, self.future(-1), '没做完'), (2, 'bad', '没做完'),
                                  (2, self.future(4), ''), (2, self.future(4), '字' * 201),
                                  (3, self.future(4), '没做完'), (1, self.future(4), '没做完')):
            with self.subTest(uid=uid, date=date, reason=reason), self.assertRaises(InvalidAction):
                extend.ask(self.path, self.task_id, uid, date, reason, timezone.utc)
        extend.ask(self.path, self.task_id, 2, self.future(4), '数据还没到', timezone.utc)
        with self.assertRaisesRegex(InvalidAction, '已经有一个延期申请在等回复了。'):
            extend.ask(self.path, self.task_id, 2, self.future(5), '再等等', timezone.utc)
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.row()['deadline'], self.data['deadline'])
        self.assertEqual(self.events()[-1]['body'], '数据还没到')

    def test_owner_approves_and_pending_appears_in_mine(self):
        self.claim_and_ask()
        self.assertIn('申请延期，等你回复', self.clients[0].get('/mine').text)
        self.assertIn('申请了延期，等 owner 回复', self.clients[1].get('/mine').text)
        with connect(self.path) as db:
            self.assertEqual([t['id'] for t in discover.my_tasks(db, 1)['yours']], [self.task_id])
            self.assertEqual(db.execute(f'SELECT COUNT(*) FROM tasks t WHERE {MY_TURN}', {'me': 1}).fetchone()[0], 1)
        page = self.post(self.clients[0], self.base + '/extend/yes', {'body': '好，多检查一遍'})
        record = self.records()[0]
        self.assertEqual((record['status'], record['decided_by']), ('approved', 1))
        self.assertIsNotNone(record['decided_at'])
        self.assertEqual(self.row()['deadline'], record['new_deadline'])
        self.assertEqual((self.events()[-1]['kind'], self.events()[-1]['user_id'], self.events()[-1]['body']),
                         ('extend', 1, '好，多检查一遍'))
        self.assertIn('已同意，截止时间延后了。', page.text)
        self.assertIn('延期过 1 次', page.text)
        self.assertIn('· 原定 ', page.text)
        self.assertNotIn('申请延期，等你回复', self.clients[0].get('/mine').text)

    def test_rejection_keeps_deadline_and_allows_another_request(self):
        self.claim_and_ask()
        result = self.post(self.clients[0], self.base + '/extend/no', {})
        self.assertIn('已回复，这次不延。', result.text)
        self.assertEqual(self.row()['deadline'], self.data['deadline'])
        self.assertEqual(self.records()[0]['status'], 'rejected')
        self.assertEqual((self.events()[-1]['kind'], self.events()[-1]['body']), ('extend_no', '这次先不延。'))
        extend.ask(self.path, self.task_id, 2, self.future(5), '重新申请', timezone.utc)
        extend.decide(self.path, self.task_id, 1, True)
        self.assertEqual(self.events()[-1]['body'], '同意延期。')

    def test_expired_open_task_can_be_claimed_after_push(self):
        with connect(self.path, write=True) as db:
            db.execute('UPDATE tasks SET deadline=? WHERE id=?', (self.future(-1), self.task_id))
        with self.assertRaises(InvalidAction):
            act(self.path, self.task_id, 3, 'claim')
        page = self.clients[0].get(self.base).text
        self.assertIn(self.base + '/extend/push', page)
        result = self.post(self.clients[0], self.base + '/extend/push', {'deadline': self.future(3)})
        self.assertIn('截止时间已延后。', result.text)
        self.assertEqual((self.records()[0]['status'], self.records()[0]['decided_by']), ('approved', 1))
        self.assertEqual(self.events()[-1]['body'], '把截止时间往后延了。')
        act(self.path, self.task_id, 3, 'claim')
        self.assertEqual(self.row()['assignee_id'], 3)

    def test_team_lead_can_reply_to_a_piece_and_sees_it_in_mine(self):
        team = create_task(self.path, 1, {**self.data, 'kind': 'team', 'members': ['2']})
        piece = teams.split(self.path, team, 2, dict(title='造数据', tag='数据', kind='standard-normal'))
        act(self.path, piece, 3, 'claim')
        extend.ask(self.path, piece, 3, self.future(4), '数据没到', timezone.utc)
        with connect(self.path) as db:
            self.assertTrue(extend.checker(db, self.row(piece), 1))
            self.assertTrue(extend.checker(db, self.row(piece), 2))
            self.assertFalse(extend.checker(db, self.row(piece), 3))
            self.assertIn(piece, [t['id'] for t in discover.my_tasks(db, 1)['yours']])
            self.assertIn(piece, [t['id'] for t in db.execute(f'SELECT t.id FROM tasks t WHERE {MY_TURN}', {'me': 1})])
        self.assertIn('申请延期，等你回复', self.clients[0].get('/mine').text)
        self.assertIn('other 申请延期', self.clients[0].get(f'/tasks/{piece}').text)
        extend.decide(self.path, piece, 1, True)
        self.assertEqual(self.row(piece)['deadline'], self.records(piece)[0]['new_deadline'])
        self.assertEqual(self.row(team)['deadline'], self.data['deadline'])

    def test_piece_claimed_by_team_lead_cannot_be_self_approved(self):
        team = create_task(self.path, 1, {**self.data, 'kind': 'team', 'members': ['2']})
        piece = teams.split(self.path, team, 2, dict(title='造数据', tag='数据', kind='standard-normal'))
        act(self.path, piece, 1, 'claim')
        extend.ask(self.path, piece, 1, self.future(4), '需要更多时间', timezone.utc)
        with self.assertRaises(InvalidAction):
            extend.decide(self.path, piece, 1, True)
        with self.assertRaises(InvalidAction):
            extend.push(self.path, piece, 1, self.future(5), '', timezone.utc)
        page = self.clients[0].get(f'/tasks/{piece}').text
        self.assertNotIn(f'/tasks/{piece}/extend/yes', page)
        self.assertNotIn('申请延期，等你回复', self.clients[0].get('/mine').text)
        extend.decide(self.path, piece, 2, True)

    def test_submission_closes_pending_for_solo_and_team(self):
        owner, worker, _ = self.clients
        for kind in ('solo', 'team'):
            with self.subTest(kind=kind):
                task = create_task(self.path, 1, {**self.data, 'kind': kind, 'assignee': '2', 'members': ['2']})
                base = f'/tasks/{task}'
                extend.ask(self.path, task, 2, self.future(4), '需要更多时间', timezone.utc)
                self.assertIn('申请延期，等你回复', owner.get('/mine').text)
                self.post(worker, base + '/submit', {'body': '文档好了'})
                self.assertEqual(self.row(task)['status'], 'review')
                self.assertEqual(self.records(task)[0]['status'], 'closed')
                page = owner.get('/mine').text
                self.assertNotIn('申请延期，等你回复', page)
                self.assertIn('等你验收', page)
                self.assertNotIn('申请了延期，等 owner 回复', worker.get('/mine').text)
                self.assertNotIn('已申请延到', worker.get(base).text)
                act(self.path, task, 1, 'return', '补充安装步骤')
                extend.ask(self.path, task, 2, self.future(5), '还要补说明', timezone.utc)
                self.assertEqual([row['status'] for row in self.records(task)], ['closed', 'pending'])
                act(self.path, task, 2, 'submit', '补好了')

    def test_mine_ignores_stale_pending_requests_outside_active(self):
        owner, worker, _ = self.clients
        for kind in ('solo', 'team'):
            with self.subTest(kind=kind):
                task = create_task(self.path, 1, {**self.data, 'kind': kind, 'assignee': '2', 'members': ['2']})
                extend.ask(self.path, task, 2, self.future(4), '需要更多时间', timezone.utc)
                # 模拟旧数据留下的申请，待验收时仍然显示验收提示
                with connect(self.path, write=True) as db:
                    db.execute("UPDATE tasks SET status='review' WHERE id=?", (task,))
                page = owner.get('/mine').text
                self.assertNotIn('申请延期，等你回复', page)
                self.assertIn('等你验收', page)
                page = worker.get('/mine').text
                self.assertNotIn('申请了延期，等 owner 回复', page)
                self.assertIn('等 owner 验收', page)

    def test_acceptance_closes_pending_for_solo_and_team(self):
        self.claim_and_ask()
        act(self.path, self.task_id, 2, 'submit', '文档好了')
        with self.assertRaises(InvalidAction):
            extend.decide(self.path, self.task_id, 1, True)
        # 旧数据可能在提交后仍有申请，验收也要能关掉
        with connect(self.path, write=True) as db:
            db.execute("UPDATE extensions SET status='pending' WHERE task_id=?", (self.task_id,))
        act(self.path, self.task_id, 1, 'accept')
        self.assertEqual(self.records()[0]['status'], 'closed')
        task = create_task(self.path, 1, {**self.data, 'kind': 'team', 'members': ['2', '3']})
        extend.ask(self.path, task, 3, self.future(4), '需要更多时间', timezone.utc)
        act(self.path, task, 2, 'submit', '做好了')
        with connect(self.path, write=True) as db:
            db.execute("UPDATE extensions SET status='pending' WHERE task_id=?", (task,))
        act(self.path, task, 1, 'accept')
        self.assertEqual(self.records(task)[0]['status'], 'closed')

    def test_detail_panels_forms_and_route_guards(self):
        owner, worker, other = self.clients
        self.claim_and_ask()
        page = owner.get(self.base).text
        self.assertIn('worker 申请延期', page)
        self.assertIn('原定截止', page)
        self.assertIn('想延到', page)
        self.assertIn('同意延期', page)
        self.assertIn('不同意', page)
        page = worker.get(self.base).text
        self.assertIn('已申请延到', page)
        self.assertIn('等 owner 回复。', page)
        self.assertNotIn(self.base + '/extend/ask', page)
        self.assertEqual(Forms(page).max_depth, 1)
        self.assertNotIn(self.base + '/extend/', other.get(self.base).text)
        with owner.session_transaction() as session:
            csrf = session['csrf']
        response = owner.post(self.base + '/extend/no', data={'csrf': csrf})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('#extend'))
        page = worker.get(self.base).text
        self.assertIn('来不及？申请延期', page)
        self.assertEqual(Forms(page).max_depth, 1)
        self.assertEqual(worker.post(self.base + '/extend/ask').status_code, 400)
        self.assertEqual(self.post(owner, self.base + '/extend/unknown', {}).status_code, 404)
        self.assertIn('只有验收人', self.post(other, self.base + '/extend/push', {'deadline': self.future(4)}).text)

    def test_expired_request_cannot_be_approved_but_can_be_rejected(self):
        self.claim_and_ask()
        with patch('bounty.extend.now', return_value=self.future(5)):
            with self.assertRaisesRegex(InvalidAction, '申请的时间已经过了，让对方重新申请。'):
                extend.decide(self.path, self.task_id, 1, True)
            self.assertEqual(self.records()[0]['status'], 'pending')
            self.assertEqual(self.row()['deadline'], self.data['deadline'])
            extend.decide(self.path, self.task_id, 1, False)
        self.assertEqual(self.records()[0]['status'], 'rejected')

    def test_push_closes_request_without_changing_rewards_or_cold(self):
        self.claim_and_ask()
        with connect(self.path, write=True) as db:
            db.execute('UPDATE tasks SET cold=1 WHERE id=?', (self.task_id,))
        before = self.row()
        extend.push(self.path, self.task_id, 1, self.future(6), '多检查一遍', timezone.utc)
        self.assertEqual([r['status'] for r in self.records()], ['closed', 'approved'])
        self.assertEqual(self.records()[1]['old_deadline'], self.data['deadline'])
        after = self.row()
        for field in ('cold', 'importance', 'urgency', 'assignee_id', 'status'):
            self.assertEqual(before[field], after[field])
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM honors').fetchone()[0], 0)
            self.assertEqual(progress.person_progress(db, 2)['xp'], 0)
        self.assertEqual(self.events()[-1]['body'], '多检查一遍')

    def test_team_members_ask_but_publisher_only_pushes(self):
        task = create_task(self.path, 1, {**self.data, 'kind': 'team', 'members': ['2'], 'join_self': '1'})
        piece = teams.split(self.path, task, 1, dict(title='造数据', tag='数据', kind='standard-normal'))
        owner_page = self.clients[0].get(f'/tasks/{task}').text
        self.assertIn(f'/tasks/{task}/extend/push', owner_page)
        self.assertNotIn(f'/tasks/{task}/extend/ask', owner_page)
        with self.assertRaises(InvalidAction):
            extend.ask(self.path, task, 1, self.future(4), '没做完', timezone.utc)
        with self.assertRaises(InvalidAction):
            extend.ask(self.path, task, 3, self.future(4), '没做完', timezone.utc)
        extend.ask(self.path, task, 2, self.future(4), '没做完', timezone.utc)
        with self.assertRaises(InvalidAction):
            extend.decide(self.path, task, 2, True)
        self.assertIn('申请延期，等你回复', self.clients[0].get('/mine').text)
        self.assertIn('等 owner 回复。', self.clients[1].get(f'/tasks/{task}').text)
        extend.push(self.path, task, 1, self.future(5), '', timezone.utc)
        self.assertEqual(self.row(piece)['deadline'], self.data['deadline'])

    def test_push_and_decide_reject_invalid_state_permissions_and_long_notes(self):
        self.claim_and_ask()
        for uid in (2, 3):
            with self.assertRaises(InvalidAction):
                extend.decide(self.path, self.task_id, uid, True)
            with self.assertRaises(InvalidAction):
                extend.push(self.path, self.task_id, uid, self.future(4), '', timezone.utc)
        with self.assertRaises(InvalidAction):
            extend.decide(self.path, self.task_id, 1, True, '字' * 201)
        for deadline, note in ((self.future(1), ''), (self.future(-1), ''), (self.future(4), '字' * 201)):
            with self.assertRaises(InvalidAction):
                extend.push(self.path, self.task_id, 1, deadline, note, timezone.utc)
        act(self.path, self.task_id, 2, 'submit', '交付')
        for status in ('review', 'done'):
            with self.assertRaises(InvalidAction):
                extend.push(self.path, self.task_id, 1, self.future(4), '', timezone.utc)
            with self.assertRaises(InvalidAction):
                extend.ask(self.path, self.task_id, 2, self.future(4), '没做完', timezone.utc)
            if status == 'review':
                act(self.path, self.task_id, 1, 'accept')

    def test_timezone_input_and_output_do_not_leak_into_events(self):
        act(self.path, self.task_id, 2, 'claim')
        requested = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(days=4)
        worker = self.clients[1]
        worker.set_cookie('tz', 'America/New_York')
        local = requested.astimezone(ZoneInfo('America/New_York')).strftime('%Y-%m-%dT%H:%M')
        page = self.post(worker, self.base + '/extend/ask', {'deadline': local, 'body': '数据没到'})
        self.assertIn('已申请延期，等 owner 回复。', page.text)
        self.assertEqual(self.records()[0]['new_deadline'], requested.isoformat(timespec='seconds'))
        owner = self.clients[0]
        owner.set_cookie('tz', 'Asia/Shanghai')
        self.assertIn(requested.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%m/%d %H:%M'), owner.get(self.base).text)
        self.assertIn(requested.astimezone(ZoneInfo('America/New_York')).strftime('%m/%d %H:%M'), worker.get(self.base).text)
        extend.decide(self.path, self.task_id, 1, True)
        later = requested + timedelta(days=2)
        self.post(owner, self.base + '/extend/push', {
            'deadline': later.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%dT%H:%M')})
        self.assertEqual(self.row()['deadline'], later.isoformat(timespec='seconds'))
        self.assertEqual([e['body'] for e in self.events() if e['kind'].startswith('extend')],
                         ['数据没到', '同意延期。', '把截止时间往后延了。'])

    def test_concurrent_requests_and_decisions_have_one_winner(self):
        act(self.path, self.task_id, 2, 'claim')
        def ask(_):
            try:
                extend.ask(self.path, self.task_id, 2, self.future(4), '没做完', timezone.utc)
                return True
            except InvalidAction:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sum(executor.map(ask, range(2))), 1)
        def decide(_):
            try:
                extend.decide(self.path, self.task_id, 1, True)
                return True
            except InvalidAction:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sum(executor.map(decide, range(2))), 1)
        self.assertEqual(len(self.records()), 1)
        self.assertEqual([e['kind'] for e in self.events()], ['claim', 'extend_ask', 'extend'])

    def test_extensions_are_added_to_existing_databases_idempotently(self):
        before = dict(self.row())
        with connect(self.path, write=True) as db:
            db.execute('DROP TABLE extensions')
            sql_before = db.execute("SELECT sql FROM sqlite_master WHERE name='tasks'").fetchone()[0]
        initialize(self.path)
        self.claim_and_ask()
        initialize(self.path)
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT sql FROM sqlite_master WHERE name='tasks'").fetchone()[0], sql_before)
            self.assertEqual(self.records()[0]['status'], 'pending')
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
            documented = Path(__file__).resolve().parents[1] / 'database/schema.sql'
            schema = documented.read_text().split('CREATE TABLE IF NOT EXISTS extensions')[1]
            from bounty.db import SCHEMA
            self.assertEqual(schema.strip(), SCHEMA.split('CREATE TABLE IF NOT EXISTS extensions')[1].strip())
        self.assertEqual(self.row()['title'], before['title'])


if __name__ == '__main__':
    unittest.main()
