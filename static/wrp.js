/**
 * Wrpper Pixel v5 — Universal Attribution Pixel
 *
 * CAPTURE EVERYTHING. CLASSIFY LATER.
 *
 * One tag install. Works on any site — ecommerce, restaurants, salons,
 * dealerships, doctors, lead gen, brand sites. No code changes needed.
 *
 * Six collection layers:
 *   1. Passive page context (every load)
 *   2. DOM observation (forms, phone links, CTAs, chat widgets)
 *   3. User behavior (scroll, clicks, engagement time)
 *   4. dataLayer interception (GA4, Shopify, WooCommerce)
 *   5. Third-party tool detection (site classification)
 *   6. URL-based page classification
 *
 * Install:
 *   <script src="https://api.wrpper.com/static/wrp.js"
 *           data-key="wrp_pub_YOUR_KEY"
 *           data-org="YOUR_ORG_ID"></script>
 */
(function () {
  "use strict";

  var script = document.currentScript;
  if (!script) return;

  var API_KEY = script.getAttribute("data-key") || "";
  var ORG_ID = script.getAttribute("data-org") || "";
  var ENDPOINT = script.getAttribute("data-endpoint") || "https://api.wrpper.com";
  var CLICK_PARAM = "inf_click_id";
  var COOKIE_NAME = "_wrp";
  var COOKIE_DAYS = 365;
  var SESSION_KEY = "_wrp_sess";
  var VISIT_KEY = "_wrp_visits";
  var FIRST_VISIT_KEY = "_wrp_first";
  var PAGE_COUNT_KEY = "_wrp_pgcnt";

  if (!API_KEY) { console.warn("[Wrpper] Missing data-key."); return; }
  if (!ORG_ID) { console.warn("[Wrpper] Missing data-org."); return; }

  // =========================================================================
  //  UTILITIES
  // =========================================================================

  function setCookie(name, value, days) {
    var d = new Date();
    d.setTime(d.getTime() + days * 86400000);
    var parts = [name + "=" + encodeURIComponent(value), "expires=" + d.toUTCString(), "path=/", "SameSite=Lax"];
    if (location.protocol === "https:") parts.push("Secure");
    document.cookie = parts.join("; ");
  }

  function getCookie(name) {
    var match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : null;
  }

  function getParam(name) {
    try { return new URLSearchParams(window.location.search).get(name); }
    catch (e) { return null; }
  }

  function getMeta(name) {
    var el = document.querySelector('meta[property="' + name + '"]') ||
             document.querySelector('meta[name="' + name + '"]');
    return el ? el.getAttribute("content") : null;
  }

  function truncate(str, len) {
    if (!str) return null;
    return str.length > len ? str.substring(0, len) : str;
  }

  function generateId() {
    return "wrps_" + Math.random().toString(36).substring(2, 15) + Date.now().toString(36);
  }

  // =========================================================================
  //  CLICK ID + SESSION + VISIT TRACKING
  // =========================================================================

  var clickIdFromUrl = getParam(CLICK_PARAM);
  var clickIdFromCookie = getCookie(COOKIE_NAME);
  if (clickIdFromUrl) setCookie(COOKIE_NAME, clickIdFromUrl, COOKIE_DAYS);
  var CLICK_ID = clickIdFromUrl || clickIdFromCookie || null;

  // Session management (30 min timeout)
  var SESSION_ID = getCookie(SESSION_KEY);
  if (!SESSION_ID) {
    SESSION_ID = generateId();
  }
  setCookie(SESSION_KEY, SESSION_ID, 0.02); // ~30 min

  // Visit counting
  var visitNumber = parseInt(getCookie(VISIT_KEY) || "0", 10);
  if (!getCookie(SESSION_KEY + "_active")) {
    visitNumber++;
    setCookie(VISIT_KEY, String(visitNumber), COOKIE_DAYS);
    setCookie(SESSION_KEY + "_active", "1", 0.02);
  }

  // First visit timestamp
  var firstVisit = getCookie(FIRST_VISIT_KEY);
  if (!firstVisit) {
    firstVisit = new Date().toISOString();
    setCookie(FIRST_VISIT_KEY, firstVisit, COOKIE_DAYS);
  }
  var daysSinceFirst = Math.floor((Date.now() - new Date(firstVisit).getTime()) / 86400000);

  // Page count this session
  var pagesThisSession = parseInt(getCookie(PAGE_COUNT_KEY) || "0", 10) + 1;
  setCookie(PAGE_COUNT_KEY, String(pagesThisSession), 0.02);

  // =========================================================================
  //  EVENT SENDER
  // =========================================================================

  var _sent = {};
  var _eventQueue = [];
  var _flushTimer = null;

  function _buildBase() {
    return {
      click_id: CLICK_ID,
      org_id: ORG_ID,
      session_id: SESSION_ID,
      timestamp: new Date().toISOString(),
      page: {
        url: window.location.href,
        path: window.location.pathname,
        title: truncate(document.title, 200),
        referrer: document.referrer || null,
        canonical: getMeta("canonical") || null,
        og_type: getMeta("og:type") || null,
        og_title: truncate(getMeta("og:title"), 200) || null,
        description: truncate(getMeta("description") || getMeta("og:description"), 300) || null,
      },
      visitor: {
        visit_number: visitNumber,
        pages_this_session: pagesThisSession,
        days_since_first_visit: daysSinceFirst,
        has_click_attribution: !!CLICK_ID,
        click_source: clickIdFromUrl ? "url_param" : (clickIdFromCookie ? "cookie" : "none"),
      },
    };
  }

  function sendEvent(eventType, eventSource, eventData, dedupe) {
    // Deduplicate
    if (dedupe) {
      if (_sent[dedupe]) return;
      _sent[dedupe] = true;
    }

    var payload = _buildBase();
    payload.event_type = eventType;
    payload.event_source = eventSource;
    payload.event_data = eventData || {};

    var url = ENDPOINT + "/v1/events/universal";

    try {
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
        body: JSON.stringify(payload),
        keepalive: true,
      }).catch(function () {});
    } catch (e) {
      try {
        if (navigator.sendBeacon) {
          navigator.sendBeacon(url + "?key=" + encodeURIComponent(API_KEY),
            new Blob([JSON.stringify(payload)], { type: "application/json" }));
        }
      } catch (e2) {}
    }
  }

  // Also send to legacy endpoints for backward compat
  function sendLegacy(path, data) {
    if (!CLICK_ID) return;
    var payload = { inf_click_id: CLICK_ID, organization_id: ORG_ID };
    if (data) { for (var k in data) { if (data.hasOwnProperty(k)) payload[k] = data[k]; } }
    var url = ENDPOINT + path;
    try {
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
        body: JSON.stringify(payload),
        keepalive: true,
      }).catch(function () {});
    } catch (e) {}
  }

  // =========================================================================
  //  LAYER 1: PASSIVE PAGE CONTEXT (fires on every page load)
  // =========================================================================

  // URL-based page type classification
  function classifyPage(path) {
    path = (path || "").toLowerCase();
    var patterns = {
      "conversion_confirm": /\/(thank[-_]?you|thanks|confirmation|confirmed|success|complete|receipt|welcome)/,
      "booking_confirm": /\/(booking|appointment|reservation)[-_]?(confirmed|complete|success)/,
      "product": /\/(product|item|p)\//,
      "shop": /\/(shop|store|catalog|collection|category)/,
      "cart": /\/(cart|bag|basket)/,
      "checkout": /\/check[-_]?out/,
      "menu": /\/(menu|food|drinks|specials|dinner|lunch|brunch)/,
      "services": /\/(services|treatments|procedures|offerings)/,
      "pricing": /\/(pricing|prices|plans|packages|rates)/,
      "booking": /\/(book|schedule|appointment|reserve|reservation)/,
      "contact": /\/(contact|reach|connect|get[-_]?in[-_]?touch)/,
      "about": /\/(about|team|staff|our[-_]?story|who[-_]?we[-_]?are)/,
      "blog": /\/(blog|article|news|post|journal)/,
      "listings": /\/(listings|properties|inventory|vehicles|cars|homes)/,
      "apply": /\/(apply|quote|estimate|request|inquiry|enquiry)/,
      "login": /\/(login|signin|sign[-_]?in|account|portal|dashboard)/,
      "download": /\/(download|get[-_]?started|free[-_]?trial)/,
      "gallery": /\/(gallery|photos|portfolio|work|projects|before[-_]?after)/,
      "reviews": /\/(reviews|testimonials|feedback)/,
      "faq": /\/(faq|help|support|questions)/,
      "location": /\/(location|directions|find[-_]?us|visit|hours)/,
    };
    for (var type in patterns) {
      if (patterns[type].test(path)) return type;
    }
    if (path === "/" || path === "") return "home";
    return "other";
  }

  var pageType = classifyPage(window.location.pathname);

  sendEvent("page_view", "passive", {
    page_type: pageType,
    screen_width: screen.width,
    screen_height: screen.height,
    viewport_width: window.innerWidth,
    viewport_height: window.innerHeight,
    device_pixel_ratio: window.devicePixelRatio || 1,
    touch_support: "ontouchstart" in window || navigator.maxTouchPoints > 0,
    connection_type: (navigator.connection && navigator.connection.effectiveType) || null,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || null,
    language: navigator.language || null,
    dark_mode: window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches,
    do_not_track: navigator.doNotTrack === "1" || navigator.globalPrivacyControl === true,
  }, "pv:" + window.location.href);

  // Legacy session + pageview
  if (CLICK_ID) {
    sendLegacy("/v1/events/session", {
      page_url: window.location.href,
      referrer: document.referrer || null,
      source: clickIdFromUrl ? "url_param" : "cookie",
    });
    sendLegacy("/v1/events/pageview", { page_url: window.location.href });
  }

  // Pixel heartbeat
  try {
    var img = new Image();
    img.src = ENDPOINT + "/v1/pixel/heartbeat?org=" + encodeURIComponent(ORG_ID) +
      "&key=" + encodeURIComponent(API_KEY) +
      "&url=" + encodeURIComponent(window.location.hostname) +
      "&has_click=" + (CLICK_ID ? "1" : "0") + "&t=" + Date.now();
  } catch (e) {}

  // Page performance (after load)
  window.addEventListener("load", function () {
    setTimeout(function () {
      try {
        var perf = performance.getEntriesByType("navigation")[0];
        if (perf) {
          sendEvent("page_performance", "passive", {
            dns_ms: Math.round(perf.domainLookupEnd - perf.domainLookupStart),
            tcp_ms: Math.round(perf.connectEnd - perf.connectStart),
            ttfb_ms: Math.round(perf.responseStart - perf.requestStart),
            dom_load_ms: Math.round(perf.domContentLoadedEventEnd - perf.fetchStart),
            full_load_ms: Math.round(perf.loadEventEnd - perf.fetchStart),
          }, "perf:" + window.location.href);
        }
      } catch (e) {}
    }, 1000);
  });

  // =========================================================================
  //  LAYER 2: DOM OBSERVATION
  // =========================================================================

  function initDomObservation() {

    // --- FORM TRACKING ---
    var forms = document.querySelectorAll("form");
    forms.forEach(function (form, idx) {
      var formId = form.id || form.getAttribute("name") || "form_" + idx;
      var action = form.getAttribute("action") || "";
      var method = (form.getAttribute("method") || "get").toUpperCase();

      // Collect field names (not values — privacy safe)
      var fieldNames = [];
      var fieldTypes = [];
      var inputs = form.querySelectorAll("input, select, textarea");
      inputs.forEach(function (input) {
        var name = input.getAttribute("name") || input.getAttribute("id") || "";
        var type = input.getAttribute("type") || input.tagName.toLowerCase();
        if (name && type !== "hidden" && type !== "submit" && type !== "button") {
          fieldNames.push(truncate(name, 50));
          fieldTypes.push(type);
        }
      });

      // Classify form type by field names
      var fieldStr = fieldNames.join(" ").toLowerCase();
      var formType = "unknown";
      if (/phone|tel|mobile/.test(fieldStr) && /name|first/.test(fieldStr)) formType = "contact";
      if (/email/.test(fieldStr) && fieldNames.length <= 2) formType = "newsletter";
      if (/date|time|appointment|schedule/.test(fieldStr)) formType = "booking";
      if (/company|budget|industry|revenue/.test(fieldStr)) formType = "lead_gen";
      if (/zip|coverage|vehicle|vin|model/.test(fieldStr)) formType = "quote_request";
      if (/address|city|state/.test(fieldStr) && /card|payment|cvv/.test(fieldStr)) formType = "checkout";
      if (/message|comment|inquiry|question/.test(fieldStr)) formType = "inquiry";
      if (/resume|cv|position|salary/.test(fieldStr)) formType = "application";
      if (/patient|insurance|dob|birth/.test(fieldStr)) formType = "intake";
      if (/review|rating|feedback|stars/.test(fieldStr)) formType = "feedback";

      // Track form interactions
      var formStarted = false;
      inputs.forEach(function (input) {
        input.addEventListener("focus", function () {
          if (!formStarted) {
            formStarted = true;
            sendEvent("form_start", "dom_observer", {
              form_id: formId,
              form_type: formType,
              field_count: fieldNames.length,
              field_names: fieldNames,
            }, "form_start:" + formId);
          }
        });
      });

      // Track form submission
      form.addEventListener("submit", function () {
        sendEvent("form_submit", "dom_observer", {
          form_id: formId,
          form_type: formType,
          form_action: truncate(action, 200),
          form_method: method,
          field_count: fieldNames.length,
          field_names: fieldNames,
          field_types: fieldTypes,
        }, "form_submit:" + formId);

        // Also send legacy conversion
        if (CLICK_ID) {
          sendLegacy("/v1/events/conversion", {
            event_type: "form_submit",
            metadata: { form_id: formId, form_type: formType, source: "dom_observer" },
            page_url: window.location.href,
          });
        }
      });
    });

    // --- PHONE CLICK TRACKING ---
    document.querySelectorAll('a[href^="tel:"]').forEach(function (link) {
      link.addEventListener("click", function () {
        var phone = link.getAttribute("href").replace("tel:", "").trim();
        sendEvent("phone_click", "dom_observer", {
          phone_number: phone,
          link_text: truncate(link.textContent.trim(), 100),
        });
        if (CLICK_ID) {
          sendLegacy("/v1/events/conversion", {
            event_type: "phone_click",
            metadata: { phone: phone, source: "dom_observer" },
            page_url: window.location.href,
          });
        }
      });
    });

    // --- EMAIL CLICK TRACKING ---
    document.querySelectorAll('a[href^="mailto:"]').forEach(function (link) {
      link.addEventListener("click", function () {
        var email = link.getAttribute("href").replace("mailto:", "").split("?")[0].trim();
        sendEvent("email_click", "dom_observer", {
          email_address: email,
          link_text: truncate(link.textContent.trim(), 100),
        });
      });
    });

    // --- DIRECTIONS / MAP CLICK TRACKING ---
    document.querySelectorAll('a[href*="maps.google"], a[href*="maps.apple"], a[href*="waze.com"], a[href*="directions"]').forEach(function (link) {
      link.addEventListener("click", function () {
        sendEvent("directions_click", "dom_observer", {
          map_url: truncate(link.getAttribute("href"), 300),
          link_text: truncate(link.textContent.trim(), 100),
        });
      });
    });

    // --- PDF / MENU / FILE DOWNLOAD TRACKING ---
    document.querySelectorAll('a[href$=".pdf"], a[href$=".PDF"], a[href*=".pdf?"]').forEach(function (link) {
      link.addEventListener("click", function () {
        sendEvent("file_download", "dom_observer", {
          file_url: truncate(link.getAttribute("href"), 300),
          file_type: "pdf",
          link_text: truncate(link.textContent.trim(), 100),
        });
      });
    });

    // --- CTA BUTTON CLICK TRACKING ---
    var ctaPatterns = /^(book|schedule|reserve|get.?quote|get.?started|buy|add.?to.?cart|sign.?up|subscribe|download|apply|request|contact|call|shop|order|enroll|register|join|donate|learn.?more|see.?more|view|start|try|claim|redeem|upgrade)$/i;
    var ctaLoosePatterns = /\b(book\s?now|schedule|reserve|get\s?quote|get\s?started|buy\s?now|add\s?to\s?cart|sign\s?up|subscribe|free\s?trial|apply\s?now|request|contact\s?us|call\s?now|call\s?us|shop\s?now|order\s?now|enroll|register|join\s?now|donate|learn\s?more|book\s?appointment|make\s?reservation|get\s?directions|view\s?menu|see\s?pricing|request\s?demo|start\s?free|claim\s?offer)\b/i;

    document.querySelectorAll("button, a, [role='button'], input[type='submit'], input[type='button']").forEach(function (el) {
      var text = (el.textContent || el.value || "").trim();
      var shortText = truncate(text, 100);

      if (ctaPatterns.test(text.replace(/\s+/g, "")) || ctaLoosePatterns.test(text)) {
        el.addEventListener("click", function () {
          sendEvent("cta_click", "dom_observer", {
            button_text: shortText,
            element_tag: el.tagName.toLowerCase(),
            href: truncate(el.getAttribute("href"), 300) || null,
            classes: truncate(el.className, 200) || null,
          });
        });
      }
    });

    // --- EXTERNAL LINK CLICK TRACKING ---
    var currentHost = window.location.hostname;
    document.querySelectorAll("a[href]").forEach(function (link) {
      try {
        var url = new URL(link.href);
        if (url.hostname !== currentHost && url.protocol.startsWith("http")) {
          link.addEventListener("click", function () {
            sendEvent("outbound_click", "dom_observer", {
              destination: truncate(link.href, 300),
              link_text: truncate(link.textContent.trim(), 100),
            });
          });
        }
      } catch (e) {}
    });
  }

  // =========================================================================
  //  LAYER 3: USER BEHAVIOR SIGNALS
  // =========================================================================

  function initBehaviorTracking() {

    // --- SCROLL DEPTH TRACKING ---
    var scrollMilestones = { 25: false, 50: false, 75: false, 90: false, 100: false };
    var maxScroll = 0;

    function checkScroll() {
      var scrollTop = window.pageYOffset || document.documentElement.scrollTop;
      var docHeight = Math.max(
        document.body.scrollHeight, document.documentElement.scrollHeight,
        document.body.offsetHeight, document.documentElement.offsetHeight
      );
      var winHeight = window.innerHeight;
      var scrollPct = docHeight <= winHeight ? 100 : Math.round((scrollTop / (docHeight - winHeight)) * 100);

      if (scrollPct > maxScroll) maxScroll = scrollPct;

      for (var milestone in scrollMilestones) {
        if (!scrollMilestones[milestone] && scrollPct >= parseInt(milestone)) {
          scrollMilestones[milestone] = true;
          sendEvent("scroll_depth", "behavior", {
            depth_percent: parseInt(milestone),
            page_height: docHeight,
          }, "scroll:" + milestone + ":" + window.location.pathname);
        }
      }
    }

    var scrollThrottle = null;
    window.addEventListener("scroll", function () {
      if (!scrollThrottle) {
        scrollThrottle = setTimeout(function () {
          scrollThrottle = null;
          checkScroll();
        }, 500);
      }
    }, { passive: true });

    // --- ENGAGEMENT TIME TRACKING ---
    var engagedTime = 0;
    var lastActivity = Date.now();
    var isActive = true;
    var isVisible = true;
    var IDLE_THRESHOLD = 30000; // 30 seconds

    function trackActivity() {
      var now = Date.now();
      if (isActive && isVisible) {
        var delta = now - lastActivity;
        if (delta < IDLE_THRESHOLD) {
          engagedTime += delta;
        }
      }
      lastActivity = now;
      isActive = true;
    }

    // Activity listeners (throttled)
    var activityThrottle = null;
    function onActivity() {
      if (!activityThrottle) {
        activityThrottle = setTimeout(function () {
          activityThrottle = null;
          trackActivity();
        }, 1000);
      }
    }

    window.addEventListener("mousemove", onActivity, { passive: true });
    window.addEventListener("scroll", onActivity, { passive: true });
    window.addEventListener("click", onActivity, { passive: true });
    window.addEventListener("keydown", onActivity, { passive: true });
    window.addEventListener("touchstart", onActivity, { passive: true });

    // Visibility tracking
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden") {
        isVisible = false;
        trackActivity();
      } else {
        isVisible = true;
        lastActivity = Date.now();
      }
    });

    // Idle detection
    setInterval(function () {
      if (Date.now() - lastActivity > IDLE_THRESHOLD) {
        isActive = false;
      }
    }, 5000);

    // --- VIDEO TRACKING ---
    function trackVideos() {
      // YouTube iframes
      document.querySelectorAll('iframe[src*="youtube.com"], iframe[src*="youtu.be"]').forEach(function (iframe) {
        sendEvent("video_detected", "dom_observer", {
          video_type: "youtube",
          video_src: truncate(iframe.src, 300),
        }, "vid:" + iframe.src);
      });

      // Vimeo iframes
      document.querySelectorAll('iframe[src*="vimeo.com"]').forEach(function (iframe) {
        sendEvent("video_detected", "dom_observer", {
          video_type: "vimeo",
          video_src: truncate(iframe.src, 300),
        }, "vid:" + iframe.src);
      });

      // HTML5 video elements
      document.querySelectorAll("video").forEach(function (video, idx) {
        var vidId = "html5_video_" + idx;
        video.addEventListener("play", function () {
          sendEvent("video_play", "behavior", {
            video_type: "html5",
            video_src: truncate(video.currentSrc || video.src, 300),
            duration: video.duration || null,
          }, "vplay:" + vidId);
        });
        video.addEventListener("ended", function () {
          sendEvent("video_complete", "behavior", {
            video_type: "html5",
            video_src: truncate(video.currentSrc || video.src, 300),
            duration: video.duration || null,
          }, "vend:" + vidId);
        });
      });
    }

    trackVideos();

    // --- PAGE UNLOAD: Send final engagement summary ---
    function sendEngagementSummary() {
      trackActivity(); // final tally
      sendEvent("engagement_summary", "behavior", {
        engaged_time_ms: engagedTime,
        total_time_ms: Date.now() - pageStartTime,
        max_scroll_depth: maxScroll,
        page_type: pageType,
      });
    }

    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden") sendEngagementSummary();
    });
    window.addEventListener("pagehide", sendEngagementSummary);
  }

  var pageStartTime = Date.now();

  // =========================================================================
  //  LAYER 4: dataLayer INTERCEPTION (GA4, Shopify, WooCommerce, etc.)
  // =========================================================================

  var ECOM_MAP = {
    "purchase": "conversion", "refund": "refund",
    "add_to_cart": "add_to_cart", "remove_from_cart": "remove_from_cart",
    "begin_checkout": "begin_checkout", "add_payment_info": "add_payment_info",
    "view_item": "view_item", "view_item_list": "view_item_list",
    "select_item": "select_item", "add_shipping_info": "add_shipping_info",
    "checkout_completed": "conversion",
    "product_added_to_cart": "add_to_cart",
    "checkout_started": "begin_checkout",
    "collection_viewed": "view_item_list",
    "product_viewed": "view_item",
    "search_submitted": "search",
    "page_viewed": "__skip__",
    "generate_lead": "lead",
    "sign_up": "sign_up",
    "login": "login",
    "eec.purchase": "conversion", "eec.refund": "refund",
    "eec.add": "add_to_cart", "eec.checkout": "begin_checkout",
    // GA4 enhanced measurement
    "form_submit": "form_submit",
    "file_download": "file_download",
    "scroll": "__skip__", // we do our own
    "click": "__skip__", // we do our own
    "video_start": "video_play",
    "video_progress": "video_progress",
    "video_complete": "video_complete",
  };

  function extractRevenueCents(d) {
    var v = d.value !== undefined ? d.value
      : d.revenue !== undefined ? d.revenue
      : d.total_price !== undefined ? parseFloat(d.total_price)
      : (d.purchase && d.purchase.revenue) ? d.purchase.revenue : null;
    if (v === null || v === undefined) return null;
    var n = parseFloat(v);
    if (isNaN(n)) return null;
    return (n > 100 && n === Math.floor(n)) ? Math.round(n) : Math.round(n * 100);
  }

  function extractOrderId(d, entry) {
    return d.transaction_id || d.order_id || d.order_number
      || (d.checkout && d.checkout.order_id)
      || (entry && entry.transaction_id) || null;
  }

  function extractItems(d) {
    var items = d.items || d.products || [];
    if (!Array.isArray(items) || !items.length) return null;
    return items.slice(0, 10).map(function (i) {
      return {
        id: i.item_id || i.id || i.product_id || i.sku || null,
        name: truncate(i.item_name || i.name || i.product_name, 100) || null,
        price: i.price || null, quantity: i.quantity || 1,
        variant: truncate(i.item_variant || i.variant, 50) || null,
        category: truncate(i.item_category || i.category, 50) || null,
      };
    });
  }

  function processDataLayerEntry(entry) {
    if (!entry || typeof entry !== "object") return;
    var eventName = entry.event;
    if (!eventName) return;

    var wrpType = ECOM_MAP[eventName];

    // If it's a known event we skip, skip
    if (wrpType === "__skip__") return;

    // Get ecommerce data
    var ecom = entry.ecommerce || entry;
    if (!entry.ecommerce && entry.items) ecom = entry;

    var revCents = extractRevenueCents(ecom);
    var orderId = extractOrderId(ecom, entry);
    var currency = ecom.currency || ecom.currencyCode || "USD";
    var items = extractItems(ecom);

    if (wrpType === "conversion") {
      sendEvent("purchase", "datalayer_auto", {
        order_id: orderId,
        revenue_cents: revCents,
        currency: currency,
        items: items,
        original_event: eventName,
      }, orderId ? "purchase:" + orderId : null);

      if (CLICK_ID) {
        sendLegacy("/v1/events/conversion", {
          event_type: eventName, order_id: orderId,
          revenue_cents: revCents, currency: currency,
          metadata: { source: "datalayer_auto", items: items },
          page_url: window.location.href,
        });
      }
    } else if (wrpType === "refund") {
      sendEvent("refund", "datalayer_auto", {
        order_id: orderId,
        refund_amount_cents: revCents,
        original_event: eventName,
        items: items,
      }, orderId ? "refund:" + orderId : null);

      if (CLICK_ID) {
        sendLegacy("/v1/events/refund", {
          original_order_id: orderId,
          refund_amount_cents: revCents,
          reason: "datalayer_auto",
        });
      }
    } else if (wrpType) {
      // Known ecommerce event
      sendEvent(wrpType, "datalayer_auto", {
        revenue_cents: revCents,
        order_id: orderId,
        currency: currency,
        items: items,
        original_event: eventName,
      });
    } else {
      // Unknown custom event — capture it anyway
      sendEvent("custom_datalayer", "datalayer_auto", {
        original_event: eventName,
        data_keys: Object.keys(entry).slice(0, 20),
      });
    }
  }

  function interceptDataLayer() {
    window.dataLayer = window.dataLayer || [];
    for (var i = 0; i < window.dataLayer.length; i++) {
      try { processDataLayerEntry(window.dataLayer[i]); } catch (e) {}
    }
    var origPush = window.dataLayer.push.bind(window.dataLayer);
    window.dataLayer.push = function () {
      var result = origPush.apply(window.dataLayer, arguments);
      for (var i = 0; i < arguments.length; i++) {
        try { processDataLayerEntry(arguments[i]); } catch (e) {}
      }
      return result;
    };
  }

  interceptDataLayer();

  // Shopify-specific hooks
  function interceptShopify() {
    if (window.Shopify && window.Shopify.analytics) {
      try {
        var origPublish = window.Shopify.analytics.publish;
        if (typeof origPublish === "function") {
          window.Shopify.analytics.publish = function (name, data) {
            try { processDataLayerEntry({ event: name, ecommerce: data || {} }); } catch (e) {}
            return origPublish.apply(this, arguments);
          };
        }
      } catch (e) {}
    }
    if (window.Shopify && window.Shopify.checkout) {
      try {
        var c = window.Shopify.checkout;
        processDataLayerEntry({
          event: "purchase",
          ecommerce: {
            transaction_id: c.order_id || c.order_number,
            value: c.total_price || c.payment_due,
            currency: c.currency || c.presentment_currency,
            items: (c.line_items || []).map(function (li) {
              return { item_id: li.product_id || li.sku, item_name: li.title,
                price: li.price, quantity: li.quantity, item_variant: li.variant_title };
            }),
          },
        });
      } catch (e) {}
    }
  }

  interceptShopify();
  setTimeout(interceptShopify, 2000);
  setTimeout(interceptShopify, 5000);

  // =========================================================================
  //  LAYER 5: THIRD-PARTY TOOL DETECTION (site classification)
  // =========================================================================

  function detectThirdPartyTools() {
    var tools = [];
    var vertical = "unknown";

    // Ecommerce platforms
    if (window.Shopify) { tools.push("shopify"); vertical = "ecommerce"; }
    if (document.querySelector('meta[name="generator"][content*="WooCommerce"]') ||
        document.querySelector('.woocommerce')) { tools.push("woocommerce"); vertical = "ecommerce"; }
    if (document.querySelector('meta[name="generator"][content*="BigCommerce"]')) { tools.push("bigcommerce"); vertical = "ecommerce"; }
    if (window.Magento || document.querySelector('[data-mage-init]')) { tools.push("magento"); vertical = "ecommerce"; }
    if (document.querySelector('meta[name="generator"][content*="Squarespace"]')) { tools.push("squarespace"); }

    // Payment
    if (window.Stripe || document.querySelector('script[src*="stripe.com"]')) tools.push("stripe");
    if (document.querySelector('script[src*="square"]') || window.SqPaymentForm) tools.push("square");
    if (document.querySelector('script[src*="paypal"]')) tools.push("paypal");

    // Booking / scheduling
    if (document.querySelector('script[src*="calendly"], iframe[src*="calendly"]')) { tools.push("calendly"); if (vertical === "unknown") vertical = "service"; }
    if (document.querySelector('script[src*="acuity"], iframe[src*="acuity"]')) { tools.push("acuity"); if (vertical === "unknown") vertical = "service"; }
    if (document.querySelector('iframe[src*="booksy"]')) { tools.push("booksy"); vertical = "salon"; }
    if (document.querySelector('script[src*="mindbody"], iframe[src*="mindbody"]')) { tools.push("mindbody"); vertical = "fitness"; }
    if (document.querySelector('script[src*="vagaro"], iframe[src*="vagaro"]')) { tools.push("vagaro"); vertical = "salon"; }
    if (document.querySelector('script[src*="fresha"]')) { tools.push("fresha"); vertical = "salon"; }

    // Restaurant
    if (document.querySelector('script[src*="opentable"], iframe[src*="opentable"]')) { tools.push("opentable"); vertical = "restaurant"; }
    if (document.querySelector('script[src*="resy"], iframe[src*="resy"]')) { tools.push("resy"); vertical = "restaurant"; }
    if (document.querySelector('script[src*="toast"], iframe[src*="toasttab"]')) { tools.push("toast"); vertical = "restaurant"; }
    if (document.querySelector('script[src*="doordash"]')) { tools.push("doordash"); vertical = "restaurant"; }
    if (document.querySelector('script[src*="ubereats"]')) { tools.push("ubereats"); vertical = "restaurant"; }
    if (document.querySelector('script[src*="grubhub"]')) { tools.push("grubhub"); vertical = "restaurant"; }
    if (document.querySelector('script[src*="yelp"]')) tools.push("yelp");

    // Healthcare
    if (document.querySelector('script[src*="zocdoc"], iframe[src*="zocdoc"]')) { tools.push("zocdoc"); vertical = "healthcare"; }
    if (document.querySelector('script[src*="healthgrades"]')) { tools.push("healthgrades"); vertical = "healthcare"; }
    if (document.querySelector('script[src*="patientpop"]')) { tools.push("patientpop"); vertical = "healthcare"; }
    if (document.querySelector('script[src*="nexhealth"]')) { tools.push("nexhealth"); vertical = "healthcare"; }

    // Real estate / Auto
    if (document.querySelector('script[src*="zillow"]')) { tools.push("zillow"); vertical = "real_estate"; }
    if (document.querySelector('script[src*="realtor.com"]')) { tools.push("realtor"); vertical = "real_estate"; }
    if (document.querySelector('script[src*="cargurus"]')) { tools.push("cargurus"); vertical = "dealership"; }
    if (document.querySelector('script[src*="dealer.com"]')) { tools.push("dealer_com"); vertical = "dealership"; }
    if (document.querySelector('script[src*="dealerinspire"]')) { tools.push("dealerinspire"); vertical = "dealership"; }

    // Chat widgets
    if (window.Intercom || document.querySelector('script[src*="intercom"]')) tools.push("intercom");
    if (window.drift || document.querySelector('script[src*="drift"]')) tools.push("drift");
    if (window.zE || document.querySelector('script[src*="zendesk"]')) tools.push("zendesk");
    if (window.LiveChatWidget || document.querySelector('script[src*="livechat"]')) tools.push("livechat");
    if (window.$crisp || document.querySelector('script[src*="crisp"]')) tools.push("crisp");
    if (window.Tawk_API || document.querySelector('script[src*="tawk"]')) tools.push("tawk");
    if (document.querySelector('script[src*="tidio"]')) tools.push("tidio");
    if (window.HubSpotConversations || document.querySelector('script[src*="hubspot"]')) tools.push("hubspot");

    // Analytics
    if (window.ga || window.gtag || document.querySelector('script[src*="googletagmanager"]')) tools.push("ga4");
    if (window.fbq || document.querySelector('script[src*="facebook"]')) tools.push("meta_pixel");
    if (window.ttq || document.querySelector('script[src*="tiktok"]')) tools.push("tiktok_pixel");
    if (window.snaptr || document.querySelector('script[src*="snapchat"]')) tools.push("snap_pixel");
    if (window.twq || document.querySelector('script[src*="twitter"]')) tools.push("twitter_pixel");
    if (window.pintrk || document.querySelector('script[src*="pinterest"]')) tools.push("pinterest_pixel");
    if (document.querySelector('script[src*="hotjar"]')) tools.push("hotjar");
    if (window.mixpanel || document.querySelector('script[src*="mixpanel"]')) tools.push("mixpanel");
    if (window.amplitude || document.querySelector('script[src*="amplitude"]')) tools.push("amplitude");
    if (document.querySelector('script[src*="segment"]')) tools.push("segment");
    if (document.querySelector('script[src*="klaviyo"]')) tools.push("klaviyo");

    // CMS
    if (document.querySelector('meta[name="generator"][content*="WordPress"]')) tools.push("wordpress");
    if (document.querySelector('meta[name="generator"][content*="Wix"]') || window.wixBiSession) tools.push("wix");
    if (document.querySelector('meta[name="generator"][content*="Webflow"]')) tools.push("webflow");

    sendEvent("site_detection", "detection", {
      tools: tools,
      detected_vertical: vertical,
      tool_count: tools.length,
      has_analytics: tools.some(function(t) { return ["ga4","meta_pixel","tiktok_pixel","mixpanel","amplitude","segment"].indexOf(t) !== -1; }),
      has_chat: tools.some(function(t) { return ["intercom","drift","zendesk","livechat","crisp","tawk","tidio","hubspot"].indexOf(t) !== -1; }),
      has_booking: tools.some(function(t) { return ["calendly","acuity","booksy","mindbody","vagaro","fresha","opentable","resy","zocdoc"].indexOf(t) !== -1; }),
      has_ecommerce: tools.some(function(t) { return ["shopify","woocommerce","bigcommerce","magento","stripe","square","paypal"].indexOf(t) !== -1; }),
    }, "detect:" + window.location.hostname);
  }

  // =========================================================================
  //  LAYER 6: CHAT WIDGET INTERACTION TRACKING
  // =========================================================================

  function trackChatWidgets() {
    // Intercom
    if (window.Intercom) {
      try {
        window.Intercom("onShow", function () {
          sendEvent("chat_opened", "dom_observer", { provider: "intercom" });
        });
        window.Intercom("onUnreadCountChange", function (count) {
          if (count > 0) sendEvent("chat_message_received", "dom_observer", { provider: "intercom" });
        });
      } catch (e) {}
    }

    // Drift
    if (window.drift) {
      try {
        window.drift.on("chatOpen", function () {
          sendEvent("chat_opened", "dom_observer", { provider: "drift" });
        });
        window.drift.on("startConversation", function () {
          sendEvent("chat_started", "dom_observer", { provider: "drift" });
        });
      } catch (e) {}
    }

    // Zendesk
    if (window.zE) {
      try {
        window.zE("messenger:on", "open", function () {
          sendEvent("chat_opened", "dom_observer", { provider: "zendesk" });
        });
      } catch (e) {}
    }

    // Crisp
    if (window.$crisp) {
      try {
        window.$crisp.push(["on", "chat:opened", function () {
          sendEvent("chat_opened", "dom_observer", { provider: "crisp" });
        }]);
        window.$crisp.push(["on", "message:sent", function () {
          sendEvent("chat_message_sent", "dom_observer", { provider: "crisp" });
        }]);
      } catch (e) {}
    }

    // Tawk.to
    if (window.Tawk_API) {
      try {
        window.Tawk_API.onChatStarted = function () {
          sendEvent("chat_started", "dom_observer", { provider: "tawk" });
        };
      } catch (e) {}
    }
  }

  // =========================================================================
  //  LAYER 6B: BOOKING WIDGET INTERACTION TRACKING
  // =========================================================================

  function trackBookingWidgets() {
    // Calendly
    if (window.addEventListener) {
      window.addEventListener("message", function (e) {
        if (e.data && typeof e.data === "object") {
          if (e.data.event === "calendly.event_scheduled") {
            sendEvent("booking_completed", "dom_observer", {
              provider: "calendly",
              event_data: e.data.payload || null,
            });
            if (CLICK_ID) {
              sendLegacy("/v1/events/conversion", {
                event_type: "booking_completed",
                metadata: { provider: "calendly", source: "dom_observer" },
                page_url: window.location.href,
              });
            }
          }
          if (e.data.event === "calendly.date_and_time_selected") {
            sendEvent("booking_started", "dom_observer", { provider: "calendly" });
          }
        }
      });
    }

    // Generic iframe booking detection (Acuity, Booksy, etc.)
    document.querySelectorAll('iframe[src*="acuity"], iframe[src*="booksy"], iframe[src*="mindbody"], iframe[src*="vagaro"]').forEach(function (iframe) {
      var provider = "unknown";
      var src = iframe.src || "";
      if (src.indexOf("acuity") !== -1) provider = "acuity";
      else if (src.indexOf("booksy") !== -1) provider = "booksy";
      else if (src.indexOf("mindbody") !== -1) provider = "mindbody";
      else if (src.indexOf("vagaro") !== -1) provider = "vagaro";

      sendEvent("booking_widget_loaded", "dom_observer", {
        provider: provider,
        iframe_src: truncate(src, 300),
      }, "booking:" + provider);
    });
  }

  // =========================================================================
  //  INITIALIZATION — Run all layers
  // =========================================================================

  // DOM-dependent layers run after DOM ready
  function initAllLayers() {
    initDomObservation();
    initBehaviorTracking();
    detectThirdPartyTools();
    trackChatWidgets();
    trackBookingWidgets();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAllLayers);
  } else {
    initAllLayers();
  }

  // Re-run detection after everything loads (some widgets load late)
  window.addEventListener("load", function () {
    setTimeout(function () {
      detectThirdPartyTools();
      trackChatWidgets();
      trackBookingWidgets();
    }, 3000);
  });

  // =========================================================================
  //  Conversion page auto-detection
  // =========================================================================

  if (pageType === "conversion_confirm" || pageType === "booking_confirm") {
    sendEvent("conversion_page_detected", "url_pattern", {
      page_type: pageType,
      url: window.location.href,
      title: truncate(document.title, 200),
    });
    if (CLICK_ID) {
      sendLegacy("/v1/events/conversion", {
        event_type: "conversion_page_visit",
        metadata: { page_type: pageType, source: "url_pattern" },
        page_url: window.location.href,
      });
    }
  }

  // =========================================================================
  //  PUBLIC API — window.wrp()
  // =========================================================================

  window.wrp = function (action, data) {
    data = data || {};
    switch (action) {
      case "conversion": sendLegacy("/v1/events/conversion", data); sendEvent("conversion_manual", "manual", data); break;
      case "pageview": sendEvent("pageview_manual", "manual", { page_url: window.location.href }); break;
      case "refund": sendLegacy("/v1/events/refund", data); sendEvent("refund_manual", "manual", data); break;
      case "identify": sendLegacy("/v1/events/identify", { external_customer_id: data.customer_id || null, email_hash: data.email_hash || null }); break;
      default: sendEvent(action, "manual", data);
    }
  };

  console.log("[Wrpper] Pixel v5 active | Org:", ORG_ID, "| Click:", CLICK_ID ? "tracked" : "none", "| Layers: passive, dom, behavior, datalayer, detection");
})();
