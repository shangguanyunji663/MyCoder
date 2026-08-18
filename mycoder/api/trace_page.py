"""vanilla JS 实时追踪页(无框架依赖),供 FastAPI 服务的 GET / 返回。

功能:提交任务 -> 拿到 task_id -> 通过 EventSource 订阅 /api/run/{id}/events,
把语义事件(task_start/step_start/model_call/tool_call/checkpoint/task_end)渲染成时间线。
"""
from __future__ import annotations

_TRACE_PAGE = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MyCoder 实时追踪</title>
<style>
  :root { color-scheme: light; --bg:#f6f7f9; --card:#fff; --line:#e3e6ea; --ink:#1f2329; --mut:#8a9099;
          --c-task:#2f6feb; --c-step:#0a8f6a; --c-model:#b8860b; --c-tool:#8957e5; --c-cp:#c2410c; }
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
         background:var(--bg); color:var(--ink); }
  header { padding:14px 18px; background:var(--card); border-bottom:1px solid var(--line); }
  header h1 { margin:0; font-size:16px; }
  main { max-width:920px; margin:18px auto; padding:0 16px; }
  .panel { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; margin-bottom:14px; }
  textarea, input[type=text] { width:100%; border:1px solid var(--line); border-radius:8px; padding:8px 10px;
          font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; resize:vertical; }
  .row { display:flex; gap:10px; align-items:center; margin-top:10px; }
  button { border:0; border-radius:8px; padding:8px 14px; background:var(--c-task); color:#fff; font-weight:600; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  .tid { font-family:ui-monospace,monospace; color:var(--mut); }
  #status { margin-left:auto; font-weight:600; }
  .timeline { list-style:none; margin:0; padding:0; position:relative; }
  .timeline li { padding:8px 10px 8px 16px; border-left:3px solid var(--line); margin:0 0 6px 6px; position:relative; }
  .timeline li::before { content:""; position:absolute; left:-7px; top:12px; width:10px; height:10px; border-radius:50%;
          background:#fff; border:2px solid var(--line); }
  .t-task_start { border-left-color:var(--c-task);} .t-task_start::before{border-color:var(--c-task);}
  .t-step_start { border-left-color:var(--c-step);} .t-step_start::before{border-color:var(--c-step);}
  .t-model_call { border-left-color:var(--c-model);} .t-model_call::before{border-color:var(--c-model);}
  .t-tool_call  { border-left-color:var(--c-tool);}  .t-tool_call::before{border-color:var(--c-tool);}
  .t-checkpoint { border-left-color:var(--c-cp);}   .t-checkpoint::before{border-color:var(--c-cp);}
  .t-task_end   { border-left-color:var(--c-task);} .t-task_end::before{border-color:var(--c-task);}
  .ev-type { font-weight:700; }
  .ev-meta { color:var(--mut); font-size:12px; }
  code { background:#eef0f3; padding:1px 5px; border-radius:4px; }
  .err { color:#d1242f; }
</style>
</head>
<body>
<header><h1>MyCoder 实时追踪 (SSE)</h1></header>
<main>
  <div class="panel">
    <label>目标 goal</label>
    <textarea id="goal" rows="2">给 src/util.py 增加 sha256_text 函数</textarea>
    <label style="display:block;margin-top:10px">脚本 script (JSON 数组,MockBackend 用;留空走真实后端)</label>
    <textarea id="script" rows="3">[]</textarea>
    <div class="row">
      <button id="run">提交任务</button>
      <span class="tid" id="tid"></span>
      <span id="status"></span>
    </div>
  </div>
  <div class="panel">
    <strong>事件流</strong>
    <ul class="timeline" id="timeline"><li class="ev-meta">尚未提交。</li></ul>
  </div>
</main>
<script>
const $ = (s)=>document.querySelector(s);
const tl = $('#timeline');
function add(ev){
  if(tl.firstChild && tl.firstChild.textContent==='尚未提交。') tl.innerHTML='';
  const li=document.createElement('li');
  li.className='t-'+(ev.type||'step_start');
  const meta=Object.entries(ev).filter(([k])=>k!=='type').map(([k,v])=>`<span class="ev-meta">${k}=${JSON.stringify(v)}</span>`).join(' ');
  li.innerHTML=`<span class="ev-type">${ev.type||'event'}</span> ${meta}`;
  tl.appendChild(li);
}
$('#run').onclick=async()=>{
  let script=[]; try{ script=JSON.parse($('#script').value||'[]'); }catch(e){ alert('script 不是合法 JSON'); return; }
  const body={goal:$('#goal').value, script};
  $('#run').disabled=true; tl.innerHTML=''; $('#status').textContent='提交中…';
  const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j=await r.json(); const tid=j.task_id;
  $('#tid').textContent='task_id: '+tid; $('#status').textContent='运行中';
  const es=new EventSource('/api/run/'+tid+'/events');
  es.onmessage=(e)=>{ try{ add(JSON.parse(e.data)); }catch(_){} };
  es.addEventListener('done',()=>{ es.close(); $('#status').textContent='完成'; $('#run').disabled=false; });
  es.onerror=()=>{ $('#status').textContent='流中断'; es.close(); $('#run').disabled=false; };
};
</script>
</body>
</html>
"""
