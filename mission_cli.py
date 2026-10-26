"""Mission CLI: standard-library HTTP client, also usable by agents through --json."""
import argparse
import getpass
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

VERSION = '0.1.0'


class CLIError(Exception):
    def __init__(self, message, code='client_error', exit_code=2, status=None):
        super().__init__(message)
        self.code, self.exit_code, self.status = code, exit_code, status


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CLIError(message, 'usage_error')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def server_url(raw):
    parsed = urllib.parse.urlsplit(raw)
    local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise CLIError('请提供站点根地址，例如 https://mission.example.test。')
    if parsed.scheme != 'https' and not (local and parsed.scheme == 'http'):
        raise CLIError('服务器必须使用 HTTPS；本机演示可用 http://127.0.0.1:5080。')
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc.lower(), '', '', ''))


def config_path(explicit):
    if explicit or os.environ.get('MISSION_CONFIG'):
        return Path(explicit or os.environ['MISSION_CONFIG']).expanduser()
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'mission' / 'config.json'


def read_config(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('tokens', {}), dict):
            raise ValueError()
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in data.get('tokens', {}).items()):
            raise ValueError()
        if 'server' in data and not isinstance(data['server'], str):
            raise ValueError()
        return data
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        raise CLIError('无法读取命令行配置，请检查 --config 指定的文件。', 'config_error')


def save_config(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.mission-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            os.chmod(temporary, 0o600)
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Client:
    def __init__(self, server, token, timeout=20):
        self.server, self.token, self.timeout = server, token, timeout
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, method, path, data=None):
        if not self.token:
            raise CLIError('尚未登录，请运行 mission login，或设置 MISSION_TOKEN。', 'unauthorized', 3)
        headers = {'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json',
                   'User-Agent': 'mission-cli/' + VERSION}
        body = None
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        for attempt in range(2 if method == 'GET' else 1):
            try:
                req = urllib.request.Request(self.server + '/api/v1' + path, data=body, headers=headers, method=method)
                try:
                    response = self.opener.open(req, timeout=self.timeout)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    status = response.code
                    raw = response.read()
                if method == 'GET' and status in (502, 503, 504) and attempt == 0:
                    time.sleep(.25)
                    continue
                try:
                    result = json.loads(raw)
                except (ValueError, UnicodeError):
                    result = None
                if status >= 300 or not isinstance(result, dict) or result.get('ok') is not True or 'data' not in result:
                    error = result.get('error', {}) if isinstance(result, dict) else {}
                    if not isinstance(error, dict):
                        error = {}
                    message = error.get('message') or f'服务器返回 HTTP {status}；请检查服务器地址和 API 版本。'
                    code = error.get('code') or 'protocol_error'
                    exit_code = 3 if status in (401, 403) else 5 if status >= 500 or status < 400 else 4
                    if method != 'GET' and (status >= 500 or not isinstance(result, dict) and status < 300):
                        message += ' 写入结果未知，请先查询任务；本命令没有自动重发。'
                        code, exit_code = 'outcome_unknown', 5
                    raise CLIError(message, code, exit_code, status)
                return result
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as error:
                if method == 'GET' and attempt == 0:
                    time.sleep(.25)
                    continue
                if method == 'GET':
                    raise CLIError('无法读取服务器，请检查网络后重试。', 'network_error', 5) from error
                raise CLIError('写入结果未知，请先查询任务再决定是否重试；本命令没有自动重发。',
                               'outcome_unknown', 5) from error


def read_file(name):
    try:
        return sys.stdin.read() if name == '-' else Path(name).read_text(encoding='utf-8')
    except (OSError, UnicodeError) as error:
        raise CLIError('无法读取输入文件，请使用 UTF-8 文本。', 'input_error') from error


def json_input(name):
    if not name:
        return {}
    try:
        data = json.loads(read_file(name))
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except ValueError as error:
        raise CLIError('--input 需要一个 JSON 对象。', 'input_error') from error


def body_flags(parser):
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--body', help='说明、成果链接、评论或原因')
    group.add_argument('--body-file', help='从 UTF-8 文件读取正文；- 表示标准输入')


def body_value(args):
    filename = getattr(args, 'body_file', None)
    return read_file(filename) if filename else getattr(args, 'body', None) or ''


