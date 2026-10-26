from importlib.resources import files
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import unittest

from app import create_app


class APIIdentityTest(unittest.TestCase):
    def test_browser_authorized_cli_session_obeys_live_identity_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            accounts = Path(tmp) / 'identity.sqlite'
            with sqlite3.connect(accounts) as db:
                db.executescript(files('team_accounts').joinpath('schema.sql').read_text())
                db.executescript('''CREATE TABLE identity_users(id TEXT PRIMARY KEY,provider_pk INTEGER,epoch TEXT);
                    CREATE TABLE identity_access(user_id TEXT,app_id TEXT,allowed INTEGER,expires REAL);
                    CREATE TABLE identity_session_scopes(token_hash TEXT PRIMARY KEY,app_id TEXT,epoch TEXT);''')
                db.executemany('INSERT INTO account_metadata VALUES (?,?)',
                               [('authority', 'authentik'), ('initialized', 'fixture'), ('updated_at', str(time.time() * 1000))])
                db.execute("INSERT INTO accounts VALUES('member','alice','Alice','member',1,X'',X'',0)")
                db.execute("INSERT INTO identity_users VALUES('member',10,'first')")
                db.execute("INSERT INTO identity_access VALUES('member','mission',1,NULL)")
            config = Path(tmp) / 'oidc.json'
            config.write_text(json.dumps(dict(origin='https://mission.example.test', issuer='https://auth.example.test',
                                              clientId='fixture', clientSecret='fixture', portalOrigin='https://portal.example.test',
                                              identityUrl='https://auth.example.test')))
            app = create_app(dict(TESTING=True, DATA_DIR=str(Path(tmp) / 'business'), SECRET_KEY='fixture',
                                  TEAM_ACCOUNTS_DATABASE=str(accounts), TEAM_IDENTITY_CONFIG=str(config)))
            provider = app.extensions['team_accounts']
            with app.test_request_context():
                browser_token = provider.oidc_login({'team_id': 'member', 'portal_pk': 10})[1]
            browser = app.test_client(); base = 'https://mission.example.test'
            browser.set_cookie('__Host-mission_session', browser_token, domain='mission.example.test', secure=True)
            self.assertEqual(browser.get('/cli', base_url=base).status_code, 200)
            with browser.session_transaction(base_url=base) as session:
                csrf = session['csrf']
            response = browser.post('/cli', data={'csrf': csrf}, base_url=base)
            self.assertEqual(response.status_code, 200)
            cli_token = re.search(r'<textarea[^>]*>([^<]+)</textarea>', response.text).group(1)
            self.assertNotEqual(cli_token, browser_token)
            client = app.test_client(); headers = {'Authorization': 'Bearer ' + cli_token}
            me = client.get('/api/v1/me', headers=headers, base_url=base)
            self.assertEqual(me.status_code, 200)
            self.assertEqual(me.json['data']['user']['name'], 'Alice')
            with sqlite3.connect(accounts) as db:
                db.execute('UPDATE identity_access SET allowed=0')
            self.assertEqual(client.get('/api/v1/me', headers=headers, base_url=base).status_code, 401)
            with sqlite3.connect(accounts) as db:
                db.execute('UPDATE identity_access SET allowed=1')
                db.execute("UPDATE account_metadata SET value='0' WHERE key='updated_at'")
            response = client.get('/api/v1/me', headers=headers, base_url=base)
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.json['ok'])
            with sqlite3.connect(Path(tmp) / 'business/bounty.sqlite3') as db:
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='cli_local_sessions'").fetchone())


if __name__ == '__main__':
    unittest.main()
