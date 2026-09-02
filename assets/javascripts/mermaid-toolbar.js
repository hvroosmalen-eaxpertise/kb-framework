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

  function addToolbarToRenderedDiagram(svgEl, source) {
    var wrapper = svgEl.parentElement;
    if (!wrapper || wrapper.classList.contains('mermaid-toolbar-added')) return;

    var bar = document.createElement('div');
    bar.className = 'mermaid-toolbar';

    var copyBtn = document.createElement('a');
    copyBtn.href = '#';
    copyBtn.textContent = 'Copy source';
    copyBtn.style.cssText = 'font-size:0.8em;margin-right:14px;';
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
      link.style.cssText = 'font-size:0.8em;' + (idx === 0 ? 'margin-right:14px;' : '') + 'color:#888;cursor:pointer;';
      bar.appendChild(link);
    });

    wrapper.parentNode.insertBefore(bar, wrapper);
    wrapper.classList.add('mermaid-toolbar-added');
    enableDownloads(bar, svgEl);
  }

  // Wait for theme's mermaid to render, then add toolbar
  function waitForRender(pre, source, attempts) {
    attempts = attempts || 0;
    // Look for rendered SVG sibling
    var svgEl = pre.nextElementSibling;
    while (svgEl && !svgEl.tagName.match(/svg/i)) {
      svgEl = svgEl.nextElementSibling;
    }
    if (svgEl && svgEl.tagName && svgEl.tagName.match(/svg/i)) {
      addToolbarToRenderedDiagram(svgEl, source);
      return;
    }
    // Also check if pre was replaced
    var prevSvg = pre.previousElementSibling;
    while (prevSvg && !prevSvg.tagName.match(/svg/i)) {
      prevSvg = prevSvg.previousElementSibling;
    }
    if (prevSvg && prevSvg.tagName && prevSvg.tagName.match(/svg/i)) {
      addToolbarToRenderedDiagram(prevSvg, source);
      return;
    }
    if (attempts > 100) {
      // Fallback: if mermaid didn't render, try to render ourselves
      if (window.mermaid && pre.classList.contains('mermaid')) {
        try {
          window.mermaid.initialize({ startOnLoad: false });
          window.mermaid.render('mmd-' + Date.now(), source).then(function(r) {
            var wrapper = document.createElement('div');
            wrapper.innerHTML = r.svg;
            var svgEl2 = wrapper.firstElementChild;
            pre.parentNode.replaceChild(wrapper, pre);
            addToolbarToRenderedDiagram(svgEl2, source);
          });
        } catch (err) {
          console.warn('mermaid-toolbar: fallback render error', err);
        }
      }
      return;
    }
    setTimeout(function() { waitForRender(pre, source, attempts + 1); }, 100);
  }

  document.querySelectorAll('pre.mermaid').forEach(function(pre) {
    var code = pre.querySelector('code');
    if (!code || !/^\s*(graph|flowchart)\s+(TD|LR|BT|RL|TB)/.test(code.textContent)) return;
    var source = code.textContent;
    waitForRender(pre, source);
  });
})();