const byId = id => document.getElementById(id);
const topic = byId('topic');
const flowPanel = byId('flow-panel');
const gatePanel = byId('gate-panel');
let chosenDirection = null;
let isWideTopic = false;
const wideExample = '导电水凝胶在神经电刺激调控中的应用';
const focusedExample = '导电水凝胶在慢性植入神经接口中的应用';

const directions = [
  { title: '慢性植入神经接口', description: '关注长期植入后的界面失效、材料设计与稳定性证据。' },
  { title: '短期神经刺激性能', description: '关注刺激效率、阻抗和电荷注入等短期测试。' },
  { title: '材料与制备路线', description: '关注导电机理、填料选择与加工条件。' }
];

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}

function scopeText() {
  const tier = document.querySelector('input[name="tier"]:checked').value;
  return `拟交付：${tier === 'fast' ? '快速版' : '深入版'}学术调研报告及 PPT 逐页内容包（上屏文字、配图建议与图源、讲稿）。${tier === 'fast' ? '首次免费资格须在邮箱验证后判断。' : '深入版不在首次免费范围内，支付尚未接入。'}`;
}

function showFlow() {
  const value = topic.value.trim();
  if (value.length < 2) { byId('form-error').textContent = '请先输入一个调研主题。'; topic.focus(); return; }
  byId('form-error').textContent = '';
  chosenDirection = null;
  isWideTopic = value === wideExample;
  byId('flow-title').textContent = value;
  byId('flow-description').textContent = isWideTopic
    ? '这是宽题交互样例。请选择你真正想研究的方向，系统不会替你决定。'
    : value === focusedExample
      ? '这是聚焦题交互样例，可直接核对交付范围。'
      : '当前原型未调用真实题目理解服务，不能判断这个题目是否过宽。你仍可查看范围确认与登录闸门的界面。';
  byId('direction-area').hidden = !isWideTopic;
  byId('directions').innerHTML = isWideTopic ? directions.map((item, index) => `<button type="button" class="direction-card" data-direction="${index}" aria-pressed="false"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.description)}</span></button>`).join('') : '';
  byId('scope-summary').textContent = scopeText();
  byId('flow-error').textContent = '';
  gatePanel.hidden = true;
  flowPanel.hidden = false;
  flowPanel.scrollIntoView({behavior:'smooth',block:'center'});
}

byId('begin').addEventListener('click', showFlow);
byId('example-topic').addEventListener('click', () => { topic.value = wideExample; topic.focus(); });
byId('focused-example').addEventListener('click', () => { topic.value = focusedExample; topic.focus(); });
byId('edit-topic').addEventListener('click', () => { flowPanel.hidden = true; gatePanel.hidden = true; topic.focus(); byId('start').scrollIntoView({behavior:'smooth'}); });
byId('directions').addEventListener('click', event => {
  const button = event.target.closest('[data-direction]');
  if (!button) return;
  chosenDirection = directions[Number(button.dataset.direction)];
  byId('flow-error').textContent = '';
  byId('scope-summary').textContent = `已选方向：${chosenDirection.title}。${scopeText()}`;
  document.querySelectorAll('.direction-card').forEach(card => { const selected = card === button; card.classList.toggle('selected', selected); card.setAttribute('aria-pressed', String(selected)); });
});
byId('confirm-scope').addEventListener('click', () => {
  if (isWideTopic && !chosenDirection) { byId('flow-error').textContent = '请先选择一个研究方向。'; byId('directions').querySelector('button')?.focus(); return; }
  byId('gate-summary').textContent = `${chosenDirection?.title || topic.value.trim()} · ${scopeText()}`;
  gatePanel.hidden = false;
  gatePanel.scrollIntoView({behavior:'smooth',block:'center'});
});
byId('back-to-scope').addEventListener('click', () => { gatePanel.hidden = true; flowPanel.scrollIntoView({behavior:'smooth',block:'center'}); });
document.querySelectorAll('input[name="tier"]').forEach(input => input.addEventListener('change', () => {
  byId('scope-summary').textContent = chosenDirection ? `已选方向：${chosenDirection.title}。${scopeText()}` : scopeText();
  if (!gatePanel.hidden) byId('gate-summary').textContent = `${chosenDirection?.title || topic.value.trim()} · ${scopeText()}`;
}));

