"""提醒：等你动手的事。

「我的」上的数字、右上角的提醒卡和浏览器标签上的 (N) 都从这里来，只算要你动手的：
有人提到你（手帳、寄合点名）、等你验收、等你批延期、被退回要改。
手上正在做的任务不算，它们在「我的」里照常列着；算进去的话数字一直不消，看久了就没人理了。
"""
from flask import Blueprint, abort, current_app, g, jsonify, url_for

from . import notes, talk
from .db import connect

# 谁来验收：任务的发布者；分工由所属大任务的发布者验收
CHECKER = "(t.owner_id=:me OR t.parent_id IN (SELECT id FROM tasks WHERE owner_id=:me AND kind='team'{}))"
MEMBER = 't.id IN (SELECT task_id FROM task_members WHERE user_id=:me)'
LATEST = "(SELECT MAX(id) FROM events WHERE task_id=t.id AND kind IN ('claim','submit','return','accept'))"

TASKS = f'''SELECT a.*,u.name who FROM (
    SELECT 'review' kind,t.id task_id,t.title,e.id ref,e.user_id who_id,e.created_at at,'' body
      FROM tasks t JOIN events e ON e.id={LATEST}
     WHERE t.status='review' AND e.kind='submit' AND {CHECKER.format(" AND status<>'done'")}
    UNION ALL
    SELECT 'extend',t.id,t.title,x.id,x.user_id,x.created_at,x.new_deadline
      FROM tasks t JOIN extensions x ON x.task_id=t.id
     WHERE t.status='active' AND x.status='pending' AND x.user_id<>:me AND {CHECKER.format('')}
       AND (t.parent_id IS NULL OR NOT {MEMBER})
    UNION ALL
    SELECT 'return',t.id,t.title,e.id,e.user_id,e.created_at,e.body
      FROM tasks t JOIN events e ON e.id={LATEST}
     WHERE t.status='active' AND e.kind='return' AND {MEMBER}
) a JOIN users u ON u.id=a.who_id ORDER BY a.at DESC'''


def task_items(db, me):
    return [dict(row) for row in db.execute(TASKS, dict(me=me))]


def counts(db, me):
    tasks = len(task_items(db, me))
    mentions = notes.unseen_count(db, me) + talk.unread_mention_count(db, me)
    return dict(tasks=tasks, mentions=mentions, total=tasks + mentions)


def _line(text, limit=90):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit] + '…'


def items(db, me):
    """Everything waiting on this person, newest first. A key changes only when there is something new
    (another submission, request, return or mention), so a card put away on one device stays away."""
    md = current_app.jinja_env.filters['md']
    found = []
    for note in notes.unseen(db, me):
        found.append(dict(key=f'note:{note["id"]}', kind='note', who=note['user_name'], who_id=note['user_id'],
                          what='在手帳里提到你', head=_line(note['head']), sub=note['task_title'] or '', at=note['created_at'],
                          url=url_for('notes.go', note_id=note['id']), go='去看看',
                          ack=url_for('notes.seen', note_id=note['id'])))
    topics = set()
    for post in talk.mentions_of(db, me, limit=100, unread_only=True):
        if post['topic_id'] in topics:
            continue
        topics.add(post['topic_id'])
        found.append(dict(key=f'talk:{post["id"]}', kind='talk', who=post['user_name'], who_id=post['user_id'],
                          what='在寄合里点名你', head=_line(post['preview']), sub=post['title'], at=post['created_at'],
                          url=url_for('talk.thread', topic_id=post['topic_id']) + f'#p{post["id"]}', go='去看看',
                          ack=url_for('alerts.talk_read', post_id=post['id'])))
    for task in task_items(db, me):
        if task['kind'] == 'extend':
            what, go = f'想把截止改到 {md(task["body"])}，等你点头', '去处理'
        else:
            what, go = {'review': ('交上来了，等你验收', '去验收'), 'return': ('退回了，要你改一下', '去看看')}[task['kind']]
        found.append(dict(key=f'{task["kind"]}:{task["ref"]}', kind=task['kind'], who=task['who'], who_id=task['who_id'],
                          what=what, head=_line(task['title']), sub=_line(task['body'], 60) if task['kind'] == 'return' else '',
                          at=task['at'], url=url_for('detail', task_id=task['task_id']), go=go, ack=None))
    found.sort(key=lambda item: item['at'], reverse=True)
    return found


def install(app):
    path = app.config['DATABASE']
    page = Blueprint('alerts', __name__, url_prefix='/alerts')

    @app.context_processor
    def alert_counts():
        if not g.get('user'):
            return dict(alerts=dict(tasks=0, mentions=0, total=0))
        with connect(path) as db:
            return dict(alerts=counts(db, g.user['id']))

    @page.before_request
    def signed_in():
        if not g.get('user'):
            abort(401)

    @page.get('')
    def listing():
        with connect(path) as db:
            found = items(db, g.user['id'])
            total = counts(db, g.user['id'])['total']
        return jsonify(ok=True, count=total, items=found)

    @page.post('/talk/<int:post_id>/read')
    def talk_read(post_id):
        """「知道了」：这条点名算读过（读到这条为止，后面的新帖照样提醒）。"""
        with connect(path) as db:
            row = db.execute('''SELECT p.topic_id FROM posts p JOIN post_mentions m ON m.post_id=p.id
                WHERE p.id=? AND m.user_id=?''', (post_id, g.user['id'])).fetchone()
        if not row:
            abort(404)
        talk.mark_read(path, g.user['id'], row['topic_id'], post_id)
        return jsonify(ok=True)

    app.register_blueprint(page)
