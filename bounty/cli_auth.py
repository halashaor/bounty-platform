"""Browser-approved CLI credentials. Production delegates to existing Mission identity sessions."""
import secrets
import time

from flask import Blueprint, abort, g, redirect, render_template, request, url_for
from itsdangerous import BadData, URLSafeTimedSerializer
from .db import connect

LOCAL_SECONDS = 7 * 24 * 60 * 60


def install(app):
    if not app.config.get('TEAM_AUTH'):
        # Local-demo sessions only. A configured identity deployment never falls back here.
        signer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='mission-cli-local')
        path = app.config['DATABASE']
        with connect(path, write=True) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS cli_local_sessions (
                id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires INTEGER NOT NULL)''')

        def issue():
            key = secrets.token_urlsafe(32)
            with connect(path, write=True) as db:
                db.execute('DELETE FROM cli_local_sessions WHERE expires<=?', (int(time.time()),))
                db.execute('INSERT INTO cli_local_sessions VALUES (?,?,?)',
                           (key, g.user['id'], int(time.time()) + LOCAL_SECONDS))
            return signer.dumps(key)

        def key_of(token):
            try:
                key = signer.loads(token, max_age=LOCAL_SECONDS)
                return key if isinstance(key, str) else None
            except BadData:
                return None

        def authenticate(token):
            with connect(path) as db:
                return db.execute('''SELECT u.id,u.name FROM cli_local_sessions c JOIN users u ON u.id=c.user_id
                    WHERE c.id=? AND c.expires>?''', (key_of(token), int(time.time()))).fetchone()

        def revoke(token):
            with connect(path, write=True) as db:
                db.execute('DELETE FROM cli_local_sessions WHERE id=?', (key_of(token),))

        app.extensions['mission_cli_auth'] = dict(issue=issue, authenticate=authenticate, revoke=revoke)

    page = Blueprint('mission_cli', __name__)

    @page.route('/cli', methods=['GET', 'POST'])
    def access():
        token = None
        if request.method == 'POST':
            if not g.get('user'):
                return redirect(url_for('auth', mode='login'))
            provider = app.extensions.get('mission_cli_auth')
            if not provider:
                abort(503, description='请先配置独立身份接入，再使用命令行。')
            token = provider['issue']()
        return render_template('cli.html', token=token, available=bool(app.extensions.get('mission_cli_auth')))

    app.register_blueprint(page)
