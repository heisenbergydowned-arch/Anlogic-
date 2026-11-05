const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const code=[...fs.readFileSync(path.join(root,'linux/static/index.html'),'utf8').matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');
async function render(data,{eventsFail=false,statusFail=false}={}){
 const nodes=new Map();
 function node(){return {textContent:'',children:[],style:{},dataset:{},value:'',className:'',clientWidth:820,append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items},querySelectorAll(selector){return selector==='.value'?this.children.flatMap(x=>x.children.filter(y=>y.className==='value')):[]},getContext(){return new Proxy({},{get(){return ()=>{}}})}}}
 const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)};
 const sandbox={document:{getElementById:get,createElement:node},window:{devicePixelRatio:1,addEventListener(){}},AbortController,performance:{now:()=>0},setTimeout:()=>1,clearTimeout(){},setInterval(){},fetch:async url=>{if(statusFail&&url==='/api/status')throw Error('offline');return {ok:!(eventsFail&&url==='/api/events'),status:503,json:async()=>url==='/api/status'?data:[]}}};
 vm.runInNewContext(code,sandbox);await new Promise(setImmediate);return get;
}
(async()=>{
 const source=JSON.parse(fs.readFileSync(path.join(root,'evidence/merged_site_review/status.json')));
 const status={...source,snapshot_monotonic:100,level:0,link:'ONLINE',temperature_pwm:{state:'RUNNING',saved:true,hardware_supported:true,hardware_armed:true,feedback_valid:true,temperature_C:52.5,target_pwm_percent:50,actual_pwm_percent:50,settings:{low_C:25,high_C:80},alarm_causes:[]},monitor_display:{available:true,fields:{daily_current_valid:'1',daily_current_value:'0.400',daily_current_average_count:'40',panel_nn_valid:'1',panel_nn_deadline_ms:'100500',panel_nn_advisory_state:'NORMAL',panel_nn_assessment:'NORMAL_RECONSTRUCTION_MATCH',panel_nn_count:'100',panel_nn_score:'.5',panel_nn_latency_ms:'1.2',panel_classifier_valid:'0'}}};
 let get=await render(status,{eventsFail:true});assert.match(get('health').textContent,/温控运行/);assert.equal(get('npu-badge').textContent,'正常基线 · 实推理');assert.equal(get('val-0').textContent,'—');assert.ok(get('cards').children.some(c=>c.children.some(x=>x.textContent==='0.400 A')));assert.equal(get('led-inh-text').textContent,'50.0%');
 const expired=structuredClone(status);expired.monitor_display.fields.panel_nn_deadline_ms='99999';get=await render(expired);assert.equal(get('npu-badge').textContent,'推理等待中');
 const classified=structuredClone(status);Object.assign(classified.monitor_display.fields,{panel_classifier_valid:'1',panel_classifier_deadline_ms:'100500',panel_classifier_label:'clog',panel_prob_clog:'92.5'});get=await render(classified);assert.equal(get('val-3').textContent,'92.5%');assert.equal(get('classifier-model').textContent,'五类识别：堵塞');
 get=await render({...status,monitor_display:{available:false,fields:{}}});assert.equal(get('npu-badge').textContent,'推理等待中');assert.equal(get('val-0').textContent,'—');
 get=await render(status,{statusFail:true});assert.equal(get('npu-badge').textContent,'连接中断');assert.equal(get('led-inh-text').textContent,'--');
 console.log('PASS: 5 monitoring page cases, current/normal/classifier/expiry/offline and event-failure isolation');
})().catch(e=>{console.error(e);process.exitCode=1});
