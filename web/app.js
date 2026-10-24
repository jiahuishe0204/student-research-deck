const $=selector=>document.querySelector(selector);
const form=$('#intent-form'),task=$('#task'),result=$('#intent-result'),title=$('#intent-title'),copy=$('#intent-copy'),error=$('#error'),confirmButton=$('#confirm');
let currentIntent=null,currentPlan=null,currentTopic='',currentTier='fast',selectedDirection=null,currentSources=[],currentScreening=null,currentEvidenceGroups=[],currentReport=null,currentPpt=null,currentTaskId=null,currentTaskToken=null,taskPaused=false;
const taskSessionKey='research-delivery.active-task.v1';
const productionTaskKey='research-delivery.production-task.v1',csrfKey='research_csrf_token';
let productionMode=false,productionChallengeId='',productionPolling=false;

const slidePreviewPages=[
  {label:'问题',eyebrow:'01 / RESEARCH QUESTION',title:'实体瘤为什么仍是 CAR-T 的困难场景？',bullets:['抗原异质性带来逃逸风险','肿瘤微环境抑制 T 细胞活性','浸润与持续性仍限制疗效'],sources:'SOURCES · 03 / 07 / 11',notes:'这一页先建立问题，不急着给出路线优劣。讲述时用三个障碍解释后续技术为什么分别从靶点、细胞状态和递送方式入手。',chips:['来源 03','来源 07']},
  {label:'路线',eyebrow:'02 / TECHNICAL ROUTES',title:'不同技术路线分别解决哪一种障碍？',bullets:['多靶点设计降低抗原逃逸风险','细胞装甲化增强抑制环境中的活性','局部递送改善肿瘤浸润与暴露'],sources:'SOURCES · 04 / 08 / 12',notes:'这一页不把路线排成简单名次，而是说明每条路线对应的问题、适用条件和仍未解决的限制。',chips:['来源 04','来源 08']},
  {label:'证据',eyebrow:'03 / EVIDENCE',title:'现有证据支持到什么程度？',bullets:['临床前结果用于说明机制可行性','早期临床信号不能等同于确定疗效','跨研究数字不作为头对头比较'],sources:'SOURCES · 05 / 09 / 13',notes:'收束时强调证据层级。讲清哪些判断来自临床前研究、哪些来自早期临床，以及为什么仍需要更成熟的比较证据。',chips:['来源 05','来源 09']}
];

const previews={
  slides:`<div class="slide-preview"><div class="slide-list" aria-label="PPT页面预览">${slidePreviewPages.map((page,index)=>`<button type="button" data-slide-preview="${index}" class="${index===0?'active':''}" aria-pressed="${index===0}">${String(index+1).padStart(2,'0')} · ${page.label}</button>`).join('')}</div><div class="slide-canvas" id="slide-preview-canvas" aria-live="polite"></div><aside class="speaker-note" id="slide-preview-note"></aside></div>`,
  report:`<article class="document-preview"><p class="eyebrow">REPORT EXCERPT</p><h3>技术路线并不是简单的优劣排序</h3><p>现有方案分别针对抗原异质性、免疫抑制微环境与细胞浸润障碍。由于多数证据来自早期临床或临床前研究，不宜把不同研究中的缓解率直接视为头对头比较。</p><h4>这一结论为什么可信</h4><p>系统会把每个可核验判断拆开，对照证据中的研究对象、条件、数字和语气强度。无法确认的内容会降级表达或删除。</p></article>`,
  sources:`<div class="source-preview"><article class="source-card"><span class="verified">● 身份已核验</span><b>系统综述</b><p>用于建立主要技术路线与共识性障碍，不替代原始研究中的具体数据。</p><span class="source-chip">全文</span></article><article class="source-card"><span class="verified">● 语义已核验</span><b>临床研究</b><p>提取样本量、终点和适用范围；避免把早期信号写成确定疗效。</p><span class="source-chip">原始研究</span></article><article class="source-card"><span class="verified">● 边界已标记</span><b>注册与官方资料</b><p>核对试验状态和监管信息，和论文证据分别呈现。</p><span class="source-chip">官方来源</span></article></div>`
};

