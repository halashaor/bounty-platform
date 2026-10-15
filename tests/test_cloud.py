import os
import hashlib
import sqlite3
from pathlib import Path
from importlib.resources import files
import tempfile
import unittest
from unittest.mock import patch

from bounty.db import connect
from wsgi import create_cloud_app


class CloudTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        accounts = Path(self.temp.name) / 'accounts.sqlite'
        with sqlite3.connect(accounts) as db:
            db.executescript(files('team_accounts').joinpath('schema.sql').read_text())
            db.execute("INSERT INTO account_metadata VALUES('initialized','test')")
            db.execute("INSERT INTO account_invites VALUES('member',?,1,0,NULL,'test',NULL)",
                       (hashlib.sha256(b'test-invite-123456789').hexdigest(),))
        self.env = patch.dict(os.environ, BOUNTY_DATA_DIR=str(Path(self.temp.name) / 'business'),
                              BOUNTY_DOMAIN='mission.example.test', TEAM_ACCOUNTS_DATABASE=str(accounts),
                              TEAM_SESSION_COOKIE_DOMAIN='example.test')
        self.env.start()
        self.app = create_cloud_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.base = 'https://mission.example.test'

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def post(self, mode, invite=''):
        self.client.get('/auth/login', base_url=self.base)
        with self.client.session_transaction(base_url=self.base) as session:
            csrf = session['csrf']
        return self.client.post('/auth/' + mode, base_url=self.base,
                                data={'name': 'student', 'password': 'test-password', 'invite': invite, 'csrf': csrf})

    def test_invite_required_and_demo_credentials_hidden(self):
        response = self.client.get('/auth/login', base_url=self.base)
        self.assertNotIn('demo12345', response.text)
        cookie = response.headers['Set-Cookie']
        self.assertIn('__Host-mission_forms=', cookie)
        self.assertIn('Secure;', cookie)
        self.assertIn('HttpOnly;', cookie)
        self.assertIn('邀请码无效', self.post('register').text)
        with connect(self.app.config['DATABASE']) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 0)
        self.assertEqual(self.post('register', 'test-invite-123456789').status_code, 302)
        self.assertEqual(self.client.get('/', base_url=self.base).status_code, 200)

    def test_host_and_auth_rate_limit(self):
        self.assertEqual(self.client.get('/healthz', base_url='https://wrong.example.test').status_code, 400)
        self.assertEqual(self.client.get('/healthz', base_url=self.base).json, {'status': 'ok'})
        for _ in range(30):
            self.assertEqual(self.post('login').status_code, 200)
        limited = self.post('login')
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.headers['Retry-After'], '60')
        # Throttle survives service restart.
        restart = create_cloud_app()
        other = restart.test_client()
        other.get('/auth/login', base_url=self.base)
        with other.session_transaction(base_url=self.base) as session:
            csrf = session['csrf']
        self.assertEqual(other.post('/auth/login', base_url=self.base,
                                    data={'csrf': csrf}).status_code, 429)


if __name__ == '__main__':
    unittest.main()
