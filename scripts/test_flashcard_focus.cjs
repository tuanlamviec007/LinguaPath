const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('flipping reads the meaning first and returns focus to the front control', async () => {
  const listeners = new Map();
  const document = {activeElement:null, addEventListener(type, fn){listeners.set(type,fn);}, querySelectorAll(){return [];}};
  const node = () => ({attrs:{},setAttribute(k,v){this.attrs[k]=v;},focus(){document.activeElement=this;}});
  const heading=node(), frontButton=node(), backButton=node(), front=node(), back=node();
  let flipped=false;
  const card={classList:{contains(){return flipped;},toggle(name,value){flipped=value;}},
    querySelector(selector){return selector==='.flash-front'?front:back;},querySelectorAll(){return [frontButton,backButton];}};
  front.querySelector=()=>frontButton;
  back.querySelector=(selector)=>selector==='[data-flashcard-meaning]'?heading:backButton;
  for(const button of [frontButton,backButton]) button.closest=(selector)=>selector==='[data-flip]'?button:card;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/js/app.js'),'utf8'),{
    document,window:{addEventListener(){}},setTimeout,clearTimeout,HTMLAudioElement:class {},
  });
  await listeners.get('click')({target:frontButton});
  assert.equal(document.activeElement,heading);
  assert.equal(front.inert,true);assert.equal(back.inert,false);
  assert.equal(frontButton.attrs['aria-expanded'],'true');
  await listeners.get('click')({target:backButton});
  assert.equal(document.activeElement,frontButton);
  assert.equal(front.inert,false);assert.equal(back.inert,true);
});