function escapeHtml(value){return String(value??'').replace(/[&<>"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[char]));}
function renderLinkedReportMarkdown(value){
  const markdown=String(value??''),links=/\[(\d+|查看原文图页)\]\((https:\/\/[^)\s]+)\)/g;let rendered='',offset=0;
  for(const match of markdown.matchAll(links)){rendered+=escapeHtml(markdown.slice(offset,match.index));rendered+=`<a href="${escapeHtml(match[2])}" target="_blank" rel="noopener">[${escapeHtml(match[1])}]</a>`;offset=match.index+match[0].length;}
  return rendered+escapeHtml(markdown.slice(offset));
}
function renderSlidePreview(index,animate=false){
  const page=slidePreviewPages[index],canvas=$('#slide-preview-canvas'),note=$('#slide-preview-note');if(!page||!canvas||!note)return;
  const render=()=>{canvas.innerHTML=`<small>${page.eyebrow}</small><div><h3>${page.title}</h3><ul>${page.bullets.map(item=>`<li>${item}</li>`).join('')}</ul></div><small>${page.sources}</small>`;note.innerHTML=`<h4>演讲者注释</h4><p>${page.notes}</p>${page.chips.map(item=>`<span class="source-chip">${item}</span>`).join('')}`;};
  if(animate&&typeof canvas.animate==='function'&&!window.matchMedia('(prefers-reduced-motion: reduce)').matches){
    canvas.animate([{opacity:1,transform:'translateY(0)'},{opacity:0,transform:'translateY(-10px)'}],{duration:130,easing:'cubic-bezier(.55,0,1,.45)'}).finished.then(()=>{render();canvas.animate([{opacity:0,transform:'translateY(12px)'},{opacity:1,transform:'translateY(0)'}],{duration:280,easing:'cubic-bezier(0,.55,.45,1)'});});
    note.animate([{opacity:1},{opacity:0}],{duration:120}).finished.then(()=>{note.innerHTML=`<h4>演讲者注释</h4><p>${page.notes}</p>${page.chips.map(item=>`<span class="source-chip">${item}</span>`).join('')}`;note.animate([{opacity:0},{opacity:1}],{duration:260});});
  }else render();
  document.querySelectorAll('[data-slide-preview]').forEach((button,buttonIndex)=>{button.classList.toggle('active',buttonIndex===index);button.setAttribute('aria-pressed',String(buttonIndex===index));});
}
function showPreview(name){$('#preview-body').innerHTML=previews[name];document.querySelectorAll('.preview-tabs button').forEach(button=>button.classList.toggle('active',button.dataset.preview===name));if(name==='slides')renderSlidePreview(0);}
async function request(path,payload){const headers={'Content-Type':'application/json'};if(currentTaskId&&currentTaskToken){headers['X-Task-ID']=currentTaskId;headers['X-Task-Token']=currentTaskToken;}const response=await fetch(path,{method:'POST',headers,body:JSON.stringify(payload)});const data=await response.json().catch(()=>({error:'服务返回格式异常'}));if(!response.ok)throw new Error(data.error||'请求失败');return data;}
async function productionRequest(path,{method='GET',body=null,csrf=false}={}){const headers={};if(body!==null)headers['Content-Type']='application/json';if(csrf)headers['X-CSRF-Token']=sessionStorage.getItem(csrfKey)||'';const response=await fetch(path,{method,credentials:'include',cache:'no-store',headers,body:body===null?undefined:JSON.stringify(body)});const data=await response.json().catch(()=>({message:'服务返回格式异常'}));if(!response.ok)throw new Error(data.message||data.error||'请求失败');return data;}
const wait=milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));
function setProductionProgress(progress){const stage=String(progress.current_stage||'P1'),number=Number(stage.slice(1))||1;$('#task-workspace').hidden=false;$('#task-status-title').textContent=progress.status==='failed'?'任务未完成':`正在执行 ${stage}`;document.querySelector('.progress-line i').style.width=`${Math.min(96,Math.max(12,number*10))}%`;document.querySelectorAll('.task-status li').forEach((item,index)=>{const boundary=Math.ceil(number/2);item.className=index<boundary?'done':index===boundary?'active':'';});$('#plan-output').innerHTML=`<p class="empty-plan">任务已安全保存到云端。当前阶段：${escapeHtml(stage)}。关闭页面不会中断，完成后会发送邮件。</p>`;}
async function pollProductionTask({untilIntent=false}={}){if(productionPolling)return;productionPolling=true;try{for(let count=0;count<180;count+=1){const response=await productionRequest(`/tasks/${encodeURIComponent(currentTaskId)}/progress`),progress=response.data||{};setProductionProgress(progress);const stageData=progress.stage_result?.data;if(untilIntent&&stageData?.normalized_topic){currentIntent=stageData;selectedDirection=null;title.textContent=currentIntent.normalized_topic;copy.textContent=currentIntent.need_clarification?currentIntent.clarification_question:(currentIntent.confirmation_text||currentIntent.scope_hint);const directions=Array.isArray(currentIntent.direction_options)?currentIntent.direction_options:[],directionBox=$('#direction-options');directionBox.hidden=!directions.length;directionBox.innerHTML=directions.map(item=>`<button type="button" class="direction-card" data-direction-id="${escapeHtml(item.direction_id)}"><b>${escapeHtml(item.title)}</b><span>${escapeHtml(item.focus)}</span></button>`).join('');$('#clarification-wrap').hidden=!currentIntent.need_clarification||directions.length>0;confirmButton.innerHTML=directions.length?'选择一个方向后继续 <span>→</span>':(currentIntent.need_clarification?'回答后开始完整调研 <span>→</span>':'确认并开始完整调研 <span>→</span>');result.hidden=false;result.scrollIntoView({behavior:'smooth',block:'center'});return;}if(progress.status==='completed'){location.href=`./delivery.html?task=${encodeURIComponent(currentTaskId)}`;return;}if(progress.status==='failed')throw new Error('任务未能完成，技术失败不会消耗首次免费资格');await wait(5000);}throw new Error('任务仍在运行，请稍后刷新页面查看');}finally{productionPolling=false;}}
async function detectProduction(){try{const response=await fetch('/api/health',{cache:'no-store'}),data=await response.json();productionMode=response.ok&&data.runtime==='edgeone-gateway'&&data.ok===true;}catch(_){productionMode=false;}if(!productionMode)return false;$('#production-auth').hidden=false;$('#cancel-task').hidden=true;$('#resume-task').hidden=true;const csrf=sessionStorage.getItem(csrfKey);if(csrf){$('#production-auth').classList.add('verified');$('#auth-status').textContent='邮箱登录状态已就绪。';}const saved=localStorage.getItem(productionTaskKey);if(saved){currentTaskId=saved;pollProductionTask({untilIntent:true}).catch(exc=>{error.textContent=exc.message;});}return true;}
async function fetchCurrentTask(){const response=await fetch(`/api/tasks/${encodeURIComponent(currentTaskId)}`,{headers:{'X-Task-ID':currentTaskId,'X-Task-Token':currentTaskToken}});const data=await response.json().catch(()=>({error:'服务返回格式异常'}));if(!response.ok)throw new Error(data.error||'任务恢复失败');return data.data;}
function saveTaskSession(){if(currentTaskId&&currentTaskToken)sessionStorage.setItem(taskSessionKey,JSON.stringify({taskId:currentTaskId,token:currentTaskToken}));}
function clearTaskSession(){sessionStorage.removeItem(taskSessionKey);localStorage.removeItem(productionTaskKey);currentTaskId=null;currentTaskToken=null;}
async function downloadReport(){const response=await fetch(`/api/tasks/${encodeURIComponent(currentTaskId)}/export.md`,{headers:{'X-Task-ID':currentTaskId,'X-Task-Token':currentTaskToken}});if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||'报告下载失败');}const blob=await response.blob(),link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=`${currentTaskId}.md`;link.click();URL.revokeObjectURL(link.href);}
function setBusy(button,busy,text){button.disabled=busy;if(text)button.innerHTML=text;}
async function persistStage(stage,eventType,payload,artifactKind,required=false){if(!currentTaskId)return;try{await request(`/api/tasks/${currentTaskId}/events`,{stage,event_type:eventType,payload,artifact_kind:artifactKind||null});}catch(exc){if(required)throw new Error('题目理解未能保存，请重试；本次不会继续付费规划。');console.warn('任务状态保存失败',exc);}}
function ensureActive(){if(taskPaused)throw new Error('任务已暂停，已有结果已保存');}