def build_parser():
    common = Parser(add_help=False)
    common.add_argument('--server', help='站点根地址，也可设置 MISSION_SERVER')
    common.add_argument('--config', help='本地配置文件；默认 ~/.config/mission/config.json')
    common.add_argument('--json', action='store_true', help='仅向 stdout 输出一个 JSON 对象')
    common.add_argument('--timeout', type=float, default=20, help='单次请求超时秒数（默认 20）')
    parser = Parser(prog='mission', parents=[common], description='結 YUI 团队任务命令行')
    parser.add_argument('--version', action='version', version='mission ' + VERSION)
    root = parser.add_subparsers(dest='command', required=True)
    login = root.add_parser('login', help='网页生成独立命令行会话后登录')
    login.add_argument('--token-stdin', action='store_true', help='从标准输入读取访问凭据，避免出现在命令参数中')
    login.add_argument('--no-browser', action='store_true', help='只显示授权页地址，不自动打开浏览器')
    for name, help_text in [('logout', '撤销当前命令行会话'), ('me', '当前身份和成长信息'),
                            ('mine', '按轮到谁处理分组列出我的任务'), ('members', '列出已进入 Mission 的成员编号'),
                            ('tags', '列出团队标签'), ('schema', '输出供 AI 使用的命令和输入说明，无需登录')]:
        root.add_parser(name, help=help_text)
    task = root.add_parser('task', help='查询和处理任务').add_subparsers(dest='operation', required=True)
    listing = task.add_parser('list', help='分页查询任务')
    for name in ('status', 'kind', 'project', 'tag', 'q'):
        listing.add_argument('--' + name)
    for name in ('owner-id', 'assignee-id', 'parent-id', 'limit', 'offset'):
        listing.add_argument('--' + name, type=int)
    for name in ('show', 'events'):
        sub = task.add_parser(name, help='任务详情' if name == 'show' else '分页读取操作和交付历史')
        sub.add_argument('id', type=int)
        if name == 'events':
            sub.add_argument('--after', type=int, default=0)
            sub.add_argument('--limit', type=int, default=50)
    create = task.add_parser('create', help='发布小任务或大任务')
    create.add_argument('--input', help='JSON 文件；- 表示从标准输入读取；显式参数覆盖文件字段')
    for name in ('title', 'description', 'requirements', 'project', 'deadline'):
        create.add_argument('--' + name)
    create.add_argument('--tag', dest='tags', action='append', help='可重复传入')
    create.add_argument('--kind', choices=['solo', 'team'])
    create.add_argument('--importance', choices=['light', 'standard', 'major'])
    create.add_argument('--urgency', choices=['normal', 'urgent'])
    create.add_argument('--assignee', type=int)
    create.add_argument('--member', dest='members', type=int, action='append')
    create.add_argument('--team-size', type=int)
    create.add_argument('--join-self', action='store_true', default=None)
    for name in ('claim', 'join', 'leave', 'submit', 'accept', 'return', 'comment', 'clap'):
        sub = task.add_parser(name)
        sub.add_argument('id', type=int)
        if name in ('submit', 'accept', 'return', 'comment'):
            body_flags(sub)
        if name == 'accept':
            sub.add_argument('--credit', type=int, action='append', help='大任务获奖成员编号，可重复；不传则按原规则发奖')
    split = task.add_parser('split', help='从大任务拆出分工')
    split.add_argument('id', type=int)
    for name in ('title', 'tag', 'kind'):
        split.add_argument('--' + name, required=True, help='kind 示例 standard-normal' if name == 'kind' else None)
    split.add_argument('--deadline')
    body_flags(split)
    extension = task.add_parser('extend', help='申请、审批或直接延期').add_subparsers(dest='move', required=True)
    for name in ('ask', 'approve', 'reject', 'push'):
        sub = extension.add_parser(name)
        sub.add_argument('id', type=int)
        if name in ('ask', 'push'):
            sub.add_argument('--deadline', required=True)
        body_flags(sub)
    return common, parser


def schema(parser):
    commands = []

    def visit(node, path):
        children = next((a for a in node._actions if isinstance(a, argparse._SubParsersAction)), None)
        if children:
            for name, child in children.choices.items():
                visit(child, path + [name])
        else:
            commands.append(dict(command='mission ' + ' '.join(path), arguments=[dict(
                name=a.dest, flags=a.option_strings, required=a.required,
                choices=a.choices, repeat=isinstance(a, argparse._AppendAction), help=a.help)
                for a in node._actions if a.dest != 'help']))

    visit(parser, [])
    return dict(version=1, commands=commands, global_flags=['--server', '--config', '--json', '--timeout'],
                deadline='ISO 8601 with explicit timezone, e.g. 2027-01-20T18:00:00+08:00',
                create_required=['title', 'description', 'requirements', 'tags', 'deadline'],
                create_defaults=dict(kind='solo', importance='standard', urgency='normal'),
                output=dict(success={'ok': True, 'data': 'object or array'},
                            failure={'ok': False, 'error': {'code': 'string', 'message': 'string'}}),
                exit_codes={'0': 'success', '2': 'usage/config/input', '3': 'login/access',
                            '4': 'rejected request', '5': 'network/server or unknown write outcome'},
                writes='Never automatically retried. Query tasks/events before deciding to repeat an uncertain write.')


