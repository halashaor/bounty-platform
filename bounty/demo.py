"""Generate an independent, editable local demo database. Never reads workspace users."""
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash
from .db import connect, initialize
from .service import act, clap, create_task, set_interests
from . import bigs, blocks

DEMO_USERS = ('发布者', '认领人', '其他成员', '陈默', '王瑶', '周然', '林夕')
DEMO_PASSWORD = 'demo12345'
U = {name: index + 1 for index, name in enumerate(DEMO_USERS)}

# (标签, 项目, 标题, 一句话说明, 分量, 紧急, 发布者, 走到哪一步, 由谁来做)
TASKS = (
    ('数据', '校赛 2026', '给模拟赛造数据', '为周六模拟赛的 E 题造 30 组数据，要含极限规模和边界情况。', 'standard', 'urgent', '陈默', 'open', None),
    ('讲解', '新人培养', '写一篇周赛题解', '把上周周赛 C、D 两题的思路和代码整理成一篇题解，发到组里。', 'light', 'normal', '王瑶', 'open', None),
    ('论文 PyTorch', 'GNN 研究', '复现 GraphSAGE 的 baseline', '在 ogbn-arxiv 上跑出论文里的精度，记录超参和每轮耗时。', 'major', 'normal', '其他成员', 'open', None),
    ('代码', '实验室基建', '配置 GPU 排队脚本', '四张卡总被抢，写个排队脚本，按提交顺序分配显卡。', 'major', 'urgent', '周然', 'open', None),
    ('数据 题库', '题库', '清洗竞赛题目标签', '给 1200 道题统一知识点标签，去掉重复和错标的。', 'light', 'urgent', '王瑶', 'open', None),
    ('实验 PyTorch', 'GNN 研究', '跑一组消融实验', '去掉注意力层和残差各跑三次，结果填进对比表。', 'standard', 'normal', '其他成员', 'open', None),
    ('讲解 图论', '新人培养', '给新人讲一次图论入门', '一小时，讲清 BFS、最短路和并查集，带两道例题。', 'standard', 'normal', '王瑶', 'open', None),
    ('讲解 题库', '新人培养', '整理 DP 专题题单', '挑 20 道 DP 题，按难度排好，每题写一句提示。', 'light', 'normal', '陈默', 'open', None),
    ('代码', '实验室基建', '修复评测机的超时统计', '多线程评测时超时被重复计数，查清原因并修好。', 'standard', 'normal', '周然', 'open', None),
    ('实验 PyTorch', 'GNN 研究', '对比三种 GNN 的训练速度', '同一张卡上比较 GCN、GAT、SAGE 每轮耗时和显存。', 'major', 'normal', '陈默', 'open', None),
    ('论文', 'GNN 研究', '读并分享一篇 ICLR 论文', '挑一篇图学习方向的论文，组会上讲 15 分钟。', 'standard', 'normal', '其他成员', 'open', None),
    ('杂务', '校赛 2026', '给校赛海报写一句口号', '十个字以内，让新生看了想来报名。', 'light', 'normal', '林夕', 'open', None),
    ('数据', '校赛 2026', '整理历年校赛题目归档', '把五年的校赛题面、数据和题解按年份放进同一个目录。', 'standard', 'normal', '发布者', 'open', None),
    ('代码 题库', '题库', '给题库加按标签检索', '在题库页面加一个标签筛选，支持多选。', 'standard', 'urgent', '发布者', 'open', None),
    ('杂务', '校赛 2026', '预订周六模拟赛的机房', '借两间机房，确认网络和投影能用。', 'light', 'urgent', '发布者', 'open', None),
    ('实验 PyTorch', 'GNN 研究', '调一版学习率预热', '试三种预热步数，画出前 2000 步的 loss 曲线。', 'standard', 'normal', '发布者', 'claim', '认领人'),
    ('讲解', '新人培养', '录一节线段树讲解视频', '二十分钟以内，讲清区间修改和懒标记。', 'major', 'normal', '王瑶', 'claim', '陈默'),
    ('代码', '新人培养', '给比赛代码模板加单元测试', '为快读、取模和并查集模板各写五个测试。', 'standard', 'normal', '发布者', 'return', '认领人'),
    ('数据', 'GNN 研究', '标注 200 条错误样例', '把模型判错的 200 条样例按错误类型分好类。', 'light', 'normal', '发布者', 'submit', '认领人'),
    ('论文', 'GNN 研究', '写一页 Transformer 速查表', '公式、复杂度和常见变体压缩成一页。', 'standard', 'urgent', '其他成员', 'submit', '林夕'),
    ('讲解', '新人培养', '写周会纪要模板', '给周会做一个纪要模板，含决议和待办两栏。', 'light', 'normal', '王瑶', 'accept', '认领人'),
    ('数据', '校赛 2026', '清洗去年比赛的提交记录', '去掉重复提交和测试账号，导出成一张表。', 'standard', 'normal', '陈默', 'accept', '认领人'),
    ('代码', '实验室基建', '修好评测机的内存统计', '内存峰值总是偏小，查清采样方式并修好。', 'major', 'urgent', '周然', 'accept', '陈默'),
    ('实验 论文', 'GNN 研究', '复现 GCN 的 baseline', '在 Cora 上跑出论文精度，写清随机种子和超参。', 'major', 'normal', '其他成员', 'accept', '周然'),
    ('讲解', '新人培养', '整理上周周赛的错题', '把大家错得最多的三道题整理成一页，写清卡在哪一步。', 'light', 'normal', '王瑶', 'accept', '认领人'),
    ('数据 题库', '题库', '补全 50 道题的样例解释', '给样例没有解释的 50 道题补上一两句说明。', 'light', 'normal', '陈默', 'accept', '认领人'),
    ('杂务', '校赛 2026', '连夜改好报名表', '报名表的学号校验写错了，今晚之前改好重新发。', 'light', 'urgent', '发布者', 'accept', '认领人'),
)
# 验收时写的夸奖：会刻在勋章背面
PRAISE = {'整理上周周赛的错题': '写得很清楚', '补全 50 道题的样例解释': '靠谱，一次就过', '连夜改好报名表': '救了急',
          '清洗去年比赛的提交记录': '超出预期'}
