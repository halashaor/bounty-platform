import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import MY_TURN, create_app
from bounty import alerts, extend, talk
from bounty.db import connect
from bounty.service import act, create_task


class AlertsTest(unittest.TestCase):
    """提醒只算要你动手的事：有人提到你、等你验收、等你批延期、被退回要改；手上在做的不算。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'test.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'test'})
        with connect(self.path, write=True) as db:
            db.executemany("INSERT INTO users(name,password) VALUES (?, '!')", [('陈默',), ('王瑶',), ('周然',)])
        self.web = {}
        for uid in (1, 2, 3):
            client = self.app.test_client()
            with client.session_transaction() as session:
                session['user_id'] = uid
            client.get('/mine')
            with client.session_transaction() as session:
                client.csrf = session['csrf']
            self.web[uid] = client
        self.task = create_task(self.path, 1, dict(
            title='办好周六模拟赛', description='题目、数据、机房', requirements='按时开赛', tags='讲解', project='校赛',
            importance='standard', urgency='normal', deadline=self.future(5)))

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def future(days):
        return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec='seconds')

    def alerts(self, uid):
        return self.web[uid].get('/alerts').json

    def kinds(self, uid):
        return [(item['kind'], item['who']) for item in self.alerts(uid)['items']]

    def test_task_steps_that_need_someone(self):
        act(self.path, self.task, 2, 'join')
        with connect(self.path) as db:              # 在做的任务还在「轮到你」里，但不算提醒
            self.assertEqual(db.execute(f'SELECT COUNT(*) FROM tasks t WHERE {MY_TURN}', {'me': 2}).fetchone()[0], 1)
        self.assertEqual(self.alerts(2)['count'], 0)
        self.assertNotIn('件事等你', self.web[2].get('/').text)

        extend.ask(self.path, self.task, 2, self.future(8), '数据还没到', timezone.utc)
        self.assertEqual(self.kinds(1), [('extend', '王瑶')])
        self.assertIn('等你点头', self.alerts(1)['items'][0]['what'])
        self.assertEqual(self.alerts(2)['count'], 0)  # 不能批自己的延期，自己也不会被提醒
        extend.decide(self.path, self.task, 1, True)
        self.assertEqual(self.alerts(1)['count'], 0)

        act(self.path, self.task, 2, 'submit', '题目放在共享盘')
        first = self.alerts(1)['items']
        self.assertEqual([(item['kind'], item['who'], item['go']) for item in first], [('review', '王瑶', '去验收')])
        self.assertEqual(first[0]['url'], f'/tasks/{self.task}')
        self.assertIsNone(first[0]['ack'])            # 验收只能去任务页做，卡片上只能「稍后」
        self.assertIn('aria-label="1 件等你处理"', self.web[1].get('/mine').text)

        act(self.path, self.task, 1, 'return', 'E 题少了数据范围')
        self.assertEqual(self.alerts(1)['count'], 0)
        returned = self.alerts(2)['items']
        self.assertEqual([(item['kind'], item['who'], item['sub']) for item in returned], [('return', '陈默', 'E 题少了数据范围')])

        act(self.path, self.task, 2, 'submit', '补好了')  # 再交一次是新的提醒，换一个 key，收起过的卡片会再弹
        again = self.alerts(1)['items']
        self.assertEqual(again[0]['kind'], 'review')
        self.assertNotEqual(again[0]['key'], first[0]['key'])
        self.assertEqual(self.alerts(2)['count'], 0)
        act(self.path, self.task, 1, 'accept')
        self.assertEqual(self.alerts(1)['count'], 0)

    def test_named_in_talk(self):
        topic, named = talk.start(self.path, 3, 'E 题时限', '@陈默 标程最坏跑多久？')
        self.assertEqual(named, [1])
        talk.reply(self.path, topic, 3, '我先在本机测一遍')
        items = self.alerts(1)['items']
        self.assertEqual([(item['kind'], item['who'], item['sub']) for item in items], [('talk', '周然', 'E 题时限')])
        self.assertEqual(self.alerts(1)['count'], 1)
        at_page = self.web[1].get('/notes/at').text
        self.assertIn('寄合点名', at_page)
        self.assertIn('aria-label="1 条提到你"', at_page)
        # 只有被点名的人能把这条标成读过
        self.assertEqual(self.web[2].post(items[0]['ack'], headers={'X-CSRF-Token': self.web[2].csrf}).status_code, 404)
        self.assertEqual(self.web[1].post(items[0]['ack'], headers={'X-CSRF-Token': self.web[1].csrf}).json, {'ok': True})
        self.assertEqual(self.alerts(1)['count'], 0)
        with connect(self.path) as db:              # 读到点名那条为止，后面的新帖照样算寄合未读
            self.assertEqual(talk.unread_count(db, 1), 1)
            self.assertEqual(alerts.counts(db, 1), dict(tasks=0, mentions=0, total=0))
        self.assertIn('寄合点名', self.web[1].get('/notes/at').text)   # 读过以后「提到我」里还留着

    def test_signed_out_and_csrf(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get('/alerts').status_code, 401)
        topic, _ = talk.start(self.path, 3, '机房', '@陈默 钥匙在谁那')
        ack = self.alerts(1)['items'][0]['ack']
        self.assertNotEqual(self.web[1].post(ack).status_code, 200)
        self.assertEqual(self.alerts(1)['count'], 1)


if __name__ == '__main__':
    unittest.main()
