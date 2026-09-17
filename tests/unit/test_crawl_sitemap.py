from __future__ import annotations

from seo_core.crawl.sitemap import parse_robots, parse_sitemap

ROBOTS = """
User-agent: *
Disallow: /admin
Disallow: /cart
Allow: /admin/help
Crawl-delay: 2
Sitemap: https://x.com/sitemap.xml

User-agent: BadBot
Disallow: /
"""

SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://x.com/a</loc></url>
  <url><loc>https://x.com/b</loc></url>
</urlset>"""

INDEX = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://x.com/sitemap-1.xml</loc></sitemap>
</sitemapindex>"""


def test_robots_rules() -> None:
    rules = parse_robots(ROBOTS)
    assert rules.crawl_delay == 2.0
    assert rules.sitemaps == ["https://x.com/sitemap.xml"]
    assert rules.can_fetch("/blog/post") is True
    assert rules.can_fetch("/admin/users") is False
    assert rules.can_fetch("/admin/help") is True  # longer Allow wins
    assert rules.can_fetch("/cart") is False


def test_sitemap_urls() -> None:
    pages, nested = parse_sitemap(SITEMAP)
    assert pages == ["https://x.com/a", "https://x.com/b"]
    assert nested == []


def test_sitemap_index() -> None:
    pages, nested = parse_sitemap(INDEX)
    assert pages == []
    assert nested == ["https://x.com/sitemap-1.xml"]
