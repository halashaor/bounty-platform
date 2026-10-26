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
import urllib.error

from werkzeug.serving import make_server
from app import create_app
from bounty.db import connect
from bounty.service import act, create_task
from mission_cli import CLIError, Client, main, server_url


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'business.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'test-only'})
        with connect(self.path, write=True) as db:
            db.executemany("INSERT INTO users(name,password) VALUES (?, '!')", [('owner',), ('worker',), ('other',)])
        self.browser = self.app.test_client()
        self.api = self.app.test_client()
        self.tokens = {uid: self.issue(uid) for uid in (1, 2, 3)}
        self.data = dict(title='准备算法分享', description='整理例题', requirements='文档链接', tags=['讲解'],
                         deadline=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat())

    def tearDown(self):
        self.temp.cleanup()

    def issue(self, uid):
        with self.browser.session_transaction() as session:
            session['user_id'] = uid
        self.browser.get('/cli')
        with self.browser.session_transaction() as session:
            csrf = session['csrf']
        response = self.browser.post('/cli', data={'csrf': csrf})
        self.assertEqual(response.status_code, 200)
        return re.search(r'<textarea[^>]*>([^<]+)</textarea>', response.text).group(1)

    def call(self, path, uid=1, data=None, status=200):
        headers = {'Authorization': 'Bearer ' + self.tokens[uid]}
        response = self.api.get('/api/v1' + path, headers=headers) if data is None else self.api.post(
            '/api/v1' + path, json=data, headers=headers)
        self.assertEqual(response.status_code, status, response.text)
        self.assertTrue(response.is_json)
        self.assertEqual(response.json['ok'], status < 400)
        return response.json.get('data', response.json.get('error'))


class APITest(Fixture):
    def test_assignment_extension_and_review_use_existing_roles(self):
        task = self.call('/tasks', data={**self.data, 'assignee': 2, 'owner_id': 3, 'future_option': True}, status=201)
        tid = task['id']; path = f'/tasks/{tid}'
        self.assertEqual((task['owner_id'], task['assignee_id'], task['status']), (1, 2, 'active'))
        self.call(path + '/actions', uid=3, data={'action': 'submit', 'body': '越权'}, status=400)
        later = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        self.call(path + '/extensions/ask', uid=2, data={'deadline': later, 'body': '补充样例'})
        mine = self.call('/mine')
        self.assertIn(tid, [row['id'] for row in mine['yours']])
        self.call(path + '/extensions/approve', uid=2, data={}, status=400)
        extended = self.call(path + '/extensions/approve', data={})
        self.assertEqual(extended['extensions'][0]['status'], 'approved')
        self.call(path + '/actions', uid=2, data={'action': 'submit', 'body': 'https://example.test/result'})
        self.call(path + '/actions', uid=3, data={'action': 'accept'}, status=400)
        self.call(path + '/actions', data={'action': 'return', 'body': '补充复杂度'})
        self.call(path + '/actions', uid=2, data={'action': 'submit', 'body': '已补充'})
        self.assertEqual(self.call(path + '/actions', data={'action': 'accept'})['status'], 'done')
        self.call(path + '/actions', data={'action': 'accept'}, status=400)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM honors WHERE task_id=?', (tid,)).fetchone()[0], 1)
        self.call(path + '/clap', uid=3, data={})
        self.call(path + '/clap', uid=2, data={}, status=400)

    def test_team_join_split_and_credit(self):
        task = self.call('/tasks', data={**self.data, 'kind': 'team', 'team_size': 2, 'join_self': True}, status=201)
        path = '/tasks/' + str(task['id'])
        self.call(path + '/actions', uid=2, data={'action': 'join'})
        self.call(path + '/actions', uid=3, data={'action': 'join'}, status=400)
        piece = self.call(path + '/pieces', uid=2,
                          data=dict(title='准备例题', note='图论', tag='讲解', kind='standard-normal'), status=201)
        self.assertEqual(piece['parent_id'], task['id'])
        self.call(path + '/actions', uid=2, data={'action': 'submit', 'body': '完成'})
        done = self.call(path + '/actions', data={'action': 'accept', 'credit': [2]})
        self.assertEqual(done['status'], 'done')
        with connect(self.path) as db:
            self.assertEqual([r[0] for r in db.execute('SELECT user_id FROM honors WHERE task_id=?', (task['id'],))], [2])

    def test_bearer_required_even_with_browser_cookie_and_web_csrf_stays(self):
        with self.browser.session_transaction() as session:
            session['user_id'] = 1
        response = self.browser.post('/api/v1/tasks', json=self.data)
        self.assertEqual(response.status_code, 401)
        response = self.browser.post('/cli', headers={'Authorization': 'Bearer ' + self.tokens[1]})
        self.assertEqual(response.status_code, 400)
        response = self.api.get('/api/v1/me', headers={'Authorization': 'Bearer nonsense'})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('password', json.dumps(self.call('/members')))
        self.assertNotIn('password', json.dumps(self.call('/me')))

    def test_revocation_is_independent_and_expiration_enforced(self):
        fresh = self.issue(1)
        self.call('/logout', data={})
        self.call('/me', status=401)
        response = self.api.get('/api/v1/me', headers={'Authorization': 'Bearer ' + fresh})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.browser.get('/').status_code, 200)
        with connect(self.path, write=True) as db:
            db.execute('UPDATE cli_local_sessions SET expires=1')
        self.call('/me', uid=2, status=401)

    def test_pagination_validation_and_history(self):
        for n in range(3):
            self.call('/tasks', data={**self.data, 'title': f'任务{n}'}, status=201)
        page = self.call('/tasks?limit=1&offset=0')
        self.assertEqual((page['total'], page['next_offset']), (3, 1))
        tid = page['items'][0]['id']
        next_page = self.call('/tasks?limit=1&offset=1')
        self.assertNotEqual(tid, next_page['items'][0]['id'])
        self.call('/tasks?limit=101', status=400)
        self.call('/tasks?status=nonsense', status=400)
        self.call('/tasks', data={**self.data, 'deadline': '2027-01-20T18:00'}, status=400)
        self.call('/tasks', data={**self.data, 'title': ['not', 'text']}, status=400)
        self.call('/tasks', data={**self.data, 'members': '1,2'}, status=400)
        for note in ('第一次', '第二次'):
            self.call(f'/tasks/{tid}/actions', data={'action': 'comment', 'body': note})
        events = self.call(f'/tasks/{tid}/events?limit=1')
        self.assertEqual(events['items'][0]['body'], '第一次')
        events = self.call(f'/tasks/{tid}/events?after={events["next_after"]}')
        self.assertEqual(events['items'][0]['body'], '第二次')
        self.call('/tasks/999999', status=404)
        self.call('/tasks/99999999999999999999999', status=400)
        self.assertTrue(self.api.get('/api/v1/missing').is_json)
        self.assertEqual(self.call('/tasks', data={**self.data, 'title': 'x' * 150000}, status=413)['code'], 'http_error')


