"""Read-only web dashboard, JSON API, and Prometheus metrics."""

import json
import logging
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from jinja2 import Environment

log = logging.getLogger(__name__)

_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PVEWatch — {{ node }}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<script>
  (function(){
    var t = localStorage.getItem('pvewatch-theme') || '';
    document.documentElement.setAttribute('data-theme', t);
  })();
</script>
<style>
  /* ── Dark (default) ─── */
  :root {
    --bg:       #070c14;
    --surf:     #0d1525;
    --surf2:    #111d30;
    --bdr:      #1a2540;
    --bdr2:     #243352;
    --tx:       #c8d8ec;
    --tx2:      #4a6080;
    --tx3:      #253248;
    --grn:      #00d97e;
    --grn-d:    #002e1a;
    --red:      #ff4458;
    --red-d:    #3a000d;
    --amb:      #ffb224;
    --amb-d:    #3a2500;
    --blu:      #4488ff;
    --font:     'JetBrains Mono', 'Consolas', 'Monaco', monospace;
  }

  /* ── Light ─── */
  [data-theme="light"] {
    --bg:    #f0f2f7;
    --surf:  #ffffff;
    --surf2: #eaecf4;
    --bdr:   #dde1ed;
    --bdr2:  #c8cedf;
    --tx:    #1a2340;
    --tx2:   #6b7a99;
    --tx3:   #b8c2d8;
    --grn:   #16a34a;
    --grn-d: #dcfce7;
    --red:   #dc2626;
    --red-d: #fee2e2;
    --amb:   #b45309;
    --amb-d: #fef3c7;
    --blu:   #2563eb;
  }
  [data-theme="light"] body::before { opacity: 0; }
  [data-theme="light"] .topbar { background: rgba(240,242,247,.95); }
  [data-theme="light"] .sbar.ok { background: linear-gradient(90deg,#15803d,#16a34a); }

  /* ── Monokai ─── */
  [data-theme="monokai"] {
    --bg:    #1a1b16;
    --surf:  #272822;
    --surf2: #2f3029;
    --bdr:   #3d3e35;
    --bdr2:  #53544a;
    --tx:    #f8f8f2;
    --tx2:   #75715e;
    --tx3:   #464741;
    --grn:   #a6e22e;
    --grn-d: #1e2b08;
    --red:   #f92672;
    --red-d: #3a0018;
    --amb:   #fd971f;
    --amb-d: #3a2000;
    --blu:   #66d9ef;
  }
  [data-theme="monokai"] .topbar { background: rgba(26,27,22,.93); }
  [data-theme="monokai"] .sbar.ok { background: linear-gradient(90deg,#7ab520,#a6e22e); }

  /* ── Solarized Dark ─── */
  [data-theme="solarized"] {
    --bg:    #001e26;
    --surf:  #002b36;
    --surf2: #073642;
    --bdr:   #0d3f4e;
    --bdr2:  #1a5464;
    --tx:    #839496;
    --tx2:   #546e75;
    --tx3:   #27484f;
    --grn:   #859900;
    --grn-d: #192000;
    --red:   #dc322f;
    --red-d: #350b0a;
    --amb:   #b58900;
    --amb-d: #2b2000;
    --blu:   #268bd2;
  }
  [data-theme="solarized"] .topbar { background: rgba(0,30,38,.93); }
  [data-theme="solarized"] .sbar.ok { background: linear-gradient(90deg,#687900,#859900); }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: var(--font);
    font-size: 13px;
    color: var(--tx);
    background: var(--bg);
    min-height: 100vh;
    line-height: 1.5;
  }
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background:
      radial-gradient(ellipse 80% 50% at 15% -5%, rgba(0,80,200,.05) 0%, transparent 65%),
      radial-gradient(ellipse 60% 40% at 85% 105%, rgba(0,180,100,.04) 0%, transparent 65%);
    pointer-events: none;
    z-index: 0;
  }
  a { color: inherit; text-decoration: none; }

  /* ── Topbar ─────────────────────────────── */
  .topbar {
    position: sticky; top: 0; z-index: 100;
    background: rgba(7,12,20,.93);
    backdrop-filter: blur(14px);
    border-bottom: 1px solid var(--bdr);
    padding: 0 28px;
    display: flex; align-items: center; gap: 20px;
    height: 54px;
  }
  .logo {
    display: flex; align-items: center; gap: 10px;
    font-weight: 700; font-size: 14px; letter-spacing: -.02em;
  }
  .logo-mark {
    display: inline-flex; align-items: center; justify-content: center;
    width: 28px; height: 28px;
    background: var(--grn); color: var(--bg);
    font-weight: 800; font-size: 11px;
    border-radius: 6px; flex-shrink: 0; letter-spacing: 0;
  }
  .topbar-node {
    font-size: 11px; color: var(--tx2);
    padding-left: 20px; border-left: 1px solid var(--bdr);
  }
  .topbar-node strong { color: var(--tx); }
  .topbar-right { margin-left: auto; display: flex; align-items: center; gap: 16px; }
  .poll-status {
    display: flex; align-items: center; gap: 7px;
    font-size: 11px; color: var(--tx2);
  }
  .pulse {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--grn); flex-shrink: 0;
    animation: pulse 3s ease-in-out infinite;
  }
  @keyframes pulse {
    0%,100% { opacity: 1; }
    50%      { opacity: .3; }
  }

  /* ── Layout ─────────────────────────────── */
  .main {
    max-width: 1180px; margin: 0 auto;
    padding: 26px 28px 64px;
    position: relative; z-index: 1;
  }

  /* ── Stats row ──────────────────────────── */
  .stats {
    display: grid; grid-template-columns: repeat(4,1fr);
    gap: 12px; margin-bottom: 18px;
  }
  .stat {
    background: var(--surf); border: 1px solid var(--bdr);
    border-radius: 10px; padding: 16px 20px;
    position: relative; overflow: hidden;
  }
  .stat::after {
    content: '';
    position: absolute; left: 0; top: 14px; bottom: 14px;
    width: 3px; border-radius: 0 2px 2px 0;
    background: var(--bdr2);
  }
  .stat.s-ok   ::after, .stat.s-ok::after   { background: var(--grn); }
  .stat.s-fail ::after, .stat.s-fail::after  { background: var(--red); }
  .stat.s-warn ::after, .stat.s-warn::after  { background: var(--amb); }
  .stat.s-neu  ::after, .stat.s-neu::after   { background: var(--blu); }
  .stat-lbl {
    font-size: 10px; font-weight: 500;
    letter-spacing: .1em; text-transform: uppercase;
    color: var(--tx2); margin-bottom: 8px;
  }
  .stat-val {
    font-size: 30px; font-weight: 700;
    letter-spacing: -.03em; line-height: 1;
    color: var(--tx);
  }
  .stat.s-ok   .stat-val { color: var(--grn); }
  .stat.s-fail .stat-val { color: var(--red); }
  .stat.s-warn .stat-val { color: var(--amb); }
  .stat-sub { font-size: 10px; color: var(--tx2); margin-top: 6px; }
  .stat-sub-ok   { color: var(--grn); }
  .stat-sub-fail { color: var(--red); }

  /* ── Card ───────────────────────────────── */
  .card {
    background: var(--surf); border: 1px solid var(--bdr);
    border-radius: 10px; margin-bottom: 14px; overflow: hidden;
  }
  .card-hdr {
    display: flex; align-items: center; justify-content: space-between;
    padding: 13px 20px; border-bottom: 1px solid var(--bdr);
    background: rgba(255,255,255,.012);
  }
  .card-title {
    font-size: 10px; font-weight: 600;
    letter-spacing: .12em; text-transform: uppercase; color: var(--tx2);
  }

  /* ── Day toggle ─────────────────────────── */
  .day-toggle {
    display: flex; gap: 2px;
    background: var(--bg); padding: 3px;
    border-radius: 7px; border: 1px solid var(--bdr);
  }
  .day-toggle a {
    font-size: 11px; font-weight: 500;
    padding: 3px 10px; border-radius: 4px;
    color: var(--tx2); transition: color .15s;
  }
  .day-toggle a:hover { color: var(--tx); }
  .day-toggle a.on {
    background: var(--surf2);
    color: var(--grn);
    border: 1px solid var(--bdr2);
  }

  /* ── Table ──────────────────────────────── */
  table { width: 100%; border-collapse: collapse; }
  th {
    text-align: left;
    font-size: 10px; font-weight: 600;
    letter-spacing: .1em; text-transform: uppercase;
    color: var(--tx3);
    padding: 9px 20px;
    border-bottom: 1px solid var(--bdr);
  }
  td {
    padding: 10px 20px;
    border-bottom: 1px solid rgba(26,37,64,.55);
    vertical-align: middle;
  }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: rgba(255,255,255,.018); }

  /* ── Sortable headers ───────────────────── */
  th.sortable {
    cursor: pointer; user-select: none;
    transition: color .15s;
  }
  th.sortable:hover { color: var(--tx2); }
  th.sortable::after { content: ' ⇅'; opacity: .3; font-size: 9px; }
  th.sort-asc::after  { content: ' ↑'; opacity: 1; color: var(--grn); }
  th.sort-desc::after { content: ' ↓'; opacity: 1; color: var(--grn); }

  /* ── VM name ────────────────────────────── */
  .vm-name {
    font-weight: 600; font-size: 13px; color: var(--tx);
    display: flex; align-items: center; gap: 7px;
  }
  .vm-id { font-size: 10px; color: var(--tx3); margin-top: 2px; }

  /* ── Type badge ─────────────────────────── */
  .badge {
    display: inline-flex; align-items: center;
    font-size: 9px; font-weight: 700;
    letter-spacing: .1em; text-transform: uppercase;
    padding: 2px 6px; border-radius: 3px;
  }
  .b-qemu { background: rgba(100,60,220,.14); color: #a78bfa; border: 1px solid rgba(100,60,220,.22); }
  .b-lxc  { background: rgba(0,150,220,.12);  color: #38bdf8; border: 1px solid rgba(0,150,220,.2); }

  /* ── Heatmap ────────────────────────────── */
  .heatmap { display: flex; align-items: center; gap: 3px; }
  .hm {
    width: 13px; height: 22px; border-radius: 3px;
    flex-shrink: 0;
  }
  .hm.ok   { background: var(--grn); opacity: .82; }
  .hm.fail { background: var(--red); opacity: .88; }
  .hm.none { background: var(--bdr); }
  .hm-counts {
    margin-left: 10px;
    display: flex; gap: 7px;
    font-size: 10px; color: var(--tx2);
  }
  .c-ok   { color: var(--grn); }
  .c-fail { color: var(--red); }

  /* ── Status pill ────────────────────────── */
  .pill {
    display: inline-flex; align-items: center; gap: 5px;
    font-size: 10px; font-weight: 700;
    letter-spacing: .08em; text-transform: uppercase;
    padding: 3px 9px; border-radius: 4px; white-space: nowrap;
  }
  .pill::before {
    content: ''; width: 5px; height: 5px;
    border-radius: 50%; flex-shrink: 0;
  }
  .p-ok    { background: var(--grn-d); color: var(--grn); border: 1px solid rgba(0,217,126,.18); }
  .p-ok::before    { background: var(--grn); }
  .p-fail  { background: var(--red-d); color: var(--red); border: 1px solid rgba(255,68,88,.2); }
  .p-fail::before  { background: var(--red); }
  .p-warn  { background: var(--amb-d); color: var(--amb); border: 1px solid rgba(255,178,36,.2); }
  .p-warn::before  { background: var(--amb); }
  .p-never { background: rgba(255,255,255,.03); color: var(--tx2); border: 1px solid var(--bdr); }
  .p-never::before { background: var(--bdr2); }

  /* ── Storage grid ───────────────────────── */
  .storage-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 1px;
    background: var(--bdr);
  }
  .pool-card {
    background: var(--surf);
    padding: 14px 16px;
    transition: background .1s;
  }
  .pool-card:hover { background: var(--surf2); }
  .pool-card[hidden] { display: none; }
  .pool-label {
    font-size: 12px; font-weight: 500;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    margin-bottom: 10px; line-height: 1.3;
  }
  .pool-label-node { color: var(--tx2); font-weight: 400; }
  .pool-label-sep  { color: var(--tx3); margin: 0 2px; }
  .pool-label-name { color: var(--tx); font-weight: 600; }
  .pool-bar-wrap {
    background: var(--bg); border-radius: 3px; height: 5px;
    overflow: hidden; margin-bottom: 8px;
  }
  .pool-bar { height: 100%; border-radius: 3px; min-width: 2px; }
  .pool-bar.ok   { background: linear-gradient(90deg,#00a860,var(--grn)); }
  .pool-bar.warn { background: linear-gradient(90deg,#cc8800,var(--amb)); }
  .pool-bar.crit { background: linear-gradient(90deg,#cc1122,var(--red)); }
  .pool-footer {
    display: flex; justify-content: space-between; align-items: baseline;
  }
  .pool-sizes { font-size: 10px; color: var(--tx2); }
  .pool-pct   { font-size: 13px; font-weight: 700; }
  .pool-pct.ok   { color: var(--grn); }
  .pool-pct.warn { color: var(--amb); }
  .pool-pct.crit { color: var(--red); }

  /* ── Node filter (storage) ──────────────── */
  .node-filter { display: flex; gap: 4px; flex-wrap: wrap; }
  .node-btn {
    font-family: var(--font); font-size: 10px; font-weight: 600;
    letter-spacing: .06em; cursor: pointer;
    padding: 3px 9px; border-radius: 4px;
    border: 1px solid var(--bdr2); color: var(--tx2);
    background: transparent; transition: all .15s;
  }
  .node-btn:hover { color: var(--tx); border-color: var(--tx2); }
  .node-btn.on {
    background: var(--surf2); color: var(--tx);
    border-color: var(--bdr2);
  }
  .node-btn.on::before { content: '● '; font-size: 7px; vertical-align: middle; }

  /* ── Alert rows ─────────────────────────── */
  .alert-row td { border-bottom: 1px solid rgba(255,68,88,.1); }

  /* ── Footer ─────────────────────────────── */
  .footer {
    text-align: center; font-size: 11px; color: var(--tx3);
    padding: 20px 0 40px; letter-spacing: .05em;
  }
  .footer a { color: var(--tx2); transition: color .15s; }
  .footer a:hover { color: var(--grn); }

  /* ── Theme picker ───────────────────────── */
  .theme-picker { display: flex; gap: 6px; align-items: center; }
  .swatch {
    width: 15px; height: 15px; border-radius: 50%;
    cursor: pointer; border: 2px solid transparent;
    padding: 0; flex-shrink: 0;
    transition: transform .15s;
  }
  .swatch:hover { transform: scale(1.2); }
  .swatch.active { outline: 2px solid var(--tx2); outline-offset: 2px; }
  .sw-dark      { background: #0d1525; border-color: #00d97e; }
  .sw-light     { background: #ffffff; border-color: #16a34a; }
  .sw-monokai   { background: #272822; border-color: #a6e22e; }
  .sw-solarized { background: #002b36; border-color: #2aa198; }

  /* ── Misc ───────────────────────────────── */
  .empty { text-align: center; padding: 40px; color: var(--tx2); font-size: 12px; }
  .muted { font-size: 11px; color: var(--tx2); }

  @media (max-width: 720px) {
    .stats { grid-template-columns: repeat(2,1fr); }
  }
</style>
</head>
<body>

<header class="topbar">
  <div class="logo">
    <span class="logo-mark">PV</span>
    PVEWatch
  </div>
  <div class="topbar-node">cluster / <strong>{{ node }}</strong></div>
  <div class="topbar-right">
    <div class="theme-picker" title="Switch theme">
      <button class="swatch sw-dark"      data-theme=""           title="Dark"      onclick="setTheme('')"></button>
      <button class="swatch sw-light"     data-theme="light"      title="Light"     onclick="setTheme('light')"></button>
      <button class="swatch sw-monokai"   data-theme="monokai"    title="Monokai"   onclick="setTheme('monokai')"></button>
      <button class="swatch sw-solarized" data-theme="solarized"  title="Solarized" onclick="setTheme('solarized')"></button>
    </div>
    <div class="poll-status">
      <span class="pulse"></span>
      last poll {{ last_poll }}
    </div>
  </div>
</header>

<div class="main">

  <div class="stats">
    <div class="stat s-neu">
      <div class="stat-lbl">Total VMs</div>
      <div class="stat-val">{{ total_vms }}</div>
    </div>
    <div class="stat {% if backed_up == total_vms %}s-ok{% elif backed_up > 0 %}s-warn{% else %}s-fail{% endif %}">
      <div class="stat-lbl">Backed up ({{ days }}d)</div>
      <div class="stat-val">{{ backed_up }}</div>
    </div>
    <div class="stat {% if failure_events > 0 and active_failure_vms > 0 %}s-fail{% elif failure_events > 0 %}s-warn{% else %}s-ok{% endif %}">
      <div class="stat-lbl">Failures ({{ days }}d)</div>
      <div class="stat-val">{{ failure_events }}</div>
      {% if failure_events > 0 %}
      <div class="stat-sub">
        {{ failure_vms }} VM{% if failure_vms != 1 %}s{% endif %} ·
        {% if active_failure_vms == 0 %}
          <span class="stat-sub-ok">all recovered</span>
        {% else %}
          <span class="stat-sub-fail">{{ active_failure_vms }} unresolved</span>
        {% endif %}
      </div>
      {% endif %}
    </div>
    <div class="stat {% if never > 0 %}s-warn{% else %}s-ok{% endif %}">
      <div class="stat-lbl">Never backed up</div>
      <div class="stat-val">{{ never }}</div>
    </div>
  </div>

  <div class="card">
    <div class="card-hdr">
      <span class="card-title">Backup history</span>
      <div style="display:flex;gap:10px;align-items:center">
        {% if vm_nodes|length > 1 %}
        <div class="node-filter" id="vm-node-filter">
          {% for n in vm_nodes %}
          <button class="node-btn on" data-node="{{ n }}" onclick="toggleVmNode('{{ n }}')">{{ n }}</button>
          {% endfor %}
        </div>
        {% endif %}
        <div class="day-toggle">
          <a href="?days=3"  {% if days == 3  %}class="on"{% endif %}>3d</a>
          <a href="?days=5"  {% if days == 5  %}class="on"{% endif %}>5d</a>
          <a href="?days=7"  {% if days == 7  %}class="on"{% endif %}>7d</a>
          <a href="?days=14" {% if days == 14 %}class="on"{% endif %}>14d</a>
          <a href="?days=30" {% if days == 30 %}class="on"{% endif %}>30d</a>
        </div>
      </div>
    </div>
    <table id="vm-table">
      <thead>
        <tr>
          <th class="sortable" data-col="node"    style="width:110px"  onclick="sortVms(this)">Node</th>
          <th class="sortable" data-col="name"    style="width:200px"  onclick="sortVms(this)">VM / Container</th>
          <th class="sortable" data-col="status"  style="width:100px"  onclick="sortVms(this)">Status</th>
          <th class="sortable" data-col="lastrun" style="width:120px"  onclick="sortVms(this)">Last backup</th>
          <th>Last {{ days }} days</th>
        </tr>
      </thead>
      <tbody id="vm-tbody">
      {% for vm in vms %}
      {% if vm.last_status == 'OK' %}{% set spri = 3 %}
      {% elif vm.last_status and vm.last_status != '' %}{% set spri = 0 %}
      {% elif vm.stale %}{% set spri = 1 %}
      {% else %}{% set spri = 2 %}{% endif %}
      <tr data-node="{{ vm.node }}"
          data-name="{{ vm.name|lower }}"
          data-status="{{ spri }}"
          data-lastrun="{{ vm.last_run_ts }}">
        <td class="muted" style="white-space:nowrap">{{ vm.node or '—' }}</td>
        <td>
          <div class="vm-name">
            {{ vm.name }}
            <span class="badge b-{{ vm.vm_type }}">{{ vm.vm_type }}</span>
          </div>
          <div class="vm-id">#{{ vm.vmid }}</div>
        </td>
        <td>
          {% if vm.last_status == 'OK' %}
            <span class="pill p-ok">OK</span>
          {% elif vm.last_status and vm.last_status != '' %}
            <span class="pill p-fail" title="{{ vm.last_status }}">Failed</span>
          {% elif vm.stale %}
            <span class="pill p-warn">Stale</span>
          {% else %}
            <span class="pill p-never">Never</span>
          {% endif %}
        </td>
        <td class="muted">{{ vm.last_run or '—' }}</td>
        <td>
          <div class="heatmap">
            {% for d in vm.dots %}
              <div class="hm {{ d }}" title="{% if loop.revindex0 == 0 %}today{% else %}{{ loop.revindex0 }}d ago{% endif %}"></div>
            {% endfor %}
            {% if vm.ok_count > 0 or vm.fail_count > 0 %}
            <div class="hm-counts">
              {% if vm.ok_count > 0 %}<span class="c-ok">{{ vm.ok_count }}✓</span>{% endif %}
              {% if vm.fail_count > 0 %}<span class="c-fail">{{ vm.fail_count }}✗</span>{% endif %}
            </div>
            {% endif %}
          </div>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="5" class="empty">No VMs found</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  {% if unattributed %}
  <div class="card">
    <div class="card-hdr">
      <span class="card-title" style="color:var(--red)">Unattributed failures</span>
    </div>
    <table>
      <thead><tr><th>Time</th><th>Error</th></tr></thead>
      <tbody>
      {% for u in unattributed %}
      <tr class="alert-row">
        <td class="muted" style="white-space:nowrap">{{ u.time }}</td>
        <td style="color:var(--red);font-size:12px">{{ u.status[:120] }}</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  {% if storage %}
  <div class="card">
    <div class="card-hdr">
      <span class="card-title">Storage</span>
      {% if storage_nodes|length > 1 %}
      <div class="node-filter" id="node-filter">
        {% for n in storage_nodes %}
        <button class="node-btn on" data-node="{{ n }}" onclick="toggleNode('{{ n }}')">{{ n }}</button>
        {% endfor %}
      </div>
      {% endif %}
    </div>
    <div class="storage-grid" id="storage-grid">
      {% for s in storage %}
      {% set cls = 'crit' if s.pct >= 85 else ('warn' if s.pct >= 70 else 'ok') %}
      <div class="pool-card" data-node="{{ s.node }}" title="{{ s.node }}: {{ s.storage_id }}">
        <div class="pool-label">
          {% if s.node %}<span class="pool-label-node">{{ s.node }}</span><span class="pool-label-sep">:</span>{% endif %}<span class="pool-label-name">{{ s.storage_id }}</span>
        </div>
        <div class="pool-bar-wrap">
          <div class="pool-bar {{ cls }}" style="width:{{ [s.pct|int, 100]|min }}%"></div>
        </div>
        <div class="pool-footer">
          <span class="pool-sizes">{{ s.used_gb }} / {{ s.total_gb }} GB</span>
          <span class="pool-pct {{ cls }}">{{ s.pct|int }}%</span>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>
  {% endif %}

</div>

<div class="footer">
  <a href="https://git.markklass.dev/markklass/pvewatch">PVEWatch</a>
</div>

<script>
  function setTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    localStorage.setItem('pvewatch-theme', t);
    document.querySelectorAll('.swatch').forEach(function(s) {
      s.classList.toggle('active', s.dataset.theme === t);
    });
  }
  // Mark active swatch on load
  var cur = document.documentElement.getAttribute('data-theme') || '';
  document.querySelectorAll('.swatch').forEach(function(s) {
    s.classList.toggle('active', s.dataset.theme === cur);
  });

  function makeNodeFilter(storageKey, rowSel, btnContainerSel) {
    var hidden = JSON.parse(localStorage.getItem(storageKey) || '[]');
    function apply() {
      document.querySelectorAll(rowSel).forEach(function(el) {
        el.hidden = hidden.indexOf(el.dataset.node) !== -1;
      });
      if (btnContainerSel) {
        document.querySelectorAll(btnContainerSel + ' .node-btn').forEach(function(b) {
          b.classList.toggle('on', hidden.indexOf(b.dataset.node) === -1);
        });
      }
      localStorage.setItem(storageKey, JSON.stringify(hidden));
    }
    apply();
    return function toggle(n) {
      var i = hidden.indexOf(n);
      if (i === -1) hidden.push(n); else hidden.splice(i, 1);
      apply();
    };
  }
  var toggleNode   = makeNodeFilter('pvewatch-hidden-nodes',    '.pool-card[data-node]', '#node-filter');
  var toggleVmNode = makeNodeFilter('pvewatch-hidden-vm-nodes', 'tr[data-node]',         '#vm-node-filter');

  // Column sort for VM table
  var vmSortCol = '', vmSortAsc = true;
  function sortVms(th) {
    var col = th.dataset.col;
    vmSortAsc = (vmSortCol === col) ? !vmSortAsc : true;
    vmSortCol = col;
    var tbody = document.getElementById('vm-tbody');
    var rows = Array.from(tbody.querySelectorAll('tr[data-node]'));
    rows.sort(function(a, b) {
      var av = a.dataset[col] || '', bv = b.dataset[col] || '';
      var n = (col === 'status' || col === 'lastrun')
        ? (parseInt(av) - parseInt(bv))
        : av.localeCompare(bv);
      return vmSortAsc ? n : -n;
    });
    rows.forEach(function(r) { tbody.appendChild(r); });
    document.querySelectorAll('#vm-table th.sortable').forEach(function(t) {
      t.classList.remove('sort-asc', 'sort-desc');
    });
    th.classList.add(vmSortAsc ? 'sort-asc' : 'sort-desc');
  }
</script>

</body>
</html>
"""


def _build_data(conn: sqlite3.Connection, node: str, days: int = 7) -> dict:
    now = int(time.time())
    since = now - days * 86400
    today = now // 86400

    # All known VMs/LXCs (one row per vmid — latest sample)
    vm_rows = conn.execute(
        """
        SELECT DISTINCT vmid, vm_name, vm_type, node
        FROM vm_states
        WHERE (vmid, sampled_at) IN (
            SELECT vmid, MAX(sampled_at) FROM vm_states GROUP BY vmid
        )
        ORDER BY vm_type, vm_name
        """
    ).fetchall()

    # All backup results within the window (excluding vmid=0)
    result_rows = conn.execute(
        """
        SELECT vmid, vm_name, status, start_time
        FROM backup_results
        WHERE start_time >= ? AND vmid != 0
        ORDER BY vmid, start_time ASC
        """,
        (since,),
    ).fetchall()

    # Most recent backup ever per VM (for last_run / stale detection)
    latest_rows = conn.execute(
        """
        SELECT vmid, vm_name, status, start_time
        FROM backup_results
        WHERE vmid != 0
          AND (vmid, start_time) IN (
              SELECT vmid, MAX(start_time) FROM backup_results WHERE vmid != 0 GROUP BY vmid
          )
        """
    ).fetchall()
    latest_by_vmid = {r["vmid"]: r for r in latest_rows}

    # Group window results by vmid
    results_by_vmid: dict[int, list] = {}
    for r in result_rows:
        results_by_vmid.setdefault(r["vmid"], []).append(r)

    vms_out = []
    for vm in vm_rows:
        vmid = vm["vmid"]
        results = results_by_vmid.get(vmid, [])
        latest = latest_by_vmid.get(vmid)

        day_map: dict[int, str] = {}
        for r in results:
            day = r["start_time"] // 86400
            # keep 'fail' if already set
            if day_map.get(day) != "fail":
                day_map[day] = "ok" if r["status"] in ("OK", "") else "fail"

        dots = [day_map.get(today - (days - 1 - i), "none") for i in range(days)]
        ok_count = sum(1 for d in dots if d == "ok")
        fail_count = sum(1 for d in dots if d == "fail")

        stale = False
        last_status = None
        last_run = None
        last_run_ts = 0
        if latest:
            last_status = latest["status"]
            last_run_ts = latest["start_time"]
            last_run = time.strftime("%b %d %H:%M", time.localtime(last_run_ts))
            # stale = last backup was > 8 days ago (expected daily but missed)
            stale = (now - last_run_ts) > 8 * 86400

        vms_out.append(
            {
                "vmid": vmid,
                "name": vm["vm_name"] or f"VM {vmid}",
                "vm_type": vm["vm_type"] or "qemu",
                "node": vm["node"] or "",
                "dots": dots,
                "ok_count": ok_count,
                "fail_count": fail_count,
                "last_status": last_status,
                "last_run": last_run,
                "last_run_ts": last_run_ts,
                "stale": stale,
            }
        )

    vm_nodes = list(dict.fromkeys(v["node"] for v in vms_out if v["node"]))

    # Summary stats
    total_vms = len(vms_out)
    backed_up = sum(1 for v in vms_out if v["ok_count"] > 0 or (v["last_status"] == "OK"))
    vms_with_failures = [v for v in vms_out if v["fail_count"] > 0]
    failure_events = sum(v["fail_count"] for v in vms_with_failures)
    failure_vms = len(vms_with_failures)
    active_failure_vms = sum(1 for v in vms_with_failures if v["last_status"] not in ("OK", "", None))
    never = sum(1 for v in vms_out if not latest_by_vmid.get(v["vmid"]))

    # Unattributed failures (vmid=0)
    unattr_rows = conn.execute(
        """
        SELECT start_time, status FROM backup_results
        WHERE vmid = 0 AND status != 'OK' AND status != ''
        AND start_time >= ?
        ORDER BY start_time DESC LIMIT 10
        """,
        (since,),
    ).fetchall()
    unattributed = [
        {"time": time.strftime("%b %d %H:%M", time.localtime(r["start_time"])), "status": r["status"]}
        for r in unattr_rows
    ]

    # Storage
    storage_rows = conn.execute(
        """
        SELECT node, storage_id, used_bytes, total_bytes
        FROM storage_snapshots
        WHERE sampled_at = (
            SELECT MAX(sampled_at) FROM storage_snapshots s2
            WHERE s2.node = storage_snapshots.node
              AND s2.storage_id = storage_snapshots.storage_id
        )
        ORDER BY node, storage_id
        """
    ).fetchall()
    # Deduplicate: same pool name + same total_bytes = shared storage visible from multiple nodes.
    # Keep the first (most-recently-sampled) occurrence. For pools with the same name but
    # different sizes (truly separate pools), keep both and add a node prefix.
    seen_shared: dict[tuple, bool] = {}
    storage_out = []
    for s in storage_rows:
        total = s["total_bytes"]
        used = s["used_bytes"]
        pct = (used / total * 100) if total else 0
        shared_key = (s["storage_id"], total)
        if shared_key in seen_shared:
            continue
        seen_shared[shared_key] = True
        storage_out.append(
            {
                "storage_id": s["storage_id"],
                "node": s["node"] or "",
                "used_bytes": used,
                "total_bytes": total,
                "used_gb": f"{used / 1_073_741_824:.1f}",
                "total_gb": f"{total / 1_073_741_824:.1f}",
                "pct": pct,
            }
        )
    # Unique ordered node list for the filter toggle
    storage_nodes = list(dict.fromkeys(s["node"] for s in storage_out if s["node"]))

    last_poll_row = conn.execute("SELECT value FROM kv WHERE key='last_poll_time'").fetchone()
    last_poll_ts_int = int(last_poll_row["value"]) if last_poll_row else 0
    last_poll = time.strftime("%Y-%m-%d %H:%M", time.localtime(last_poll_ts_int)) if last_poll_ts_int else "never"

    return {
        "node": node,
        "last_poll": last_poll,
        "last_poll_ts": last_poll_ts_int,
        "days": days,
        "summary": {
            "total_vms": total_vms,
            "backed_up": backed_up,
            "failure_events": failure_events,
            "failure_vms": failure_vms,
            "unresolved_failures": active_failure_vms,
            "never_backed_up": never,
        },
        "vms": vms_out,
        "vm_nodes": vm_nodes,
        "storage": storage_out,
        "storage_nodes": storage_nodes,
        "unattributed": unattributed,
    }


def _build_index(conn: sqlite3.Connection, node: str, days: int = 7) -> str:
    data = _build_data(conn, node, days)
    env = Environment(autoescape=True)
    tmpl = env.from_string(_INDEX_TEMPLATE)
    return tmpl.render(
        node=data["node"],
        last_poll=data["last_poll"],
        vms=data["vms"],
        vm_nodes=data["vm_nodes"],
        storage=data["storage"],
        storage_nodes=data["storage_nodes"],
        unattributed=data["unattributed"],
        days=data["days"],
        total_vms=data["summary"]["total_vms"],
        backed_up=data["summary"]["backed_up"],
        failure_events=data["summary"]["failure_events"],
        failure_vms=data["summary"]["failure_vms"],
        active_failure_vms=data["summary"]["unresolved_failures"],
        never=data["summary"]["never_backed_up"],
    )


def _build_metrics(data: dict) -> str:
    lines: list[str] = []

    def g(name: str, help_text: str, type_: str = "gauge") -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {type_}")

    # Cluster-level summary
    g("pvewatch_vms_total", "Total number of VMs and containers")
    lines.append(f"pvewatch_vms_total {data['summary']['total_vms']}")

    g("pvewatch_vms_backed_up", f"VMs with at least one successful backup in the last {data['days']} days")
    lines.append(f"pvewatch_vms_backed_up {data['summary']['backed_up']}")

    g("pvewatch_vms_never_backed_up", "VMs that have never had a recorded backup")
    lines.append(f"pvewatch_vms_never_backed_up {data['summary']['never_backed_up']}")

    g("pvewatch_backup_failure_events", f"Total individual backup failure days in the last {data['days']} days")
    lines.append(f"pvewatch_backup_failure_events {data['summary']['failure_events']}")

    g("pvewatch_vms_unresolved_failures", "VMs whose most recent backup failed (not yet recovered)")
    lines.append(f"pvewatch_vms_unresolved_failures {data['summary']['unresolved_failures']}")

    g("pvewatch_last_poll_timestamp_seconds", "Unix timestamp of the last successful Proxmox poll")
    lines.append(f"pvewatch_last_poll_timestamp_seconds {data['last_poll_ts']}")

    # Per-VM metrics
    g("pvewatch_backup_last_success_timestamp_seconds", "Unix timestamp of the most recent successful backup per VM")
    for vm in data["vms"]:
        lbl = f'vmid="{vm["vmid"]}",vm="{vm["name"]}",node="{vm["node"]}",type="{vm["vm_type"]}"'
        ts = vm["last_run_ts"] if vm["last_status"] == "OK" else 0
        lines.append(f"pvewatch_backup_last_success_timestamp_seconds{{{lbl}}} {ts}")

    g("pvewatch_backup_last_status", "Most recent backup status per VM: 1=ok, 0=failed, -1=stale, -2=never")
    for vm in data["vms"]:
        lbl = f'vmid="{vm["vmid"]}",vm="{vm["name"]}",node="{vm["node"]}",type="{vm["vm_type"]}"'
        if vm["last_status"] == "OK":
            val = 1
        elif vm["last_status"] and vm["last_status"] != "":
            val = 0
        elif vm["stale"]:
            val = -1
        else:
            val = -2
        lines.append(f"pvewatch_backup_last_status{{{lbl}}} {val}")

    g("pvewatch_backup_failures_window", f"Number of failed backup days in the last {data['days']} days per VM")
    for vm in data["vms"]:
        lbl = f'vmid="{vm["vmid"]}",vm="{vm["name"]}",node="{vm["node"]}",type="{vm["vm_type"]}"'
        lines.append(f"pvewatch_backup_failures_window{{{lbl}}} {vm['fail_count']}")

    # Per-pool storage metrics
    g("pvewatch_storage_used_bytes", "Storage pool used bytes")
    for s in data["storage"]:
        lbl = f'pool="{s["storage_id"]}",node="{s["node"]}"'
        lines.append(f"pvewatch_storage_used_bytes{{{lbl}}} {s['used_bytes']}")

    g("pvewatch_storage_total_bytes", "Storage pool total bytes")
    for s in data["storage"]:
        lbl = f'pool="{s["storage_id"]}",node="{s["node"]}"'
        lines.append(f"pvewatch_storage_total_bytes{{{lbl}}} {s['total_bytes']}")

    return "\n".join(lines) + "\n"


def run_web_server(conn: sqlite3.Connection, node: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            try:
                days = int(qs.get("days", ["7"])[0])
                if days not in (3, 5, 7, 14, 30):
                    days = 7
            except (ValueError, IndexError):
                days = 7

            if parsed.path in ("/", "/index.html"):
                body = _build_index(conn, node, days).encode()
                self._respond(body, "text/html; charset=utf-8")
            elif parsed.path == "/api/status":
                data = _build_data(conn, node, days)
                body = json.dumps(data, default=str).encode()
                self._respond(body, "application/json")
            elif parsed.path == "/metrics":
                data = _build_data(conn, node, days)
                body = _build_metrics(data).encode()
                self._respond(body, "text/plain; version=0.0.4; charset=utf-8")
            else:
                self.send_response(404)
                self.end_headers()

        def _respond(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            log.debug("web: " + fmt, *args)

    server = ThreadingHTTPServer(("", port), Handler)
    log.info("Web UI available at http://0.0.0.0:%d", port)
    log.info("API available at http://0.0.0.0:%d/api/status", port)
    log.info("Metrics available at http://0.0.0.0:%d/metrics", port)
    server.serve_forever()