showPreview('slides');
document.querySelectorAll('[data-preview]').forEach(button=>button.addEventListener('click',()=>showPreview(button.dataset.preview)));
$('#preview-body').addEventListener('click',event=>{const button=event.target.closest('[data-slide-preview]');if(button)renderSlidePreview(Number(button.dataset.slidePreview),true);});
document.querySelectorAll('[data-example]').forEach(button=>button.addEventListener('click',()=>{task.value=button.dataset.example;task.focus();error.textContent='';}));

$('#request-code').addEventListener('click',async event=>{
  if(!productionMode)return;const button=event.currentTarget,email=$('#auth-email').value.trim(),status=$('#auth-status');
  if(!email||!$('#auth-email').checkValidity()){status.textContent='请先填写有效邮箱地址。';$('#auth-email').focus();return;}
  setBusy(button,true,'发送中…');
  try{const response=await productionRequest('/auth/otp/request',{method:'POST',body:{email}});productionChallengeId=response.challenge_id;$('#code-row').hidden=false;status.textContent=response.message||'验证码已发送，请在十分钟内填写。';$('#auth-code').focus();}
  catch(exc){status.textContent=exc.message;}
  finally{setBusy(button,false,'重新发送');}
});

$('#verify-code').addEventListener('click',async event=>{
  if(!productionMode)return;const button=event.currentTarget,code=$('#auth-code').value.trim(),status=$('#auth-status');
  if(!productionChallengeId||!/^[0-9]{6}$/.test(code)){status.textContent='请输入邮件中的 6 位验证码。';$('#auth-code').focus();return;}
  setBusy(button,true,'验证中…');
  try{const response=await productionRequest('/auth/otp/verify',{method:'POST',body:{challenge_id:productionChallengeId,code}});sessionStorage.setItem(csrfKey,response.csrf_token);$('#production-auth').classList.add('verified');status.textContent=currentTaskId?'邮箱验证成功，正在恢复云端任务。':'邮箱验证成功，可以开始任务。';if(currentTaskId)pollProductionTask({untilIntent:true}).catch(exc=>{error.textContent=exc.message;});}
  catch(exc){status.textContent=exc.message;}
  finally{setBusy(button,false,'确认登录');}
});

