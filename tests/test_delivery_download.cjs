const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../web/delivery.js'), 'utf8');
const start = source.indexOf('function artifactInfo(');
const end = source.indexOf('function setDownloadMenu(', start);
assert.ok(start >= 0 && end > start);
let saved;
const sandbox = {
  state: { report: '# 测试主题', slides: '完整 PPT', reportSections: [1], slidePages: [], topic: '', production: false },
  URL: { createObjectURL(blob) { saved = { body: blob.parts.join('') }; return 'blob:test'; }, revokeObjectURL() {} },
  Blob: class { constructor(parts) { this.parts = parts; } },
  document: { body: { append() {} }, createElement() { return { click() { saved.filename = this.download; }, remove() {} }; } },
  byId() { return {}; }, setTimeout() {}, escapeHtml: String,
};
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end), sandbox);
vm.runInContext("completeArtifactHtml = kind => '完整内容:' + kind", sandbox);
vm.runInContext("downloadArtifact('report', 'html')", sandbox);
assert.equal(saved.body, '完整内容:report');
assert.equal(saved.filename, '测试主题-调研报告.html');
vm.runInContext("downloadArtifact('slides', 'html')", sandbox);
assert.equal(saved.body, '完整内容:slides');
assert.equal(saved.filename, '测试主题-PPT内容包.html');
