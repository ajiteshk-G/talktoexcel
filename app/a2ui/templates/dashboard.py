# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Responsive HTML5 dashboard template generator for A2UI WebFrame components.

Features:
- Self-contained styling and scripts conforming to strict CSP (connect-src 'none').
- Executive KPI summary cards with dynamic status chips.
- Interactive SVG charts (Bar, Horizontal Bar, Line, Donut) with hover tooltips.
- Client-side searchable, sortable, and paginated data tables.
- Bidirectional window.parent.postMessage action dispatching to Gemini Enterprise.
"""

import html
import json
from typing import Any, Dict, List, Optional


def generate_dashboard_html(
    title: str,
    summary_metrics: Optional[List[Dict[str, Any]]] = None,
    chart_type: str = "bar",
    chart_data: Optional[Dict[str, Any]] = None,
    table_headers: Optional[List[str]] = None,
    table_rows: Optional[List[List[Any]]] = None,
    suggested_actions: Optional[List[Dict[str, Any]]] = None,
    subtitle: Optional[str] = None,
) -> str:
    """Renders a fully self-contained, interactive HTML5 dashboard string.

    Args:
        title: Main dashboard title.
        summary_metrics: List of KPI card dicts:
            [{"label": "Total Revenue", "value": "$1.45M", "delta": "+14%", "is_positive": True}]
        chart_type: "bar" | "horizontal_bar" | "line" | "donut"
        chart_data: Dict containing labels and datasets:
            {"labels": ["Q1", "Q2"], "datasets": [{"label": "Sales", "data": [100, 150]}]}
            or for donut: {"labels": ["A", "B"], "values": [60, 40]}
        table_headers: Column header names for data table.
        table_rows: 2D list of row cells.
        suggested_actions: List of action button configs:
            [{"label": "Export Word Report", "name": "export_word_report", "context": {}}]
        subtitle: Subtitle text.

    Returns:
        A standalone HTML5 string.
    """
    safe_title = html.escape(title or "Analytics Dashboard")
    safe_subtitle = html.escape(subtitle or "BigQuery Conversational Intelligence")

    metrics_list = summary_metrics or []
    chart_info = chart_data or {}
    headers_list = table_headers or []
    rows_list = table_rows or []
    actions_list = suggested_actions or []

    # Prepare JSON payloads for script consumption
    chart_json = json.dumps({
        "type": chart_type.lower(),
        "labels": chart_info.get("labels", []),
        "datasets": chart_info.get("datasets", []),
        "values": chart_info.get("values", []),
    })

    table_data_json = json.dumps({
        "headers": headers_list,
        "rows": rows_list,
    })

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'self' 'unsafe-inline'; connect-src 'none';">
<title>{safe_title}</title>
<style>
  :root {{
    --primary: #1a73e8;
    --primary-dark: #1557b0;
    --primary-light: #e8f0fe;
    --success: #1e8e3e;
    --success-bg: #e6f4ea;
    --danger: #d93025;
    --danger-bg: #fce8e6;
    --text-primary: #202124;
    --text-secondary: #5f6368;
    --border-color: #dadce0;
    --card-bg: #ffffff;
    --bg-page: #f8f9fa;
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 14px;
    --shadow-sm: 0 1px 2px 0 rgba(60,64,67,.3), 0 1px 3px 1px rgba(60,64,67,.15);
    --shadow-md: 0 1px 3px 0 rgba(60,64,67,.3), 0 4px 8px 3px rgba(60,64,67,.15);
  }}

  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}

  body {{
    background-color: var(--bg-page);
    color: var(--text-primary);
    padding: 16px;
    line-height: 1.5;
  }}

  .dashboard-container {{
    max-width: 1100px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }}

  /* Header Section */
  .header-card {{
    background: var(--card-bg);
    padding: 18px 24px;
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-sm);
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-left: 5px solid var(--primary);
  }}

  .header-left h1 {{
    font-size: 20px;
    font-weight: 600;
    color: var(--text-primary);
  }}

  .header-left p {{
    font-size: 13px;
    color: var(--text-secondary);
    margin-top: 2px;
  }}

  .header-badge {{
    background: var(--primary-light);
    color: var(--primary);
    font-size: 12px;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 20px;
    letter-spacing: 0.3px;
  }}

  /* KPI Summary Cards Grid */
  .metrics-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 14px;
  }}

  .metric-card {{
    background: var(--card-bg);
    padding: 16px 20px;
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-sm);
    display: flex;
    flex-direction: column;
    gap: 6px;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }}

  .metric-card:hover {{
    transform: translateY(-2px);
    box-shadow: var(--shadow-md);
  }}

  .metric-label {{
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}

  .metric-value-row {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
  }}

  .metric-value {{
    font-size: 24px;
    font-weight: 700;
    color: var(--text-primary);
  }}

  .metric-delta {{
    font-size: 12px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 12px;
  }}

  .metric-delta.positive {{
    color: var(--success);
    background: var(--success-bg);
  }}

  .metric-delta.negative {{
    color: var(--danger);
    background: var(--danger-bg);
  }}

  /* Chart & Analytics Section */
  .chart-card {{
    background: var(--card-bg);
    padding: 20px;
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-sm);
  }}

  .card-title {{
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 12px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}

  .chart-wrapper {{
    position: relative;
    width: 100%;
    min-height: 280px;
    display: flex;
    justify-content: center;
    align-items: center;
  }}

  svg.chart-canvas {{
    width: 100%;
    height: 100%;
    min-height: 280px;
    overflow: visible;
  }}

  /* Tooltip */
  .chart-tooltip {{
    position: absolute;
    display: none;
    background: rgba(32, 33, 36, 0.95);
    color: #ffffff;
    padding: 6px 12px;
    border-radius: var(--radius-sm);
    font-size: 12px;
    pointer-events: none;
    z-index: 1000;
    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
    white-space: nowrap;
    transition: opacity 0.1s ease;
  }}

  /* Data Table Section */
  .table-card {{
    background: var(--card-bg);
    padding: 20px;
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-sm);
  }}

  .table-toolbar {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    gap: 12px;
    flex-wrap: wrap;
  }}

  .search-input {{
    padding: 8px 14px;
    font-size: 13px;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    outline: none;
    width: 260px;
    transition: border-color 0.2s;
  }}

  .search-input:focus {{
    border-color: var(--primary);
  }}

  .table-responsive {{
    overflow-x: auto;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
  }}

  table.data-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    text-align: left;
  }}

  table.data-table th {{
    background: #f1f3f4;
    color: var(--text-primary);
    font-weight: 600;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border-color);
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
  }}

  table.data-table th:hover {{
    background: #e8eaed;
  }}

  table.data-table th .sort-icon {{
    margin-left: 6px;
    font-size: 10px;
    color: var(--text-secondary);
  }}

  table.data-table td {{
    padding: 9px 14px;
    border-bottom: 1px solid var(--border-color);
    color: var(--text-primary);
    white-space: nowrap;
  }}

  table.data-table tr:last-child td {{
    border-bottom: none;
  }}

  table.data-table tr:hover td {{
    background: #f8f9fa;
  }}

  /* Pagination */
  .table-pagination {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 12px;
    font-size: 12px;
    color: var(--text-secondary);
  }}

  .pagination-buttons {{
    display: flex;
    gap: 6px;
  }}

  .btn-page {{
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 500;
    background: #ffffff;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    cursor: pointer;
    color: var(--text-primary);
  }}

  .btn-page:hover:not(:disabled) {{
    background: #f1f3f4;
    border-color: #c6c9cc;
  }}

  .btn-page:disabled {{
    opacity: 0.5;
    cursor: not-allowed;
  }}

  /* Suggested Action Footer */
  .action-footer {{
    background: var(--card-bg);
    padding: 14px 20px;
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-sm);
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 10px;
  }}

  .action-footer-label {{
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary);
  }}

  .action-chips {{
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }}

  .action-chip {{
    padding: 7px 14px;
    background: var(--primary-light);
    color: var(--primary);
    border: 1px solid #c2e7ff;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: all 0.15s ease;
  }}

  .action-chip:hover {{
    background: var(--primary);
    color: #ffffff;
    box-shadow: 0 1px 3px rgba(26,115,232,0.4);
  }}

  /* Action Toast */
  .action-toast {{
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: #323232;
    color: #fff;
    padding: 10px 18px;
    border-radius: var(--radius-sm);
    font-size: 13px;
    box-shadow: var(--shadow-md);
    display: none;
    align-items: center;
    gap: 8px;
    z-index: 9999;
  }}
</style>
</head>
<body>

<div class="dashboard-container">
  <!-- Header Card -->
  <div class="header-card">
    <div class="header-left">
      <h1>{safe_title}</h1>
      <p>{safe_subtitle}</p>
    </div>
    <div class="header-badge">Live Interactive A2UI</div>
  </div>

  <!-- KPI Metrics Grid -->
  <div class="metrics-grid" id="metricsContainer">
    <!-- Generated dynamically -->
  </div>

  <!-- Chart Card -->
  <div class="chart-card">
    <div class="card-title">
      <span>Visualization: {chart_type.replace('_', ' ').title()}</span>
      <span style="font-size: 12px; font-weight: normal; color: var(--text-secondary);">Hover points to inspect</span>
    </div>
    <div class="chart-wrapper">
      <svg id="svgChart" class="chart-canvas" viewBox="0 0 900 320"></svg>
      <div id="chartTooltip" class="chart-tooltip"></div>
    </div>
  </div>

  <!-- Data Table Card (if data provided) -->
  <div class="table-card" id="tableCard" style="display: {'block' if headers_list else 'none'};">
    <div class="table-toolbar">
      <div class="card-title" style="margin-bottom: 0;">Tabular Inspection</div>
      <input type="text" id="tableSearchInput" class="search-input" placeholder="Quick search rows...">
    </div>
    <div class="table-responsive">
      <table class="data-table" id="dataTable">
        <thead id="tableHead"></thead>
        <tbody id="tableBody"></tbody>
      </table>
    </div>
    <div class="table-pagination">
      <span id="pageInfo">Showing 0 of 0</span>
      <div class="pagination-buttons">
        <button id="prevBtn" class="btn-page" disabled>Previous</button>
        <button id="nextBtn" class="btn-page" disabled>Next</button>
      </div>
    </div>
  </div>

  <!-- Action Footer -->
  <div class="action-footer" id="actionFooter" style="display: {'flex' if actions_list else 'none'};">
    <span class="action-footer-label">Suggested Actions:</span>
    <div class="action-chips" id="actionChips"></div>
  </div>
</div>

<div id="toast" class="action-toast">Action dispatched to agent...</div>

<script>
(function() {{
  const rawMetrics = {json.dumps(metrics_list)};
  const chartConfig = {chart_json};
  const tableData = {table_data_json};
  const suggestedActions = {json.dumps(actions_list)};

  // 1. Render KPI Metric Cards
  const metricsContainer = document.getElementById("metricsContainer");
  if (rawMetrics && rawMetrics.length > 0) {{
    metricsContainer.innerHTML = rawMetrics.map(m => {{
      const deltaClass = m.is_positive === false ? "negative" : "positive";
      const deltaText = m.delta ? `<span class="metric-delta ${{deltaClass}}">${{m.delta}}</span>` : "";
      return `
        <div class="metric-card">
          <div class="metric-label">${{m.label || ""}}</div>
          <div class="metric-value-row">
            <span class="metric-value">${{m.value || ""}}</span>
            ${{deltaText}}
          </div>
        </div>
      `;
    }}).join("");
  }} else {{
    metricsContainer.style.display = "none";
  }}

  // 2. Render Interactive SVG Charts
  const svg = document.getElementById("svgChart");
  const tooltip = document.getElementById("chartTooltip");

  function showTooltip(evt, text) {{
    tooltip.style.display = "block";
    tooltip.innerHTML = text;
    const rect = svg.getBoundingClientRect();
    const x = evt.clientX - rect.left + 12;
    const y = evt.clientY - rect.top - 28;
    tooltip.style.left = `${{x}}px`;
    tooltip.style.top = `${{y}}px`;
  }}

  function hideTooltip() {{
    tooltip.style.display = "none";
  }}

  const colors = ["#1a73e8", "#34a853", "#fbbc04", "#ea4335", "#9334e6", "#00acc1", "#ff7043"];

  if (chartConfig.type === "bar" || chartConfig.type === "horizontal_bar") {{
    renderBarChart(chartConfig);
  }} else if (chartConfig.type === "line") {{
    renderLineChart(chartConfig);
  }} else if (chartConfig.type === "donut") {{
    renderDonutChart(chartConfig);
  }} else {{
    renderBarChart(chartConfig);
  }}

  function renderBarChart(cfg) {{
    const labels = cfg.labels || [];
    const ds = (cfg.datasets && cfg.datasets[0]) || {{ data: [] }};
    const data = ds.data || [];
    if (labels.length === 0 || data.length === 0) return;

    const maxVal = Math.max(...data, 1);
    const chartW = 820;
    const chartH = 240;
    const padX = 60;
    const padY = 30;

    let elements = "";
    const numBars = labels.length;
    const barWidth = Math.min(60, Math.max(16, (chartW - (numBars * 10)) / numBars));
    const step = (chartW - barWidth) / Math.max(1, numBars - 1);

    // Draw gridlines
    for (let i = 0; i <= 4; i++) {{
      const y = padY + (chartH / 4) * i;
      const valLabel = Math.round(maxVal - (maxVal / 4) * i);
      elements += `
        <line x1="${{padX}}" y1="${{y}}" x2="${{padX + chartW}}" y2="${{y}}" stroke="#e8eaed" stroke-width="1" />
        <text x="${{padX - 8}}" y="${{y + 4}}" fill="#80868b" font-size="11" text-anchor="end">${{valLabel.toLocaleString()}}</text>
      `;
    }}

    // Draw bars
    labels.forEach((lbl, idx) => {{
      const val = data[idx] || 0;
      const h = (val / maxVal) * chartH;
      const x = padX + (numBars === 1 ? (chartW - barWidth) / 2 : idx * step);
      const y = padY + chartH - h;
      const col = colors[idx % colors.length];

      elements += `
        <rect x="${{x}}" y="${{y}}" width="${{barWidth}}" height="${{h}}" rx="4" fill="${{col}}"
              style="cursor: pointer; transition: opacity 0.15s;"
              onmouseover="window.showChartTip(event, '${{lbl}}: <b>${{val.toLocaleString()}}</b>')"
              onmousemove="window.showChartTip(event, '${{lbl}}: <b>${{val.toLocaleString()}}</b>')"
              onmouseout="window.hideChartTip()" />
        <text x="${{x + barWidth / 2}}" y="${{padY + chartH + 20}}" fill="#5f6368" font-size="11" text-anchor="middle">
          ${{lbl.length > 12 ? lbl.substring(0, 10) + '..' : lbl}}
        </text>
      `;
    }});

    svg.innerHTML = elements;
  }}

  function renderLineChart(cfg) {{
    const labels = cfg.labels || [];
    const ds = (cfg.datasets && cfg.datasets[0]) || {{ data: [] }};
    const data = ds.data || [];
    if (labels.length === 0 || data.length === 0) return;

    const maxVal = Math.max(...data, 1);
    const minVal = Math.min(...data, 0);
    const range = maxVal - minVal || 1;
    const chartW = 820;
    const chartH = 240;
    const padX = 60;
    const padY = 30;

    const step = chartW / Math.max(1, labels.length - 1);
    const points = data.map((v, i) => {{
      const x = padX + i * step;
      const y = padY + chartH - ((v - minVal) / range) * chartH;
      return {{ x, y, v, lbl: labels[i] }};
    }});

    let pathD = `M ${{points[0].x}} ${{points[0].y}}`;
    for (let i = 1; i < points.length; i++) {{
      pathD += ` L ${{points[i].x}} ${{points[i].y}}`;
    }}

    let elements = `
      <defs>
        <linearGradient id="lineGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#1a73e8" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="#1a73e8" stop-opacity="0.0"/>
        </linearGradient>
      </defs>
      <!-- Gridlines -->
    `;

    for (let i = 0; i <= 4; i++) {{
      const y = padY + (chartH / 4) * i;
      const valLabel = Math.round(maxVal - (range / 4) * i);
      elements += `
        <line x1="${{padX}}" y1="${{y}}" x2="${{padX + chartW}}" y2="${{y}}" stroke="#e8eaed" stroke-width="1" />
        <text x="${{padX - 8}}" y="${{y + 4}}" fill="#80868b" font-size="11" text-anchor="end">${{valLabel.toLocaleString()}}</text>
      `;
    }}

    // Area fill under line
    const areaD = `${{pathD}} L ${{points[points.length - 1].x}} ${{padY + chartH}} L ${{points[0].x}} ${{padY + chartH}} Z`;
    elements += `<path d="${{areaD}}" fill="url(#lineGrad)" />`;
    elements += `<path d="${{pathD}}" fill="none" stroke="#1a73e8" stroke-width="3" stroke-linecap="round" />`;

    // Dots and hover handlers
    points.forEach(p => {{
      elements += `
        <circle cx="${{p.x}}" cy="${{p.y}}" r="5" fill="#1a73e8" stroke="#ffffff" stroke-width="2"
                style="cursor: pointer;"
                onmouseover="window.showChartTip(event, '${{p.lbl}}: <b>${{p.v.toLocaleString()}}</b>')"
                onmousemove="window.showChartTip(event, '${{p.lbl}}: <b>${{p.v.toLocaleString()}}</b>')"
                onmouseout="window.hideChartTip()" />
        <text x="${{p.x}}" y="${{padY + chartH + 20}}" fill="#5f6368" font-size="11" text-anchor="middle">
          ${{p.lbl.length > 12 ? p.lbl.substring(0, 10) + '..' : p.lbl}}
        </text>
      `;
    }});

    svg.innerHTML = elements;
  }}

  function renderDonutChart(cfg) {{
    const labels = cfg.labels || [];
    const values = cfg.values && cfg.values.length > 0 ? cfg.values : (cfg.datasets && cfg.datasets[0] ? cfg.datasets[0].data : []);
    if (!values || values.length === 0) return;

    const total = values.reduce((a, b) => a + b, 0) || 1;
    const cx = 300;
    const cy = 160;
    const r = 90;
    const strokeWidth = 36;
    const circ = 2 * Math.PI * r;

    let elements = `<g transform="rotate(-90 ${{cx}} ${{cy}})">`;
    let accumulatedAngle = 0;

    values.forEach((v, idx) => {{
      const ratio = v / total;
      const dash = ratio * circ;
      const offset = -(accumulatedAngle * circ);
      const col = colors[idx % colors.length];
      const lbl = labels[idx] || `Item ${{idx + 1}}`;
      const pct = (ratio * 100).toFixed(1);

      elements += `
        <circle cx="${{cx}}" cy="${{cy}}" r="${{r}}" fill="transparent"
                stroke="${{col}}" stroke-width="${{strokeWidth}}"
                stroke-dasharray="${{dash}} ${{circ - dash}}"
                stroke-dashoffset="${{offset}}"
                style="cursor: pointer; transition: stroke-width 0.15s;"
                onmouseover="window.showChartTip(event, '${{lbl}}: <b>${{v.toLocaleString()}}</b> (${{pct}}%)')"
                onmousemove="window.showChartTip(event, '${{lbl}}: <b>${{v.toLocaleString()}}</b> (${{pct}}%)')"
                onmouseout="window.hideChartTip()" />
      `;
      accumulatedAngle += ratio;
    }});

    elements += `</g>`;
    elements += `
      <text x="${{cx}}" y="${{cy - 5}}" fill="#202124" font-size="20" font-weight="bold" text-anchor="middle">${{total.toLocaleString()}}</text>
      <text x="${{cx}}" y="${{cy + 15}}" fill="#5f6368" font-size="12" text-anchor="middle">Total</text>
    `;

    // Legend on the right
    let legendY = 60;
    labels.forEach((lbl, idx) => {{
      const col = colors[idx % colors.length];
      const val = values[idx] || 0;
      const pct = ((val / total) * 100).toFixed(1);
      elements += `
        <rect x="520" y="${{legendY}}" width="14" height="14" rx="3" fill="${{col}}" />
        <text x="544" y="${{legendY + 12}}" fill="#202124" font-size="13">${{lbl}}</text>
        <text x="760" y="${{legendY + 12}}" fill="#5f6368" font-size="13" text-anchor="end">${{val.toLocaleString()}} (${{pct}}%)</text>
      `;
      legendY += 28;
    }});

    svg.innerHTML = elements;
  }}

  window.showChartTip = showTooltip;
  window.hideChartTip = hideTooltip;

  // 3. Render Searchable & Paginated Table
  const thead = document.getElementById("tableHead");
  const tbody = document.getElementById("tableBody");
  const searchInput = document.getElementById("tableSearchInput");
  const pageInfo = document.getElementById("pageInfo");
  const prevBtn = document.getElementById("prevBtn");
  const nextBtn = document.getElementById("nextBtn");

  let tableRows = (tableData.rows || []).slice();
  const headers = tableData.headers || [];
  let currentPage = 1;
  const pageSize = 8;
  let sortCol = -1;
  let sortAsc = true;

  if (headers.length > 0) {{
    thead.innerHTML = `<tr>${{
      headers.map((h, i) => `<th onclick="window.sortTable(${{i}})">${{h}} <span class="sort-icon" id="sort_${{i}}">↕</span></th>`).join("")
    }}</tr>`;
    renderTable();
  }}

  function filterAndSortRows() {{
    const query = (searchInput.value || "").toLowerCase().trim();
    let filtered = tableRows.filter(row => {{
      if (!query) return true;
      return row.some(cell => String(cell).toLowerCase().includes(query));
    }});

    if (sortCol >= 0) {{
      filtered.sort((a, b) => {{
        const vA = a[sortCol];
        const vB = b[sortCol];
        const numA = Number(vA);
        const numB = Number(vB);
        if (!isNaN(numA) && !isNaN(numB)) {{
          return sortAsc ? numA - numB : numB - numA;
        }}
        return sortAsc ? String(vA).localeCompare(String(vB)) : String(vB).localeCompare(String(vA));
      }});
    }}
    return filtered;
  }}

  function renderTable() {{
    const rows = filterAndSortRows();
    const totalRows = rows.length;
    const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));
    if (currentPage > totalPages) currentPage = totalPages;

    const startIdx = (currentPage - 1) * pageSize;
    const pageRows = rows.slice(startIdx, startIdx + pageSize);

    tbody.innerHTML = pageRows.map(r => `
      <tr>${{r.map(c => `<td>${{c !== null && c !== undefined ? c : ""}}</td>`).join("")}}</tr>
    `).join("");

    pageInfo.innerText = totalRows === 0
      ? "Showing 0 of 0 entries"
      : `Showing ${{startIdx + 1}} to ${{Math.min(startIdx + pageSize, totalRows)}} of ${{totalRows}} entries`;

    prevBtn.disabled = currentPage <= 1;
    nextBtn.disabled = currentPage >= totalPages;
  }}

  window.sortTable = function(colIndex) {{
    if (sortCol === colIndex) {{
      sortAsc = !sortAsc;
    }} else {{
      sortCol = colIndex;
      sortAsc = true;
    }}
    headers.forEach((_, i) => {{
      const icon = document.getElementById(`sort_${{i}}`);
      if (icon) icon.innerText = i === sortCol ? (sortAsc ? "▲" : "▼") : "↕";
    }});
    renderTable();
  }};

  searchInput.addEventListener("input", () => {{
    currentPage = 1;
    renderTable();
  }});

  prevBtn.addEventListener("click", () => {{
    if (currentPage > 1) {{
      currentPage--;
      renderTable();
    }}
  }});

  nextBtn.addEventListener("click", () => {{
    currentPage++;
    renderTable();
  }});

  // 4. Action Chips & Bidirectional postMessage
  const actionChipsContainer = document.getElementById("actionChips");
  const toast = document.getElementById("toast");

  function sendAgentAction(actionName, contextData) {{
    const payload = {{
      type: "a2ui_action",
      name: actionName,
      context: contextData || {{}}
    }};
    // Send postMessage to parent frame (Gemini Enterprise)
    window.parent.postMessage(payload, "*");

    // Visual feedback
    toast.innerText = `Dispatched '${{actionName}}' to agent`;
    toast.style.display = "flex";
    setTimeout(() => {{
      toast.style.display = "none";
    }}, 2800);
  }}

  if (suggestedActions && suggestedActions.length > 0) {{
    actionChipsContainer.innerHTML = suggestedActions.map((act, i) => `
      <button class="action-chip" onclick='window.triggerAction(${{i}})'>
        <span>✦</span> ${{act.label || act.name}}
      </button>
    `).join("");

    window.triggerAction = function(index) {{
      const act = suggestedActions[index];
      if (act) {{
        sendAgentAction(act.name, act.context || {{}});
      }}
    }};
  }}
}})();
</script>

</body>
</html>
"""
