import hashlib
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from importlib.resources import files
from flask import Flask
from bounty.central_auth import CentralAccounts

class CentralIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'accounts.sqlite'
        with sqlite3.connect(self.path) as db:
            db.executescript(files('team_accounts').joinpath('schema.sql').read_text())
            db.executescript('''CREATE TABLE identity_users(id TEXT PRIMARY KEY,provider_pk INTEGER,epoch TEXT);
            CREATE TABLE identity_access(user_id TEXT,app_id TEXT,allowed INTEGER,expires REAL);
            CREATE TABLE identity_session_scopes(token_hash TEXT PRIMARY KEY,app_id TEXT,epoch TEXT);''')
            db.execute("INSERT INTO account_metadata VALUES('authority','authentik')")
            db.execute("INSERT INTO account_metadata VALUES('initialized','fixture')")
            db.execute("INSERT INTO account_metadata VALUES('updated_at',?)",(str(time.time()*1000),))
            db.execute("INSERT INTO accounts VALUES('member','alice','Alice','member',1,X'',X'',0)")
            db.execute("INSERT INTO identity_users VALUES('member',10,'first')")
            db.execute("INSERT INTO identity_access VALUES('member','mission',1,NULL)")
        self.accounts=CentralAccounts(self.path);self.app=Flask(__name__)
        self.context=self.app.test_request_context();self.context.push()
    def tearDown(self):self.context.pop();self.temp.cleanup()
    def execute(self,query,*params):
        with sqlite3.connect(self.path) as db:db.execute(query,params)
    def token(self):return self.accounts.oidc_login({'team_id':'member','portal_pk':10})[1]
    def test_application_scope_password_epoch_and_revocation(self):
        token=self.token();self.assertEqual(self.accounts.principal(token)['id'],'member')
        self.execute("UPDATE identity_session_scopes SET app_id='amax'");self.assertIsNone(self.accounts.principal(token))
        self.execute("UPDATE identity_session_scopes SET app_id='mission'")
        self.execute("UPDATE identity_users SET epoch='second'");self.assertIsNone(self.accounts.principal(token))
        token=self.token();self.execute('UPDATE identity_access SET allowed=0');self.assertIsNone(self.accounts.principal(token))
    def test_disabled_expired_and_missing_directory_are_rejected(self):
        token=self.token();self.execute('UPDATE accounts SET enabled=0');self.assertIsNone(self.accounts.principal(token))
        self.execute('UPDATE accounts SET enabled=1');self.execute('UPDATE identity_access SET expires=1');self.assertIsNone(self.accounts.principal(token))
        for value in ['0','NaN',str((time.time()+100)*1000)]:
            self.execute("UPDATE account_metadata SET value=? WHERE key='updated_at'",value)
            with self.assertRaises(Exception) as result:self.accounts.principal(token)
            self.assertEqual(result.exception.code,503)
    def test_unverified_provider_identity_cannot_create_a_session(self):
        with self.assertRaises(Exception) as result:self.accounts.oidc_login({'team_id':'member','portal_pk':11})
        self.assertEqual(result.exception.code,403)

if __name__=='__main__':unittest.main()
