import os
import secrets
import sqlite3
import zlib
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import unquote
from flask import Flask, abort, flash, g, redirect, render_template, render_template_string, request, session, url_for, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from bounty import blocks, discover, games, progress, recap, tags, titles, unlocks
from bounty.db import connect, initialize
from bounty.honors import COLD_DAYS, EFFORT, IMPORTANCE, URGENCY, MEDALS, cold_bonus, medal_key, task_xp
from bounty.service import (CATEGORIES, STATUSES, KINDS, MAX_INTERESTS, TEAM_TZ, InvalidAction, act, clap, create_task,
                            dismiss, is_cold, now, required, set_interests, waited_days, zone)

PAGE_SIZE = 12


def due_label(deadline):
    """Countdown text for cards: (text, is_urgent_looking). Counts hours, not calendar days, so it reads the same
    for teammates in every time zone."""
    moment = datetime.fromisoformat(deadline)
    left = (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)) - datetime.now(timezone.utc)
    if left.total_seconds() < 0:
        return '已截止', True
    if left.days == 0:
        hours = int(left.total_seconds() // 3600)
        return (f'剩 {hours} 小时' if hours else '不到 1 小时'), True
    return f'剩 {left.days} 天', left.days < 2
PRAISE = ('靠谱，一次就过', '超出预期', '救了急', '写得很清楚')
# 方向卡的颜色和图形：按标签文字算出来，同一个方向在谁的屏幕上都长一个样。第二项是压在这个颜色上的字色。
TONES = (('#E54465', '#fff'), ('#F39800', '#1B1D2A'), ('#F2B700', '#1B1D2A'),
         ('#00A27A', '#fff'), ('#00AEE0', '#1B1D2A'), ('#2866B1', '#fff'))


def offer_xp(task):
    """Experience the person who finishes this task gets, including the cold-task bonus."""
    key = medal_key(task)
    return task_xp(key) + (cold_bonus(key) if is_cold(task) else 0)


def cold_days(task):
    """How many days an open task has waited, when that makes it a cold task; otherwise 0."""
    return waited_days(task) if task['status'] == 'open' and is_cold(task) else 0


def tag_look(tag):
    code = zlib.crc32(tag.encode('utf-8'))
    hue, on = TONES[code % len(TONES)]
    return dict(hue=hue, on=on, variant=code // len(TONES) % 6)


def create_app(config=None):
    settings = dict(config or {})
    default_data = Path(__file__).resolve().parent / 'instance'
    data_dir = Path(settings.get('DATA_DIR') or os.environ.get('BOUNTY_DATA_DIR') or
                    (Path(settings['DATABASE']).parent if settings.get('DATABASE') else default_data)).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    app = Flask(__name__, instance_path=str(data_dir), instance_relative_config=True)
    app.config.update(DATABASE=str(data_dir / 'bounty.sqlite3'), DATA_DIR=str(data_dir),
                      MAX_CONTENT_LENGTH=128 * 1024, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Lax', SHOW_DEMO_LOGIN=True, INVITE_CODE='')
    app.config.update(settings)
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    if not app.config.get('SECRET_KEY'):
        secret_path = Path(app.instance_path) / 'secret.key'
        try:
            with secret_path.open('x') as handle:
                os.chmod(secret_path, 0o600)
                handle.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config['SECRET_KEY'] = secret_path.read_text()
    initialize(app.config['DATABASE'])
    if not (app.config.get('TEAM_ACCOUNTS_DATABASE') or os.environ.get('TEAM_ACCOUNTS_DATABASE')):
        with connect(app.config['DATABASE']) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_settings'").fetchone() and db.execute("SELECT 1 FROM app_settings WHERE key='shared_accounts'").fetchone():
                raise RuntimeError('此数据目录使用团队统一账号，请配置 TEAM_ACCOUNTS_DATABASE。')

    @app.get('/healthz')
    def health():
        with connect(app.config['DATABASE']) as db:
            db.execute('SELECT 1 FROM users LIMIT 1').fetchone()
        if app.extensions.get('team_accounts'):
            with app.extensions['team_accounts'].connection() as accounts:
                accounts.execute('SELECT 1 FROM accounts LIMIT 1').fetchone()
        return jsonify(status='ok')

    @app.after_request
    def response_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'same-origin')
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response

    def database(write=False):
        return connect(app.config['DATABASE'], write=write)

    @app.before_request
    def load_user():
        g.user = None
        # 浏览器把自己的时区写在 tz cookie 里（见 base.html），页面上的时间都按看的人当地时间显示
        g.tz_name = unquote(request.cookies.get('tz', ''))
        g.tz = zone(g.tz_name)
        if g.tz is TEAM_TZ:
            g.tz_name = ''
        if session.get('user_id'):
            with database() as db:
                g.user = db.execute('SELECT id,name FROM users WHERE id=?', (session['user_id'],)).fetchone()
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(24)
        # 表单放在 csrf 字段里；积木存档这类 JSON 请求放在 X-CSRF-Token 头里
        token = request.form.get('csrf') or request.headers.get('X-CSRF-Token', '')
        if request.method == 'POST' and not secrets.compare_digest(session['csrf'].encode('utf-8'), token.encode('utf-8')):
            abort(400, description='表单已过期，请刷新后重试。')

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for('auth', mode='login'))
            return view(*args, **kwargs)
        return wrapped

    # Globals (not a context processor) so imported macros such as the medal can read them too.
    app.jinja_env.globals.update(categories=CATEGORIES, statuses=STATUSES, kinds=KINDS, importance_labels=IMPORTANCE,
                                 urgency_labels=URGENCY, effort_labels=EFFORT, medals=MEDALS, medal_key=medal_key,
                                 task_xp=progress.task_xp, praise_options=PRAISE, due_label=due_label, tag_look=tag_look,
                                 max_interests=MAX_INTERESTS, local_now=lambda: datetime.now(g.tz), offer_xp=offer_xp,
                                 cold_days=cold_days, is_cold=is_cold, title_names=titles.BY_KEY,
                                 block_parts=blocks.PARTS, block_colors=blocks.COLORS, block_bgs=blocks.BACKGROUNDS)

    def page_url(**changes):
        """Same page, same filters, with a few changed; empty values drop out of the URL."""
        args = {**request.args.to_dict(), **changes}
        return url_for(request.endpoint, **{k: v for k, v in args.items() if v not in ('', None)})

    app.jinja_env.globals['page_url'] = page_url

    @app.context_processor
    def context():
        extra = dict(current_time=now(), mailbox=0, me=None, my_turn=0, play_new=0, my_title=None)
        if g.get('user'):
            with database() as db:
                # 信箱里装两种东西：还没拆的勋章，和刚解锁、还没庆祝过的称号
                extra['mailbox'] = db.execute('SELECT COUNT(*) FROM honors WHERE user_id=? AND seen_at IS NULL',
                                              (g.user['id'],)).fetchone()[0] + len(titles.unseen(db, g.user['id']))
                extra['play_new'] = unlocks.new_count(db, g.user['id'])
                extra['my_title'] = titles.chosen_title(db, g.user['id'])
                extra['me'] = progress.person_progress(db, g.user['id'])
                # 轮到我的事：我在做的、等我验收的
                extra['my_turn'] = db.execute('''SELECT COUNT(*) FROM tasks WHERE (assignee_id=? AND status='active')
                    OR (owner_id=? AND status='review')''', (g.user['id'], g.user['id'])).fetchone()[0]
        return extra

    def local(value):
        moment = datetime.fromisoformat(value)
        return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).astimezone(g.get('tz') or TEAM_TZ)

    @app.template_filter('date')
    def date(value):
        return f'{local(value):%m/%d %H:%M}' if value else ''

    @app.template_filter('md')
    def month_day(value):
        moment = local(value) if value else None
        return f'{moment.month}/{moment.day}' if moment else ''

    def back():
        # Only follow a referrer from this same site, so a crafted Referer cannot bounce people elsewhere.
        target = request.referrer or ''
        return redirect(target if target.startswith(request.host_url) else url_for('index'))

    @app.route('/auth/<mode>', methods=['GET', 'POST'])
    def auth(mode):
        if mode not in ('login', 'register'):
            abort(404)
        if request.method == 'POST':
            try:
                if mode == 'register' and app.config['INVITE_CODE'] and not secrets.compare_digest(
                        request.form.get('invite', '').encode(), app.config['INVITE_CODE'].encode()):
                    raise InvalidAction('邀请码不正确，请向团队负责人获取。')
                name = required(request.form, 'name', '用户名', 40)
                password = request.form.get('password', '')
                if not 8 <= len(password) <= 128:
                    raise InvalidAction('密码长度须为 8–128 个字符。')
                with database(write=True) as db:
                    if mode == 'register':
                        try:
                            user_id = db.execute('INSERT INTO users (name,password) VALUES (?,?)', (name, generate_password_hash(password))).lastrowid
                        except sqlite3.IntegrityError:
                            raise InvalidAction('用户名已被使用。')
                    else:
                        user = db.execute('SELECT * FROM users WHERE name=?', (name,)).fetchone()
                        if not user or not check_password_hash(user['password'], password):
                            raise InvalidAction('用户名或密码不正确。')
                        user_id = user['id']
                session.clear()
                session['user_id'] = user_id
                return redirect(url_for('index'))
            except InvalidAction as error:
                flash(str(error), 'error')
        return render_template('auth.html', mode=mode)

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('index'))

    @app.get('/')
    @login_required
    def index():
        scope = request.args.get('scope', 'all')
        tag = request.args.get('tag') or request.args.get('category', '')
        project, query, effort = (request.args.get(k, '') for k in ('project', 'q', 'effort'))
        status = request.args.get('status', 'open')
        unlock = request.args.get('unlock') == '1'
        batch, want_batch = (int(value) if value.isdigit() else 0
                             for value in (request.args.get('batch', '0'), request.args.get('wb', '0')))
        clauses, params = [], []
        if scope in ('published', 'claimed'):
            clauses.append('t.owner_id=?' if scope == 'published' else 't.assignee_id=?')
            params.append(g.user['id'])
        if tag:
            clauses.append('t.id IN (SELECT task_id FROM task_tags WHERE tag=?)'); params.append(tag)
        if project:
            clauses.append('t.project=?'); params.append(project)
        if status in STATUSES:
            clauses.append('t.status=?'); params.append(status)
        if effort in IMPORTANCE:
            clauses.append('t.importance=?'); params.append(effort)
        medal = request.args.get('medal', '')
        if medal in MEDALS:
            importance, urgency = medal.split('-')
            clauses.extend(['t.importance=?', 't.urgency=?', 't.owner_id<>?', 't.deadline>?'])
            params.extend([importance, urgency, g.user['id'], now()])
        if query:
            clauses.append('(t.title LIKE ? OR t.description LIKE ?)'); params.extend([f'%{query}%'] * 2)
        with database() as db:
            earned = discover.earned_keys(db, g.user['id'])
            tasks = db.execute('SELECT t.*,u.name owner_name FROM tasks t JOIN users u ON u.id=t.owner_id' +
                               (' WHERE ' + ' AND '.join(clauses) if clauses else '') +
                               " ORDER BY t.status='done', t.urgency='urgent' DESC, t.deadline, t.id DESC", params).fetchall()
            if unlock:
                tasks = [task for task in tasks if medal_key(task) not in earned]
            counts = {row['status']: row['n'] for row in db.execute('SELECT status,COUNT(*) n FROM tasks GROUP BY status')}
            # 筛选条从现有任务里长出来：新标签、新项目一出现就能点
            top_tags = [row['tag'] for row in db.execute('''SELECT tag,COUNT(*) n FROM task_tags JOIN tasks t ON t.id=task_id
                WHERE t.status='open' GROUP BY tag ORDER BY n DESC,tag LIMIT 10''')]
            projects = [row['project'] for row in db.execute('''SELECT project,MAX(created_at) latest FROM tasks
                WHERE project IS NOT NULL GROUP BY project ORDER BY latest DESC''')]
            tags_of = discover.tags_by_task(db)
            lanes = picks_for(db, want_batch, batch)
            hand = db.execute('''SELECT * FROM tasks WHERE (assignee_id=? AND status='active') OR (owner_id=? AND status='review')
                ORDER BY deadline LIMIT 3''', (g.user['id'], g.user['id'])).fetchall()
            feed = discover.team_feed(db, g.user['id'])
            week = discover.week_summary(db, g.tz)
            bundles = progress.team_bundles(db)
            notes = clap_notes(db)
            term = recap.term_of(datetime.now(timezone.utc))
            term_left = recap.days_left(term)
        zones = [tasks[i:i + PAGE_SIZE] for i in range(0, len(tasks), PAGE_SIZE)] or [[]]
        unlockable = sum(1 for task in tasks if task['status'] == 'open' and medal_key(task) not in earned)
        return render_template('index.html', tasks=tasks, zones=zones, scope=scope, tag=tag, project=project, status=status,
                               query=query, effort=effort, unlock=unlock, batch=batch, want_batch=want_batch, counts=counts,
                               hand=hand, feed=feed, week=week, bundles=bundles, earned_keys=earned, unlockable=unlockable,
                               top_tags=top_tags, projects=projects, tags_of=tags_of, notes=notes,
                               term=term, term_label=recap.label(term), term_left=term_left, **lanes)

    def clap_notes(db):
        """鼓掌的回声：自上次来过之后，队友又为你完成的任务鼓了掌，就在首页留一张纸条（看过就收起来）。"""
        seen = db.execute('SELECT notes_seen_at FROM users WHERE id=?', (g.user['id'],)).fetchone()[0] or ''
        recent = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        notes = db.execute('''SELECT t.id,t.title,COUNT(*) n,GROUP_CONCAT(u.name,'、') names,
                (SELECT COUNT(*) FROM claps a WHERE a.task_id=t.id) total
            FROM claps c JOIN tasks t ON t.id=c.task_id JOIN users u ON u.id=c.user_id
            WHERE t.assignee_id=? AND c.created_at>? AND c.created_at>?
            GROUP BY t.id ORDER BY MAX(c.created_at) DESC''', (g.user['id'], seen, recent)).fetchall()
        if notes:
            with database(write=True) as writer:
                writer.execute('UPDATE users SET notes_seen_at=? WHERE id=?', (now(), g.user['id']))
        return notes

    def picks_for(db, want_batch=0, past_batch=0):
        """The two recommendation lanes: what you picked as directions, and what you have done before. Never the same task twice."""
        interests = [row['tag'] for row in db.execute('SELECT tag FROM interests WHERE user_id=? ORDER BY rowid', (g.user['id'],))]
        want = discover.recommend(db, g.user['id'], batch=want_batch, lane='want') if interests else []
        past = discover.recommend(db, g.user['id'], batch=past_batch, lane='past', exclude={pick['task']['id'] for pick in want})
        chosen = discover.directions(db, interests)
        chosen.sort(key=lambda option: not option['chosen'])   # 上次选的排在最前面，不用翻找
        history = discover.past_tags(db, g.user['id'])
        # 还没有任何和自己经历有关的推荐时，第二排叫「先上手试试」
        starter = not history and not any(pick['reasons'][0][0] in ('skill', 'project', 'similar') for pick in past)
        return dict(interests=interests, want=want, past=past, directions=chosen, history=history, starter=starter)

    # 换一批、改方向、不感兴趣之后，只重画对应那一排推荐
    LANE = "{% from 'components/picks.html' import lane_body %}{{ lane_body(lane, picks, interests) }}"

    @app.get('/picks/<lane>')
    @login_required
    def lane_picks(lane):
        if lane not in ('want', 'past'):
            abort(404)
        page, want_page = (int(value) if value.isdigit() else 0
                           for value in (request.args.get('batch', '0'), request.args.get('wb', '0')))
        with database() as db:
            # 「按你做过的」要避开第一排此刻正显示的那几张，所以带上第一排翻到了第几批
            lanes = picks_for(db, page if lane == 'want' else want_page, page if lane == 'past' else 0)
        return render_template_string(LANE, lane=lane, picks=lanes[lane], interests=lanes['interests'])

    @app.post('/me/interests')
    @login_required
    def interests():
        wants_json = request.accept_mimetypes.best == 'application/json'
        try:
            tags = set_interests(app.config['DATABASE'], g.user['id'], ' '.join(request.form.getlist('tags')))
        except InvalidAction as error:
            if wants_json:
                return jsonify(error=str(error)), 400
            flash(str(error), 'error')
            return back()
        if wants_json:
            return jsonify(interests=tags)
        return redirect(url_for('index') + '#dirs')

    @app.get('/mine')
    @login_required
    def mine():
        with database() as db:
            groups = discover.my_tasks(db, g.user['id'])
        return render_template('mine.html', groups=groups)

    @app.route('/tasks/new', methods=['GET', 'POST'])
    @login_required
    def new_task():
        if request.method == 'POST':
            # 标签：从团队标签表里勾的，加上自己新写的（新写的会加进标签表）
            payload = request.form.to_dict()
            payload['tags'] = ' '.join(request.form.getlist('tags') + [request.form.get('new_tags', '')])
            try:
                task_id = create_task(app.config['DATABASE'], g.user['id'], payload, g.tz)
                flash('任务已发布。', 'success')
                return redirect(url_for('detail', task_id=task_id))
            except InvalidAction as error:
                flash(str(error), 'error')
        with database() as db:
            team_tags = tags.listing(db)
            projects = [row['project'] for row in db.execute('SELECT DISTINCT project FROM tasks WHERE project IS NOT NULL ORDER BY project')]
        return render_template('new.html', team_tags=team_tags, projects=projects, picked=request.form.getlist('tags'))

    # ---------------- 团队共同维护标签 ----------------
    @app.get('/tags')
    @login_required
    def team_tags():
        with database() as db:
            listing = tags.listing(db)
            loose = [row['tag'] for row in db.execute('''SELECT DISTINCT x.tag FROM task_tags x JOIN tasks t ON t.id=x.task_id
                WHERE t.status<>'done' AND x.tag NOT IN (SELECT name FROM org_tags) ORDER BY x.tag''')]
        return render_template('team_tags.html', listing=listing, loose=loose, note_limit=tags.NOTE_LIMIT)

    def tag_action(action, message):
        try:
            result = action()
            flash(message(result) if callable(message) else message, 'success')
        except InvalidAction as error:
            flash(str(error), 'error')
        return redirect(url_for('team_tags') + (request.form.get('anchor') or ''))

    @app.post('/tags')
    @login_required
    def add_tag():
        return tag_action(lambda: tags.add(app.config['DATABASE'], g.user['id'], request.form.get('name', ''), request.form.get('note', '')),
                            lambda name: f'加上了「{name}」。')

    @app.post('/tags/update')
    @login_required
    def update_tag():
        def done(result):
            name, merged = result
            return f'已经并进「{name}」。' if merged else f'「{name}」改好了。'
        return tag_action(lambda: tags.update(app.config['DATABASE'], g.user['id'], request.form.get('name', ''),
                                                request.form.get('note', ''), request.form.get('rename', '')), done)

    @app.post('/tags/move')
    @login_required
    def move_tag():
        return tag_action(lambda: tags.move(app.config['DATABASE'], g.user['id'], request.form.get('name', ''),
                                              1 if request.form.get('step') == 'down' else -1), '顺序调好了。')

    @app.post('/tags/delete')
    @login_required
    def delete_tag():
        name = request.form.get('name', '')
        return tag_action(lambda: tags.remove(app.config['DATABASE'], g.user['id'], name), f'「{name}」从表里拿掉了。')

    @app.get('/honors')
    @login_required
    def honors():
        with database() as db:
            awards = db.execute('''SELECT h.*,t.title,u.name owner_name,
                    (SELECT body FROM events e WHERE e.task_id=h.task_id AND e.kind='accept' ORDER BY e.id DESC LIMIT 1) praise,
                    (SELECT COUNT(*) FROM claps c WHERE c.task_id=h.task_id) claps
                FROM honors h JOIN tasks t ON t.id=h.task_id JOIN users u ON u.id=t.owner_id
                WHERE h.user_id=? ORDER BY h.awarded_at DESC,h.task_id DESC''', (g.user['id'],)).fetchall()
            featured = [row['medal_key'] for row in db.execute(
                'SELECT medal_key FROM featured_honors WHERE user_id=? ORDER BY slot', (g.user['id'],))]
            stats = discover.person_stats(db, g.user['id'])
            levels = progress.everyone_levels(db)
            team = []
            for user in db.execute('SELECT id,name FROM users ORDER BY id').fetchall():
                shown = [row['medal_key'] for row in db.execute(
                    'SELECT medal_key FROM featured_honors WHERE user_id=? ORDER BY slot', (user['id'],))]
                kinds = [row['medal_key'] for row in db.execute(
                    'SELECT medal_key,COUNT(*) n FROM honors WHERE user_id=? GROUP BY medal_key ORDER BY n DESC', (user['id'],))]
                team.append(dict(id=user['id'], name=user['name'], featured=shown or kinds[:3],
                                 level=levels.get(user['id'], progress.level_info(0)),
                                 title=titles.chosen_title(db, user['id']), complete=len(kinds) == len(MEDALS),
                                 build=None))
            team.sort(key=lambda person: (-person['level']['xp'], person['id']))
            shown_builds = blocks.shown_by_user(db)
            for person in team:
                person['build'] = shown_builds.get(person['id'])
            bundles = progress.team_bundles(db)
            interests = [row['tag'] for row in db.execute('SELECT tag FROM interests WHERE user_id=? ORDER BY rowid', (g.user['id'],))]
            title_board = titles.board(db, g.user['id'])
            first_task = db.execute('SELECT task_id FROM honors WHERE user_id=? ORDER BY awarded_at,task_id LIMIT 1',
                                    (g.user['id'],)).fetchone()
            # 还没拿到的勋章，告诉他现在有几个任务能拿到
            can_get = {key: 0 for key in MEDALS}
            for task in discover.open_tasks(db, g.user['id']):
                can_get[medal_key(task)] += 1
        by_key = {key: [award for award in awards if award['medal_key'] == key] for key in MEDALS}
        # 没挑过名牌勋章的人，先用拿得最多的三种撑起名牌
        plate_medals = featured or sorted((key for key in MEDALS if by_key[key]), key=lambda key: -len(by_key[key]))[:3]
        case = {}
        for key, info in MEDALS.items():
            got = by_key[key]
            importance, urgency = key.split('-')
            praised = next((award for award in got if award['praise'] and award['praise'] != '成果验收通过。'), None)
            face = praised or (got[0] if got else None)
            case[key] = dict(
                name=info['name'], hue=info['hue'], count=len(got), xp=sum(task_xp(key) + award['bonus'] for award in got),
                each=progress.task_xp(key), kind=f'{EFFORT[importance]} · {IMPORTANCE[importance]} · {URGENCY[urgency]}',
                first=month_day(got[-1]['awarded_at']) if got else '', can_get=can_get[key], plate=key in featured,
                find=url_for('index', medal=key) + '#browse-title',
                # 勋章背面：刻最近一句夸奖，没有夸奖就刻任务名
                back=dict(quote=face['praise'] if praised else face['title'], by=face['owner_name'],
                          on=month_day(face['awarded_at']), praised=bool(praised)) if face else None,
                history=[dict(title=award['title'], by=award['owner_name'], on=month_day(award['awarded_at']), claps=award['claps'],
                              debut=bool(first_task) and award['task_id'] == first_task[0], bonus=award['bonus'],
                              praise=award['praise'] if award['praise'] and award['praise'] != '成果验收通过。' else '',
                              task=url_for('detail', task_id=award['task_id'])) for award in got])
        return render_template('honors.html', awards=awards, by_key=by_key, featured=featured, plate_medals=plate_medals,
                               stats=stats, team=team, bundles=bundles, rows=progress.ROWS, case=case, interests=interests,
                               title_board=title_board, term=recap.term_of(datetime.now(timezone.utc)),
                               my_build=shown_builds.get(g.user['id']))

    @app.post('/honors/title')
    @login_required
    def choose_title():
        wants_json = request.accept_mimetypes.best == 'application/json'
        try:
            with database(write=True) as db:
                titles.choose(db, g.user['id'], request.form.get('title', ''))
        except InvalidAction as error:
            if wants_json:
                return jsonify(error=str(error)), 400
            flash(str(error), 'error')
            return redirect(url_for('honors') + '#titles')
        if wants_json:
            return jsonify(ok=True)
        flash('名牌上的称号换好了。', 'success')
        return redirect(url_for('honors') + '#titles')

    @app.post('/honors/featured')
    @login_required
    def feature_honors():
        keys = list(dict.fromkeys(request.form.getlist('medals')))
        try:
            if len(keys) > 3 or any(key not in MEDALS for key in keys):
                raise InvalidAction('最多展示三种已获得的勋章。')
            with database(write=True) as db:
                earned = {row['medal_key'] for row in db.execute(
                    'SELECT medal_key FROM honors WHERE user_id=?', (g.user['id'],))}
                if any(key not in earned for key in keys):
                    raise InvalidAction('只能展示自己已获得的勋章。')
                db.execute('DELETE FROM featured_honors WHERE user_id=?', (g.user['id'],))
                db.executemany('INSERT INTO featured_honors (user_id,slot,medal_key) VALUES (?,?,?)',
                               [(g.user['id'], i + 1, key) for i, key in enumerate(keys)])
            flash('名牌已保存。', 'success')
        except InvalidAction as error:
            flash(str(error), 'error')
        return redirect(url_for('honors'))

    @app.post('/honors/reveal')
    @login_required
    def reveal_honors():
        # Read and mark in one transaction: refreshing or opening two tabs cannot replay a batch.
        with database(write=True) as db:
            awards = db.execute("""SELECT h.task_id,h.medal_key,h.bonus,t.title,t.importance,t.cold,u.name owner,
                    (SELECT body FROM events e WHERE e.task_id=h.task_id AND e.kind='accept' ORDER BY e.id DESC LIMIT 1) praise
                FROM honors h JOIN tasks t ON t.id=h.task_id JOIN users u ON u.id=t.owner_id
                WHERE h.user_id=? AND h.seen_at IS NULL ORDER BY h.awarded_at,h.task_id LIMIT 12""", (g.user['id'],)).fetchall()
            db.executemany('UPDATE honors SET seen_at=? WHERE task_id=? AND user_id=?',
                           [(now(), row['task_id'], g.user['id']) for row in awards])
            after = progress.person_progress(db, g.user['id'])
            titles_before = db.execute('SELECT COUNT(*) FROM titles_seen WHERE user_id=?', (g.user['id'],)).fetchone()[0]
            fresh_titles = titles.take_unseen(db, g.user['id'])
        # 这一批之前是什么样：用来算"第一枚""新种类""凑齐一行""全收集""升级"这些要放大庆祝的时刻
        counts = dict(after['counts'])
        for row in awards:
            counts[row['medal_key']] -= 1
        xp_before = after['xp'] - sum(task_xp(row['medal_key']) + row['bonus'] for row in awards)
        total_before = after['total'] - len(awards)
        items = []
        for index, row in enumerate(awards):
            first = counts[row['medal_key']] == 0
            before = dict(counts)
            counts[row['medal_key']] += 1
            completed_row = next((label for label, members in progress.ROWS.values()
                                  if row['medal_key'] in members and first and all(counts[k] for k in members)), None)
            everything = first and all(counts.values())
            items.append(dict(task_id=row['task_id'], medal_key=row['medal_key'], title=row['title'], owner=row['owner'],
                              praise=row['praise'], name=MEDALS[row['medal_key']]['name'],
                              xp=task_xp(row['medal_key']) + row['bonus'], bonus=row['bonus'],
                              opens=unlocks.opened_by(before, counts, titles_before), debut=total_before == 0 and index == 0,
                              first=first, row=completed_row,
                              tier='all' if everything else 'row' if completed_row else 'new' if first else 'plain'))
        counts_before = dict(after['counts'])
        for row in awards:
            counts_before[row['medal_key']] -= 1
        return jsonify(awards=items, before=progress.level_info(xp_before),
                       unlocks=unlocks.opened_by(counts_before, after['counts'], titles_before, titles_before + len(fresh_titles)),
                       titles=[dict(key=t['key'], name=t['name'], how=t['how'], color=t['color']) for t in fresh_titles],
                       after={k: after[k] for k in ('xp', 'level', 'name', 'into', 'span', 'to_next', 'percent', 'kinds', 'complete')})

    # ---------------- 縁側（游戏角）：全都随便玩；勋章解锁积木的颜色和零件、游戏的玩法和印章，解锁了就一直在 ----------------
    def json_error(error):
        return jsonify(error=str(error)), 400

    @app.get('/play')
    @login_required
    def play():
        with database(write=True) as db:
            board = unlocks.board(db, g.user['id'])
            state = games.lines_state(db, g.user['id'])
            best = games.stamp_best(db, g.user['id'])
            game_titles = [item for item in titles.board(db, g.user['id']) if item['key'] in games.GAME_TITLES]
            daily_done = bool(db.execute('SELECT 1 FROM daily_solved WHERE user_id=? AND day=?', (g.user['id'], games.today())).fetchone())
            daily_count = games.daily_count(db)
            mine = blocks.mine(db, g.user['id'])
            wall = list(blocks.shown_by_user(db).values())
            unlocks.mark_seen(db, g.user['id'])   # 看过了，导航上的「新」收起来
        have = {item['id'] for item in board if item['open']}
        return render_template('play.html', board=board, lines=state, best=best, modes=games.MODES, have=have,
                               game_titles=game_titles, levels=games.LEVELS, daily_done=daily_done, daily_count=daily_count,
                               mine=mine[:4], builds=len(mine), wall=wall, part_shapes=blocks.PARTS, colors=blocks.COLORS)

    # ---------- 积木 ----------
    @app.get('/play/blocks')
    @login_required
    def play_blocks():
        wanted = request.args.get('id', '')
        with database() as db:
            parts, colors = blocks.palette(db, g.user['id'])
            mine = blocks.mine(db, g.user['id'])
        build = next((item for item in mine if str(item['id']) == wanted), None)
        if wanted and not build:
            return redirect(url_for('play_blocks'))
        editor = dict(parts={part['id']: {k: part[k] for k in ('w', 'h', 'shape', 'open', 'name', 'need')} for part in parts},
                      colors={color['id']: {k: color[k] for k in ('hex', 'open', 'name', 'need')} for color in colors},
                      backgrounds=blocks.BACKGROUNDS, build=build)
        return render_template('blocks.html', parts=parts, colors=colors, mine=mine, build=build, size=blocks.BOARD,
                               backgrounds=blocks.BACKGROUNDS, max_parts=blocks.MAX_PARTS, editor=editor)

    @app.post('/play/blocks/save')
    @login_required
    def save_build():
        data = request.get_json(silent=True) or {}
        build_id = data.get('id')
        try:
            saved = blocks.save(app.config['DATABASE'], g.user['id'], build_id if isinstance(build_id, int) else None,
                                data.get('name', ''), data.get('bg', 'paper'), data.get('parts'))
        except InvalidAction as error:
            return json_error(error)
        return jsonify(id=saved, url=url_for('play_blocks', id=saved))

    @app.post('/play/blocks/<int:build_id>/show')
    @login_required
    def show_build(build_id):
        try:
            shown = blocks.show(app.config['DATABASE'], g.user['id'], build_id)
        except InvalidAction as error:
            return json_error(error)
        return jsonify(shown=shown)

    @app.post('/play/blocks/<int:build_id>/delete')
    @login_required
    def delete_build(build_id):
        try:
            blocks.delete(app.config['DATABASE'], g.user['id'], build_id)
        except InvalidAction as error:
            flash(str(error), 'error')
        return redirect(url_for('play_blocks'))

    # ---------- 一笔画 ----------
    def lines_page(kind, value, board):
        with database() as db:
            state = games.lines_state(db, g.user['id'])
            daily = dict(done=bool(db.execute('SELECT 1 FROM daily_solved WHERE user_id=? AND day=?',
                                              (g.user['id'], games.today())).fetchone()), count=games.daily_count(db))
        name, nodes, edges = board
        solve = {'level': lambda: url_for('solve_lines', level=value), 'daily': lambda: url_for('solve_daily'),
                 'random': lambda: url_for('solve_random', seed=value)}[kind]()
        return render_template('lines.html', kind=kind, value=value, state=state, name=name, levels=games.LEVELS,
                               board=dict(nodes=nodes, edges=edges), solve=solve, daily=daily,
                               random_need=unlocks.need_text(unlocks.BY_ID['random'][3]))

    @app.get('/play/lines')
    @login_required
    def play_lines():
        with database() as db:
            state = games.lines_state(db, g.user['id'])
        wanted = request.args.get('level', '')
        unsolved = [n for n in state['open'] if n not in state['solved']]
        level = int(wanted) if wanted.isdigit() else (unsolved[0] if unsolved else state['open'][-1])
        if level not in state['open']:
            return redirect(url_for('play_lines'))
        return lines_page('level', level, games.LEVELS[level - 1])

    @app.get('/play/lines/daily')
    @login_required
    def play_daily():
        return lines_page('daily', games.today(), games.daily_board(games.today()))

    @app.get('/play/lines/random')
    @app.get('/play/lines/random/<int:seed>')
    @login_required
    def play_random(seed=None):
        with database() as db:
            if not games.lines_state(db, g.user['id'])['random']:
                flash(f'随机一笔要{unlocks.need_text(unlocks.BY_ID["random"][3])}才开。', 'error')
                return redirect(url_for('play'))
        if seed is None or seed > 2 ** 31:
            return redirect(url_for('play_random', seed=secrets.randbelow(10 ** 6)))
        return lines_page('random', seed, games.random_board(seed))

    def solve_with(kind, value):
        raw = request.form.get('stroke', '')
        try:
            stroke = [int(part) for part in raw.split(',')] if raw else []
        except ValueError:
            return json_error('笔画数据不对。')
        try:
            result = games.solve(app.config['DATABASE'], g.user['id'], kind, value, stroke)
        except InvalidAction as error:
            return json_error(error)
        state = result['state']
        reply = dict(first=result['first'], titles=result['titles'], solved=len(state['solved']), total=state['total'],
                     daily=result['daily'])
        if kind == 'level' and value < state['total']:
            reply['next'] = url_for('play_lines', level=value + 1) if value + 1 in state['open'] else None
        elif kind == 'random':
            reply['next'] = url_for('play_random')
        return jsonify(reply)

    @app.post('/play/lines/<int:level>')
    @login_required
    def solve_lines(level):
        return solve_with('level', level)

    @app.post('/play/lines/daily')
    @login_required
    def solve_daily():
        return solve_with('daily', games.today())

    @app.post('/play/lines/random/<int:seed>')
    @login_required
    def solve_random(seed):
        return solve_with('random', seed)

    # ---------- 盖章挑战 ----------
    @app.get('/play/stamp')
    @login_required
    def play_stamp():
        with database() as db:
            best = games.stamp_best(db, g.user['id'])
            have = unlocks.unlocked(db, g.user['id'])
            title = titles.chosen_title(db, g.user['id']) or next(
                (item for item in titles.board(db, g.user['id']) if item['done'] and item['seen']), None)
        needs = {item[0]: unlocks.need_text(item[3]) for item in unlocks.ITEMS}
        modes = {key: dict(mode, open=games.mode_open(have, key), need=needs.get(mode['unlock'], ''))
                 for key, mode in games.MODES.items()}
        styles = [dict(key=key, name=name, open=unlock is None or unlock in have, need=needs.get(unlock, ''))
                  for key, name, unlock in games.STYLES]
        styles.append(dict(key='title', name=title['name'] if title else '称号', open=bool(title) and 'style:title' in have,
                           need=needs['style:title'], color=title['color'] if title else None))
        return render_template('stamp.html', best=best, modes=modes, styles=styles)

    @app.post('/play/stamp/start')
    @login_required
    def start_stamp():
        mode = request.form.get('mode', 'normal')
        try:
            run = games.start_stamp(app.config['DATABASE'], g.user['id'], mode)
        except InvalidAction as error:
            return json_error(error)
        return jsonify(run=run, finish=url_for('finish_stamp', run_id=run), mode=mode, **games.MODES[mode])

    @app.post('/play/stamp/<int:run_id>')
    @login_required
    def finish_stamp(run_id):
        try:
            score, combo = (int(request.form.get(name, '')) for name in ('score', 'combo'))
        except ValueError:
            return json_error('分数不对，没有记录。')
        try:
            result = games.finish_stamp(app.config['DATABASE'], g.user['id'], run_id, score, combo)
        except InvalidAction as error:
            return json_error(error)
        return jsonify(result)

    # ---------------- 学期绘卷 ----------------
    @app.get('/recap')
    @login_required
    def recap_page():
        current = recap.term_of(datetime.now(timezone.utc))
        term = request.args.get('term') or current
        if not recap.bounds(term):
            abort(404)
        with database() as db:
            data = recap.build(db, g.user['id'], term)
            terms = recap.terms(db, g.user['id'])
        return render_template('recap.html', recap=data, terms=terms, current=current, label=recap.label,
                               days_left=recap.days_left(term) if term == current else None)

    @app.get('/tasks/<int:task_id>')
    @login_required
    def detail(task_id):
        with database() as db:
            task = db.execute('''SELECT t.*,u.name owner_name,a.name assignee_name FROM tasks t
                JOIN users u ON u.id=t.owner_id LEFT JOIN users a ON a.id=t.assignee_id WHERE t.id=?''', (task_id,)).fetchone()
            if not task:
                abort(404)
            events = db.execute('SELECT e.*,u.name FROM events e JOIN users u ON u.id=e.user_id WHERE task_id=? ORDER BY e.id', (task_id,)).fetchall()
            award = db.execute('SELECT * FROM honors WHERE task_id=?', (task_id,)).fetchone()
            tags = discover.tags_by_task(db, [task_id])[task_id]
            claps = db.execute('SELECT COUNT(*) n, COALESCE(SUM(user_id=?),0) mine FROM claps WHERE task_id=?',
                               (g.user['id'], task_id)).fetchone()
            earned = discover.earned_keys(db, g.user['id'])
            # 新人第一单：认领人还没有任何勋章时，提醒发布者多给一点鼓励
            first_timer = bool(task['assignee_id']) and task['status'] in ('active', 'review') and not db.execute(
                'SELECT 1 FROM honors WHERE user_id=?', (task['assignee_id'],)).fetchone()
            debut = bool(award) and not db.execute(
                'SELECT 1 FROM honors WHERE user_id=? AND (awarded_at<? OR (awarded_at=? AND task_id<?))',
                (award['user_id'], award['awarded_at'], award['awarded_at'], task_id)).fetchone()
            why = []
            if task['status'] == 'open' and task['owner_id'] != g.user['id']:
                why = next((pick['reasons'] for pick in discover.recommend(db, g.user['id'], limit=100)
                            if pick['task']['id'] == task_id), [])
        feedback = session.pop('task_feedback', None)
        if feedback and feedback['task_id'] != task_id:
            feedback = None
        return render_template('detail.html', task=task, events=events, award=award, feedback=feedback, tags=tags,
                               claps=claps, new_kind=medal_key(task) not in earned, why=why[:3], first_timer=first_timer,
                               debut=debut)

    @app.post('/tasks/<int:task_id>/clap')
    @login_required
    def clap_task(task_id):
        wants_json = request.accept_mimetypes.best == 'application/json'
        try:
            count = clap(app.config['DATABASE'], task_id, g.user['id'])
        except InvalidAction as error:
            if wants_json:
                return jsonify(error=str(error)), 400
            flash(str(error), 'error')
            return back()
        return jsonify(claps=count) if wants_json else back()

    @app.post('/tasks/<int:task_id>/dismiss')
    @login_required
    def dismiss_task(task_id):
        wants_json = request.accept_mimetypes.best == 'application/json'
        try:
            dismiss(app.config['DATABASE'], task_id, g.user['id'])
        except InvalidAction as error:
            if wants_json:
                return jsonify(error=str(error)), 400
            flash(str(error), 'error')
        return jsonify(ok=True) if wants_json else back()

    @app.post('/tasks/<int:task_id>/<action>')
    @login_required
    def task_action(task_id, action):
        try:
            act(app.config['DATABASE'], task_id, g.user['id'], action, request.form.get('body', ''))
            if action in ('claim', 'submit', 'accept', 'return'):
                session['task_feedback'] = {'task_id': task_id, 'action': action}
            flash('验收通过，勋章已授予认领人。' if action == 'accept' else '操作已保存。', 'success')
        except InvalidAction as error:
            flash(str(error), 'error')
        return redirect(url_for('detail', task_id=task_id))

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def error_page(error):
        return render_template('error.html', error=error), error.code

    if app.config.get('TEAM_ACCOUNTS_DATABASE') or os.environ.get('TEAM_ACCOUNTS_DATABASE'):
        from bounty.team_auth import install
        install(app, app.config.get('TEAM_ACCOUNTS_DATABASE') or os.environ['TEAM_ACCOUNTS_DATABASE'])
    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=int(os.environ.get('PORT', '5080')), debug=False)
