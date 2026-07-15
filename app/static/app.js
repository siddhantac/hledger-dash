// ECharts dark theme, built from the same palette the Chart.js version used.
const CHART_COLORS = [
  '#6366f1', '#22d3ee', '#f59e0b', '#10b981',
  '#f43f5e', '#a78bfa', '#34d399', '#fb923c',
  '#38bdf8', '#facc15', '#4ade80', '#f472b6',
];

const AXIS_LINE = { lineStyle: { color: '#1f2937' } };
const AXIS_LABEL = { color: '#9ca3af' };
const SPLIT_LINE = { lineStyle: { color: '#1f2937' } };

function _initChart(elId) {
  const el = document.getElementById(elId);
  const chart = echarts.init(el);
  window.addEventListener('resize', () => chart.resize());
  return chart;
}

function pieChart(elId, labels, data) {
  const chart = _initChart(elId);
  chart.setOption({
    color: CHART_COLORS,
    tooltip: {
      trigger: 'item',
      formatter: p => `${p.name}: ${formatAmount(p.value)} (${p.percent}%)`,
    },
    legend: {
      orient: 'vertical', right: 0, top: 'center', type: 'scroll',
      textStyle: { color: '#9ca3af' },
    },
    series: [{
      type: 'pie',
      radius: ['0%', '70%'],
      center: ['40%', '50%'],
      data: labels.map((label, i) => ({ name: label, value: data[i] })),
      label: { color: '#9ca3af' },
      itemStyle: { borderColor: '#111827', borderWidth: 1 },
    }],
  });
  return chart;
}

function barChart(elId, labels, datasets) {
  const chart = _initChart(elId);
  chart.setOption({
    color: CHART_COLORS,
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 0, textStyle: { color: '#9ca3af' } },
    grid: { left: 55, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: labels, axisLine: AXIS_LINE, axisLabel: AXIS_LABEL },
    yAxis: {
      type: 'value', splitLine: SPLIT_LINE,
      axisLabel: { color: '#9ca3af', formatter: v => formatAmount(v) },
    },
    series: datasets.map(ds => ({
      name: ds.label,
      type: 'bar',
      data: ds.data,
      barMaxWidth: 28,
      itemStyle: { borderRadius: [4, 4, 0, 0] },
    })),
  });
  return chart;
}

function lineChart(elId, labels, datasets) {
  const chart = _initChart(elId);
  chart.setOption({
    color: CHART_COLORS,
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: { color: '#9ca3af' } },
    grid: { left: 55, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: labels, axisLine: AXIS_LINE, axisLabel: AXIS_LABEL },
    yAxis: {
      type: 'value', splitLine: SPLIT_LINE,
      axisLabel: { color: '#9ca3af', formatter: v => formatAmount(v) },
    },
    series: datasets.map(ds => ({
      name: ds.label,
      type: 'line',
      data: ds.data,
      smooth: 0.3,
      symbolSize: 6,
      lineStyle: { width: 2 },
      areaStyle: ds.fill === false ? undefined : { opacity: 0.13 },
    })),
  });
  return chart;
}

function sankeyChart(elId, nodes, links) {
  const chart = _initChart(elId);
  chart.setOption({
    color: CHART_COLORS,
    tooltip: {
      trigger: 'item',
      formatter: p => p.dataType === 'edge'
        ? `${p.data.source} → ${p.data.target}: ${formatAmount(p.data.value)}`
        : `${p.name}: ${formatAmount(p.value)}`,
    },
    series: [{
      type: 'sankey',
      data: nodes,
      links: links,
      emphasis: { focus: 'adjacency' },
      lineStyle: { color: 'gradient', curveness: 0.5, opacity: 0.4 },
      label: { color: '#e5e7eb' },
      itemStyle: { borderColor: '#111827' },
      nodeAlign: 'justify',
    }],
  });
  return chart;
}

function budgetChart(elId, rows) {
  const chart = _initChart(elId);
  const labels = rows.map(r => r.account);
  const pct = rows.map(r => r.pct === null ? 0 : Math.round(r.pct * 10) / 10);
  const maxPct = Math.max(120, ...pct);
  chart.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: params => {
        const r = rows[params[0].dataIndex];
        const pctLabel = r.pct === null ? 'no budget' : r.pct.toFixed(1) + '%';
        return `${r.account}: ${formatAmount(r.actual)} / ${formatAmount(r.budget)} (${pctLabel})`;
      },
    },
    grid: { left: 90, right: 40, top: 20, bottom: 30 },
    xAxis: {
      type: 'value', max: maxPct, splitLine: SPLIT_LINE,
      axisLabel: { color: '#9ca3af', formatter: v => v + '%' },
    },
    yAxis: { type: 'category', data: labels, axisLine: AXIS_LINE, axisLabel: AXIS_LABEL },
    series: [{
      type: 'bar',
      data: pct.map(p => ({ value: p, itemStyle: { color: p > 100 ? '#f43f5e' : '#10b981' } })),
      barMaxWidth: 20,
      markLine: {
        symbol: 'none',
        silent: true,
        lineStyle: { color: '#facc15', type: 'dashed' },
        label: { formatter: '100%', color: '#facc15' },
        data: [{ xAxis: 100 }],
      },
    }],
  });
  return chart;
}

function quickRange(range) {
  const form = document.querySelector('form[data-first-month]');
  if (!form) return;
  const fromInput = form.querySelector('[name=date_from]');
  const toInput   = form.querySelector('[name=date_to]');
  const now = new Date();
  const y   = now.getFullYear();
  const cur = `${y}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  const lm  = now.getMonth() === 0
    ? `${y - 1}-12`
    : `${y}-${String(now.getMonth()).padStart(2, '0')}`;
  const first = form.dataset.firstMonth || cur;
  const map = {
    ytd:       [String(y) + '-01', cur],
    lastmonth: [lm, lm],
    lastyear:  [`${y - 1}-01`, `${y - 1}-12`],
    alltime:   [first, cur],
  };
  if (!map[range]) return;
  [fromInput.value, toInput.value] = map[range];
  form.submit();
}

function formatAmount(value) {
  if (Math.abs(value) >= 1000) {
    return (value / 1000).toFixed(1) + 'k';
  }
  return value.toFixed(0);
}
