/**
 * Pareto Anywhere — Floor Plan Builder
 * Canvas-based drawing tool for BLE floor plan mapping
 */

// ─── Constants ───────────────────────────────────────────────────────────────
const GRID_SIZE = 20;
const SNAP_THRESHOLD = 10;

const TOOL_COLORS = {
  'wall-concrete':  { stroke: '#4a4a4a', fill: null, width: 6 },
  'wall-drywall':   { stroke: '#7a7a7a', fill: null, width: 3, dash: [6, 3] },
  'wall-glass':     { stroke: '#88bbcc', fill: 'rgba(136,187,204,0.15)', width: 2, dash: [4, 2] },
  'wall-exterior':  { stroke: '#2a2a2a', fill: null, width: 8 },
  'door-single':    { stroke: '#006400', fill: 'rgba(0,100,0,0.08)', width: 2 },
  'door-double':    { stroke: '#006400', fill: 'rgba(0,100,0,0.08)', width: 2 },
  'window':         { stroke: '#5599aa', fill: 'rgba(85,153,170,0.2)', width: 2 },
  'room':           { stroke: '#006400', fill: 'rgba(0,100,0,0.06)', width: 2 },
  'polygon':        { stroke: '#006400', fill: 'rgba(0,100,0,0.06)', width: 2 },
  'stairs':         { stroke: '#886633', fill: 'rgba(136,102,51,0.1)', width: 2 },
  'lift':           { stroke: '#445588', fill: 'rgba(68,85,136,0.1)', width: 2 },
  'column':         { stroke: '#555555', fill: 'rgba(80,80,80,0.4)', width: 2 },
  'text':           { stroke: '#006400', fill: null, width: 0 },
  'gateway':        { stroke: '#00aa44', fill: 'rgba(0,170,68,0.15)', width: 2 },
};

// ─── State ────────────────────────────────────────────────────────────────────
let state = {
  tool: 'select',
  floors: [{ id: 1, name: 'Floor 1', elements: [] }],
  currentFloor: 0,
  selected: null,
  zoom: 1,
  panX: 0,
  panY: 0,
  drawing: false,
  drawStart: null,
  drawCurrent: null,
  polygonPoints: [],
  history: [],
  redoStack: [],
  gridVisible: true,
  snapEnabled: true,
  overlayImage: null,
  overlayOpacity: 0.35,
  overlayVisible: true,
  dragging: false,
  dragStartPos: null,
  dragElementStart: null,
  draggingEndpoint: null, // 'p1' | 'p2' | null
  panning: false,
  panStart: null,
  textPending: null,
};

const LINE_TYPES = ['wall-concrete','wall-drywall','wall-glass','wall-exterior',
                    'door-single','door-double','window'];

// Return 'p1', 'p2', or null — whether wx,wy is near an endpoint of a selected wall
function endpointHitTest(wx, wy) {
  if (!state.selected) return null;
  const el = state.floors[state.currentFloor].elements.find(e => e.id === state.selected);
  if (!el || !LINE_TYPES.includes(el.type)) return null;
  const thresh = Math.max(8, 10 / state.zoom);
  if (Math.hypot(wx - el.x1, wy - el.y1) < thresh) return 'p1';
  if (Math.hypot(wx - el.x2, wy - el.y2) < thresh) return 'p2';
  return null;
}

let nextId = 1;
function genId() { return `el_${nextId++}`; }

// ─── Canvas Setup ─────────────────────────────────────────────────────────────
const wrapper = document.getElementById('canvasWrapper');
const mainCanvas = document.getElementById('mainCanvas');
const overlayCanvas = document.getElementById('overlayCanvas');
const interactCanvas = document.getElementById('interactCanvas');
const mCtx = mainCanvas.getContext('2d');
const oCtx = overlayCanvas.getContext('2d');
const iCtx = interactCanvas.getContext('2d');

function resizeCanvases() {
  const w = wrapper.clientWidth, h = wrapper.clientHeight;
  [mainCanvas, overlayCanvas, interactCanvas].forEach(c => {
    c.width = w; c.height = h;
  });
  render();
}
window.addEventListener('resize', resizeCanvases);

// ─── Coordinate Helpers ───────────────────────────────────────────────────────
function screenToWorld(sx, sy) {
  return {
    x: (sx - state.panX) / state.zoom,
    y: (sy - state.panY) / state.zoom
  };
}

function worldToScreen(wx, wy) {
  return {
    x: wx * state.zoom + state.panX,
    y: wy * state.zoom + state.panY
  };
}

function snap(v) {
  if (!state.snapEnabled) return v;
  return Math.round(v / GRID_SIZE) * GRID_SIZE;
}

function snapPoint(p) {
  return { x: snap(p.x), y: snap(p.y) };
}

// ─── Rendering ───────────────────────────────────────────────────────────────
function render() {
  const w = mainCanvas.width, h = mainCanvas.height;
  mCtx.clearRect(0, 0, w, h);

  // Background
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  mCtx.fillStyle = isDark ? '#111611' : '#e8ece8';
  mCtx.fillRect(0, 0, w, h);

  // Grid
  if (state.gridVisible) drawGrid(mCtx, w, h, isDark);

  // Elements
  mCtx.save();
  mCtx.translate(state.panX, state.panY);
  mCtx.scale(state.zoom, state.zoom);
  const elements = state.floors[state.currentFloor].elements;
  elements.forEach(el => drawElement(mCtx, el, false));
  mCtx.restore();

  // Overlay image
  renderOverlay(w, h);

  // Interact layer
  renderInteract(w, h);
}

function drawGrid(ctx, w, h, isDark) {
  const gs = GRID_SIZE * state.zoom;
  const offX = ((state.panX % gs) + gs) % gs;
  const offY = ((state.panY % gs) + gs) % gs;

  ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.06)';
  ctx.lineWidth = 1;

  for (let x = offX; x < w; x += gs) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
  for (let y = offY; y < h; y += gs) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }

  // Major grid every 5
  const mgs = gs * 5;
  const mOffX = ((state.panX % mgs) + mgs) % mgs;
  const mOffY = ((state.panY % mgs) + mgs) % mgs;
  ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.12)';
  for (let x = mOffX; x < w; x += mgs) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
  for (let y = mOffY; y < h; y += mgs) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
}

function drawElement(ctx, el, isPreview) {
  const cfg = TOOL_COLORS[el.type] || { stroke: '#006400', fill: null, width: 2 };
  const strokeColor = el.color || cfg.stroke;
  const fillColor = el.fill !== undefined ? el.fill : cfg.fill;
  const lw = (el.width !== undefined ? el.width : cfg.width) / state.zoom;
  
  ctx.save();
  ctx.strokeStyle = strokeColor;
  ctx.lineWidth = Math.max(lw, 1 / state.zoom);
  ctx.fillStyle = fillColor || 'transparent';
  if (cfg.dash) ctx.setLineDash(cfg.dash.map(d => d / state.zoom));
  else ctx.setLineDash([]);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  switch (el.type) {
    case 'wall-concrete':
    case 'wall-drywall':
    case 'wall-glass':
    case 'wall-exterior':
      drawWall(ctx, el);
      break;
    case 'door-single':
      drawDoorSingle(ctx, el);
      break;
    case 'door-double':
      drawDoorDouble(ctx, el);
      break;
    case 'window':
      drawWindow(ctx, el);
      break;
    case 'room':
      drawRoom(ctx, el, fillColor);
      break;
    case 'polygon':
      drawPolygon(ctx, el, fillColor);
      break;
    case 'stairs':
      drawStairs(ctx, el);
      break;
    case 'lift':
      drawLift(ctx, el);
      break;
    case 'column':
      drawColumn(ctx, el, fillColor);
      break;
    case 'text':
      drawText(ctx, el);
      break;
    case 'gateway':
      drawGateway(ctx, el);
      break;
  }
  ctx.restore();

  // Selection indicator
  if (el.id === state.selected && !isPreview) {
    drawSelectionRing(ctx, el);
  }
}

function drawWall(ctx, el) {
  ctx.beginPath();
  ctx.moveTo(el.x1, el.y1);
  ctx.lineTo(el.x2, el.y2);
  ctx.stroke();
}

function drawDoorSingle(ctx, el) {
  const dx = el.x2 - el.x1, dy = el.y2 - el.y1;
  const len = Math.sqrt(dx*dx + dy*dy);
  if (len < 2) return;
  ctx.beginPath();
  ctx.moveTo(el.x1, el.y1);
  ctx.lineTo(el.x2, el.y2);
  ctx.stroke();
  // Arc
  ctx.beginPath();
  const angle = Math.atan2(dy, dx);
  ctx.arc(el.x1, el.y1, len, angle, angle - Math.PI/2, true);
  ctx.stroke();
}

function drawDoorDouble(ctx, el) {
  const mx = (el.x1+el.x2)/2, my = (el.y1+el.y2)/2;
  const dx = (el.x2-el.x1)/2, dy = (el.y2-el.y1)/2;
  const halfLen = Math.sqrt(dx*dx+dy*dy);
  const angle = Math.atan2(dy, dx);
  ctx.beginPath(); ctx.moveTo(el.x1, el.y1); ctx.lineTo(mx, my); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(mx, my); ctx.lineTo(el.x2, el.y2); ctx.stroke();
  ctx.beginPath(); ctx.arc(el.x1, el.y1, halfLen, angle, angle - Math.PI/2, true); ctx.stroke();
  ctx.beginPath(); ctx.arc(el.x2, el.y2, halfLen, angle + Math.PI, angle + Math.PI + Math.PI/2, false); ctx.stroke();
}

function drawWindow(ctx, el) {
  ctx.beginPath();
  ctx.moveTo(el.x1, el.y1);
  ctx.lineTo(el.x2, el.y2);
  ctx.stroke();
  const dx = el.x2-el.x1, dy = el.y2-el.y1;
  const len = Math.sqrt(dx*dx+dy*dy);
  if (len < 4) return;
  const nx = -dy/len * 4, ny = dx/len * 4;
  // Double line for window
  ctx.beginPath();
  ctx.moveTo(el.x1 + nx, el.y1 + ny);
  ctx.lineTo(el.x2 + nx, el.y2 + ny);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(el.x1 - nx, el.y1 - ny);
  ctx.lineTo(el.x2 - nx, el.y2 - ny);
  ctx.stroke();
}

function drawRoom(ctx, el, fillColor) {
  const x = Math.min(el.x1, el.x2), y = Math.min(el.y1, el.y2);
  const w = Math.abs(el.x2-el.x1), h = Math.abs(el.y2-el.y1);
  if (fillColor) { ctx.fillStyle = fillColor; ctx.fillRect(x, y, w, h); }
  ctx.strokeRect(x, y, w, h);
  if (el.label) {
    ctx.font = `${(el.fontSize || 12)}px DM Sans, sans-serif`;
    ctx.fillStyle = ctx.strokeStyle;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(el.label, x + w/2, y + h/2);
  }
}

