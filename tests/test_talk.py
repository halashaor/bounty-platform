import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch

from werkzeug.serving import make_server
from app import create_app
from bounty import talk
from bounty.db import connect
from bounty.service import create_task
import mission_cli


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'business.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'test-only'})
        with connect(self.path, write=True) as db:
            db.executemany("INSERT INTO users(name,password) VALUES (?, '!')", [('林夕',), ('陈雨',), ('陈雨萱',), ('路人',)])
        self.web = {uid: self.login(uid) for uid in (1, 2, 3, 4)}
        self.tokens = {uid: self.issue(uid) for uid in (1, 3)}
        self.api = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def login(self, uid):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = uid
        client.get('/talk')
        with client.session_transaction() as session:
            client.csrf = session['csrf']
        return client

    def issue(self, uid):
        response = self.web[uid].post('/cli', data={'csrf': self.web[uid].csrf})
        return re.search(r'<textarea[^>]*>([^<]+)</textarea>', response.text).group(1)

    def post(self, uid, url, **form):
        return self.web[uid].post(url, data={'csrf': self.web[uid].csrf, **form})

    def call(self, path, uid=1, data=None, status=200):
        headers = {'Authorization': 'Bearer ' + self.tokens[uid]}
        response = self.api.get('/api/v1' + path, headers=headers) if data is None else self.api.post(
            '/api/v1' + path, json=data, headers=headers)
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.json['ok'], status < 400)
        return response.json.get('data', response.json.get('error'))

    def task(self, owner=1, **extra):
        values = dict(title='整理图论模板', description='统一接口', requirements='代码和说明', tags='代码',
                      importance='standard', urgency='normal', deadline=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat(), **extra)
        return create_task(self.path, owner, values, timezone.utc)

    def badge(self, uid):
        found = re.search(r'寄合<b[^>]*>(\d+)</b>', self.web[uid].get('/mine').text)
        return int(found.group(1)) if found else 0


class WebTest(Fixture):
    def test_naming_reaches_the_inbox_and_reading_clears_it(self):
        response = self.post(1, '/talk', title='图论模板的接口', body='接口改好了，@陈雨萱 剩下的边界样例交给你', to=['4'])
        self.assertEqual(response.status_code, 302)
        topic = int(response.headers['Location'].rsplit('/', 1)[1])
        # @陈雨萱 按最长的名字匹配，不会顺带点到「陈雨」
        self.assertEqual((self.badge(1), self.badge(2), self.badge(3), self.badge(4)), (0, 0, 1, 1))
        page = self.web[3].get(f'/talk/{topic}').text
        self.assertIn('post fresh', page)
        self.assertEqual(self.badge(3), 0)
        self.assertNotIn('post fresh', self.web[3].get(f'/talk/{topic}').text)
        # 回复的人自己读过了；话题里说过话的人都会收到后面的回复
        self.post(3, f'/talk/{topic}', body='收到，今晚接着写')
        self.assertEqual((self.badge(1), self.badge(3), self.badge(4)), (1, 0, 1))
        self.assertEqual(self.badge(2), 0)
        listed = self.web[2].get('/talk').text
        self.assertIn('图论模板的接口', listed)
        self.assertNotIn('图论模板的接口', self.web[2].get('/talk?scope=mine').text)
        self.assertIn('图论模板的接口', self.web[3].get('/talk?scope=mine').text)

    def test_topics_on_a_task_reach_the_people_doing_it(self):
        tid = self.task(owner=1, kind='team', members=[2])
        self.post(4, '/talk', title='模板里的 LCA 用哪个版本', body='倍增还是树剖？', task=str(tid))
        self.assertEqual((self.badge(1), self.badge(2), self.badge(3)), (1, 1, 0))
        detail = self.web[3].get(f'/tasks/{tid}').text
        self.assertIn('模板里的 LCA 用哪个版本', detail)
        self.assertIn(f'/talk/new?task={tid}', detail)
        form = self.web[1].get(f'/talk/new?task={tid}').text
        self.assertRegex(form, rf'<option value="{tid}" selected>')

    def test_text_is_escaped_with_links_and_code_kept(self):
        body = '<script>alert(1)</script> 见 https://example.test/a?b=1 和 `make <test>`\n```\nif (a < b) {}\n```'
        response = self.post(1, '/talk', title='<b>标题</b>', body=body)
        page = self.web[1].get(response.headers['Location']).text
        self.assertNotIn('<script>alert', page)
        self.assertNotIn('<b>标题</b>', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('href="https://example.test/a?b=1"', page)
        self.assertIn('<code>make &lt;test&gt;</code>', page)
        self.assertIn('<pre><code>if (a &lt; b) {}</code></pre>', page)

    def test_bad_input_login_and_csrf(self):
        response = self.post(1, '/talk', title='', body='有内容')
        self.assertEqual(response.status_code, 400)
        self.assertIn('标题不能为空', response.text)
        response = self.post(1, '/talk', title='有标题', body='写了一半', task='999')
        self.assertIn('关联的任务不存在', response.text)
        self.assertIn('写了一半', response.text)
        self.assertEqual(self.post(1, '/talk', title='t', body='x' * 10001).status_code, 400)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM topics').fetchone()[0], 0)
        self.assertEqual(self.web[1].post('/talk', data={'title': 't', 'body': 'b'}).status_code, 400)
        self.assertEqual(self.app.test_client().get('/talk').status_code, 302)
        self.assertEqual(self.web[1].get('/talk/999').status_code, 404)
        self.assertEqual(self.post(1, '/talk/999', body='x').status_code, 302)

    def test_tables_survive_restart(self):
        self.post(1, '/talk', title='保留', body='重启后还在')
        create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'test-only'})
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 1)


