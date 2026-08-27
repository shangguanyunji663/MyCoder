"""Vue 3 运行监控页。

页面使用仓库内 vendored 的 Vue global build,不需要 npm 或构建步骤。
"""
from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
VUE_RUNTIME = STATIC_DIR / "vue.global.prod.js"

_MONITOR_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MyCoder 运行监控</title>
<style>
:root { color-scheme: light; --bg:#f6f7f9; --card:#fff; --line:#e3e6ea;
  --ink:#1f2329; --mut:#707780; --blue:#2f6feb; --green:#0a8f6a;
  --amber:#b26a00; --purple:#8957e5; --red:#cf222e; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
  "PingFang SC","Microsoft YaHei",sans-serif; }
header { padding:16px 24px; background:var(--card); border-bottom:1px solid var(--line); }
header h1 { margin:0; font-size:18px; }
header p { margin:3px 0 0; color:var(--mut); }
main { max-width:1200px; margin:18px auto; padding:0 16px; }
.grid { display:grid; grid-template-columns:minmax(300px,360px) 1fr; gap:16px; }
.panel { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:16px; margin-bottom:16px; }
label { display:block; margin:0 0 6px; font-weight:600; }
textarea,input { width:100%; border:1px solid var(--line); border-radius:7px;
  padding:9px 10px; font:13px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace; }
