const test=require('node:test'), assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const script=fs.readFileSync('static/js/companion.js','utf8');
function setup({stored='false',blocked=false}={}){
 const toggle={hidden:true,attrs:{},setAttribute(k,v){this.attrs[k]=v;},addEventListener(_,fn){this.click=fn;}};
 const message={textContent:''};
 const greet={classList:{remove(){},add(){}},addEventListener(_,fn){this.click=fn;}};
 const classes=new Set();
 const companion={classList:{toggle(k,on){if(on)classes.add(k);else classes.delete(k);}},querySelector(s){return {'[data-lumi-toggle]':toggle,'[data-lumi-greet]':greet,'[data-lumi-message]':message}[s];}};
 let saved;
 vm.runInNewContext(script,{window:{matchMedia:()=>({matches:false}),localStorage:{getItem(){if(blocked)throw Error();return stored;},setItem(_,v){if(blocked)throw Error();saved=v;}}},document:{querySelectorAll:s=>s==='[data-lumi]'?[companion]:[]}});
 return {toggle,greet,message,classes,get saved(){return saved;}};
}
test('Lumi collapse is reversible and restores a saved preference',()=>{
 const s=setup({stored:'true'});assert.ok(s.classes.has('is-collapsed'));assert.equal(s.toggle.attrs['aria-expanded'],'false');s.toggle.click();assert.ok(!s.classes.has('is-collapsed'));assert.equal(s.saved,'false');s.toggle.click();assert.equal(s.saved,'true');
});
test('blocked browser storage does not break collapse or greetings',()=>{
 const s=setup({blocked:true});s.toggle.click();assert.ok(s.classes.has('is-collapsed'));s.toggle.click();s.greet.click();assert.match(s.message.textContent,/Một từ mới/);
});