class APITest(Fixture):
    def test_ai_posts_are_marked_and_named_people_get_them(self):
        tid = self.task()
        topic = self.call('/talk', data={'title': '交接：图论模板', 'body': '分支 feat/x，剩下边界样例', 'task_id': tid,
                                         'to': [3], 'extra': True}, status=201)
        tid_topic = topic['topic']['id']
        self.assertEqual(topic['topic']['task_id'], tid)
        self.assertTrue(topic['posts'][0]['ai'])
        self.assertEqual(topic['posts'][0]['to'], [{'id': 3, 'name': '陈雨萱'}])
        self.assertIn('经 AI', self.web[3].get(f'/talk/{tid_topic}').text)
        box = self.call('/inbox', uid=3)
        self.assertEqual(box['items'], [])   # 网页上读过就算读过
        self.call(f'/talk/{tid_topic}/posts', data={'body': '还有一处', 'to': [3]}, status=201)
        box = self.call('/inbox', uid=3)
        self.assertEqual([(i['topic_id'], i['unread'], i['mentioned']) for i in box['items']], [(tid_topic, 1, True)])
        self.assertEqual(box['items'][0]['last']['preview'], '还有一处')
        unread = self.call(f'/talk/{tid_topic}?unread=1', uid=3)
        self.assertEqual([p['body'] for p in unread['posts']], ['还有一处'])
        self.assertEqual(self.call('/inbox', uid=3)['items'], [])
        self.assertEqual(self.call('/inbox')['items'], [])   # 自己发的不进自己的收件箱

    def test_cursor_bounds_the_inbox(self):
        first = self.call('/talk', data={'title': 'a', 'body': '1', 'to': [3]}, status=201)['topic']['id']
        box = self.call('/inbox', uid=3)
        cursor = box['cursor']
        self.assertEqual(len(box['items']), 1)
        self.assertEqual(self.call(f'/inbox?after={cursor}', uid=3)['items'], [])
        self.call(f'/talk/{first}/posts', data={'body': '2'}, status=201)
        later = self.call(f'/inbox?after={cursor}', uid=3)
        self.assertEqual(later['items'][0]['unread'], 1)
        self.assertGreater(later['cursor'], cursor)

    def test_validation_and_paging(self):
        self.call('/talk', data={'title': 't', 'body': 'b', 'to': [99]}, status=400)
        self.call('/talk', data={'title': 't', 'body': 'b', 'to': '3'}, status=400)
        self.call('/talk', data={'title': 't', 'body': 'b', 'task_id': 999}, status=400)
        self.call('/talk', data={'title': 'x' * 121, 'body': 'b'}, status=400)
        self.call('/talk', data={'title': ['t'], 'body': 'b'}, status=400)
        self.call('/talk/999', status=404)
        self.call('/talk/999/posts', data={'body': 'x'}, status=404)
        self.call('/talk/99999999999999999999999', status=400)
        topic = self.call('/talk', data={'title': 'paging', 'body': '0'}, status=201)['topic']['id']
        for n in range(1, 4):
            self.call(f'/talk/{topic}/posts', data={'body': str(n)}, status=201)
        page = self.call(f'/talk/{topic}?limit=2')
        self.assertEqual([p['body'] for p in page['posts']], ['0', '1'])
        page = self.call(f'/talk/{topic}?limit=2&after={page["next_after"]}')
        self.assertEqual(([p['body'] for p in page['posts']], page['next_after']), (['2', '3'], None))
        listing = self.call('/talk?q=paging')
        self.assertEqual((listing['total'], listing['items'][0]['posts']), (1, 4))
        self.assertEqual(self.call('/talk?mine=1', uid=3)['total'], 0)
        response = self.web[1].post('/api/v1/talk', json={'title': 't', 'body': 'b'})
        self.assertEqual(response.status_code, 401)


