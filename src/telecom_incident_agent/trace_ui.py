"""Small dependency-free Trace viewer served by the Incident API."""

TRACE_UI_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>通信故障诊断 Trace</title>
  <style>
    :root{color-scheme:dark;--bg:#08111f;--panel:#0f1d31;--line:#28415f;--text:#e8f0fb;--muted:#94a9c1;--accent:#49d3b5;--warn:#ffca6a}
    *{box-sizing:border-box}body{margin:0;font:15px/1.55 system-ui,sans-serif;background:radial-gradient(circle at top,#132b45,var(--bg) 45%);color:var(--text)}
    main{max-width:1120px;margin:auto;padding:40px 20px 80px}h1{margin:0 0 6px;font-size:clamp(26px,4vw,42px)}p{color:var(--muted)}
    .search{display:flex;gap:10px;margin:28px 0}.search input{flex:1;background:#07101d;border:1px solid var(--line);border-radius:10px;padding:13px;color:var(--text)}
    button{border:0;border-radius:10px;padding:0 20px;background:var(--accent);color:#062019;font-weight:700;cursor:pointer}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
    .card,.step{background:color-mix(in srgb,var(--panel) 92%,transparent);border:1px solid var(--line);border-radius:14px;padding:16px}.label{color:var(--muted);font-size:12px;text-transform:uppercase}.value{font-size:18px;font-weight:700;word-break:break-word}
    #steps{display:grid;gap:12px;margin-top:18px}.step h3{margin:0 0 8px}.tool{margin:8px 0;padding:10px;border-left:3px solid var(--accent);background:#091524}.error{border-left-color:#ff7285}.empty{text-align:center;padding:35px}.boundary{color:var(--warn)}
    pre{white-space:pre-wrap;word-break:break-word;color:#bfd0e3}@media(max-width:760px){.grid{grid-template-columns:1fr 1fr}.search{flex-direction:column}button{padding:13px}}
  </style>
</head>
<body><main>
  <div class="label">Synthetic evidence only · 不连接真实设备</div>
  <h1>通信网络故障诊断 Trace</h1>
  <p>查看 Runtime 步骤、工具事实、错误、审批点和领域结论。输入 API 返回的 incident_id。</p>
  <div class="search"><input id="incident" placeholder="INC-XXXXXXXXXXXX" autocomplete="off"><button id="load">加载 Trace</button></div>
  <section class="grid" id="summary"></section><section id="steps"><div class="card empty">等待加载</div></section>
</main><script>
const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function card(label,value){return `<div class="card"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`}
async function loadTrace(){const id=document.querySelector('#incident').value.trim();if(!id)return;location.hash=id;const steps=document.querySelector('#steps');steps.innerHTML='<div class="card empty">加载中…</div>';
 try{const response=await fetch(`/v1/incidents/${encodeURIComponent(id)}/trace`);const data=await response.json();if(!response.ok)throw new Error(data.detail||response.statusText);
 document.querySelector('#summary').innerHTML=card('Incident',data.incident_id)+card('Runtime',data.runtime_status)+card('工具调用',data.tool_call_count)+card('数据边界',data.data_boundary);
 const blocks=(data.steps||[]).map(s=>`<article class="step"><div class="label">Step ${esc(s.step_no)}</div><h3>${esc(s.action_kind)}</h3>${(s.tool_calls||[]).map(t=>`<div class="tool ${t.status==='failed_closed'?'error':''}"><strong>${esc(t.tool_name)}</strong> · ${esc(t.status)} · ${esc(t.duration_ms)} ms<pre>${esc(JSON.stringify(t.output??t.error_type,null,2))}</pre></div>`).join('')}</article>`);
 if(data.pending_action)blocks.push(`<article class="step"><div class="label">审批点</div><h3>${esc(data.pending_action.kind)}</h3><pre>${esc(JSON.stringify(data.pending_action,null,2))}</pre></article>`);
 if(data.domain_result)blocks.push(`<article class="step"><div class="label">领域结果</div><h3>${esc(data.domain_result.status||'result')}</h3><pre>${esc(JSON.stringify(data.domain_result,null,2))}</pre></article>`);
 steps.innerHTML=blocks.join('')||'<div class="card empty">任务尚未生成 Trace（可能仍在队列中）</div>';
 }catch(error){steps.innerHTML=`<div class="card empty">${esc(error.message)}</div>`}}
document.querySelector('#load').addEventListener('click',loadTrace);document.querySelector('#incident').addEventListener('keydown',e=>{if(e.key==='Enter')loadTrace()});if(location.hash.slice(1)){document.querySelector('#incident').value=location.hash.slice(1);loadTrace()}
</script></body></html>"""