textarea { resize:vertical; }
button { border:0; border-radius:7px; padding:9px 14px; background:var(--blue);
  color:#fff; font-weight:600; cursor:pointer; }
button:disabled { opacity:.5; cursor:default; }
.row { display:flex; gap:8px; align-items:center; }
.muted { color:var(--mut); }
.task-list { list-style:none; padding:0; margin:10px 0 0; }
.task-list li { display:flex; justify-content:space-between; gap:8px; padding:9px;
  border:1px solid var(--line); border-radius:7px; margin-top:7px; cursor:pointer; }
.task-list li.active { border-color:var(--blue); background:#f0f6ff; }
.task-id { font:12px ui-monospace,monospace; overflow:hidden; text-overflow:ellipsis; }
.status { font-weight:600; white-space:nowrap; }
.status-running { color:var(--amber); } .status-completed { color:var(--green); }
.status-error { color:var(--red); }
.timeline { list-style:none; margin:0; padding:0; }
.event { border-left:3px solid var(--line); padding:9px 10px; margin:0 0 7px 5px;
  background:#fafbfc; border-radius:0 7px 7px 0; }
.event-task_start { border-left-color:var(--blue); }
.event-step_start,.event-step_end { border-left-color:var(--green); }
.event-model_call { border-left-color:var(--amber); }
.event-tool_call { border-left-color:var(--purple); }
.event-checkpoint { border-left-color:#c2410c; }
.event-task_end { border-left-color:var(--blue); }
.event-title { font-weight:700; } .event-meta { color:var(--mut); font-size:12px; }
.metrics { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:8px;
  margin-top:10px; }
.metric { border:1px solid var(--line); border-radius:7px; padding:9px; }
.metric strong { display:block; font-size:18px; }
.artifacts a { margin-right:12px; color:var(--blue); }
@media (max-width:760px) { .grid { grid-template-columns:1fr; } }
</style>
</head>
<body>
<header><h1>MyCoder 运行监控</h1><p>Vue 3 + SSE 实时事件流 · Agent 工具调用与成本追踪</p></header>
<div id="app"><main><p>正在加载监控页...</p></main></div>
<script src="/vue.global.prod.js"></script>
<script>
const { createApp, ref, computed, onMounted, onBeforeUnmount } = Vue;
const labels = { task_start:'任务开始', step_start:'步骤开始', step_end:'步骤结束',
  model_call:'模型调用', tool_call:'工具调用', checkpoint:'检查点', task_end:'任务结束' };
function eventText(ev) {
  if (ev.type === 'model_call') return `模型 ${ev.model || '-'} · prompt ${ev.prompt_tokens || 0} · completion ${ev.completion_tokens || 0} · ${ev.latency_ms || 0}ms`;
  if (ev.type === 'tool_call') return `${ev.name || '-'} · ${ev.status || '-'} · ${ev.latency_ms || 0}ms`;
  if (ev.type === 'checkpoint') return `step ${ev.step} · ${ev.reason || '-'}`;
  return Object.entries(ev).filter(([k]) => !['type','ts'].includes(k))
    .map(([k,v]) => `${k}=${JSON.stringify(v)}`).join(' · ');
}
createApp({
  setup() {
    const goal = ref('给 src/util.py 增加 sha256_text 函数');
    const script = ref('[]');
    const followUp = ref('');
    const runs = ref([]); const selected = ref(null); const events = ref([]);
    const status = ref(''); const submitting = ref(false); let timer = null; let source = null;
    const current = computed(() => runs.value.find(x => x.task_id === selected.value) || null);
    const result = ref(null); const metrics = computed(() => result.value?.metrics || {});
    async function refreshRuns() {
      try { const r = await fetch('/api/runs'); if (r.ok) runs.value = await r.json(); }
      catch (_) { /* 标准库实现没有任务列表时由单任务轮询兜底 */ }
    }
    function append(ev) { events.value.push(ev); }
    async function pollTask(tid) {
      const r = await fetch('/api/run/' + encodeURIComponent(tid));
      if (!r.ok) return;
      const body = await r.json(); result.value = body.result || null; status.value = body.status || '';
    }
    function watchTask(tid) {
      selected.value = tid; events.value = []; result.value = null; status.value = '运行中';
      if (source) source.close();
      try {
        source = new EventSource('/api/run/' + encodeURIComponent(tid) + '/events');
        source.onmessage = e => { try { append(JSON.parse(e.data)); } catch (_) {} };
        source.addEventListener('done', async () => { source.close(); status.value = '完成'; await pollTask(tid); refreshRuns(); });
        source.onerror = () => { source.close(); source = null; pollTask(tid); };
      } catch (_) { pollTask(tid); }
    }
    async function submit() {
      let parsed = []; try { parsed = JSON.parse(script.value || '[]'); }
      catch (_) { status.value = 'script 不是合法 JSON'; return; }
      submitting.value = true; status.value = '提交中'; events.value = [];
      const body = { goal: goal.value, script: parsed };
      if (followUp.value) body.follow_up_of = followUp.value;
      try {
        const r = await fetch('/api/run', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
        if (!r.ok) throw new Error('api'); const j = await r.json(); await refreshRuns(); watchTask(j.task_id);
      } catch (_) { status.value = '提交失败,请确认 FastAPI 服务已启动'; }
      finally { submitting.value = false; }
    }
    onMounted(() => { refreshRuns(); timer = setInterval(refreshRuns, 2000); });
    onBeforeUnmount(() => { if (timer) clearInterval(timer); if (source) source.close(); });
    return { goal, script, followUp, runs, selected, current, events, status, submitting,
      result, metrics, labels, eventText, submit, watchTask };
  },
  template: `
  <main><div class="grid"><section>
    <div class="panel"><h2>提交任务</h2>
      <label>目标</label><textarea v-model="goal" rows="3"></textarea>
      <label style="margin-top:10px">Mock script(JSON,留空走真实后端)</label>
      <textarea v-model="script" rows="5"></textarea>
      <label style="margin-top:10px">父任务 ID(可选)</label><input v-model="followUp" placeholder="follow-up-of">
      <div class="row" style="margin-top:12px"><button @click="submit" :disabled="submitting">提交任务</button><span class="muted">{{ status }}</span></div>
    </div>
    <div class="panel"><h2>任务列表</h2><p v-if="!runs.length" class="muted">暂无任务</p>
      <ul class="task-list"><li v-for="item in runs" :key="item.task_id" :class="{active:selected===item.task_id}" @click="watchTask(item.task_id)"><span class="task-id">{{ item.task_id }}</span><span :class="['status','status-'+item.status]">{{ item.status }} · {{ item.event_count }}</span></li></ul>
    </div>
  </section><section>
    <div class="panel"><h2>运行指标 <span v-if="current" class="muted">{{ current.task_id }}</span></h2>
      <div class="metrics"><div class="metric"><span class="muted">状态</span><strong>{{ result?.status || current?.status || '-' }}</strong></div><div class="metric"><span class="muted">步骤</span><strong>{{ metrics.steps ?? '-' }}</strong></div><div class="metric"><span class="muted">工具调用</span><strong>{{ metrics.tool_calls ?? '-' }}</strong></div><div class="metric"><span class="muted">Token</span><strong>{{ metrics.prompt_tokens_total ?? '-' }}</strong></div><div class="metric"><span class="muted">成本</span><strong>{{ metrics.cost_usd ?? 0 }}</strong></div></div>
      <div class="artifacts" v-if="selected" style="margin-top:12px">工件: <a :href="'/api/artifacts/'+selected+'/report.md'" target="_blank">report.md</a><a :href="'/api/artifacts/'+selected+'/trajectory.jsonl'" target="_blank">trajectory.jsonl</a><a :href="'/api/artifacts/'+selected+'/metrics.json'" target="_blank">metrics.json</a></div>
    </div>
    <div class="panel"><h2>实时事件 <span class="muted">{{ events.length }} 条</span></h2><p v-if="!events.length" class="muted">选择任务或提交任务后显示 SSE 事件</p><ul class="timeline"><li v-for="(ev,index) in events" :key="index" :class="['event','event-'+ev.type]"><div class="event-title">{{ labels[ev.type] || ev.type }}</div><div>{{ eventText(ev) }}</div><div class="event-meta">{{ ev.ts || '' }}</div></li></ul></div>
  </section></div></main>`
}).mount('#app');
</script>
</body>
</html>
"""
