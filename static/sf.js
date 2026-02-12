/**
 * Stackfluence Advertiser Snippet v2
 *
 * Usage:
 *   <script src="https://cdn.stackfluence.com/sf.js"
 *           data-key="sf_pub_YOUR_PUBLISHABLE_KEY"
 *           data-org="YOUR_ORG_ID"
 *           data-endpoint="https://api.stackfluence.com"></script>
 *
 * The publishable key (sf_pub_...) is safe to expose client-side.
 * It can ONLY write events — it cannot read any data.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var API_KEY = script?.getAttribute("data-key") || "";
  var ORG_ID = script?.getAttribute("data-org") || "";
  var ENDPOINT =
    script?.getAttribute("data-endpoint") || "https://api.stackfluence.com";
  var CLICK_ID_PARAM = "inf_click_id";
  var STORAGE_KEY = "sf_click_id";
  var IS_SHOPIFY = typeof window.Shopify !== "undefined";

  if (!API_KEY) {
    console.warn("[Stackfluence] Missing data-key attribute. Events will not be sent.");
    return;
  }

  // Shopify: use localStorage (survives cross-domain checkout redirect)
  // Non-Shopify: use sessionStorage (scoped to tab, no cross-site leakage)
  var storage = (function () {
    var store = IS_SHOPIFY ? window.localStorage : window.sessionStorage;
    return {
      get: function (key) {
        try { return store.getItem(key); } catch (e) { return null; }
      },
      set: function (key, val) {
        try { store.setItem(key, val); } catch (e) {}
      },
    };
  })();

  function getParam(name) {
    var params = new URLSearchParams(window.location.search);
    return params.get(name);
  }

  function getClickId() {
    var fromUrl = getParam(CLICK_ID_PARAM);
    if (fromUrl) {
      storage.set(STORAGE_KEY, fromUrl);
      return fromUrl;
    }
    return storage.get(STORAGE_KEY);
  }

  // Shopify: inject click_id into cart attributes so it survives checkout
  function injectCartAttribute(clickId) {
    if (!IS_SHOPIFY || !clickId) return;
    try {
      fetch("/cart/update.js", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          attributes: { inf_click_id: clickId },
        }),
      }).catch(function () {});
    } catch (e) {}
  }

  function sendEvent(path, data) {
    var clickId = getClickId();
    if (!clickId || !ORG_ID || !API_KEY) return;

    var payload = Object.assign(
      { inf_click_id: clickId, organization_id: ORG_ID },
      data
    );

    // Use fetch with API key header
    try {
      fetch(ENDPOINT + path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": API_KEY,
        },
        body: JSON.stringify(payload),
        keepalive: true, // survives page unload like sendBeacon
      }).catch(function () {});
    } catch (e) {
      // Fallback: sendBeacon (no custom headers, but key in query param)
      if (navigator.sendBeacon) {
        var url = ENDPOINT + path + "?key=" + encodeURIComponent(API_KEY);
        navigator.sendBeacon(
          url,
          new Blob([JSON.stringify(payload)], { type: "application/json" })
        );
      }
    }
  }

  // Auto-fire on page load if click_id present
  var clickId = getClickId();
  if (clickId) {
    // Shopify: inject click_id into cart attributes for checkout survival
    injectCartAttribute(clickId);

    sendEvent("/v1/events/session", {
      page_url: window.location.href,
      referrer: document.referrer || null,
    });
    sendEvent("/v1/events/pageview", {
      page_url: window.location.href,
    });
  }

  // Public API
  window.sfq = function (action, data) {
    if (action === "conversion") {
      sendEvent("/v1/events/conversion", data || {});
    } else if (action === "pageview") {
      sendEvent("/v1/events/pageview", {
        page_url: window.location.href,
        time_on_page_ms: data?.time_on_page_ms || null,
      });
    } else if (action === "refund") {
      sendEvent("/v1/events/refund", data || {});
    }
  };
})();