function drawPolygon(ctx, el, fillColor) {
  if (!el.points || el.points.length < 2) return;
  ctx.beginPath();
  ctx.moveTo(el.points[0].x, el.points[0].y);
  el.points.forEach((p, i) => { if (i > 0) ctx.lineTo(p.x, p.y); });
  if (el.closed) {
    ctx.closePath();
    if (fillColor) { ctx.fillStyle = fillColor; ctx.fill(); }
  }
  ctx.stroke();
  if (el.label && el.closed && el.points.length > 2) {
    const cx = el.points.reduce((s,p) => s+p.x, 0) / el.points.length;
    const cy = el.points.reduce((s,p) => s+p.y, 0) / el.points.length;
    ctx.font = `${(el.fontSize || 12)}px DM Sans`;
    ctx.fillStyle = ctx.strokeStyle;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(el.label, cx, cy);
  }
}

function drawStairs(ctx, el) {
  const x = Math.min(el.x1, el.x2), y = Math.min(el.y1, el.y2);
  const w = Math.abs(el.x2-el.x1), h = Math.abs(el.y2-el.y1);
  const rot = el.rotation || 0; // 0=right, 90=down, 180=left, 270=up
  const cx = x + w/2, cy = y + h/2;

  ctx.save();
  // Rotate around the bounding box centre
  ctx.translate(cx, cy);
  ctx.rotate(rot * Math.PI / 180);
  ctx.translate(-cx, -cy);

  ctx.strokeRect(x, y, w, h);

  // Step lines run perpendicular to travel direction (always vertical in local space)
  const steps = Math.max(1, Math.floor(w / 12));
  for (let i = 1; i <= steps; i++) {
    const sx = x + (i / steps) * w;
    ctx.beginPath(); ctx.moveTo(sx, y); ctx.lineTo(sx, y+h); ctx.stroke();
  }
  // Arrow pointing in travel direction (right in local space)
  ctx.beginPath();
  ctx.moveTo(x+8, y+h/2);
  ctx.lineTo(x+w-8, y+h/2);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x+w-16, y+h/2-6);
  ctx.lineTo(x+w-8, y+h/2);
  ctx.lineTo(x+w-16, y+h/2+6);
  ctx.stroke();

  ctx.restore();
}

function drawLift(ctx, el) {
  const x = Math.min(el.x1,el.x2), y = Math.min(el.y1,el.y2);
  const w = Math.abs(el.x2-el.x1), h = Math.abs(el.y2-el.y1);
  ctx.strokeRect(x, y, w, h);
  // Center divider
  ctx.beginPath(); ctx.moveTo(x+w/2, y); ctx.lineTo(x+w/2, y+h); ctx.stroke();
  // Up/down arrows in each half
  const arrowY = y + h/2;
  // Left half: up arrow
  ctx.beginPath(); ctx.moveTo(x+w/4, arrowY+8); ctx.lineTo(x+w/4, arrowY-8); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x+w/4-5, arrowY-2); ctx.lineTo(x+w/4, arrowY-8); ctx.lineTo(x+w/4+5, arrowY-2); ctx.stroke();
  // Right half: down arrow
  ctx.beginPath(); ctx.moveTo(x+3*w/4, arrowY-8); ctx.lineTo(x+3*w/4, arrowY+8); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x+3*w/4-5, arrowY+2); ctx.lineTo(x+3*w/4, arrowY+8); ctx.lineTo(x+3*w/4+5, arrowY+2); ctx.stroke();
  if (el.label) {
    ctx.font = `bold ${Math.max(8,9/state.zoom)}px JetBrains Mono`;
    ctx.fillStyle = ctx.strokeStyle;
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.fillText(el.label || 'LIFT', x+w/2, y+3);
  }
}

function drawColumn(ctx, el, fillColor) {
  const x = Math.min(el.x1,el.x2), y = Math.min(el.y1,el.y2);
  const w = Math.abs(el.x2-el.x1)||20, h = Math.abs(el.y2-el.y1)||20;
  if (fillColor) { ctx.fillStyle = fillColor; ctx.fillRect(x,y,w,h); }
  ctx.strokeRect(x,y,w,h);
  // X cross
  ctx.beginPath(); ctx.moveTo(x,y); ctx.lineTo(x+w,y+h); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x+w,y); ctx.lineTo(x,y+h); ctx.stroke();
}

function drawText(ctx, el) {
  if (!el.label) return;
  ctx.font = `${(el.fontSize||14)}px DM Sans, sans-serif`;
  ctx.fillStyle = el.color || '#006400';
  ctx.textAlign = 'left'; ctx.textBaseline = 'top';
  ctx.fillText(el.label, el.x1, el.y1);
}

function drawGateway(ctx, el) {
  const cx = el.x1, cy = el.y1, r = 10;
  // Circle
  ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI*2);
  if (el.fill) { ctx.fillStyle = el.fill; ctx.fill(); }
  ctx.stroke();
  // Wifi arcs
  for (let i = 1; i <= 3; i++) {
    ctx.beginPath();
    ctx.arc(cx, cy, r + i*8, -Math.PI*0.6, -Math.PI*0.1);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cy, r + i*8, Math.PI*1.1, Math.PI*1.6);
    ctx.stroke();
  }
  if (el.label) {
    ctx.font = `${Math.max(9,(el.fontSize||14)/state.zoom)}px JetBrains Mono`;
    ctx.fillStyle = ctx.strokeStyle;
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.fillText(el.label, cx, cy + r + 32);
  }
}

function drawSelectionRing(ctx, el) {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  ctx.save();
  ctx.strokeStyle = isDark ? 'rgba(0,200,0,0.7)' : 'rgba(0,120,0,0.7)';
  ctx.lineWidth = 1.5 / state.zoom;
  ctx.setLineDash([4/state.zoom, 3/state.zoom]);

  if (el.type === 'text' || el.type === 'gateway') {
    const r = el.type === 'gateway' ? 40 : 0;
    const pad = 8 / state.zoom;
    ctx.strokeRect(el.x1 - pad - r, el.y1 - pad - r, (r ? r*2 : 80/state.zoom) + pad*2, (r ? r*2 : 24/state.zoom) + pad*2);
  } else if (el.type === 'polygon' && el.points && el.points.length > 0) {
    const xs = el.points.map(p=>p.x), ys = el.points.map(p=>p.y);
    const pad = 8/state.zoom;
    ctx.strokeRect(Math.min(...xs)-pad, Math.min(...ys)-pad, Math.max(...xs)-Math.min(...xs)+pad*2, Math.max(...ys)-Math.min(...ys)+pad*2);
  } else if (el.x1 !== undefined && el.x2 !== undefined) {
    const pad = 8/state.zoom;
    const x = Math.min(el.x1,el.x2)-pad, y = Math.min(el.y1,el.y2)-pad;
    const w = Math.abs(el.x2-el.x1)+pad*2||pad*4, h = Math.abs(el.y2-el.y1)+pad*2||pad*4;
    ctx.strokeRect(x, y, w, h);
  }
  ctx.restore();

  // Draw draggable endpoint handles for wall/door/window types
  if (LINE_TYPES.includes(el.type) && el.x1 !== undefined) {
    const isDark2 = document.documentElement.getAttribute('data-theme') === 'dark';
    const r = 5 / state.zoom;
    ctx.save();
    ctx.setLineDash([]);
    ctx.lineWidth = 1.5 / state.zoom;
    [[el.x1, el.y1], [el.x2, el.y2]].forEach(([px, py]) => {
      ctx.beginPath();
      ctx.arc(px, py, r, 0, Math.PI * 2);
      ctx.fillStyle = isDark2 ? '#00cc44' : '#006400';
      ctx.fill();
      ctx.strokeStyle = isDark2 ? '#001a00' : '#ffffff';
      ctx.stroke();
    });
    ctx.restore();
  }
}

// ─── Overlay Rendering ────────────────────────────────────────────────────────
function renderOverlay(w, h) {
  oCtx.clearRect(0, 0, w, h);
  if (!state.overlayImage || !state.overlayVisible) return;
  oCtx.save();
  oCtx.globalAlpha = state.overlayOpacity;
  oCtx.translate(state.panX, state.panY);
  oCtx.scale(state.zoom, state.zoom);
  oCtx.drawImage(state.overlayImage, 0, 0);
  oCtx.restore();
}

// ─── Interact Layer (preview while drawing) ───────────────────────────────────
function renderInteract(w, h) {
  iCtx.clearRect(0, 0, w, h);
  if (!state.drawing || !state.drawStart || !state.drawCurrent) return;
  iCtx.save();
  iCtx.translate(state.panX, state.panY);
  iCtx.scale(state.zoom, state.zoom);

  const s = state.drawStart, c = state.drawCurrent;

  // Preview element
  const previewEl = buildElement(state.tool, s, c);
  if (previewEl) drawElement(iCtx, previewEl, true);

  // Polygon: draw in-progress line
  if (state.tool === 'polygon' && state.polygonPoints.length > 0) {
    const cfg = TOOL_COLORS['polygon'];
    iCtx.strokeStyle = cfg.stroke;
    iCtx.lineWidth = cfg.width / state.zoom;
    iCtx.setLineDash([]);
    iCtx.beginPath();
    iCtx.moveTo(state.polygonPoints[0].x, state.polygonPoints[0].y);
    state.polygonPoints.forEach((p,i) => { if(i>0) iCtx.lineTo(p.x, p.y); });
    iCtx.lineTo(c.x, c.y);
    iCtx.stroke();
    // Draw vertex dots
    state.polygonPoints.forEach(p => {
      iCtx.beginPath(); iCtx.arc(p.x, p.y, 4/state.zoom, 0, Math.PI*2);
      iCtx.fillStyle = cfg.stroke; iCtx.fill();
    });
  }
  iCtx.restore();
}

// ─── Element Factory ──────────────────────────────────────────────────────────
function buildElement(tool, start, end, extra = {}) {
  const cfg = TOOL_COLORS[tool] || {};
  const base = {
    id: genId(),
    type: tool,
    color: cfg.stroke,
    fill: cfg.fill,
    width: cfg.width,
    label: '',
    ...extra
  };

  if (['wall-concrete','wall-drywall','wall-glass','wall-exterior',
       'door-single','door-double','window'].includes(tool)) {
    return { ...base, x1: start.x, y1: start.y, x2: end.x, y2: end.y };
  }

  if (['room','stairs','lift','column'].includes(tool)) {
    return { ...base, x1: start.x, y1: start.y, x2: end.x, y2: end.y, fontSize: 14 };
  }

  if (tool === 'gateway') {
    return { ...base, x1: start.x, y1: start.y };
  }

  if (tool === 'text') {
    return { ...base, x1: start.x, y1: start.y, fontSize: 14 };
  }

  if (tool === 'polygon') {
    return null; // handled separately
  }

  return null;
}

// ─── History ──────────────────────────────────────────────────────────────────
function pushHistory() {
  state.history.push(JSON.stringify(state.floors));
  state.redoStack = [];
  if (state.history.length > 50) state.history.shift();
}

function undo() {
  if (!state.history.length) return;
  state.redoStack.push(JSON.stringify(state.floors));
  state.floors = JSON.parse(state.history.pop());
  state.selected = null;
  render(); updateStats(); updateFloorList();
}

function redo() {
  if (!state.redoStack.length) return;
  state.history.push(JSON.stringify(state.floors));
  state.floors = JSON.parse(state.redoStack.pop());
  state.selected = null;
  render(); updateStats(); updateFloorList();
}

