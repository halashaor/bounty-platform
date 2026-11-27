import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

from app import create_app
from bounty import shame, teams
from bounty.db import connect, initialize
from bounty.service import InvalidAction, act, create_task


class FormDepth(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.depth = self.max_depth = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'form':
            self.depth += 1
            self.max_depth = max(self.max_depth, self.depth)

    def handle_endtag(self, tag):
        if tag == 'form':
            self.depth -= 1


class ShamePillarTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'test.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'test'})
        self.clients = []
        for name in ('owner', 'worker', 'other'):
            client = self.app.test_client()
            self.post(client, '/auth/register', {'name': name, 'password': 'test-password'})
            self.clients.append(client)
        self.data = dict(title='造评测数据', description='补齐边界数据', requirements='提交脚本与数据',
                         category='数据', importance='standard', urgency='normal', deadline=self.future(3))
        self.task_id = create_task(self.path, 1, self.data)

    def tearDown(self):
        self.temp.cleanup()

    def future(self, days):
        return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec='seconds')

    def csrf(self, client):
        client.get('/auth/login')
        with client.session_transaction() as session:
            return session['csrf']

    def post(self, client, path, data):
        return client.post(path, data={**data, 'csrf': self.csrf(client)}, follow_redirects=True)

    def test_pin_requires_publisher_worker_and_reason(self):
        # 没人接任务时不能钉
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 1, 2, '还没接就想钉')
        act(self.path, self.task_id, 2, 'join')
        # 理由为空或超长报错
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 1, 2, '   ')
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 1, 2, '超' * 201)
        # 非发布者不能钉
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 3, 2, '路人乱钉')
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 2, 2, '自己钉自己')
        # 不能钉没接任务的人
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 1, 3, 'other 没接这个任务')
        # 只要发布者写明理由就能钉（即使未逾期、未退回）
        pin_id = shame.pin(self.path, self.task_id, 1, 2, '进度严重落后且未沟通', 'overdue')
        self.assertGreater(pin_id, 0)
        # 同一任务同一人不能重复钉
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 1, 2, '再钉一次')

    def test_visible_to_everyone_on_task_and_shame_page_and_lift_anytime(self):
        act(self.path, self.task_id, 2, 'join')
        res = self.post(self.clients[0], f'/tasks/{self.task_id}/shame/pin',
                        {'user_id': '2', 'kind': 'rejected', 'reason': '边界用例全部挂了'})
        self.assertEqual(res.status_code, 200)

        # 所有人（发布者、被钉者、第三方队友）进任务详情页和独立耻辱柱页都能看到动效展台与理由
        for client in self.clients:
            detail_html = client.get(f'/tasks/{self.task_id}').text
            self.assertIn('data-shame-stage', detail_html)
            self.assertIn('边界用例全部挂了', detail_html)
            self.assertIn('shame.js', detail_html)
            self.assertEqual(FormDepth(detail_html).max_depth, 1)

            shame_html = client.get('/shame').text
            self.assertIn('data-shame-stage', shame_html)
            self.assertIn('造评测数据', shame_html)
            self.assertIn('边界用例全部挂了', shame_html)
            self.assertEqual(FormDepth(shame_html).max_depth, 1)

        with connect(self.path) as db:
            pin = shame.active_for_task(db, self.task_id)[0]
            self.assertEqual(pin['kind'], 'rejected')
            self.assertEqual(pin['lashes'], 0)

        # 第三方队友帮忙抽一鞭（JSON 接口 + 持久化计数）
        lash_res = self.clients[2].post(
            f'/shame/{pin["id"]}/lash',
            headers={'Accept': 'application/json', 'X-CSRF-Token': self.csrf(self.clients[2])},
        )
        self.assertEqual(lash_res.status_code, 200)
        self.assertEqual(json.loads(lash_res.text)['lashes'], 1)

        # 第三方不能拔出钉子
        with self.assertRaises(InvalidAction):
            shame.lift(self.path, pin['id'], 3)
        with self.assertRaises(InvalidAction):
            shame.lift(self.path, pin['id'], 2)

        # 发布者随时可以拔出钉子（从 /shame 拔出并跳回 /shame）
        lift_res = self.post(self.clients[0], f'/shame/{pin["id"]}/lift', {'next': '/shame'})
        self.assertEqual(lift_res.status_code, 200)
        self.assertIn('现在柱子上干干净净', lift_res.text)
        self.assertIn('最近已拔出', lift_res.text)

        # 拔出后不能再抽，事件时间线保留完整记录
        with self.assertRaises(InvalidAction):
            shame.lash(self.path, pin['id'])
        with connect(self.path) as db:
            self.assertEqual(shame.active_count(db), 0)
            kinds = [row['kind'] for row in db.execute('SELECT kind FROM events WHERE task_id=? ORDER BY id', (self.task_id,))]
            self.assertIn('shame_pin', kinds)
            self.assertIn('shame_unpin', kinds)

    def test_big_task_owner_can_manage_piece_shame_and_reinit_idempotent(self):
        big_id = create_task(self.path, 1, {**self.data, 'kind': 'team', 'title': '周六模拟赛'})
        act(self.path, big_id, 2, 'join')
        piece_id = teams.split(self.path, big_id, 2, {'title': '造 E 题数据', 'tag': '数据', 'kind': 'standard-normal'})
        act(self.path, piece_id, 3, 'join')

        # 大任务发布者（用户 1）可以把分工执行人（用户 3）钉上耻辱柱并拔出
        pin_id = shame.pin(self.path, piece_id, 1, 3, '模拟赛开赛前还没交数据', 'overdue')
        shame.lift(self.path, pin_id, 1, '已补交')

        # 重复 initialize 幂等且保留原记录
        initialize(self.path)
        with connect(self.path) as db:
            row = db.execute('SELECT status,lift_note FROM shame_pins WHERE id=?', (pin_id,)).fetchone()
            self.assertEqual((row['status'], row['lift_note']), ('lifted', '已补交'))


if __name__ == '__main__':
    unittest.main()
