/**
 * Wrpper Pixel v3 — Universal Attribution Pixel
 *
 * Drops a first-party cookie (_wrp) on the advertiser's domain.
 * Tracks pageviews, sessions, conversions, and refunds.
 * Cookie persists 30 days — survives tab close, return visits, etc.
 *
 * Usage:
 *   <script src="https://api.wrpper.com/static/wrp.js"
 *           data-key="wrp_pub_YOUR_PUBLISHABLE_KEY"
 *           data-org="YOUR_ORG_ID"></script>
 *
 * Auto-fires: session + pageview on every page load where a click ID exists.
 *
 * Manual events:
 *   wrp("conversion", { order_id: "ORD-123", revenue_cents: 4999, currency: "USD" });
 *   wrp("refund", { original_order_id: "ORD-123", refund_amount_cents: 4999 });
 *   wrp("pageview");  // manual pageview (auto-fires on load already)
 *
 * The publishable key (wrp_pub_...) is safe to expose client-side.
 * It can ONLY write events — it cannot read any data.
 */
(function () {
  "use strict";

  // --- Config from script tag ---
  var script = document.currentScript;
  if (!script) return;

  var API_KEY = script.getAttribute("data-key") || "";
  var ORG_ID = script.getAttribute("data-org") || "";
  var ENDPOINT = script.getAttribute("data-endpoint") || "https://api.wrpper.com";

  // The URL param name your redirect injects (from redirect.py → resolve_destination)
  var CLICK_PARAM = "inf_click_id";

  // Cookie config
  var COOKIE_NAME = "_wrp";
  var COOKIE_DAYS = 30;

  if (!API_KEY) {
    console.warn("[Wrpper] Missing data-key. Pixel inactive.");
    return;
  }
  if (!ORG_ID) {
    console.warn("[Wrpper] Missing data-org. Pixel inactive.");
    return;
  }

  // =========================================================================
  //  Cookie helpers — first-party cookie on the advertiser's domain
  // =========================================================================

  function setCookie(name, value, days) {
    var d = new Date();
    d.setTime(d.getTime() + days * 86400000);
    var parts = [
      name + "=" + encodeURIComponent(value),
      "expires=" + d.toUTCString(),
      "path=/",
      "SameSite=Lax",
    ];
    // Set Secure flag if on HTTPS
    if (location.protocol === "https:") {
      parts.push("Secure");
    }
    document.cookie = parts.join("; ");
  }

  function getCookie(name) {
    var match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : null;
  }

  // =========================================================================
  //  Click ID resolution — URL param → cookie (persists across sessions)
  // =========================================================================

  function getParam(name) {
    try {
      return new URLSearchParams(window.location.search).get(name);
    } catch (e) {
      return null;
    }
  }

  // Check URL first (fresh click), then fall back to cookie (return visit)
  var clickIdFromUrl = getParam(CLICK_PARAM);
  var clickIdFromCookie = getCookie(COOKIE_NAME);

  if (clickIdFromUrl) {
    // Fresh click — set/refresh the cookie
    setCookie(COOKIE_NAME, clickIdFromUrl, COOKIE_DAYS);
  }

  // The active click ID: URL param wins, then cookie
  var CLICK_ID = clickIdFromUrl || clickIdFromCookie || null;

  // =========================================================================
  //  Event sender
  // =========================================================================

  function sendEvent(path, data) {
    if (!CLICK_ID) return; // No attribution context — skip silently

    var payload = {};
    payload.inf_click_id = CLICK_ID;
    payload.organization_id = ORG_ID;

    // Merge caller data
    if (data) {
      for (var k in data) {
        if (data.hasOwnProperty(k)) payload[k] = data[k];
      }
    }

    var url = ENDPOINT + path;

    // Primary: fetch with keepalive (survives page unload)
    try {
      fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": API_KEY,
        },
        body: JSON.stringify(payload),
        keepalive: true,
      }).catch(function () {});
    } catch (e) {
      // Fallback: sendBeacon (no custom headers — key in query param)
      try {
        if (navigator.sendBeacon) {
          navigator.sendBeacon(
            url + "?key=" + encodeURIComponent(API_KEY),
            new Blob([JSON.stringify(payload)], { type: "application/json" })
          );
        }
      } catch (e2) {}
    }
  }

  // =========================================================================
  //  Auto-fire: session + pageview on load (if click ID exists)
  // =========================================================================

  if (CLICK_ID) {
    sendEvent("/v1/events/session", {
      page_url: window.location.href,
      referrer: document.referrer || null,
      source: clickIdFromUrl ? "url_param" : "cookie",
    });

    sendEvent("/v1/events/pageview", {
      page_url: window.location.href,
    });
  }

  // =========================================================================
  //  Pixel heartbeat — tells you which advertiser sites have the pixel live
  // =========================================================================

  try {
    var img = new Image();
    img.src =
      ENDPOINT +
      "/v1/pixel/heartbeat?org=" +
      encodeURIComponent(ORG_ID) +
      "&key=" +
      encodeURIComponent(API_KEY) +
      "&url=" +
      encodeURIComponent(window.location.hostname) +
      "&has_click=" +
      (CLICK_ID ? "1" : "0") +
      "&t=" +
      Date.now();
  } catch (e) {}

  // =========================================================================
  //  Public API — window.wrp()
  // =========================================================================

  window.wrp = function (action, data) {
    data = data || {};

    switch (action) {
      case "conversion":
        sendEvent("/v1/events/conversion", data);
        break;

      case "pageview":
        sendEvent("/v1/events/pageview", {
          page_url: window.location.href,
          time_on_page_ms: data.time_on_page_ms || null,
        });
        break;

      case "refund":
        sendEvent("/v1/events/refund", data);
        break;

      case "identify":
        // Optional: let advertiser attach their own customer ID to the click
        sendEvent("/v1/events/identify", {
          external_customer_id: data.customer_id || null,
          email_hash: data.email_hash || null,
        });
        break;

      default:
        // Custom event passthrough
        sendEvent("/v1/events/custom", {
          event_name: action,
          metadata: data,
          page_url: window.location.href,
        });
    }
  };

  // =========================================================================
  //  Convenience: auto-track time on page (fires on unload)
  // =========================================================================

  if (CLICK_ID) {
    var _wrpPageStart = Date.now();

    function _wrpUnload() {
      var timeMs = Date.now() - _wrpPageStart;
      if (timeMs > 1000) {
        // Only track if they stayed more than 1 second
        sendEvent("/v1/events/pageview", {
          page_url: window.location.href,
          time_on_page_ms: timeMs,
          event_subtype: "unload",
        });
      }
    }

    // visibilitychange is more reliable than beforeunload on mobile
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden") _wrpUnload();
    });

    // Fallback for desktop
    window.addEventListener("pagehide", _wrpUnload);
  }
})();
