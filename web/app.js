const $=selector=>document.querySelector(selector);
const form=$('#intent-form'),task=$('#task'),result=$('#intent-result'),title=$('#intent-title'),copy=$('#intent-copy'),error=$('#error'),confirmButton=$('#confirm');
let currentIntent=null,currentTopic='',currentTier='fast';

const previews={
  slides:`<div class="slide-preview"><div class="slide-list"><button class="active">01 · 问题</button><button>02 · 路线</button><button>03 · 证据</button></div><div class="slide-canvas"><small>01 / RESEARCH QUESTION</small><div><h3>实体瘤为什么仍是 CAR-T 的困难场景？</h3><ul><li>抗原异质性带来逃逸风险</li><li>肿瘤微环境抑制 T 细胞活性</li><li>浸润与持续性仍限制疗效</li></ul></div><small>SOURCES · 03 / 07 / 11</small></div><aside class="speaker-note"><h4>演讲者注释</h4><p>这一页先建立问题，不急着给出路线优劣。讲述时用三个障碍解释后续技术为什么分别从靶点、细胞状态和递送方式入手。</p><span class="source-chip">来源 03</span><span class="source-chip">来源 07</span></aside></div>`,
  report:`<article class="document-preview"><p class="eyebrow">REPORT EXCERPT</p><h3>技术路线并不是简单的优劣排序</h3><p>现有方案分别针对抗原异质性、免疫抑制微环境与细胞浸润障碍。由于多数证据来自早期临床或临床前研究，不宜把不同研究中的缓解率直接视为头对头比较。</p><h4>这一结论为什么可信</h4><p>系统会把每个可核验判断拆开，对照证据中的研究对象、条件、数字和语气强度。无法确认的内容会降级表达或删除。</p></article>`,
  sources:`<div class="source-preview"><article class="source-card"><span class="verified">● 身份已核验</span><b>系统综述</b><p>用于建立主要技术路线与共识性障碍，不替代原始研究中的具体数据。</p><span class="source-chip">全文</span></article><article class="source-card"><span class="verified">● 语义已核验</span><b>临床研究</b><p>提取样本量、终点和适用范围；避免把早期信号写成确定疗效。</p><span class="source-chip">原始研究</span></article><article class="source-card"><span class="verified">● 边界已标记</span><b>注册与官方资料</b><p>核对试验状态和监管信息，和论文证据分别呈现。</p><span class="source-chip">官方来源</span></article></div>`
};

function escapeHtml(value){return String(value??'').replace(/[&<>"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[char]));}
function showPreview(name){$('#preview-body').innerHTML=previews[name];document.querySelectorAll('.preview-tabs button').forEach(button=>button.classList.toggle('active',button.dataset.preview===name));}
async function request(path,payload){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await response.json().catch(()=>({error:'服务返回格式异常'}));if(!response.ok)throw new Error(data.error||'请求失败');return data;}
function setBusy(button,busy,text){button.disabled=busy;if(text)button.innerHTML=text;}

showPreview('slides');
document.querySelectorAll('[data-preview]').forEach(button=>button.addEventListener('click',()=>showPreview(button.dataset.preview)));
document.querySelectorAll('[data-example]').forEach(button=>button.addEventListener('click',()=>{task.value=button.dataset.example;task.focus();error.textContent='';}));

form.addEventListener('submit',async event=>{
  event.preventDefault();currentTopic=task.value.trim();currentTier=$('input[name="tier"]:checked').value;
  if(currentTopic.length<2){error.textContent='输入一个调研主题就可以开始。';task.focus();return;}
  error.textContent='';setBusy(form.querySelector('.primary'),true,'正在理解题目… <span>·</span>');result.hidden=true;
  try{
    const response=await request('/api/intent',{topic:currentTopic,tier:currentTier});currentIntent=response.data;
    title.textContent=currentIntent.normalized_topic;copy.textContent=currentIntent.need_clarification?currentIntent.clarification_question:(currentIntent.confirmation_text||currentIntent.scope_hint);
    $('#clarification-wrap').hidden=!currentIntent.need_clarification;$('#clarification').value='';
    confirmButton.innerHTML=currentIntent.need_clarification?'回答后生成工作规划 <span>→</span>':'确认并生成工作规划 <span>→</span>';
    result.hidden=false;result.scrollIntoView({behavior:'smooth',block:'center'});
  }catch(exc){error.textContent=exc.message;}
  finally{setBusy(form.querySelector('.primary'),false,'让系统先理解题目 <span>→</span>');}
});

confirmButton.addEventListener('click',async()=>{
  const clarification=$('#clarification').value.trim();
  if(currentIntent?.need_clarification&&!clarification){$('#clarification').focus();return;}
  setBusy(confirmButton,true,'正在建立规划… <span>·</span>');$('#task-workspace').hidden=false;$('#plan-output').innerHTML='<p class="empty-plan">正在确定研究问题、资料需求和交付结构…</p>';$('#task-status-title').textContent='正在建立调研规划';$('#task-workspace').scrollIntoView({behavior:'smooth',block:'start'});
  try{
    const response=await request('/api/plan',{topic:currentTopic,tier:currentTier,clarification});renderPlan(response.data,response.usage);
    $('#task-status-title').textContent='调研规划已经就绪';document.querySelector('.progress-line i').style.width='100%';
    document.querySelectorAll('.task-status li')[1].className='done';
  }catch(exc){$('#plan-output').innerHTML=`<p class="error-card">${escapeHtml(exc.message)}。你可以返回上方重新提交。</p>`;$('#task-status-title').textContent='规划未能完成';}
  finally{setBusy(confirmButton,false,'重新生成规划 <span>↻</span>');}
});

function renderPlan(plan,usage){
  const questions=plan.questions.map(item=>`<div class="question"><b>${escapeHtml(item.question_id)}</b>${escapeHtml(item.question)}</div>`).join('');
  const story=plan.ppt_story_arc.map(item=>`<li>${escapeHtml(typeof item==='string'?item:(item.title||JSON.stringify(item)))}</li>`).join('');
  const sourceCount=Array.isArray(plan.source_plan)?plan.source_plan.length:0;
  $('#plan-output').innerHTML=`<header><span>${currentTier==='deep'?'DEEP RESEARCH PLAN':'FAST RESEARCH PLAN'}</span><h2>${escapeHtml(currentIntent?.normalized_topic||currentTopic)}</h2><div class="meta"><span>${plan.questions.length} 个研究问题</span><span>${sourceCount} 组来源计划</span><span>${Number(usage?.total_tokens||0).toLocaleString()} tokens</span></div></header><h3>研究范围</h3><p>${escapeHtml(plan.research_scope)}</p><h3>需要回答的问题</h3>${questions}<h3>PPT 叙事顺序</h3><ol>${story}</ol>`;
}
