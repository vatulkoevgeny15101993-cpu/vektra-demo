// Behavioral tests for the public conversion flow using the real HTML IDs and JS.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.hidden=false;this.value='';this.textContent='';this.disabled=false;this.handlers={};this.dataset={}; }
  addEventListener(type,fn){this.handlers[type]=fn;}
  focus(){} scrollIntoView(){} select(){this.selected=true;}
  async emit(type,event={}){return this.handlers[type]({preventDefault(){},target:this,...event});}
}
(async()=>{
 const html=fs.readFileSync('index.html','utf8');
 const elements=Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
 const demo=[0,1,2].map(n=>Object.assign(new Element(),{dataset:{demo:String(n)}}));
 const plans=['Starter','Professional','Enterprise'].map(plan=>Object.assign(new Element(),{dataset:{plan}}));
 const document={getElementById:id=>{assert.ok(elements[id],`Missing HTML element ${id}`);return elements[id];},querySelectorAll:q=>q==='[data-demo]'?demo:plans};
 let response={ok:true,data:{message:'Заявка сохранена. Номер: 5'}}, sent;
 const context={document,matchMedia:()=>({matches:true}),navigator:{clipboard:{writeText:async text=>{context.copied=text;}}},FormData:class{*[Symbol.iterator](){yield ['email','test@example.com'];yield ['company','Тест'];yield ['plan',elements.plan.value];}},fetch:async(url,options)=>{sent=JSON.parse(options.body);return {ok:response.ok,json:async()=>response.data};}};
 vm.runInNewContext(fs.readFileSync('app.js','utf8'),context);
 await demo[1].emit('click');assert.match(elements['demo-title'].textContent,/SalesFlow/);assert.equal(elements['demo-panel'].hidden,false);
 await elements['generate-demo'].emit('click');assert.match(elements['demo-draft'].value,/Jonas/);assert.equal(elements['demo-draft-wrap'].hidden,false);
 await elements['copy-demo'].emit('click');assert.match(context.copied,/SalesFlow/);
 await plans[1].emit('click');assert.equal(elements.plan.value,'Professional');
 elements.consent.checked=true;let resets=0;elements['request-form'].reset=()=>{resets++;};
 await elements['request-form'].emit('submit');assert.equal(sent.consent,true);assert.equal(sent.plan,'Professional');assert.equal(resets,1);assert.match(elements['request-status'].textContent,/сохранена/);assert.equal(elements['send-request'].disabled,false);
 response={ok:false,data:{error:'Сервер временно недоступен'}};
 await elements['request-form'].emit('submit');assert.equal(resets,1);assert.match(elements['request-status'].textContent,/недоступен/);assert.equal(elements['send-request'].disabled,false);
 context.navigator.clipboard.writeText=async()=>{throw new Error('denied')};
 await elements['copy-demo'].emit('click');assert.equal(elements['demo-draft'].selected,true);
 console.log('Public flow: demo selection, draft, copy, plan transfer, successful intake, failed intake and copy fallback passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