form.addEventListener('submit',async event=>{
  event.preventDefault();currentTopic=task.value.trim();currentTier=$('input[name="tier"]:checked').value;
  if(currentTopic.length<2){error.textContent='输入一个调研主题就可以开始。';task.focus();return;}
  error.textContent='';setBusy(form.querySelector('.primary'),true,'正在理解题目… <span>·</span>');result.hidden=true;
  try{
    if(productionMode){
      if(!sessionStorage.getItem(csrfKey)){throw new Error('请先完成邮箱验证码登录。');}
      const taskResponse=await productionRequest('/tasks',{method:'POST',csrf:true,body:{topic:currentTopic,tier:currentTier}});currentTaskId=taskResponse.data.task_id;localStorage.setItem(productionTaskKey,currentTaskId);
      $('#task-workspace').hidden=false;$('#task-status-title').textContent='题目已提交，正在理解研究方向';$('#plan-output').innerHTML='<p class="empty-plan">任务已安全保存到云端，正在执行 P1 题目理解…</p>';$('#task-workspace').scrollIntoView({behavior:'smooth',block:'start'});
      await pollProductionTask({untilIntent:true});return;
    }
    const taskResponse=await request('/api/tasks',{topic:currentTopic,tier:currentTier});currentTaskId=taskResponse.data.task_id;currentTaskToken=taskResponse.data.owner_token;saveTaskSession();
    const response=await request('/api/intent',{topic:currentTopic,tier:currentTier});currentIntent=response.data;
    await persistStage('P1','intent_completed',currentIntent,'intent',true);
    selectedDirection=null;title.textContent=currentIntent.normalized_topic;copy.textContent=currentIntent.need_clarification?currentIntent.clarification_question:(currentIntent.confirmation_text||currentIntent.scope_hint);
    const directions=Array.isArray(currentIntent.direction_options)?currentIntent.direction_options:[],directionBox=$('#direction-options');
    directionBox.hidden=!directions.length;directionBox.innerHTML=directions.map(item=>`<button type="button" class="direction-card" data-direction-id="${escapeHtml(item.direction_id)}"><b>${escapeHtml(item.title)}</b><span>${escapeHtml(item.focus)}</span></button>`).join('');
    $('#clarification-wrap').hidden=!currentIntent.need_clarification||directions.length>0;$('#clarification').value='';
    confirmButton.innerHTML=directions.length?'选择一个方向后继续 <span>→</span>':(currentIntent.need_clarification?'回答后生成工作规划 <span>→</span>':'确认并生成工作规划 <span>→</span>');
    result.hidden=false;result.scrollIntoView({behavior:'smooth',block:'center'});
  }catch(exc){error.textContent=exc.message;}
  finally{setBusy(form.querySelector('.primary'),false,'让系统先理解题目 <span>→</span>');}
});

confirmButton.addEventListener('click',async()=>{
  const directions=Array.isArray(currentIntent?.direction_options)?currentIntent.direction_options:[];
  const clarification=directions.length?(selectedDirection?`${selectedDirection.title}：${selectedDirection.focus}`:''):$('#clarification').value.trim();
  if(currentIntent?.need_clarification&&!clarification){(directions.length?$('#direction-options .direction-card'):$('#clarification'))?.focus();return;}
  setBusy(confirmButton,true,'正在建立规划… <span>·</span>');$('#task-workspace').hidden=false;$('#plan-output').innerHTML='<p class="empty-plan">正在确定研究问题、资料需求和交付结构…</p>';$('#task-status-title').textContent='正在建立调研规划';$('#task-workspace').scrollIntoView({behavior:'smooth',block:'start'});
  try{
    if(productionMode){await productionRequest(`/tasks/${encodeURIComponent(currentTaskId)}/continue`,{method:'POST',csrf:true,body:{clarification}});result.hidden=true;$('#task-status-title').textContent='方向已确认，正在执行完整调研';$('#plan-output').innerHTML='<p class="empty-plan">系统将按 P2—P9 完成检索、证据提取、报告与 PPT 编排及独立核验。关闭页面不会中断任务。</p>';await pollProductionTask();return;}
    const response=await request('/api/plan',{topic:currentTopic,tier:currentTier,clarification,direction_id:selectedDirection?.direction_id||null});currentPlan=response.data;await persistStage('P2','plan_completed',currentPlan,'plan');renderPlan(response.data,response.usage);
    $('#task-status-title').textContent='调研规划已经就绪';document.querySelector('.progress-line i').style.width='100%';
    document.querySelectorAll('.task-status li')[1].className='done';
  }catch(exc){$('#plan-output').innerHTML=`<p class="error-card">${escapeHtml(exc.message)}。题目理解已经保留，请点击“重新生成规划”继续当前阶段，无需重新提交整题。</p>`;$('#task-status-title').textContent='规划未能完成';}
  finally{setBusy(confirmButton,false,'重新生成规划 <span>↻</span>');}
});

$('#direction-options').addEventListener('click',event=>{
  const button=event.target.closest('.direction-card');if(!button)return;
  selectedDirection=(currentIntent?.direction_options||[]).find(item=>item.direction_id===button.dataset.directionId)||null;
  document.querySelectorAll('.direction-card').forEach(item=>item.classList.toggle('selected',item===button));
  confirmButton.innerHTML='按这个方向生成工作规划 <span>→</span>';
});

