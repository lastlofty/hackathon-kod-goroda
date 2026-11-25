'use strict';

// A tile-independent overview also prints when the map provider is offline.
function atlasOverview(route, sections) {
  if (!route.points?.length) return '<p>Геометрия маршрута отсутствует.</p>';
  const [lon,lat] = route.points[0];
  const cosLat = Math.cos(lat*Math.PI/180);
  const xy = ([x,y]) => [(x-lon)*cosLat,lat-y];
  const coords = route.points.map(xy);
  let left=0, right=0, top=0, bottom=0;
  for (const [x,y] of coords) {
    left=Math.min(left,x); right=Math.max(right,x);
    top=Math.min(top,y); bottom=Math.max(bottom,y);
  }
  const scale = Math.min(620/Math.max(right-left,.000001),330/Math.max(bottom-top,.000001));
  const project = point => {
    const [x,y] = xy(point);
    return [340 + (x-(right+left)/2)*scale, 200 + (y-(bottom+top)/2)*scale];
  };
  const points = path => path.map(p => project(p).join(',')).join(' ');
  const markers = sections.map(part => {
    const [x,y] = project(part.path[Math.floor((part.path.length-1)/2)]);
    return `<g><circle cx="${x}" cy="${y}" r="10" fill="#10293f"/><text x="${x}" y="${y+4}" text-anchor="middle" fill="white" font-size="11">${part.index+1}</text></g>`;
  });
  return `<svg class="atlas-map" viewBox="0 0 680 400" aria-label="Схема маршрута с номерами проблемных участков" role="img">
    <polyline points="${points(route.points)}" fill="none" stroke="#566c80" stroke-width="4" stroke-linejoin="round"/>
    ${sections.map(p=>`<polyline points="${points(p.path)}" fill="none" stroke="${p.priority==='urgent'?'#b73929':'#7256a6'}" stroke-width="6"/>`).join('')}
    ${markers.join('')}<text x="637" y="28" fill="#354657">С ↑</text></svg>`;
}

function atlasPhoto(frame) {
  if (!frame) return '<p>Снимок отсутствует.</p>';
  return `<figure class="atlas-photo"><div><img src="${escapeHTML(frame.src)}" alt="Кадр обследования">${reportBoxes(frame).map(box=>boxHTML(box)).join('')}</div></figure>`;
}

function atlasEntry(record) {
  const frame = frameById(record.frame);
  return `<div class="atlas-entry"><strong>${escapeHTML(displayId(record))} · ${escapeHTML(recordLabel(record))}</strong>
    <p class="atlas-address">${escapeHTML(record.place || (isValidPoint(record.point) ? formatPoint(record.point) : 'Адрес не указан'))}</p>
    <p>${escapeHTML(crewReason(record))}</p>
    ${atlasPhoto(frame)}</div>`;
}

function openRouteAtlas() {
  const route = currentSurveyRoute();
  if (!route) return;
  const actionable = r => ['review','urgent'].includes(sectionPriority(r));
  const sections = routeSections(route).filter(part=>part.members.some(actionable));
  const groups = sections.map(part=>({title:'Участок ' + (part.index+1) + ' · ' + sectionRange(part), members:part.members.filter(actionable)}));
  const unlocated = routeRecords(route).filter(r=>!isValidPoint(r.point) && actionable(r));
  if (unlocated.length) groups.push({title:'Точки без привязки к участку',members:unlocated});
  const pages = [];
  const name = escapeHTML(route.name);
  for (const group of groups) {
    // Two photos per sheet leave enough room for addresses and field notes on A4.
    for (let i=0; i<group.members.length; i+=2) {
      pages.push(`<section class="atlas-sheet${i+1 === group.members.length ? ' single-stop' : ''}"><p>${name}</p><h2>${group.title}${i ? ' · продолжение' : ''}</h2>
        ${group.members.slice(i,i+2).map(atlasEntry).join('')}</section>`);
    }
  }
  $('atlas-body').innerHTML = `<section class="atlas-sheet"><h2>${name}</h2>
    <p>Длина маршрута · ${Math.round(route.distance || 0).toLocaleString('ru-RU')} м</p>
    ${atlasOverview(route,sections)}
    <p>${sections.length ? 'Номера на схеме соответствуют номерам участков.' : 'Проблемных участков с координатами нет.'}</p>
    ${sections.length ? '<ul>' + sections.map(part=>'<li>Участок ' + (part.index+1) + ' · ' + sectionRange(part) + ' · ' + sectionName(part.priority) + '</li>').join('') + '</ul>' : ''}
    <p>Участков для проверки · ${sections.length} &nbsp; Точек для проверки · ${groups.reduce((n,g)=>n+g.members.length,0)}</p></section>` + pages.join('');
  const body = $('atlas-body');
  const addresses = body.querySelectorAll('.atlas-address');
  const tasks = groups.flatMap(group=>group.members).map((r,i) =>
    !r.place && isValidPoint(r.point) ? showPointAddress(r,addresses[i],formatPoint(r.point)) : null);
  const imageTasks = Array.from(body.querySelectorAll('img'),async image => {
    try { await image.decode(); }
    catch { image.closest('figure').replaceChildren(document.createTextNode('Снимок недоступен.')); }
  });
  body.ready = Promise.allSettled([...tasks,...imageTasks]);
  $('report-dialog').close();
  $('atlas-dialog').showModal();
}

async function printRouteAtlas() {
  await $('atlas-body').ready;
  if ($('atlas-dialog').open) window.print();
}
