const $=selector=>document.querySelector(selector);
const form=$('#intent-form'),task=$('#task'),result=$('#intent-result'),title=$('#intent-title'),copy=$('#intent-copy'),error=$('#error'),confirmButton=$('#confirm');
let currentIntent=null,currentPlan=null,currentTopic='',currentTier='fast',selectedDirection=null,currentSources=[],currentScreening=null,currentEvidenceGroups=[],currentReport=null,currentPpt=null,currentTaskId=null,currentTaskToken=null,taskPaused=false;
const taskSessionKey='research-delivery.active-task.v1';
const productionTaskKey='research-delivery.production-task.v1',csrfKey='research_csrf_token';
let productionMode=false,productionChallengeId='',productionPolling=false,currentIntentTicket=null,productionConfirmedClarification=null;

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
async function request(path,payload){const headers={'Content-Type':'application/json'};if(currentTaskId&&currentTaskToken){headers['X-Task-ID']=currentTaskId;headers['X-Task-Token']=currentTaskToken;}const response=await fetch(path,{method:'POST',headers,body:JSON.stringify(payload)});const data=await response.json().catch(()=>({error:'服务返回格式异常'}));if(!response.ok)throw new Error(data.detail?`${data.error||'请求失败'}：${data.detail}`:(data.error||'请求失败'));return data;}
async function productionRequest(path,{method='GET',body=null,csrf=false}={}){const headers={};if(body!==null)headers['Content-Type']='application/json';if(csrf)headers['X-CSRF-Token']=sessionStorage.getItem(csrfKey)||'';const response=await fetch(path,{method,credentials:'include',cache:'no-store',headers,body:body===null?undefined:JSON.stringify(body)});const data=await response.json().catch(()=>({message:'服务返回格式异常'}));if(!response.ok)throw new Error(data.message||data.error||'请求失败');return data;}
const wait=milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));
function setProductionProgress(progress){const stage=String(progress.current_stage||'P1'),number=Number(stage.slice(1))||1;$('#task-workspace').hidden=false;$('#task-status-title').textContent=progress.status==='failed'?'任务未完成':`正在执行 ${stage}`;document.querySelector('.progress-line i').style.width=`${Math.min(96,Math.max(12,number*10))}%`;document.querySelectorAll('.task-status li').forEach((item,index)=>{const boundary=Math.ceil(number/2);item.className=index<boundary?'done':index===boundary?'active':'';});$('#plan-output').innerHTML=`<p class="empty-plan">任务已安全保存到云端。当前阶段：${escapeHtml(stage)}。关闭页面不会中断，完成后会发送邮件。</p>`;}
async function pollProductionTask({untilIntent=false}={}){if(productionPolling)return;productionPolling=true;try{for(let count=0;count<180;count+=1){const response=await productionRequest(`/tasks/${encodeURIComponent(currentTaskId)}/progress`),progress=response.data||{};setProductionProgress(progress);const stageData=progress.stage_result?.data;if(untilIntent&&stageData?.normalized_topic){currentIntent=stageData;selectedDirection=null;title.textContent=currentIntent.normalized_topic;copy.textContent=currentIntent.need_clarification?currentIntent.clarification_question:(currentIntent.confirmation_text||currentIntent.scope_hint);const directions=Array.isArray(currentIntent.direction_options)?currentIntent.direction_options:[],directionBox=$('#direction-options');directionBox.hidden=!directions.length;directionBox.innerHTML=directions.map(item=>`<button type="button" class="direction-card" data-direction-id="${escapeHtml(item.direction_id)}"><b>${escapeHtml(item.title)}</b><span>${escapeHtml(item.focus)}</span></button>`).join('');$('#clarification-wrap').hidden=!currentIntent.need_clarification||directions.length>0;confirmButton.innerHTML=directions.length?'选择一个方向后继续 <span>→</span>':(currentIntent.need_clarification?'回答后开始完整调研 <span>→</span>':'确认并开始完整调研 <span>→</span>');result.hidden=false;result.scrollIntoView({behavior:'smooth',block:'center'});return;}if(progress.status==='completed'||progress.status==='partial'){location.href=`./delivery.html?task=${encodeURIComponent(currentTaskId)}`;return;}if(progress.status==='failed')throw new Error('任务未能完成，技术失败不会消耗首次免费资格');await wait(5000);}throw new Error('任务仍在运行，请稍后刷新页面查看');}finally{productionPolling=false;}}
function showOwnerTestCopy(){
  const fastLabel=$('input[name="tier"][value="fast"]').closest('label');
  const deepLabel=$('input[name="tier"][value="deep"]').closest('label');
  fastLabel.querySelector('small').textContent='主理人本地测试，可重复体验';
  fastLabel.querySelector('strong').textContent='每任务≤¥3';
  deepLabel.querySelector('small').textContent='主理人本地测试，可重复体验';
  deepLabel.querySelector('strong').textContent='每任务≤¥3';
  form.querySelector('.primary').innerHTML='开始本地测试 <span>→</span>';
  form.querySelector('.form-note').textContent='本机主理人测试不占用新用户首次体验名额，也不受每日体验次数限制；每个任务仍保留 ¥3 模型费用保护。';
  document.querySelector('.trust-line span').textContent='主理人可重复测试';
  const plans=document.querySelector('#plans');
  plans.querySelector('.section-intro .eyebrow').textContent='LOCAL OWNER TEST';
  plans.querySelector('.section-intro h2').innerHTML='本机可重复体验，<br />模型调用仍有预算保护。';
  const cards=plans.querySelectorAll('.plan-grid article');
  cards[0].querySelector('.plan-label').textContent='快速版 · 主理人测试';
  cards[0].querySelector(':scope > p:not(.plan-label)').textContent='本机反复测试，不占新用户首次体验名额；模型调用受单任务预算保护。';
  cards[0].querySelector('.price small').textContent='单任务模型预算';
  cards[0].querySelector('.price b').textContent='≤¥3';
  cards[0].querySelector('.price span').textContent='按 API 实际用量计费';
  cards[1].querySelector('.plan-label').textContent='深入版 · 本地测试';
  cards[1].querySelector('.price small').textContent='单任务模型预算';
  cards[1].querySelector('.price b').textContent='≤¥3';
  cards[1].querySelector('.price span').textContent='按 API 实际用量计费';
}
async function detectProduction(){
  if(location.protocol==='file:'){
    productionMode=false;error.textContent='这是文件预览，无法连接调研接口。请改用 http://127.0.0.1:4180 打开本地测试页面。';
    form.querySelector('.primary').disabled=true;return true;
  }
  let health={};try{const response=await fetch('/api/health',{cache:'no-store'});health=await response.json();const data=health;productionMode=response.ok&&data.runtime==='edgeone-gateway'&&data.ok===true;}catch(_exc){productionMode=false;}
  if(!productionMode){const local=['localhost','127.0.0.1','::1'].includes(location.hostname);if(local){if(health.owner_test_mode===true)showOwnerTestCopy();return false;}error.textContent='线上服务暂时不可用，请稍后再试。';form.querySelector('.primary').disabled=true;return true;}
  $('#cancel-task').hidden=true;$('#resume-task').hidden=true;const csrf=sessionStorage.getItem(csrfKey);if(csrf){$('#production-auth').classList.add('verified');$('#auth-status').textContent='邮箱登录状态已就绪。';}const saved=sessionStorage.getItem(productionTaskKey);if(saved){currentTaskId=saved;if(!csrf)$('#production-auth').hidden=false;else pollProductionTask().catch(exc=>{error.textContent=exc.message;});}return true;
}
async function startProductionTask(){
  if(!currentTaskId){
    if(!currentIntentTicket)throw new Error('题目确认已过期，请重新提交主题。');
    const created=await productionRequest('/tasks',{method:'POST',csrf:true,body:{intent_ticket:currentIntentTicket}});
    currentTaskId=created.data.task_id;sessionStorage.setItem(productionTaskKey,currentTaskId);currentIntentTicket=null;
  }
  await productionRequest(`/tasks/${encodeURIComponent(currentTaskId)}/continue`,{method:'POST',csrf:true,body:{clarification:productionConfirmedClarification||''}});
  productionConfirmedClarification=null;result.hidden=true;$('#production-auth').hidden=true;$('#task-workspace').hidden=false;
  $('#task-status-title').textContent='方向已确认，正在执行完整调研';
  $('#plan-output').innerHTML='<p class="empty-plan">系统将按 P2—P9 完成检索、证据提取、报告与 PPT 编排及独立核验。关闭页面不会中断任务。</p>';
  $('#task-workspace').scrollIntoView({behavior:'smooth',block:'start'});
  pollProductionTask().catch(exc=>{error.textContent=exc.message;});
}
async function fetchCurrentTask(){const response=await fetch(`/api/tasks/${encodeURIComponent(currentTaskId)}`,{headers:{'X-Task-ID':currentTaskId,'X-Task-Token':currentTaskToken}});const data=await response.json().catch(()=>({error:'服务返回格式异常'}));if(!response.ok)throw new Error(data.error||'任务恢复失败');return data.data;}
function saveTaskSession(){if(currentTaskId&&currentTaskToken)sessionStorage.setItem(taskSessionKey,JSON.stringify({taskId:currentTaskId,token:currentTaskToken}));}
function clearTaskSession(){sessionStorage.removeItem(taskSessionKey);sessionStorage.removeItem(productionTaskKey);currentTaskId=null;currentTaskToken=null;}
function resetRunForNewTopic(){
  clearTaskSession();currentIntent=null;currentPlan=null;currentSources=[];currentScreening=null;currentEvidenceGroups=[];currentReport=null;currentPpt=null;taskPaused=false;
  $('#task-workspace').hidden=true;$('#plan-output').replaceChildren();
  document.querySelectorAll('.task-status li').forEach(item=>{item.className='';});document.querySelector('.progress-line i').style.width='0%';$('#task-status-title').textContent='等待开始新任务';
}
async function downloadReport(){const response=await fetch(`/api/tasks/${encodeURIComponent(currentTaskId)}/export.md`,{headers:{'X-Task-ID':currentTaskId,'X-Task-Token':currentTaskToken}});if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||'报告下载失败');}const blob=await response.blob(),link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=`${currentTaskId}.md`;link.click();URL.revokeObjectURL(link.href);}
function setBusy(button,busy,text){button.disabled=busy;if(text)button.innerHTML=text;}
async function persistStage(stage,eventType,payload,artifactKind,required=false){if(!currentTaskId)return;try{await request(`/api/tasks/${currentTaskId}/events`,{stage,event_type:eventType,payload,artifact_kind:artifactKind||null});}catch(exc){if(required)throw new Error('题目理解未能保存，请重试；本次不会继续付费规划。');console.warn('任务状态保存失败',exc);}}
function ensureActive(){if(taskPaused)throw new Error('任务已暂停，已有结果已保存');}
const tokenUsageGroups=[
  {label:'P1 题目理解',stages:['P1'],emptyNote:'登录前意图识别使用独立预算账本，不并入本任务用量统计。'},
  {label:'P2A/P2B 研究规划',stages:['P2A','P2B']},
  {label:'P2 文献与专利检索',fixed:'检索接口步骤，不调用模型，不计模型 Tokens。'},
  {label:'P3 来源筛选',stages:['P3']},{label:'P4 证据提取',stages:['P4']},
  {label:'P5 报告生成',stages:['P5']},{label:'P6 PPT 编排',stages:['P6']},
  {label:'P7 声明提取',stages:['P7']},{label:'P8 独立核验',stages:['P8']},
  {label:'P9 终稿装配',fixed:'由程序确定性装配，不调用模型。'}
];
function usageForStages(stageNames,stageData){
  const rows=stageNames.map(stage=>stageData?.[stage]).filter(Boolean);
  if(!rows.length)return '当前任务没有该阶段的模型用量记录（可能未执行，或任务记录不完整）';
  const sum=key=>rows.reduce((total,row)=>total+Number(row[key]||0),0);
  const calls=sum('calls'),reported=sum('reported_calls'),unknown=sum('unknown_usage_calls'),total=sum('total_tokens');
  if(!reported&&unknown)return `有 ${unknown} 次网络失败未收到用量（不等于 0，是否计费未知）`;
  if(!reported)return `有 ${calls} 次调用记录，但没有收到 Tokens 用量`;
  const parts=`${total.toLocaleString()} tokens（输入 ${sum('prompt_tokens').toLocaleString()} + 输出 ${sum('completion_tokens').toLocaleString()}，其中推理 ${sum('reasoning_tokens').toLocaleString()}）`;
  return `模型回报 ${parts}；${reported} 次有用量${unknown?`，另有 ${unknown} 次网络失败用量未知`:''}${sum('truncated_calls')?`，${sum('truncated_calls')} 次截断的已报告用量已计入`:''}`;
}
function applyUsageDetail(data){
  const stageData=data?.stages||{};
  document.querySelectorAll('[data-usage-stages]').forEach(node=>{
    const stages=node.dataset.usageStages.split(',').map(item=>item.trim()).filter(Boolean);
    node.textContent=usageForStages(stages,stageData);
  });
  const total=usageForStages(Object.keys(stageData),stageData);
  const rows=tokenUsageGroups.map(group=>{
    const stageUsage=group.stages?usageForStages(group.stages,stageData):'';
    const hasCalls=group.stages?.some(stage=>stageData[stage]?.calls);
    const description=group.fixed||(group.emptyNote&&!hasCalls?group.emptyNote:stageUsage);
    return `<li><b>${escapeHtml(group.label)}：</b>${escapeHtml(description)}</li>`;
  }).join('');
  const summary=$('#usage-summary-body');
  if(summary)summary.innerHTML=`<p class="task-hint">本任务内已记录：${escapeHtml(total)}。不含登录前 P1 意图识别的独立预算记录。</p><ul>${rows}</ul>`;
}
async function refreshTaskUsage(){
  if(!currentTaskId||!currentTaskToken)return;
  const response=await fetch(`/api/tasks/${encodeURIComponent(currentTaskId)}/usage-detail`,{headers:{'X-Task-ID':currentTaskId,'X-Task-Token':currentTaskToken}});
  if(!response.ok)throw new Error('模型用量记录暂不可读取');
  const body=await response.json();applyUsageDetail(body.data);
}

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
  try{const response=await productionRequest('/auth/otp/verify',{method:'POST',body:{challenge_id:productionChallengeId,code}});sessionStorage.setItem(csrfKey,response.csrf_token);$('#production-auth').classList.add('verified');status.textContent='邮箱验证成功。';if(productionConfirmedClarification!==null)await startProductionTask();else if(currentTaskId)pollProductionTask().catch(exc=>{error.textContent=exc.message;});}
  catch(exc){status.textContent=exc.message;}
  finally{setBusy(button,false,'确认登录');}
});