function renderPlan(plan,usage){
  const questions=plan.questions.map(item=>`<div class="question"><b>${escapeHtml(item.question_id)}</b>${escapeHtml(item.question)}</div>`).join('');
  const story=plan.ppt_story_arc.map(item=>`<li>${escapeHtml(typeof item==='string'?item:(item.title||JSON.stringify(item)))}</li>`).join('');
  const sourceCount=Array.isArray(plan.source_plan)?plan.source_plan.length:0;
  $('#plan-output').innerHTML=`<header><span>${currentTier==='deep'?'DEEP RESEARCH PLAN':'FAST RESEARCH PLAN'}</span><h2>${escapeHtml(currentIntent?.normalized_topic||currentTopic)}</h2><div class="meta"><span>${plan.questions.length} 个研究问题</span><span>${sourceCount} 组来源计划</span><span>${Number(usage?.total_tokens||0).toLocaleString()} tokens</span></div></header><h3>研究范围</h3><p>${escapeHtml(plan.research_scope)}</p><h3>需要回答的问题</h3>${questions}<h3>PPT 叙事顺序</h3><ol>${story}</ol><button class="primary retrieve-button" id="start-retrieval">检索首批真实资料 <span>→</span></button><div id="retrieval-output"></div>`;
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('#start-retrieval');if(!button)return;
  setBusy(button,true,'正在连接文献数据库… <span>·</span>');
  const output=$('#retrieval-output');output.innerHTML='<p class="empty-plan">正在检索 PubMed、Europe PMC 和 Crossref，并按 DOI、PMID 去重…</p>';
  try{const response=await request('/api/search',{topic:currentTopic,plan:currentPlan,tier:currentTier});currentSources=response.data.records;currentScreening=null;currentEvidenceGroups=[];currentReport=null;currentPpt=null;await persistStage('P2','search_completed',response.data,'sources');renderSources(response.data);document.querySelectorAll('.task-status li')[2].className='active';}
  catch(exc){output.innerHTML=`<p class="error-card">${escapeHtml(exc.message)}</p>`;}
  finally{setBusy(button,false,'重新检索 <span>↻</span>');}
});

function renderSources(data){
  const cards=data.records.map((item,index)=>`<article class="evidence-card"><div><span class="evidence-id">S${String(index+1).padStart(2,'0')}</span><span>${escapeHtml(item.source)} · ${escapeHtml(item.year||'年份未知')}</span></div><h4>${escapeHtml(item.title||'无标题')}</h4><p>${escapeHtml((item.abstract||'暂无摘要').slice(0,260))}${(item.abstract||'').length>260?'…':''}</p><footer><span>${escapeHtml(item.access)}</span><span>${escapeHtml((item.also_found_in||[]).join(' / '))}</span><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">查看原始记录</a></footer></article>`).join('');
  const failures=data.errors.length?`<p class="source-warning">部分来源暂时失败：${escapeHtml(data.errors.map(item=>item.source).join('、'))}。其他来源结果仍可用。</p>`:'';
  $('#retrieval-output').innerHTML=`<div class="retrieval-head"><h3>首批真实资料</h3><span>${data.records.length} 条去重记录</span></div><p class="source-notice">来源元数据仅用于调研与引用核验；PubMed 摘要可能受版权保护，请遵守 <a href="https://www.ncbi.nlm.nih.gov/About/disclaimer.html" target="_blank" rel="noopener">NCBI 声明</a>。</p>${failures}${cards||'<p class="empty-plan">没有找到可用记录，需要调整检索式。</p>'}${data.records.length?'<button class="primary screen-button" id="start-screening">筛选真正有用的资料 <span>→</span></button><div id="screening-output"></div>':''}`;
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('#start-screening');if(!button)return;
  setBusy(button,true,'正在判断相关性与证据类型… <span>·</span>');
  const output=$('#screening-output');output.innerHTML='<p class="empty-plan">系统只判断当前候选，不会凭空新增来源…</p>';
  try{const response=await request('/api/screen',{topic:currentTopic,tier:currentTier,plan:currentPlan,candidates:currentSources,queries:[],supplement:true});currentSources=response.sources||currentSources;currentScreening=response.data;await persistStage('P2','search_finalized',{records:currentSources,errors:[],queries:[]},'sources');await persistStage('P3','screening_completed',currentScreening,'screening');renderScreening(response.data,response.usage);}
  catch(exc){output.innerHTML=`<p class="error-card">${escapeHtml(exc.message)}</p>`;}
  finally{setBusy(button,false,'重新筛选 <span>↻</span>');}
});

