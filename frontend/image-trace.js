'use strict';

// Sample just the chosen area. Coordinates inside the tracer are image pixels.
function traceRaster(image, a, b, forLine) {
  const w = image.naturalWidth, h = image.naturalHeight;
  const x1 = a[0]*w, y1 = a[1]*h, x2 = b[0]*w, y2 = b[1]*h;
  const padding = forLine ? Math.hypot(x2-x1,y2-y1)*.34+4 : 4;
  const left = Math.max(0,Math.floor(Math.min(x1,x2)-padding));
  const top = Math.max(0,Math.floor(Math.min(y1,y2)-padding));
  const width = Math.min(w,Math.ceil(Math.max(x1,x2)+padding))-left;
  const height = Math.min(h,Math.ceil(Math.max(y1,y2)+padding))-top;
  const scale = Math.min(1,560/Math.max(width,height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1,Math.round(width*scale));
  canvas.height = Math.max(1,Math.round(height*scale));
  const ctx = canvas.getContext('2d',{willReadFrequently:true});
  ctx.drawImage(image,left,top,width,height,0,0,canvas.width,canvas.height);
  const pixels = ctx.getImageData(0,0,canvas.width,canvas.height).data;
  const sx = canvas.width/width, sy = canvas.height/height;
  const point = (x,y) => [(x-left)*sx,(y-top)*sy];
  function index(x,y) {
    const c = Math.max(0,Math.min(canvas.width-1,Math.round(x)));
    const r = Math.max(0,Math.min(canvas.height-1,Math.round(y)));
    return 4*(r*canvas.width+c);
  }
  function difference(i,j) {
    return (Math.abs(pixels[i]-pixels[j])+Math.abs(pixels[i+1]-pixels[j+1])+Math.abs(pixels[i+2]-pixels[j+2]))/3;
  }
  return {
    start:point(x1,y1),end:point(x2,y2),
    normalized:([x,y]) => [Math.min(1,Math.max(0,(left+x/sx)/w)),Math.min(1,Math.max(0,(top+y/sy)/h))],
    contrast(x,y,nx,ny,ridge) {
      if (x<0 || x>=canvas.width || y<0 || y>=canvas.height) return 0;
      const inside = index(x-2*nx,y-2*ny), outside = index(x+2*nx,y+2*ny);
      const edge = difference(inside,outside);
      if (!ridge) return edge;
      const center = index(x,y);
      return Math.max(edge*.78,Math.min(difference(center,inside),difference(center,outside)));
    }
  };
}

// Find a continuous set of offsets across samples along a cable or around a perimeter.
function traceOffsets(scores, start, end, smoothness) {
  const n = scores.length, width = scores[0].length;
  const previous = new Int16Array(n*width);
  let costs = scores[0].map((s,j)=>start == null || j===start ? -s : Infinity);
  for (let i=1; i<n; i++) {
    const next = new Float64Array(width);
    for (let j=0; j<width; j++) {
      let best = Infinity, from = j;
      for (let k=Math.max(0,j-4); k<=Math.min(width-1,j+4); k++) {
        const step = j-k, cost = costs[k]+smoothness*step*step;
        if (cost<best) { best=cost; from=k; }
      }
      next[j]=best-scores[i][j];
      previous[i*width+j]=from;
    }
    costs=next;
  }
  let j=end ?? costs.indexOf(Math.min(...costs));
  const offsets = new Array(n);
  for (let i=n-1; i>=0; i--) {
    offsets[i]=j;
    j=previous[i*width+j];
  }
  return offsets;
}

// Keep editable bends, dropping intermediate samples below the pixel tolerance.
function simplifyTrace(points,tolerance) {
  const a=points[0], b=points.at(-1), dx=b[0]-a[0], dy=b[1]-a[1];
  const length=dx*dx+dy*dy;
  let farthest=0, split=0;
  for (let i=1; i<points.length-1; i++) {
    const [x,y]=points[i];
    const t=length ? Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/length)) : 0;
    const distance=Math.hypot(x-a[0]-t*dx,y-a[1]-t*dy);
    if (distance>farthest) { farthest=distance; split=i; }
  }
  if (farthest<=tolerance) return [a,b];
  return simplifyTrace(points.slice(0,split+1),tolerance).slice(0,-1).concat(simplifyTrace(points.slice(split),tolerance));
}

function fitImagePath(image,type,a,b) {
  const line=type==='polyline';
  const raster=traceRaster(image,a,b,line);
  const [x,y]=raster.start, dx=raster.end[0]-x, dy=raster.end[1]-y;
  const length=Math.hypot(dx,dy);
  if (line ? length<5 : Math.min(Math.abs(dx),Math.abs(dy))<5) return null;
  const steps=line ? Math.ceil(length/2) : 96;
  const radius=line ? Math.max(4,Math.min(64,Math.ceil(length*.31))) : 36;
  const cols=line ? 2*radius+1 : radius+1;
  const scores=[], contrasts=[], positions=[];
  for (let i=0; i<=steps; i++) {
    const t=i/steps, angle=t*2*Math.PI;
    const nx=line ? -dy/length : Math.cos(angle);
    const ny=line ? dx/length : Math.sin(angle);
    const reach=line ? 0 : Math.min(Math.abs(dx)/(2*Math.max(.00001,Math.abs(nx))),Math.abs(dy)/(2*Math.max(.00001,Math.abs(ny))));
    const row=[], values=[], points=[];
    for (let j=0; j<cols; j++) {
      const offset=line ? j-radius : reach*(.20+.80*j/radius);
      const px=x+dx*(line ? t : .5)+nx*offset, py=y+dy*(line ? t : .5)+ny*offset;
      const strength=raster.contrast(px,py,nx,ny,line);
      const bias=line ? Math.abs(offset)/radius : Math.abs(j/radius-.8);
      row.push(Math.min(100,strength)-bias*10);
      values.push(strength); points.push([px,py]);
    }
    scores.push(row); contrasts.push(values); positions.push(points);
  }
  // Close the contour at the same offset on its first and last ray.
  const anchor=line ? radius : traceOffsets(scores,null,null,1.4)[0];
  const offsets=traceOffsets(scores,anchor,anchor,line ? 2.4 : 1.4);
  const supported=offsets.filter((j,i)=>contrasts[i][j]>=14).length;
  if (supported<offsets.length*(line ? .54 : .58)) return null;
  const points=offsets.map((j,i)=>positions[i][j]);
  const tolerance=Math.max(.85,Math.min(2.6,length*.006));
  const result=simplifyTrace(points,tolerance);
  if (!line) result.pop();
  const normalized=result.map(raster.normalized);
  return validPath(type,normalized) ? normalized : null;
}