form.addEventListener('submit',async event=>{
  event.preventDefault();const submittedTopic=task.value.trim(),submittedTier=$('input[name="tier"]:checked').value;
  if(submittedTopic.length<2){error.textContent='输入一个调研主题就可以开始。';task.focus();return;}
  resetRunForNewTopic();currentTopic=submittedTopic;currentTier=submittedTier;
  error.textContent='';setBusy(form.querySelector('.primary'),true,'正在理解题目… <span>·</span>');result.hidden=true;currentIntentTicket=null;productionConfirmedClarification=null;
  try{
    if(productionMode){
      const response=await productionRequest('/api/intent',{method:'POST',body:{topic:currentTopic,tier:currentTier}});
      currentIntent=response.data;currentIntentTicket=response.intent_ticket;currentTaskId=null;
    }else{
      const taskResponse=await request('/api/tasks',{topic:currentTopic,tier:currentTier});currentTaskId=taskResponse.data.task_id;currentTaskToken=taskResponse.data.owner_token;saveTaskSession();
      const response=await request('/api/intent',{topic:currentTopic,tier:currentTier});currentIntent=response.data;
      await persistStage('P1','intent_completed',currentIntent,'intent',true);
      refreshTaskUsage().catch(()=>{});
    }
    selectedDirection=null;title.textContent=currentIntent.normalized_topic;copy.textContent=currentIntent.need_clarification?currentIntent.clarification_question:(currentIntent.confirmation_text||currentIntent.scope_hint);
    const directions=Array.isArray(currentIntent.direction_options)?currentIntent.direction_options:[],directionBox=$('#direction-options');
    directionBox.hidden=!directions.length;directionBox.innerHTML=directions.map(item=>`<button type="button" class="direction-card" data-direction-id="${escapeHtml(item.direction_id)}"><b>${escapeHtml(item.title)}</b><span>${escapeHtml(item.focus)}</span></button>`).join('');
    $('#clarification-wrap').hidden=!currentIntent.need_clarification||directions.length>0;$('#clarification').value='';
    confirmButton.innerHTML=directions.length?'选择一个方向后继续 <span>→</span>':(currentIntent.need_clarification?'回答后继续 <span>→</span>':'确认研究方向 <span>→</span>');
    result.hidden=false;result.scrollIntoView({behavior:'smooth',block:'center'});
  }catch(exc){error.textContent=exc.message;}
  finally{setBusy(form.querySelector('.primary'),false,'让系统先理解题目 <span>→</span>');}
});