function renderScreening(data,usage){
  const rows=data.decisions.map(item=>`<article class="screen-row ${escapeHtml(item.status)}"><div><b>${escapeHtml(item.status.toUpperCase())}</b><span>${escapeHtml(item.source_id)}</span><span>${escapeHtml(item.evidence_type)}</span><span>${Math.round(Number(item.relevance_score)*100)}%</span></div><p>${escapeHtml(item.reason)}</p><small>${escapeHtml(item.intended_uses.join(' · ')||'未指定用途')}</small></article>`).join('');
  const gate=data.quality_gate;const blocked=gate&&gate.passed===false;
  $('#screening-output').innerHTML=`<div class="retrieval-head"><h3>相关性筛选</h3><span>保留 ${data.summary.keep_count} · 备选 ${data.summary.reserve_count} · 剔除 ${data.summary.drop_count}</span></div>${rows}<p class="source-notice">本阶段使用 ${Number(usage?.total_tokens||0).toLocaleString()} tokens；只对保留资料提取证据。</p>${blocked?`<p class="source-warning">来源质量尚未达标，已停止后续付费生成：${escapeHtml(gate.problems.join('；'))}。请收窄主题或调整检索规划。</p>`:data.summary.keep_count?'<button class="primary extract-button" id="start-evidence">生成可核验的证据底稿 <span>→</span></button>':'<p class="source-warning">没有资料达到保留标准，需要调整检索式。</p>'}<div id="evidence-output"></div>`;
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('#start-evidence');if(!button||!currentScreening)return;
  const kept=currentScreening.decisions.filter(item=>item.status==='keep');
  setBusy(button,true,`正在提取 0 / ${kept.length}… <span>·</span>`);
  const output=$('#evidence-output');const records=[];let tokens=0;
  try{
    for(let index=0;index<kept.length;index+=1){ensureActive();
      setBusy(button,true,`正在提取 ${index+1} / ${kept.length}… <span>·</span>`);
      const decision=kept[index],source=currentSources.find(item=>item.source_id===decision.source_id);
      if(!source)throw new Error(`找不到来源 ${decision.source_id}`);
      const response=await request('/api/evidence',{source_record:source,question_ids:decision.question_ids,tier:currentTier});records.push(response.data);tokens+=Number(response.usage?.total_tokens||0);
      output.innerHTML=`<p class="empty-plan">已完成 ${records.length} / ${kept.length} 个来源…</p>`;
    }
    currentEvidenceGroups=records;await persistStage('P4','evidence_completed',{groups:records},'evidence');renderEvidence(records,tokens);document.querySelector('.progress-line i').style.width='55%';
  }catch(exc){output.innerHTML=`<p class="error-card">${escapeHtml(exc.message)}。已完成的 ${records.length} 个来源未被伪装成全部完成。</p>`;}
  finally{setBusy(button,false,'重新生成证据底稿 <span>↻</span>');}
});

function renderEvidence(groups,tokens){
  const evidence=groups.flatMap(group=>group.evidence_records);const unavailable=groups.filter(group=>group.extraction_status!=='extracted');
  const cards=evidence.map(item=>`<article class="evidence-record"><div><b>${escapeHtml(item.evidence_id)}</b><span>${escapeHtml(item.source_id)}</span><span>${escapeHtml(item.locator)}</span></div><h4>${escapeHtml(item.fact)}</h4>${item.excerpt?`<blockquote>${escapeHtml(item.excerpt)}</blockquote>`:''}<p><b>条件</b> ${escapeHtml(item.conditions.join('；')||'未说明')}</p><p><b>局限</b> ${escapeHtml(item.limitations.join('；')||'未说明')}</p></article>`).join('');
  $('#evidence-output').innerHTML=`<div class="retrieval-head"><h3>证据底稿</h3><span>${evidence.length} 条证据 · ${unavailable.length} 个不可提取来源</span></div>${cards||'<p class="source-warning">当前保留资料没有可提取证据，不能继续硬写报告。</p>'}<p class="source-notice">本阶段使用 ${tokens.toLocaleString()} tokens。每条证据都保留来源、定位、适用条件和局限。</p>${evidence.length?'<button class="primary deliver-button" id="start-deliverables">生成报告与 PPT 内容包 <span>→</span></button>':''}<div id="deliverables-output"></div>`;
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('#start-deliverables');if(!button)return;
  const evidenceRecords=currentEvidenceGroups.flatMap(group=>group.evidence_records);const figureRecords=currentEvidenceGroups.flatMap(group=>group.figure_records);
  const output=$('#deliverables-output');setBusy(button,true,'正在生成调研报告… <span>·</span>');
  try{
    const reportResponse=await request('/api/report',{intent:currentIntent,plan:currentPlan,evidence_records:evidenceRecords,figure_records:figureRecords,evidence_contexts:currentEvidenceGroups.map(group=>({source_id:group.source_id,reading_scope:group.reading_scope})),tier:currentTier});ensureActive();
    setBusy(button,true,'正在编排 PPT 内容… <span>·</span>');
    const pptResponse=await request('/api/ppt',{intent:currentIntent,plan:currentPlan,report:reportResponse.data,evidence_records:evidenceRecords,figure_records:figureRecords,source_records:currentSources.filter(source=>evidenceRecords.some(evidence=>evidence.source_id===source.source_id)),constraints:{language:'zh-CN',format:'storyboard_with_speaker_notes'},tier:currentTier});
    currentReport=reportResponse.data;await persistStage('P5','report_completed',currentReport,'report');currentPpt=pptResponse.data;await persistStage('P6','ppt_completed',currentPpt,'ppt');renderDeliverables(currentReport,currentPpt,Number(reportResponse.usage?.total_tokens||0)+Number(pptResponse.usage?.total_tokens||0));
    document.querySelectorAll('.task-status li')[2].className='done';document.querySelectorAll('.task-status li')[3].className='active';document.querySelector('.progress-line i').style.width='72%';$('#task-status-title').textContent='报告与 PPT 内容包已生成';
  }catch(exc){output.innerHTML=`<p class="error-card">${escapeHtml(exc.message)}。证据底稿仍然保留，可以重试本阶段。</p>`;}
  finally{setBusy(button,false,'重新生成报告与 PPT <span>↻</span>');}
});