def perform(args, global_args, parser):
    if args.command == 'schema':
        return dict(ok=True, data=schema(parser))
    path = config_path(global_args.config)
    config = read_config(path)
    raw_server = global_args.server or os.environ.get('MISSION_SERVER') or config.get('server')
    if not raw_server:
        raise CLIError('请先用 --server 指定 Mission 地址。', 'config_error')
    server = server_url(raw_server)
    if global_args.timeout <= 0:
        raise CLIError('--timeout 必须大于零。')
    token = os.environ.get('MISSION_TOKEN') or config.get('tokens', {}).get(server, '')
    if args.command == 'login':
        if args.token_stdin:
            token = sys.stdin.readline().strip()
        else:
            if not sys.stdin.isatty():
                raise CLIError('非交互登录请用 --token-stdin；AI 调用可设置 MISSION_TOKEN。')
            print('在网页登录后生成命令行访问凭据：' + server + '/cli', file=sys.stderr)
            if not args.no_browser:
                webbrowser.open(server + '/cli')
            token = getpass.getpass('访问凭据（不显示输入）：').strip()
        result = Client(server, token, global_args.timeout).call('GET', '/me')
        config.setdefault('tokens', {})[server] = token
        config['server'] = server
        save_config(path, config)
        return result
    client = Client(server, token, global_args.timeout)
    if args.command == 'logout':
        try:
            result = client.call('POST', '/logout', {})
        except CLIError as error:
            if error.status != 401:
                raise
            result = dict(ok=True, data=dict(logged_out=True))
        config.get('tokens', {}).pop(server, None)
        save_config(path, config)
        return result
    if args.command in ('me', 'mine', 'members', 'tags'):
        return client.call('GET', '/' + args.command)
    operation = args.operation
    if operation == 'list':
        fields = ('status', 'kind', 'project', 'tag', 'q', 'owner_id', 'assignee_id', 'parent_id', 'limit', 'offset')
        query = urllib.parse.urlencode({k: getattr(args, k) for k in fields if getattr(args, k) is not None})
        return client.call('GET', '/tasks?' + query)
    if operation == 'create':
        data = json_input(args.input)
        fields = ('title', 'description', 'requirements', 'tags', 'project', 'deadline', 'kind', 'importance',
                  'urgency', 'assignee', 'members', 'team_size', 'join_self')
        data.update({k: getattr(args, k) for k in fields if getattr(args, k) is not None})
        for key, value in dict(kind='solo', importance='standard', urgency='normal').items():
            data.setdefault(key, value)
        return client.call('POST', '/tasks', data)
    path = '/tasks/' + str(args.id)
    if operation == 'show':
        return client.call('GET', path)
    if operation == 'events':
        return client.call('GET', path + '/events?' + urllib.parse.urlencode(dict(after=args.after, limit=args.limit)))
    if operation == 'extend':
        data = dict(body=body_value(args))
        if hasattr(args, 'deadline'):
            data['deadline'] = args.deadline
        return client.call('POST', path + '/extensions/' + args.move, data)
    if operation == 'split':
        return client.call('POST', path + '/pieces', dict(title=args.title, tag=args.tag, kind=args.kind,
                           note=body_value(args), deadline=args.deadline or ''))
    if operation == 'clap':
        return client.call('POST', path + '/clap', {})
    data = dict(action=operation, body=body_value(args))
    if getattr(args, 'credit', None) is not None:
        data['credit'] = args.credit
    return client.call('POST', path + '/actions', data)


def display(result, machine):
    if machine or not result['ok']:
        print(json.dumps(result, ensure_ascii=False))
        return
    data = result['data']
    if isinstance(data, dict) and 'title' in data and 'id' in data:
        print(f"#{data['id']}  {data['title']}  [{data['status']}]")
        print('截止：' + data['deadline'])
        print('发布：' + data['owner_name'] + '  认领：' + (data.get('assignee_name') or '—'))
        print(data['description'])
        print('交付要求：' + data['requirements'])
    elif isinstance(data, dict) and 'items' in data and all('title' in item for item in data['items']):
        for item in data['items']:
            print(f"#{item['id']}  [{item['status']}]  {item['title']}")
        if data.get('next_offset') is not None:
            print('下一页：--offset ' + str(data['next_offset']))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    machine = '--json' in argv
    try:
        common, parser = build_parser()
        global_args, remaining = common.parse_known_args(argv)
        args = parser.parse_args(remaining)
        result = perform(args, global_args, parser)
        display(result, machine)
        return 0
    except CLIError as error:
        result = dict(ok=False, error=dict(code=error.code, message=str(error)))
        if error.status is not None:
            result['error']['status'] = error.status
        if machine:
            display(result, True)
        else:
            print(str(error), file=sys.stderr)
        return error.exit_code
    except (OSError, ValueError) as error:
        result = dict(ok=False, error=dict(code='client_error', message='无法完成本地操作，请检查输入和配置文件权限。'))
        if machine:
            display(result, True)
        else:
            print(result['error']['message'], file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
