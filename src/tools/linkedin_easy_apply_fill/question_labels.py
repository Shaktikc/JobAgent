"""Browser helpers for each question's own visible label, independent of metadata.

SDUI puts headings before bare fieldsets, sometimes followed by helper text.
Classic forms use labels and legends. Resolve those visible nodes before aria
text, and never borrow markers from options or neighbouring questions.
"""

QUESTION_LABEL_JS = r"""const questionControls =
    'input,select,textarea,[role="radio"],[role="checkbox"]';
  const questionGroups = 'fieldset,[role="radiogroup"],[role="group"]';
  const labelNodeVisible = (node) => {
    if (!node) return false;
    for (let p = node; p; p = p.parentElement) {
      const style = getComputedStyle(p);
      if (p.hidden || style.display === 'none' || style.visibility === 'hidden'
          || style.visibility === 'collapse' || style.opacity === '0') return false;
    }
    return true;
  };
  const visibleLabelText = (node) => {
    if (!labelNodeVisible(node) || !node.getClientRects().length) return '';
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    const parts = [];
    while (walker.nextNode()) {
      const text = walker.currentNode;
      if (labelNodeVisible(text.parentElement) && !text.parentElement.closest(questionControls)) {
        parts.push(text.textContent);
      }
    }
    // Classic LinkedIn labels draw '*' in CSS rather than a DOM text node.
    // Inspect only this label's rendered pseudo-elements, never metadata or
    // neighbouring helpers. Hidden generated markers do not require a field.
    for (const el of [node, ...node.querySelectorAll('*')]) {
      if (!labelNodeVisible(el) || el.closest(questionControls)) continue;
      for (const pseudo of ['::before', '::after']) {
        const style = getComputedStyle(el, pseudo);
        const content = style.content.match(/^(['"])(.*)\1$/);
        if (content && content[2].includes('*') && style.display !== 'none'
            && !['hidden', 'collapse'].includes(style.visibility) && style.opacity !== '0') {
          parts.push('*');
        }
      }
    }
    return norm(parts.join(' '));
  };
  const referencedLabel = (el) => {
    const ids = (el.getAttribute('aria-labelledby') || '').trim().split(/\s+/);
    return ids.map((id) => document.getElementById(id))
      .filter((n) => n && !n.querySelector(questionControls + ',' + questionGroups))
      .map(visibleLabelText).filter(Boolean).join(' ');
  };
  const headingBefore = (el) => {
    const nodes = [];
    const parent = el.parentElement;
    const shared = parent === modal || parent.querySelectorAll(questionGroups).length > 1;
    for (let n = el.previousElementSibling; n; n = n.previousElementSibling) {
      if (n === modal.querySelector('h1,h2,h3')
          || (shared && /^H[1-6]$/.test(n.tagName))) break;
      if (n.matches(questionControls + ',' + questionGroups)
          || n.querySelector(questionControls + ',' + questionGroups)) break;
      nodes.unshift(n);
    }
    // A field wrapper's first preceding text is its question; subsequent text
    // may be voluntary/instructional copy. Do not search for a '*'.
    return nodes.map(visibleLabelText).find(Boolean) || '';
  };
  const groupQuestionFromOptions = (el) => {
    const group = el.closest(questionGroups);
    if (group && !group.querySelector(questionGroups)) {
      const legend = Array.from(group.querySelectorAll('legend'))
        .find((n) => n.closest(questionGroups) === group);
      const own = visibleLabelText(legend) || referencedLabel(group);
      if (own) return own;
      for (const child of group.children) {
        if (child.matches(questionControls + ',' + questionGroups)
            || child.querySelector(questionControls + ',' + questionGroups)) break;
        const heading = visibleLabelText(child);
        if (heading) return heading;
      }
      const before = headingBefore(group);
      if (before) return before;
    }
    // Hashed SDUI option lists can have no semantic group at all. Stop at the
    // smallest box containing multiple options, then read only preceding text.
    let box = el.parentElement;
    for (let hops = 0; box && box !== modal && hops < 8; hops++, box = box.parentElement) {
      if (box.querySelectorAll(questionControls).length < 2) continue;
      if (box.querySelector(questionGroups)) break;
      return headingBefore(box);
    }
    return '';
  };
  const questionLabel = (el, isChoice) => {
    if (isChoice) {
      const groupText = groupQuestionFromOptions(el);
      if (groupText) return groupText;
      // A lone checkbox's own visible label is itself the question. In an
      // unlabelled group it is merely an option, whose '*' cannot require it.
      const type = el.getAttribute('type') || el.getAttribute('role');
      const name = el.getAttribute('name');
      const peers = name && Array.from(modal.querySelectorAll(questionControls))
        .some((n) => n !== el && n.getAttribute('name') === name);
      if (el.closest(questionGroups) || type === 'radio' || peers) return '';
    }
    const labels = Array.from(el.labels || []);
    const wrap = el.closest('label');
    if (wrap && !labels.includes(wrap)) labels.push(wrap);
    const text = labels.map(visibleLabelText).filter(Boolean).join(' ');
    if (text) return text;
    const by = referencedLabel(el);
    if (by) return by;
    // A local SDUI question wrapper may use a <p> instead of a label. Helper
    // text/counters after the control are not its heading; keep climbing to
    // find the preceding question. Never enter another question's container.
    let box = el.parentElement;
    while (box && box !== modal && box.querySelectorAll(questionControls).length === 1) {
      const label = Array.from(box.querySelectorAll(
        'label,legend,p,.fb-form-element-label,.fb-dash-form-element__label,'
        + '.artdeco-text-input--label'
      ))
        .find((n) => !n.querySelector(questionControls)
          && (n.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)
          && visibleLabelText(n));
      if (label) return visibleLabelText(label);
      box = box.parentElement;
    }
    return '';
  };"""