// ─── Hit Testing ──────────────────────────────────────────────────────────────
function hitTest(wx, wy) {
  const elements = [...state.floors[state.currentFloor].elements].reverse();
  const thresh = 10 / state.zoom;

  for (const el of elements) {
    if (el.type === 'gateway') {
      const dx = wx-el.x1, dy = wy-el.y1;
      if (Math.sqrt(dx*dx+dy*dy) < 12/state.zoom) return el.id;
      continue;
    }
    if (el.type === 'text') {
      if (wx >= el.x1-4 && wx <= el.x1+100 && wy >= el.y1-4 && wy <= el.y1+20) return el.id;
      continue;
    }
    if (el.type === 'polygon') {
      if (!el.points || el.points.length < 2) continue;
      for (let i = 0; i < el.points.length - 1; i++) {
        if (distToSegment(wx, wy, el.points[i].x, el.points[i].y, el.points[i+1].x, el.points[i+1].y) < thresh) return el.id;
      }
      if (el.closed && el.points.length > 2) {
        const last = el.points[el.points.length-1], first = el.points[0];
        if (distToSegment(wx, wy, last.x, last.y, first.x, first.y) < thresh) return el.id;
      }
      continue;
    }
    if (el.x1 !== undefined && el.x2 !== undefined) {
      const isLine = ['wall-concrete','wall-drywall','wall-glass','wall-exterior','door-single','door-double','window'].includes(el.type);
      if (isLine) {
        if (distToSegment(wx, wy, el.x1, el.y1, el.x2, el.y2) < thresh) return el.id;
      } else {
        const x = Math.min(el.x1,el.x2), y = Math.min(el.y1,el.y2);
        const w = Math.abs(el.x2-el.x1), h = Math.abs(el.y2-el.y1);
        if (wx >= x-thresh && wx <= x+w+thresh && wy >= y-thresh && wy <= y+h+thresh) return el.id;
      }
    }
  }
  return null;
}

function distToSegment(px, py, ax, ay, bx, by) {
  const dx = bx-ax, dy = by-ay;
  const lenSq = dx*dx + dy*dy;
  if (lenSq === 0) return Math.hypot(px-ax, py-ay);
  let t = ((px-ax)*dx + (py-ay)*dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (ax+t*dx), py - (ay+t*dy));
}

// ─── Mouse Events ─────────────────────────────────────────────────────────────
interactCanvas.addEventListener('mousedown', onMouseDown);
interactCanvas.addEventListener('mousemove', onMouseMove);
interactCanvas.addEventListener('mouseup', onMouseUp);
interactCanvas.addEventListener('dblclick', onDblClick);
interactCanvas.addEventListener('wheel', onWheel, { passive: false });
interactCanvas.addEventListener('contextmenu', e => e.preventDefault());

function onMouseDown(e) {
  e.preventDefault();
  const rect = interactCanvas.getBoundingClientRect();
  const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
  const world = screenToWorld(sx, sy);

  // Middle mouse or Alt+drag = pan
  if (e.button === 1 || (e.button === 0 && e.altKey)) {
    state.panning = true;
    state.panStart = { sx, sy, px: state.panX, py: state.panY };
    interactCanvas.style.cursor = 'grabbing';
    return;
  }

  if (e.button === 2) {
    // Right click: cancel polygon or deselect
    if (state.tool === 'polygon' && state.polygonPoints.length > 0) {
      state.polygonPoints = [];
      state.drawing = false;
      render();
    } else {
      state.selected = null; render(); showProperties(null);
    }
    return;
  }

  if (state.tool === 'select') {
    // Check endpoint drag first (only if something is already selected)
    const ep = endpointHitTest(world.x, world.y);
    if (ep) {
      // Start endpoint drag — don't change selection
      const el = state.floors[state.currentFloor].elements.find(e => e.id === state.selected);
      state.draggingEndpoint = ep;
      state.dragElementStart = JSON.parse(JSON.stringify(el));
      render();
      return;
    }

    const hit = hitTest(world.x, world.y);
    state.selected = hit;
    if (hit) {
      const el = state.floors[state.currentFloor].elements.find(e => e.id === hit);
      showProperties(el);
      state.dragging = true;
      state.dragStartPos = { x: world.x, y: world.y };
      state.dragElementStart = JSON.parse(JSON.stringify(el));
    } else {
      showProperties(null);
      // Start panning
      state.panning = true;
      state.panStart = { sx, sy, px: state.panX, py: state.panY };
    }
    render();
    return;
  }

  if (state.tool === 'polygon') {
    const snapped = snapPoint(world);
    if (state.polygonPoints.length === 0) {
      state.drawing = true;
      state.polygonPoints = [snapped];
    } else {
      state.polygonPoints.push(snapped);
    }
    state.drawCurrent = snapped;
    render();
    return;
  }

  if (state.tool === 'gateway') {
    pushHistory();
    const snapped = snapPoint(world);
    const el = buildElement('gateway', snapped, snapped);
    el.label = 'GW-' + (state.floors[state.currentFloor].elements.filter(e=>e.type==='gateway').length+1);
    state.floors[state.currentFloor].elements.push(el);
    state.selected = el.id;
    showProperties(el);
    render(); updateStats();
    return;
  }

  if (state.tool === 'text') {
    const snapped = snapPoint(world);
    state.textPending = snapped;
    showTextModal();
    return;
  }

  // Start drawing
  state.drawing = true;
  state.drawStart = snapPoint(world);
  state.drawCurrent = state.drawStart;
}

function onMouseMove(e) {
  const rect = interactCanvas.getBoundingClientRect();
  const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
  const world = screenToWorld(sx, sy);
  const snapped = snapPoint(world);

  document.getElementById('cursorCoords').textContent = `${Math.round(world.x)}, ${Math.round(world.y)}`;

  if (state.panning) {
    state.panX = state.panStart.px + (sx - state.panStart.sx);
    state.panY = state.panStart.py + (sy - state.panStart.sy);
    render(); return;
  }

  // Endpoint drag
  if (state.draggingEndpoint && state.selected) {
    const el = state.floors[state.currentFloor].elements.find(e => e.id === state.selected);
    if (el) {
      if (state.draggingEndpoint === 'p1') {
        el.x1 = snapped.x; el.y1 = snapped.y;
      } else {
        el.x2 = snapped.x; el.y2 = snapped.y;
      }
      render();
    }
    return;
  }

  if (state.dragging && state.selected) {
    const dx = world.x - state.dragStartPos.x;
    const dy = world.y - state.dragStartPos.y;
    const el = state.floors[state.currentFloor].elements.find(e => e.id === state.selected);
    const src = state.dragElementStart;
    if (el) {
      if (el.type === 'polygon' && el.points) {
        el.points = src.points.map(p => ({ x: snap(p.x+dx), y: snap(p.y+dy) }));
      } else if (el.type === 'gateway' || el.type === 'text') {
        el.x1 = snap(src.x1 + dx);
        el.y1 = snap(src.y1 + dy);
      } else {
        el.x1 = snap(src.x1 + dx); el.y1 = snap(src.y1 + dy);
        el.x2 = snap(src.x2 + dx); el.y2 = snap(src.y2 + dy);
      }
      render();
    }
    return;
  }

  if (state.drawing) {
    state.drawCurrent = snapped;
    render();
  }

  // Hover cursor
  if (state.tool === 'select') {
    if (state.draggingEndpoint) {
      interactCanvas.style.cursor = 'crosshair';
    } else if (endpointHitTest(world.x, world.y)) {
      interactCanvas.style.cursor = 'crosshair';
    } else {
      const hit = hitTest(world.x, world.y);
      interactCanvas.style.cursor = hit ? 'move' : 'default';
    }
  } else {
    interactCanvas.style.cursor = 'crosshair';
  }
}

function onMouseUp(e) {
  if (state.panning) {
    state.panning = false;
    interactCanvas.style.cursor = state.tool === 'select' ? 'default' : 'crosshair';
    return;
  }

  if (state.draggingEndpoint) {
    state.draggingEndpoint = null;
    pushHistory();
    render();
    return;
  }

  if (state.dragging) {
    state.dragging = false;
    pushHistory();
    return;
  }

  if (!state.drawing) return;
  const rect = interactCanvas.getBoundingClientRect();
  const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
  const world = screenToWorld(sx, sy);
  const snapped = snapPoint(world);

  if (state.tool === 'polygon') return; // handled on click

  if (state.drawStart) {
    const dx = Math.abs(snapped.x - state.drawStart.x);
    const dy = Math.abs(snapped.y - state.drawStart.y);
    if (dx < 2 && dy < 2) { state.drawing = false; render(); return; }

    pushHistory();
    const el = buildElement(state.tool, state.drawStart, snapped);
    if (el) {
      state.floors[state.currentFloor].elements.push(el);
      state.selected = el.id;
      showProperties(el);
    }
    updateStats();
  }
  state.drawing = false;
  state.drawStart = null;
  state.drawCurrent = null;
  render();
}

function onDblClick(e) {
  if (state.tool === 'polygon' && state.polygonPoints.length >= 3) {
    pushHistory();
    const el = {
      id: genId(),
      type: 'polygon',
      color: TOOL_COLORS['polygon'].stroke,
      fill: TOOL_COLORS['polygon'].fill,
      width: TOOL_COLORS['polygon'].width,
      points: [...state.polygonPoints],
      closed: true,
      label: '',
      fontSize: 14
    };
    state.floors[state.currentFloor].elements.push(el);
    state.selected = el.id;
    showProperties(el);
    state.polygonPoints = [];
    state.drawing = false;
    updateStats(); render();
  }
}

function onWheel(e) {
  e.preventDefault();
  const rect = interactCanvas.getBoundingClientRect();
  const mx = e.clientX - rect.left, my = e.clientY - rect.top;
  const factor = e.deltaY < 0 ? 1.1 : 0.9;
  const newZoom = Math.min(8, Math.max(0.1, state.zoom * factor));
  state.panX = mx - (mx - state.panX) * (newZoom / state.zoom);
  state.panY = my - (my - state.panY) * (newZoom / state.zoom);
  state.zoom = newZoom;
  document.getElementById('zoomLabel').textContent = Math.round(state.zoom * 100) + '%';
  render();
}

// ─── Tool Selection ───────────────────────────────────────────────────────────
document.querySelectorAll('.tool-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const tool = btn.dataset.tool;
    if (!tool) return;
    state.tool = tool;
    state.drawing = false;
    state.polygonPoints = [];
    document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    interactCanvas.style.cursor = tool === 'select' ? 'default' : 'crosshair';
  });
});

// ─── Rotation Buttons (Stairs) ───────────────────────────────────────────────
document.querySelectorAll('.rot-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const rot = parseInt(btn.dataset.rot);
    pushHistory();
    updateSelectedProp('rotation', rot);
    // Update active state
    document.querySelectorAll('.rot-btn').forEach(b => {
      b.classList.toggle('active', parseInt(b.dataset.rot) === rot);
    });
  });
});

// ─── Properties Panel ─────────────────────────────────────────────────────────
// Types that show the label text input field
const LABEL_TYPES = ['room','polygon','text','gateway'];
// Types that show the font size control (same set)
const FONTSIZE_TYPES = ['room','polygon','text','gateway'];
// Types that show the fill colour + opacity controls
const FILL_TYPES = ['room','polygon','stairs','lift','column'];