confirmButton.addEventListener('click',async()=>{
  const directions=Array.isArray(currentIntent?.direction_options)?currentIntent.direction_options:[];
  const clarification=directions.length?(selectedDirection?`${selectedDirection.title}：${selectedDirection.focus}`:''):$('#clarification').value.trim();
  if(currentIntent?.need_clarification&&!clarification){(directions.length?$('#direction-options .direction-card'):$('#clarification'))?.focus();return;}
  setBusy(confirmButton,true,'正在建立规划… <span>·</span>');
  try{
    if(productionMode){productionConfirmedClarification=clarification;if(!sessionStorage.getItem(csrfKey)){$('#production-auth').hidden=false;$('#auth-status').textContent='题目已确认。请验证邮箱以保存任务并开始完整调研。';$('#production-auth').scrollIntoView({behavior:'smooth',block:'center'});return;}await startProductionTask();return;}
    $('#task-workspace').hidden=false;$('#plan-output').innerHTML='<p class="empty-plan">正在确定研究问题、资料需求和交付结构…</p>';$('#task-status-title').textContent='正在建立调研规划';$('#task-workspace').scrollIntoView({behavior:'smooth',block:'start'});
    const response=await request('/api/plan',{topic:currentTopic,tier:currentTier,clarification,direction_id:selectedDirection?.direction_id||null});currentPlan=response.data;await persistStage('P2','plan_completed',currentPlan,'plan',true);renderPlan(response.data,response.usage);await refreshTaskUsage().catch(()=>{});
    $('#task-status-title').textContent='调研规划已经就绪';document.querySelector('.progress-line i').style.width='100%';
    document.querySelectorAll('.task-status li')[1].className='done';
  }catch(exc){$('#plan-output').innerHTML=`<p class="error-card">${escapeHtml(exc.message)}。题目理解已经保留，请点击“重新生成规划”继续当前阶段，无需重新提交整题。</p>`;$('#task-status-title').textContent='规划未能完成';}
  finally{setBusy(confirmButton,false,productionMode?'确认方向并继续 <span>→</span>':'重新生成规划 <span>↻</span>');}
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
  $('#plan-output').innerHTML=`<header><span>${currentTier==='deep'?'DEEP RESEARCH PLAN':'FAST RESEARCH PLAN'}</span><h2>${escapeHtml(currentIntent?.normalized_topic||currentTopic)}</h2><div class="meta"><span>${plan.questions.length} 个研究问题</span><span>${sourceCount} 组来源计划</span><span data-usage-stages="P2A,P2B">模型用量同步中…</span></div></header><h3>研究范围</h3><p>${escapeHtml(plan.research_scope)}</p><h3>需要回答的问题</h3>${questions}<h3>PPT 叙事顺序</h3><ol>${story}</ol><button class="primary retrieve-button" id="start-retrieval">检索首批真实资料 <span>→</span></button><div id="retrieval-output"></div>`;
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('#start-retrieval');if(!button)return;
  setBusy(button,true,'正在连接文献数据库… <span>·</span>');
  const output=$('#retrieval-output');output.innerHTML='<p class="empty-plan">正在检索 PubMed、Europe PMC 和 Crossref，并按 DOI、PMID 去重…</p>';
  try{const response=await request('/api/search',{topic:currentTopic,plan:currentPlan,tier:currentTier});currentSources=response.data.records;currentScreening=null;currentEvidenceGroups=[];currentReport=null;currentPpt=null;await persistStage('P2','search_completed',response.data,'sources',true);renderSources(response.data);document.querySelectorAll('.task-status li')[2].className='active';}
  catch(exc){output.innerHTML=`<p class="error-card">${escapeHtml(exc.message)}</p>`;}
  finally{setBusy(button,false,'重新检索 <span>↻</span>');}
});

