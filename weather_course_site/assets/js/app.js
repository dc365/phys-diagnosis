
(function(){
  const idx = window.COURSE_INDEX || [];
  const LESSON_TOTAL = idx.filter(x => x.id && x.id.startsWith('lesson-')).length;
  const rootPrefix = location.pathname.includes('/lessons/') ? '../' : '';
  function getDone(){try{return JSON.parse(localStorage.getItem('weatherCourseDone')||'[]')}catch(e){return []}}
  function setDone(list){localStorage.setItem('weatherCourseDone', JSON.stringify([...new Set(list)])); updateProgress();}
  function updateProgress(){
    const done = getDone();
    const count = done.length;
    const progressText = document.getElementById('progressText');
    if(progressText) progressText.textContent = count + '/' + LESSON_TOTAL;
    const bar = document.getElementById('homeProgressBar');
    if(bar) bar.style.width = (LESSON_TOTAL ? (count/LESSON_TOTAL*100) : 0) + '%';
    const cap = document.getElementById('homeProgressCaption');
    if(cap) cap.textContent = '已完成 ' + count + ' / ' + LESSON_TOTAL + ' 课';
    document.querySelectorAll('[data-lesson-id]').forEach(el => {
      const id = el.getAttribute('data-lesson-id');
      if(id && done.includes(id)) el.classList.add('done'); else el.classList.remove('done');
    });
    const cur = document.body.getAttribute('data-lesson-id');
    const btn = document.querySelector('.mark-done');
    if(btn && cur){btn.textContent = done.includes(cur) ? '已完成 ✓' : '标记完成';}
  }
  updateProgress();
  const curHref = document.body.getAttribute('data-current-href');
  if(curHref){
    document.querySelectorAll('.lesson-link').forEach(a=>{
      const href = a.getAttribute('href').replace(/^\.\.\//,'');
      if(href === curHref) a.classList.add('active');
    });
  }
  const mark = document.querySelector('.mark-done');
  if(mark){mark.addEventListener('click',()=>{
    const id = document.body.getAttribute('data-lesson-id');
    const done = getDone();
    if(done.includes(id)) setDone(done.filter(x=>x!==id)); else setDone([...done,id]);
  });}
  const navToggle = document.querySelector('.nav-toggle');
  const sidebar = document.getElementById('sidebar');
  if(navToggle && sidebar){navToggle.addEventListener('click',()=>sidebar.classList.toggle('open'));}
  // Search
  const input = document.getElementById('globalSearch');
  const box = document.getElementById('searchResults');
  function norm(s){return (s||'').toLowerCase();}
  if(input && box){
    input.addEventListener('input',()=>{
      const q = norm(input.value.trim());
      if(!q){box.hidden=true; box.innerHTML=''; return;}
      const hits = idx.filter(item => norm(item.title+' '+item.summary+' '+(item.tags||[]).join(' ')).includes(q)).slice(0,8);
      box.innerHTML = hits.length ? hits.map(h=>`<a href="${rootPrefix}${h.href}"><strong>${h.title}</strong><small>${h.summary||''}</small></a>`).join('') : '<a><strong>未找到</strong><small>试试 CAPE、雷达、探空、湿球温度、涡度。</small></a>';
      box.hidden=false;
    });
    document.addEventListener('click',(e)=>{if(!box.contains(e.target) && e.target!==input) box.hidden=true;});
  }
  // TOC
  const toc = document.getElementById('toc');
  const article = document.querySelector('.article');
  if(toc && article){
    const hs = Array.from(article.querySelectorAll('h2,h3'));
    if(hs.length){
      hs.forEach((h,i)=>{h.id = h.id || 'sec-' + (i+1); const a=document.createElement('a'); a.href='#'+h.id; a.textContent=h.textContent; a.className=h.tagName==='H3'?'toc-h3':'toc-h2'; toc.appendChild(a);});
    } else { toc.style.display='none'; }
  }
  // Glossary filter
  const gInput = document.getElementById('glossarySearch');
  if(gInput){
    gInput.addEventListener('input',()=>{
      const q = norm(gInput.value.trim());
      document.querySelectorAll('#glossaryTable tbody tr').forEach(row=>{
        row.classList.toggle('hide', q && !norm(row.textContent).includes(q));
      });
    });
  }
  // Back top
  const back = document.getElementById('backTop');
  if(back){
    window.addEventListener('scroll',()=>back.classList.toggle('show', scrollY>600));
    back.addEventListener('click',()=>scrollTo({top:0, behavior:'smooth'}));
  }
})();
