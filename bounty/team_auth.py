"""Shared account integration. Business users are profiles, never credential copies."""
import os
from pathlib import Path
from flask import g, request, session, redirect, url_for, render_template, flash
from team_accounts import TeamAccounts, AccountError, COOKIE_SECONDS
from .db import connect


def _profiles(path):
    with connect(path) as db:
        if 'identity_id' in {row['name'] for row in db.execute('PRAGMA table_info(users)')}:
            return
        # Profile names are display data. The only unique login name lives in
        # the shared account store; local integer IDs continue owning all tasks.
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE users_team (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, password TEXT NOT NULL DEFAULT '!',
            title_key TEXT, play_seen TEXT NOT NULL DEFAULT '', notes_seen_at TEXT,
            identity_id TEXT UNIQUE)''')
        db.execute('''INSERT INTO users_team(id,name,password,title_key,play_seen,notes_seen_at)
            SELECT id,name,'!',title_key,play_seen,notes_seen_at FROM users''')
        db.execute('DROP TABLE users')
        db.execute('ALTER TABLE users_team RENAME TO users')
        db.execute('CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute("INSERT OR REPLACE INTO app_settings VALUES('shared_accounts','1')")
        db.commit()
        db.execute('PRAGMA foreign_keys=ON')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('账号资料迁移失败，请恢复应用备份。')


def install(app, accounts_path):
    config_path = app.config.get('TEAM_IDENTITY_CONFIG') or os.environ.get('TEAM_IDENTITY_CONFIG')
    if not config_path:
        adjacent = Path(accounts_path).parent/'mission-identity.json'
        if adjacent.exists():
            config_path = str(adjacent)
    if config_path:
        from .central_auth import install as install_central
        return install_central(app, accounts_path, config_path)
    accounts = TeamAccounts(accounts_path)
    app.extensions['team_accounts'] = accounts
    app.config['TEAM_AUTH'] = True
    _profiles(app.config['DATABASE'])
    cookie_domain = app.config.get('TEAM_SESSION_COOKIE_DOMAIN') or os.environ.get('TEAM_SESSION_COOKIE_DOMAIN')
    secure = app.config.get('TEAM_SESSION_COOKIE_SECURE', True)

    def profile(identity):
        with connect(app.config['DATABASE']) as db:
            row = db.execute('SELECT id,name FROM users WHERE identity_id=?', (identity['id'],)).fetchone()
        if row:
            return row
        with connect(app.config['DATABASE'], write=True) as db:
            db.execute("INSERT OR IGNORE INTO users(name,password,identity_id) VALUES(?,'!',?)",
                       (identity['username'], identity['id']))
            return db.execute('SELECT id,name FROM users WHERE identity_id=?', (identity['id'],)).fetchone()

    @app.before_request
    def shared_user():
        session.pop('user_id', None)
        if request.endpoint == 'static':
            g.identity = g.user = None
            return
        g.identity = accounts.principal(request.cookies.get('team_session'))
        g.user = profile(g.identity) if g.identity else None

    def auth(mode):
        if mode not in ('login', 'register'):
            from flask import abort
            abort(404)
        if request.method == 'POST':
            try:
                if mode == 'register':
                    identity, token = accounts.register(request.form.get('name'), request.form.get('password'),
                                                        request.form.get('invite'))
                else:
                    identity, token = accounts.login(request.form.get('name'), request.form.get('password'))
                profile(identity)
                session.clear()
                response = redirect(url_for('index'))
                response.set_cookie('team_session', token, max_age=COOKIE_SECONDS, secure=secure,
                                    httponly=True, samesite='Strict', domain=cookie_domain, path='/')
                return response
            except AccountError as error:
                flash(str(error), 'error')
        return render_template('auth.html', mode=mode)

    def logout():
        accounts.logout(request.cookies.get('team_session'))
        session.clear()
        response = redirect(url_for('index'))
        response.delete_cookie('team_session', domain=cookie_domain, path='/', secure=secure,
                               httponly=True, samesite='Strict')
        return response

    app.view_functions['auth'] = auth
    app.view_functions['logout'] = logout
