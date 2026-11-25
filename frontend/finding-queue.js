'use strict';

let activeFinding;

function pendingFindings() {
  const linked = new Map();
  const levels = ['urgent','review','unverified','normal','empty'];
  for (const record of records.objects) {
    if (!record.frame || !record.box) continue;
    const key = JSON.stringify([record.frame,record.box]);
    const old = linked.get(key);
    if (!old || levels.indexOf(sectionPriority(record)) < levels.indexOf(sectionPriority(old))) linked.set(key,record);
  }
  const items = [];
  for (const frame of records.frames) {
    for (const box of frame.boxes || []) {
      if (boxVerdict(frame,box.id)) continue;
      const key = JSON.stringify([frame.id,box.id]);
      const record = linked.get(key);
      const confidence = frame.findingsByBox?.[box.id]?.confidence ?? record?.confidence;
      items.push({key,frame,box,record,confidence:Number.isFinite(confidence) ? confidence : null,
        priority:record ? sectionPriority(record) : 'unverified'});
    }
  }
  return items.sort((a,b) => levels.indexOf(a.priority)-levels.indexOf(b.priority)
    || (a.confidence ?? Infinity)-(b.confidence ?? Infinity));
}

function renderFindingQueue() {
  const items = pendingFindings();
  activeFinding = items.find(item=>item.key === activeFinding?.key) || items[0];
  const host = $('finding-content');
  $('finding-actions').hidden = !activeFinding;
  $('finding-count').textContent = 'Осталось: ' + items.length;
  if (!activeFinding) {
    host.textContent = 'Все доступные рамки проверены.';
    return;
  }
  const {frame,box,record,confidence,priority} = activeFinding;
  host.innerHTML = cropHTML(frame,box) + '<div class="finding-meta"><strong>' + escapeHTML(checkedLabel(frame,box)) +
    '</strong><span>' + escapeHTML(sectionName(priority)) + (confidence !== null ? ' · Уверенность ' + confidence + '%' : '') +
    '</span><small>' + escapeHTML([record?.place,frame.name].filter(Boolean).join(' · ')) + '</small></div>';
}

function reviewFinding(action) {
  if (!activeFinding) return;
  const {frame,box} = activeFinding;
  if (action === 'edit') {
    openEditor(frame.id,box.id);
    return;
  }
  saveBoxVerdict(frame,box,action);
  activeFinding = null;
  renderFindingQueue();
}

function openFindingQueue() {
  activeFinding = null;
  renderFindingQueue();
  $('finding-dialog').showModal();
}

const findingDialog = document.getElementById('finding-dialog');
findingDialog.addEventListener('click',event=>{
  const button = event.target.closest('[data-finding-action]');
  if (button) reviewFinding(button.dataset.findingAction);
});
findingDialog.addEventListener('keydown',event=>{
  if (event.repeat || event.isComposing || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  const action = {KeyA:'accepted',KeyE:'edit',KeyR:'rejected'}[event.code];
  if (!action) return;
  event.preventDefault();
  reviewFinding(action);
});
document.getElementById('annotator').addEventListener('close',()=>{
  if (findingDialog.open) renderFindingQueue();
});
findingDialog.addEventListener('close',()=>{
  activeFinding = null;
  if (state.view === 'overview') renderOverview();
});
