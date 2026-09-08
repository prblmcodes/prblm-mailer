// Turn every <input.prblm-mailer-color-input> into a colour picker: inject a swatch
// beside it and keep the two in sync. The text input stays the real value, so it
// can be cleared for "no colour". A MutationObserver catches blocks added to the
// StreamField editor after load.
(function () {
  var HEX = /^#[0-9a-fA-F]{6}$/;

  function enhance(input) {
    if (input.dataset.colorEnhanced) return;
    input.dataset.colorEnhanced = "1";
    var swatch = document.createElement("input");
    swatch.type = "color";
    swatch.tabIndex = -1;
    swatch.value = HEX.test((input.value || "").trim()) ? input.value.trim() : "#ffffff";
    swatch.style.cssText =
      "width:2.4rem;height:2.2rem;padding:0;flex:0 0 auto;border:1px solid #ccc;" +
      "border-radius:4px;cursor:pointer;background:none";
    // Wrap swatch + input in a full-width flex row: swatch fixed on the LEFT,
    // the text field flexes to fill the rest of the cell.
    var wrap = document.createElement("span");
    wrap.style.cssText = "display:flex;align-items:center;gap:.4rem;width:100%";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(swatch);
    wrap.appendChild(input);
    input.style.flex = "1 1 auto";
    input.style.width = "auto";
    input.style.minWidth = "0";
    swatch.addEventListener("input", function () {
      input.value = swatch.value;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    input.addEventListener("input", function () {
      var v = (input.value || "").trim();
      if (HEX.test(v)) swatch.value = v;
    });
  }

  function scan(root) {
    if (root.querySelectorAll) {
      root.querySelectorAll("input.prblm-mailer-color-input").forEach(enhance);
    }
  }

  document.addEventListener("DOMContentLoaded", function () { scan(document); });
  new MutationObserver(function (mutations) {
    mutations.forEach(function (m) {
      m.addedNodes.forEach(function (n) {
        if (n.nodeType !== 1) return;
        if (n.matches && n.matches("input.prblm-mailer-color-input")) enhance(n);
        scan(n);
      });
    });
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
