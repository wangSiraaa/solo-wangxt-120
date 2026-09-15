const BASE = '/api'

async function req(path, options) {
  const r = await fetch(BASE + path, options)
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body.detail || `HTTP ${r.status}`)
  }
  return r.json()
}

export const api = {
  listScenarios: () => req('/scenarios'),
  getScenario: (id) => req(`/scenarios/${id}`),
  getWaveforms: (id) => req(`/scenarios/${id}/waveforms`),
  getVelocityModel: () => req('/velocity-model'),
  locate: (id) => req(`/scenarios/${id}/locate`, { method: 'POST' }),
  saveRevisedPicks: (id, picks) =>
    req(`/scenarios/${id}/picks/revised`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ picks }),
    }),
}
