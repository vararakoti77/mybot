// Frontend logic for ChatGPT-like UI
const els = {
  chat: document.getElementById('chat'),
  input: document.getElementById('input'),
  form: document.getElementById('composer'),
  model: document.getElementById('model'),
  system: document.getElementById('system'),
  temp: document.getElementById('temperature'),
  tempVal: document.getElementById('tempVal'),
  history: document.getElementById('history'),
  newChat: document.getElementById('newChat'),
  title: document.getElementById('title'),
  send: document.getElementById('send'),
};

let activeChatId = null;
let chats = []; // for sidebar

function bubble(role, content){
  const el = document.createElement('div');
  el.className = `bubble ${role}`;
  el.innerHTML = `
    <div class="role ${role}">${role==='user'?'U':'A'}</div>
    <div class="content">${sanitize(content)}</div>
  `;
  els.chat.appendChild(el);
  els.chat.scrollTop = els.chat.scrollHeight;
  return el.querySelector('.content');
}

function sanitize(s){
  return (s ?? '').toString()
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\n/g,'<br/>');
}

function setSending(sending){
  els.send.disabled = sending;
  els.input.disabled = sending;
  els.model.disabled = sending;
  els.system.disabled = sending;
  els.temp.disabled = sending;
}

async function loadModels(){
  const r = await fetch('/api/models');
  const models = await r.json();
  els.model.innerHTML = '';
  models.forEach(m=>{
    const o = document.createElement('option');
    o.value = m; o.textContent = m;
    els.model.appendChild(o);
  });
  els.model.value = models[0];
}

async function listChats(){
  const r = await fetch('/api/chats');
  chats = await r.json();
  renderHistory();
  if(chats.length && !activeChatId){
    setActiveChat(chats[0].id);
  }
}

function renderHistory(){
  els.history.innerHTML = '';
  if(!chats.length){
    els.history.innerHTML = '<div class="muted">No conversations yet.</div>';
    return;
  }
  chats.forEach(c=>{
    const btn = document.createElement('button');
    btn.className = 'chat-link' + (c.id===activeChatId ? ' active':'');
    btn.textContent = c.title;
    btn.onclick = ()=> setActiveChat(c.id);
    els.history.appendChild(btn);
  });
}

async function setActiveChat(id){
  activeChatId = id;
  const r = await fetch(`/api/chats/${id}`);
  const data = await r.json();
  els.chat.innerHTML = '';
  els.title.textContent = data.chat.title;
  els.model.value = data.chat.model;
  els.system.value = data.chat.system_prompt || '';
  els.temp.value = data.chat.temperature;
  els.tempVal.textContent = data.chat.temperature;
  data.messages.forEach(m=> bubble(m.role, m.content));
  chats = chats.map(c => c.id===id ? data.chat : c);
  renderHistory();
}

async function createChat(){
  const r = await fetch('/api/chats', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      title: 'New chat',
      model: els.model.value,
      system_prompt: els.system.value,
      temperature: parseFloat(els.temp.value)
    })
  });
  const data = await r.json();
  await listChats();
  await setActiveChat(data.id);
}

els.newChat.addEventListener('click', createChat);
els.temp.addEventListener('input', ()=> els.tempVal.textContent = els.temp.value);

els.form.addEventListener('submit', async (e)=>{
  e.preventDefault();
  const text = els.input.value.trim();
  if(!text) return;
  if(!activeChatId){
    await createChat();
  } else {
    // persist current config
    await fetch(`/api/chats/${activeChatId}/config`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        model: els.model.value,
        system_prompt: els.system.value,
        temperature: parseFloat(els.temp.value)
      })
    });
  }

  // user bubble
  bubble('user', text);
  setSending(true);

  const assistantEl = bubble('assistant', '...');

  try{
    const r = await fetch(`/api/chats/${activeChatId}/message`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ content: text })
    });
    const data = await r.json();
    assistantEl.innerHTML = sanitize(data.reply || '(no content)');
    // update title in sidebar if changed
    chats = chats.map(c=> c.id===activeChatId ? {...c, title: data.title || c.title} : c);
    renderHistory();
  }catch(err){
    assistantEl.innerHTML = sanitize('⚠️ Error: ' + err.message);
  }finally{
    els.input.value='';
    els.input.focus();
    setSending(false);
  }
});

// init
(async function(){
  await loadModels();
  await listChats();
})();
