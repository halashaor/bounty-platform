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

    def test_three_options_and_conditional_reason_validation(self):
        # 没人接任务时不能钉
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 1, 2, '', 'overdue')
        act(self.path, self.task_id, 2, 'join')

        # 权限校验与未知类型
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 3, 2, '', 'overdue')
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 2, 2, '', 'overdue')
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 1, 3, '', 'overdue')
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 1, 2, '', 'invalid_kind')

        # 选「其他」时必须填写理由且不超过 200 字
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 1, 2, '   ', 'other')
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 1, 2, '超' * 201, 'other')

        # 选「逾期」无需理由直接可钉
        pin1 = shame.pin(self.path, self.task_id, 1, 2, '', 'overdue')
        self.assertGreater(pin1, 0)
        # 同一任务同一人不能重复钉
        with self.assertRaises(InvalidAction):
            shame.pin(self.path, self.task_id, 1, 2, '', 'overdue')
        shame.lift(self.path, pin1, 1)

        # 选「未达到交付标准」(rejected / substandard) 同样无需理由
        pin2 = shame.pin(self.path, self.task_id, 1, 2, '', 'rejected')
        with connect(self.path) as db:
            item = shame.active_for_task(db, self.task_id)[0]
            self.assertEqual(item['kind_label'], '未达到交付标准')
            self.assertEqual(item['reason'], '')
            self.assertEqual(item['display_reason'], '提交成果未达到任务交付标准')
        shame.lift(self.path, pin2, 1)

        # 选「其他」写明理由可钉
        pin3 = shame.pin(self.path, self.task_id, 1, 2, '临时失联未交接', 'other')
        with connect(self.path) as db:
            item = shame.active_for_task(db, self.task_id)[0]
            self.assertEqual(item['id'], pin3)
            self.assertEqual(item['kind_label'], '其他')
            self.assertEqual(item['display_reason'], '临时失联未交接')

    def test_visible_to_everyone_on_task_and_shame_page_and_lift_anytime(self):
        act(self.path, self.task_id, 2, 'join')
        # 任务详情页右侧表单呈现三个选项
        owner_before = self.clients[0].get(f'/tasks/{self.task_id}').text
        self.assertIn('逾期', owner_before)
        self.assertIn('未达到交付标准', owner_before)
        self.assertIn('其他', owner_before)
        self.assertEqual(FormDepth(owner_before).max_depth, 1)

        # 通过表单以「未达到交付标准」不填理由直接钉上
        res = self.post(self.clients[0], f'/tasks/{self.task_id}/shame/pin',
                        {'user_id': '2', 'kind': 'rejected', 'reason': ''})
        self.assertEqual(res.status_code, 200)

        for client in self.clients:
            detail_html = client.get(f'/tasks/{self.task_id}').text
            self.assertIn('data-shame-stage', detail_html)
            self.assertIn('未达到交付标准', detail_html)
            self.assertIn('shame.js', detail_html)
            self.assertEqual(FormDepth(detail_html).max_depth, 1)

            shame_html = client.get('/shame').text
            self.assertIn('data-shame-stage', shame_html)
            self.assertIn('造评测数据', shame_html)
            self.assertIn('未达到交付标准', shame_html)
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

        pin_id = shame.pin(self.path, piece_id, 1, 3, '', 'overdue')
        shame.lift(self.path, pin_id, 1, '已补交')

        initialize(self.path)
        with connect(self.path) as db:
            row = db.execute('SELECT status,lift_note FROM shame_pins WHERE id=?', (pin_id,)).fetchone()
            self.assertEqual((row['status'], row['lift_note']), ('lifted', '已补交'))


if __name__ == '__main__':
    unittest.main()
