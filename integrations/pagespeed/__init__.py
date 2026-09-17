from integrations.pagespeed.base import VitalsProvider
from integrations.pagespeed.fake import FakeVitalsProvider


def get_vitals_provider(name: str = "pagespeed") -> VitalsProvider:
    if name == "fake":
        return FakeVitalsProvider()
    if name == "pagespeed":
        from integrations.pagespeed.psi import PageSpeedInsightsProvider

        return PageSpeedInsightsProvider()
    raise ValueError(f"no vitals provider for {name!r}")


__all__ = ["VitalsProvider", "FakeVitalsProvider", "get_vitals_provider"]
