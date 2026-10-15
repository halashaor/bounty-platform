"""Optional Chromium smoke check; isolated users/database and a temporary loopback server."""
import base64,json,subprocess,tempfile,time,urllib.request,threading,sys,os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import websocket
sys.path.insert(0,str(Path.cwd()))
from app import create_app
from bounty.db import connect
from bounty.service import create_task
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server
binary=os.environ.get('BOUNTY_BROWSER')
if not binary:
 candidates=sorted((Path.home()/'.cache/ms-playwright').glob('chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell'))
 if not candidates: raise SystemExit('Set BOUNTY_BROWSER to a Chromium/headless-shell executable.')
 binary=str(candidates[-1])
Path('previews').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='bounty-motion-') as root:
 app=create_app({'DATABASE':root+'/db.sqlite3','SECRET_KEY':'isolated-browser-test','TESTING':True})
 with connect(app.config['DATABASE'],write=True) as db:
  db.executemany('INSERT INTO users(name,password) VALUES (?,?)',[(name,generate_password_hash('test-password')) for name in ('发布者','认领人')])
 deadline = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(timespec='minutes')
 for i in range(14):
  create_task(app.config['DATABASE'],1,dict(title=f'墙面测试任务 {i+1}',description='真实数据库任务',requirements='文字成果',tags='文档 测试',project='墙面',importance='standard',urgency='normal',deadline=deadline))
 server=make_server('127.0.0.1',0,app,threaded=True)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 base='http://127.0.0.1:'+str(server.server_port)
 profile=Path(root)/'chrome'
 proc=subprocess.Popen([binary,'--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--remote-debugging-port=0','--remote-allow-origins=*','--user-data-dir='+str(profile),'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  for _ in range(100):
   if (profile/'DevToolsActivePort').exists():break
   time.sleep(.1)
  port=(profile/'DevToolsActivePort').read_text().splitlines()[0]
  pages=json.load(urllib.request.urlopen('http://127.0.0.1:'+port+'/json'))
  ws=websocket.create_connection(pages[0]['webSocketDebuggerUrl'],timeout=15,suppress_origin=True)
  seq=0
  def call(method,params=None):
   global seq
   seq+=1;ws.send(json.dumps({'id':seq,'method':method,'params':params or {}}))
   while True:
    r=json.loads(ws.recv())
    if r.get('id')==seq:
     if 'error' in r:raise RuntimeError(r['error'])
     return r.get('result',{})
  def ev(code):
   r=call('Runtime.evaluate',{'expression':code,'returnByValue':True,'awaitPromise':True})
   if 'exceptionDetails' in r:raise RuntimeError(r['exceptionDetails'])
   return r['result'].get('value')
  def wait(expr):
   for _ in range(100):
    try:
     if ev('Boolean('+expr+')'):return
    except RuntimeError:pass
    time.sleep(.05)
   raise AssertionError(expr)
  def nav(path):
   call('Page.navigate',{'url':base+path})
   wait("document.readyState==='complete' && location.pathname==="+json.dumps(path.split('?')[0]))
  def click(selector):ev('document.querySelector('+json.dumps(selector)+').click()')
  def shot(name):
   data=call('Page.captureScreenshot',{'format':'png'})['data']
   Path('previews/'+name+'.png').write_bytes(base64.b64decode(data))
  def login(name):
   nav('/auth/login')
   ev('document.querySelector("[name=name]").value='+json.dumps(name)+';document.querySelector("[name=password]").value="test-password"')
   click('form button');wait("location.pathname==='/' && document.querySelector('.home')")
  call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1100,'deviceScaleFactor':1,'mobile':False})
  login('发布者')
  nav('/tasks/new')
  ev("document.querySelector('[name=title]').value='整理入门文档';document.querySelector('[name=description]').value='整理安装步骤和常见问题';document.querySelector('[name=requirements]').value='提交成果链接';document.querySelector('[name=new_tags]').value='文档 新人';document.querySelector('[name=importance][value=standard]').checked=true;document.querySelector('[name=urgency][value=normal]').checked=true")
  ev('document.querySelector("[name=deadline]").value='+json.dumps(deadline[:16]))
  click('form.editor button[type=submit], form.editor button.primary')
  wait("location.pathname.startsWith('/tasks/') && !location.pathname.endsWith('/new')")
  flow_path=ev('location.pathname')
  assert ev("document.querySelector('h1').textContent.includes('整理入门文档')")
  click('.account form button');wait("location.pathname==='/auth/login'")
  login('认领人')
  nav(flow_path);click('[data-action-form=claim] button')
  wait("!!document.querySelector('[data-confirmed-action=claim]')")
  assert ev("document.querySelector('[data-confirmed-action=claim]').textContent.includes('认领人')")
  shot('claim-feedback')
  nav(flow_path);assert not ev("!!document.querySelector('[data-confirmed-action]')")
  ev("document.querySelector('[data-action-form=submit] textarea').value='https://example.test/document'")
  click('[data-action-form=submit] button');wait("!!document.querySelector('[data-confirmed-action=submit]')")
  click('.account form button');wait("location.pathname==='/auth/login'")
  login('发布者');nav(flow_path)
  click('[data-action-form=return] button')
  assert not ev("document.querySelector('[data-action-form=return]').hasAttribute('aria-busy')")
  ev("document.querySelector('[data-action-form=return] textarea').value='请补充安装截图'")
  click('[data-action-form=return] button');wait("!!document.querySelector('[data-confirmed-action=return]')")
  assert ev("!!document.querySelector('.event-return')")
  click('.account form button');wait("location.pathname==='/auth/login'")
  login('认领人');nav(flow_path)
  ev("document.querySelector('[data-action-form=submit] textarea').value='已补充安装截图'")
  click('[data-action-form=submit] button');wait("!!document.querySelector('[data-confirmed-action=submit]')")
  click('.account form button');wait("location.pathname==='/auth/login'")
  login('发布者');nav(flow_path);click('[data-action-form=accept] [data-praise]')
  assert ev("document.querySelector('[data-action-form=accept] textarea').value.length>0")
  click('[data-action-form=accept] button:not([data-praise])')
  wait("!!document.querySelector('[data-confirmed-action=accept]')")
  nav('/honors');time.sleep(.2);assert not ev("document.querySelector('.award-dialog').open")
  click('.account form button');wait("location.pathname==='/auth/login'")
  login('认领人');nav('/honors');wait("document.querySelector('.award-dialog').open")
  assert ev("document.querySelector('.award-items').textContent.includes('线')")
  time.sleep(.85);shot('medal-reveal')
  click('[data-close-awards]');wait("!document.querySelector('.award-dialog').open")
  wait("!!document.querySelector('.collection-new')")
  assert ev("document.querySelector('[data-collection-key=\"standard-normal\"]').dataset.count==='1'")
  nav('/honors');time.sleep(.3);assert not ev("document.querySelector('.award-dialog').open")
  click('[data-collection-key="standard-normal"] summary')
  wait("document.querySelector('.inspect').open")
  assert ev("document.querySelector('[data-inspect-info]').textContent.includes('整理入门文档')")
  assert ev("document.querySelector('[data-coin-back]').textContent.length>0")
  wait("document.querySelector('[data-coin]').style.transform==='rotateY(0deg)'")
  shot('medal-inspect')
  ev("document.querySelector('[data-inspect-step=\"1\"]').click()")
  wait("document.querySelector('#inspect-name').textContent.startsWith('面')")
  ev("document.querySelector('[data-inspect-close]').click()")
  wait("!document.querySelector('.inspect').open")
  click('.shelf-editor summary');click('[name=medals][value="standard-normal"]');click('.shelf-editor button')
  wait("!!document.querySelector('.notice.success')")
  assert ev("document.querySelector('.shelf-slots').textContent.includes('线')")
  nav('/');assert ev("document.querySelector('.level-card').textContent.includes('Lv.')")
  assert ev("document.querySelectorAll('[data-pick]').length===3")
  assert ev("!document.querySelector('[data-lane-body=want] [data-pick]')")
  ev("document.querySelector('.dir input[value=\"测试\"]').click()")
  wait("document.querySelectorAll('[data-lane-body=want] [data-pick]').length>0")
  assert ev("document.querySelector('[data-lane-body=want] .sticker').textContent.includes('测试')")
  assert ev("document.querySelector('[data-want-tags]').textContent.includes('测试')")
  ev("document.querySelector('[data-lane-more=past]').click()")
  wait("document.querySelector('[data-lane-more=past]').dataset.batch==='1'")
  wait("document.querySelectorAll('[data-task]').length===14")
  assert ev("document.querySelectorAll('.wall-zone').length===2")
  click('[data-wall-next]')
  wait("document.querySelector('.wall-canvas').getAnimations().length===0")
  assert ev("document.querySelector('.wall-canvas').dataset.zone==='1'")
  click('[data-wall-prev]')
  wait("document.querySelector('.wall-canvas').getAnimations().length===0")
  click('[data-motion-toggle]');assert ev("document.documentElement.dataset.motion==='off'")
  assert ev("document.getAnimations().length===0")
  nav('/honors');assert ev("document.documentElement.dataset.motion==='off'")
  click('[data-motion-toggle]')
  call('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
  wait("document.documentElement.dataset.motion==='off'")
  assert ev("document.querySelector('[data-motion-toggle]').disabled")
  click('[data-collection-key="standard-normal"] summary')
  assert ev("document.querySelector('.inspect').open && document.getAnimations().length===0")
  ev("document.querySelector('[data-inspect-close]').click()")
  call('Emulation.setEmulatedMedia',{'features':[]})
  # 游戏角：一笔画第一关用真实的鼠标拖一遍，服务器检查笔画后记为通关
  nav('/play/lines')
  pts=ev("[...document.querySelectorAll('[data-node]')].map(c=>{const r=c.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})")
  call('Input.dispatchMouseEvent',{'type':'mousePressed','x':pts[0][0],'y':pts[0][1],'button':'left','clickCount':1})
  for x,y in pts[1:]:
   call('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x,'y':y,'button':'left'})
  call('Input.dispatchMouseEvent',{'type':'mouseReleased','x':pts[-1][0],'y':pts[-1][1],'button':'left','clickCount':1})
  wait("!document.querySelector('[data-solved]').hidden")
  with connect(app.config['DATABASE']) as db:
   assert db.execute('SELECT COUNT(*) FROM lines_solved').fetchone()[0]==1
  # 积木：拿起一个方块放到板子上，存起来，挂到名牌上
  nav('/play/blocks')
  ev("document.querySelector('[data-part=\"block\"]').click()")
  box=ev("(()=>{const r=document.querySelector('[data-board]').getBoundingClientRect();return [r.x,r.y,r.width]})()")
  for gx in (3,8):
   call('Input.dispatchMouseEvent',{'type':'mousePressed','x':box[0]+box[2]*gx/16,'y':box[1]+box[2]*gx/16,'button':'left','clickCount':1})
   call('Input.dispatchMouseEvent',{'type':'mouseReleased','x':box[0]+box[2]*gx/16,'y':box[1]+box[2]*gx/16,'button':'left','clickCount':1})
  assert ev("document.querySelector('[data-count]').textContent")=='2'
  ev("document.querySelector('[data-part=\"quarter\"]').click()")
  wait("document.querySelector('.toast[data-key=locked]')")
  click('[data-save-build]');wait("document.readyState==='complete' && !!document.querySelector('.work.now:not(.new)')")
  click('[data-show-build]');wait("document.querySelector('[data-show-build]').getAttribute('aria-pressed')==='true'")
  nav('/honors');assert ev("!!document.querySelector('.plate-build svg path')")
  for width in (1440,390):
   call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1150 if width==1440 else 1500,'deviceScaleFactor':1,'mobile':False})
   for name,path in [('hall','/'),('detail',flow_path),('new','/tasks/new'),('honors','/honors'),('play','/play'),('blocks','/play/blocks'),('lines','/play/lines'),('stamp','/play/stamp'),('recap','/recap')]:
    nav(path);time.sleep(.5)
    assert ev('document.documentElement.scrollWidth<=innerWidth'),(name,width)
    shot('motion-'+name+('-desktop' if width==1440 else '-mobile'))
  with connect(app.config['DATABASE']) as db:
   assert db.execute('SELECT COUNT(*) FROM honors').fetchone()[0]==1
   assert db.execute('SELECT COUNT(*) FROM featured_honors').fetchone()[0]==1
   assert [row[0] for row in db.execute('SELECT tag FROM interests')]==['测试']
  print('PASS: live browser publish, claim, validation, return/resubmit, praise + accept, private one-time ceremony, medal case + inspector, nameplate, picks, live direction lane, task wall paging, motion opt-out, reduced motion, one-stroke game, blocks build + nameplate, 18 responsive views')
  ws.close()
 finally:
  proc.terminate()
  try:proc.wait(timeout=5)
  except subprocess.TimeoutExpired:proc.kill();proc.wait()
  server.shutdown();server.server_close()