function showProperties(el) {
  const noSel = document.getElementById('noSelection');
  const selProps = document.getElementById('selectionProps');
  if (!el) {
    noSel.style.display = 'flex'; selProps.style.display = 'none'; return;
  }
  noSel.style.display = 'none'; selProps.style.display = 'block';
  document.getElementById('propType').textContent = el.type;
  document.getElementById('propId').textContent = el.id;
  document.getElementById('propLabel').value = el.label || '';
  document.getElementById('propColor').value = el.color || '#006400';
  document.getElementById('propColorHex').value = el.color || '#006400';
  // Fill group — only for area types
  const showFill = FILL_TYPES.includes(el.type);
  document.getElementById('propFillGroup').style.display = showFill ? 'block' : 'none';
  if (showFill) {
    const fillHex = el.fill ? (el.fill.startsWith('rgba') ? rgbaToHex(el.fill) : el.fill) : '#1a2a1a';
    if (el.fill) document.getElementById('propFill').value = fillHex;
    document.getElementById('propFillHex').value = el.fill ? fillHex : '';
    document.getElementById('propFillToggle').checked = !!el.fill;
    const fillPct = fillAlphaPct(el.fill);
    document.getElementById('propFillOpacity').value = fillPct;
    document.getElementById('propFillOpacityVal').textContent = fillPct + '%';
    document.getElementById('propFillOpacityRow').style.display = el.fill ? 'flex' : 'none';
  }
  document.getElementById('propThickness').value = el.width || 2;
  document.getElementById('propThicknessVal').textContent = (el.width||2) + 'px';

  // Rotation — only for stairs
  const rotGroup = document.getElementById('propRotationGroup');
  rotGroup.style.display = el.type === 'stairs' ? 'block' : 'none';
  if (el.type === 'stairs') {
    document.querySelectorAll('.rot-btn').forEach(b => {
      b.classList.toggle('active', parseInt(b.dataset.rot) === (el.rotation || 0));
    });
  }

  // Label text field — only for areas, text labels and gateways
  const showLabel = LABEL_TYPES.includes(el.type);
  document.getElementById('propLabel').closest('.prop-group').style.display = showLabel ? 'block' : 'none';

  // Font size — only for elements that render text on canvas
  const showFontSize = FONTSIZE_TYPES.includes(el.type);
  document.getElementById('propFontSizeGroup').style.display = showFontSize ? 'block' : 'none';
  if (showFontSize) {
    const fs = el.fontSize || 14;
    document.getElementById('propFontSize').value = fs;
    document.getElementById('propFontSizeNum').value = fs;
    document.getElementById('propFontSizeVal').textContent = fs + 'px';
  }
}

function rgbaToHex(rgba) {
  try {
    const m = rgba.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (!m) return '#000000';
    return '#' + [m[1],m[2],m[3]].map(n => parseInt(n).toString(16).padStart(2,'0')).join('');
  } catch { return '#000000'; }
}

function fillAlphaPct(fill) {
  if (!fill) return 15;
  if (fill.startsWith('rgba')) {
    const m = fill.match(/rgba\([^,]+,[^,]+,[^,]+,\s*([\d.]+)\)/);
    return m ? Math.round(parseFloat(m[1]) * 100) : 15;
  }
  return 15;
}

function hexToRgba(hex, pct) {
  if (!hex || hex.length < 7) hex = '#006400';
  const r = parseInt(hex.slice(1,3),16);
  const g = parseInt(hex.slice(3,5),16);
  const b = parseInt(hex.slice(5,7),16);
  const a = Math.round(pct) / 100;
  return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
}

document.getElementById('propLabel').addEventListener('input', e => {
  updateSelectedProp('label', e.target.value);
});
document.getElementById('propColor').addEventListener('input', e => {
  document.getElementById('propColorHex').value = e.target.value;
  updateSelectedProp('color', e.target.value);
});
document.getElementById('propColorHex').addEventListener('input', e => {
  const v = e.target.value;
  if (/^#[0-9a-fA-F]{6}$/.test(v)) {
    document.getElementById('propColor').value = v;
    updateSelectedProp('color', v);
  }
});
document.getElementById('propThickness').addEventListener('input', e => {
  document.getElementById('propThicknessVal').textContent = e.target.value + 'px';
  updateSelectedProp('width', parseInt(e.target.value));
});
document.getElementById('propFontSize').addEventListener('input', e => {
  const val = parseInt(e.target.value);
  document.getElementById('propFontSizeVal').textContent = val + 'px';
  document.getElementById('propFontSizeNum').value = val;
  updateSelectedProp('fontSize', val);
});
document.getElementById('propFontSizeNum').addEventListener('input', e => {
  const val = Math.min(120, Math.max(6, parseInt(e.target.value) || 14));
  document.getElementById('propFontSize').value = val;
  document.getElementById('propFontSizeVal').textContent = val + 'px';
  updateSelectedProp('fontSize', val);
});
document.getElementById('propFontSizeDec').addEventListener('click', () => {
  const el = getSelectedEl(); if (!el) return;
  const val = Math.max(6, (el.fontSize || 14) - 1);
  document.getElementById('propFontSize').value = val;
  document.getElementById('propFontSizeNum').value = val;
  document.getElementById('propFontSizeVal').textContent = val + 'px';
  updateSelectedProp('fontSize', val);
});
document.getElementById('propFontSizeInc').addEventListener('click', () => {
  const el = getSelectedEl(); if (!el) return;
  const val = Math.min(120, (el.fontSize || 14) + 1);
  document.getElementById('propFontSize').value = val;
  document.getElementById('propFontSizeNum').value = val;
  document.getElementById('propFontSizeVal').textContent = val + 'px';
  updateSelectedProp('fontSize', val);
});
document.getElementById('propFill').addEventListener('input', e => {
  const pct = parseInt(document.getElementById('propFillOpacity').value) || 15;
  updateSelectedProp('fill', hexToRgba(e.target.value, pct));
  document.getElementById('propFillHex').value = e.target.value;
  document.getElementById('propFillToggle').checked = true;
  document.getElementById('propFillOpacityRow').style.display = 'flex';
});

document.getElementById('propFillHex').addEventListener('input', e => {
  const v = e.target.value;
  if (/^#[0-9a-fA-F]{6}$/.test(v)) {
    document.getElementById('propFill').value = v;
    const pct = parseInt(document.getElementById('propFillOpacity').value) || 15;
    updateSelectedProp('fill', hexToRgba(v, pct));
    document.getElementById('propFillToggle').checked = true;
    document.getElementById('propFillOpacityRow').style.display = 'flex';
  }
});
document.getElementById('propFillToggle').addEventListener('change', e => {
  const opacityRow = document.getElementById('propFillOpacityRow');
  if (e.target.checked) {
    const pickerVal = document.getElementById('propFill').value || '#006400';
    const pct = parseInt(document.getElementById('propFillOpacity').value) || 15;
    updateSelectedProp('fill', hexToRgba(pickerVal, pct));
    document.getElementById('propFillHex').value = pickerVal;
    opacityRow.style.display = 'flex';
  } else {
    updateSelectedProp('fill', null);
    opacityRow.style.display = 'none';
  }
});

function getSelectedEl() {
  if (!state.selected) return null;
  return state.floors[state.currentFloor].elements.find(e => e.id === state.selected);
}

function updateSelectedProp(key, value) {
  const el = getSelectedEl();
  if (el) { el[key] = value; render(); }
}

document.getElementById('propFillOpacity').addEventListener('input', e => {
  const pct = parseInt(e.target.value);
  document.getElementById('propFillOpacityVal').textContent = pct + '%';
  const el = getSelectedEl();
  if (!el || !el.fill) return;
  const hex = document.getElementById('propFill').value || rgbaToHex(el.fill);
  document.getElementById('propFillHex').value = hex;
  updateSelectedProp('fill', hexToRgba(hex, pct));
});

document.getElementById('deleteSelected').addEventListener('click', () => {
  if (!state.selected) return;
  pushHistory();
  state.floors[state.currentFloor].elements = state.floors[state.currentFloor].elements.filter(e => e.id !== state.selected);
  state.selected = null;
  showProperties(null); updateStats(); render();
});

document.getElementById('duplicateSelected').addEventListener('click', () => {
  const el = getSelectedEl();
  if (!el) return;
  pushHistory();
  const clone = JSON.parse(JSON.stringify(el));
  clone.id = genId();
  if (clone.x1 !== undefined) { clone.x1 += 20; clone.y1 += 20; }
  if (clone.x2 !== undefined) { clone.x2 += 20; clone.y2 += 20; }
  if (clone.points) clone.points = clone.points.map(p => ({ x: p.x+20, y: p.y+20 }));
  state.floors[state.currentFloor].elements.push(clone);
  state.selected = clone.id;
  showProperties(clone);
  updateStats(); render();
});

// ─── Undo / Redo ──────────────────────────────────────────────────────────────
document.getElementById('undoBtn').addEventListener('click', undo);
document.getElementById('redoBtn').addEventListener('click', redo);
document.addEventListener('keydown', e => {
  if ((e.ctrlKey||e.metaKey) && e.key === 'z' && !e.shiftKey) { undo(); e.preventDefault(); }
  if ((e.ctrlKey||e.metaKey) && (e.key === 'y' || (e.key==='z' && e.shiftKey))) { redo(); e.preventDefault(); }
  if (e.key === 'Escape') {
    if (state.tool === 'polygon') { state.polygonPoints = []; state.drawing = false; render(); }
    state.selected = null; showProperties(null); render();
  }
  if (e.key === 'Delete' || e.key === 'Backspace') {
    if (state.selected && document.activeElement === document.body) {
      pushHistory();
      state.floors[state.currentFloor].elements = state.floors[state.currentFloor].elements.filter(e => e.id !== state.selected);
      state.selected = null; showProperties(null); updateStats(); render();
    }
  }
  if (e.key === 'v' || e.key === 'V') {
    document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('[data-tool="select"]').classList.add('active');
    state.tool = 'select';
  }
});

// ─── Zoom Controls ────────────────────────────────────────────────────────────
document.getElementById('zoomIn').addEventListener('click', () => {
  state.zoom = Math.min(8, state.zoom * 1.2);
  document.getElementById('zoomLabel').textContent = Math.round(state.zoom*100) + '%';
  render();
});
document.getElementById('zoomOut').addEventListener('click', () => {
  state.zoom = Math.max(0.1, state.zoom / 1.2);
  document.getElementById('zoomLabel').textContent = Math.round(state.zoom*100) + '%';
  render();
});
document.getElementById('zoomFit').addEventListener('click', () => {
  state.zoom = 1; state.panX = 0; state.panY = 0;
  document.getElementById('zoomLabel').textContent = '100%';
  render();
});

// ─── Grid & Snap ──────────────────────────────────────────────────────────────
document.getElementById('gridToggle').addEventListener('change', e => {
  state.gridVisible = e.target.checked; render();
});
document.getElementById('snapToggle').addEventListener('change', e => {
  state.snapEnabled = e.target.checked;
});

