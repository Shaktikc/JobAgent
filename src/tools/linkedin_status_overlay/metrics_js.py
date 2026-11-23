"""Metrics rows use textContent and preserve the activity row."""

UPDATE_METRICS_JS = r"""
(live) => {
  const box = document.getElementById('autojob-status');
  if (!box) return false;
  for (const id of ['autojob-submission-metrics', 'autojob-usage-note']) {
    document.getElementById(id)?.remove();
  }
  for (const [id, text] of [
    ['autojob-session-heading', 'Current session info'],
    ['autojob-session-metrics', live]
  ]) {
    let row = document.getElementById(id);
    if (!row) {
      row = document.createElement('div');
      row.id = id;
      row.style.cssText = 'font-size:11px;margin-top:4px;pointer-events:none';
      box.appendChild(row);
    }
    row.textContent = text;
    row.hidden = !text;
  }
  return true;
}
"""
