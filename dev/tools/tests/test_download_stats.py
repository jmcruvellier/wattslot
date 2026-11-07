"""Statistiques de téléchargement (lot statistiques de diffusion) : lecture des pages publiques du
paquet GHCR et addition par release. Les pages sont réduites au balisage que lit le script."""

import pytest

from tools import download_stats as ds

PACKAGE_PAGE = """
<div class="lh-condensed d-flex flex-column flex-items-baseline tmp-pr-1">
  <span class="d-block color-fg-muted text-small tmp-mb-1">Total downloads</span>
  <h3 title="1234">1,234</h3>
</div>
"""


def version_row(tags: list[str], downloads: str) -> str:
    labels = "".join(
        f'<a class="Label" href="/users/o/packages/container/p/1?tag={t}">{t}</a>' for t in tags
    )
    return (
        f'<li data-view-component="true" class="Box-row">{labels}'
        f'<span><svg class="octicon octicon-download"></svg>\n        {downloads}\n'
        f'        <span class="sr-only">Version downloads</span></span></li>'
    )


def test_the_package_total_is_read_with_its_thousands_separator() -> None:
    assert ds.package_total(PACKAGE_PAGE) == 1234


def test_an_abbreviated_package_total_is_read_from_its_title() -> None:
    page = PACKAGE_PAGE.replace('<h3 title="1234">1,234</h3>', '<h3 title="1038">1.04K</h3>')

    assert ds.package_total(page) == 1038


def test_an_abbreviated_package_total_without_title_is_rounded() -> None:
    page = PACKAGE_PAGE.replace('<h3 title="1234">1,234</h3>', "<h3>1.04K</h3>")

    assert ds.package_total(page) == 1040


@pytest.mark.parametrize(
    ("text", "count"), [("27", 27), ("1,002", 1002), ("1.2K", 1200), ("2.1m", 2_100_000)]
)
def test_displayed_counts_are_parsed(text: str, count: int) -> None:
    assert ds.parse_count(text) == count


def test_a_changed_package_page_is_reported() -> None:
    with pytest.raises(ValueError, match="Total downloads"):
        ds.package_total("<h3>1234</h3>")


def test_each_version_keeps_its_tags_and_downloads() -> None:
    page = version_row(["latest", "0.9.5", "main"], "27") + version_row(["sha-1a2b3c4"], "1,002")

    assert ds.package_versions(page) == [
        {"tags": ["latest", "0.9.5", "main"], "downloads": 27},
        {"tags": ["sha-1a2b3c4"], "downloads": 1002},
    ]


def test_the_image_tag_of_a_release_drops_the_v() -> None:
    assert ds.image_tag("v0.9.5") == "0.9.5"
    assert ds.image_tag("1.0.0") == "1.0.0"


def test_the_version_pages_stop_once_every_release_is_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        1: version_row(["latest", "0.9.5"], "27") + version_row(["sha-1a2b3c4"], "1"),
        2: version_row(["0.9.4"], "64"),
        3: version_row(["0.9.3"], "92"),
    }
    fetched: list[str] = []

    def web_get(path: str) -> str:
        fetched.append(path)
        if "/package/" in path:
            return PACKAGE_PAGE
        return pages.get(int(path.rsplit("page=", 1)[1]), "")

    monkeypatch.setattr(ds, "web_get", web_get)

    image = ds.image_downloads("o", "p", {"0.9.5", "0.9.4"})

    assert image == {"package": "ghcr.io/o/p", "total": 1234, "by_tag": {"0.9.5": 27, "0.9.4": 64}}
    assert len(fetched) == 3  # page du paquet, puis versions pages 1 et 2


def test_a_release_adds_its_image_and_its_assets() -> None:
    releases = [
        {"tag_name": "v0.9.4", "published_at": "2026-10-25T20:52:07Z", "assets": []},
        {
            "tag_name": "v0.9.5",
            "name": "0.9.5",
            "published_at": "2026-11-02T08:14:34Z",
            "assets": [{"name": "wattslot.zip", "size": 10, "download_count": 3}],
        },
        {"tag_name": "v0.8.0", "published_at": "2026-10-01T00:00:00Z", "assets": []},
    ]
    image = {"package": "ghcr.io/o/p", "total": 633, "by_tag": {"0.9.5": 27, "0.9.4": 64}}

    per_release, asset_total, total = ds.summarize(releases, image)

    assert [(r["tag"], r["downloads"], r["image_downloads"]) for r in per_release] == [
        ("v0.9.5", 30, 27),
        ("v0.9.4", 64, 64),
        ("v0.8.0", 0, None),
    ]
    assert per_release[1]["name"] == "v0.9.4"
    assert (asset_total, total) == (3, 636)


def test_without_the_image_only_the_assets_count() -> None:
    releases = [{"tag_name": "v0.9.5", "published_at": None, "assets": []}]

    per_release, asset_total, total = ds.summarize(releases, None)

    assert per_release[0]["downloads"] == 0
    assert per_release[0]["image_downloads"] is None
    assert (asset_total, total) == (0, 0)
