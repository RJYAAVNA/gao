document.addEventListener('DOMContentLoaded', () => {
  const discovery = document.getElementById('ccb-discover');
  if (!discovery) return;
  const status = document.getElementById('ccb-status');
  const mapping = document.getElementById('ccb-mapping');
  const productSelect = document.getElementById('ccb-product');
  const bankSelect = document.getElementById('ccb-bank');
  let selected = null, discoveryJob = null, products = [], institutions = [];
  async function api(url, method='GET', body) {
    const response = await ledgerIdentity.api(url, {method, headers: body ? {'Content-Type':'application/json'} : {}, body:body ? JSON.stringify(body):undefined});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '请求失败');
    return data;
  }
  function showIdentity() {
    const product = products.find(p=>p.id===productSelect.value);
    document.getElementById('ccb-confirm').checked=false;
    document.getElementById('ccb-identity').textContent=product ?
      `发行机构：${institutions.find(i=>i.id===product.issuer_id)?.name || '待核对'}；产品代码：${product.issuer_code}；份额类别：${product.share_class}；币种：${product.currency}` : '';
  }
  async function loadProducts(keyword='') {
    const query = keyword ? '&keyword='+encodeURIComponent(keyword) : '';
    products = await api('/api/catalog/products?limit=200'+query);
    productSelect.replaceChildren();
    for(const product of products) {
      const option=document.createElement('option'); option.value=product.id;
      option.textContent=product.name+' · '+product.issuer_code;
      productSelect.append(option);
    }
    showIdentity();
  }
  productSelect.addEventListener('change',showIdentity);
  let searchTimer;
  document.getElementById('ccb-product-search').addEventListener('input',event=>{
    clearTimeout(searchTimer); searchTimer=setTimeout(()=>loadProducts(event.target.value).catch(e=>status.textContent=e.message),300);
  });
  discovery.addEventListener('submit', async event=>{
    event.preventDefault(); const button=discovery.querySelector('button');button.disabled=true;
    mapping.hidden=true;document.getElementById('ccb-candidates').replaceChildren();
    try {
      const page=Number(document.getElementById('ccb-page').value);
      const receipt=await api('/api/admin/ccb/discovery','POST',{first_page:page,last_page:page});
      discoveryJob=receipt.job_id; status.textContent='正在读取公开目录…';
      for(let i=0;i<60;i++) {
        await new Promise(resolve=>setTimeout(resolve,2000));
        const job=await api('/api/admin/ccb/discovery/'+discoveryJob);
        if(job.status==='succeeded') {
          const result=job.result;
          status.textContent=`第 ${result.page}/${result.total_pages} 页，公开目录共 ${result.total_records} 条。以下候选尚未关联账本产品。`;
          for(const candidate of result.candidates) {
            const row=document.createElement('p'); row.textContent=candidate.name+' · '+candidate.issuer_name+' · '+candidate.channel_code+' ';
            const select=document.createElement('button');select.type='button';select.className='btn';select.textContent='核对映射';
            select.addEventListener('click',()=>{
              selected=candidate;mapping.hidden=false;
              document.getElementById('ccb-selected').textContent=`建行销售代码 ${candidate.channel_code}；披露发行机构 ${candidate.issuer_name}；${candidate.name}`;
              showIdentity();mapping.scrollIntoView({block:'start'});
            });row.append(select);document.getElementById('ccb-candidates').append(row);
          }
          return;
        }
        if(['failed','needs_action','cancelled'].includes(job.status)) throw new Error('目录获取未完成，请查看管理员任务详情后重试');
      }
      status.textContent='任务仍在后台运行，请稍后通过管理员任务查看结果。';
    } catch(error){status.textContent=error.message;} finally{button.disabled=false;}
  });
  mapping.addEventListener('submit',async event=>{
    event.preventDefault();const button=mapping.querySelector('button[type=submit]');button.disabled=true;
    try {
      const product=products.find(p=>p.id===productSelect.value);
      if(!selected || !product || !bankSelect.value) throw new Error('请先选择候选、账本产品和建设银行机构');
      await api('/api/admin/ccb/sources','POST',{discovery_job_id:discoveryJob,channel_code:selected.channel_code,
        product_id:product.id,bank_id:bankSelect.value,issuer_id:product.issuer_id,currency:product.currency,
        share_class:product.share_class,review_note:document.getElementById('ccb-note').value,
        identity_confirmed:document.getElementById('ccb-confirm').checked});
      status.textContent='映射已批准，首次行情同步已排队。';mapping.hidden=true;
    }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
  });
  (async()=>{
    institutions=await api('/api/catalog/institutions');
    for(const institution of institutions.filter(i=>i.type==='bank' && i.name.includes('建设银行'))){
      const option=document.createElement('option');option.value=institution.id;option.textContent=institution.name;bankSelect.append(option);
    }
    await loadProducts();
  })().catch(error=>status.textContent=error.message);
});
