const byId = id => document.getElementById(id);
const SAMPLE_FILES = { report: './sample-delivery/report.md', slides: './sample-delivery/ppt-content.md' };
const state = { report: '', slides: '', reportSections: [], slidePages: [], sources: [], view: 'report', selectedSlide: 0, sourceFilter: '全部', taskId: '', topic: '', artifacts: [], production: false };
const VIEW_ORDER = ['report', 'slides', 'sources'];
let viewTransitionId = 0;

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}
function safeUrl(value) {
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol)) return '';
    url.hash = '';
    if (url.pathname !== '/') url.pathname = url.pathname.replace(/\/$/, '');
    return url.href;
  } catch (_) { return ''; }
}
function slugify(value, index) {
  return `section-${index}-${Array.from(value).slice(0, 12).map(char => char.codePointAt(0).toString(36)).join('-')}`;
}
function inlineMarkdown(value) {
  let output = escapeHtml(value);
  output = output.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => {
    const href = safeUrl(url);
    return href ? `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${label} ↗</a>` : label;
  });
  return output.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
}
function renderMarkdown(markdown) {
  const html = []; let paragraph = []; let listType = ''; let headingIndex = 0;
  const flushParagraph = () => { if (paragraph.length) html.push(`<p>${inlineMarkdown(paragraph.join(' '))}</p>`); paragraph = []; };
  const closeList = () => { if (listType) html.push(`</${listType}>`); listType = ''; };
  markdown.replace(/\r/g, '').split('\n').forEach(line => {
    const heading = line.match(/^(#{1,3})\s+(.+)$/); const bullet = line.match(/^\s*[-*]\s+(.+)$/); const numbered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (heading) {
      flushParagraph(); closeList(); headingIndex += 1;
      const level = heading[1].length; html.push(`<h${level} id="${slugify(heading[2], headingIndex)}">${inlineMarkdown(heading[2])}</h${level}>`);
    } else if (bullet || numbered) {
      flushParagraph(); const wanted = bullet ? 'ul' : 'ol';
      if (listType !== wanted) { closeList(); html.push(`<${wanted}>`); listType = wanted; }
      html.push(`<li>${inlineMarkdown((bullet || numbered)[1])}</li>`);
    } else if (!line.trim()) { flushParagraph(); closeList(); } else { paragraph.push(line.trim()); }
  });
  flushParagraph(); closeList(); return html.join('');
}
function parseHeadings(markdown) {
  let index = 0;
  return markdown.split('\n').flatMap(line => { const match = line.match(/^(#{1,2})\s+(.+)$/); if (!match) return []; index += 1; return [{ level: match[1].length, title: match[2], id: slugify(match[2], index) }]; });
}
function parseSlides(markdown) {
  const matches = Array.from(markdown.matchAll(/^##\s+第\s*(\d+)\s*页[｜|]\s*(.+)$/gm));
  return matches.map((match, index) => {
    const body = markdown.slice(match.index + match[0].length, index + 1 < matches.length ? matches[index + 1].index : markdown.length).trim();
    const blocks = {}; const labels = Array.from(body.matchAll(/^(?:\*\*)?(目录标题|副标题|上屏文字|配图建议|原文图入口|参考来源|讲稿|来源|页目的)(?:\*\*)?：?([^\n]*)$/gm));
    labels.forEach((label, labelIndex) => {
      const remainder = label[2].trim();
      const following = body.slice(label.index + label[0].length, labelIndex + 1 < labels.length ? labels[labelIndex + 1].index : body.length).trim();
      const key = label[1] === '页目的' ? '副标题' : label[1] === '原文图入口' ? '配图建议' : label[1] === '参考来源' ? '来源' : label[1];
      blocks[key] = [remainder, following].filter(Boolean).join('\n\n');
    });
    const navigationTitle = body.match(/^目录标题：\s*(.+)$/m)?.[1]?.trim() || match[2].trim();
    return { number: Number(match[1]), title: blocks['副标题'] || match[2].trim(), navigationTitle, raw: `${match[0]}\n\n${body}\n`, blocks };
  });
}
function pptToMarkdown(ppt) {
  return (ppt?.pages || []).map((page, index) => {
    const lines = [`## 第 ${index + 1} 页｜${page.title || page.navigation_title || `页面 ${index + 1}`}`];
    if (page.navigation_title) lines.push(`目录标题：${page.navigation_title}`);
    lines.push('', '上屏文字：', ...(page.on_slide_text || []).map(item => `- ${item}`));
    lines.push('', '配图建议：', page.visual_suggestion || '无');
    lines.push('', '讲稿：', page.speaker_notes || '');
    const citations = (page.source_citations || []).map(item => {
      const label = item.short_vancouver || item.source_id || '来源';
      return item.url ? `- [${label}](${item.url})` : `- ${label}`;
    });
    lines.push('', '来源：', ...(citations.length ? citations : ['- 见参考文献交付文件']));
    return lines.join('\n');
  }).join('\n\n');
}
function artifact(kind) { return state.artifacts.find(item => item.kind === kind); }
async function requestPrivateDownload(kind, filename) {
  const item = artifact(kind); const csrf = sessionStorage.getItem('research_csrf_token') || '';
  if (!item || !csrf) throw new Error('登录状态或下载凭证已过期，请重新通过邮箱进入任务页');
  const response = await fetch('/delivery/download', { method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify({ task_id: state.taskId, artifact_id: item.artifact_id, filename }) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.download_url) throw new Error(payload.message || '下载链接生成失败');
  location.assign(payload.download_url);
}
function extractSources(report, slides) {
  const found = new Map(); const referenceNames = new Map();
  report.split('\n').forEach(line => {
    const reference = line.match(/^\[\d+\]\s+(.+?)\s+(https?:\/\/\S+)$/);
    if (reference) referenceNames.set(safeUrl(reference[2]), reference[1]);
  });
  for (const match of `${report}\n${slides}`.matchAll(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g)) {
    const url = safeUrl(match[2]); if (!url || found.has(url)) continue;
    const isFigure = url.includes('/figure/');
    const figureId = decodeURIComponent(new URL(url).pathname.split('/').filter(Boolean).pop() || '原文图页');
    const genericLabel = /^\d+$/.test(match[1]) || match[1] === '原文' || match[1] === '查看原文图页';
    const label = referenceNames.get(url) || (isFigure && genericLabel ? `原文图页 · ${figureId}` : match[1]);
    found.set(url, { label, url, kind: isFigure ? '图源' : '论文来源' });
  }
  return Array.from(found.values());
}
function setIndex(items, activeIndex, onSelect) {
  const index = byId('content-index');
  const existingButtons = Array.from(index.querySelectorAll('button'));
  const canReuse = existingButtons.length === items.length && existingButtons.every((button, itemIndex) => button.textContent === items[itemIndex].title);
  if (canReuse) {
    updateIndexIndicator(activeIndex);
    return;
  }
  index.innerHTML = `<span class="index-label">${state.view === 'slides' ? '页面目录' : state.view === 'sources' ? '来源筛选' : '报告目录'}</span><span class="index-active-indicator" aria-hidden="true"></span>`;
  items.forEach((item, itemIndex) => { const button = document.createElement('button'); button.type = 'button'; button.className = itemIndex === activeIndex ? 'active' : ''; button.textContent = item.title; button.addEventListener('click', () => onSelect(item, itemIndex)); index.append(button); });
  requestAnimationFrame(() => updateIndexIndicator(activeIndex));
}
function updateIndexIndicator(activeIndex) {
  const index = byId('content-index'); const buttons = Array.from(index.querySelectorAll('button')); const indicator = index.querySelector('.index-active-indicator');
  buttons.forEach((button, itemIndex) => button.classList.toggle('active', itemIndex === activeIndex));
  const button = buttons[activeIndex];
  if (!button || !indicator) { if (indicator) indicator.classList.remove('visible'); return; }
  indicator.classList.add('visible');
  indicator.style.setProperty('--index-x', `${button.offsetLeft}px`);
  indicator.style.setProperty('--index-y', `${button.offsetTop}px`);
  indicator.style.setProperty('--index-width', `${button.offsetWidth}px`);
  indicator.style.setProperty('--index-height', `${button.offsetHeight}px`);
}
function animateIndexedContent(render, direction) {
  const panel = byId('content-panel');
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || typeof panel.animate !== 'function') { render(); return; }
  const outgoing = panel.animate([{ opacity: 1, transform: 'translateY(0)' }, { opacity: 0, transform: `translateY(${-direction * 12}px)` }], { duration: 140, easing: 'cubic-bezier(.55, 0, 1, .45)', fill: 'forwards' });
  outgoing.finished.then(() => {
    render();
    panel.animate([{ opacity: 0, transform: `translateY(${direction * 14}px)` }, { opacity: 1, transform: 'translateY(0)' }], { duration: 300, easing: 'cubic-bezier(0, .55, .45, 1)', fill: 'both' });
  }).catch(() => render());
}
function showReport() {
  setIndex(state.reportSections, -1, (item, itemIndex) => { updateIndexIndicator(itemIndex); document.getElementById(item.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); });
  byId('content-panel').innerHTML = `<div class="report-document">${renderMarkdown(state.report)}</div>`;
  byId('content-panel').querySelectorAll('h1,h2').forEach((heading, index) => { heading.id = state.reportSections[index]?.id || heading.id; });
  byId('content-panel').querySelectorAll('p').forEach(paragraph => { if (/^\[\d+\]/.test(paragraph.textContent.trim())) paragraph.classList.add('reference-line'); });
}
function renderSlideBlock(title, markdown, className = '') { return markdown ? `<section class="slide-block ${className}"><h2>${escapeHtml(title)}</h2>${renderMarkdown(markdown)}</section>` : ''; }
function renderFigureBlock(markdown) {
  if (!markdown || !/https:\/\/[^\s)]+/i.test(markdown)) return '';
  return renderSlideBlock('配图建议与图源', markdown);
}
function showSlide(index) {
  state.selectedSlide = index; const page = state.slidePages[index];
  setIndex(state.slidePages.map(item => ({ title: `${String(item.number).padStart(2, '0')} · ${item.navigationTitle}` })), index, (_, nextIndex) => {
    if (nextIndex === state.selectedSlide) return;
    const direction = nextIndex > state.selectedSlide ? 1 : -1;
    updateIndexIndicator(nextIndex); animateIndexedContent(() => showSlide(nextIndex), direction);
  });
  byId('content-panel').innerHTML = `<div class="slide-document"><div class="slide-topline"><span class="slide-counter">第 ${page.number} 页 / 共 ${state.slidePages.length} 页</span><button type="button" class="slide-copy">复制本页</button></div><h1>${escapeHtml(page.navigationTitle)}</h1><p class="slide-subtitle">${escapeHtml(page.title)}</p>${renderSlideBlock('上屏文字', page.blocks['上屏文字'])}${renderFigureBlock(page.blocks['配图建议'])}${renderSlideBlock('专业答辩式讲稿', page.blocks['讲稿'], 'speaker-notes')}${renderSlideBlock('参考来源', page.blocks['来源'])}</div>`;
  byId('content-panel').querySelector('.slide-copy').addEventListener('click', () => copyText(page.raw, '本页内容已复制。'));
  byId('content-panel').querySelectorAll('p').forEach(paragraph => { if (paragraph.textContent.includes('复用许可') || paragraph.textContent.includes('reuse_status')) paragraph.insertAdjacentHTML('afterbegin', '<span class="figure-warning">许可需核对</span> '); });
  byId('content-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function showSources(filter = '全部') {
  state.sourceFilter = filter;
  const filterNames = ['全部', '论文来源', '图源']; const filters = filterNames.map(title => ({ title })); setIndex(filters, filterNames.indexOf(filter), (item, nextIndex) => {
    if (item.title === state.sourceFilter) return;
    const direction = nextIndex > filterNames.indexOf(state.sourceFilter) ? 1 : -1;
    updateIndexIndicator(nextIndex); animateIndexedContent(() => showSources(item.title), direction);
  });
  const sources = filter === '全部' ? state.sources : state.sources.filter(item => item.kind === filter);
  byId('content-panel').innerHTML = `<div class="source-grid"><div class="source-summary"><h1>引用与图源</h1><p>共整理 ${state.sources.length} 个不重复原文入口。图源许可未知时仅打开原文页，不在此处嵌入或暗示可复用。</p></div>${sources.map((source, index) => `<article class="source-card"><div class="source-card-top"><h2>${escapeHtml(source.label || `原文入口 ${index + 1}`)}</h2><span class="source-kind">${source.kind}</span></div><p>${escapeHtml(new URL(source.url).hostname)} · 新窗口打开原始页面</p><a href="${escapeHtml(source.url)}" target="_blank" rel="noopener noreferrer">查看原文 ↗</a></article>`).join('')}</div>`;
}
function showView(view) {
  state.view = view; document.querySelectorAll('[data-view]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.view === view))); byId('action-feedback').textContent = '';
  if (view === 'report') showReport(); else if (view === 'slides') showSlide(state.selectedSlide); else showSources();
  updateTabIndicator(view);
}
function updateTabIndicator(view = state.view) {
  const tabs = document.querySelector('.delivery-view-tabs');
  const button = tabs.querySelector(`[data-view="${view}"]`);
  const indicator = tabs.querySelector('.view-tab-indicator');
  if (!button || !indicator) return;
  indicator.style.setProperty('--indicator-left', `${button.offsetLeft}px`);
  indicator.style.setProperty('--indicator-width', `${button.offsetWidth}px`);
}
async function changeView(view) {
  if (view === state.view) return;
  const transitionId = ++viewTransitionId;
  const direction = VIEW_ORDER.indexOf(view) > VIEW_ORDER.indexOf(state.view) ? 1 : -1;
  const body = byId('delivery-body');
  document.querySelectorAll('[data-view]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.view === view)));
  updateTabIndicator(view);
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || typeof body.animate !== 'function') {
    showView(view);
    return;
  }
  try {
    await body.animate(
      [{ opacity: 1, transform: 'translateX(0)' }, { opacity: 0, transform: `translateX(${-direction * 22}px)` }],
      { duration: 150, easing: 'cubic-bezier(.55, 0, 1, .45)', fill: 'forwards' }
    ).finished;
  } catch (_) { /* A newer tab choice can cancel this animation. */ }
  if (transitionId !== viewTransitionId) return;
  showView(view);
  body.animate(
    [{ opacity: 0, transform: `translateX(${direction * 22}px)` }, { opacity: 1, transform: 'translateX(0)' }],
    { duration: 300, easing: 'cubic-bezier(0, .55, .45, 1)', fill: 'both' }
  );
}
function currentMarkdown() {
  if (state.view === 'report') return state.report;
  if (state.view === 'slides') return state.slidePages[state.selectedSlide].raw;
  return `# 引用与图源\n\n${state.sources.map(source => `- ${source.kind}｜${source.label}：${source.url}`).join('\n')}\n`;
}
function artifactInfo(kind) {
  const topic = (state.report.match(/^#\s+(.+)$/m) || [])[1] || state.topic || '调研主题';
  const safeTopic = topic.replace(/[\\/:*?"<>|]/g, '-').trim();
  return { content: kind === 'report' ? state.report : state.slides, title: `${safeTopic}-${kind === 'report' ? '调研报告' : 'PPT内容包'}` };
}
function completeArtifactHtml(kind) {
  const artifact = artifactInfo(kind);
  const body = kind === 'report'
    ? `<div class="report-document">${renderMarkdown(state.report)}</div>`
    : `<div class="slide-package">${state.slidePages.map(page => `<article class="slide-document"><div class="slide-topline"><span class="slide-counter">第 ${page.number} 页 / 共 ${state.slidePages.length} 页</span></div><h1>${escapeHtml(page.navigationTitle)}</h1><p class="slide-subtitle">${escapeHtml(page.title)}</p>${renderSlideBlock('上屏文字', page.blocks['上屏文字'])}${renderFigureBlock(page.blocks['配图建议'])}${renderSlideBlock('专业答辩式讲稿', page.blocks['讲稿'], 'speaker-notes')}${renderSlideBlock('参考来源', page.blocks['来源'])}</article>`).join('')}</div>`;
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(artifact.title)}</title>
<style>
@page{size:A4;margin:18mm 17mm}*{box-sizing:border-box}body{margin:0;color:#2f3041;background:#fff;font-family:"Microsoft YaHei","PingFang SC",Arial,sans-serif;line-height:1.8}.document{max-width:850px;margin:0 auto;padding:36px 42px}.report-document,.slide-document{max-width:none}.report-document h1,.slide-document h1{font-family:"SimSun","Songti SC",serif;font-size:26px;line-height:1.45;margin:34px 0 15px}.report-document h1:first-child{margin-top:0}.report-document h2,.slide-block h2{margin:27px 0 10px}.report-document p,.report-document li,.slide-block p,.slide-block li{font-size:14px;line-height:1.9}.report-document a,.slide-block a{color:#514397}.speaker-notes{margin-top:20px;padding:16px 18px;border-left:3px solid #a89ad2;background:#f5f3fa}.slide-topline{margin-bottom:8px}.slide-counter{font-size:11px;color:#6658b5}.slide-document{padding-bottom:22px;margin-bottom:30px;border-bottom:1px solid #e6e2e9;break-after:page}.slide-document:last-child{break-after:auto}.slide-subtitle{font-size:17px;font-weight:600;color:#565267}.slide-block{break-inside:avoid}@media(max-width:650px){.document{padding:24px 20px}}@media print{.document{padding:0}a{color:#2f3041;text-decoration:none}}
</style></head><body><main class="document"><div class="notice">完整交付文件 · 共 ${kind === 'report' ? state.reportSections.length + ' 个报告章节' : state.slidePages.length + ' 页 PPT 内容'}。</div>${body}<div class="footer">调研交付台 · 完整交付文件</div></main></body></html>`;
}
function downloadHtml(kind) {
  const artifact = artifactInfo(kind); const filename = `${artifact.title}.html`;
  const url = URL.createObjectURL(new Blob([completeArtifactHtml(kind)], { type: 'text/html;charset=utf-8' }));
  const link = document.createElement('a'); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000); byId('action-feedback').textContent = `已下载 ${filename}，可作为完整网页文件在浏览器直接打开。`;
}
function printArtifactAsPdf(kind) {
  const artifact = artifactInfo(kind); const printWindow = window.open('', '_blank');
  if (!printWindow) { byId('action-feedback').textContent = '浏览器阻止了打印窗口，请允许弹出窗口后重试。'; return; }
  printWindow.opener = null; printWindow.document.open(); printWindow.document.write(completeArtifactHtml(kind)); printWindow.document.close();
  printWindow.document.title = artifact.title;
  setTimeout(() => { printWindow.focus(); printWindow.print(); }, 250);
  byId('action-feedback').textContent = `已打开完整${kind === 'report' ? '调研报告' : 'PPT 内容包'}打印窗口；请选择“另存为 PDF”。`;
}
function downloadArtifact(kind, format) {
  const artifact = artifactInfo(kind);
  if (format === 'markdown' && state.production) {
    requestPrivateDownload(kind === 'report' ? 'report' : 'ppt_content', `${artifact.title}.md`)
      .catch(error => { byId('action-feedback').textContent = error.message; });
  } else if (format === 'markdown') downloadText(artifact.content, `${artifact.title}.md`);
  else if (format === 'html') downloadHtml(kind);
  else printArtifactAsPdf(kind);
}
function currentFilename() {
  const prefix = state.production ? (state.topic || state.taskId) : '慢性植入神经接口';
  if (state.view === 'report') return `${prefix}-调研报告.md`;
  if (state.view === 'slides') return `${prefix}-PPT-第${state.slidePages[state.selectedSlide].number}页.md`;
  return `${prefix}-引用与图源.md`;
}
function currentBaseFilename() {
  return currentFilename().replace(/\.md$/, '');
}
function currentStandaloneHtml() {
  const content = byId('content-panel').cloneNode(true);
  content.querySelectorAll('button').forEach(button => button.remove());
  content.querySelectorAll('a').forEach(link => {
    link.setAttribute('target', '_blank');
    link.setAttribute('rel', 'noopener noreferrer');
  });
  const title = currentBaseFilename();
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>
@page{size:A4;margin:18mm 17mm}*{box-sizing:border-box}body{margin:0;color:#2f3041;background:#fff;font-family:"Microsoft YaHei","PingFang SC",Arial,sans-serif;line-height:1.8}.document{max-width:850px;margin:0 auto;padding:36px 42px}.notice{margin-bottom:28px;padding:12px 15px;border-left:3px solid #6b5ab6;background:#f3f1fa;color:#615d6d;font-size:12px}.content-panel{padding:0}.report-document,.slide-document,.source-grid{max-width:none}.report-document h1,.slide-document h1,.source-summary h1{font-family:"SimSun","Songti SC",serif;font-size:26px;line-height:1.45;margin:34px 0 15px}.report-document h1:first-child{margin-top:0}.report-document h2,.slide-block h2{margin:27px 0 10px}.report-document p,.report-document li,.slide-block p,.slide-block li{font-size:14px;line-height:1.9}.report-document a,.source-card a{color:#514397}.speaker-notes{margin-top:20px;padding:16px 18px;border-left:3px solid #a89ad2;background:#f5f3fa}.slide-topline{margin-bottom:16px}.slide-counter,.source-kind{font-size:11px;color:#6658b5}.slide-copy{display:none}.source-card{padding:17px 0;border-top:1px solid #e6e2e9}.source-card h2{font-size:14px}.source-card p,.source-card a{font-size:12px}.footer{margin-top:34px;padding-top:14px;border-top:1px solid #e6e2e9;color:#77727f;font-size:10px}@media(max-width:650px){.document{padding:24px 20px}}@media print{.document{padding:0}.notice{break-inside:avoid}a{color:#2f3041;text-decoration:none}.source-card,.slide-block{break-inside:avoid}.footer{position:running(footer)}}
</style></head><body><main class="document"><div class="notice">本地真实内容样本，经过人工学术润色；不是线上生成结果。图源许可未知时仅提供原文入口。</div>${content.innerHTML}<div class="footer">调研交付台 · 本地样本 · 正式服务尚未开放</div></main></body></html>`;
}
async function copyText(text, successMessage = '当前内容已复制。') {
  try { await navigator.clipboard.writeText(text); byId('action-feedback').textContent = successMessage; } catch (_) { byId('action-feedback').textContent = '浏览器未允许自动复制，请选中文本后手动复制。'; }
}
function downloadText(text, filename) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' })); const link = document.createElement('a');
  link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); byId('action-feedback').textContent = `已下载 ${filename}`;
}
function downloadHtml() {
  const filename = `${currentBaseFilename()}.html`;
  const url = URL.createObjectURL(new Blob([currentStandaloneHtml()], { type: 'text/html;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  byId('action-feedback').textContent = `已下载 ${filename}，可在 Windows 浏览器直接打开。`;
}
function printCurrentAsPdf() {
  const printWindow = window.open('', '_blank');
  if (!printWindow) {
    byId('action-feedback').textContent = '浏览器阻止了打印窗口，请允许弹出窗口后重试。';
    return;
  }
  printWindow.opener = null;
  printWindow.document.open();
  printWindow.document.write(currentStandaloneHtml());
  printWindow.document.close();
  printWindow.document.title = currentBaseFilename();
  setTimeout(() => { printWindow.focus(); printWindow.print(); }, 250);
  byId('action-feedback').textContent = '已打开打印窗口；请选择“另存为 PDF”或“Microsoft Print to PDF”。';
}
function setDownloadMenu(open, focusFirst = false) {
  byId('download-options').hidden = !open;
  byId('download-trigger').setAttribute('aria-expanded', String(open));
  if (open && focusFirst) byId('download-options').querySelector('[role="menuitem"]')?.focus();
}
async function loadDelivery() {
  byId('load-error').hidden = true; byId('loading-state').hidden = false; byId('delivery-body').hidden = true; document.querySelector('.delivery-app').setAttribute('aria-busy', 'true');
  try {
    const taskId = new URL(location.href).searchParams.get('task') || '';
    if (taskId) {
      if (!/^TASK-[A-Za-z0-9_-]{6,64}$/.test(taskId)) throw new Error('invalid task id');
      const response = await fetch(`/tasks/${encodeURIComponent(taskId)}/delivery`, { credentials: 'include', cache: 'no-store' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.data?.final_delivery) throw new Error(payload.message || 'delivery unavailable');
      const delivery = payload.data; const final = delivery.final_delivery;
      state.taskId = taskId; state.topic = delivery.topic || ''; state.production = true; state.artifacts = delivery.artifacts || [];
      state.report = final.final_report?.markdown || '';
      state.slides = pptToMarkdown(final.final_ppt || {});
      document.querySelector('.result-heading h1').textContent = delivery.topic || final.final_report?.title || '调研交付';
      document.title = `${delivery.topic || '调研交付'}｜调研交付台`;
      const account = document.querySelector('.header-action');
      if (account) { account.textContent = '已验证邮箱'; account.classList.remove('login-pending'); account.removeAttribute('aria-disabled'); account.removeAttribute('title'); }
      document.querySelector('.boundary-note h2').textContent = '内容已完成，引用边界仍需核对。';
      document.querySelector('.boundary-note p').textContent = '本页读取当前账户的私有交付结果。报告与 PPT 使用同一套核验证据；正式提交课程或比赛前，仍应复核原文与图片许可。';
      const footerCopy = document.querySelector('footer p');
      if (footerCopy) footerCopy.textContent = '私有交付阅读页 · 文件保留七天';
    } else if (window.DELIVERY_SAMPLE?.report && window.DELIVERY_SAMPLE?.slides) {
      state.report = window.DELIVERY_SAMPLE.report;
      state.slides = window.DELIVERY_SAMPLE.slides;
    } else {
      const responses = await Promise.all(Object.values(SAMPLE_FILES).map(path => fetch(path, { cache: 'no-store' })));
      if (responses.some(response => !response.ok)) throw new Error('sample not found');
      [state.report, state.slides] = await Promise.all(responses.map(response => response.text()));
    }
    state.reportSections = parseHeadings(state.report); state.slidePages = parseSlides(state.slides); state.sources = extractSources(state.report, state.slides);
    if (!state.reportSections.length || !state.slidePages.length) throw new Error('sample format invalid');
    byId('loading-state').hidden = true; byId('delivery-body').hidden = false; document.querySelector('.delivery-app').setAttribute('aria-busy', 'false'); showView('report');
  } catch (_) { byId('loading-state').hidden = true; byId('load-error').hidden = false; document.querySelector('.delivery-app').setAttribute('aria-busy', 'false'); }
}
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => changeView(button.dataset.view)));
document.querySelector('.delivery-view-tabs').addEventListener('keydown', event => { if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return; const buttons = Array.from(document.querySelectorAll('[data-view]')); const current = buttons.findIndex(button => button.getAttribute('aria-selected') === 'true'); const next = buttons[(current + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length]; next.focus(); changeView(next.dataset.view); event.preventDefault(); });
window.addEventListener('resize', () => updateTabIndicator());
byId('copy-current').addEventListener('click', () => copyText(currentMarkdown()));
byId('download-trigger').addEventListener('click', () => setDownloadMenu(byId('download-options').hidden, true));
byId('download-options').addEventListener('click', event => {
  const option = event.target.closest('[data-kind][data-format]');
  if (!option) return;
  setDownloadMenu(false);
  downloadArtifact(option.dataset.kind, option.dataset.format);
});
byId('download-options').addEventListener('keydown', event => {
  const items = Array.from(byId('download-options').querySelectorAll('[role="menuitem"]'));
  const current = items.indexOf(document.activeElement);
  if (event.key === 'Escape') { setDownloadMenu(false); byId('download-trigger').focus(); event.preventDefault(); }
  if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
    items[(current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
    event.preventDefault();
  }
});
document.addEventListener('click', event => { if (!event.target.closest('.download-menu')) setDownloadMenu(false); });
byId('retry-load').addEventListener('click', loadDelivery);
loadDelivery();
