const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const script = fs.readFileSync('static/js/quiz-result.js', 'utf8');
function setup(values) {
  const cards = values.map(value => ({dataset: {resultCorrect: value}, hidden: false}));
  const buttons = ['all','missed'].map(mode => ({dataset: {resultFilter:mode}, attrs:{}, addEventListener(_,fn){this.click=fn;},setAttribute(k,v){this.attrs[k]=v;}}));
  const toolbar = {hidden:true}, status = {textContent:''};
  const review = {querySelector:s=>s==='[data-result-filters]'?toolbar:status,querySelectorAll:s=>s==='[data-result-card]'?cards:buttons};
  vm.runInNewContext(script,{document:{querySelector:()=>review}});
  return {cards,buttons,toolbar,status};
}
test('review filter shows only mistakes and can restore every answer',()=>{
  const s=setup(['true','false','true']);
  s.buttons[1].click();
  assert.deepEqual(s.cards.map(c=>c.hidden),[true,false,true]);
  assert.equal(s.buttons[1].attrs['aria-pressed'],'true');
  assert.match(s.status.textContent,/1 từ cần ôn/);
  s.buttons[0].click();
  assert.ok(s.cards.every(c=>!c.hidden));
  assert.equal(s.buttons[1].attrs['aria-pressed'],'false');
});
test('perfect result provides an explanation instead of an unexplained empty list',()=>{
  const s=setup(['true']);s.buttons[1].click();
  assert.match(s.status.textContent,/Không có câu sai/);
  s.buttons[0].click();assert.equal(s.cards[0].hidden,false);
});
