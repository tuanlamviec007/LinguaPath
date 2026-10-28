/* Standard POST/redirect remains the no-JS path. Never inject model HTML. */
(() => {
  const form=document.querySelector('[data-chat-form]');
  if(!form)return;
  const status=form.querySelector('[data-chat-status]');
  let pending=false;
  form.addEventListener('submit',event=>{
    if(pending){event.preventDefault();return;}
    pending=true;status.textContent='Lumi đang xử lý yêu cầu của bạn…';
    form.setAttribute('aria-busy','true');
    // Do not disable the submitter: its tool value must reach the server.
  });
  window.addEventListener('pageshow',()=>{pending=false;form.removeAttribute('aria-busy');status.textContent='';});
})();