// ─── Theme Toggle ─────────────────────────────────────────────────────────────
document.getElementById('themeToggle').addEventListener('click', () => {
  const html = document.documentElement;
  html.setAttribute('data-theme', html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
  render();
});

// ─── Overlay Image ────────────────────────────────────────────────────────────
document.getElementById('overlayOpacity').addEventListener('input', e => {
  state.overlayOpacity = parseInt(e.target.value) / 100;
  document.getElementById('opacityVal').textContent = e.target.value + '%';
  render();
});
document.getElementById('overlayToggle').addEventListener('change', e => {
  state.overlayVisible = e.target.checked; render();
});
document.getElementById('uploadOverlayBtn').addEventListener('click', () => {
  document.getElementById('overlayFileInput').click();
});
document.getElementById('clearOverlayBtn').addEventListener('click', () => {
  state.overlayImage = null;
  document.getElementById('clearOverlayBtn').style.display = 'none';
  render();
});

document.getElementById('overlayFileInput').addEventListener('change', async e => {
  const file = e.target.files[0];
  if (!file) return;
  await loadOverlayFile(file);
  e.target.value = '';
});

async function loadOverlayFile(file) {
  if (file.type === 'application/pdf') {
    alert('PDF overlays: please convert to PNG/JPG first for best results, or use a PDF viewer to screenshot the floor plan. PNG/JPG/SVG are recommended.');
    return;
  }
  const url = URL.createObjectURL(file);
  const img = new Image();
  img.onload = () => {
    state.overlayImage = img;
    document.getElementById('clearOverlayBtn').style.display = 'flex';
    render();
  };
  img.src = url;
}

// ─── Drag & Drop onto canvas ──────────────────────────────────────────────────
wrapper.addEventListener('dragover', e => {
  e.preventDefault();
  document.getElementById('dropHint').classList.add('active');
});
wrapper.addEventListener('dragleave', () => {
  document.getElementById('dropHint').classList.remove('active');
});
wrapper.addEventListener('drop', async e => {
  e.preventDefault();
  document.getElementById('dropHint').classList.remove('active');
  const file = e.dataTransfer.files[0];
  if (file) await loadOverlayFile(file);
});

// ─── Text Tool ────────────────────────────────────────────────────────────────
function showTextModal() {
  const modal = document.getElementById('textModal');
  const input = document.getElementById('textInput');
  modal.style.display = 'flex';
  input.value = '';
  setTimeout(() => input.focus(), 50);
}

document.getElementById('textConfirm').addEventListener('click', () => {
  const val = document.getElementById('textInput').value.trim();
  if (val && state.textPending) {
    pushHistory();
    const el = buildElement('text', state.textPending, state.textPending);
    el.label = val;
    state.floors[state.currentFloor].elements.push(el);
    state.selected = el.id;
    showProperties(el);
    updateStats(); render();
  }
  document.getElementById('textModal').style.display = 'none';
  state.textPending = null;
});
document.getElementById('textCancel').addEventListener('click', () => {
  document.getElementById('textModal').style.display = 'none';
  state.textPending = null;
});
document.getElementById('textInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('textConfirm').click();
  if (e.key === 'Escape') document.getElementById('textCancel').click();
});

