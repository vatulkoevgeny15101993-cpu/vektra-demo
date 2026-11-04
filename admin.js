'use strict';
const $=id=>document.getElementById(id);
const labels={new:'Новый',contacted:'Связались',meeting:'Встреча',won:'Выигран',lost:'Потерян'};
let leads=[], selected=null, dirty=false, busy=false;
function message(text,error=false){$('admin-status').textContent=text;$('admin-status').className=error?'notice error':'notice success';}
function loginView(){ $('workspace').hidden=true;$('login-section').hidden=false;$('logout').hidden=true;leads=[];selected=null;$('lead-list').replaceChildren();$('detail').reset();$('detail').hidden=true;dirty=false; }
async function api(path,method='GET',data){
 const response=await fetch(path,{method,headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined});
 const result=await response.json();
 if(response.status===401)loginView();
 if(!response.ok)throw new Error(result.error || 'Ошибка сервера');
 return result;
}
function renderList(){
 const query=$('search').value.trim().toLowerCase(),filter=$('filter').value;
 const rows=leads.filter(l=>(!filter||l.status===filter)&&`${l.company} ${l.email} ${l.contact}`.toLowerCase().includes(query));
 $('lead-list').replaceChildren();
 if(!rows.length){const p=document.createElement('p');p.textContent=leads.length?'Нет совпадений. Измените фильтры.':'Пока нет заявок. Отправьте первую через форму на главной.';$('lead-list').append(p);}
 rows.forEach(lead=>{const b=document.createElement('button');b.type='button';b.className='lead-choice';b.setAttribute('aria-pressed',String(lead.id===selected));b.textContent=`${lead.company} · ${labels[lead.status]} · ${lead.score.grade}\n${lead.email}`;b.addEventListener('click',()=>{if(busy)return;if(dirty&&!confirm('Несохранённые изменения будут потеряны. Продолжить?'))return;selectLead(lead);});$('lead-list').append(b);});
 const won=leads.filter(l=>l.status==='won').length;
 $('summary').textContent=`Заявок: ${leads.length} · Новых: ${leads.filter(l=>l.status==='new').length} · Встреч: ${leads.filter(l=>l.status==='meeting').length} · Выиграно: ${won} · Доля выигранных: ${leads.length?Math.round(won/leads.length*100):0}%`;
}
function selectLead(lead){selected=lead.id;dirty=false;$('empty-detail').hidden=true;$('detail').hidden=false;$('lead-title').textContent=lead.company;$('lead-contact').textContent=`${lead.contact || 'Контакт не указан'} · ${lead.email}`;$('lead-site').textContent=lead.website || 'Сайт не указан';$('lead-plan').textContent='Тариф: '+lead.plan;$('lead-created').textContent='Заявка: '+new Date(lead.created_at*1000).toLocaleString('ru-RU');$('lead-score').textContent=`Приоритет ${lead.score.grade} · ${lead.score.points}/100. ${lead.score.method}`;$('score-reasons').replaceChildren(...lead.score.reasons.map(reason=>{const li=document.createElement('li');li.textContent=reason;return li;}));$('lead-status').value=lead.status;$('notes').value=lead.notes;$('draft').value=lead.draft;renderList();}
async function load(){const result=await api('/api/leads');leads=result.leads;$('workspace').hidden=false;$('login-section').hidden=true;$('logout').hidden=false;const lead=leads.find(l=>l.id===selected);if(lead)selectLead(lead);else {selected=null;$('detail').hidden=true;$('empty-detail').hidden=false;renderList();}}
$('login-form').addEventListener('submit',async e=>{e.preventDefault();$('login-button').disabled=true;try{await api('/api/login','POST',{password:$('password').value});$('password').value='';await load();message('Вы вошли в кабинет.');}catch(e){message(e.message,true);}finally{$('login-button').disabled=false;}});
$('logout').addEventListener('click',async()=>{if(busy)return;if(dirty&&!confirm('Выйти без сохранения изменений?'))return;try{await api('/api/logout','POST',{});loginView();message('Вы вышли.');}catch(e){message(e.message,true);}});
$('refresh').addEventListener('click',async()=>{if(busy)return;if(dirty&&!confirm('Обновить и потерять несохранённые изменения?'))return;try{await load();message('Данные обновлены.');}catch(e){message(e.message,true);}});
$('search').addEventListener('input',renderList);$('filter').addEventListener('change',renderList);
$('detail').addEventListener('input',()=>{dirty=true;});
$('detail').addEventListener('submit',async e=>{e.preventDefault();if(busy)return;busy=true;$('save').disabled=true;try{await api('/api/leads/'+selected,'PATCH',{status:$('lead-status').value,notes:$('notes').value,draft:$('draft').value});dirty=false;await load();message('Изменения сохранены.');}catch(e){message(e.message,true);}finally{busy=false;$('save').disabled=false;}});
$('generate').addEventListener('click',async()=>{if((dirty||$('draft').value)&&!confirm('Заменить текущий черновик? Сначала сохраните другие изменения, если они нужны.'))return;if(busy)return;busy=true;$('generate').disabled=true;try{const result=await api('/api/leads/'+selected+'/draft','POST',{});$('draft').value=result.draft;dirty=true;message(result.method+'. Черновик сохранён на сервере.');}catch(e){message(e.message,true);}finally{busy=false;$('generate').disabled=false;}});
$('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('draft').value);message('Текст скопирован.');}catch{$('draft').focus();$('draft').select();message('Скопируйте выделенный текст вручную.');}});
$('delete').addEventListener('click',async()=>{if(busy)return;if(!confirm('Удалить эту заявку и заметки без возможности восстановления?'))return;try{await api('/api/leads/'+selected,'DELETE',{});dirty=false;selected=null;await load();message('Заявка удалена.');}catch(e){message(e.message,true);}});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
load().catch(e=>{if($('login-section').hidden)message(e.message,true);else if(!e.message.includes('Войдите'))message(e.message,true);});
