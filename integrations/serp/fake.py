"""Deterministic fake SERP provider for tests + offline development."""

from __future__ import annotations

from seo_core.serp.models import SerpFeatureRaw, SerpItem, SerpPayload

_FIXTURES: dict[str, SerpPayload] = {
    "how to clean gemstone rings": SerpPayload(
        query="how to clean gemstone rings",
        provider="fake",
        organic=[
            SerpItem(1, "https://gia.edu/gem-care", "How to Clean Gemstone Rings Safely",
                     "Use warm water and mild soap. Avoid ultrasonic cleaners for soft stones."),
            SerpItem(2, "https://jewelry.com/care/rings", "Gemstone Ring Cleaning Guide",
                     "Soft cloth, mild detergent, and warm water. Dry thoroughly to protect the setting."),
            SerpItem(3, "https://shop.example.com/blog/clean-rings", "Cleaning Your Gemstone Ring",
                     "A step-by-step method for cleaning gemstone rings at home without damage."),
            SerpItem(4, "https://reddit.com/r/jewelry/clean", "Best way to clean a sapphire ring?",
                     "Community tips on cleaning sapphire and other hard gemstone rings."),
        ],
        features=[
            SerpFeatureRaw("people_also_ask", position=3, items=[
                "Can you clean gemstone rings with vinegar?",
                "How often should you clean a gemstone ring?",
                "What household products damage gemstones?",
            ]),
            SerpFeatureRaw("featured_snippet", position=1, data={"source": "gia.edu"}),
            SerpFeatureRaw("video", position=5, items=["How to Clean Jewelry at Home"]),
        ],
        related_searches=["how to clean a diamond ring", "gemstone cleaning solution",
                          "is it safe to clean opal rings?"],
    ),
}


class FakeSerpProvider:
    name = "fake"

    def search(self, query: str, *, locale: str = "en-US", device: str = "desktop",
               num: int = 10) -> SerpPayload:
        key = query.lower().strip()
        if key in _FIXTURES:
            return _FIXTURES[key]
        return SerpPayload(query=query, provider="fake", organic=[
            SerpItem(i + 1, f"https://example{i}.com/{key.replace(' ', '-')}", f"{query} result {i + 1}",
                     f"A page about {query}.")
            for i in range(min(num, 5))
        ])
