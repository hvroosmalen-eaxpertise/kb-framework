(function() {
  'use strict';

  var CDNS = [
    'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js',
    'https://unpkg.com/mermaid@11/dist/mermaid.min.js',
  ];

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

  function renderSelf(pre, bar, source, cdnIndex) {
    cdnIndex = cdnIndex || 0;
    if (cdnIndex >= CDNS.length) return;

    var s = document.createElement('script');
    s.src = CDNS[cdnIndex];
    s.onload = function() {
      try {
        mermaid.initialize({ startOnLoad: false });
        mermaid.render('mmd-' + Date.now(), source).then(function(r) {
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
    };
    s.onerror = function() { renderSelf(pre, bar, source, cdnIndex + 1); };
    document.head.appendChild(s);
  }

  // Remove the mermaid class so the Material theme's auto-loader
  // does NOT process these elements (which would create a duplicate).
  // We will render them ourselves below.
  document.querySelectorAll('pre.mermaid').forEach(function(pre) {
    pre.classList.remove('mermaid');
  });

  document.querySelectorAll('pre').forEach(function(pre) {
    var code = pre.querySelector('code');
    if (!code || !/^\s*graph\s+(TD|LR|BT|RL)/.test(code.textContent)) return;
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

    // Render after a short delay so the page layout is settled
    setTimeout(function() { renderSelf(pre, bar, source); }, 100);
  });
})();