function renderPptPages(ppt){
  const figures=new Map(currentEvidenceGroups.flatMap(group=>group.figure_records||[]).map(item=>[item.figure_id,item]));
  const reuseLabels={allowed:'来源标注可复用（仍须核对具体许可）',citation_only:'仅建议引用原文链接',permission_required:'嵌入前需取得许可',unknown:'许可未核实，仅提供原文链接'};
  return ppt.pages.map(page=>`<article class="ppt-page" data-evidence-ids="${escapeHtml((page.evidence_ids||[]).join(' '))}"><div><b>${escapeHtml(page.page_id)}</b></div><h4>${escapeHtml(page.navigation_title||page.title)}</h4>${page.navigation_title&&page.navigation_title!==page.title?`<p class="ppt-long-title"><b>完整标题：</b>${escapeHtml(page.title)}</p>`:''}<ul>${(page.on_slide_text||[]).map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul><p><b>配图建议：</b>${escapeHtml(page.visual_suggestion||'无')}</p>${(page.figure_refs||[]).map(ref=>{const item=figures.get(ref.figure_id)||{};const url=item.article_figure_url||(item.locator||ref.locator||'').match(/https:\/\/[^\s|;)，]+/)?.[0]||'';return `<p>${escapeHtml(ref.figure_id)}：${escapeHtml(item.caption||ref.intended_use||'原文配图')} ${/^https:\/\//.test(url)?`<a href="${escapeHtml(url)}" target="_blank" rel="noopener">查看原图</a> · ${escapeHtml(url)}`:'未找到可直接访问的原图链接'}；复用状态：${escapeHtml(reuseLabels[item.reuse_status||ref.reuse_status]||reuseLabels.unknown)}</p>`;}).join('')}<p><b>来源：</b>${(page.source_citations||[]).map(item=>{const source=currentSources.find(source=>source.source_id===item.source_id)||{};const url=source.url||'';return `${escapeHtml(item.short_vancouver||item.source_id)} ${/^https:\/\//.test(url)?`<a href="${escapeHtml(url)}" target="_blank" rel="noopener">原文</a> · ${escapeHtml(url)}`:''}`;}).join('；')}</p><details><summary>演讲者注释</summary><p>${escapeHtml(page.speaker_notes)}</p></details></article>`).join('');
}

function renderDeliverables(report,ppt,tokens){
  const pages=renderPptPages(ppt);
  $('#deliverables-output').innerHTML=`<div class="retrieval-head"><h3>${escapeHtml(report.report_title)}</h3><span>${ppt.pages.length} 页内容</span></div><details class="report-result" open><summary>完整调研报告</summary><pre>${escapeHtml(report.report_markdown)}</pre></details><div class="ppt-result"><h3>PPT 逐页内容</h3>${pages}</div><p class="source-notice">报告与 PPT 共用证据编号；本阶段使用 ${tokens.toLocaleString()} tokens。当前输出是内容包，不是 .pptx 文件。</p><button class="primary verify-button" id="start-verification">独立核验并生成终稿 <span>→</span></button><div id="verification-output"></div>`;
  document.querySelectorAll('.ppt-long-title b').forEach(label=>label.remove());
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('#start-verification');if(!button||!currentReport||!currentPpt)return;
  const evidenceRecords=currentEvidenceGroups.flatMap(group=>group.evidence_records);const evidenceIds=evidenceRecords.map(item=>item.evidence_id);const sourceIds=[...new Set(evidenceRecords.map(item=>item.source_id))];
  const output=$('#verification-output');setBusy(button,true,'正在拆分事实声明… <span>·</span>');
  try{
    const claimsResponse=await request('/api/claims',{report:currentReport,ppt:currentPpt,evidence_ids:evidenceIds,tier:currentTier});ensureActive();
    setBusy(button,true,'正在独立核验引用… <span>·</span>');
    await persistStage('P7','claims_completed',claimsResponse.data,'claims');const verifyResponse=await request('/api/verify',{claims:claimsResponse.data,evidence_records:evidenceRecords,source_records:currentSources,tier:currentTier});ensureActive();
    setBusy(button,true,'正在同步修订终稿… <span>·</span>');
    await persistStage('P8','verification_completed',verifyResponse.data,'verification');const finalResponse=await request('/api/final',{verification_results:verifyResponse.data,draft_report:currentReport,draft_ppt:currentPpt,claims:claimsResponse.data.claims,claim_ids:claimsResponse.data.claims.map(item=>item.claim_id),source_ids:sourceIds,evidence_ids:evidenceIds,evidence_version:'1.0',tier:currentTier});await persistStage('P9','final_completed',finalResponse.data,'final_delivery');await request(`/api/tasks/${currentTaskId}/complete`,{});
    renderVerification(verifyResponse.data,finalResponse.data,{claims:Number(claimsResponse.usage?.total_tokens||0),verify:Number(verifyResponse.usage?.total_tokens||0),final:Number(finalResponse.usage?.total_tokens||0),route:verifyResponse.route});
    document.querySelectorAll('.task-status li')[3].className='done';document.querySelectorAll('.task-status li')[4].className='done';document.querySelector('.progress-line i').style.width='100%';$('#task-status-title').textContent='可核验终稿已经完成';
  }catch(exc){output.innerHTML=`<p class="error-card">${escapeHtml(exc.message)}。草稿仍保留，核验失败不会伪装成终稿。</p>`;}
  finally{setBusy(button,false,'重新核验终稿 <span>↻</span>');}
});

function renderVerification(verification,finalDelivery,meta){
  const summary=verification.summary;const totalTokens=meta.claims+meta.verify+meta.final;
  const changes=finalDelivery.change_log.map(item=>`<li><b>${escapeHtml(item.claim_id)}</b> · ${escapeHtml(item.action)} · ${escapeHtml(item.reason)}</li>`).join('');
  $('#verification-output').innerHTML=`<div class="verification-summary"><div><b>${summary.supported}</b><span>支持</span></div><div><b>${summary.partially_supported}</b><span>部分支持</span></div><div><b>${summary.unsupported}</b><span>不支持</span></div><div><b>${summary.cannot_determine}</b><span>无法判断</span></div></div><details class="report-result" open><summary>核验后的最终报告</summary><pre>${renderLinkedReportMarkdown(finalDelivery.final_report.markdown)}</pre></details><section class="ppt-result"><h3>核验后的 PPT 逐页内容包</h3>${renderPptPages(finalDelivery.final_ppt)}</section><details class="report-result"><summary>修订记录</summary><ul class="change-log">${changes||'<li>没有需要修订的声明</li>'}</ul></details><button class="export-link" id="download-report" type="button">下载 Markdown 报告</button><p class="source-notice">核验路由：${escapeHtml(meta.route?.model||'unknown')}（${escapeHtml(meta.route?.reason||'')}）；P7—P9 共使用 ${totalTokens.toLocaleString()} tokens。</p>`;
  $('#download-report').addEventListener('click',async event=>{event.currentTarget.disabled=true;try{await downloadReport();}catch(exc){alert(exc.message);}finally{event.currentTarget.disabled=false;}});
}

$('#cancel-task').addEventListener('click',async()=>{if(!currentTaskId)return;await request(`/api/tasks/${currentTaskId}/cancel`,{});taskPaused=true;$('#cancel-task').hidden=true;$('#resume-task').hidden=false;$('#task-status-title').textContent='任务已暂停，已有结果已保存';});
$('#resume-task').addEventListener('click',async()=>{if(!currentTaskId)return;await request(`/api/tasks/${currentTaskId}/resume`,{});taskPaused=false;$('#resume-task').hidden=true;$('#cancel-task').hidden=false;$('#task-status-title').textContent='任务已恢复，可以从当前阶段继续';});
$('#forget-task').addEventListener('click',()=>{clearTaskSession();location.reload();});

function restoreArtifacts(saved){
  const artifacts=saved.artifacts||{},read=kind=>artifacts[kind]?.data;
  currentTopic=saved.topic;currentTier=saved.tier;currentIntent=read('intent');currentPlan=read('plan');currentSources=read('sources')?.records||[];currentScreening=read('screening')||null;currentEvidenceGroups=read('evidence')?.groups||[];currentReport=read('report')||null;currentPpt=read('ppt')||null;
  task.value=currentTopic;const tierInput=$(`input[name="tier"][value="${currentTier}"]`);if(tierInput)tierInput.checked=true;
  if(currentIntent){title.textContent=currentIntent.normalized_topic||currentTopic;copy.textContent=currentIntent.confirmation_text||currentIntent.scope_hint||'';result.hidden=false;}
  if(!currentPlan)return;
  $('#task-workspace').hidden=false;renderPlan(currentPlan,{});
  if(currentSources.length)renderSources(read('sources'));
  if(currentScreening)renderScreening(currentScreening,{});
  if(currentEvidenceGroups.length)renderEvidence(currentEvidenceGroups,0);
  if(currentReport&&currentPpt)renderDeliverables(currentReport,currentPpt,0);
  const verification=read('verification'),finalDelivery=read('final_delivery');
  if(verification&&finalDelivery)renderVerification(verification,finalDelivery,{claims:0,verify:0,final:0,route:{model:'已保存任务',reason:'从服务端恢复'}});
  const stageNumber=Number(String(saved.current_stage||'P1').slice(1))||1;document.querySelector('.progress-line i').style.width=`${Math.min(100,Math.max(20,stageNumber*11))}%`;
  document.querySelectorAll('.task-status li').forEach((item,index)=>{item.className=index<Math.ceil(stageNumber/2)?'done':(index===Math.ceil(stageNumber/2)?'active':'');});
  taskPaused=saved.status==='cancelled';$('#cancel-task').hidden=taskPaused||saved.status==='completed';$('#resume-task').hidden=!taskPaused;
  $('#task-status-title').textContent=saved.status==='completed'?'可核验终稿已经完成':(taskPaused?'任务已暂停，已有结果已保存':`已恢复到 ${saved.current_stage||'当前'} 阶段`);
}

async function restoreTaskSession(){
  let saved;try{saved=JSON.parse(sessionStorage.getItem(taskSessionKey)||'null');}catch(_exc){clearTaskSession();return;}
  if(!saved?.taskId||!saved?.token)return;
  currentTaskId=saved.taskId;currentTaskToken=saved.token;
  try{restoreArtifacts(await fetchCurrentTask());}catch(exc){console.warn('任务恢复失败',exc);clearTaskSession();}
}

async function bootstrap(){const active=await detectProduction();if(!active)await restoreTaskSession();}
bootstrap().catch(exc=>{console.warn('页面初始化失败',exc);});
