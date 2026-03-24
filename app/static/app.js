// Chart.js global defaults for dark theme
Chart.defaults.color = '#9ca3af';
Chart.defaults.borderColor = '#1f2937';
Chart.defaults.backgroundColor = 'transparent';

const CHART_COLORS = [
  '#6366f1', '#22d3ee', '#f59e0b', '#10b981',
  '#f43f5e', '#a78bfa', '#34d399', '#fb923c',
  '#38bdf8', '#facc15', '#4ade80', '#f472b6',
];

function pieChart(canvasId, labels, data) {
  const ctx = document.getElementById(canvasId).getContext('2d');
  return new Chart(ctx, {
    type: 'pie',
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: CHART_COLORS.slice(0, data.length),
        borderWidth: 1,
        borderColor: '#111827',
      }]
    },
    options: {
      plugins: {
        legend: { position: 'right' }
      }
    }
  });
}

function barChart(canvasId, labels, datasets) {
  const ctx = document.getElementById(canvasId).getContext('2d');
  return new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: datasets.map((ds, i) => ({
        ...ds,
        backgroundColor: CHART_COLORS[i] + 'cc',
        borderColor: CHART_COLORS[i],
        borderWidth: 1,
        borderRadius: 4,
      }))
    },
    options: {
      responsive: true,
      scales: {
        x: { grid: { color: '#1f2937' } },
        y: { grid: { color: '#1f2937' }, ticks: { callback: v => formatAmount(v) } }
      },
      plugins: { legend: { position: 'top' } }
    }
  });
}

function lineChart(canvasId, labels, datasets) {
  const ctx = document.getElementById(canvasId).getContext('2d');
  return new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: datasets.map((ds, i) => ({
        ...ds,
        borderColor: CHART_COLORS[i],
        backgroundColor: CHART_COLORS[i] + '22',
        fill: true,
        tension: 0.3,
        pointRadius: 4,
      }))
    },
    options: {
      responsive: true,
      scales: {
        x: { grid: { color: '#1f2937' } },
        y: { grid: { color: '#1f2937' }, ticks: { callback: v => formatAmount(v) } }
      },
      plugins: { legend: { position: 'top' } }
    }
  });
}

function formatAmount(value) {
  if (Math.abs(value) >= 1000) {
    return (value / 1000).toFixed(1) + 'k';
  }
  return value.toFixed(0);
}