# 已经拆开看过的勋章（其余的留在信箱里，登录后能看到颁奖）
SEEN = ('整理上周周赛的错题', '补全 50 道题的样例解释', '连夜改好报名表')
PIECES_SEEN = ('出一道签到题', '带新人配好比赛环境', '讲一次 STL 入门')
INTERESTS = {'认领人': '图论 PyTorch', '王瑶': '数据 论文'}
# 团队的标签表（团队成员整理过的样子）：顺序就是方向条和发布页上的顺序
TEAM_TAGS = (('数据', '造数据、清洗、标注、整理题目'), ('讲解', '讲题、写题解、带新人'), ('实验', '跑实验、调参、消融'),
             ('论文', '读论文、复现、组会分享'), ('代码', '写工具、修评测机、加测试'), ('题库', '题目整理、知识点标签、检索'),
             ('图论', '图算法的讲题和实验'), ('PyTorch', '模型训练和 GPU 上的活'), ('杂务', '订机房、做海报、改表格'))
ADMIN = '发布者'
# 发布了一周还没人接的冷门任务（其中一个后来被认领人接下并完成，带冷门加成）
COLD = {'整理 DP 专题题单': 8, '整理历年校赛题目归档': 6, '补全 50 道题的样例解释': 9}
# 挂在名牌上的积木作品（只用他们的勋章已经解锁的零件和颜色）
BUILDS = {
    '陈默': ('评测机', 'paper', [['quarter', 'red', 0, 12, 0], ['sq-2', 'ink', 10, 2, 0], ['dot-s', 'ink', 4, 4, 0], ['dot-s', 'ink', 5, 5, 0], ['bar-3', 'ink', 6, 9, 0],
                                ['bar-3', 'red', 9, 11, 1], ['dot-s', 'ink', 13, 13, 0], ['medal-major-urgent', 'white', 12, 6, 0]]),
    '周然': ('夜里的实验室', 'ink', [['quarter', 'blue', 12, 12, 1], ['dot-s', 'white', 2, 2, 0], ['dot-s', 'white', 6, 4, 0], ['dot-s', 'white', 10, 1, 0],
                                   ['sq-2', 'white', 12, 2, 0], ['bar-3', 'white', 2, 13, 0], ['sq-2', 'blue', 5, 10, 0], ['medal-major-normal', 'white', 1, 7, 0]]),
}
# 大任务：(标题, 项目, 目标, 牵头人, 几天后到目标日期, 加入的人, 上面已有的任务里归它的, 新加的分工, 收尾的话)
# 新加的分工：(标题, 标签, 勋章, 走到哪一步, 由谁来做)，都由牵头人加
BIGS = (
    ('办好周六模拟赛', '校赛 2026', '周六下午两点准时开赛：题目、数据、机房和赛时答疑全部就位，赛后当天发题解。', '发布者', 3,
     ('陈默', '周然'), ('给模拟赛造数据', '预订周六模拟赛的机房'),
     (('出一道签到题', '讲解', 'light-normal', 'accept', '周然'),
      ('给 E 题写标程和题解', '讲解', 'standard-normal', 'claim', '认领人'),
      ('赛时在群里答疑', '杂务', 'light-normal', 'open', None)), None),
    ('GNN 三个基线复现', 'GNN 研究', 'GCN、GAT、GraphSAGE 在同一套代码里跑通，精度对齐论文，超参和耗时整理成一张对比表。', '其他成员', 20,
     ('陈默',), ('复现 GCN 的 baseline', '复现 GraphSAGE 的 baseline', '对比三种 GNN 的训练速度'),
     (('复现 GAT 的 baseline', '论文', 'major-normal', 'submit', '林夕'),
      ('把三份结果整理成对比表', '实验', 'light-normal', 'open', None)), None),
    ('新人训练营 · 第一周', '新人培养', '带新人走完第一周：配好环境、上完两节课、做完第一次周赛，每个人都知道下一步练什么。', '王瑶', 10,
     (), ('写周会纪要模板', '整理上周周赛的错题'),
     (('带新人配好比赛环境', '杂务', 'standard-normal', 'accept', '林夕'),
      ('讲一次 STL 入门', '讲解', 'standard-normal', 'accept', '陈默')), '第一周顺利办完，新人都留下来了。谢谢大家！'),
)
BIG_TALK = {'办好周六模拟赛': (('陈默', 'E 题的数据我来造，周四前给。'), ('发布者', '机房还没人订，谁顺路去一趟？'))}
CLAPS = {'写周会纪要模板': ('王瑶', '陈默'), '清洗去年比赛的提交记录': ('陈默', '周然', '林夕'),
         '修好评测机的内存统计': ('认领人', '王瑶', '周然', '林夕'), '复现 GCN 的 baseline': ('陈默', '王瑶')}


