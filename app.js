'use strict';
const samples = [
  {company:'TechStart GmbH',contact:'Max Mueller',grade:'A',reason:'В этом вымышленном сценарии контакт запросил демонстрацию и указал задачу автоматизации продаж.',action:'Уточнить задачи команды и договориться о встрече.'},
  {company:'SalesFlow UAB',contact:'Jonas P.',grade:'A',reason:'В этом вымышленном сценарии компания запросила материалы, но следующий шаг ещё не назначен.',action:'Уточнить процесс обработки входящих заявок.'},
  {company:'Digital Solutions',contact:'Anna Schmidt',grade:'B',reason:'В этом вымышленном сценарии контакт изучает возможности продукта, сроки внедрения неизвестны.',action:'Уточнить задачу и срок принятия решения.'}
];
const $ = id => document.getElementById(id);
let current = null;
document.querySelectorAll('[data-demo]').forEach(button => button.addEventListener('click', () => {
  current = samples[Number(button.dataset.demo)];
  $('demo-panel').hidden = false;
  $('demo-title').textContent = current.company + ' · ' + current.contact;
  $('demo-reason').textContent = current.reason;
  $('demo-action').textContent = current.action;
  $('demo-draft-wrap').hidden = true;
  $('demo-status').textContent = '';
  $('demo-title').focus();
  $('demo-panel').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'nearest'});
}));
$('generate-demo').addEventListener('click', () => {
  if (!current) return;
  $('demo-draft').value = `${current.contact}, добрый день!\n\nСпасибо за интерес к ВЕКРА. Как сейчас команда ${current.company} определяет, каким входящим заявкам отвечать в первую очередь? Предлагаю обсудить ваш процесс продаж и показать подходящий сценарий работы. Когда вам удобно?`;
  $('demo-draft-wrap').hidden = false;
  $('demo-draft').focus();
});
$('copy-demo').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('demo-draft').value); $('demo-status').textContent='Письмо скопировано.'; }
  catch { $('demo-status').textContent='Выделите текст письма и скопируйте вручную.'; $('demo-draft').focus(); $('demo-draft').select(); }
});
document.querySelectorAll('[data-plan]').forEach(button => button.addEventListener('click', () => { $('plan').value=button.dataset.plan; }));
$('request-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button=$('send-request');
  const data=Object.fromEntries(new FormData(event.target));
  data.consent=$('consent').checked;
  button.disabled=true;
  $('request-status').className='notice';
  $('request-status').textContent='Сохраняем заявку…';
  try {
    const response=await fetch('/api/requests',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const result=await response.json();
    if (!response.ok) throw new Error(result.error || 'Не удалось сохранить заявку');
    $('request-status').className='notice success';
    $('request-status').textContent=result.message + '. Команда сможет обработать её в кабинете.';
    event.target.reset();
  } catch(error) { $('request-status').className='notice error'; $('request-status').textContent=error.message || 'Нет связи с сервером. Данные остались в форме; повторите попытку.'; }
  finally { button.disabled=false; }
});
