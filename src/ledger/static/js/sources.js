document.addEventListener('DOMContentLoaded', () => {
  const message = document.getElementById('source-message');
  const form = document.getElementById('source-form');
  const statusLabels = {draft:'草稿', submitted:'等待审核', approved:'已批准', rejected:'已驳回'};
  let editing = null;
  const notify = text => { message.textContent = text; message.focus(); };
  async function api(path, method = 'GET', body) {
    const response = await ledgerIdentity.api(path, {method,
      headers: body ? {'Content-Type':'application/json'} : {},
      body: body ? JSON.stringify(body) : undefined});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '请求失败，请检查输入或联系管理员');
    return result;
  }
  function button(label, handler) {
    const el = document.createElement('button'); el.textContent = label; el.className = 'btn';
    el.type = 'button';
    el.addEventListener('click', async () => {
      el.disabled = true;
      try { await handler(); } catch (error) { notify(error.message); }
      finally { el.disabled = false; }
    });
    return el;
  }
  async function reload() {
    const list = document.getElementById('my-sources'); list.replaceChildren();
    for (const item of await api('/api/source-proposals')) list.append(card(item, false));
    const reviews = document.getElementById('source-reviews');
    if (reviews) {
      reviews.replaceChildren();
      for (const item of await api('/api/admin/source-proposals')) {
        if (item.status === 'submitted') reviews.append(card(item, true));
      }
      document.getElementById('domain-list').textContent = (await api('/api/admin/domains')).join('、');
      const active = document.getElementById('active-sources'); active.replaceChildren();
      for (const item of await api('/api/admin/sources')) {
        const p = document.createElement('p'); p.textContent = item.display_name + (item.enabled ? ' · 已启用 ' : ' · 已暂停 ');
        p.append(button(item.enabled ? '暂停' : '启用', async () => {
          await api('/api/admin/sources/'+item.id, 'PATCH', {enabled: !item.enabled}); await reload();
        })); active.append(p);
      }
    }
  }
  function card(item, review) {
    const el = document.createElement('article'); el.className = 'card mb-lg';
    const title = document.createElement('h3'); title.textContent = item.display_name + ' · v' + item.version + ' · ' + statusLabels[item.status]; el.append(title);
    const pre = document.createElement('pre'); pre.className = 'source-preview';
    pre.textContent = JSON.stringify({config:item.config, preview:item.preview, review_note:item.review_note}, null, 2); el.append(pre);
    if (review) {
      const label = document.createElement('label'); label.textContent = '审核理由';
      const note = document.createElement('textarea'); label.append(note); el.append(label);
      for (const [decision, text] of [['approve','批准'],['reject','驳回']]) el.append(button(text, async () => {
        if (!note.value.trim()) throw new Error('请填写审核理由');
        await api('/api/admin/source-proposals/'+item.id+'/review', 'POST', {version:item.version, decision, note:note.value}); await reload();
      }));
    } else {
      el.append(button('编辑为新版本', async () => {
        editing = item.id;
        const c = item.config;
        const select=form.elements.namedItem('product_id');
        if(![...select.options].some(option=>option.value===item.product_id)) {
          const product=await api('/api/catalog/products/'+item.product_id);
          const option=document.createElement('option');option.value=product.id;
          option.textContent=product.name+' · '+product.issuer_code;option.dataset.currency=product.currency;
          select.append(option);
        }
        for (const [key,value] of Object.entries({display_name:item.display_name,product_id:item.product_id,
          url:c.url,format:c.format,source_product_id:c.source_product_id,rows:c.format==='json'?c.rows_path:c.table_selector,
          field_product:c.fields.product_id,field_date:c.fields.date,field_nav:c.fields.unit_nav||'',
          field_cumulative:c.fields.cumulative_nav||'',field_tenk:c.fields.ten_thousand_profit||'',
          field_seven:c.fields.seven_day_annualized||'',method:c.method,params:JSON.stringify(c.params),date_format:c.date_format,page_param:c.page_param||''})) {
          form.elements.namedItem(key).value = value;
        }
        form.elements.namedItem('product_id').disabled = true;
        notify('正在编辑；保存会生成新版本，原版本记录仍保留。'); form.scrollIntoView();
      }));
      if (item.status === 'draft') {
        el.append(button('试抓取', async () => {
          const receipt = await api('/api/source-proposals/'+item.id+'/preview','POST'); notify('试抓取已提交…');
          for (let i=0;i<60;i++) {
            await new Promise(resolve=>setTimeout(resolve,2000));
            const job = await api('/api/my/jobs/'+receipt.job_id);
            if (['succeeded','failed','needs_action','cancelled'].includes(job.status)) {notify('试抓取结束，请核对预览结果。'); await reload(); return;}
          }
          notify('任务仍在后台运行，请稍后刷新。');
        }));
        el.append(button('提交审核', async () => {await api('/api/source-proposals/'+item.id+'/submit','POST'); await reload();}));
      }
    }
    return el;
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); const submit = form.querySelector('[type=submit]'); submit.disabled = true;
    try {
      const value = name => form.elements.namedItem(name).value.trim();
      const productOption = form.elements.namedItem('product_id').selectedOptions[0];
      const fields = {product_id:value('field_product'),date:value('field_date')};
      for (const [name,key] of [['field_nav','unit_nav'],['field_cumulative','cumulative_nav'],['field_tenk','ten_thousand_profit'],['field_seven','seven_day_annualized']]) if(value(name)) fields[key]=value(name);
      const config = {url:value('url'),format:value('format'),source_product_id:value('source_product_id'),
        currency:productOption.dataset.currency || 'CNY',fields, method:value('method'),params:JSON.parse(value('params')),
        date_format:value('date_format'),page_param:value('page_param')||null};
      config[config.format==='json'?'rows_path':'table_selector']=value('rows');
      await api(editing?'/api/source-proposals/'+editing:'/api/source-proposals',editing?'PATCH':'POST',
        {display_name:value('display_name'),product_id:value('product_id'),config});
      editing = null; form.elements.namedItem('product_id').disabled=false;
      notify('草稿已保存。请先试抓取、核对结果，再提交审核。'); await reload();
    } catch(error) {notify(error.message);} finally {submit.disabled=false;}
  });
  document.getElementById('domain-form')?.addEventListener('submit', async event => {
    event.preventDefault(); try {await api('/api/admin/domains','POST',{hostname:event.target.hostname.value}); await reload();}
    catch(error){notify(error.message);}
  });
  async function loadProducts(keyword='') {
    const select = document.getElementById('source-product'); select.replaceChildren();
    for (const product of await api('/api/catalog/products?limit=200&keyword='+encodeURIComponent(keyword))) {
      const option=document.createElement('option'); option.value=product.id;
      option.textContent=product.name+' · '+product.issuer_code; option.dataset.currency=product.currency;
      select.append(option);
    }
    if(!select.options.length) notify('没有找到产品，请联系管理员登记产品后再配置来源。');
  }
  let searchTimer;
  document.getElementById('source-product-search').addEventListener('input', event=>{
    if(editing) return;
    clearTimeout(searchTimer);
    searchTimer=setTimeout(()=>loadProducts(event.target.value).catch(error=>notify(error.message)),300);
  });
  (async () => { await loadProducts(); await reload(); })().catch(error=>notify(error.message));
});