// ─── Floors ───────────────────────────────────────────────────────────────────
function updateFloorList() {
  const list = document.getElementById('floorList');
  list.innerHTML = '';
  state.floors.forEach((fl, idx) => {
    const item = document.createElement('div');
    item.className = 'floor-item' + (idx === state.currentFloor ? ' active' : '');

    // Name span
    const nameSpan = document.createElement('span');
    nameSpan.className = 'floor-name';
    nameSpan.textContent = fl.name;

    // Edit button
    const editBtn = document.createElement('button');
    editBtn.className = 'floor-edit-btn';
    editBtn.title = 'Rename floor';
    editBtn.innerHTML = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`;
    editBtn.addEventListener('click', e => {
      e.stopPropagation();
      showRenameModal(idx);
    });

    // Element count badge
    const countSpan = document.createElement('span');
    countSpan.className = 'stat-count';
    countSpan.textContent = fl.elements.length;

    // Delete button (hidden when only one floor remains)
    const delBtn = document.createElement('button');
    delBtn.className = 'floor-del-btn';
    delBtn.title = 'Delete floor';
    delBtn.innerHTML = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
    delBtn.style.display = state.floors.length === 1 ? 'none' : 'flex';
    delBtn.addEventListener('click', e => {
      e.stopPropagation();
      if (state.floors.length === 1) return;
      if (fl.elements.length > 0) {
        if (!confirm(`Delete "${fl.name}" and its ${fl.elements.length} element(s)?`)) return;
      }
      pushHistory();
      state.floors.splice(idx, 1);
      if (state.currentFloor >= state.floors.length) {
        state.currentFloor = state.floors.length - 1;
      }
      state.selected = null;
      showProperties(null);
      document.getElementById('floorLabel').textContent = state.floors[state.currentFloor].name;
      updateFloorList(); updateStats(); render();
    });

    item.appendChild(nameSpan);
    item.appendChild(editBtn);
    item.appendChild(countSpan);
    item.appendChild(delBtn);

    // Click to switch floor
    item.addEventListener('click', () => {
      state.currentFloor = idx;
      state.selected = null;
      showProperties(null);
      document.getElementById('floorLabel').textContent = fl.name;
      updateFloorList(); updateStats(); render();
    });

    list.appendChild(item);
  });
}

document.getElementById('addFloor').addEventListener('click', () => {
  const num = state.floors.length + 1;
  state.floors.push({ id: num, name: `Floor ${num}`, elements: [] });
  state.currentFloor = state.floors.length - 1;
  document.getElementById('floorLabel').textContent = state.floors[state.currentFloor].name;
  updateFloorList(); updateStats(); render();
});

document.getElementById('prevFloor').addEventListener('click', () => {
  if (state.currentFloor > 0) {
    state.currentFloor--;
    document.getElementById('floorLabel').textContent = state.floors[state.currentFloor].name;
    state.selected = null; showProperties(null);
    updateFloorList(); updateStats(); render();
  }
});

document.getElementById('nextFloor').addEventListener('click', () => {
  if (state.currentFloor < state.floors.length - 1) {
    state.currentFloor++;
    document.getElementById('floorLabel').textContent = state.floors[state.currentFloor].name;
    state.selected = null; showProperties(null);
    updateFloorList(); updateStats(); render();
  }
});

// ─── Rename Floor Modal ──────────────────────────────────────────────────────
let renamingFloorIdx = null;

function showRenameModal(idx) {
  renamingFloorIdx = idx;
  const input = document.getElementById('renameFloorInput');
  input.value = state.floors[idx].name;
  document.getElementById('renameFloorModal').style.display = 'flex';
  setTimeout(() => { input.focus(); input.select(); }, 50);
}

document.getElementById('renameFloorConfirm').addEventListener('click', () => {
  const val = document.getElementById('renameFloorInput').value.trim();
  if (val && renamingFloorIdx !== null) {
    state.floors[renamingFloorIdx].name = val;
    if (renamingFloorIdx === state.currentFloor) {
      document.getElementById('floorLabel').textContent = val;
    }
    updateFloorList();
  }
  document.getElementById('renameFloorModal').style.display = 'none';
  renamingFloorIdx = null;
});

document.getElementById('renameFloorCancel').addEventListener('click', () => {
  document.getElementById('renameFloorModal').style.display = 'none';
  renamingFloorIdx = null;
});

document.getElementById('renameFloorInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('renameFloorConfirm').click();
  if (e.key === 'Escape') document.getElementById('renameFloorCancel').click();
});

// ─── Stats ────────────────────────────────────────────────────────────────────
function updateStats() {
  const els = state.floors[state.currentFloor].elements;
  const stats = document.getElementById('elementStats');
  const counts = {};
  els.forEach(el => { counts[el.type] = (counts[el.type]||0) + 1; });
  const labels = {
    'wall-concrete': 'Concrete walls', 'wall-drywall': 'Drywall', 'wall-glass': 'Glass walls',
    'wall-exterior': 'Exterior walls', 'door-single': 'Doors', 'door-double': 'Double doors',
    'window': 'Windows', 'room': 'Rooms', 'polygon': 'Poly rooms', 'stairs': 'Stairs',
    'lift': 'Lifts', 'column': 'Columns', 'text': 'Labels', 'gateway': 'Gateways'
  };
  if (!Object.keys(counts).length) {
    stats.innerHTML = '<div class="stat-row" style="color:var(--text-sub);font-size:11px">No elements yet</div>';
    return;
  }
  stats.innerHTML = Object.entries(counts).map(([k,v]) =>
    `<div class="stat-row"><span>${labels[k]||k}</span><span class="stat-count">${v}</span></div>`
  ).join('');
}

// ─── Export ───────────────────────────────────────────────────────────────────
document.getElementById('exportJsonBtn').addEventListener('click', () => {
  const data = {
    version: '1.0',
    generated: new Date().toISOString(),
    tool: 'Pareto Anywhere Floor Plan Builder',
    floors: state.floors.map(fl => ({
      id: fl.id,
      name: fl.name,
      elements: fl.elements
    }))
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  downloadBlob(blob, 'floorplan.json');
});

document.getElementById('exportSvgBtn').addEventListener('click', () => {
  const els = state.floors[state.currentFloor].elements;
  if (!els.length) { alert('No elements on this floor to export.'); return; }
  const svg = generateSVG(els);
  const blob = new Blob([svg], { type: 'image/svg+xml' });
  const floorName = state.floors[state.currentFloor].name.replace(/[^a-z0-9_\-]/gi, '_');
  downloadBlob(blob, `${floorName}.svg`);
});

function generateSVG(elements) {
  // ── Compute bounding box (account for rotated stairs) ──
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  function trackPtSvg(x, y) {
    minX = Math.min(minX, x); minY = Math.min(minY, y);
    maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
  }
  elements.forEach(el => {
    if (el.points) { el.points.forEach(p => trackPtSvg(p.x, p.y)); }
    else if (el.x1 !== undefined) {
      trackPtSvg(el.x1, el.y1);
      if (el.x2 !== undefined) trackPtSvg(el.x2, el.y2);
    }
  });
  const pad = 50;
  const W = Math.ceil(maxX - minX + pad*2);
  const H = Math.ceil(maxY - minY + pad*2);
  const ox = -minX + pad, oy = -minY + pad;

  // ── SVG path helpers ──
  function p(x, y) { return `${r(x+ox)},${r(y+oy)}`; }
  function r(n) { return Math.round(n * 10) / 10; }
  function lineAttrs(sc, lw, dash, extra='') {
    return `stroke="${sc}" stroke-width="${lw}" stroke-linecap="round" stroke-linejoin="round"${dash ? ` stroke-dasharray="${dash}"` : ''} fill="none"${extra}`;
  }

  // Rotate point around centre (for stairs)
  function rotPt(px, py, cx, cy, deg) {
    const rad = deg * Math.PI / 180;
    const dx = px-cx, dy = py-cy;
    return [cx + dx*Math.cos(rad) - dy*Math.sin(rad),
            cy + dx*Math.sin(rad) + dy*Math.cos(rad)];
  }

  // Arc path for door (SVG arc command)
  // Matches canvas: pivot at (ax,ay), tip at (bx,by), sweeps 90 degrees
  // reverse=true sweeps the other way (right panel of double door)
  function doorArcPath(ax, ay, bx, by, reverse) {
    const dx=bx-ax, dy=by-ay;
    const len = Math.hypot(dx, dy);
    if (len < 2) return '';
    const angle = Math.atan2(dy, dx);
    // Canvas: sweeps angle - PI/2 (CCW in canvas = clockwise in SVG coords since Y is flipped)
    const sweepAngle = reverse ? angle + Math.PI/2 : angle - Math.PI/2;
    const ex = ax + Math.cos(sweepAngle) * len;
    const ey = ay + Math.sin(sweepAngle) * len;
    // SVG sweep-flag: 0=CCW, 1=CW. Canvas Y-down means canvas CCW = SVG CW = sweep 1
    const sweepFlag = reverse ? 0 : 1;
    return `M${p(ax,ay)} A${r(len)},${r(len)} 0 0,${sweepFlag} ${p(ex,ey)}`;
  }

  let shapes = '';

  elements.forEach(el => {
    const cfg = TOOL_COLORS[el.type] || {};
    const sc  = el.color || cfg.stroke || '#006400';
    const lw  = el.width || cfg.width || 2;
    const fillVal = el.fill !== undefined ? el.fill : cfg.fill;
    const fc  = fillVal || 'none';
    const dash = cfg.dash ? cfg.dash.join(',') : '';
    const fs  = el.fontSize || 14;

    switch (el.type) {
      // ── Walls ──
      case 'wall-concrete':
      case 'wall-exterior':
        shapes += `<line x1="${r(el.x1+ox)}" y1="${r(el.y1+oy)}" x2="${r(el.x2+ox)}" y2="${r(el.y2+oy)}" ${lineAttrs(sc,lw,'')}/>`;
        break;
      case 'wall-drywall':
        shapes += `<line x1="${r(el.x1+ox)}" y1="${r(el.y1+oy)}" x2="${r(el.x2+ox)}" y2="${r(el.y2+oy)}" ${lineAttrs(sc,lw,'6,3')}/>`;
        break;
      case 'wall-glass': {
        const dx=el.x2-el.x1, dy=el.y2-el.y1, len=Math.hypot(dx,dy);
        shapes += `<line x1="${r(el.x1+ox)}" y1="${r(el.y1+oy)}" x2="${r(el.x2+ox)}" y2="${r(el.y2+oy)}" ${lineAttrs(sc,lw,'3,2')}/>`;
        if (len > 2) {
          const nx=-dy/len*4, ny=dx/len*4;
          shapes += `<line x1="${r(el.x1+nx+ox)}" y1="${r(el.y1+ny+oy)}" x2="${r(el.x2+nx+ox)}" y2="${r(el.y2+ny+oy)}" ${lineAttrs(sc,1,'3,2')}/>`;
          shapes += `<line x1="${r(el.x1-nx+ox)}" y1="${r(el.y1-ny+oy)}" x2="${r(el.x2-nx+ox)}" y2="${r(el.y2-ny+oy)}" ${lineAttrs(sc,1,'3,2')}/>`;
        }
        break;
      }

      // ── Single door ──
      case 'door-single':
        shapes += `<line x1="${r(el.x1+ox)}" y1="${r(el.y1+oy)}" x2="${r(el.x2+ox)}" y2="${r(el.y2+oy)}" ${lineAttrs(sc,lw,'')}/>`;
        shapes += `<path d="${doorArcPath(el.x1,el.y1,el.x2,el.y2,false)}" ${lineAttrs(sc,lw,'')}/>`;
        break;

      // ── Double door ──
      case 'door-double': {
        const mx=(el.x1+el.x2)/2, my=(el.y1+el.y2)/2;
        shapes += `<line x1="${r(el.x1+ox)}" y1="${r(el.y1+oy)}" x2="${r(mx+ox)}" y2="${r(my+oy)}" ${lineAttrs(sc,lw,'')}/>`;
        shapes += `<line x1="${r(mx+ox)}" y1="${r(my+oy)}" x2="${r(el.x2+ox)}" y2="${r(el.y2+oy)}" ${lineAttrs(sc,lw,'')}/>`;
        shapes += `<path d="${doorArcPath(el.x1,el.y1,mx,my,false)}" ${lineAttrs(sc,lw,'')}/>`;
        shapes += `<path d="${doorArcPath(el.x2,el.y2,mx,my,true)}" ${lineAttrs(sc,lw,'')}/>`;
        break;
      }

      // ── Window ──
      case 'window': {
        const dx=el.x2-el.x1, dy=el.y2-el.y1, len=Math.hypot(dx,dy);
        shapes += `<line x1="${r(el.x1+ox)}" y1="${r(el.y1+oy)}" x2="${r(el.x2+ox)}" y2="${r(el.y2+oy)}" ${lineAttrs(sc,lw,'')}/>`;
        if (len > 2) {
          const nx=-dy/len*5, ny=dx/len*5;
          shapes += `<line x1="${r(el.x1+nx+ox)}" y1="${r(el.y1+ny+oy)}" x2="${r(el.x2+nx+ox)}" y2="${r(el.y2+ny+oy)}" ${lineAttrs(sc,1.5,'')}/>`;
          shapes += `<line x1="${r(el.x1-nx+ox)}" y1="${r(el.y1-ny+oy)}" x2="${r(el.x2-nx+ox)}" y2="${r(el.y2-ny+oy)}" ${lineAttrs(sc,1.5,'')}/>`;
        }
        break;
      }

      // ── Room ──
      case 'room': {
        const x=Math.min(el.x1,el.x2)+ox, y=Math.min(el.y1,el.y2)+oy;
        const w=Math.abs(el.x2-el.x1), h=Math.abs(el.y2-el.y1);
        shapes += `<rect x="${r(x)}" y="${r(y)}" width="${r(w)}" height="${r(h)}" stroke="${sc}" fill="${fc}" stroke-width="${lw}"/>`;
        if (el.label) shapes += `<text x="${r(x+w/2)}" y="${r(y+h/2)}" text-anchor="middle" dominant-baseline="middle" font-family="DM Sans,sans-serif" font-size="${fs}" fill="${sc}">${escSvg(el.label)}</text>`;
        break;
      }

      // ── Polygon ──
      case 'polygon':
        if (el.points?.length >= 2) {
          const pts = el.points.map(pt => p(pt.x, pt.y)).join(' ');
          shapes += `<polygon points="${pts}" stroke="${sc}" fill="${fc}" stroke-width="${lw}"/>`;
          if (el.label && el.points.length >= 3) {
            const cx = el.points.reduce((s,pt)=>s+pt.x,0)/el.points.length;
            const cy = el.points.reduce((s,pt)=>s+pt.y,0)/el.points.length;
            shapes += `<text x="${r(cx+ox)}" y="${r(cy+oy)}" text-anchor="middle" dominant-baseline="middle" font-family="DM Sans,sans-serif" font-size="${fs}" fill="${sc}">${escSvg(el.label)}</text>`;
          }
        }
        break;

      // ── Stairs ──
      case 'stairs': {
        const bx1=Math.min(el.x1,el.x2), by1=Math.min(el.y1,el.y2);
        const bx2=Math.max(el.x1,el.x2), by2=Math.max(el.y1,el.y2);
        const bw=bx2-bx1, bh=by2-by1;
        const cx=(bx1+bx2)/2, cy=(by1+by2)/2;
        const rot = el.rotation || 0;
        function rp(px,py) { const [rx,ry]=rotPt(px,py,cx,cy,rot); return p(rx,ry); }
        function rpLine(x1,y1,x2,y2) { return `<line x1="${rp(x1,y1).split(',')[0]}" y1="${rp(x1,y1).split(',')[1]}" x2="${rp(x2,y2).split(',')[0]}" y2="${rp(x2,y2).split(',')[1]}" ${lineAttrs(sc,lw,'')}/>`; }

        // Outline
        shapes += `<polygon points="${rp(bx1,by1)} ${rp(bx2,by1)} ${rp(bx2,by2)} ${rp(bx1,by2)}" stroke="${sc}" fill="${fc}" stroke-width="${lw}"/>`;
        // Step lines
        const steps = Math.max(2, Math.floor(bw/12));
        for (let i=1; i<steps; i++) {
          const sx = bx1+(i/steps)*bw;
          shapes += `<line x1="${rp(sx,by1).split(',')[0]}" y1="${rp(sx,by1).split(',')[1]}" x2="${rp(sx,by2).split(',')[0]}" y2="${rp(sx,by2).split(',')[1]}" ${lineAttrs(sc,0.8,'')} opacity="0.7"/>`;
        }
        // Arrow
        const ay=by1+bh/2;
        shapes += `<polyline points="${rp(bx1+8,ay)} ${rp(bx2-8,ay)}" ${lineAttrs(sc,1.5,'')}/>`;
        shapes += `<polyline points="${rp(bx2-16,ay-6)} ${rp(bx2-8,ay)} ${rp(bx2-16,ay+6)}" ${lineAttrs(sc,1.5,'')}/>`;
        break;
      }

      // ── Lift ──
      case 'lift': {
        const x=Math.min(el.x1,el.x2)+ox, y=Math.min(el.y1,el.y2)+oy;
        const w=Math.abs(el.x2-el.x1), h=Math.abs(el.y2-el.y1);
        shapes += `<rect x="${r(x)}" y="${r(y)}" width="${r(w)}" height="${r(h)}" stroke="${sc}" fill="${fc}" stroke-width="${lw}"/>`;
        const mx=r(x+w/2), my=r(y+h/2);
        shapes += `<line x1="${mx}" y1="${r(y)}" x2="${mx}" y2="${r(y+h)}" ${lineAttrs(sc,1.5,'')}/>`;
        const q1x=r(x+w/4), q2x=r(x+3*w/4);
        // Up arrow
        shapes += `<polyline points="${q1x},${r(y+h/2+10)} ${q1x},${r(y+h/2-10)}" ${lineAttrs(sc,1.5,'')}/>`;
        shapes += `<polyline points="${r(x+w/4-5)},${r(y+h/2-4)} ${q1x},${r(y+h/2-10)} ${r(x+w/4+5)},${r(y+h/2-4)}" ${lineAttrs(sc,1.5,'')}/>`;
        // Down arrow
        shapes += `<polyline points="${q2x},${r(y+h/2-10)} ${q2x},${r(y+h/2+10)}" ${lineAttrs(sc,1.5,'')}/>`;
        shapes += `<polyline points="${r(x+3*w/4-5)},${r(y+h/2+4)} ${q2x},${r(y+h/2+10)} ${r(x+3*w/4+5)},${r(y+h/2+4)}" ${lineAttrs(sc,1.5,'')}/>`;
        break;
      }

      // ── Column ──
      case 'column': {
        let cx1=Math.min(el.x1,el.x2), cy1=Math.min(el.y1,el.y2);
        let cx2=Math.max(el.x1,el.x2), cy2=Math.max(el.y1,el.y2);
        if (cx2-cx1 < 10) { cx1-=5; cx2+=5; }
        if (cy2-cy1 < 10) { cy1-=5; cy2+=5; }
        shapes += `<rect x="${r(cx1+ox)}" y="${r(cy1+oy)}" width="${r(cx2-cx1)}" height="${r(cy2-cy1)}" stroke="${sc}" fill="${fc}" stroke-width="${lw}"/>`;
        shapes += `<line x1="${r(cx1+ox)}" y1="${r(cy1+oy)}" x2="${r(cx2+ox)}" y2="${r(cy2+oy)}" ${lineAttrs(sc,1,'')}/>`;
        shapes += `<line x1="${r(cx2+ox)}" y1="${r(cy1+oy)}" x2="${r(cx1+ox)}" y2="${r(cy2+oy)}" ${lineAttrs(sc,1,'')}/>`;
        break;
      }

      // ── Gateway ──
      case 'gateway': {
        // Centre in SVG space (with offset applied once)
        const gx = el.x1 + ox;
        const gy = el.y1 + oy;
        shapes += `<circle cx="${r(gx)}" cy="${r(gy)}" r="10" stroke="${sc}" fill="${fc}" stroke-width="${lw}"/>`;
        // WiFi arcs: match canvas angles (-0.6π to -0.1π, and 1.1π to 1.6π)
        for (let i=1; i<=3; i++) {
          const rad = 10+i*8;
          const a1s = -0.6*Math.PI, a1e = -0.1*Math.PI;
          const a2s =  1.1*Math.PI, a2e =  1.6*Math.PI;
          const x1s=r(gx+Math.cos(a1s)*rad), y1s=r(gy+Math.sin(a1s)*rad);
          const x1e=r(gx+Math.cos(a1e)*rad), y1e=r(gy+Math.sin(a1e)*rad);
          const x2s=r(gx+Math.cos(a2s)*rad), y2s=r(gy+Math.sin(a2s)*rad);
          const x2e=r(gx+Math.cos(a2e)*rad), y2e=r(gy+Math.sin(a2e)*rad);
          shapes += `<path d="M${x1s},${y1s} A${rad},${rad} 0 0,1 ${x1e},${y1e}" ${lineAttrs(sc,lw,'')}/>`;
          shapes += `<path d="M${x2s},${y2s} A${rad},${rad} 0 0,1 ${x2e},${y2e}" ${lineAttrs(sc,lw,'')}/>`;
        }
        if (el.label) shapes += `<text x="${r(gx)}" y="${r(gy+10+32)}" text-anchor="middle" font-family="JetBrains Mono,monospace" font-size="${r(fs*0.85)}" fill="${sc}">${escSvg(el.label)}</text>`;
        break;
      }

      // ── Text label ──
      case 'text':
        if (el.label) shapes += `<text x="${r(el.x1+ox)}" y="${r(el.y1+oy)}" font-family="DM Sans,sans-serif" font-size="${fs}" fill="${sc}">${escSvg(el.label)}</text>`;
        break;
    }
  });

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <rect width="${W}" height="${H}" fill="#f8faf8"/>
  ${shapes}
</svg>`;
}

function escSvg(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Import JSON ──────────────────────────────────────────────────────────────
document.getElementById('importBtn').addEventListener('click', () => {
  document.getElementById('importFileInput').click();
});
document.getElementById('importFileInput').addEventListener('change', e => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = ev => {
    try {
      const data = JSON.parse(ev.target.result);
      if (data.floors) {
        pushHistory();
        state.floors = data.floors;
        state.currentFloor = 0;
        state.selected = null;
        // Recalculate nextId
        let maxId = 0;
        state.floors.forEach(fl => fl.elements.forEach(el => {
          const n = parseInt(el.id.replace('el_',''));
          if (!isNaN(n)) maxId = Math.max(maxId, n);
        }));
        nextId = maxId + 1;
        document.getElementById('floorLabel').textContent = state.floors[0]?.name || 'Floor 1';
        showProperties(null);
        updateFloorList(); updateStats(); render();
      }
    } catch { alert('Invalid floor plan JSON file.'); }
  };
  reader.readAsText(file);
  e.target.value = '';
});

// ─── Save / Load ──────────────────────────────────────────────────────────────
const SAVE_KEY = 'pareto_floorplan_v1';
let autoSaveTimer = null;
let unsavedChanges = false;

function saveToLocalStorage() {
  try {
    const data = {
      version: '1.0',
      saved_at: new Date().toISOString(),
      floors: state.floors,
      currentFloor: state.currentFloor,
    };
    localStorage.setItem(SAVE_KEY, JSON.stringify(data));
    unsavedChanges = false;
    showSaveStatus('Saved', false);
  } catch (e) {
    showSaveStatus('Save failed', true);
  }
}

function loadFromLocalStorage() {
  try {
    const raw = localStorage.getItem(SAVE_KEY);
    if (!raw) return false;
    const data = JSON.parse(raw);
    if (!data.floors || !data.floors.length) return false;
    state.floors = data.floors;
    state.currentFloor = Math.min(data.currentFloor || 0, data.floors.length - 1);
    // Recalculate nextId
    let maxId = 0;
    state.floors.forEach(fl => fl.elements.forEach(el => {
      const n = parseInt((el.id || '').replace('el_', ''));
      if (!isNaN(n)) maxId = Math.max(maxId, n);
    }));
    nextId = maxId + 1;
    return true;
  } catch (e) {
    return false;
  }
}

function showSaveStatus(msg, isError) {
  const el = document.getElementById('saveStatus');
  if (!el) return;
  el.textContent = msg;
  el.className = 'save-status' + (isError ? ' save-error' : ' save-ok');
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => { el.textContent = ''; el.className = 'save-status'; }, 2500);
}

function markUnsaved() {
  if (!unsavedChanges) {
    unsavedChanges = true;
    const el = document.getElementById('saveStatus');
    if (el) { el.textContent = 'Unsaved changes'; el.className = 'save-status save-pending'; }
  }
  // Auto-save after 3 seconds of inactivity
  clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(saveToLocalStorage, 3000);
}

// Manual save button
document.getElementById('saveBtn').addEventListener('click', saveToLocalStorage);

// Ctrl+S
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault();
    saveToLocalStorage();
  }
});

