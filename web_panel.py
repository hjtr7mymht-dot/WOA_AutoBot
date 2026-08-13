#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WOA AutoBot - Web 控制面板（多实例支持）
==========================================
独立的 Web 控制面板，提供：
  - FastAPI 后端服务 (默认端口 8080)
  - 多实例 MJPEG 实时视频流（支持多开模拟器同时查看）
  - 启动 / 停止 / 暂停 / 恢复 控制接口（按实例独立控制）
  - Token 安全验证（URL 参数 ?token=woa_bot_1234）
  - 嵌入式 HTML5 响应式前端（实例 Tab 切换）

依赖安装:
  pip install fastapi uvicorn opencv-python numpy

用法:
  # 1) 独立测试运行
  python web_panel.py

  # 2) 集成到主程序 (多实例)
  from web_panel import start_web_panel, bot_states, update_frame
  start_web_panel()
  ...
  update_frame(screenshot, instance_id=1)
  bot_states[1]["running"] = True
"""

import os
import sys
import time
import threading
import cv2
import numpy as np

# ============================================================
#  全局配置
# ============================================================
TOKEN = "woa_bot_1234"
PORT = 8080
MAX_INSTANCES = 8

# ============================================================
#  多实例状态存储
# ============================================================
bot_states: dict[int, dict] = {}

for _i in range(1, MAX_INSTANCES + 1):
    bot_states[_i] = {
        "running": False,
        "paused": False,
        "log": "",
        "label": f"实例 {_i}",
        "screenshot_path": f"latest_frame_{_i}.jpg",
    }

_latest_frames: dict[int, np.ndarray | None] = {i: None for i in range(1, MAX_INSTANCES + 1)}
_frame_lock = threading.Lock()
_frame_versions: dict[int, int] = {i: 0 for i in range(1, MAX_INSTANCES + 1)}
_last_served_versions: dict[int, int] = {i: -1 for i in range(1, MAX_INSTANCES + 1)}
_server_start_time: float = 0.0

# 向后兼容代理
class _BotStateProxy:
    def __getitem__(self, key): return bot_states[1][key]
    def __setitem__(self, key, value): bot_states[1][key] = value
    def get(self, key, default=None): return bot_states[1].get(key, default)
    def __contains__(self, key): return key in bot_states[1]

bot_state = _BotStateProxy()

# ============================================================
#  FastAPI 应用
# ============================================================
from fastapi import FastAPI, Query, HTTPException, Depends
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
import uvicorn

app = FastAPI(title="WOA AutoBot 控制面板", version="2.0.0", docs_url=None, redoc_url=None)

def verify_token(token: str = Query(None)):
    if token != TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid or missing token")
    return token

def _get_state(instance_id: int) -> dict:
    if instance_id not in bot_states:
        raise HTTPException(status_code=404, detail=f"实例 {instance_id} 不存在")
    return bot_states[instance_id]

# ── 实例列表 ──
@app.get("/api/instances")
async def list_instances(token: str = Depends(verify_token)):
    result = []
    for iid in sorted(bot_states.keys()):
        s = bot_states[iid]
        has_frame = False
        with _frame_lock:
            has_frame = _latest_frames.get(iid) is not None
        result.append({"id": iid, "running": s["running"], "paused": s["paused"],
                       "label": s.get("label", f"实例 {iid}"), "has_frame": has_frame})
    return JSONResponse(result)

# ── 实例控制接口 ──
@app.get("/instance/{instance_id}/control/start")
async def inst_start(instance_id: int, token: str = Depends(verify_token)):
    s = _get_state(instance_id); s["running"] = True; s["paused"] = False
    return {"status": "ok", "instance": instance_id, "action": "start", "running": True, "paused": False}

@app.get("/instance/{instance_id}/control/stop")
async def inst_stop(instance_id: int, token: str = Depends(verify_token)):
    s = _get_state(instance_id); s["running"] = False; s["paused"] = False
    return {"status": "ok", "instance": instance_id, "action": "stop", "running": False, "paused": False}

@app.get("/instance/{instance_id}/control/pause")
async def inst_pause(instance_id: int, token: str = Depends(verify_token)):
    s = _get_state(instance_id); s["paused"] = True
    return {"status": "ok", "instance": instance_id, "action": "pause", "running": s["running"], "paused": True}

@app.get("/instance/{instance_id}/control/resume")
async def inst_resume(instance_id: int, token: str = Depends(verify_token)):
    s = _get_state(instance_id); s["paused"] = False
    return {"status": "ok", "instance": instance_id, "action": "resume", "running": s["running"], "paused": False}

@app.get("/instance/{instance_id}/status")
async def inst_status(instance_id: int, token: str = Depends(verify_token)):
    s = _get_state(instance_id)
    uptime = time.time() - _server_start_time if _server_start_time else 0.0
    return JSONResponse({"instance": instance_id, "running": s["running"], "paused": s["paused"],
                         "label": s.get("label", f"实例 {instance_id}"), "uptime": uptime})

# ── MJPEG ──
def _get_frame_for(iid: int) -> np.ndarray | None:
    with _frame_lock:
        f = _latest_frames.get(iid)
        if f is not None and _frame_versions.get(iid, 0) != _last_served_versions.get(iid, -1):
            _last_served_versions[iid] = _frame_versions.get(iid, 0)
            return f.copy()
    path = bot_states.get(iid, {}).get("screenshot_path", f"latest_frame_{iid}.jpg")
    if os.path.exists(path):
        try:
            f = cv2.imread(path)
            if f is not None and f.size > 0: return f
        except Exception: pass
    return None

def _mjpeg_for(iid: int):
    while True:
        frame = _get_frame_for(iid)
        if frame is not None:
            h, w = frame.shape[:2]
            if w > 800:
                scale = 800.0 / w
                frame = cv2.resize(frame, (800, int(h * scale)), interpolation=cv2.INTER_NEAREST)
            ret, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
            if ret:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        time.sleep(0.066)

@app.get("/instance/{instance_id}/screenshot")
async def inst_screenshot(instance_id: int, token: str = Depends(verify_token)):
    _get_state(instance_id)
    return StreamingResponse(_mjpeg_for(instance_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache",
                 "Expires": "0", "X-Accel-Buffering": "no"})

# ── 向后兼容路由 ──
@app.get("/status")
async def status_v1(token: str = Depends(verify_token)): return await inst_status(1, token)
@app.get("/screenshot")
async def screenshot_v1(token: str = Depends(verify_token)): return await inst_screenshot(1, token)
@app.get("/control/start")
async def ctrl_start_v1(token: str = Depends(verify_token)): return await inst_start(1, token)
@app.get("/control/stop")
async def ctrl_stop_v1(token: str = Depends(verify_token)): return await inst_stop(1, token)
@app.get("/control/pause")
async def ctrl_pause_v1(token: str = Depends(verify_token)): return await inst_pause(1, token)
@app.get("/control/resume")
async def ctrl_resume_v1(token: str = Depends(verify_token)): return await inst_resume(1, token)

# ── 实例独立页面 ──
_INST_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>实例 __IID__ - WOA</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--text-dim:#8b949e;--green:#3fb950;--red:#f85149;--yellow:#d2991d;--blue:#58a6ff;--btn-start:#238636;--btn-stop:#da3633;--btn-pause:#d2991d;--radius:14px}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:12px;-webkit-tap-highlight-color:transparent;user-select:none;-webkit-user-select:none}
.header{width:100%;max-width:460px;text-align:center;padding:8px 0}
.header h1{font-size:18px;color:var(--blue)}
.back-link{font-size:13px;color:var(--text-dim);text-decoration:none;margin-bottom:8px}
.status-bar{display:flex;align-items:center;gap:10px;padding:12px 20px;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);width:100%;max-width:460px;margin-bottom:10px}
.status-dot{width:14px;height:14px;border-radius:50%;flex-shrink:0;background:var(--red);box-shadow:0 0 10px var(--red);transition:all .35s}
.status-dot.running{background:var(--green);box-shadow:0 0 12px var(--green)}
.status-dot.paused{background:var(--yellow);box-shadow:0 0 12px var(--yellow);animation:pulse 1.4s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.status-text{font-size:15px;font-weight:600}
.video-wrap{width:100%;max-width:460px;aspect-ratio:16/9;background:#000;border:2px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:12px;position:relative}
.video-wrap img{width:100%;height:100%;object-fit:contain;display:block}
.video-placeholder{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--text-dim);font-size:13px;pointer-events:none;flex-direction:column;gap:8px}
.btn-row{display:flex;gap:8px;width:100%;max-width:460px}
.btn{flex:1;padding:16px 4px;border:none;border-radius:var(--radius);font-size:17px;font-weight:700;color:#fff;cursor:pointer;transition:all .12s;-webkit-appearance:none;touch-action:manipulation}
.btn:active{transform:scale(.97)}.btn:disabled{opacity:.35;pointer-events:none;filter:grayscale(.5)}
.btn-start{background:var(--btn-start)}.btn-pause{background:var(--btn-pause)}.btn-stop{background:var(--btn-stop)}
.toast{position:fixed;top:18px;left:50%;transform:translateX(-50%);background:var(--card);color:var(--text);border:1px solid var(--border);padding:10px 22px;border-radius:24px;font-size:14px;z-index:999;opacity:0;transition:opacity .3s;pointer-events:none;box-shadow:0 4px 16px rgba(0,0,0,.5)}
.toast.show{opacity:1}.toast.err{border-color:var(--red);color:var(--red)}
</style>
</head>
<body>
<div id="toast" class="toast"></div>
<div class="header"><h1>实例 __IID__</h1></div>
<a class="back-link" href="/?token=__TOKEN__">&larr; 返回总览</a>
<div class="status-bar"><div id="dot" class="status-dot"></div><span id="lbl" class="status-text">⚫ 等待…</span></div>
<div class="video-wrap"><div class="video-placeholder" id="ph"><span style="font-size:40px;opacity:.4">📡</span><span>等待画面…</span></div><img id="stream" src="" style="display:none" /></div>
<div class="btn-row">
<button class="btn btn-start" id="bs" onclick="send('start')">▶ 启动</button>
<button class="btn btn-pause" id="bp" onclick="send('pause')" disabled>⏸ 暂停</button>
<button class="btn btn-stop" id="bst" onclick="send('stop')" disabled>⏹ 停止</button>
</div>
<script>
const TK="__TOKEN__",IID=__IID__,BASE=location.origin;
let _s={running:false,paused:false},_tid=null;
function toast(m,e){var el=document.getElementById('toast');el.textContent=m;el.className='toast show'+(e?' err':'');if(_tid)clearTimeout(_tid);_tid=setTimeout(function(){el.className='toast'},2200)}
async function send(a){var c=({start:'start',pause:_s.paused?'resume':'pause',stop:'stop'})[a]||a;try{var r=await fetch(BASE+'/instance/'+IID+'/control/'+c+'?token='+TK);if(!r.ok)throw new Error('HTTP '+r.status);var d=await r.json();upd(d);toast(({start:'✅ 已启动',pause:'⏸ 已暂停',resume:'▶ 已恢复',stop:'⏹ 已停止'})[c]||c)}catch(e){toast('❌ '+e.message,true)}}
function upd(s){_s=s;var d=document.getElementById('dot'),l=document.getElementById('lbl'),bs=document.getElementById('bs'),bp=document.getElementById('bp'),bst=document.getElementById('bst'),img=document.getElementById('stream'),ph=document.getElementById('ph');d.className='status-dot';if(s.paused){d.classList.add('paused');l.textContent='🟡 已暂停';img.style.display='block';ph.style.display='none'}else if(s.running){d.classList.add('running');l.textContent='🟢 运行中';img.style.display='block';ph.style.display='none'}else{l.textContent='🔴 已停止';img.style.display='none';ph.style.display='flex'}bs.disabled=s.running;bp.disabled=!s.running;bst.disabled=!s.running;bp.textContent=s.paused?'▶ 恢复':'⏸ 暂停'}
async function poll(){try{var r=await fetch(BASE+'/instance/'+IID+'/status?token='+TK);if(r.ok)upd(await r.json())}catch(e){}}
function startStream(){var img=document.getElementById('stream');img.src=BASE+'/instance/'+IID+'/screenshot?token='+TK+'&_='+Date.now();img.onerror=function(){setTimeout(function(){if(document.hidden)return;img.src=BASE+'/instance/'+IID+'/screenshot?token='+TK+'&_='+Date.now()},2500)}}
window.addEventListener('DOMContentLoaded',function(){startStream();poll();setInterval(poll,2000)})
document.addEventListener('visibilitychange',function(){if(!document.hidden)poll()})
</script>
</body>
</html>"""