function renderSources(data){
  const cards=data.records.map((item,index)=>`<article class="evidence-card"><div><span class="evidence-id">S${String(index+1).padStart(2,'0')}</span><span>${escapeHtml(item.source)} · ${escapeHtml(item.year||'年份未知')}</span></div><h4>${escapeHtml(item.title||'无标题')}</h4><p>${escapeHtml((item.abstract||'暂无摘要').slice(0,260))}${(item.abstract||'').length>260?'…':''}</p><footer><span>${escapeHtml(item.access)}</span><span>${escapeHtml((item.also_found_in||[]).join(' / '))}</span><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">查看原始记录</a></footer></article>`).join('');
  const failures=data.errors.length?`<p class="source-warning">部分来源暂时失败：${escapeHtml(data.errors.map(item=>item.source).join('、'))}。其他来源结果仍可用。智慧芽 MCP 专利来源以本次实际调用并成功返回的记录为准。</p>`:'';
  $('#retrieval-output').innerHTML=`<div class="retrieval-head"><h3>首批真实资料</h3><span>${data.records.length} 条去重记录</span></div><p class="source-notice">来源元数据仅用于调研与引用核验。智慧芽 MCP 专利信息只在本次实际调用并成功返回后纳入，且不作为论文科学结论的直接证据；PubMed 摘要可能受版权保护，请遵守 <a href="https://www.ncbi.nlm.nih.gov/About/disclaimer.html" target="_blank" rel="noopener">NCBI 声明</a>。</p>${failures}${cards||'<p class="empty-plan">没有找到可用记录，需要调整检索式。</p>'}${data.records.length?'<button class="primary screen-button" id="start-screening">筛选真正有用的资料 <span>→</span></button><div id="screening-output"></div>':''}`;
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('#start-screening');if(!button)return;
  setBusy(button,true,'正在判断相关性与证据类型… <span>·</span>');
  const output=$('#screening-output');output.innerHTML='<p class="empty-plan">系统只判断当前候选，不会凭空新增来源…</p>';
  try{const response=await request('/api/screen',{topic:currentTopic,tier:currentTier,plan:currentPlan,candidates:currentSources,queries:[],supplement:true});currentSources=response.sources||currentSources;currentScreening=response.data;await persistStage('P2','search_finalized',{records:currentSources,errors:[],queries:[]},'sources',true);await persistStage('P3','screening_completed',currentScreening,'screening',true);renderScreening(response.data,response.usage);await refreshTaskUsage().catch(()=>{});}
  catch(exc){output.innerHTML=`<p class="error-card">${escapeHtml(exc.message)}</p>`;}
  finally{setBusy(button,false,'重新筛选 <span>↻</span>');}
});

