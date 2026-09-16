"""External document reads are always explicit fakes in the test suite."""
import pytest


@pytest.fixture(autouse=True)
def offline_research_documents(monkeypatch):
    from portal import research_documents
    from portal.research_fetch import CatalogFetchError

    def unavailable(*args, **kwargs):
        raise CatalogFetchError("offline_test")

    monkeypatch.setattr(research_documents, "fetch_catalog_html", unavailable)