// Hook into pushHistory to mark unsaved
const _origPushHistory = pushHistory;
pushHistory = function() {
  _origPushHistory();
  markUnsaved();
};

// ─── Init ─────────────────────────────────────────────────────────────────────
resizeCanvases();

// Load saved data on startup
const loaded = loadFromLocalStorage();

updateFloorList();
updateStats();
render();

if (loaded) {
  document.getElementById('floorLabel').textContent = state.floors[state.currentFloor]?.name || 'Floor 1';
  showSaveStatus('Project loaded', false);
}

console.log('Pareto Anywhere Floor Plan Builder initialized.');
console.log('Tools: Select (V), Wall types, Doors, Windows, Rooms, Polygon, Stairs, Lift, Column, Label, Gateway');
console.log('Controls: Scroll to zoom, Alt+drag or middle-click to pan, Right-click to cancel/deselect');
console.log('Keys: Ctrl+Z undo, Ctrl+Y redo, Ctrl+S save, Delete to remove selected, Escape to cancel');

// ─── Leaflet Preview ──────────────────────────────────────────────────────────
let leafletMap = null;
let previewFloorIdx = 0;
let showGateways = true;
let showLabels = true;

// CRS.Simple: pass canvas coords directly, negate Y (canvas Y grows down, map Y grows up)
function c2ll(x, y) { return [-y, x]; }

document.getElementById('previewBtn').addEventListener('click', openPreview);
document.getElementById('previewClose').addEventListener('click', closePreview);
document.getElementById('previewGatewayToggle').addEventListener('change', e => {
  showGateways = e.target.checked; renderPreviewFloor(previewFloorIdx);
});
document.getElementById('previewLabelToggle').addEventListener('change', e => {
  showLabels = e.target.checked; renderPreviewFloor(previewFloorIdx);
});

function openPreview() {
  document.getElementById('previewPanel').style.display = 'flex';
  if (!leafletMap) {
    leafletMap = L.map('leafletMap', {
      crs: L.CRS.Simple, zoomControl: true,
      attributionControl: false, minZoom: -5, maxZoom: 4, zoomSnap: 0.1,
    });
  }
  previewFloorIdx = state.currentFloor;
  buildFloorTabs();
  setTimeout(() => { leafletMap.invalidateSize(); renderPreviewFloor(previewFloorIdx); }, 80);
}

function closePreview() {
  document.getElementById('previewPanel').style.display = 'none';
}

function buildFloorTabs() {
  const tabs = document.getElementById('previewFloorTabs');
  tabs.innerHTML = '';
  state.floors.forEach((fl, idx) => {
    const btn = document.createElement('button');
    btn.className = 'preview-tab' + (idx === previewFloorIdx ? ' active' : '');
    btn.textContent = fl.name;
    btn.addEventListener('click', () => { previewFloorIdx = idx; buildFloorTabs(); renderPreviewFloor(idx); });
    tabs.appendChild(btn);
  });
}

