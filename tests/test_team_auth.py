import hashlib
import sqlite3
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path
from app import create_app

try:
    from team_accounts import TeamAccounts
except ImportError:
    TeamAccounts = None


@unittest.skipIf(TeamAccounts is None, 'Install the shared team-accounts package for integration tests')
class SharedAccountsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.accounts_path = root / 'accounts.sqlite'
        self.password = 'Synthetic-Test-Password-Only'
        self.invite = 'Synthetic-Shared-Team-Invite'
        with sqlite3.connect(self.accounts_path) as db:
            db.executescript(files('team_accounts').joinpath('schema.sql').read_text())
            db.execute("INSERT INTO account_metadata VALUES('initialized','test')")
            salt = b'synthetic-salt16'
            db.execute('INSERT INTO accounts VALUES(?,?,?,?,?,?,?,?)',
                       ('existing-member', 'alice', 'Alice', 'member', 1, salt,
                        hashlib.pbkdf2_hmac('sha256', self.password.encode(), salt, 600000), 600000))
            db.execute("INSERT INTO account_invites VALUES('member',?,1,0,NULL,'test',NULL)",
                       (hashlib.sha256(self.invite.encode()).hexdigest(),))
        self.accounts = TeamAccounts(self.accounts_path)
        self.business = root / 'business'
        self.app = create_app({'TESTING': True, 'DATA_DIR': str(self.business),
                               'TEAM_ACCOUNTS_DATABASE': str(self.accounts_path),
                               'TEAM_SESSION_COOKIE_SECURE': False, 'SECRET_KEY': 'synthetic'})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def post(self, path, data=None):
        self.client.get('/auth/login')
        with self.client.session_transaction() as session:
            csrf = session['csrf']
        return self.client.post(path, data={'csrf': csrf, **(data or {})})

    def test_existing_team_member_has_equal_mission_permissions_and_shared_logout(self):
        _, token = self.accounts.login('alice', self.password)
        self.client.set_cookie('team_session', token)
        page = self.client.get('/tags')
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('管理员', page.text)
        self.assertEqual(self.post('/tags', {'name': '团队共同维护'}).status_code, 302)
        self.assertEqual(self.post('/admin/admins', {'name': 'alice', 'on': '1'}).status_code, 404)
        self.assertEqual(self.post('/logout').status_code, 302)
        self.assertIsNone(self.accounts.principal(token))

    def test_registration_is_shared_and_never_stores_local_passwords(self):
        page = self.client.get('/auth/register')
        self.assertIn('name="invite"', page.text)
        response = self.post('/auth/register', {'name': 'bob', 'password': self.password, 'invite': self.invite})
        self.assertEqual(response.status_code, 302)
        user, token = self.accounts.login('bob', self.password)
        self.assertEqual(user['role'], 'member')
        self.assertTrue(self.accounts.principal(token))
        with sqlite3.connect(self.business / 'bounty.sqlite3') as db:
            self.assertEqual(db.execute("SELECT password FROM users WHERE identity_id=?", (user['id'],)).fetchone()[0], '!')
            self.assertNotIn('is_admin', {row[1] for row in db.execute('PRAGMA table_info(users)')})

    def test_disabling_account_revokes_mission_access_without_another_platform_call(self):
        _, token = self.accounts.login('alice', self.password)
        self.client.set_cookie('team_session', token)
        self.assertEqual(self.client.get('/').status_code, 200)
        with sqlite3.connect(self.accounts_path) as db:
            db.execute("UPDATE accounts SET enabled=0 WHERE id='existing-member'")
        self.assertEqual(self.client.get('/').status_code, 302)

    def test_local_session_cannot_bypass_shared_login_and_missing_mount_fails_closed(self):
        _, token = self.accounts.login('alice', self.password)
        self.client.set_cookie('team_session', token)
        self.client.get('/')
        self.client.delete_cookie('team_session')
        with self.client.session_transaction() as session:
            session['user_id'] = 1
        self.assertEqual(self.client.get('/').status_code, 302)
        with self.assertRaisesRegex(RuntimeError, 'TEAM_ACCOUNTS_DATABASE'):
            create_app({'TESTING': True, 'DATA_DIR': str(self.business)})
        self.assertFalse((self.business / 'accounts.sqlite').exists())

    def test_migration_preserves_business_ids_and_does_not_match_people_by_name(self):
        # An unrelated local user with the same visible name does not become Alice.
        with sqlite3.connect(self.business / 'bounty.sqlite3') as db:
            db.execute("INSERT INTO users(id,name,password) VALUES(7,'alice','!')")
        _, token = self.accounts.login('alice', self.password)
        self.client.set_cookie('team_session', token)
        self.client.get('/')
        with sqlite3.connect(self.business / 'bounty.sqlite3') as db:
            linked = db.execute("SELECT id FROM users WHERE identity_id='existing-member'").fetchone()[0]
            self.assertNotEqual(linked, 7)
            self.assertIsNone(db.execute('SELECT identity_id FROM users WHERE id=7').fetchone()[0])

    def test_existing_database_upgrade_keeps_task_ownership_and_retires_local_auth(self):
        from bounty.db import initialize
        legacy = Path(self.temp.name) / 'legacy'
        legacy.mkdir()
        path = legacy / 'bounty.sqlite3'
        initialize(path)
        with sqlite3.connect(path) as db:
            db.execute('ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0')
            db.execute("INSERT INTO users(id,name,password,is_admin) VALUES(7,'alice','old-local-password',1)")
            db.execute('''INSERT INTO tasks(id,title,description,category,importance,urgency,deadline,requirements,owner_id,created_at)
                VALUES(11,'Existing task','Description','代码','light','normal','2099-01-01','Delivery',7,'2026-01-01')''')
        app = create_app({'TESTING': True, 'DATA_DIR': str(legacy),
                          'TEAM_ACCOUNTS_DATABASE': str(self.accounts_path),
                          'TEAM_SESSION_COOKIE_SECURE': False})
        client = app.test_client()
        _, token = self.accounts.login('alice', self.password)
        client.set_cookie('team_session', token)
        self.assertEqual(client.get('/').status_code, 200)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('SELECT owner_id FROM tasks WHERE id=11').fetchone()[0], 7)
            self.assertEqual(db.execute('SELECT password FROM users WHERE id=7').fetchone()[0], '!')
            self.assertIsNone(db.execute('SELECT identity_id FROM users WHERE id=7').fetchone()[0])
            self.assertNotIn('is_admin', {row[1] for row in db.execute('PRAGMA table_info(users)')})
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())


if __name__ == '__main__':
    unittest.main()