function renderScreening(data,usage){
  const rows=data.decisions.map(item=>`<article class="screen-row ${escapeHtml(item.status)}"><div><b>${escapeHtml(item.status.toUpperCase())}</b><span>${escapeHtml(item.source_id)}</span><span>${escapeHtml(item.evidence_type)}</span><span>${Math.round(Number(item.relevance_score)*100)}%</span></div><p>${escapeHtml(item.reason)}</p><small>${escapeHtml(item.intended_uses.join(' · ')||'未指定用途')}</small></article>`).join('');
  const gate=data.quality_gate;const blocked=gate&&gate.passed===false;
  $('#screening-output').innerHTML=`<div class="retrieval-head"><h3>相关性筛选</h3><span>保留 ${data.summary.keep_count} · 备选 ${data.summary.reserve_count} · 剔除 ${data.summary.drop_count}</span></div>${rows}<p class="source-notice" data-usage-stages="P3">模型用量同步中…；只对保留资料提取证据。</p>${blocked?`<p class="source-warning">来源质量尚未达标，已停止后续付费生成：${escapeHtml(gate.problems.join('；'))}。请收窄主题或调整检索式。</p>`:data.summary.keep_count?'<button class="primary extract-button" id="start-evidence">生成可核验的证据底稿 <span>→</span></button>':'<p class="source-warning">没有资料达到保留标准，需要调整检索式。</p>'}<div id="evidence-output"></div>`;
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
    currentEvidenceGroups=records;await persistStage('P4','evidence_completed',{groups:records},'evidence',true);renderEvidence(records,tokens);await refreshTaskUsage().catch(()=>{});document.querySelector('.progress-line i').style.width='55%';
  }catch(exc){output.innerHTML=`<p class="error-card">${escapeHtml(exc.message)}。已完成的 ${records.length} 个来源未被伪装成全部完成。</p>`;}
  finally{setBusy(button,false,'重新生成证据底稿 <span>↻</span>');}
});

