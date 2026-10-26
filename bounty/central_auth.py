"""Mission OIDC client. Identity and grants belong to the independent directory."""
import hashlib
import json
import math
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode
from authlib.integrations.flask_client import OAuth
from flask import abort, g, redirect, request, session, url_for
from team_accounts import TeamAccounts, AccountError, COOKIE_SECONDS, IDLE_MS, TOUCH_MS
from .db import connect


class CentralAccounts(TeamAccounts):
    def __init__(self, path):
        super().__init__(path)
        with self.connection() as db:
            source = db.execute("SELECT value FROM account_metadata WHERE key='authority'").fetchone()
            if not source or source[0] != 'authentik':
                raise RuntimeError('请先配置统一身份服务的账号视图。')

    @staticmethod
    def check_fresh(db):
        now = time.time()
        updated = db.execute("SELECT value FROM account_metadata WHERE key='updated_at'").fetchone()
        try:
            age = now*1000-float(updated[0]) if updated else math.inf
        except (ValueError, TypeError):
            age = math.inf
        if not math.isfinite(age) or age < -5000 or age > 60000:
            abort(503, description='账号服务暂时无法连接，请稍后重试。')

    @staticmethod
    def access(db, user_id):
        CentralAccounts.check_fresh(db)
        now = time.time()
        access = db.execute("SELECT * FROM identity_access WHERE user_id=? AND app_id='mission'", (user_id,)).fetchone()
        identity = db.execute('SELECT * FROM identity_users WHERE id=?', (user_id,)).fetchone()
        if not identity or not access or not access['allowed'] or access['expires'] is not None and access['expires'] <= now:
            return None
        return identity

    def oidc_login(self, claims):
        with self.connection(write=True) as db:
            user = db.execute('SELECT * FROM accounts WHERE id=?', (claims.get('team_id'),)).fetchone()
            identity = self.access(db, user['id']) if user else None
            if not user or not user['enabled'] or not identity or identity['provider_pk'] != claims.get('portal_pk'):
                abort(403, description='你暂时没有任务平台的使用权限，请在统一门户查看。')
            return self._mission_session(db, user, identity)

    def _mission_session(self, db, user, identity):
        token = self.issue(db, user)
        db.execute('INSERT INTO identity_session_scopes VALUES(?,?,?)',
                   (hashlib.sha256(token.encode()).hexdigest(), 'mission', identity['epoch']))
        return self.public(user), token

    def cli_login(self, user_id):
        """A separately revocable session, issued only after authenticated browser approval."""
        with self.connection(write=True) as db:
            user = db.execute('SELECT * FROM accounts WHERE id=?', (user_id,)).fetchone()
            identity = self.access(db, user_id)
            if not user or not user['enabled'] or not identity:
                abort(403, description='你暂时没有任务平台的使用权限。')
            return self._mission_session(db, user, identity)

    def principal(self, token):
        if not isinstance(token, str) or len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
            return None
        key, now = hashlib.sha256(token.encode()).hexdigest(), int(time.time()*1000)
        with self.connection(write=True) as db:
            login = db.execute('SELECT * FROM login_sessions_v2 WHERE token_hash=?', (key,)).fetchone()
            if not login or login['expires_at'] <= now:
                return None
            scope = db.execute('SELECT * FROM identity_session_scopes WHERE token_hash=?', (key,)).fetchone()
            identity = self.access(db, login['user_id'])
            user = db.execute('SELECT * FROM accounts WHERE id=?', (login['user_id'],)).fetchone()
            if not scope or scope['app_id'] != 'mission' or not identity or scope['epoch'] != identity['epoch'] or not user or not user['enabled']:
                return None
            if now-login['touched_at'] >= TOUCH_MS:
                db.execute('UPDATE login_sessions_v2 SET touched_at=?,expires_at=? WHERE token_hash=?', (now, now+IDLE_MS, key))
            return self.public(user)


def install(app, accounts_path, config_path):
    from .team_auth import _profiles
    config = json.loads(Path(config_path).read_text())
    origin, issuer = config['origin'].rstrip('/'), config['issuer'].rstrip('/')
    secure = origin.startswith('https:')
    cookie = '__Host-mission_session' if secure else 'mission_session'
    app.config.update(TEAM_AUTH=True, SESSION_COOKIE_NAME='__Host-mission_state' if secure else 'mission_state',
                      SESSION_COOKIE_SECURE=secure, SESSION_COOKIE_DOMAIN=None, SESSION_COOKIE_SAMESITE='Lax')
    accounts = CentralAccounts(config.get('projectionDatabase') or accounts_path)
    app.extensions['team_accounts'] = accounts
    _profiles(app.config['DATABASE'])
    oauth = OAuth(app)
    client = oauth.register('central', client_id=config['clientId'], client_secret=config['clientSecret'],
        server_metadata_url=issuer+'/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid profile portal', 'code_challenge_method': 'S256'})

    def profile(identity):
        with connect(app.config['DATABASE'], write=True) as db:
            db.execute("INSERT OR IGNORE INTO users(name,password,identity_id) VALUES(?,'!',?)", (identity['name'], identity['id']))
            db.execute('UPDATE users SET name=? WHERE identity_id=?', (identity['name'], identity['id']))
            return db.execute('SELECT id,name FROM users WHERE identity_id=?', (identity['id'],)).fetchone()

    def cli_principal(token):
        identity = accounts.principal(token)
        return profile(identity) if identity else None

    app.extensions['mission_cli_auth'] = dict(
        issue=lambda: accounts.cli_login(g.identity['id'])[1],
        authenticate=cli_principal, revoke=accounts.logout)

    @app.before_request
    def central_user():
        session.pop('user_id', None)
        g.identity = g.user = None
        if request.endpoint != 'static' and request.path not in ('/auth/callback', '/auth/login', '/auth/register', '/healthz'):
            g.identity = accounts.principal(request.cookies.get(cookie))
            g.user = profile(g.identity) if g.identity else None

    def auth(mode):
        if mode == 'register':
            return redirect(config['portalOrigin'].rstrip('/')+'/register')
        if mode != 'login':
            abort(404)
        return client.authorize_redirect(origin+'/auth/callback')

    @app.get('/auth/callback')
    def identity_callback():
        token = client.authorize_access_token()
        identity, local_token = accounts.oidc_login(token.get('userinfo') or {})
        profile(identity)
        session.clear()
        session['csrf'] = secrets.token_hex(24)
        response = redirect(url_for('index'))
        response.set_cookie(cookie, local_token, max_age=COOKIE_SECONDS, secure=secure, httponly=True, samesite='Lax', path='/')
        return response

    def logout():
        accounts.logout(request.cookies.get(cookie))
        session.clear()
        response = redirect(config['identityUrl'].rstrip('/')+'/application/o/mission/end-session/?'+urlencode({
            'client_id': config['clientId'], 'post_logout_redirect_uri': origin+'/'}))
        response.delete_cookie(cookie, path='/', secure=secure, httponly=True, samesite='Lax')
        return response

    app.view_functions['auth'] = auth
    app.view_functions['logout'] = logout
