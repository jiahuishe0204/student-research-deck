const $=selector=>document.querySelector(selector);
const form=$('#intent-form'),task=$('#task'),result=$('#intent-result'),title=$('#intent-title'),copy=$('#intent-copy'),error=$('#error');
const previews={
  slides:`<div class="slide-preview"><div class="slide-list"><button class="active">01 · 问题</button><button>02 · 路线</button><button>03 · 证据</button></div><div class="slide-canvas"><small>01 / RESEARCH QUESTION</small><div><h3>实体瘤为什么仍是 CAR-T 的困难场景？</h3><ul><li>抗原异质性带来逃逸风险</li><li>肿瘤微环境抑制 T 细胞活性</li><li>浸润与持续性仍限制疗效</li></ul></div><small>SOURCES · 03 / 07 / 11</small></div><aside class="speaker-note"><h4>演讲者注释</h4><p>这一页先建立问题，不急着给出路线优劣。讲述时用三个障碍解释后续技术为什么分别从靶点、细胞状态和递送方式入手。</p><span class="source-chip">来源 03</span><span class="source-chip">来源 07</span></aside></div>`,
  report:`<article class="document-preview"><p class="eyebrow">REPORT EXCERPT</p><h3>技术路线并不是简单的优劣排序</h3><p>现有方案分别针对抗原异质性、免疫抑制微环境与细胞浸润障碍。由于多数证据来自早期临床或临床前研究，不宜把不同研究中的缓解率直接视为头对头比较。</p><h4>这一结论为什么可信</h4><p>系统会把每个可核验判断拆开，对照证据中的研究对象、条件、数字和语气强度。无法确认的内容会降级表达或删除。</p></article>`,
  sources:`<div class="source-preview"><article class="source-card"><span class="verified">● 身份已核验</span><b>系统综述</b><p>用于建立主要技术路线与共识性障碍，不替代原始研究中的具体数据。</p><span class="source-chip">全文</span></article><article class="source-card"><span class="verified">● 语义已核验</span><b>临床研究</b><p>提取样本量、终点和适用范围；避免把早期信号写成确定疗效。</p><span class="source-chip">原始研究</span></article><article class="source-card"><span class="verified">● 边界已标记</span><b>注册与官方资料</b><p>核对试验状态和监管信息，和论文证据分别呈现。</p><span class="source-chip">官方来源</span></article></div>`
};
function showPreview(name){$('#preview-body').innerHTML=previews[name];document.querySelectorAll('.preview-tabs button').forEach(button=>button.classList.toggle('active',button.dataset.preview===name));}
showPreview('slides');
document.querySelectorAll('[data-preview]').forEach(button=>button.addEventListener('click',()=>showPreview(button.dataset.preview)));
document.querySelectorAll('[data-example]').forEach(button=>button.addEventListener('click',()=>{task.value=button.dataset.example;task.focus();error.textContent='';}));
function isAmbiguous(value){return /^(苹果|细胞|病毒|衰老|基因|蛋白质)$/.test(value.replace(/[？?。.!\s]/g,''));}
form.addEventListener('submit',event=>{
  event.preventDefault();const value=task.value.trim();
  if(value.length<2){error.textContent='输入一个调研主题就可以开始。';task.focus();return;}
  error.textContent='';const tier=$('input[name="tier"]:checked').value;
  if(isAmbiguous(value)){
    title.textContent=`“${value}”还存在一个会改变调研范围的歧义`;
    copy.textContent=value.includes('苹果')?'你指的是苹果植物/果实，还是 Apple 公司？实际产品中这里只会追问这一个关键问题。':'这个词可以对应多个研究方向。实际产品中会只追问一个能确定范围的问题。';
    $('#confirm').textContent='回答后继续 →';
  }else{
    title.textContent=`将围绕“${value}”建立${tier==='deep'?'深入调研':'快速调研'}框架`;
    copy.textContent=tier==='deep'?'将重点比较主要路线、反证与适用条件，再组织为报告和 PPT 内容包。':'将先梳理基本概念、主要路线、当前进展和局限，再组织为报告和 PPT 内容包。';
    $('#confirm').innerHTML='确认并查看工作规划 <span>→</span>';
  }
  result.hidden=false;result.scrollIntoView({behavior:'smooth',block:'center'});
});
$('#confirm').addEventListener('click',()=>{$('#confirm').disabled=true;$('#confirm').textContent='原型已完成意图确认，真实任务将在后端接入后启动';});