function renderEvidence(groups,tokens){
  const evidence=groups.flatMap(group=>group.evidence_records);const unavailable=groups.filter(group=>group.extraction_status!=='extracted');
  const cards=evidence.map(item=>`<article class="evidence-record"><div><b>${escapeHtml(item.evidence_id)}</b><span>${escapeHtml(item.source_id)}</span><span>${escapeHtml(item.locator)}</span></div><h4>${escapeHtml(item.fact)}</h4>${item.excerpt?`<blockquote>${escapeHtml(item.excerpt)}</blockquote>`:''}<p><b>条件</b> ${escapeHtml(item.conditions.join('；')||'未说明')}</p><p><b>局限</b> ${escapeHtml(item.limitations.join('；')||'未说明')}</p></article>`).join('');
  $('#evidence-output').innerHTML=`<div class="retrieval-head"><h3>证据底稿</h3><span>${evidence.length} 条证据 · ${unavailable.length} 个不可提取来源</span></div>${cards||'<p class="source-warning">当前保留资料没有可提取证据，不能继续硬写报告。</p>'}<p class="source-notice" data-usage-stages="P4">模型用量同步中。每条证据都保留来源、定位、适用条件和局限。</p>${evidence.length?'<button class="primary deliver-button" id="start-deliverables">生成报告与 PPT 内容包 <span>→</span></button>':''}<div id="deliverables-output"></div>`;
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('#start-deliverables');if(!button)return;
  const evidenceRecords=currentEvidenceGroups.flatMap(group=>group.evidence_records);const figureRecords=currentEvidenceGroups.flatMap(group=>group.figure_records);
  const output=$('#deliverables-output');setBusy(button,true,'正在生成调研报告… <span>·</span>');
  try{
    const reportResponse=await request('/api/report',{intent:currentIntent,plan:currentPlan,evidence_records:evidenceRecords,figure_records:figureRecords,evidence_contexts:currentEvidenceGroups.map(group=>({source_id:group.source_id,reading_scope:group.reading_scope})),tier:currentTier});ensureActive();
    setBusy(button,true,'正在编排 PPT 内容… <span>·</span>');
    const pptResponse=await request('/api/ppt',{intent:currentIntent,plan:currentPlan,report:reportResponse.data,evidence_records:evidenceRecords,figure_records:figureRecords,source_records:currentSources.filter(source=>evidenceRecords.some(evidence=>evidence.source_id===source.source_id)),constraints:{language:'zh-CN',format:'storyboard_with_speaker_notes'},tier:currentTier});
    currentReport=reportResponse.data;await persistStage('P5','report_completed',currentReport,'report',true);currentPpt=pptResponse.data;await persistStage('P6','ppt_completed',currentPpt,'ppt',true);renderDeliverables(currentReport,currentPpt,Number(reportResponse.usage?.total_tokens||0)+Number(pptResponse.usage?.total_tokens||0));await refreshTaskUsage().catch(()=>{});
    document.querySelectorAll('.task-status li')[2].className='done';document.querySelectorAll('.task-status li')[3].className='active';document.querySelector('.progress-line i').style.width='72%';$('#task-status-title').textContent='报告与 PPT 内容包已生成';
  }catch(exc){output.innerHTML=`<p class="error-card">${escapeHtml(exc.message)}。证据底稿仍然保留，可以重试本阶段。</p>`;}
  finally{setBusy(button,false,'重新生成报告与 PPT <span>↻</span>');}
});

