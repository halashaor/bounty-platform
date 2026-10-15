import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app import create_app
from bounty import bigs, discover, progress, titles, unlocks
from bounty.db import connect
from bounty.service import InvalidAction, act


class BigTaskTest(unittest.TestCase):
    """大任务：分成几份分工，每份就是一个小任务；牵头人能验收分工，最后收尾给大家记一笔。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'test.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'test'})
        self.clients = []
        for name in ('lead', 'worker', 'other', 'fourth'):
            client = self.app.test_client()
            self.post(client, '/auth/register', {'name': name, 'password': 'test-password'})
            self.clients.append(client)
        self.deadline = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        self.form = dict(title='办好周六模拟赛', goal='周六准时开赛，赛后发题解。', project='校赛', deadline=self.deadline)
        self.rows = [dict(title='造数据', tag='数据', kind='standard-normal', note='E 题 30 组'),
                     dict(title='订机房', tag='杂务', kind='light-urgent'),
                     dict(title='写题解', tag='讲解', kind='major-normal')]

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self, client):
        client.get('/auth/login')
        with client.session_transaction() as session:
            return session['csrf']

    def post(self, client, path, data):
        return client.post(path, data={**data, 'csrf': self.csrf(client)}, follow_redirects=True)

    def pieces(self, big_id):
        with connect(self.path) as db:
            return {row['title']: row for row in db.execute('SELECT * FROM tasks WHERE big_id=? ORDER BY id', (big_id,))}

    def finish(self, task_id, worker, checker=1):
        act(self.path, task_id, worker, 'claim')
        act(self.path, task_id, worker, 'submit', '做好了')
        act(self.path, task_id, checker, 'accept', '谢谢')

    def test_a_big_task_needs_at_least_two_shares_from_the_team_list(self):
        with self.assertRaises(InvalidAction):
            bigs.create(self.path, 1, self.form, self.rows[:1])
        with self.assertRaises(InvalidAction):   # 标签只能从团队的标签表里选
            bigs.create(self.path, 1, self.form, [*self.rows[:1], dict(title='乱写', tag='没有这个', kind='light-normal')])
        with self.assertRaises(InvalidAction):
            bigs.create(self.path, 1, {**self.form, 'deadline': '2020-01-01T00:00'}, self.rows)
        # 空行跳过
        big_id = bigs.create(self.path, 1, self.form, [*self.rows, dict(title='', tag='', kind='light-normal', note='')])
        pieces = self.pieces(big_id)
        self.assertEqual(list(pieces), ['造数据', '订机房', '写题解'])
        data = pieces['造数据']
        with connect(self.path) as db:
            target = db.execute('SELECT deadline FROM big_tasks WHERE id=?', (big_id,)).fetchone()[0]
        self.assertEqual((data['owner_id'], data['project'], data['deadline'], data['status'], data['description'], data['requirements']),
                         (1, '校赛', target, 'open', 'E 题 30 组', ''))
        self.assertEqual((pieces['订机房']['importance'], pieces['订机房']['urgency']), ('light', 'urgent'))
        with connect(self.path) as db:
            self.assertEqual(discover.tags_by_task(db, [data['id']])[data['id']], ['数据'])
            self.assertTrue(bigs.is_member(db, big_id, 1))

    def test_the_form_publishes_and_the_pages_show_it(self):
        lead, worker, other, _ = self.clients
        form = {**self.form, 'piece_title': [r['title'] for r in self.rows], 'piece_tag': [r['tag'] for r in self.rows],
                'piece_kind': [r['kind'] for r in self.rows], 'piece_note': ['', '', '']}
        page = self.post(lead, '/big/new', form)
        self.assertIn('大任务发起了', page.text)
        self.assertIn('class="share-list"', page.text)
        home = worker.get('/').text
        self.assertIn('class="bigband', home)
        self.assertIn('办好周六模拟赛', home)
        self.assertIn('class="bigtag"', home)        # 分工的卡片上写着属于哪个大任务
        self.assertIn('办好周六模拟赛', worker.get('/big').text)
        self.assertIn('class="kind-switch"', worker.get('/tasks/new').text)
        piece = self.pieces(1)['造数据']
        detail = worker.get(f'/tasks/{piece["id"]}').text
        self.assertIn('class="big-crumb"', detail)
        self.assertIn('按大任务的目标来', detail)
        # 少于两份：留在表单上，已经写的不丢
        page = self.post(lead, '/big/new', {**form, 'title': '再来一个', 'piece_title': ['只有一份', '', '']})
        self.assertIn('至少分成两份', page.text)
        self.assertIn('只有一份', page.text)

    def test_crew_join_add_shares_and_the_lead_can_accept(self):
        big_id = bigs.create(self.path, 1, self.form, self.rows)
        pieces = self.pieces(big_id)
        with self.assertRaises(InvalidAction):    # 没加入不能加分工
            bigs.add_piece(self.path, big_id, 3, dict(title='答疑', tag='杂务', kind='light-normal'))
        bigs.join(self.path, big_id, 3)
        extra = bigs.add_piece(self.path, big_id, 3, dict(title='答疑', tag='杂务', kind='light-normal'))
        # 接一份分工就算加入
        act(self.path, extra, 2, 'claim')
        with connect(self.path) as db:
            self.assertTrue(bigs.is_member(db, big_id, 2))
        act(self.path, extra, 2, 'submit', '答完了')
        # 分工由加它的人验收，牵头人也能验收；别人不行
        with self.assertRaises(InvalidAction):
            act(self.path, extra, 4, 'accept')
        act(self.path, extra, 1, 'accept', '辛苦')
        # 牵头人自己接的分工，不能自己验收
        act(self.path, pieces['造数据']['id'], 3, 'claim')
        with self.assertRaises(InvalidAction):
            act(self.path, pieces['造数据']['id'], 1, 'claim')   # 自己发的分工不能接
        bigs.join(self.path, big_id, 4)
        other_piece = bigs.add_piece(self.path, big_id, 4, dict(title='校对', tag='讲解', kind='light-normal'))
        act(self.path, other_piece, 1, 'claim')
        act(self.path, other_piece, 1, 'submit', '校对完')
        with self.assertRaises(InvalidAction):
            act(self.path, other_piece, 1, 'accept')
        act(self.path, other_piece, 4, 'accept')
        # 手上有分工不能退出，牵头人不能退出
        with self.assertRaises(InvalidAction):
            bigs.leave(self.path, big_id, 3)
        with self.assertRaises(InvalidAction):
            bigs.leave(self.path, big_id, 1)
        # 牵头人「轮到你」里看得到别人交上来的分工
        act(self.path, pieces['造数据']['id'], 3, 'submit', '数据好了')
        lead = self.clients[0]
        self.assertIn('造数据', lead.get('/mine').text.split('等对方')[0])
        self.assertIn('class="share-list"', lead.get(f'/big/{big_id}').text)

    def test_wrap_up_credits_the_crew_and_frees_unclaimed_shares(self):
        big_id = bigs.create(self.path, 1, self.form, self.rows)
        pieces = self.pieces(big_id)
        with self.assertRaises(InvalidAction):    # 一份都没做完，不能收尾
            bigs.close(self.path, big_id, 1)
        act(self.path, pieces['造数据']['id'], 2, 'claim')
        with self.assertRaises(InvalidAction):    # 还有人在做
            bigs.close(self.path, big_id, 1)
        act(self.path, pieces['造数据']['id'], 2, 'submit', '好了')
        act(self.path, pieces['造数据']['id'], 1, 'accept')
        self.finish(pieces['写题解']['id'], 3)
        with self.assertRaises(InvalidAction):    # 只有牵头人能收尾
            bigs.close(self.path, big_id, 2)
        with connect(self.path) as db:
            xp_before = progress.person_progress(db, 2)['xp']
        self.assertEqual(sorted(bigs.close(self.path, big_id, 1, '谢谢大家')), [1, 2, 3])
        with connect(self.path) as db:
            # 没人接的「订机房」变回普通小任务，留在发现里
            self.assertIsNone(db.execute("SELECT big_id FROM tasks WHERE title='订机房'").fetchone()[0])
            self.assertEqual(progress.person_progress(db, 2)['xp'], xp_before + bigs.BONUS)
            self.assertEqual(progress.everyone_levels(db)[1]['xp'], bigs.BONUS)
            credits = {row['user_id']: dict(row) for row in db.execute('SELECT * FROM big_credits')}
            self.assertEqual((credits[1]['lead'], credits[1]['pieces'], credits[2]['pieces']), (1, 0, 1))
            self.assertEqual(titles.counts(db, 1)['captain'], 1)
            self.assertEqual(titles.counts(db, 2)['together'], 1)
            self.assertIn('part:knot', unlocks.unlocked(db, 2))
            self.assertNotIn('part:knot', unlocks.unlocked(db, 4))
        with self.assertRaises(InvalidAction):    # 收尾后不能再加分工、再加入
            bigs.join(self.path, big_id, 4)
        # 信箱：勋章和合力纪念一起拆
        worker = self.clients[1]
        self.assertIn('mailbox has-mail', worker.get('/').text)
        reply = worker.post('/honors/reveal', data={'csrf': self.csrf(worker)}, headers={'Accept': 'application/json'}).json
        self.assertEqual(len(reply['awards']), 1)
        self.assertEqual([item['title'] for item in reply['bigs']], ['办好周六模拟赛'])
        self.assertEqual((reply['bigs'][0]['closing'], reply['bigs'][0]['pieces'], reply['bigs'][0]['xp']), ('谢谢大家', 1, bigs.BONUS))
        self.assertIn('class="mosaic m-cer"', reply['bigs'][0]['mosaic'])
        self.assertIn('双环', reply['bigs'][0]['opens'])
        self.assertEqual(reply['after']['xp'], 30 + bigs.BONUS)   # 「线」30 经验 + 收尾奖励
        self.assertEqual(reply['before']['xp'], 0)
        again = worker.post('/honors/reveal', data={'csrf': self.csrf(worker)}, headers={'Accept': 'application/json'}).json
        self.assertEqual(again['bigs'], [])
        honors = worker.get('/honors').text
        self.assertIn('一起完成的大任务', honors)
        self.assertIn('谢谢大家', honors)
        self.assertIn('class="closing panel"', worker.get(f'/big/{big_id}').text)

    def test_lead_is_told_when_every_share_is_done(self):
        big_id = bigs.create(self.path, 1, self.form, self.rows[:2])
        for title, worker in (('造数据', 2), ('订机房', 3)):
            self.finish(self.pieces(big_id)[title]['id'], worker)
        lead = self.clients[0]
        self.assertIn('等你收尾', lead.get('/mine').text)
        with connect(self.path) as db:
            self.assertEqual(bigs.ready_count(db, 1), 1)

    def test_shares_are_recommended_to_the_crew(self):
        big_id = bigs.create(self.path, 1, self.form, self.rows)
        with connect(self.path) as db:
            reasons = {pick['task']['title']: pick['reasons'] for pick in discover.recommend(db, 2, limit=10)}
        self.assertIn('big', [kind for kind, _ in reasons['造数据']])
        bigs.join(self.path, big_id, 2)
        with connect(self.path) as db:
            picks = discover.recommend(db, 2, limit=10, lane='past')
        self.assertEqual(picks[0]['ranked'][0][0], 'crew')
        self.assertIn('你加入了「办好周六模拟赛」', [text for _, text in picks[0]['ranked']])


if __name__ == '__main__':
    unittest.main()
