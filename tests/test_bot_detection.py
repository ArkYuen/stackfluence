"""Tests for bot detection scoring."""

import pytest
from app.core.bot_detection import score_request


REAL_CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

REAL_HEADERS = {
    "accept-language": "en-US,en;q=0.9",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "cross-site",
}


class TestHardBlocks:
    """Obvious automation UAs should be hard-blocked (risk=1.0)."""

    @pytest.mark.parametrize("ua", [
        "curl/7.88.1",
        "python-requests/2.31.0",
        "Go-http-client/1.1",
        "Scrapy/2.11.0",
        "Mozilla/5.0 HeadlessChrome/120.0",
        "puppeteer",
    ])
    def test_automation_uas_blocked(self, ua):
        v = score_request(ua, REAL_HEADERS)
        assert v.should_block is True
        assert v.risk_score == 1.0

    def test_real_browser_not_blocked(self):
        v = score_request(REAL_CHROME_UA, REAL_HEADERS)
        assert v.should_block is False
        assert v.risk_score < 0.3


class TestKnownBots:
    """Search/social bots: not blocked, but high risk score."""

    @pytest.mark.parametrize("ua", [
        "Googlebot/2.1 (+http://www.google.com/bot.html)",
        "facebookexternalhit/1.1",
        "Twitterbot/1.0",
        "LinkedInBot/1.0",
    ])
    def test_known_bots_flagged(self, ua):
        v = score_request(ua, REAL_HEADERS)
        assert v.should_block is False
        assert v.risk_score >= 0.5


class TestHeaderSanity:
    def test_missing_accept_language_adds_risk(self):
        headers = {k: v for k, v in REAL_HEADERS.items() if k != "accept-language"}
        v = score_request(REAL_CHROME_UA, headers)
        assert v.risk_score > 0.0
        assert v.signals.missing_accept_language is True

    def test_missing_sec_fetch_adds_risk(self):
        headers = {"accept-language": "en-US"}
        v = score_request(REAL_CHROME_UA, headers)
        assert v.signals.missing_sec_fetch is True
        assert v.risk_score > 0.0


class TestDatacenterASN:
    def test_datacenter_ip_flagged(self):
        v = score_request(REAL_CHROME_UA, REAL_HEADERS, asn=16509)  # AWS
        assert v.signals.is_datacenter_ip is True
        assert v.risk_score > 0.0

    def test_residential_ip_clean(self):
        v = score_request(REAL_CHROME_UA, REAL_HEADERS, asn=7922)  # Comcast
        assert v.signals.is_datacenter_ip is False


class TestRateLimiting:
    def test_rate_limited_adds_risk(self):
        v = score_request(REAL_CHROME_UA, REAL_HEADERS, rate_limited=True)
        assert v.signals.rate_limited is True
        assert v.risk_score >= 0.3


class TestCleanTraffic:
    def test_perfect_request_scores_zero(self):
        v = score_request(REAL_CHROME_UA, REAL_HEADERS)
        assert v.risk_score == 0.0
        assert v.should_block is False
