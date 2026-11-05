"""Keep the explicit completion control synchronized with the current answer."""

_UPDATE_PENDING_JS = r"""
(value) => {
  const done = document.getElementById('autojob-unknown-done');
  if (done) done.disabled = !value;
  const status = document.getElementById('autojob-unknown-status');
  if (status) {
    status.textContent = value ? 'Answer detected. Finish answering to save it.' : '';
    status.style.display = value ? 'block' : 'none';
  }
  return true;
}
"""