function renderPptPages(ppt){
  const figures=new Map(currentEvidenceGroups.flatMap(group=>group.figure_records||[]).map(item=>[item.figure_id,item]));
  const reuseLabels={allowed:'来源标注可复用（仍须核对具体许可）',citation_only:'仅建议引用原文链接',permission_required:'嵌入前需取得许可',unknown:'许可未核实，仅提供原文链接'};
  return ppt.pages.map(page=>`<article class="ppt-page" data-evidence-ids="${escapeHtml((page.evidence_ids||[]).join(' '))}"><div><b>${escapeHtml(page.page_id)}</b></div><h4>${escapeHtml(page.navigation_title||page.title)}</h4>${page.navigation_title&&page.navigation_title!==page.title?`<p class="ppt-long-title"><b>完整标题：</b>${escapeHtml(page.title)}</p>`:''}<ul>${(page.on_slide_text||[]).map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul><p><b>配图建议：</b>${escapeHtml(page.visual_suggestion||'无')}</p>${(page.figure_refs||[]).map(ref=>{const item=figures.get(ref.figure_id)||{};const url=item.article_figure_url||(item.locator||ref.locator||'').match(/https:\/\/[^\s|;)，]+/)?.[0]||'';return `<p>${escapeHtml(ref.figure_id)}：${escapeHtml(item.caption||ref.intended_use||'原文配图')} ${/^https:\/\//.test(url)?`<a href="${escapeHtml(url)}" target="_blank" rel="noopener">查看原图</a> · ${escapeHtml(url)}`:'未找到可直接访问的原图链接'}；复用状态：${escapeHtml(reuseLabels[item.reuse_status||ref.reuse_status]||reuseLabels.unknown)}</p>`;}).join('')}<p><b>参考来源：</b>${(page.source_citations||[]).map(item=>{const source=currentSources.find(source=>source.source_id===item.source_id)||{};const url=source.url||'';return `${escapeHtml(item.short_vancouver||item.source_id)} ${/^https:\/\//.test(url)?`<a href="${escapeHtml(url)}" target="_blank" rel="noopener">原文</a> · ${escapeHtml(url)}`:''}`;}).join('；')}</p><details><summary>演讲者注释</summary><p>${escapeHtml(page.speaker_notes)}</p></details></article>`).join('');
}

function renderDeliverables(report,ppt,tokens){
  const pages=renderPptPages(ppt);
  $('#deliverables-output').innerHTML=`<div class="retrieval-head"><h3>${escapeHtml(report.report_title)}</h3><span>${ppt.pages.length} 页内容</span></div><details class="report-result" open><summary>完整调研报告</summary><pre>${escapeHtml(report.report_markdown)}</pre></details><div class="ppt-result"><h3>PPT 逐页内容</h3>${pages}</div><p class="source-notice">报告与 PPT 共用证据编号；报告生成模型用量：<span data-usage-stages="P5">同步中…</span></p><p class="source-notice">PPT 编排模型用量：<span data-usage-stages="P6">同步中…</span>。当前输出是内容包，不是 .pptx 文件。</p><button class="primary verify-button" id="start-verification">独立核验并生成终稿 <span>→</span></button><div id="verification-output"></div>`;
  document.querySelectorAll('.ppt-long-title b').forEach(label=>label.remove());
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('#start-verification');if(!button||!currentReport||!currentPpt)return;
  const evidenceRecords=currentEvidenceGroups.flatMap(group=>group.evidence_records);const evidenceIds=evidenceRecords.map(item=>item.evidence_id);const sourceIds=[...new Set(evidenceRecords.map(item=>item.source_id))];
  const output=$('#verification-output');setBusy(button,true,'正在拆分事实声明… <span>·</span>');
  try{
    const claimsResponse=await request('/api/claims',{report:currentReport,ppt:currentPpt,evidence_ids:evidenceIds,tier:currentTier});ensureActive();
    setBusy(button,true,'正在独立核验引用… <span>·</span>');
    await persistStage('P7','claims_completed',claimsResponse.data,'claims',true);const verifyResponse=await request('/api/verify',{claims:claimsResponse.data,evidence_records:evidenceRecords,source_records:currentSources,tier:currentTier});ensureActive();
    setBusy(button,true,'正在同步修订终稿… <span>·</span>');
    await persistStage('P8','verification_completed',verifyResponse.data,'verification',true);const finalResponse=await request('/api/final',{verification_results:verifyResponse.data,draft_report:currentReport,draft_ppt:currentPpt,claims:claimsResponse.data.claims,claim_ids:claimsResponse.data.claims.map(item=>item.claim_id),source_ids:sourceIds,evidence_ids:evidenceIds,evidence_version:'1.0',tier:currentTier});await persistStage('P9','final_completed',finalResponse.data,'final_delivery',true);await request(`/api/tasks/${currentTaskId}/complete`,{});
    renderVerification(verifyResponse.data,finalResponse.data,{claims:Number(claimsResponse.usage?.total_tokens||0),verify:Number(verifyResponse.usage?.total_tokens||0),final:Number(finalResponse.usage?.total_tokens||0),route:verifyResponse.route});
    await refreshTaskUsage().catch(()=>{});
    document.querySelectorAll('.task-status li')[3].className='done';document.querySelectorAll('.task-status li')[4].className='done';document.querySelector('.progress-line i').style.width='100%';$('#task-status-title').textContent='可核验终稿已经完成';
  }catch(exc){const retry=canRetryFinalAssembly()?'<button class="export-link" id="retry-final-only" type="button">只重试终稿装配（复用已保存核验结果）</button>':'<p class="source-warning">当前任务缺少完整保存的来源或证据，不能通过重复装配修复。请从新任务重新生成，避免将其他任务的资料拼入本稿。</p>';output.innerHTML=`<p class="error-card">${escapeHtml(exc.message)}。草稿仍保留，核验失败不会伪装成终稿。</p>${retry}`;}
  finally{await refreshTaskUsage().catch(()=>{});setBusy(button,false,'重新核验终稿 <span>↻</span>');}
});

document.addEventListener('click',async event=>{
  const button=event.target.closest('#retry-final-only');if(!button||!currentTaskId)return;
  setBusy(button,true,'正在复用已保存结果装配终稿…');
  try{
    const response=await request('/api/final/retry',{});
    await persistStage('P9','final_completed',response.data,'final_delivery',true);
    await request(`/api/tasks/${currentTaskId}/complete`,{});
    const saved=await fetchCurrentTask(),verification=saved.artifacts?.verification?.data;
    if(verification)renderVerification(verification,response.data,{claims:0,verify:0,final:0,route:{model:'已保存任务',reason:'仅重试确定性终稿装配'}});
    document.querySelectorAll('.task-status li')[3].className='done';document.querySelectorAll('.task-status li')[4].className='done';document.querySelector('.progress-line i').style.width='100%';$('#task-status-title').textContent='可核验终稿已经完成';
    await refreshTaskUsage().catch(()=>{});
  }catch(exc){button.insertAdjacentHTML('beforebegin',`<p class="error-card">${escapeHtml(exc.message)}。已保存的草稿与核验结果仍保留。</p>`);}
  finally{setBusy(button,false,'只重试终稿装配（复用已保存核验结果）');}
});

function renderVerification(verification,finalDelivery,meta){
  const summary=verification.summary;
  const changes=finalDelivery.change_log.map(item=>`<li><b>${escapeHtml(item.claim_id)}</b> · ${escapeHtml(item.action)} · ${escapeHtml(item.reason)}</li>`).join('');
  $('#verification-output').innerHTML=`<div class="verification-summary"><div><b>${summary.supported}</b><span>支持</span></div><div><b>${summary.partially_supported}</b><span>部分支持</span></div><div><b>${summary.unsupported}</b><span>不支持</span></div><div><b>${summary.cannot_determine}</b><span>无法判断</span></div></div><details class="report-result" open><summary>核验后的最终报告</summary><pre>${renderLinkedReportMarkdown(finalDelivery.final_report.markdown)}</pre></details><section class="ppt-result"><h3>核验后的 PPT 逐页内容包</h3>${renderPptPages(finalDelivery.final_ppt)}</section><details class="report-result"><summary>修订记录</summary><ul class="change-log">${changes||'<li>没有需要修订的声明</li>'}</ul></details><button class="export-link" id="download-report" type="button">下载 Markdown 报告</button><p class="source-notice">P7 声明提取与 P8 独立核验：<span data-usage-stages="P7,P8">模型用量同步中…</span></p><p class="source-notice">P9 终稿装配由程序确定性完成，不调用模型。</p>`;
  $('#download-report').addEventListener('click',async event=>{event.currentTarget.disabled=true;try{await downloadReport();}catch(exc){alert(exc.message);}finally{event.currentTarget.disabled=false;}});
}

function canRetryFinalAssembly(){return Boolean(currentTaskId&&currentReport&&currentPpt&&currentSources.length&&currentEvidenceGroups.some(group=>(group.evidence_records||[]).length));}

$('#cancel-task').addEventListener('click',async()=>{if(!currentTaskId)return;await request(`/api/tasks/${currentTaskId}/cancel`,{});taskPaused=true;$('#cancel-task').hidden=true;$('#resume-task').hidden=false;$('#task-status-title').textContent='任务已暂停，已有结果已保存';});
$('#resume-task').addEventListener('click',async()=>{if(!currentTaskId)return;await request(`/api/tasks/${currentTaskId}/resume`,{});taskPaused=false;$('#resume-task').hidden=true;$('#cancel-task').hidden=false;$('#task-status-title').textContent='任务已恢复，可以从当前阶段继续';});
$('#forget-task').addEventListener('click',()=>{clearTaskSession();location.reload();});

function restoreArtifacts(saved){
  const artifacts=saved.artifacts||{},read=kind=>artifacts[kind]?.data;
  currentTopic=saved.topic;currentTier=saved.tier;currentIntent=read('intent');currentPlan=read('plan');currentSources=read('sources')?.records||[];currentScreening=read('screening')||null;currentEvidenceGroups=read('evidence')?.groups||[];currentReport=read('report')||null;currentPpt=read('ppt')||null;
  task.value=currentTopic;const tierInput=$(`input[name="tier"][value="${currentTier}"]`);if(tierInput)tierInput.checked=true;
  if(currentIntent){title.textContent=currentIntent.normalized_topic||currentTopic;copy.textContent=currentIntent.confirmation_text||currentIntent.scope_hint||'';result.hidden=false;}
  if(!currentPlan){
    if(saved.current_stage!=='P1'){
      $('#task-workspace').hidden=false;$('#task-status-title').textContent='任务记录不完整，已停止终稿核验';
      $('#plan-output').innerHTML='<p class="error-card">这条任务缺少已保存的规划或来源、证据与交付内容。页面中的其他任务草稿不能并入本任务；请回到上方重新提交主题，系统会从全新的任务记录开始。</p>';
      refreshTaskUsage().catch(exc=>console.warn('模型用量恢复失败',exc));
    }
    return;
  }
  $('#task-workspace').hidden=false;renderPlan(currentPlan,{});
  if(currentSources.length)renderSources(read('sources'));
  if(currentScreening)renderScreening(currentScreening,{});
  if(currentEvidenceGroups.length)renderEvidence(currentEvidenceGroups,0);
  if(currentReport&&currentPpt)renderDeliverables(currentReport,currentPpt,0);
  const verification=read('verification'),finalDelivery=read('final_delivery');
  if(verification&&finalDelivery)renderVerification(verification,finalDelivery,{claims:0,verify:0,final:0,route:{model:'已保存任务',reason:'从服务端恢复'}});
  else if(verification&&read('claims')&&currentReport&&currentPpt){const retry=canRetryFinalAssembly()?'<p class="source-notice">已恢复这条任务保存的声明和独立核验结果；可直接重试终稿装配，不会重新调用模型。</p><button class="export-link" id="retry-final-only" type="button">只重试终稿装配（复用已保存核验结果）</button>':'<p class="source-warning">这条任务没有完整保存来源或证据，不能只重试终稿装配。请重新开始当前主题任务；已保存草稿不会被伪装成可核验终稿。</p>';$('#verification-output').innerHTML=retry;}
  const stageNumber=Number(String(saved.current_stage||'P1').slice(1))||1;document.querySelector('.progress-line i').style.width=`${Math.min(100,Math.max(20,stageNumber*11))}%`;
  document.querySelectorAll('.task-status li').forEach((item,index)=>{item.className=index<Math.ceil(stageNumber/2)?'done':(index===Math.ceil(stageNumber/2)?'active':'');});
  taskPaused=saved.status==='cancelled';$('#cancel-task').hidden=taskPaused||saved.status==='completed';$('#resume-task').hidden=!taskPaused;
  $('#task-status-title').textContent=saved.status==='completed'?'可核验终稿已经完成':(taskPaused?'任务已暂停，已有结果已保存':`已恢复到 ${saved.current_stage||'当前'} 阶段`);
  refreshTaskUsage().catch(exc=>console.warn('模型用量恢复失败',exc));
}

async function restoreTaskSession(){
  let saved;try{saved=JSON.parse(sessionStorage.getItem(taskSessionKey)||'null');}catch(_exc){clearTaskSession();return;}
  if(!saved?.taskId||!saved?.token)return;
  currentTaskId=saved.taskId;currentTaskToken=saved.token;
  try{restoreArtifacts(await fetchCurrentTask());}catch(exc){console.warn('任务恢复失败',exc);clearTaskSession();}
}

async function bootstrap(){const active=await detectProduction();if(!active)await restoreTaskSession();}
bootstrap().catch(exc=>{console.warn('页面初始化失败',exc);});
