import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import create_app
from bounty import notes
from bounty.db import connect
from bounty.service import InvalidAction, act, create_task
from mission_cli import build_parser, schema


class NotesTest(unittest.TestCase):
    """手帳：有进展、遇到问题才记；@ 会提醒；问题能发成任务；只自己看的谁也看不到。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'test.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'test'})
        self.clients = []
        for name in ('陈默', '王瑶', '周然'):
            client = self.app.test_client()
            self.post(client, '/auth/register', {'name': name, 'password': 'test-password'})
            self.clients.append(client)
        self.task = create_task(self.path, 1, dict(
            title='办好周六模拟赛', description='题目、数据、机房', requirements='按时开赛', tags='讲解', project='校赛',
            importance='standard', urgency='normal', deadline=(datetime.now(timezone.utc) + timedelta(days=5)).isoformat()))
        act(self.path, self.task, 2, 'join')

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self, client):
        client.get('/auth/login')
        with client.session_transaction() as session:
            return session['csrf']

    def post(self, client, path, data, follow=True):
        return client.post(path, data={**data, 'csrf': self.csrf(client)}, follow_redirects=follow)

    def test_write_view_and_keep_private_notes_private(self):
        me, wang, zhou = self.clients
        page = self.post(me, '/notes', {'body': 'E 题对拍跑完 500 组\n生成器补了链和菊花两种形状', 'kind': 'progress', 'task': str(self.task)})
        self.assertIn('E 题对拍跑完 500 组', page.text)
        self.assertIn('class="ent prog new"', page.text)                 # 刚记下的一条带落位动画
        note_id = notes.write(self.path, 1, '选课的事还没想好', private=True)[0]
        theirs = wang.get('/notes/u/1').text
        self.assertIn('E 题对拍跑完 500 组', theirs)
        self.assertNotIn('选课的事', theirs)                              # 只自己看的，别人完全看不到
        self.assertIn('选课的事', me.get('/notes').text)
        self.assertEqual(wang.get(f'/notes/n/{note_id}').status_code, 404)
        self.assertIn('E 题对拍跑完 500 组', wang.get(f'/tasks/{self.task}').text)   # 任务页「进展」
        with self.assertRaises(InvalidAction):
            notes.edit(self.path, 2, note_id, '改别人的')
        with self.assertRaises(InvalidAction):
            notes.write(self.path, 1, '   ')
        with self.assertRaises(InvalidAction):
            notes.write(self.path, 1, '随便', kind='diary')

    def test_mentions_stay_until_read(self):
        me, wang, _ = self.clients
        note_id, named = notes.write(self.path, 2, 'E 题时限想定 1 秒，@陈默 你那边最坏跑多久？', task_id=self.task)
        self.assertEqual(named, [1])
        home = me.get('/').text
        self.assertIn('aria-label="1 件事等你"', home)                    # 导航「我的」上的数字
        self.assertIn('<title>(1) ', home)                                 # 浏览器标签上也有
        for _ in range(2):                                                 # 没看过就一直提醒，不是只弹一次
            alerts = me.get('/alerts').json
            self.assertEqual(alerts['count'], 1)
            self.assertEqual([(item['key'], item['who'], item['what']) for item in alerts['items']],
                             [(f'note:{note_id}', '王瑶', '在手帳里提到你')])
        self.assertIn('aria-label="1 条提到你"', me.get('/notes').text)  # 「提到我」页签上的数字留到看过为止
        page = me.get('/notes/at').text
        self.assertIn('class="mref me"', page)
        self.assertNotIn('aria-label="1 件事等你"', me.get('/').text)
        self.assertEqual(me.get('/alerts').json, {'ok': True, 'count': 0, 'items': []})
        # 卡片上点「知道了」也算看过
        again = notes.write(self.path, 2, '@陈默 标程我也改好了')[0]
        ack = me.get('/alerts').json['items'][0]['ack']
        self.assertEqual(me.post(ack, headers={'X-CSRF-Token': self.csrf(me)}).json, {'ok': True})
        self.assertEqual(me.get('/alerts').json['count'], 0)
        # 改成只自己看：提醒一起收回
        secret = notes.write(self.path, 2, '@周然 这条先别外传')[0]
        notes.set_private(self.path, 2, secret, True)
        with connect(self.path) as db:
            self.assertEqual(notes.unseen_count(db, 3), 0)
        self.assertEqual(notes.write(self.path, 2, '@陈默 私下说', private=True)[1], [])

    def test_problem_becomes_a_task_and_is_solved_when_it_is_done(self):
        me, wang, zhou = self.clients
        reply = self.post(me, '/notes', {'body': '对拍脚本在 Windows 上路径拼错\n反斜杠被当成转义', 'kind': 'problem',
                                         'task': str(self.task), 'spawn': '1'}, follow=False)
        self.assertIn('/tasks/new?', reply.headers['Location'])
        form = me.get(reply.headers['Location']).text
        self.assertIn('value="对拍脚本在 Windows 上路径拼错"', form)
        self.assertIn('name="from_note"', form)
        note_id = int(re.search(r'from_note=(\d+)', reply.headers['Location']).group(1))
        self.post(me, '/tasks/new', {'title': '统一对拍脚本的路径', 'description': '反斜杠被当成转义', 'requirements': '两边都能跑',
                                     'tags': '代码', 'importance': 'light', 'urgency': 'normal', 'kind': 'solo', 'from_note': str(note_id),
                                     'deadline': (datetime.now(timezone.utc) + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')})
        with connect(self.path) as db:
            spawned = db.execute('SELECT spawned_task_id FROM notes WHERE id=?', (note_id,)).fetchone()[0]
            self.assertTrue(spawned)
            self.assertEqual([n['id'] for n in notes.team(db, 2, timezone.utc)['stuck']], [note_id])   # 大家页「卡住了」
        act(self.path, spawned, 3, 'join')
        act(self.path, spawned, 3, 'submit', '改成 pathlib')
        act(self.path, spawned, 1, 'accept')
        with connect(self.path) as db:
            data = notes.timeline(db, 1, 1, timezone.utc)
            note = next(item['note'] for day in data['days'] for item in day['items'] if item['type'] == 'note')
            self.assertTrue(note['solved'])
            self.assertEqual(note['solved_name'], '周然')
            self.assertEqual(notes.team(db, 2, timezone.utc)['stuck'], [])
        # 手动标成解决：只有「问题」能标，标一次
        other = notes.write(self.path, 2, '评测机内存不够', 'problem')[0]
        with self.assertRaises(InvalidAction):
            notes.solve(self.path, 1, notes.write(self.path, 1, '一条进展')[0])
        page = self.post(zhou, f'/notes/{other}/solve', {'how': '换到 16G 那台'})
        self.assertIn('换到 16G 那台', page.text)
        self.assertIn(' just', page.text)
        with self.assertRaises(InvalidAction):
            notes.solve(self.path, 1, other)

    def test_todos_and_task_events_in_the_timeline(self):
        me, wang, _ = self.clients
        self.post(me, '/notes/todos', {'title': '写 E 题题解', 'task': str(self.task)})
        hidden = notes.add_todo(self.path, 1, '交选课表', private=True)
        with connect(self.path) as db:
            todo_id = db.execute("SELECT id FROM todos WHERE title='写 E 题题解'").fetchone()[0]
        reply = me.post(f'/notes/todos/{todo_id}', data={'state': 'done', 'csrf': self.csrf(me)},
                        headers={'X-Requested-With': 'fetch', 'Accept': 'application/json'})
        self.assertEqual(reply.json['state'], 'done')
        with self.assertRaises(InvalidAction):
            notes.set_todo(self.path, 2, todo_id, 'doing')
        with self.assertRaises(InvalidAction):
            notes.set_todo(self.path, 1, todo_id, 'later')
        notes.set_todo(self.path, 1, hidden, 'dropped')
        mine = me.get('/notes').text
        self.assertIn('写 E 题题解', mine)
        self.assertNotIn('交选课表', mine)                                # 不做了：收起来，记录还在
        self.assertNotIn('交选课表', wang.get('/notes/u/1').text)
        # 加入任务会自动排进时间线
        self.assertIn('加入', wang.get('/notes').text)
        self.assertIn('办好周六模拟赛', wang.get('/notes').text)
        self.assertEqual(self.clients[0].get('/notes/team').status_code, 200)
        self.assertEqual(self.clients[0].get('/notes/team?scope=crew').status_code, 200)

    def test_command_line_notes_are_marked_and_folded(self):
        with self.app.test_client() as browser:
            with browser.session_transaction() as session:
                session['user_id'] = 1
            browser.get('/cli')
            with browser.session_transaction() as session:
                csrf = session['csrf']
            token = re.search(r'<textarea[^>]*>([^<]+)</textarea>', browser.post('/cli', data={'csrf': csrf}).text).group(1)
        api = self.app.test_client()
        headers = {'Authorization': 'Bearer ' + token}
        body = '跑完对拍，全部一致\n' + '\n'.join(f'第 {n} 行过程' for n in range(1, 7))
        made = api.post('/api/v1/notes', json={'body': body, 'task_id': self.task}, headers=headers).json['data']
        self.assertTrue(made['ai'])
        self.assertTrue(made['folded'])
        self.assertEqual(made['head'], '跑完对拍，全部一致')
        listed = api.get('/api/v1/notes', headers=headers).json['data']['items']
        self.assertEqual(listed[0]['id'], made['id'])
        problem = api.post('/api/v1/notes', json={'body': '评测机内存不够', 'kind': 'problem'}, headers=headers).json['data']
        team = api.get('/api/v1/team', headers=headers).json['data']
        self.assertEqual(team['stuck'], [])                               # 自己的问题不在「卡住了」里
        self.assertIn('王瑶', [person['name'] for person in team['people'] + team['quiet']])
        solved = api.post(f'/api/v1/notes/{problem["id"]}/solve', json={'how': '换机器'}, headers=headers).json['data']
        self.assertTrue(solved['solved'])
        todo = api.post('/api/v1/todos', json={'title': '配时限', 'task_id': self.task}, headers=headers).json['data']
        self.assertEqual(api.post(f'/api/v1/todos/{todo["id"]}', json={'state': 'doing'}, headers=headers).json['data']['state'], 'doing')
        groups = api.get('/api/v1/todos', headers=headers).json['data']
        self.assertIn('配时限', [item['title'] for group in groups for item in group['items']])
        self.assertEqual(api.post('/api/v1/notes', json={'body': ''}, headers=headers).status_code, 400)
        _, parser = build_parser()
        self.assertIn('第一行写结论', schema(parser)['notes'])          # 给 AI 的写法说明


if __name__ == '__main__':
    unittest.main()
