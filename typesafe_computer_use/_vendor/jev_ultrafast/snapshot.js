(() => {
  if (!document.body) return null;
  const cache = window.__jevFast ||= {ids:new WeakMap(), nodes:new Map(), next:1};
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
  };
  for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const safe = e => !['password','file','hidden'].includes(e.type);
  const visible = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  const name = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const referenced=(e.getAttribute('aria-labelledby')||'').split(/\s+/)
      .map(id=>name(document.getElementById(id),seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ') ||
      (['button','submit','reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (e.tagName==='INPUT' ? '' : [...e.childNodes].map(n=>n.nodeType===3 ? n.textContent :
        n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' ? name(n,seen) : '').join(' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'option','gridcell','combobox','textbox','searchbox','spinbutton'];
  const selector='a,button,input,textarea,select,summary,label,[onclick],[tabindex],[contenteditable="true"],'+
    roles.map(role=>'[role="'+role+'"]').join(',');
  const role = e => {
    const explicit=e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (explicit) return null;
    if (e.tagName==='LABEL' && ['checkbox','radio'].includes(e.control?.type)) return e.control.type;
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A') return 'link';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (['text','email','url','tel'].includes(e.type)) return 'textbox';
    }
    if (e.hasAttribute('onclick') || e.hasAttribute('tabindex') || getComputedStyle(e).cursor==='pointer') return 'button';
    return null;
  };
  cache.pageKey=()=>[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    [...document.querySelectorAll('input,textarea,select')].filter(safe)
      .map(e=>[identity(e),e.value,e.checked,e.selectedIndex,e.disabled,e.readOnly])];
  cache.guard=e=>{
    if (!e?.isConnected || !visible(e)) return null;
    const scope=e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    return [identity(e),role(e),name(e),e.value??null,e.checked??null,e.selectedIndex??null,
      e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('href'),e.scrollTop,e.scrollLeft,scope?.innerText?.slice(0,6000)||''];
  };
  const actions=[];
  const candidates=[...document.querySelectorAll(selector)];
  for (const e of document.querySelectorAll('span,div')) {
    if (!e.matches(selector) && getComputedStyle(e).cursor==='pointer' &&
        !e.parentElement?.closest('a,button,label,[role=button],[role=link],[role=tab],[role=option]') && !e.querySelector(selector)) candidates.push(e);
  }
  for (const e of candidates) {
    if (!safe(e) || !visible(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"]')) continue;
    const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2, rname=role(e);
    if (!rname || r.width<=0 || r.height<=0 || x<0 || y<0 || x>=innerWidth || y>=innerHeight) continue;
    if (!e.contains(document.elementFromPoint(x,y))) continue;
    if (rname==='gridcell' && e.querySelector('button,[role="button"]')) continue;
    const base={node:identity(e),role:rname,label:name(e)||rname,
      rect:{x:r.x,y:r.y,w:r.width,h:r.height},
      context:e.parentElement?.innerText?.trim().slice(0,900)||'',
      position_in_parent:1+[...e.parentElement.children].indexOf(e)};
    const peers=[...(e.parentElement.parentElement?.children||[])].filter(n=>n.tagName===e.parentElement.tagName && visible(n));
    if (peers.length>1) base.group={node:identity(e.parentElement.parentElement),position:1+peers.indexOf(e.parentElement),size:peers.length};
    if (!name(e) && e.parentElement.matches('li') && e.parentElement.querySelector('ul')) {
      base.label='Toggle '+[...e.parentElement.children].filter(n=>n.tagName==='SPAN').map(n=>n.innerText).join(' ');
      base.expanded=String([...e.parentElement.children].some(n=>n.tagName==='UL' && visible(n)));
    }
    base.autocomplete=e.getAttribute('aria-autocomplete') || (e.classList.contains('ui-autocomplete-input') ? 'list' : '');
    const current=e.closest('[aria-current],.active,.selected,.current,.ui-tabs-active');
    if (current) {
      const value=current.getAttribute('aria-current');
      if (value===null || (value.trim() && value.toLowerCase()!=='false')) base.current=value||'true';
    }
    for (const key of ['checked','selected','expanded']) {
      const value=e.getAttribute('aria-'+key);
      if (value!==null) base[key]=value;
    }
    const control=e.tagName==='LABEL' ? e.control : e;
    if (['checkbox','radio'].includes(control?.type)) base.checked=String(control.checked);
    if (e.tagName==='SELECT') {
      for (const o of e.options) if (!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
        actions.push({...base,kind:'select',value:o.value,
          current_value:[...e.selectedOptions].map(o=>o.label).join(', '),label:base.label+' → '+o.label});
    } else {
      const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
        (['textbox','searchbox','spinbutton'].includes(rname) ||
          (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      const value='value' in e ? String(e.value) :
        e.isContentEditable || rname==='combobox' ? e.innerText.trim() : '';
      actions.push({...base,kind:editable?'fill':'click',value});
      if (editable && e!==document.activeElement) actions.push({...base,kind:'click',value,label:'Open '+base.label});
    }
  }
  // Derive paging arithmetic only from a visible current numeric control and a sibling list.
  // The uniform-page assumption remains explicit; this metadata never chooses an action.
  cache.pageSizes ||= new Map();
  cache.pageCounts ||= new Map();
  for (const current of actions.filter(a=>a.current && /^\d+$/.test(a.label) && a.role==='link')) {
    const e=cache.nodes.get(current.node), nav=e.closest('ul,ol,nav,[role="navigation"]');
    if (!nav) continue;
    const page=Number(current.label), parent=nav.parentElement;
    const numeric=[...nav.querySelectorAll('a,button')].filter(n=>visible(n) && /^\d+$/.test(name(n)));
    if (numeric.length<2) continue;
    for (const a of actions) {
      if (a.role!=='link' || !a.group || a.current) continue;
      const group=cache.nodes.get(a.group.node);
      if (group===nav || group?.parentElement!==parent || !(group.compareDocumentPosition(nav)&Node.DOCUMENT_POSITION_FOLLOWING)) continue;
      if (page===1) cache.pageSizes.set(a.group.node,a.group.size);
      const size=cache.pageSizes.get(a.group.node);
      const countKey=JSON.stringify([a.group.node,location.href,cache.pageKey()[6]]);
      const counts=cache.pageCounts.get(countKey)||{}; counts[page]=a.group.size; cache.pageCounts.set(countKey,counts);
      a.pagination={page,position_on_page:a.group.position,visible_items:a.group.size};
      if (size && a.group.size<=size) a.pagination.ordinal_if_uniform_pages=(page-1)*size+a.group.position;
      let offset=0, complete=true;
      for (let prior=1;prior<page;prior++) { if (!(prior in counts)) {complete=false;break;} offset+=counts[prior]; }
      if (complete) a.pagination.ordinal_from_observed_pages=offset+a.group.position;
    }
  }
  const words=[], writerWords=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const range=document.createRange(); let node,length=0;
  while ((node=walker.nextNode()) && length<6000) {
    const value=node.textContent.trim(), parent=node.parentElement;
    if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
    range.selectNodeContents(node); const r=range.getBoundingClientRect();
    if (r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth) {
      words.push(value); length+=value.length;
      // Exclude explicit timers and standalone countdown counters from writer evidence.
      // All other text (including amounts, references and dates) must remain fresh.
      if (!parent.closest('[role="timer"]') && !/^\d+(?:\.\d+)?\s*\/\s*\d+(?:\.\d+)?\s*(?:sec|seconds?)$/i.test(value)) writerWords.push(value);
    }
  }
  const text=words.join('\n').slice(0,6000), height=document.documentElement.scrollHeight;
  for (const e of document.querySelectorAll('div,section,article,main,aside,ul,ol,textarea,[role="listbox"]')) {
    if (!safe(e) || !visible(e) || e.scrollHeight<=e.clientHeight+2 || e.clientHeight<20 ||
        !/auto|scroll/.test(getComputedStyle(e).overflowY)) continue;
    const r=e.getBoundingClientRect();
    if (r.bottom<=0 || r.top>=innerHeight || r.right<=0 || r.left>=innerWidth) continue;
    const base={node:identity(e),kind:'scroll',label:name(e).slice(0,100)||e.tagName.toLowerCase(),
      rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
    if (e.scrollTop+e.clientHeight<e.scrollHeight-2)
      actions.push({...base,id:'region_'+base.node+'_down',label:'Scroll down inside '+base.label,delta:Math.max(80,e.clientHeight*0.8)});
    if (e.scrollTop>0)
      actions.push({...base,id:'region_'+base.node+'_up',label:'Scroll up inside '+base.label,delta:-Math.max(80,e.clientHeight*0.8)});
  }
  const page_key=cache.pageKey(), guards={};
  for (const a of actions) if (!(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node));
  // Compare meaning and identity. Geometry is always resolved and hit-tested just before input.
  const semantics=actions.map(({rect,...action})=>action);
  const marker=[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.title,text,semantics,page_key[6]];
  const omitted_actions=Math.max(0,actions.length-250);
  actions.splice(250);
  actions.forEach((a,i)=>a.id ||= 'e'+(i+1));
  if (scrollY+innerHeight<height-2) actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down',delta:560});
  if (scrollY>0) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-560});
  actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
  const text_blocks=[...document.querySelectorAll('p,pre,article')].filter(visible).slice(0,20).map(e=>({text:e.innerText.slice(0,1500),words:e.innerText.trim().split(/\s+/).slice(0,200).map((word,i)=>({position:i+1,word}))}));
  const visual_surfaces=[...document.querySelectorAll('img,canvas,iframe,[role="slider"],input[type="range"]')]
    .filter(e=>{const r=e.getBoundingClientRect();return visible(e)&&r.width>1&&r.height>1&&r.bottom>0&&r.top<innerHeight&&r.right>0&&r.left<innerWidth;})
    .slice(0,30).map(e=>({kind:e.tagName.toLowerCase(),role:e.getAttribute('role'),label:name(e).slice(0,200)}));
  return {url:location.href,title:document.title,w:innerWidth,h:innerHeight,text,text_blocks,visual_surfaces,
    writer_text:writerWords.join("\n").slice(0,6000),scroll:{y:scrollY,height},actions,marker,page_key,guards,omitted_actions};
})()