class CLITest(Fixture):
    def setUp(self):
        super().setUp()
        self.server = make_server('127.0.0.1', 0, self.app, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown(); self.thread.join(); self.server.server_close()
        super().tearDown()

    def command(self, *args, uid=1, stdin=''):
        out, err = io.StringIO(), io.StringIO()
        env = {'MISSION_TOKEN': self.tokens[uid], 'MISSION_SERVER': '', 'MISSION_CONFIG': ''}
        with patch.dict(os.environ, env), patch('sys.stdin', io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mission_cli.main(['--server', self.url, '--config', str(Path(self.temp.name) / 'cli.json'), *args])
        return code, out.getvalue(), err.getvalue()

    def test_talk_commands_and_waiting(self):
        code, out, _ = self.command('talk', 'new', '--title', '交接', '--to', '3', '--body-file', '-', '--json',
                                    stdin='做到第二步了\n剩下第三步')
        self.assertEqual(code, 0, out)
        topic = json.loads(out)['data']['topic']['id']
        code, out, _ = self.command('inbox', uid=3)
        self.assertIn('@你', out)
        code, out, _ = self.command('talk', 'show', str(topic), '--unread', uid=3)
        self.assertIn('剩下第三步', out)
        self.assertIn('（经 AI）', out)
        self.assertEqual(self.command('talk', 'list', '--mine', '--json', uid=3)[0], 0)
        self.assertEqual(self.command('talk', 'reply', str(topic), '--to', '99', '--body', 'x', '--json', uid=3)[0], 4)
        # 等的时候有人回复：下一次去问就带回来
        replied = []

        def nap(seconds):
            if not replied:
                replied.append(self.command('talk', 'reply', str(topic), '--body', '收到', uid=3))
        with patch.object(mission_cli.time, 'sleep', nap):
            code, out, _ = self.command('inbox', '--wait', '--interval', '10', '--json')
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)['data']['items'][0]['last']['preview'], '收到')
        with patch.object(mission_cli.time, 'sleep', lambda seconds: None):
            code, out, _ = self.command('inbox', '--wait', '--max-wait', '0.01', '--json')
        self.assertEqual(json.loads(out)['data']['items'], [])
        self.assertEqual(self.command('inbox', '--wait', '--interval', '1')[0], 2)

    def test_watch_runs_the_command_with_posts_on_stdin(self):
        topic = self.call('/talk', data={'title': '找人', 'body': '在吗'}, status=201)['topic']['id']
        cursor = self.call('/inbox', uid=3)['cursor']
        self.call(f'/talk/{topic}/posts', data={'body': '@陈雨萱 帮我看一下'}, status=201)
        seen = []

        def run(command, shell, input, text):
            seen.append((command, json.loads(input)))
            raise KeyboardInterrupt
        with patch.object(mission_cli.time, 'sleep', lambda seconds: None), patch.object(mission_cli.subprocess, 'run', run):
            code, _, err = self.command('watch', '--after', str(cursor), '--run', 'my-agent --wake', uid=3)
        self.assertEqual(code, 130)
        self.assertEqual(seen[0][0], 'my-agent --wake')
        self.assertEqual(seen[0][1]['data']['items'][0]['last']['preview'], '@陈雨萱 帮我看一下')
        self.assertIn('寄合来了', err)

    def test_schema_lists_talk_commands(self):
        commands = {c['command'] for c in mission_cli.schema(mission_cli.build_parser()[1])['commands']}
        self.assertTrue({'mission inbox', 'mission watch', 'mission talk new', 'mission talk reply'} <= commands)


class RenderTest(unittest.TestCase):
    def test_unclosed_fence_runs_to_the_end(self):
        html = str(talk.render('看这里\n```\nx = 1'))
        self.assertIn('<p>看这里</p>', html)
        self.assertIn('<pre><code>x = 1</code></pre>', html)


if __name__ == '__main__':
    unittest.main()
