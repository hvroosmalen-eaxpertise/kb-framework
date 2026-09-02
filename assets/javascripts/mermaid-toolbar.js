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

  function renderWithMermaid(mermaidLib, pre, bar, source) {
    try {
      mermaidLib.initialize({ startOnLoad: false });
      mermaidLib.render('mmd-' + Date.now(), source).then(function(r) {
        var wrapper = document.createElement('div');
        wrapper.innerHTML = r.svg;
        var svgEl = wrapper.firstElementChild;
        if (pre.parentNode) {
          pre.parentNode.replaceChild(wrapper, pre);
        } else {
          bar.parentNode.insertBefore(wrapper, bar);
        }
        enableDownloads(bar, svgEl);
      });
    } catch (err) {
      console.warn('mermaid-toolbar: render error', err);
    }
  }

  // Wait for mermaid to be available (from theme bundle)
  function waitForMermaid(pre, bar, source, attempts) {
    attempts = attempts || 0;
    if (window.mermaid) {
      renderWithMermaid(window.mermaid, pre, bar, source);
      return;
    }
    if (attempts > 50) {
      console.warn('mermaid-toolbar: mermaid not available after 5s');
      return;
    }
    setTimeout(function() { waitForMermaid(pre, bar, source, attempts + 1); }, 100);
  }

  // Remove the mermaid class so the Material theme's auto-loader
  // does NOT process these elements (which would create a duplicate).
  // We will render them ourselves below using the theme's mermaid.
  document.querySelectorAll('pre.mermaid').forEach(function(pre) {
    pre.classList.remove('mermaid');
  });

  document.querySelectorAll('pre').forEach(function(pre) {
    var code = pre.querySelector('code');
    if (!code || !/^\s*(graph|flowchart)\s+(TD|LR|BT|RL|TB)/.test(code.textContent)) return;
    var source = code.textContent;

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
      link.style.cssText = 'font-size:0.8em;' + (idx === 0 ? 'margin-right:14px;' : '') + 'color:#888;cursor:default;';
      bar.appendChild(link);
    });

    pre.parentNode.insertBefore(bar, pre.nextSibling);

    // Wait for mermaid to be available from theme bundle, then render
    waitForMermaid(pre, bar, source);
  });
})();