@app.get("/instance/{instance_id}", response_class=HTMLResponse)
async def instance_page(instance_id: int, token: str = Depends(verify_token)):
    _get_state(instance_id)
    return HTMLResponse(content=_INST_PAGE.replace("__TOKEN__", TOKEN).replace("__IID__", str(instance_id)))

# ── 主页：多实例总览 ──
_MAIN = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>WOA AutoBot 控制面板</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--text-dim:#8b949e;--green:#3fb950;--red:#f85149;--yellow:#d2991d;--blue:#58a6ff;--btn-start:#238636;--btn-stop:#da3633;--btn-pause:#d2991d;--radius:14px}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:12px 12px 24px;-webkit-tap-highlight-color:transparent;user-select:none;-webkit-user-select:none}
.header{width:100%;max-width:700px;text-align:center;padding:4px 0 8px}
.header h1{font-size:20px;font-weight:700;letter-spacing:2px;background:linear-gradient(135deg,var(--green),var(--blue));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.tabs{display:flex;gap:4px;width:100%;max-width:700px;overflow-x:auto;padding:4px 0 8px;-webkit-overflow-scrolling:touch;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tab{flex-shrink:0;padding:8px 18px;border-radius:20px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid var(--border);background:var(--card);color:var(--text-dim);transition:all .2s;white-space:nowrap}
.tab.active{background:var(--blue);color:#fff;border-color:var(--blue)}
.tab .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:var(--red);vertical-align:middle}
.tab .dot.on{background:var(--green)}
.tab .dot.paused{background:var(--yellow);animation:pulse 1.4s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.instance-panel{width:100%;max-width:700px;display:none}
.instance-panel.active{display:block}
.status-bar{display:flex;align-items:center;gap:10px;padding:12px 20px;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:10px}
.status-dot{width:14px;height:14px;border-radius:50%;flex-shrink:0;background:var(--red);box-shadow:0 0 10px var(--red);transition:all .35s}
.status-dot.running{background:var(--green);box-shadow:0 0 12px var(--green)}
.status-dot.paused{background:var(--yellow);box-shadow:0 0 12px var(--yellow);animation:pulse 1.4s infinite}
.status-text{font-size:15px;font-weight:600}
.status-link{font-size:12px;color:var(--blue);margin-left:auto;text-decoration:none;cursor:pointer}
.status-time{font-size:12px;color:var(--text-dim);margin-left:8px}
.video-wrap{width:100%;aspect-ratio:16/9;background:#000;border:2px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:10px;position:relative}
.video-wrap img{width:100%;height:100%;object-fit:contain;display:block}
.video-placeholder{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--text-dim);font-size:13px;pointer-events:none;flex-direction:column;gap:8px}
.btn-row{display:flex;gap:8px;width:100%}
.btn{flex:1;padding:15px 4px;border:none;border-radius:var(--radius);font-size:17px;font-weight:700;color:#fff;cursor:pointer;transition:all .12s;-webkit-appearance:none;touch-action:manipulation}
.btn:active{transform:scale(.97)}.btn:disabled{opacity:.35;pointer-events:none;filter:grayscale(.5)}
.btn-start{background:var(--btn-start)}.btn-pause{background:var(--btn-pause)}.btn-stop{background:var(--btn-stop)}
.toast{position:fixed;top:18px;left:50%;transform:translateX(-50%);background:var(--card);color:var(--text);border:1px solid var(--border);padding:10px 22px;border-radius:24px;font-size:14px;z-index:999;opacity:0;transition:opacity .3s;pointer-events:none;box-shadow:0 4px 16px rgba(0,0,0,.5)}
.toast.show{opacity:1}.toast.err{border-color:var(--red);color:var(--red)}
.footer{margin-top:14px;font-size:11px;color:var(--text-dim);text-align:center;width:100%;max-width:700px}
</style>
</head>
<body>
<div id="toast" class="toast"></div>
<div class="header"><h1>🛩 WOA AutoBot</h1></div>
<div class="tabs" id="tabs"></div>
<div id="panels"></div>
<div class="footer">v2.0 · 多实例 · 仅局域网使用</div>
<script>
const TK="__TOKEN__",BASE=location.origin;
let _instances=[],_activeId=1,_toastId=null;
function toast(m,e){var el=document.getElementById('toast');el.textContent=m;el.className='toast show'+(e?' err':'');if(_toastId)clearTimeout(_toastId);_toastId=setTimeout(function(){el.className='toast'},2200)}
function buildUI(instances){
  _instances=instances;
  var tabs=document.getElementById('tabs'),panels=document.getElementById('panels');
  tabs.innerHTML='';panels.innerHTML='';
  var html='';
  instances.forEach(function(inst){
    var iid=inst.id,label=inst.label||('实例 '+iid);
    var dotClass=inst.paused?'paused':(inst.running?'on':'');
    tabs.innerHTML+='<div class="tab" data-id="'+iid+'" onclick="switchTab('+iid+')"><span class="dot '+dotClass+'"></span>'+label+'</div>';
    html+='<div class="instance-panel" id="panel'+iid+'">'+
      '<div class="status-bar">'+
        '<div class="status-dot" id="dot'+iid+'"></div>'+
        '<span class="status-text" id="lbl'+iid+'">'+label+' ⚫ 等待…</span>'+
        '<a class="status-link" href="/instance/'+iid+'?token='+TK+'" target="_blank">🔗</a>'+
        '<span class="status-time" id="tm'+iid+'"></span>'+
      '</div>'+
      '<div class="video-wrap">'+
        '<div class="video-placeholder" id="ph'+iid+'"><span style="font-size:40px;opacity:.4">📡</span><span>等待画面…</span></div>'+
        '<img id="stream'+iid+'" src="" style="display:none" />'+
      '</div>'+
      '<div class="btn-row">'+
        '<button class="btn btn-start" id="bs'+iid+'" onclick="send('+iid+',\'start\')">▶ 启动</button>'+
        '<button class="btn btn-pause" id="bp'+iid+'" onclick="send('+iid+',\'pause\')" disabled>⏸ 暂停</button>'+
        '<button class="btn btn-stop"  id="bst'+iid+'" onclick="send('+iid+',\'stop\')"  disabled>⏹ 停止</button>'+
      '</div></div>';
  });
  panels.innerHTML=html;
  instances.forEach(function(inst){startStream(inst.id);startPoll(inst.id)});
  var firstFrame=instances.find(function(i){return i.has_frame});
  switchTab(firstFrame?firstFrame.id:(instances[0]?instances[0].id:1));
}
function switchTab(id){
  _activeId=id;
  document.querySelectorAll('.tab').forEach(function(t){t.classList.toggle('active',t.dataset.id==String(id))});
  document.querySelectorAll('.instance-panel').forEach(function(p){p.classList.toggle('active',p.id=='panel'+id)});
}
function updateTabDots(){
  document.querySelectorAll('.tab').forEach(function(t){
    var inst=_instances.find(function(i){return i.id==parseInt(t.dataset.id)});
    if(!inst)return;
    var dot=t.querySelector('.dot');
    if(dot)dot.className='dot'+(inst.paused?' paused':(inst.running?' on':''))
  })
}
async function send(id,act){
  var inst=_instances.find(function(i){return i.id==id});if(!inst)return;
  var paused=inst.paused,cmd=({start:'start',pause:paused?'resume':'pause',stop:'stop'})[act]||act;
  try{
    var r=await fetch(BASE+'/instance/'+id+'/control/'+cmd+'?token='+TK);
    if(!r.ok)throw new Error('HTTP '+r.status);
    var d=await r.json();
    updateInstUI(id,d);
    toast(({start:'✅ 实例'+id+' 已启动',pause:'⏸ 实例'+id+' 已暂停',resume:'▶ 实例'+id+' 已恢复',stop:'⏹ 实例'+id+' 已停止'})[cmd]||cmd);
  }catch(e){toast('❌ '+e.message,true)}
}
function updateInstUI(id,s){
  var inst=_instances.find(function(i){return i.id==id});if(!inst)return;
  inst.running=s.running;inst.paused=s.paused;
  var dot=document.getElementById('dot'+id),lbl=document.getElementById('lbl'+id),tm=document.getElementById('tm'+id),
      bs=document.getElementById('bs'+id),bp=document.getElementById('bp'+id),bst=document.getElementById('bst'+id),
      img=document.getElementById('stream'+id),ph=document.getElementById('ph'+id);
  if(!dot)return;
  var label=inst.label||('实例 '+id);
  dot.className='status-dot';
  if(s.paused){dot.classList.add('paused');lbl.textContent=label+' 🟡 已暂停';if(img)img.style.display='block';if(ph)ph.style.display='none'}
  else if(s.running){dot.classList.add('running');lbl.textContent=label+' 🟢 运行中';if(img)img.style.display='block';if(ph)ph.style.display='none'}
  else{lbl.textContent=label+' 🔴 已停止';if(img)img.style.display='none';if(ph)ph.style.display='flex'}
  if(bs)bs.disabled=s.running;
  if(bp){bp.disabled=!s.running;bp.textContent=s.paused?'▶ 恢复':'⏸ 暂停'}
  if(bst)bst.disabled=!s.running;
  if(s.uptime!=null){var m=Math.floor(s.uptime/60),h=Math.floor(m/60);if(tm)tm.textContent=(h?h+'h ':'')+(m%60)+'m'}
  updateTabDots()
}
async function pollInstance(id){
  try{var r=await fetch(BASE+'/instance/'+id+'/status?token='+TK);if(r.ok)updateInstUI(id,await r.json())}catch(e){}
}
function startPoll(id){setInterval(function(){pollInstance(id)},2000)}
function startStream(id){
  var img=document.getElementById('stream'+id);if(!img)return;
  img.src=BASE+'/instance/'+id+'/screenshot?token='+TK+'&_='+Date.now();
  img.onerror=function(){setTimeout(function(){if(document.hidden)return;img.src=BASE+'/instance/'+id+'/screenshot?token='+TK+'&_='+Date.now()},2500)}
}
async function refreshInstances(){
  try{
    var r=await fetch(BASE+'/api/instances?token='+TK);if(!r.ok)return;
    var newList=await r.json();
    newList.forEach(function(ni){var old=_instances.find(function(o){return o.id==ni.id});if(old){old.running=ni.running;old.paused=ni.paused;old.has_frame=ni.has_frame}});
    if(_instances.length!=newList.length)buildUI(newList);
    updateTabDots()
  }catch(e){}
}
window.addEventListener('DOMContentLoaded',function(){
  fetch(BASE+'/api/instances?token='+TK).then(function(r){return r.json()}).then(buildUI);
  setInterval(refreshInstances,5000)
})
document.addEventListener('visibilitychange',function(){if(!document.hidden)_instances.forEach(function(i){pollInstance(i.id)})})
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
async def index(token: str = Depends(verify_token)):
    return HTMLResponse(content=_MAIN.replace("__TOKEN__", TOKEN))

# ============================================================
#  供主程序调用的公开 API
# ============================================================
def update_frame(frame: np.ndarray, instance_id: int = 1):
    global _latest_frames, _frame_versions
    with _frame_lock:
        _latest_frames[instance_id] = frame.copy()
        _frame_versions[instance_id] = _frame_versions.get(instance_id, 0) + 1
    if instance_id not in bot_states:
        bot_states[instance_id] = {"running": False, "paused": False, "log": "", "label": f"实例 {instance_id}", "screenshot_path": f"latest_frame_{instance_id}.jpg"}
    try:
        cv2.imwrite(bot_states[instance_id].get("screenshot_path", f"latest_frame_{instance_id}.jpg"), frame)
    except Exception: pass

def set_instance_label(instance_id: int, label: str):
    if instance_id not in bot_states:
        bot_states[instance_id] = {"running": False, "paused": False, "log": "", "label": label, "screenshot_path": f"latest_frame_{instance_id}.jpg"}
    else: bot_states[instance_id]["label"] = label

def set_screenshot_path(path: str, instance_id: int = 1):
    if instance_id in bot_states: bot_states[instance_id]["screenshot_path"] = path

# ============================================================
#  Web 服务生命周期
# ============================================================
_server_thread: threading.Thread | None = None
_server_ready = threading.Event()

def _run_server():
    _saved_stdout, _saved_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
        config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="warning", access_log=False)
    finally:
        sys.stdout, sys.stderr = _saved_stdout, _saved_stderr
    server = uvicorn.Server(config)
    _server_ready.set()
    server.run()

def start_web_panel(port: int = 8080):
    global PORT, _server_thread, _server_start_time
    PORT = port
    if _server_thread is not None and _server_thread.is_alive(): return
    _server_ready.clear()
    _server_start_time = time.time()
    _server_thread = threading.Thread(target=_run_server, daemon=True, name="web-panel")
    _server_thread.start()
    if not _server_ready.wait(timeout=5): print("[web_panel] ⚠ 服务启动超时，请检查端口是否被占用")
    local_ip = "127.0.0.1"
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("10.255.255.255", 1))
        local_ip = s.getsockname()[0]; s.close()
    except Exception: pass
    print(f"\n{'='*52}")
    print(f"  🌐 WOA AutoBot Web 控制面板 (多实例)")
    print(f"  {'─'*40}")
    print(f"  总览     : http://127.0.0.1:{PORT}/?token={TOKEN}")
    if local_ip != "127.0.0.1": print(f"  局域网   : http://{local_ip}:{PORT}/?token={TOKEN}")
    print(f"  Token    : {TOKEN}")
    print(f"  实例直链 : /instance/1, /instance/2, ...")
    print(f"{'='*52}\n")

def stop_web_panel():
    global _server_thread; _server_thread = None

# ============================================================
#  独立测试入口
# ============================================================
if __name__ == '__main__':
    print("=" * 55)
    print("  WOA AutoBot - Web 控制面板 (多实例测试)")
    print("=" * 55)
    missing = []
    try: import fastapi
    except ImportError: missing.append("fastapi")
    try: import uvicorn
    except ImportError: missing.append("uvicorn")
    try: import cv2
    except ImportError: missing.append("opencv-python")
    if missing:
        print(f"\n❌ 缺少依赖: {', '.join(missing)}")
        print(f"   请运行: pip install {' '.join(missing)}")
        sys.exit(1)
    print("\n📸 生成多实例测试截图...")
    colors = [(55, 168, 82), (58, 130, 220), (210, 153, 29)]
    for iid in range(1, 4):
        W, H = 960, 540
        frame = np.zeros((H, W, 3), dtype=np.uint8)
        frame[:] = (40, 44, 52)
        cv2.rectangle(frame, (20, 20), (W - 20, H - 20), (65, 70, 78), 2)
        cv2.putText(frame, f"实例 {iid} - 模拟器画面", (W // 2 - 160, H // 2 - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (210, 210, 215), 2, cv2.LINE_AA)
        cv2.putText(frame, "Web 控制面板 · 多实例测试", (W // 2 - 155, H // 2 + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (145, 148, 155), 1, cv2.LINE_AA)
        cv2.circle(frame, (W // 2, H // 2 - 80), 26, colors[(iid - 1) % 3], -1)
        cv2.putText(frame, "✈", (W // 2 - 17, H // 2 - 72),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        update_frame(frame, instance_id=iid)
        set_instance_label(iid, f"模拟器 {iid}")
        print(f"   ✓ 实例 {iid} ({(iid-1)%3}号色标)")
    start_web_panel()
    print("\n💡 提示:")
    print("   · 总览页含实例 Tab 切换")
    print("   · 每个实例独立控制（启动/暂停/停止）")
    print("   · 实例直链: /instance/1, /instance/2, /instance/3")
    print("   · 按 Ctrl+C 退出\n")
    frame_count = 0
    try:
        while True:
            time.sleep(0.1)
            frame_count += 1
            if frame_count % 20 == 0:
                for iid in range(1, 4):
                    f = np.zeros((540, 960, 3), dtype=np.uint8)
                    f[:] = (40, 44, 52)
                    cv2.rectangle(f, (20, 20), (938, 518), (65, 70, 78), 2)
                    ts = time.strftime("%H:%M:%S")
                    c = colors[(iid - 1) % 3]
                    cv2.circle(f, (480, 190), 26, c, -1)
                    cv2.putText(f, "✈", (462, 198), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
                    cv2.putText(f, f"实例 {iid} · {ts} · Frame #{frame_count}", (220, 310),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (180, 185, 190), 1, cv2.LINE_AA)
                    s = bot_states.get(iid, {})
                    if s.get("running"):
                        color = (55, 168, 82) if not s.get("paused") else (210, 153, 29)
                        cv2.rectangle(f, (6, 6), (954, 534), color, 5)
                    update_frame(f, instance_id=iid)
    except KeyboardInterrupt: print("\n\n👋 Web 控制面板已退出")
