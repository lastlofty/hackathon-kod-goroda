'use strict';

const inspectionCollections = ['frames', 'entities', 'types', 'standalone_findings'];
let inspectionCache;
let inspectionStream;
let inspectionRevision = 0;

function inspectionPath(endpoint) {
  return '/api/v1/inspection/' + endpoint + '?' + new URLSearchParams({workspace: workspaceSlug});
}

function replaceInspectionBatch(batch) {
  inspectionCache = Object.fromEntries(inspectionCollections.map(key =>
    [key, new Map(batch[key].map(row => [row.id, row]))]));
}

function inspectionFromCache() {
  const values = key => Array.from(inspectionCache[key].values());
  const frames = values('frames').sort((a, b) => Date.parse(b.captured_at || b.created_at) - Date.parse(a.captured_at || a.created_at));
  const findings = values('standalone_findings').concat(frames.flatMap(frame => frame.findings));
  findings.sort((a, b) => Date.parse(b.observed_at) - Date.parse(a.observed_at) || a.id.localeCompare(b.id));
  return buildBackendInspection(values('types'), values('entities'), frames, findings);
}

async function loadBackendInspection() {
  try {
    replaceInspectionBatch(await backendRequest(inspectionPath('frames')));
    return inspectionFromCache();
  } catch (error) {
    if (error.status !== 404) throw error;
    return loadLegacyInspection();
  }
}

function startInspectionStream(onUpdate) {
  if (!window.EventSource || inspectionStream) return;
  const stream = new EventSource(new URL(inspectionPath('stream'), backendBase));
  inspectionStream = stream;
  stream.addEventListener('open', renderLiveStatus);
  stream.addEventListener('error', renderLiveStatus);
  async function receive(event) {
    const revision = ++inspectionRevision;
    try {
      const payload = JSON.parse(event.data);
      if (event.type === 'batch') {
        replaceInspectionBatch(payload);
      } else {
        for (const key of inspectionCollections) {
          for (const id of payload.remove[key] || []) inspectionCache[key].delete(id);
          for (const row of payload.upsert[key] || []) inspectionCache[key].set(row.id, row);
        }
      }
      const result = await inspectionFromCache();
      if (revision === inspectionRevision) onUpdate(result);
    } catch {
      if (revision === inspectionRevision) {
        stream.close();
        inspectionStream = null;
        setTimeout(() => startInspectionStream(onUpdate), 2000);
      }
    }
  }
  stream.addEventListener('batch', receive);
  stream.addEventListener('changes', receive);
}
