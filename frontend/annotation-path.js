'use strict';

function isPathType(type) {
  return type === 'polyline' || type === 'polygon';
}

function pathBounds(points) {
  let left = 1, top = 1, right = 0, bottom = 0;
  for (const [x,y] of points) {
    left = Math.min(left,x);
    top = Math.min(top,y);
    right = Math.max(right,x);
    bottom = Math.max(bottom,y);
  }
  return {x:left, y:top, w:right-left, h:bottom-top};
}

function validPath(type, points) {
  if (!Array.isArray(points) || !points.every(p => Array.isArray(p) && p.length === 2 &&
    p.every(n => Number.isFinite(n) && n >= 0 && n <= 1))) return false;
  const distinct = new Set(points.map(p => p.join(','))).size;
  if (type === 'polyline') return distinct >= 2;
  if (distinct < 3) return false;
  const [x,y] = points[0];
  const [a,b] = points.find(p => p[0] !== x || p[1] !== y);
  return points.some(([u,v]) => Math.abs((a-x)*(v-y)-(b-y)*(u-x)) > 1e-12);
}

function pathLayer(type, points, vertices) {
  const coords = points.map(p => p.join(',')).join(' ');
  const line = '<' + type + ' class="path-ink" points="' + coords + '" vector-effect="non-scaling-stroke"/>';
  const nodes = vertices ? points.map(([x,y],i) =>
    `<i class="path-node" data-vertex="${i}" style="left:${100*x}%;top:${100*y}%"></i>`).join('') : '';
  return '<svg viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">' + line + '</svg>' + nodes;
}

function strokeAnnotation(ctx, box, width, height) {
  if (!isPathType(box.type)) {
    ctx.strokeRect(box.x*width,box.y*height,box.w*width,box.h*height);
    return;
  }
  ctx.beginPath();
  box.points.forEach(([x,y],i) => i ? ctx.lineTo(x*width,y*height) : ctx.moveTo(x*width,y*height));
  if (box.type === 'polygon') {
    ctx.closePath();
    ctx.save();
    ctx.fillStyle = 'rgba(105,189,255,.18)';
    ctx.fill();
    ctx.restore();
  }
  ctx.stroke();
}

function movePath(drag, point) {
  const box = drag.original;
  const dx = Math.max(-box.x, Math.min(1-box.x-box.w,point[0]-drag.start[0]));
  const dy = Math.max(-box.y, Math.min(1-box.y-box.h,point[1]-drag.start[1]));
  const points = box.points.map(([x,y],i) => drag.vertex === undefined
    ? [Math.max(0,Math.min(1,x+dx)),Math.max(0,Math.min(1,y+dy))]
    : i === Number(drag.vertex) ? point : [x,y]);
  return validPath(box.type,points) ? {points,...pathBounds(points)} : {points:box.points,...pathBounds(box.points)};
}
