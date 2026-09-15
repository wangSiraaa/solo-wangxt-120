<template>
  <div ref="plotEl" class="map-plot"></div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import Plotly from 'plotly.js-dist-min'

const props = defineProps({
  stations: { type: Array, required: true },
  trueSource: { type: Object, required: true },
  results: { type: Object, default: () => ({}) },  // {raw: result, revised: result}
})
const plotEl = ref(null)

const KM_PER_DEG = 111.195

function ellipsePolygon(res) {
  const e = res.ellipse_68
  if (!e || res.lat == null) return null
  const lat0 = res.lat
  const cosLat = Math.cos((lat0 * Math.PI) / 180)
  const az = (e.major_axis_azimuth_deg * Math.PI) / 180
  const a = e.semi_major_km, b = e.semi_minor_km
  const lats = [], lons = []
  for (let i = 0; i <= 48; i++) {
    const t = (2 * Math.PI * i) / 48
    const east = a * Math.cos(t) * Math.sin(az) + b * Math.sin(t) * Math.cos(az)
    const north = a * Math.cos(t) * Math.cos(az) - b * Math.sin(t) * Math.sin(az)
    lats.push(lat0 + north / KM_PER_DEG)
    lons.push(res.lon + east / (KM_PER_DEG * cosLat))
  }
  return { lat: lats, lon: lons }
}

const STAGE_STYLE = {
  raw: { color: '#d62728', label: 'raw (原始拾取)' },
  revised: { color: '#2ca02c', label: 'revised (人工修订)' },
}

function render() {
  if (!plotEl.value) return
  const traces = [{
    type: 'scatter', mode: 'markers+text',
    lon: props.stations.map((s) => s.lon),
    lat: props.stations.map((s) => s.lat),
    text: props.stations.map((s) => s.id),
    textposition: 'top center',
    marker: { symbol: 'triangle-up', size: 12, color: '#1f77b4' },
    name: '台站',
  }]

  for (const [stage, res] of Object.entries(props.results)) {
    const style = STAGE_STYLE[stage] || { color: '#9467bd', label: stage }
    if (res.lat == null) continue
    const poly = ellipsePolygon(res)
    if (poly) {
      traces.push({
        type: 'scatter', mode: 'lines', lon: poly.lon, lat: poly.lat,
        line: { color: style.color, width: 1, dash: 'dash' },
        name: `${style.label} 68% 置信椭圆`, opacity: 0.7,
      })
    }
    traces.push({
      type: 'scatter', mode: 'markers',
      lon: [res.lon], lat: [res.lat],
      marker: { symbol: 'circle', size: 11, color: style.color },
      name: `${style.label} 解 (${res.status})`,
    })
    if (res.alternate_minimum) {
      traces.push({
        type: 'scatter', mode: 'markers',
        lon: [res.alternate_minimum.lon], lat: [res.alternate_minimum.lat],
        marker: { symbol: 'diamond-open', size: 13, color: style.color, line: { width: 2 } },
        name: `${style.label} 镜像模糊解`,
      })
    }
  }

  traces.push({
    type: 'scatter', mode: 'markers',
    lon: [props.trueSource.lon], lat: [props.trueSource.lat],
    marker: { symbol: 'star', size: 16, color: '#ffbf00', line: { color: '#000', width: 1 } },
    name: '真实震源 (教学真值)',
  })

  const allLats = [...props.stations.map((s) => s.lat), props.trueSource.lat]
  const allLons = [...props.stations.map((s) => s.lon), props.trueSource.lon]
  const layout = {
    margin: { l: 50, r: 10, t: 10, b: 40 },
    height: 420,
    xaxis: { title: '经度', range: [Math.min(...allLons) - 0.3, Math.max(...allLons) + 0.3] },
    yaxis: { title: '纬度', range: [Math.min(...allLats) - 0.3, Math.max(...allLats) + 0.3] },
    legend: { orientation: 'h', y: -0.18 },
  }
  Plotly.react(plotEl.value, traces, layout, { displayModeBar: false, responsive: true })
}

onMounted(render)
watch(() => [props.stations, props.results], render, { deep: true })
</script>
