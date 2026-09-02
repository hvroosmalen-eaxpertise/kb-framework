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
    var svgEl = wrapper.querySelector('svg');
    if (svgEl) enableDownloads(bar, svgEl);
  }

  function findAndAddToolbar(pre, source) {
    // Case 1: pre was replaced by a div with mermaid class containing svg
    var wrapper = pre.parentNode;
    while (wrapper && wrapper !== document.body) {
      if (wrapper.classList && wrapper.classList.contains('mermaid') && wrapper.querySelector('svg')) {
        addToolbar(wrapper, source);
        return true;
      }
      wrapper = wrapper.parentNode;
    }

    // Case 2: pre has a next sibling that is the rendered mermaid div
    var next = pre.nextElementSibling;
    while (next) {
      if (next.classList && next.classList.contains('mermaid') && next.querySelector('svg')) {
        addToolbar(next, source);
        return true;
      }
      if (next.tagName && next.tagName.match(/svg/i)) {
        // SVG directly
        var parentDiv = document.createElement('div');
        parentDiv.className = 'mermaid';
        next.parentNode.insertBefore(parentDiv, next);
        parentDiv.appendChild(next);
        addToolbar(parentDiv, source);
        return true;
      }
      next = next.nextElementSibling;
    }

    // Case 3: pre was replaced entirely - look for mermaid div with our content
    var allMermaids = document.querySelectorAll('.mermaid svg');
    for (var i = 0; i < allMermaids.length; i++) {
      var svg = allMermaids[i];
      var mw = svg.parentElement;
      while (mw && !mw.classList.contains('mermaid')) mw = mw.parentElement;
      if (mw && !mw.classList.contains('mermaid-toolbar-added')) {
        // Check if this mermaid is near where our pre was
        addToolbar(mw, source);
        return true;
      }
    }
    return false;
  }

  function waitAndAdd(pre, source, attempts) {
    attempts = attempts || 0;
    if (findAndAddToolbar(pre, source)) return;

    if (attempts > 150) {
      // Fallback: render ourselves if theme didn't
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
          console.warn('mermaid-toolbar: fallback render error', err);
        }
      }
      return;
    }
    setTimeout(function() { waitAndAdd(pre, source, attempts + 1); }, 100);
  }

  document.querySelectorAll('pre.mermaid').forEach(function(pre) {
    var code = pre.querySelector('code');
    if (!code || !/^\s*(graph|flowchart)\s+(TD|LR|BT|RL|TB)/.test(code.textContent)) return;
    var source = code.textContent;
    waitAndAdd(pre, source);
  });
})();