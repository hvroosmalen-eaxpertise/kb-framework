(function() {
  'use strict';

  function svgUrl(svg) {
    var str = new XMLSerializer().serializeToString(svg.cloneNode(true));
    var blob = new Blob([str], {type: 'image/svg+xml'});
    return URL.createObjectURL(blob);
  }

  function enableDownloads(bar, svg) {
    [['svg', 'Download SVG'], ['open', 'Open SVG']].forEach(function(pair, idx) {
      var link = bar.querySelector('[data-action=' + pair[0] + ']');
      if (!link) return;
      link.style.cssText = 'font-size:0.8em;' + (idx === 0 ? 'margin-right:14px;' : '') + 'color:inherit;cursor:pointer;';
      link.onclick = function(e) {
        e.preventDefault();
        var url = svgUrl(svg);
        if (pair[0] === 'open') {
          window.open(url, '_blank');
        } else {
          var a = document.createElement('a');
          a.href = url;
          a.download = 'concept-map.svg';
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
        }
      };
    });
  }

  function addToolbar(wrapper, source) {
    if (wrapper.classList.contains('mermaid-toolbar-added')) return;
    console.log('[mermaid-toolbar] Adding toolbar to', wrapper);

    var bar = document.createElement('div');
    bar.className = 'mermaid-toolbar';
    bar.style.cssText = 'margin-bottom: 8px;';

    var copyBtn = document.createElement('a');
    copyBtn.href = '#';
    copyBtn.textContent = 'Copy source';
    copyBtn.style.cssText = 'font-size:0.8em;margin-right:14px;color:var(--md-primary-fg-color);cursor:pointer;text-decoration:underline;';
    copyBtn.onclick = function(e) {
      e.preventDefault();
      navigator.clipboard.writeText(source).then(function() {
        copyBtn.textContent = 'Copied!';
        setTimeout(function() { copyBtn.textContent = 'Copy source'; }, 2000);
      });
    };
    bar.appendChild(copyBtn);

    [['svg', 'Download SVG'], ['open', 'Open SVG']].forEach(function(pair, idx) {
      var link = document.createElement('a');
      link.href = '#';
      link.textContent = pair[1];
      link.setAttribute('data-action', pair[0]);
      link.style.cssText = 'font-size:0.8em;' + (idx === 0 ? 'margin-right:14px;' : '') + 'color:var(--md-primary-fg-color);cursor:pointer;text-decoration:underline;';
      link.onclick = function(e) {
        e.preventDefault();
        var url = svgUrl(svg);
        if (pair[0] === 'open') {
          window.open(url, '_blank');
        } else {
          var a = document.createElement('a');
          a.href = url;
          a.download = 'concept-map.svg';
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
        }
      };
      bar.appendChild(link);
    });

    wrapper.parentNode.insertBefore(bar, wrapper);
    wrapper.classList.add('mermaid-toolbar-added');
    var svgEl = wrapper.querySelector('svg');
    if (svgEl) enableDownloads(bar, svgEl);
  }

  function findWrapper(pre) {
    // 1. Check if pre.parentNode is the mermaid wrapper
    var p = pre.parentNode;
    if (p && p.classList && p.classList.contains('mermaid') && p.querySelector('svg')) {
      console.log('[mermaid-toolbar] Found wrapper: pre.parentNode');
      return p;
    }

    // 2. Check next siblings
    var next = pre.nextElementSibling;
    while (next) {
      if (next.classList && next.classList.contains('mermaid') && next.querySelector('svg')) {
        console.log('[mermaid-toolbar] Found wrapper: nextElementSibling');
        return next;
      }
      if (next.tagName && next.tagName.match(/svg/i)) {
        // Wrap the SVG
        console.log('[mermaid-toolbar] Found SVG, wrapping');
        var div = document.createElement('div');
        div.className = 'mermaid';
        next.parentNode.insertBefore(div, next);
        div.appendChild(next);
        return div;
      }
      next = next.nextElementSibling;
    }

    // 3. Check previous siblings
    var prev = pre.previousElementSibling;
    while (prev) {
      if (prev.classList && prev.classList.contains('mermaid') && prev.querySelector('svg')) {
        console.log('[mermaid-toolbar] Found wrapper: previousElementSibling');
        return prev;
      }
      prev = prev.previousElementSibling;
    }

    // 4. Look for mermaid div containing our pre's content
    var allMermaids = document.querySelectorAll('.mermaid');
    for (var i = 0; i < allMermaids.length; i++) {
      var m = allMermaids[i];
      if (m.querySelector('svg') && !m.classList.contains('mermaid-toolbar-added')) {
        // Check if this mermaid is near our pre
        var dist = Math.abs(m.getBoundingClientRect().top - pre.getBoundingClientRect().top);
        if (dist < 500) { // within 500px vertically
          console.log('[mermaid-toolbar] Found wrapper: nearby mermaid div');
          return m;
        }
      }
    }

    return null;
  }

  function waitAndAdd(pre, source, attempts) {
    attempts = attempts || 0;
    var wrapper = findWrapper(pre);
    if (wrapper) {
      addToolbar(wrapper, source);
      return;
    }
    if (attempts > 200) { // 20 seconds
      console.log('[mermaid-toolbar] Timeout waiting for render, attempting fallback');
      if (window.mermaid && pre.classList.contains('mermaid')) {
        try {
          window.mermaid.initialize({ startOnLoad: false });
          window.mermaid.render('mmd-' + Date.now(), source).then(function(r) {
            var wrapper = document.createElement('div');
            wrapper.className = 'mermaid';
            wrapper.innerHTML = r.svg;
            pre.parentNode.replaceChild(wrapper, pre);
            addToolbar(wrapper, source);
          });
        } catch (err) {
          console.warn('[mermaid-toolbar] Fallback render error', err);
        }
      }
      return;
    }
    setTimeout(function() { waitAndAdd(pre, source, attempts + 1); }, 100);
  }

  function init() {
    console.log('[mermaid-toolbar] Init, found', document.querySelectorAll('pre.mermaid').length, 'mermaid blocks');
    document.querySelectorAll('pre.mermaid').forEach(function(pre) {
      var code = pre.querySelector('code');
      if (!code || !/^\s*(graph|flowchart)\s+(TD|LR|BT|RL|TB)/.test(code.textContent)) return;
      var source = code.textContent;
      waitAndAdd(pre, source);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();