def seed_demo(path):
    initialize(path)
    with connect(path, write=True) as db:
        if db.execute('SELECT COUNT(*) FROM users').fetchone()[0] or db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]:
            raise ValueError('演示数据只允许导入空数据库，请使用新的 --data-dir。')
        db.executemany('INSERT INTO users(name,password) VALUES (?,?)',
                       [(name, generate_password_hash(DEMO_PASSWORD)) for name in DEMO_USERS])
        db.execute('DELETE FROM org_tags')
        db.executemany("INSERT INTO org_tags (name,note,position,created_by,created_at) VALUES (?,?,?,?,'2026-01-01T00:00:00+00:00')",
                       [(name, note, i, U[ADMIN]) for i, (name, note) in enumerate(TEAM_TAGS, 1)])
    soon = datetime.now(timezone.utc)
    for index, (tags, project, title, description, importance, urgency, owner, stage, worker) in enumerate(TASKS):
        # 截止时间错开：加急的两三天内，其余一到三周，卡片上的倒计时才有轻重
        days = 2 + index % 2 if urgency == 'urgent' else 6 + (index * 5) % 16
        task_id = create_task(path, U[owner], dict(
            title=title, tags=tags, project=project, description=description,
            requirements='提交成果链接和一段说明；发布者对照说明验收，需要修改时写明原因。',
            importance=importance, urgency=urgency, deadline=(soon + timedelta(days=days, hours=10)).isoformat(timespec='seconds'),
        ))
        if title in COLD:
            with connect(path, write=True) as db:
                db.execute('UPDATE tasks SET created_at=? WHERE id=?',
                           ((soon - timedelta(days=COLD[title])).isoformat(timespec='seconds'), task_id))
        if stage == 'open':
            continue
        act(path, task_id, U[worker], 'claim')
        if stage == 'return':
            act(path, task_id, U[worker], 'submit', '第一版放在共享盘「模板/tests」。')
            act(path, task_id, U[owner], 'return', '并查集的测试少了路径压缩后的情况，请补上再提交。')
        if stage in ('submit', 'accept'):
            act(path, task_id, U[worker], 'submit', '成果放在共享盘，说明写在 README 里。')
        if stage == 'accept':
            act(path, task_id, U[owner], 'accept', PRAISE.get(title, '很清楚，已经在用了。'))
            for fan in CLAPS.get(title, ()):
                clap(path, task_id, U[fan])
    for title, project, goal, lead, days, members, linked, pieces, closing in BIGS:
        stamp = (soon + timedelta(days=days, hours=10)).isoformat(timespec='seconds')
        rows = [dict(title=row[0], tag=row[1], kind=row[2]) for row in pieces]
        big_id = bigs.create(path, U[lead], dict(title=title, goal=goal, project=project, deadline=stamp), rows)
        with connect(path, write=True) as db:
            db.executemany('UPDATE tasks SET big_id=? WHERE title=?', [(big_id, name) for name in linked])
            # 已有的任务归进来时，接过它们的人也算加入
            db.execute('''INSERT OR IGNORE INTO big_members (big_id,user_id,joined_at)
                SELECT big_id,assignee_id,created_at FROM tasks WHERE big_id=? AND assignee_id IS NOT NULL''', (big_id,))
            ids = {row['title']: row['id'] for row in db.execute('SELECT id,title FROM tasks WHERE big_id=?', (big_id,))}
        for name in members:
            bigs.join(path, big_id, U[name])
        for name, body in BIG_TALK.get(title, ()):
            bigs.comment(path, big_id, U[name], body)
        for piece_title, _, _, stage, worker in pieces:
            if stage == 'open':
                continue
            act(path, ids[piece_title], U[worker], 'claim')
            if stage in ('submit', 'accept'):
                act(path, ids[piece_title], U[worker], 'submit', '做好了，放在共享盘，说明写在 README 里。')
            if stage == 'accept':
                act(path, ids[piece_title], U[lead], 'accept', '很清楚，已经在用了。')
        if closing:
            bigs.close(path, big_id, U[lead], closing)
    with connect(path, write=True) as db:
        db.executemany('UPDATE honors SET seen_at=awarded_at WHERE task_id=(SELECT id FROM tasks WHERE title=?)',
                       [(title,) for title in SEEN + PIECES_SEEN])
        # 收尾的合力纪念：只有「认领人」的还没拆，登录后能看到
        db.execute('UPDATE big_credits SET seen_at=awarded_at WHERE user_id<>?', (U['认领人'],))
    for name, tags in INTERESTS.items():
        set_interests(path, U[name], tags)
    for name, (title, bg, parts) in BUILDS.items():
        blocks.show(path, U[name], blocks.save(path, U[name], None, title, bg, parts))
    with connect(path) as db:
        return db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
