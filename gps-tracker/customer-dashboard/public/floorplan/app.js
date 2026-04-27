// ═══════════════════════════════════════════════════════
// Floor Plan View — Namespaced App Logic
// Exposed as: window.FP
//
// Portal integration hooks:
//   FP.onShow()   — call from switchTab when 'floorplan' tab becomes active
//   FP.drawAll()  — call from applyTheme() to redraw after theme change
// ═══════════════════════════════════════════════════════

window.FP = (() => {
  'use strict';

  // ═══════════════════════════════════════════════════════
  // FLOOR PLAN DEFINITIONS
  // ═══════════════════════════════════════════════════════
  const FLOORS = {
    'G': {
      name: 'Ground Floor — Warehouse',
      width: 1000, height: 680,
      shell: [[40,40],[960,40],[960,640],[700,640],[700,580],[40,580]],
      rooms: [
        {id:'g-r1',  rect:[40,40,200,200],   label:'Receiving Bay',       type:'loading'},
        {id:'g-r2',  rect:[40,240,200,150],  label:'Goods-In Office',     type:'room'},
        {id:'g-r3',  rect:[40,390,200,190],  label:'Dispatch',            type:'loading'},
        {id:'g-r4',  rect:[240,40,480,440],  label:'Main Warehouse Floor',type:'open'},
        {id:'g-r5',  rect:[720,40,240,200],  label:'Cold Storage',        type:'room'},
        {id:'g-r6',  rect:[720,240,240,180], label:'Returns Area',        type:'room'},
        {id:'g-r7',  rect:[720,420,240,100], label:'Plant Room',          type:'room'},
        {id:'g-r8',  rect:[240,480,340,100], label:'Staging Zone',        type:'loading'},
        {id:'g-r9',  rect:[580,480,140,100], label:'Battery Charging',    type:'room'},
        {id:'g-c1',  rect:[700,520,40,60],   label:'',                    type:'stair'},
        {id:'g-c2',  rect:[700,460,40,60],   label:'',                    type:'lift'},
        {id:'g-cor', rect:[240,440,480,40],  label:'',                    type:'corridor'},
      ],
      doors:[
        {x:150,y:240,w:40,horiz:true},  {x:150,y:390,w:40,horiz:true},
        {x:240,y:100,w:40,horiz:false}, {x:240,y:300,w:40,horiz:false},
        {x:720,y:100,w:40,horiz:false}, {x:720,y:310,w:40,horiz:false},
        {x:720,y:450,w:40,horiz:false}, {x:360,y:480,w:40,horiz:true},
        {x:580,y:480,w:40,horiz:false}, {x:580,y:530,w:40,horiz:true},
        {x:700,y:520,w:40,horiz:true},
      ],
      columns:[
        {x:340,y:120},{x:480,y:120},{x:620,y:120},
        {x:340,y:270},{x:480,y:270},{x:620,y:270},
        {x:340,y:420},{x:480,y:420},{x:620,y:420},
      ],
    },
    '1F': {
      name: 'First Floor — Offices',
      width: 1000, height: 680,
      shell: [[40,40],[960,40],[960,640],[40,640]],
      rooms: [
        {id:'1-cor1', rect:[40,40,920,80],    label:'',                    type:'corridor'},
        {id:'1-cor2', rect:[440,120,80,520],  label:'',                    type:'corridor'},
        {id:'1-r1',  rect:[40,120,400,160],  label:'Open Plan Office A',  type:'open'},
        {id:'1-r2',  rect:[40,280,180,180],  label:'Meeting Room 1',      type:'room'},
        {id:'1-r3',  rect:[220,280,220,180], label:'Meeting Room 2',      type:'room'},
        {id:'1-r4',  rect:[40,460,400,180],  label:'Open Plan Office B',  type:'open'},
        {id:'1-r5',  rect:[520,120,200,160], label:'Server Room',         type:'room'},
        {id:'1-r6',  rect:[720,120,240,160], label:'IT & Network',        type:'room'},
        {id:'1-r7',  rect:[520,280,200,180], label:'Finance',             type:'room'},
        {id:'1-r8',  rect:[720,280,240,180], label:'HR Dept',             type:'room'},
        {id:'1-r9',  rect:[520,460,200,180], label:'Boardroom',           type:'room'},
        {id:'1-r10', rect:[720,460,180,180], label:'Director Suite',      type:'room'},
        {id:'1-r11', rect:[900,460,60,180],  label:'',                    type:'toilet'},
        {id:'1-s1',  rect:[900,120,60,80],   label:'',                    type:'stair'},
        {id:'1-l1',  rect:[900,200,60,80],   label:'',                    type:'lift'},
        {id:'1-t1',  rect:[900,280,60,80],   label:'',                    type:'toilet'},
      ],
      doors:[
        {x:240,y:120,w:40,horiz:true},  {x:130,y:280,w:40,horiz:false},
        {x:330,y:280,w:40,horiz:false}, {x:220,y:280,w:40,horiz:true},
        {x:220,y:460,w:40,horiz:false}, {x:240,y:460,w:40,horiz:true},
        {x:520,y:180,w:40,horiz:false}, {x:720,y:180,w:40,horiz:false},
        {x:520,y:340,w:40,horiz:false}, {x:720,y:340,w:40,horiz:false},
        {x:520,y:540,w:40,horiz:false}, {x:720,y:540,w:40,horiz:false},
        {x:900,y:200,w:40,horiz:false}, {x:900,y:360,w:40,horiz:false},
        {x:900,y:540,w:40,horiz:false},
      ],
      columns:[
        {x:240,y:40},{x:440,y:40},{x:640,y:40},{x:840,y:40},
        {x:240,y:640},{x:440,y:640},{x:640,y:640},{x:840,y:640},
      ],
    },
    '2F': {
      name: 'Second Floor — Retail',
      width: 1000, height: 680,
      shell: [[40,40],[960,40],[960,640],[40,640]],
      rooms: [
        {id:'2-r1',  rect:[40,40,920,80],    label:'',                              type:'corridor'},
        {id:'2-r2',  rect:[40,120,280,380],  label:'Sales Floor A',                 type:'open'},
        {id:'2-r3',  rect:[320,120,280,380], label:'Sales Floor B',                 type:'open'},
        {id:'2-r4',  rect:[600,120,360,180], label:'Stockroom',                     type:'room'},
        {id:'2-r5',  rect:[600,300,180,200], label:'Staff Room',                    type:'room'},
        {id:'2-r6',  rect:[780,300,180,200], label:'Manager Office',                type:'room'},
        {id:'2-r7',  rect:[40,500,560,140],  label:'Customer Service & Checkout',   type:'loading'},
        {id:'2-r8',  rect:[600,500,260,140], label:'Returns & Fitting',             type:'room'},
        {id:'2-r9',  rect:[860,500,100,100], label:'',                              type:'toilet'},
        {id:'2-r10', rect:[860,420,100,80],  label:'',                              type:'stair'},
        {id:'2-cor', rect:[600,120,20,380],  label:'',                              type:'corridor'},
      ],
      doors:[
        {x:200,y:120,w:40,horiz:true},  {x:460,y:120,w:40,horiz:true},
        {x:320,y:200,w:40,horiz:false}, {x:600,y:180,w:40,horiz:false},
        {x:600,y:350,w:40,horiz:false}, {x:780,y:350,w:40,horiz:false},
        {x:200,y:500,w:40,horiz:true},  {x:460,y:500,w:40,horiz:true},
        {x:600,y:540,w:40,horiz:false}, {x:860,y:500,w:40,horiz:false},
        {x:860,y:420,w:40,horiz:false},
      ],
      columns:[
        {x:160,y:300},{x:260,y:300},{x:420,y:300},{x:520,y:300},
        {x:160,y:460},{x:260,y:460},{x:420,y:460},{x:520,y:460},
      ],
    },
    '3F': {
      name: 'Third Floor — Plant & Storage',
      width: 1000, height: 680,
      shell: [[40,40],[700,40],[700,120],[960,120],[960,640],[40,640]],
      rooms: [
        {id:'3-r1',  rect:[40,40,660,80],    label:'Roof Plant Access',      type:'loading'},
        {id:'3-r2',  rect:[40,120,300,260],  label:'Archive Storage A',      type:'room'},
        {id:'3-r3',  rect:[340,120,300,260], label:'Archive Storage B',      type:'room'},
        {id:'3-r4',  rect:[700,120,260,200], label:'IT Equipment Store',     type:'room'},
        {id:'3-r5',  rect:[700,320,260,200], label:'CCTV & Security Hub',    type:'room'},
        {id:'3-r6',  rect:[40,380,300,140],  label:'Maintenance Workshop',   type:'room'},
        {id:'3-r7',  rect:[340,380,300,140], label:'Cleaning Supplies',      type:'room'},
        {id:'3-r8',  rect:[40,520,600,120],  label:'General Storage',        type:'open'},
        {id:'3-r9',  rect:[700,520,260,120], label:'Loading Platform',       type:'loading'},
        {id:'3-c1',  rect:[640,380,60,140],  label:'',                       type:'stair'},
        {id:'3-c2',  rect:[640,260,60,120],  label:'',                       type:'lift'},
        {id:'3-cor', rect:[40,360,600,20],   label:'',                       type:'corridor'},
        {id:'3-t1',  rect:[640,120,60,140],  label:'',                       type:'toilet'},
      ],
      doors:[
        {x:200,y:120,w:40,horiz:true},  {x:490,y:120,w:40,horiz:true},
        {x:340,y:200,w:40,horiz:false}, {x:700,y:200,w:40,horiz:false},
        {x:700,y:380,w:40,horiz:false}, {x:640,y:430,w:40,horiz:false},
        {x:200,y:380,w:40,horiz:true},  {x:490,y:380,w:40,horiz:true},
        {x:200,y:520,w:40,horiz:true},  {x:700,y:560,w:40,horiz:false},
      ],
      columns:[
        {x:200,y:240},{x:490,y:240},
        {x:200,y:460},{x:490,y:460},
      ],
    },
  };

  const ASSETS = [
    // Ground floor
    {id:'a1', name:'Forklift #1',    type:'vehicle',   emoji:'🚛', floor:'G',  status:'online',  zone:'Main Warehouse',  x:400,y:200,lastSeen:'2s ago',  battery:91,  tagId:'BT:V001'},
    {id:'a2', name:'Forklift #2',    type:'vehicle',   emoji:'🚛', floor:'G',  status:'idle',    zone:'Staging Zone',    x:350,y:530,lastSeen:'48s ago', battery:73,  tagId:'BT:V002'},
    {id:'a3', name:'Pallet Jack #1', type:'vehicle',   emoji:'🔧', floor:'G',  status:'online',  zone:'Receiving Bay',   x:130,y:130,lastSeen:'5s ago',  battery:55,  tagId:'BT:V003'},
    {id:'a4', name:'Scanner A',      type:'equipment', emoji:'📷', floor:'G',  status:'online',  zone:'Goods-In Office', x:120,y:300,lastSeen:'1s ago',  battery:88,  tagId:'BT:E001'},
    {id:'a5', name:'Scanner B',      type:'equipment', emoji:'📷', floor:'G',  status:'online',  zone:'Main Warehouse',  x:560,y:260,lastSeen:'3s ago',  battery:65,  tagId:'BT:E002'},
    {id:'a6', name:'Weighing Scale', type:'equipment', emoji:'⚖️',  floor:'G',  status:'idle',    zone:'Dispatch',        x:120,y:490,lastSeen:'4m ago',  battery:44,  tagId:'BT:E003'},
    {id:'a7', name:'Crate #44',      type:'container', emoji:'📦', floor:'G',  status:'idle',    zone:'Cold Storage',    x:830,y:130,lastSeen:'2m ago',  battery:null,tagId:'BT:C001'},
    {id:'a8', name:'Crate #45',      type:'container', emoji:'📦', floor:'G',  status:'online',  zone:'Main Warehouse',  x:480,y:380,lastSeen:'10s ago', battery:null,tagId:'BT:C002'},
    {id:'a9', name:'Pallet J-88',    type:'container', emoji:'📦', floor:'G',  status:'offline', zone:'Returns Area',    x:820,y:310,lastSeen:'12m ago', battery:null,tagId:'BT:C003'},
    {id:'a10',name:'J. Mwangi',      type:'personnel', emoji:'🧑', floor:'G',  status:'online',  zone:'Main Warehouse',  x:620,y:180,lastSeen:'1s ago',  battery:78,  tagId:'BT:P001'},
    {id:'a11',name:'S. Okafor',      type:'personnel', emoji:'🧑', floor:'G',  status:'online',  zone:'Dispatch',        x:130,y:450,lastSeen:'2s ago',  battery:62,  tagId:'BT:P002'},
    // First floor
    {id:'b1', name:'Laptop Cart',    type:'vehicle',   emoji:'🛒', floor:'1F', status:'idle',    zone:'Open Plan A',     x:200,y:200,lastSeen:'5m ago',  battery:40,  tagId:'BT:V010'},
    {id:'b2', name:'Projector A',    type:'equipment', emoji:'📽', floor:'1F', status:'online',  zone:'Meeting Room 1',  x:130,y:360,lastSeen:'3s ago',  battery:null,tagId:'BT:E010'},
    {id:'b3', name:'Projector B',    type:'equipment', emoji:'📽', floor:'1F', status:'offline', zone:'Meeting Room 2',  x:330,y:370,lastSeen:'2h ago',  battery:null,tagId:'BT:E011'},
    {id:'b4', name:'Server Rack A',  type:'equipment', emoji:'🖥', floor:'1F', status:'online',  zone:'Server Room',     x:610,y:200,lastSeen:'1s ago',  battery:null,tagId:'BT:E012'},
    {id:'b5', name:'T. Adeyemi',     type:'personnel', emoji:'🧑', floor:'1F', status:'online',  zone:'Finance',         x:610,y:360,lastSeen:'4s ago',  battery:90,  tagId:'BT:P010'},
    {id:'b6', name:'K. Chen',        type:'personnel', emoji:'🧑', floor:'1F', status:'online',  zone:'Open Plan B',     x:200,y:540,lastSeen:'6s ago',  battery:71,  tagId:'BT:P011'},
    {id:'b7', name:'Supply Crate',   type:'container', emoji:'📦', floor:'1F', status:'idle',    zone:'Open Plan A',     x:380,y:180,lastSeen:'30m ago', battery:null,tagId:'BT:C010'},
    // Second floor
    {id:'c1', name:'Stock Trolley',  type:'vehicle',   emoji:'🛒', floor:'2F', status:'online',  zone:'Stockroom',       x:760,y:210,lastSeen:'7s ago',  battery:66,  tagId:'BT:V020'},
    {id:'c2', name:'Price Gun A',    type:'equipment', emoji:'🔫', floor:'2F', status:'online',  zone:'Sales Floor A',   x:180,y:280,lastSeen:'2s ago',  battery:55,  tagId:'BT:E020'},
    {id:'c3', name:'Price Gun B',    type:'equipment', emoji:'🔫', floor:'2F', status:'idle',    zone:'Sales Floor B',   x:440,y:280,lastSeen:'90s ago', battery:33,  tagId:'BT:E021'},
    {id:'c4', name:'Returns Box #9', type:'container', emoji:'📦', floor:'2F', status:'online',  zone:'Returns & Fitting',x:720,y:560,lastSeen:'15s ago',battery:null,tagId:'BT:C020'},
    {id:'c5', name:'L. Fernandez',   type:'personnel', emoji:'🧑', floor:'2F', status:'online',  zone:'Sales Floor A',   x:150,y:370,lastSeen:'1s ago',  battery:85,  tagId:'BT:P020'},
    {id:'c6', name:'M. Williams',    type:'personnel', emoji:'🧑', floor:'2F', status:'online',  zone:'Customer Svc',    x:300,y:560,lastSeen:'3s ago',  battery:77,  tagId:'BT:P021'},
    {id:'c7', name:'Store Manager',  type:'personnel', emoji:'🧑', floor:'2F', status:'idle',    zone:'Manager Office',  x:870,y:380,lastSeen:'8m ago',  battery:58,  tagId:'BT:P022'},
    // Third floor
    {id:'d1', name:'Maintenance Kit',type:'container', emoji:'🧰', floor:'3F', status:'online',  zone:'Maintenance',     x:170,y:450,lastSeen:'11s ago', battery:null,tagId:'BT:C030'},
    {id:'d2', name:'CCTV Monitor',   type:'equipment', emoji:'📺', floor:'3F', status:'online',  zone:'CCTV Hub',        x:820,y:400,lastSeen:'1s ago',  battery:null,tagId:'BT:E030'},
    {id:'d3', name:'Archive Box A',  type:'container', emoji:'📦', floor:'3F', status:'idle',    zone:'Archive A',       x:170,y:240,lastSeen:'2h ago',  battery:null,tagId:'BT:C031'},
    {id:'d4', name:'Archive Box B',  type:'container', emoji:'📦', floor:'3F', status:'idle',    zone:'Archive B',       x:470,y:240,lastSeen:'2h ago',  battery:null,tagId:'BT:C032'},
    {id:'d5', name:'P. Nkemdirim',   type:'personnel', emoji:'🧑', floor:'3F', status:'online',  zone:'CCTV Hub',        x:830,y:370,lastSeen:'5s ago',  battery:88,  tagId:'BT:P030'},
  ];

  const ZONES = {
    'G': [
      {label:'Dispatch',    rect:[40,390,200,190],  fill:'rgba(0,100,0,.15)',    stroke:'rgba(0,100,0,.6)'},
      {label:'Cold Storage',rect:[720,40,240,200],  fill:'rgba(59,130,246,.13)',  stroke:'rgba(59,130,246,.5)'},
      {label:'Alert Zone',  rect:[560,460,160,120], fill:'rgba(239,68,68,.15)',  stroke:'rgba(239,68,68,.55)'},
      {label:'Staging',     rect:[240,480,340,100], fill:'rgba(245,158,11,.13)', stroke:'rgba(245,158,11,.5)'},
    ],
    '1F': [
      {label:'Server Restricted',    rect:[520,120,200,160], fill:'rgba(59,130,246,.13)',  stroke:'rgba(59,130,246,.5)'},
      {label:'Boardroom (Booked)',    rect:[520,460,200,180], fill:'rgba(245,158,11,.12)', stroke:'rgba(245,158,11,.45)'},
    ],
    '2F': [
      {label:'Active Sales',  rect:[40,120,560,380],  fill:'rgba(0,100,0,.08)',    stroke:'rgba(0,100,0,.4)'},
      {label:'Staff Only',    rect:[600,120,360,380], fill:'rgba(59,130,246,.11)', stroke:'rgba(59,130,246,.45)'},
    ],
    '3F': [
      {label:'Secure Store',  rect:[700,120,260,400], fill:'rgba(239,68,68,.12)',  stroke:'rgba(239,68,68,.45)'},
      {label:'Plant Access',  rect:[40,40,660,80],    fill:'rgba(245,158,11,.12)', stroke:'rgba(245,158,11,.4)'},
    ],
  };

  const BEACONS = {
    'G':  [{x:200,y:140},{x:450,y:140},{x:700,y:140},{x:200,y:350},{x:450,y:350},{x:700,y:350},{x:350,y:530}],
    '1F': [{x:200,y:80}, {x:500,y:80}, {x:750,y:80}, {x:200,y:400},{x:620,y:400},{x:800,y:400}],
    '2F': [{x:180,y:80}, {x:460,y:80}, {x:760,y:80}, {x:180,y:450},{x:460,y:450},{x:760,y:450}],
    '3F': [{x:200,y:80}, {x:500,y:80}, {x:200,y:480},{x:490,y:480}, {x:800,y:480}],
  };

  // ═══════════════════════════════════════════════════════
  // STATE
  // ═══════════════════════════════════════════════════════
  let canvas, ctx;
  let activeFloor  = 'G';
  let activeCat    = 'all';
  let activeStatus = 'all';
  let searchQ      = '';
  let layers       = {assets:true, zones:false, beacons:false};
  let selectedId   = null;

  let panX=0, panY=0, scale=1;
  let dragging=false, lastPx=0, lastPy=0;

  let _initialized = false;
  let _liveTimer   = null;

  // ── ID shorthand (all floor-plan DOM IDs are prefixed fp-) ──
  const $id = id => document.getElementById('fp-' + id);

  // ═══════════════════════════════════════════════════════
  // THEME COLOURS (read CSS vars at render time)
  // ═══════════════════════════════════════════════════════
  function getThemeColors() {
    const root = document.getElementById('fp-root') || document.documentElement;
    const s = getComputedStyle(root);
    const get = v => s.getPropertyValue(v).trim();
    return {
      bg:      get('--fp-bg')      || '#12151e',
      wall:    get('--fp-wall')    || '#2e3548',
      room:    get('--fp-room')    || '#1a1f2e',
      roomAlt: get('--fp-room-alt')|| '#161b28',
      label:   get('--fp-label')   || 'rgba(148,160,180,.45)',
      grid:    get('--fp-grid')    || 'rgba(255,255,255,.025)',
      text:    get('--text')       || '#e2e8f0',
      text2:   get('--text2')      || '#94a3b8',
      text3:   get('--text3')      || '#64748b',
      border:  get('--border')     || '#1e293b',
      border2: get('--border2')    || '#334155',
      green:   get('--green')      || '#006400',
      surface: get('--surface')    || '#0f1623',
    };
  }

  // ═══════════════════════════════════════════════════════
  // CANVAS SETUP
  // ═══════════════════════════════════════════════════════
  function _initCanvas() {
    canvas = document.getElementById('fp-canvas');
    ctx    = canvas.getContext('2d');
    _resize();

    window.addEventListener('resize', () => { _resize(); _drawAll(); });

    canvas.addEventListener('mousedown',  _onMouseDown);
    canvas.addEventListener('mousemove',  _onMouseMove);
    canvas.addEventListener('mouseup',    () => { dragging=false; canvas.style.cursor='grab'; });
    canvas.addEventListener('mouseleave', () => { dragging=false; _hideTooltip(); });
    canvas.addEventListener('wheel',      _onWheel, {passive:false});
    canvas.addEventListener('click',      _onClick);
    canvas.addEventListener('dblclick',   resetView);
  }

  function _resize() {
    const area = document.getElementById('fp-map-area');
    if (canvas && area && area.clientWidth > 0 && area.clientHeight > 0) {
      canvas.width  = area.clientWidth;
      canvas.height = area.clientHeight;
    }
  }

  // ═══════════════════════════════════════════════════════
  // VIEW
  // ═══════════════════════════════════════════════════════
  function resetView() {
    const fp  = FLOORS[activeFloor];
    const cw  = canvas.width, ch = canvas.height;
    const pad = 60;
    const sx  = (cw - pad*2) / fp.width;
    const sy  = (ch - pad*2) / fp.height;
    scale = Math.min(sx, sy, 1.2);
    panX  = (cw - fp.width  * scale) / 2;
    panY  = (ch - fp.height * scale) / 2;
    _drawAll();
  }

  function zoom(factor) {
    const cx = canvas.width/2, cy = canvas.height/2;
    panX = cx - (cx - panX) * factor;
    panY = cy - (cy - panY) * factor;
    scale *= factor;
    scale = Math.max(0.3, Math.min(4, scale));
    _drawAll();
  }

  // ═══════════════════════════════════════════════════════
  // EVENTS
  // ═══════════════════════════════════════════════════════
  function _onWheel(e) {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 1/1.12;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    panX = mx - (mx - panX) * factor;
    panY = my - (my - panY) * factor;
    scale *= factor;
    scale = Math.max(0.3, Math.min(4, scale));
    _drawAll();
  }

  function _onMouseDown(e) {
    dragging=true; lastPx=e.clientX; lastPy=e.clientY;
    canvas.style.cursor='grabbing';
  }

  function _onMouseMove(e) {
    if (dragging) {
      panX += e.clientX - lastPx;
      panY += e.clientY - lastPy;
      lastPx=e.clientX; lastPy=e.clientY;
      _drawAll(); _hideTooltip(); return;
    }
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const asset = _hitTestAsset(mx, my);
    if (asset) {
      _showTooltip(asset, mx, my);
      canvas.style.cursor = 'pointer';
    } else {
      _hideTooltip();
      canvas.style.cursor = 'grab';
    }
  }

  function _onClick(e) {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const asset = _hitTestAsset(mx, my);
    if (asset) {
      selectedId = selectedId === asset.id ? null : asset.id;
      document.querySelectorAll('#fp-root .fp-asset-item').forEach(el =>
        el.classList.toggle('selected', el.dataset.id === selectedId)
      );
      if (selectedId) _scrollToAsset(selectedId);
    } else {
      selectedId = null;
      document.querySelectorAll('#fp-root .fp-asset-item').forEach(el =>
        el.classList.remove('selected')
      );
    }
    _drawAll();
  }

  // ═══════════════════════════════════════════════════════
  // HIT TEST
  // ═══════════════════════════════════════════════════════
  function _toCanvas(lx, ly) { return [lx * scale + panX, ly * scale + panY]; }

  function _hitTestAsset(mx, my) {
    const R = 14 * scale;
    for (const a of _visibleAssets()) {
      const [cx,cy] = _toCanvas(a.x, a.y);
      if (Math.hypot(mx-cx, my-cy) < R) return a;
    }
    return null;
  }

  // ═══════════════════════════════════════════════════════
  // DRAW
  // ═══════════════════════════════════════════════════════
  const WALL = 2.5;

  function _drawAll() {
    if (!canvas || !ctx) return;
    const C  = getThemeColors();
    const fp = FLOORS[activeFloor];

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();

    // Background fill
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    _drawGrid(C);
    _drawBuilding(fp, C);
    if (layers.zones)   _drawZones(C);
    if (layers.beacons) _drawBeacons(C);
    if (layers.assets)  _drawAssets(C);

    ctx.restore();
  }

  function _drawGrid(C) {
    const step = 40 * scale;
    if (step < 10) return;
    ctx.strokeStyle = C.grid;
    ctx.lineWidth   = 1;
    ctx.beginPath();
    const ox = ((panX % step) + step) % step;
    const oy = ((panY % step) + step) % step;
    for (let x = ox; x < canvas.width;  x += step) { ctx.moveTo(x,0); ctx.lineTo(x,canvas.height); }
    for (let y = oy; y < canvas.height; y += step) { ctx.moveTo(0,y); ctx.lineTo(canvas.width,y);  }
    ctx.stroke();
  }

  function _drawBuilding(fp, C) {
    // Room fills
    for (const r of fp.rooms) {
      const [x,y,w,h] = r.rect;
      const [cx,cy]   = _toCanvas(x,y);
      const cw = w*scale, ch = h*scale;

      let fill;
      switch(r.type) {
        case 'open':     fill = C.room;    break;
        case 'corridor': fill = adjustAlpha(C.wall, 0.35); break;
        case 'loading':  fill = adjustAlpha(C.room, 0.85); break;
        case 'service':
        case 'stair':
        case 'lift':
        case 'toilet':   fill = adjustAlpha(C.wall, 0.55); break;
        default:         fill = C.roomAlt;
      }
      ctx.fillStyle = fill;
      ctx.fillRect(cx, cy, cw, ch);

      // Room label
      if (r.label && scale > 0.55) {
        ctx.fillStyle = C.label;
        const font = getComputedStyle(document.documentElement).getPropertyValue('--font') || 'sans-serif';
        ctx.font = `${Math.max(9,10*scale)}px ${font}`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(_truncLabel(r.label, cw/scale), cx+cw/2, cy+ch/2);
      }

      // Special icons
      if (scale > 0.7) {
        const icon = {stair:'⬆', lift:'🔲', toilet:'🚻'}[r.type];
        if (icon) {
          ctx.font = `${12*scale}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(icon, cx+cw/2, cy+ch/2);
        }
      }
    }

    // Walls — shell
    ctx.strokeStyle = C.wall;
    ctx.lineWidth   = WALL;
    ctx.lineJoin    = 'miter';
    ctx.beginPath();
    fp.shell.forEach(([x,y],i) => {
      const [cx,cy] = _toCanvas(x,y);
      i ? ctx.lineTo(cx,cy) : ctx.moveTo(cx,cy);
    });
    ctx.closePath();
    ctx.stroke();

    // Internal walls
    ctx.lineWidth = Math.max(1, 1.5*scale);
    for (const r of fp.rooms) {
      if (r.type === 'corridor') continue;
      const [x,y,w,h] = r.rect;
      const [cx,cy] = _toCanvas(x,y);
      ctx.strokeRect(cx, cy, w*scale, h*scale);
    }

    // Columns
    for (const col of fp.columns) {
      const [cx,cy] = _toCanvas(col.x, col.y);
      const cr = 6 * scale;
      ctx.fillStyle   = C.wall;
      ctx.strokeStyle = adjustAlpha(C.wall, 1.5);
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(cx,cy,cr,0,Math.PI*2); ctx.fill(); ctx.stroke();
    }

    // Doors
    ctx.strokeStyle = C.bg;
    ctx.lineWidth   = Math.max(2, 3.5*scale);
    ctx.lineCap     = 'butt';
    for (const d of fp.doors) {
      const [cx,cy] = _toCanvas(d.x, d.y);
      const len = d.w * scale;
      ctx.beginPath();
      if (d.horiz) { ctx.moveTo(cx,cy); ctx.lineTo(cx+len,cy); }
      else         { ctx.moveTo(cx,cy); ctx.lineTo(cx,cy+len); }
      ctx.stroke();
      // Door arc
      ctx.strokeStyle = adjustAlpha(C.wall, 0.4);
      ctx.lineWidth   = Math.max(0.5, 1*scale);
      ctx.beginPath();
      if (d.horiz) ctx.arc(cx,cy,len,0,Math.PI/2);
      else         ctx.arc(cx,cy,len,Math.PI/2,Math.PI);
      ctx.stroke();
      ctx.strokeStyle = C.bg;
      ctx.lineWidth   = Math.max(2, 3.5*scale);
    }

    // Floor label
    const monoFont = getComputedStyle(document.documentElement).getPropertyValue('--mono') || 'monospace';
    ctx.fillStyle = C.text3;
    ctx.font = `500 ${Math.max(10,12*scale)}px ${monoFont}`;
    ctx.textAlign    = 'left';
    ctx.textBaseline = 'top';
    const [lx,ly] = _toCanvas(fp.shell[0][0]+6, fp.shell[0][1]+6);
    ctx.fillText(fp.name, lx, ly);
  }

  function _drawZones(C) {
    const zones = ZONES[activeFloor] || [];
    const font  = getComputedStyle(document.documentElement).getPropertyValue('--font') || 'sans-serif';
    for (const z of zones) {
      const [x,y,w,h] = z.rect;
      const [cx,cy]   = _toCanvas(x,y);
      ctx.fillStyle   = z.fill;
      ctx.strokeStyle = z.stroke;
      ctx.lineWidth   = 1.5;
      ctx.setLineDash([5*scale, 3*scale]);
      ctx.fillRect(cx, cy, w*scale, h*scale);
      ctx.strokeRect(cx, cy, w*scale, h*scale);
      ctx.setLineDash([]);
      if (scale > 0.5) {
        ctx.fillStyle = z.stroke;
        ctx.font = `600 ${Math.max(8,10*scale)}px ${font}`;
        ctx.textAlign    = 'left';
        ctx.textBaseline = 'top';
        ctx.fillText(z.label, cx+5*scale, cy+4*scale);
      }
    }
  }

  function _drawBeacons(C) {
    const bcs = BEACONS[activeFloor] || [];
    for (const b of bcs) {
      const [cx,cy] = _toCanvas(b.x, b.y);
      const r = 5 * scale;
      ctx.fillStyle   = adjustAlpha(C.green, 0.18);
      ctx.strokeStyle = adjustAlpha(C.green, 0.6);
      ctx.lineWidth   = 1;
      ctx.beginPath(); ctx.arc(cx,cy,r,0,Math.PI*2); ctx.fill(); ctx.stroke();
      ctx.strokeStyle = adjustAlpha(C.green, 0.18);
      ctx.lineWidth   = 0.8;
      [10,17].forEach(rm => { ctx.beginPath(); ctx.arc(cx,cy,rm*scale,0,Math.PI*2); ctx.stroke(); });
    }
  }

  function _drawAssets(C) {
    const catColor    = {vehicle:'#3b82f6',equipment:'#a855f7',container:'#f97316',personnel:'#06b6d4'};
    const statusColor = {online:'#22c55e', idle:'#f59e0b', offline:'#ef4444'};

    for (const a of _visibleAssets()) {
      const [cx,cy]   = _toCanvas(a.x, a.y);
      const R         = 13 * scale;
      const cc        = catColor[a.type]    || '#888';
      const sc        = statusColor[a.status] || '#888';
      const isSelected = a.id === selectedId;

      // Selection ring
      if (isSelected) {
        ctx.strokeStyle = cc;
        ctx.lineWidth   = 2.5;
        ctx.beginPath(); ctx.arc(cx,cy,R+5,0,Math.PI*2); ctx.stroke();
        ctx.globalAlpha = 0.25;
        ctx.strokeStyle = cc; ctx.lineWidth = 4;
        ctx.beginPath(); ctx.arc(cx,cy,R+10,0,Math.PI*2); ctx.stroke();
        ctx.globalAlpha = 1;
      }

      // Shadow + body
      ctx.shadowColor = 'rgba(0,0,0,0.3)'; ctx.shadowBlur = 6; ctx.shadowOffsetY = 2;
      ctx.fillStyle = C.surface;
      ctx.beginPath(); ctx.arc(cx,cy,R,0,Math.PI*2); ctx.fill();
      ctx.shadowColor = 'transparent'; ctx.shadowBlur = 0;

      // Border
      ctx.strokeStyle = cc; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(cx,cy,R,0,Math.PI*2); ctx.stroke();

      // Emoji
      ctx.font = `${Math.max(10,12*scale)}px sans-serif`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(a.emoji, cx, cy+0.5);

      // Status dot
      const dr = 4*scale;
      const dx = cx + R*0.68, dy = cy + R*0.68;
      ctx.fillStyle = C.surface;
      ctx.beginPath(); ctx.arc(dx,dy,dr+1,0,Math.PI*2); ctx.fill();
      ctx.fillStyle = sc;
      ctx.beginPath(); ctx.arc(dx,dy,dr,0,Math.PI*2); ctx.fill();
    }
  }

  function adjustAlpha(hex, factor) {
    if (!hex || hex.startsWith('rgba')) return hex || 'rgba(128,128,128,0.5)';
    if (hex.startsWith('rgb(')) return hex.replace('rgb(','rgba(').replace(')',`,${factor})`);
    return hex;
  }

  function _truncLabel(text, maxWidth) {
    const chars = Math.floor(maxWidth / 7);
    return text.length > chars ? text.slice(0, chars-1) + '…' : text;
  }

  // ═══════════════════════════════════════════════════════
  // TOOLTIP
  // ═══════════════════════════════════════════════════════
  function _showTooltip(a, mx, my) {
    const tt = document.getElementById('fp-asset-tooltip');
    const catColor    = {vehicle:'#3b82f6',equipment:'#a855f7',container:'#f97316',personnel:'#06b6d4'}[a.type];
    const statusColor = {online:'#22c55e',  idle:'#f59e0b',  offline:'#ef4444'}[a.status];
    document.getElementById('fp-tt-icon').style.background  = catColor + '22';
    document.getElementById('fp-tt-icon').textContent       = a.emoji;
    document.getElementById('fp-tt-name').textContent       = a.name;
    document.getElementById('fp-tt-type').innerHTML =
      `<span style="color:${catColor}">${a.type}</span> · <span style="color:${statusColor}">${a.status}</span>`;
    const batt = a.battery != null
      ? `<div class="fp-tt-stat"><div class="lbl">Battery</div><div class="val" style="color:${a.battery>30?'#22c55e':'#ef4444'}">${a.battery}%</div></div>`
      : '';
    document.getElementById('fp-tt-grid').innerHTML = `
      <div class="fp-tt-stat"><div class="lbl">Zone</div><div class="val">${a.zone}</div></div>
      <div class="fp-tt-stat"><div class="lbl">Last seen</div><div class="val">${a.lastSeen}</div></div>
      ${batt}
      <div class="fp-tt-stat"><div class="lbl">Tag ID</div><div class="val" style="font-size:10px">${a.tagId}</div></div>
    `;
    const area = document.getElementById('fp-map-area');
    const aw = area.clientWidth, ah = area.clientHeight;
    let tx = mx + 18, ty = my - 10;
    if (tx + 200 > aw) tx = mx - 218;
    if (ty + 160 > ah) ty = ah - 165;
    tt.style.left = tx+'px'; tt.style.top = ty+'px';
    tt.classList.add('visible');
  }

  function _hideTooltip() {
    const tt = document.getElementById('fp-asset-tooltip');
    if (tt) tt.classList.remove('visible');
  }

  // ═══════════════════════════════════════════════════════
  // FILTERING & LIST
  // ═══════════════════════════════════════════════════════
  function _visibleAssets() {
    return ASSETS.filter(a => {
      if (a.floor !== activeFloor) return false;
      if (activeCat    !== 'all' && a.type   !== activeCat)    return false;
      if (activeStatus !== 'all' && a.status !== activeStatus) return false;
      if (searchQ) {
        const q = searchQ.toLowerCase();
        if (!a.name.toLowerCase().includes(q) &&
            !a.tagId.toLowerCase().includes(q) &&
            !a.zone.toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }

  function _updateCounts() {
    const v = _visibleAssets();
    const el = id => document.getElementById('fp-count-' + id);
    if (el('total'))   el('total').textContent   = v.length;
    if (el('online'))  el('online').textContent  = v.filter(a=>a.status==='online').length;
    if (el('idle'))    el('idle').textContent    = v.filter(a=>a.status==='idle').length;
    if (el('offline')) el('offline').textContent = v.filter(a=>a.status==='offline').length;
  }

  function _renderList() {
    const container = document.getElementById('fp-asset-list');
    const es        = document.getElementById('fp-empty-state');
    if (!container) return;
    container.querySelectorAll('.fp-asset-item').forEach(el => el.remove());
    const v = _visibleAssets();
    if (!v.length) {
      if (es) es.style.display = 'flex';
      const msg = document.getElementById('fp-empty-msg');
      if (msg) msg.textContent = 'No assets match filters';
      return;
    }
    if (es) es.style.display = 'none';
    v.forEach(a => {
      const el = document.createElement('div');
      el.className  = 'fp-asset-item';
      el.dataset.id = a.id;
      el.innerHTML  = `<div class="fp-asset-icon ${a.type}">${a.emoji}</div><div class="fp-asset-info"><div class="fp-asset-name">${a.name}</div><div class="fp-asset-meta">${a.zone} · ${a.lastSeen}</div></div><div class="fp-status-dot ${a.status}"></div>`;
      el.onclick    = () => {
        selectedId = selectedId === a.id ? null : a.id;
        document.querySelectorAll('#fp-root .fp-asset-item').forEach(e =>
          e.classList.toggle('selected', e.dataset.id === selectedId)
        );
        _drawAll();
      };
      container.appendChild(el);
    });
  }

  function _scrollToAsset(id) {
    const el = document.querySelector(`#fp-root .fp-asset-item[data-id="${id}"]`);
    if (el) el.scrollIntoView({block:'nearest', behavior:'smooth'});
  }

  // ═══════════════════════════════════════════════════════
  // FLOOR SYNC
  // ═══════════════════════════════════════════════════════
  function _syncFloorUI(floor) {
    activeFloor = floor;
    document.querySelectorAll('#fp-root .fp-floor-tab').forEach(t =>
      t.classList.toggle('active', t.textContent === floor)
    );
    document.querySelectorAll('#fp-root .fp-fsw-btn').forEach(b =>
      b.classList.toggle('active', b.textContent === floor)
    );
    _updateCounts(); _renderList();
    selectedId = null;
    resetView();
  }

  // ═══════════════════════════════════════════════════════
  // LIVE DEMO SIMULATION
  // ═══════════════════════════════════════════════════════
  function _startLiveDemo() {
    if (_liveTimer) return;
    _liveTimer = setInterval(() => {
      const tab = document.getElementById('tab-floorplan');
      if (!tab || tab.style.display === 'none') return;
      ASSETS.forEach(a => {
        if (a.status === 'online' && Math.random() < 0.3) {
          a.x += (Math.random() - 0.5) * 4;
          a.y += (Math.random() - 0.5) * 4;
          a.lastSeen = Math.floor(Math.random() * 10) + 's ago';
        }
      });
      _updateCounts(); _renderList(); _drawAll();
    }, 4000);
  }

  // ═══════════════════════════════════════════════════════
  // PUBLIC UI HANDLERS (called from HTML onclick attributes)
  // ═══════════════════════════════════════════════════════
  function filterCat(el, cat) {
    activeCat = cat;
    document.querySelectorAll('#fp-root .fp-chip').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
    _updateCounts(); _renderList(); _drawAll();
  }

  function filterByStatus(s, el) {
    activeStatus = s;
    document.querySelectorAll('#fp-root .fp-status-card').forEach(c => c.classList.remove('fp-active'));
    el.classList.add('fp-active');
    _updateCounts(); _renderList(); _drawAll();
  }

  function filterAssets(q) {
    searchQ = q;
    _updateCounts(); _renderList(); _drawAll();
  }

  function selectFloor(el, floor)    { _syncFloorUI(floor); }
  function selectFloorMap(el, floor) { _syncFloorUI(floor); }

  function toggleLayer(layer, btn) {
    layers[layer] = !layers[layer];
    btn.classList.toggle('active', layers[layer]);
    if (layer === 'zones') {
      const legend = document.getElementById('fp-zone-legend');
      if (legend) legend.classList.toggle('visible', layers[layer]);
    }
    _drawAll();
  }

  function exportPNG() {
    const link    = document.createElement('a');
    link.download = `floor-plan-${activeFloor}.png`;
    link.href     = canvas.toDataURL('image/png');
    link.click();
  }

  // ═══════════════════════════════════════════════════════
  // PORTAL INTEGRATION HOOKS
  // ═══════════════════════════════════════════════════════

  /** Called first time the Floor Plan tab becomes visible. */
  function _init() {
    _initialized = true;
    _initCanvas();
    resetView();
    _updateCounts();
    _renderList();
    _startLiveDemo();
  }

  /** Call from switchTab('floorplan') — initialises on first show, resizes on subsequent. */
  function onShow() {
    if (!_initialized) {
      _init();
    } else {
      requestAnimationFrame(() => { _resize(); _drawAll(); });
    }
  }

  /** Call from applyTheme() after theme change to repaint canvas with new colours. */
  function drawAll() {
    if (canvas && ctx) _drawAll();
  }

  // Public API
  return {
    onShow,
    drawAll,
    resetView,
    zoom,
    filterCat,
    filterByStatus,
    filterAssets,
    selectFloor,
    selectFloorMap,
    toggleLayer,
    exportPNG,
  };
})();
