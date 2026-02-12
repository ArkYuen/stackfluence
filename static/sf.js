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

  if (!API_KEY) {
    console.warn("[Stackfluence] Missing data-key attribute. Events will not be sent.");
    return;
  }

  function getParam(name) {
    var params = new URLSearchParams(window.location.search);
    return params.get(name);
  }

  function getClickId() {
    var fromUrl = getParam(CLICK_ID_PARAM);
    if (fromUrl) {
      try {
        sessionStorage.setItem(STORAGE_KEY, fromUrl);
      } catch (e) {}
      return fromUrl;
    }
    try {
      return sessionStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
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