class CLITest(Fixture):
    def setUp(self):
        super().setUp()
        self.server = make_server('127.0.0.1', 0, self.app, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.config = Path(self.temp.name) / 'cli.json'

    def tearDown(self):
        self.server.shutdown(); self.thread.join(); self.server.server_close()
        super().tearDown()

    def command(self, *args, stdin='', token=None):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {'MISSION_TOKEN': token or '', 'MISSION_SERVER': '', 'MISSION_CONFIG': ''}), \
                patch('sys.stdin', io.StringIO(stdin)), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--server', self.url, '--config', str(self.config), *args, '--json'])
        return code, json.loads(out.getvalue()), err.getvalue()

    def test_real_http_login_create_submit_logout_and_config_permissions(self):
        code, result, err = self.command('login', '--token-stdin', stdin=self.tokens[1])
        self.assertEqual(code, 0, result)
        self.assertNotIn(self.tokens[1], json.dumps(result) + err)
        if os.name != 'nt':
            self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        code, result, _ = self.command('task', 'create', '--input', '-', stdin=json.dumps({**self.data, 'assignee': 2}))
        self.assertEqual(code, 0, result); tid = result['data']['id']
        body = Path(self.temp.name) / '成果 文档.txt'; body.write_text('交付说明\nhttps://example.test/result', encoding='utf-8')
        code, result, _ = self.command('task', 'submit', str(tid), '--body-file', str(body), token=self.tokens[2])
        self.assertEqual(code, 0, result)
        code, result, _ = self.command('task', 'accept', str(tid))
        self.assertEqual(code, 0, result)
        self.assertEqual(result['data']['status'], 'done')
        self.assertEqual(self.command('logout')[0], 0)
        self.assertEqual(self.command('me')[0], 3)
        self.assertNotIn(self.url, json.loads(self.config.read_text())['tokens'])

    def test_offline_schema_usage_errors_and_server_isolation(self):
        self.assertEqual(self.command('schema')[1]['data']['version'], 1)
        self.assertEqual(self.command('task', 'show', 'not-an-id')[0], 2)
        self.assertEqual(self.command('task', 'show', '999', token=self.tokens[1])[0], 4)
        self.command('login', '--token-stdin', stdin=self.tokens[1])
        out = io.StringIO()
        with patch.dict(os.environ, {'MISSION_TOKEN': ''}), contextlib.redirect_stdout(out):
            code = main(['--server', 'https://different.example.test', '--config', str(self.config), 'me', '--json'])
        self.assertEqual(code, 3)
        with self.assertRaises(CLIError):
            server_url('http://remote.example.test')


class TransportTest(unittest.TestCase):
    def test_unknown_write_is_not_repeated_and_reads_retry_once(self):
        client = Client('https://mission.example.test', 'secret-test-token')
        with patch.object(client.opener, 'open', side_effect=urllib.error.URLError('lost connection')) as mocked:
            with self.assertRaises(CLIError) as error:
                client.call('POST', '/tasks', {'title': 'test'})
            self.assertEqual(error.exception.code, 'outcome_unknown')
            self.assertEqual(mocked.call_count, 1)
        with patch.object(client.opener, 'open', side_effect=urllib.error.URLError('offline')) as mocked:
            with self.assertRaises(CLIError) as error:
                client.call('GET', '/me')
            self.assertEqual(error.exception.code, 'network_error')
            self.assertEqual(mocked.call_count, 2)


if __name__ == '__main__':
    unittest.main()