const statusExamples = {
  working: { title:'正在整理来源', description:'正式版将从服务端读取实际阶段。页面关闭后仍可通过已验证邮箱返回任务页，完成后发送邮件。', action:'当前无需操作，稍后查看任务页。', stage:1 },
  limited: { title:'现有证据不足', description:'可用资料不足以支持原定判断。交付页会指出证据缺口，保留能核对的来源，不把推测写成定论。', action:'查看证据缺口，再决定是否缩小题目范围。' },
  failed: { title:'生成未完成', description:'正式版会显示失败阶段、已保留的检查点和恢复结果。技术失败不消耗已预留的首次免费资格。', action:'查看失败说明或从已完成阶段恢复；不会假装交付成功。' },
  expired: { title:'交付已过期', description:'交付文件保存 7 天，到期前 1 天提醒。过期后不再提供失效下载链接。', action:'需要重新生成时，将先说明资格与费用，不自动发起任务。' }
};
function showStatus(name) {
  const example = statusExamples[name];
  const stages = example.stage == null ? '' : `<ol><li class="done">题目确认</li><li class="current">检索与证据整理</li><li>报告与 PPT 内容</li><li>核验与交付</li></ol>`;
  byId('status-panel').innerHTML = `<h4>${example.title}</h4><p>${example.description}</p>${stages}<span class="state-action">下一步：${example.action}</span>`;
  document.querySelectorAll('[data-status]').forEach(button => {
    const selected = button.dataset.status === name;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
}
document.querySelectorAll('[data-status]').forEach(button => button.addEventListener('click', () => {
  showStatus(button.dataset.status);
}));
showStatus('working');

const reportHtml = `<div class="reader"><div class="reader-nav" aria-label="报告结构示例"><span>报告结构示例</span><a class="active">摘要</a><a>界面失效机制</a><a>材料与电学设计</a><a>长期稳定性</a></div><article class="reader-article"><span class="section-kicker">调研报告 · 节选</span><h4>摘要</h4><p>慢性植入神经接口是脑机接口、深部脑刺激和神经假体的重要技术基础，但现有电极在长期服役中面临信号衰减和通道失效。导电水凝胶因其与神经组织接近的力学顺应性、高含水量和可设计的电学性能，被视为缓解力学失配、改善界面电荷传递的候选材料。</p><p>现有材料表征、体外测试和部分动物研究观察到阻抗或记录表现改善；但所引研究尚不足以说明这些优势能否在长期植入中保持。<a class="citation" href="https://pubmed.ncbi.nlm.nih.gov/39380329/" target="_blank" rel="noopener noreferrer">[4] 原文 ↗</a> <a class="citation" href="https://europepmc.org/article/MED/39145569" target="_blank" rel="noopener noreferrer">[6] 原文 ↗</a></p><h5>本报告回答什么</h5><p>报告沿着界面失效机制、材料设计、实验证据与长期稳定性展开；对短期结果与慢性植入结论分别说明。</p><p class="reading-note">阅读提示：这里展示人工润色验证稿的节选。正式交付中，引用应贴近对应论断，重要限制须留在正文。</p></article></div>`;

const slidePages = [
  { title:'慢性植入神经接口的核心瓶颈：界面失效而非单纯器件老化', bullets:['植入后的异物反应、胶质包裹与电极阻抗变化共同影响信号','力学失配与持续炎症使电极—组织界面逐渐退化'], notes:'开场先界定问题：关注的是植入后的界面如何随时间变化，以及材料为什么可能影响记录和刺激表现。现有证据不能直接推断长期临床可靠性。', figure:'建议自绘界面失效流程示意图；不使用未经许可的论文原图。' },
  { title:'超软电极初步证明力学匹配可减轻炎症组织反应', bullets:['杨氏模量低于 1 MPa 的超软微电极接近脑组织模量','大鼠脑内植入 8 周后，炎症组织反应低于相似尺寸和表面化学的钨丝对照'], notes:'这项动物研究为力学匹配提供组织学证据，但它不是典型导电水凝胶体系。不要把这项结果外推为水凝胶长期功能已经得到证实。', figure:'建议自行绘制超软电极与刚性钨丝的对照示意图。' },
  { title:'长期稳定性评估需要区分材料短期安全与慢性功能保持', bullets:['24 小时细胞测试支持初步短期安全信号','8 周组织学结果与数月功能追踪属于不同证据层级','数月以上的系统追踪仍是关键缺口'], notes:'讲清楚各项研究分别测试了什么：体外细胞、动物组织学和长期电学功能不可互相替代。离体脑实验样本量很小，结论应保留边界。', figure:'建议使用时间轴对照；图源与许可状态需在正式使用前核对。' }
];
let selectedSlide = 0;
function slideHtml() {
  const page = slidePages[selectedSlide];
  return `<div class="slide-layout"><div class="slide-index">${slidePages.map((item,index)=>`<button type="button" data-slide="${index}" class="${index===selectedSlide?'active':''}">${String(index+1).padStart(2,'0')} · ${escapeHtml(item.title.slice(0,9))}…</button>`).join('')}</div><article class="slide-main"><span class="slide-number">第 ${selectedSlide+1} 页 / 内容包节选</span><h4>${escapeHtml(page.title)}</h4><h5>上屏文字</h5><ul>${page.bullets.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul><h5>配图建议</h5><p>${escapeHtml(page.figure)}</p><details open><summary>专业答辩式讲稿</summary><p>${escapeHtml(page.notes)}</p></details></article></div>`;
}

const sourcesHtml = `<div class="source-list"><span class="section-kicker">来源与配图</span><h4>让读者找得到原始依据</h4><p>案例中的原文入口独立呈现。以下图页的复用许可未核实，原型只提供链接，不嵌入图片。</p><div class="source-item"><b>超软微电极的植入对照研究</b><p>用于说明力学匹配与组织反应的初步关系。</p><a href="https://europepmc.org/article/MED/28185910" target="_blank" rel="noopener noreferrer">查看论文原文 ↗</a></div><div class="source-item"><b>PEDOT:PSS/AA 水凝胶电化学数据</b><p>原文 Fig. 4。许可未知，嵌图前需确认。</p><a href="https://europepmc.org/articles/PMC11325676/figure/fig4" target="_blank" rel="noopener noreferrer">查看原文图页 ↗</a></div><div class="source-item"><b>导电水凝胶导电机理分类</b><p>原文 Fig. 1。许可未知，嵌图前需确认。</p><a href="https://europepmc.org/articles/PMC13633225/figure/Fig1" target="_blank" rel="noopener noreferrer">查看原文图页 ↗</a></div></div>`;

function showTab(name) {
  document.querySelectorAll('[data-tab]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.tab===name)));
  byId('delivery-content').innerHTML = name==='report' ? reportHtml : name==='slides' ? slideHtml() : sourcesHtml;
  byId('sample-feedback').textContent = '';
}
document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => showTab(button.dataset.tab)));
document.querySelector('.delivery-tabs').addEventListener('keydown', event => {
  if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
  const buttons = Array.from(document.querySelectorAll('[data-tab]'));
  const current = buttons.findIndex(button => button.getAttribute('aria-selected') === 'true');
  const next = buttons[(current + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length];
  next.focus();
  showTab(next.dataset.tab);
  event.preventDefault();
});
byId('delivery-content').addEventListener('click', event => {
  const button = event.target.closest('[data-slide]');
  if (!button) return;
  selectedSlide = Number(button.dataset.slide);
  showTab('slides');
});
function currentExcerpt() {
  const selected = document.querySelector('[data-tab][aria-selected="true"]').dataset.tab;
  const heading = selected === 'report' ? '调研报告节选' : selected === 'slides' ? `PPT 第 ${selectedSlide + 1} 页节选` : '来源与配图节选';
  const content = byId('delivery-content').innerText.trim();
  const urls = selected === 'sources' ? Array.from(byId('delivery-content').querySelectorAll('.source-item a')).map(link => `${link.textContent.trim()}：${link.href}`).join('\n') : '';
  return `# ${heading}\n\n${content}${urls ? `\n\n${urls}` : ''}\n\n案例经过人工学术润色，仅供界面审查。\n`;
}
byId('copy-excerpt').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(currentExcerpt());
    byId('sample-feedback').textContent = '当前节选已复制。';
  } catch (_) {
    byId('sample-feedback').textContent = '浏览器未允许复制，请选中文本后手动复制。';
  }
});
byId('download-excerpt').addEventListener('click', () => {
  const blob = new Blob([currentExcerpt()], {type:'text/markdown;charset=utf-8'});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = '调研交付台-案例节选.md';
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  byId('sample-feedback').textContent = '已下载当前节选；这不是完整交付文件。';
});
showTab('report');
