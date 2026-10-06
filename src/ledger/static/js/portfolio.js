document.getElementById('revalue')?.addEventListener('click', async event => {
  const button = event.currentTarget, status = document.getElementById('valuation-status');
  button.disabled = true; status.textContent = '正在提交计算任务…';
  try {
    const response = await ledgerIdentity.api('/api/valuation/recalculate', {method: 'POST'});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || '提交失败');
    status.textContent = '任务已提交，正在计算…';
    for (let i = 0; i < 120; i++) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      const poll = await ledgerIdentity.api('/api/my/jobs/' + body.job_id);
      const job = await poll.json();
      if (!poll.ok) throw new Error('无法读取任务状态');
      if (job.status === 'succeeded') { location.reload(); return; }
      if (['failed','cancelled','needs_action'].includes(job.status)) throw new Error('计算未完成，请检查交易记录后重试');
    }
    status.textContent = '后台仍在计算，请稍后刷新。';
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
});