function renderPreviewFloor(idx) {
  if (!leafletMap) return;
  const floor = state.floors[idx];
  if (!floor) return;

  leafletMap.eachLayer(l => leafletMap.removeLayer(l));
  const elements = floor.elements;
  if (!elements.length) { leafletMap.setView([0,0], 0); return; }

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  function trk(x, y) {
    if (x < minX) minX = x; if (x > maxX) maxX = x;
    if (y < minY) minY = y; if (y > maxY) maxY = y;
  }

  elements.forEach(el => {
    const cfg = TOOL_COLORS[el.type] || {};
    const color   = el.color || cfg.stroke || '#006400';
    const weight  = Math.max(el.width || cfg.width || 2, 1);
    const fillVal = el.fill !== undefined ? el.fill : cfg.fill;
    const fillOpacity = fillVal
      ? (fillVal.startsWith('rgba') ? extractAlpha(fillVal) : 0.15) : 0;

    const ls = { color, weight, opacity: 1,
      dashArray: cfg.dash ? cfg.dash.join(',') : null,
      lineCap: 'round', lineJoin: 'round' };
    const as = { ...ls, fillColor: fillVal || color, fillOpacity };

    // ── Concrete / exterior wall (solid thick) ──
    if (el.type === 'wall-concrete' || el.type === 'wall-exterior') {
      trk(el.x1,el.y1); trk(el.x2,el.y2);
      L.polyline([c2ll(el.x1,el.y1), c2ll(el.x2,el.y2)], ls).addTo(leafletMap);
    }

    // ── Drywall (dashed) ──
    else if (el.type === 'wall-drywall') {
      trk(el.x1,el.y1); trk(el.x2,el.y2);
      L.polyline([c2ll(el.x1,el.y1), c2ll(el.x2,el.y2)],
        { ...ls, dashArray: '8,4' }).addTo(leafletMap);
    }

    // ── Glass wall (fine dash) ──
    else if (el.type === 'wall-glass') {
      trk(el.x1,el.y1); trk(el.x2,el.y2);
      // Main line
      L.polyline([c2ll(el.x1,el.y1), c2ll(el.x2,el.y2)], { ...ls, dashArray: '3,2' }).addTo(leafletMap);
      // Parallel lines to show glass thickness
      const dx=el.x2-el.x1, dy=el.y2-el.y1, len=Math.hypot(dx,dy);
      if (len > 2) {
        const nx=-dy/len*5, ny=dx/len*5;
        L.polyline([c2ll(el.x1+nx,el.y1+ny), c2ll(el.x2+nx,el.y2+ny)],
          { ...ls, weight: 1, dashArray: '3,2', opacity: 0.5 }).addTo(leafletMap);
        L.polyline([c2ll(el.x1-nx,el.y1-ny), c2ll(el.x2-nx,el.y2-ny)],
          { ...ls, weight: 1, dashArray: '3,2', opacity: 0.5 }).addTo(leafletMap);
      }
    }

    // ── Single door ──
    else if (el.type === 'door-single') {
      trk(el.x1,el.y1); trk(el.x2,el.y2);
      L.polyline([c2ll(el.x1,el.y1), c2ll(el.x2,el.y2)], ls).addTo(leafletMap);
      const arc = doorArc(el.x1,el.y1, el.x2,el.y2, false);
      if (arc.length) L.polyline(arc, { ...ls, dashArray: '5,3', weight: Math.max(1,weight-1) }).addTo(leafletMap);
    }

    // ── Double door ──
    else if (el.type === 'door-double') {
      trk(el.x1,el.y1); trk(el.x2,el.y2);
      const mx=(el.x1+el.x2)/2, my=(el.y1+el.y2)/2;
      L.polyline([c2ll(el.x1,el.y1), c2ll(mx,my)], ls).addTo(leafletMap);
      L.polyline([c2ll(mx,my), c2ll(el.x2,el.y2)], ls).addTo(leafletMap);
      // arc1: left door pivots at x1,y1 sweeping toward midpoint (clockwise)
      const arc1 = doorArc(el.x1,el.y1, mx,my, false);
      // arc2: right door pivots at x2,y2 sweeping toward midpoint (counter-clockwise)
      const arc2 = doorArc(el.x2,el.y2, mx,my, true);
      if (arc1.length) L.polyline(arc1, { ...ls, dashArray:'5,3', weight:Math.max(1,weight-1) }).addTo(leafletMap);
      if (arc2.length) L.polyline(arc2, { ...ls, dashArray:'5,3', weight:Math.max(1,weight-1) }).addTo(leafletMap);
    }

    // ── Window (3 parallel lines) ──
    else if (el.type === 'window') {
      trk(el.x1,el.y1); trk(el.x2,el.y2);
      const dx=el.x2-el.x1, dy=el.y2-el.y1, len=Math.hypot(dx,dy);
      L.polyline([c2ll(el.x1,el.y1), c2ll(el.x2,el.y2)], ls).addTo(leafletMap);
      if (len > 2) {
        const nx=-dy/len*6, ny=dx/len*6;
        L.polyline([c2ll(el.x1+nx,el.y1+ny), c2ll(el.x2+nx,el.y2+ny)], { ...ls, weight:1.5 }).addTo(leafletMap);
        L.polyline([c2ll(el.x1-nx,el.y1-ny), c2ll(el.x2-nx,el.y2-ny)], { ...ls, weight:1.5 }).addTo(leafletMap);
      }
    }

    // ── Room ──
    else if (el.type === 'room') {
      const x1=Math.min(el.x1,el.x2), y1=Math.min(el.y1,el.y2);
      const x2=Math.max(el.x1,el.x2), y2=Math.max(el.y1,el.y2);
      trk(x1,y1); trk(x2,y2);
      L.polygon([c2ll(x1,y1),c2ll(x2,y1),c2ll(x2,y2),c2ll(x1,y2)], as).addTo(leafletMap);
      if (showLabels && el.label)
        addLabel(leafletMap, c2ll((x1+x2)/2,(y1+y2)/2), el.label, color, el.fontSize||14);
    }

    // ── Stairs ──
    else if (el.type === 'stairs') {
      const x1=Math.min(el.x1,el.x2), y1=Math.min(el.y1,el.y2);
      const x2=Math.max(el.x1,el.x2), y2=Math.max(el.y1,el.y2);
      const w=x2-x1, h=y2-y1;
      const rot = el.rotation || 0;
      const csx=(x1+x2)/2, csy=(y1+y2)/2;

      // Rotate a point in local space (relative to bounding box) around the centre
      function rpt(px, py) {
        const rad = rot * Math.PI / 180;
        const dx=px-csx, dy=py-csy;
        const rx = csx + dx*Math.cos(rad) - dy*Math.sin(rad);
        const ry = csy + dx*Math.sin(rad) + dy*Math.cos(rad);
        trk(rx, ry);
        return c2ll(rx, ry);
      }

      // Rotated outline — rotate the 4 corners
      L.polygon([rpt(x1,y1), rpt(x2,y1), rpt(x2,y2), rpt(x1,y2)], as).addTo(leafletMap);

      // Step lines: always perpendicular to travel direction.
      // In local (unrotated) space, travel is left→right (horizontal),
      // so steps are vertical stripes across width, spaced along X.
      const stepCount = Math.max(2, Math.floor(w / 12));
      for (let i=1; i<stepCount; i++) {
        const sx = x1 + (i/stepCount)*w;
        L.polyline([rpt(sx,y1), rpt(sx,y2)], { color, weight:1, opacity:0.7 }).addTo(leafletMap);
      }

      // Arrow: runs along travel direction (horizontal in local space)
      const ay = y1+h/2;
      L.polyline([rpt(x1+8,ay), rpt(x2-8,ay)], { color, weight:1.5 }).addTo(leafletMap);
      L.polyline([rpt(x2-16,ay-6), rpt(x2-8,ay), rpt(x2-16,ay+6)], { color, weight:1.5 }).addTo(leafletMap);
    }

    // ── Lift ──
    else if (el.type === 'lift') {
      const x1=Math.min(el.x1,el.x2), y1=Math.min(el.y1,el.y2);
      const x2=Math.max(el.x1,el.x2), y2=Math.max(el.y1,el.y2);
      trk(x1,y1); trk(x2,y2);
      L.polygon([c2ll(x1,y1),c2ll(x2,y1),c2ll(x2,y2),c2ll(x1,y2)], as).addTo(leafletMap);
      // Centre divider
      const mx=(x1+x2)/2;
      L.polyline([c2ll(mx,y1),c2ll(mx,y2)], { color, weight:1.5 }).addTo(leafletMap);
      // Up arrow (left half)
      const my=(y1+y2)/2, q1x=(x1+mx)/2, q2x=(mx+x2)/2;
      L.polyline([c2ll(q1x,my+10),c2ll(q1x,my-10)], { color, weight:1.5 }).addTo(leafletMap);
      L.polyline([c2ll(q1x-5,my-4),c2ll(q1x,my-10),c2ll(q1x+5,my-4)], { color, weight:1.5 }).addTo(leafletMap);
      // Down arrow (right half)
      L.polyline([c2ll(q2x,my-10),c2ll(q2x,my+10)], { color, weight:1.5 }).addTo(leafletMap);
      L.polyline([c2ll(q2x-5,my+4),c2ll(q2x,my+10),c2ll(q2x+5,my+4)], { color, weight:1.5 }).addTo(leafletMap);
      if (showLabels && el.label)
        addLabel(leafletMap, c2ll((x1+x2)/2, y1+12), el.label, color, 10);
    }

    // ── Column ──
    else if (el.type === 'column') {
      let x1=Math.min(el.x1,el.x2), y1=Math.min(el.y1,el.y2);
      let x2=Math.max(el.x1,el.x2), y2=Math.max(el.y1,el.y2);
      // Ensure minimum visible size if drawn as a point
      if (x2-x1 < 10) { x1 -= 5; x2 += 5; }
      if (y2-y1 < 10) { y1 -= 5; y2 += 5; }
      trk(x1,y1); trk(x2,y2);
      L.polygon([c2ll(x1,y1),c2ll(x2,y1),c2ll(x2,y2),c2ll(x1,y2)], as).addTo(leafletMap);
      L.polyline([c2ll(x1,y1),c2ll(x2,y2)], { color, weight:1 }).addTo(leafletMap);
      L.polyline([c2ll(x2,y1),c2ll(x1,y2)], { color, weight:1 }).addTo(leafletMap);
    }

    // ── Polygon area ──
    else if (el.type === 'polygon' && el.points && el.points.length >= 3) {
      el.points.forEach(p => trk(p.x,p.y));
      L.polygon(el.points.map(p => c2ll(p.x,p.y)), as).addTo(leafletMap);
      if (showLabels && el.label) {
        const cx=el.points.reduce((s,p)=>s+p.x,0)/el.points.length;
        const cy=el.points.reduce((s,p)=>s+p.y,0)/el.points.length;
        addLabel(leafletMap, c2ll(cx,cy), el.label, color, el.fontSize||14);
      }
    }

    // ── Gateway ──
    else if (el.type === 'gateway') {
      trk(el.x1, el.y1);
      if (showGateways) {
        const labelHtml = (showLabels && el.label)
          ? `<div class="preview-gw-label" style="color:${color}">${escapeHtml(el.label)}</div>` : '';
        const icon = L.divIcon({
          className: '',
          html: `<div class="preview-gw-wrap">
            <div class="preview-gw-icon" style="border-color:${color}">
              <div class="preview-gw-rings">
                <div class="gw-arc gw-arc3" style="border-top-color:${color}"></div>
                <div class="gw-arc gw-arc2" style="border-top-color:${color}"></div>
                <div class="gw-arc gw-arc1" style="border-top-color:${color}"></div>
                <div class="gw-dot" style="background:${color}"></div>
              </div>
            </div>${labelHtml}</div>`,
          iconSize: [40, 58], iconAnchor: [20, 20],
        });
        const marker = L.marker(c2ll(el.x1,el.y1), { icon });
        if (el.label) {
          marker.bindPopup(
            `<div style="font-family:JetBrains Mono,monospace;font-size:12px;font-weight:600">${escapeHtml(el.label)}</div>` +
            `<div style="font-size:11px;color:#888;margin-top:4px">BLE Gateway</div>`,
            { maxWidth: 180 }
          );
        }
        marker.addTo(leafletMap);
      }
    }

    // ── Text label ──
    else if (el.type === 'text' && el.label) {
      trk(el.x1, el.y1);
      if (showLabels) addLabel(leafletMap, c2ll(el.x1,el.y1), el.label, color, el.fontSize||14);
    }
  });

  // fitBounds
  if (isFinite(minX)) {
    const pad = 80;
    leafletMap.fitBounds([c2ll(minX-pad, maxY+pad), c2ll(maxX+pad, minY-pad)], { animate: false });
  }
}

// ── Label marker — centred on point ──
function addLabel(map, ll, text, color, canvasFontSize) {
  const fs = Math.min(Math.max(Math.round((canvasFontSize || 14) * 0.85), 9), 24);
  const icon = L.divIcon({
    className: '',
    // iconSize [0,0] + iconAnchor [0,0] means the marker point is top-left of the div.
    // The div itself uses CSS transform:translate(-50%,-50%) to centre over the point.
    html: `<div class="preview-label-marker" style="color:${color};font-size:${fs}px">${escapeHtml(text)}</div>`,
    iconSize: [0, 0], iconAnchor: [0, 0],
  });
  L.marker(ll, { icon, interactive: false }).addTo(map);
}

function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function extractAlpha(rgba) {
  const m = rgba.match(/rgba\([^,]+,[^,]+,[^,]+,\s*([\d.]+)\)/);
  return m ? parseFloat(m[1]) : 0.15;
}

// Door arc: pivot at (ax,ay), tip at (bx,by), sweeps 90°
// reverse=true sweeps the other way (for right panel of double door)
function doorArc(ax, ay, bx, by, reverse) {
  const dx=bx-ax, dy=by-ay;
  const len = Math.hypot(dx,dy);
  if (len < 2) return [];
  const angle = Math.atan2(dy, dx);
  const dir = reverse ? 1 : -1;
  const pts = [];
  for (let i=0; i<=16; i++) {
    const a = angle + dir*(Math.PI/2)*(i/16);
    pts.push(c2ll(ax + Math.cos(a)*len, ay + Math.sin(a)*len));
  }
  return pts;
}
