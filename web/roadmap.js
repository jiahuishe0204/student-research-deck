const data = window.ROADMAP_DATA;
const stageRoot = document.querySelector('#roadmap-stages');
const filters = document.querySelector('#stage-filters');

const statusText = { done: '已完成', active: '进行中', next: '下一步', planned: '已规划', decision: '待决策' };

function render(filter = 'all') {
  const stages = filter === 'all' ? data.stages : data.stages.filter(stage => stage.id === filter);
  stageRoot.innerHTML = stages.map(stage => `
    <article class="roadmap-stage ${stage.status}" id="${stage.id}">
      <header><span>${stage.id}</span><div><p>${statusText[stage.status]}</p><h2>${stage.title}</h2></div></header>
      <div class="stage-summary">
        <p><b>目的</b>${stage.purpose}</p>
        <p><b>产物</b>${stage.output}</p>
        <p><b>决策方式</b>${stage.decision}</p>
      </div>
      <div class="path-grid">
        ${stage.paths.map(path => `<section class="path-card ${path.verdict.includes('采用') && !path.verdict.includes('不') ? 'recommended' : ''}"><div><h3>${path.name}</h3><span>${path.verdict}</span></div><p><b>优点</b>${path.pros}</p><p><b>缺点</b>${path.cons}</p></section>`).join('')}
      </div>
      <footer><b>完成判据</b>${stage.doneWhen}</footer>
    </article>
  `).join('');
}

data.stages.forEach(stage => {
  const button = document.createElement('button');
  button.type = 'button';
  button.dataset.stage = stage.id;
  button.textContent = stage.id;
  filters.appendChild(button);
});

filters.addEventListener('click', event => {
  const button = event.target.closest('button');
  if (!button) return;
  filters.querySelectorAll('button').forEach(item => item.classList.toggle('active', item === button));
  render(button.dataset.stage);
});

document.querySelector('#updated-at').textContent = data.updatedAt;
document.querySelector('#current-stage').textContent = data.currentStage;
render();
