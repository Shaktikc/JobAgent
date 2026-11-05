"""Keep the explicit completion control synchronized with the current answer."""

_UPDATE_PENDING_JS = r"""
(value, multiple = false) => {
  const done = document.getElementById('autojob-unknown-done');
  if (done) done.disabled = !value;
  const status = document.getElementById('autojob-unknown-status');
  if (status) {
    status.textContent = value
      ? (multiple ? 'Selected: ' + value + '. ' : 'Answer detected. ')
        + 'Click Done to save and continue.' : '';
    status.style.display = value ? 'block' : 'none';
  }
  return true;
}
"""
