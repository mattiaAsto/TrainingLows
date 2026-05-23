Charting Guide for TrainingLows

Overview
- This guide explains how to create and manage charts using Chart.js (recommended) or other JS charting libraries.
- Templates include canvas elements: `weeklyDistanceChart`, `monthlyBarChart`, `activityDonutChart`, `intensityChart`, `paceSpeedChart`, `intensityDonut`.

Install Chart.js
- Add Chart.js to your base template (e.g., in `main_base.html`) via CDN:

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

Server-side data shape
- Provide JSON-serializable data from your Flask view via Jinja variables.
- Examples:
  - `weekly_data = { labels: [...], distances: [...] }`
  - `monthly_data = { labels: [...], distances: [...] }`
  - `activity_distribution = { labels: ['Running','Cycling','Swimming'], values: [120,80,40] }`

Embedding data in templates
- Safely serialize with `|tojson` filter (Jinja):

```jinja
<script>
  const weeklyData = {{ weekly_data|tojson }};
</script>
```

Basic chart initialization (example)

```js
const ctx = document.getElementById('weeklyDistanceChart').getContext('2d');
const chart = new Chart(ctx, {
  type: 'line',
  data: {
    labels: weeklyData.labels,
    datasets: [{
      label: 'Distance (km)',
      data: weeklyData.distances,
      borderColor: '#dc3545',
      backgroundColor: 'rgba(220,53,69,0.1)',
      tension: 0.2,
      fill: true,
    }]
  },
  options: { responsive: true, maintainAspectRatio: false }
});
```

Managing multiple charts
- Create a small helper function to build charts with defaults (colors, font sizes).
- Store chart instances globally if you plan to update or destroy them.
- To update data: `chart.data.datasets[0].data = newData; chart.update();`

Performance tips
- Do not render charts with huge datasets on page load; paginate or fetch via AJAX.
- Use `decimation` plugin (Chart.js) for large series: reduces points drawn.
- Keep `maintainAspectRatio: false` and control container height with CSS.

Interactivity
- Use tooltips and hover callbacks for custom interactions.
- Add click handlers on canvas to open detail views for a clicked point.

Async updates
- Create an endpoint that returns JSON (e.g., `/api/charts/weekly?start=...`) and fetch with `fetch()`.
- On response, call `chart.data.datasets[0].data = data.values; chart.update();`

Color system
- Use the app palette: running `#dc3545`, cycling `#007bff`, swimming `#28a745` for dataset colors to match UI.

Example: rendering `activityDonutChart`

```js
const dist = {{ activity_distribution|tojson }}; // { labels:[], values:[] }
new Chart(document.getElementById('activityDonutChart'), {
  type: 'doughnut',
  data: { labels: dist.labels, datasets:[{ data: dist.values, backgroundColor:['#dc3545','#007bff','#28a745'] }]},
  options: { responsive: true, plugins: { legend: { position: 'bottom' } } }
});
```

Troubleshooting
- Canvas size blank: ensure parent container has height set via CSS.
- `tojson` errors: ensure data is serializable (no datetime objects; convert to strings or numbers).
- Mixed-type labels: keep labels consistent (strings).

Advanced
- Use WebSockets for real-time charts.
- For heavy analytics, pre-aggregate data server-side and send summarized arrays.

That's all — follow this guide to wire your Flask views to template charts. If you want, I can implement example Chart.js initializers in the `graphs.html` and `analysis.html` using placeholder data from the route.
