"""Nombre de téléchargements de WattSlot : total et par release (lot statistiques de diffusion).

WattSlot s'installe en tirant l'image ``ghcr.io/jmcruvellier/wattslot`` : l'extension Home
Assistant (``image:`` de ``ha-addon/wattslot/config.yaml``) comme l'installation Docker. C'est
donc **l'image** qui porte les vrais téléchargements. GHCR n'a pas d'API pour ce compteur, mais
la page publique du paquet l'affiche : total (« Total downloads ») et par version (« Version
downloads », une version étant une image avec ses étiquettes ``0.9.5``, ``latest``…). Le script
lit ces pages ; si GitHub change leur balisage, il avertit et continue sans ces chiffres.

GitHub compte aussi les téléchargements des **assets joints aux releases** (champ
``download_count``, API publique ``GET /repos/{owner}/{repo}/releases``). WattSlot n'en joint
aucun pour l'instant : cette part vaut 0, mais elle est gardée pour le jour où il y en aura.

Par release, ``downloads`` additionne les deux : ``image_downloads`` (version de l'image dont
l'étiquette est le numéro de la release sans le ``v``) et ``asset_downloads``. Au total,
``total_downloads`` additionne le total de l'image (toutes versions, y compris ``main`` et les
``sha-…``) et celui des assets. Ces chiffres comptent aussi les téléchargements du mainteneur.

En option, avec un jeton (``GITHUB_TOKEN``) : les **clones** du dépôt via
``GET /repos/{owner}/{repo}/traffic/clones?per=day`` — Home Assistant clone le dépôt de
l'extension quand on l'ajoute (compteur sur 14 jours seulement, comme l'API). L'API traffic
refuse le ``GITHUB_TOKEN`` de la CI : il faut un jeton à grain fin avec la permission
« Administration » en lecture sur le dépôt (secret ``STATS_PAT`` du workflow). Sinon, le
script avertit et continue sans les clones.

``--history CHEMIN`` ajoute une ligne JSON par exécution (date UTC + snapshot) : c'est ce que
fait le workflow ``.github/workflows/stats.yml`` chaque nuit pour garder l'historique au-delà
de la fenêtre de 14 jours de l'API traffic.

Depuis la racine du dépôt :

    python dev/tools/download_stats.py [--repo jmcruvellier/wattslot] [--package wattslot]
        [--json] [--clones] [--history dev/stats/history.jsonl]
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

API = "https://api.github.com"
WEB = "https://github.com"
USER_AGENT = "wattslot-download-stats"
# Pages de versions lues au plus (50 versions par page) : les releases sont en tête.
MAX_VERSION_PAGES = 10

# Au-delà de 1 000, GitHub abrège le compteur (« 1.04K ») et met la valeur exacte dans ``title``.
_TOTAL = re.compile(
    r'Total downloads</span>\s*<h3(?:[^>]*\btitle="([\d,]+)")?[^>]*>\s*([\d.,]+[KkMm]?)\s*</h3>'
)
_VERSION_ROW = '<li data-view-component="true" class="Box-row">'
_TAG = re.compile(r'\?tag=([^"&]+)"')
_VERSION_DOWNLOADS = re.compile(
    r'([\d.,]+[KkMm]?)\s*<span class="sr-only">Version downloads</span>'
)
_SUFFIX = {"k": 1_000, "m": 1_000_000}


def parse_count(text: str) -> int:
    """Compteur affiché par GitHub : ``1,234`` exact, ``1.04K`` ou ``2.1M`` arrondis."""
    text = text.replace(",", "")
    factor = _SUFFIX.get(text[-1:].lower())
    if factor:
        return round(float(text[:-1]) * factor)
    return int(text)


def api_get(path: str, token: str | None) -> object:
    """Appel GET de l'API GitHub ; lève une erreur lisible sinon."""
    req = urllib.request.Request(f"{API}{path}", headers={"Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def web_get(path: str) -> str:
    """Page publique de github.com, sans jeton."""
    req = urllib.request.Request(f"{WEB}{path}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as resp:
        return str(resp.read().decode("utf-8"))


def releases_with_assets(owner: str, repo: str, token: str | None) -> list[dict]:
    """Toutes les releases (paginé) avec leurs assets et leur ``download_count``."""
    out = []
    page = 1
    while True:
        batch = api_get(f"/repos/{owner}/{repo}/releases?per_page=100&page={page}", token)
        if not isinstance(batch, list) or not batch:
            break
        out.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return out


def package_total(html: str) -> int:
    """« Total downloads » de la page d'un paquet ; ``ValueError`` si la page a changé."""
    match = _TOTAL.search(html)
    if not match:
        raise ValueError("compteur « Total downloads » introuvable")
    return parse_count(match.group(1) or match.group(2))


def package_versions(html: str) -> list[dict]:
    """Versions d'une page « versions » : étiquettes et téléchargements de chacune."""
    out = []
    for row in html.split(_VERSION_ROW)[1:]:
        downloads = _VERSION_DOWNLOADS.search(row)
        if downloads:
            out.append(
                {
                    "tags": _TAG.findall(row),
                    "downloads": parse_count(downloads.group(1)),
                }
            )
    return out


def image_tag(release_tag: str) -> str:
    """Étiquette de l'image d'une release : ``v0.9.5`` → ``0.9.5``."""
    return release_tag.removeprefix("v")


def image_downloads(owner: str, package: str, wanted: set[str]) -> dict:
    """Téléchargements de l'image : total, et par étiquette pour celles de ``wanted``."""
    base = f"/users/{owner}/packages/container/{package}"
    total = package_total(web_get(f"/users/{owner}/packages/container/package/{package}"))
    by_tag: dict[str, int] = {}
    for page in range(1, MAX_VERSION_PAGES + 1):
        versions = package_versions(
            web_get(f"{base}/versions?filters%5Bversion_type%5D=tagged&page={page}")
        )
        for version in versions:
            for tag in version["tags"]:
                if tag in wanted:
                    by_tag[tag] = version["downloads"]
        if not versions or wanted <= by_tag.keys():
            break
    return {"package": f"ghcr.io/{owner}/{package}", "total": total, "by_tag": by_tag}


def clones(owner: str, repo: str, token: str) -> dict:
    """Clones du dépôt par jour (14 derniers jours) — ajouts du dépôt de l'extension."""
    data = api_get(f"/repos/{owner}/{repo}/traffic/clones?per=day", token)
    return {
        "count": data.get("count", 0),
        "uniques": data.get("uniques", 0),
        "days": [
            {"day": d.get("timestamp"), "count": d.get("count"), "uniques": d.get("uniques")}
            for d in data.get("clones", [])
        ],
    }


def summarize(releases: list[dict], image: dict | None) -> tuple[list[dict], int, int]:
    """Releases avec leurs téléchargements (assets + image), total des assets, total général."""
    by_tag = image["by_tag"] if image else {}
    per_release = []
    asset_total = 0
    for rel in releases:
        assets = [
            {"name": a["name"], "size": a["size"], "downloads": a["download_count"]}
            for a in rel.get("assets", [])
        ]
        rel_assets = sum(a["downloads"] for a in assets)
        asset_total += rel_assets
        rel_image = by_tag.get(image_tag(rel["tag_name"])) if image else None
        per_release.append(
            {
                "tag": rel["tag_name"],
                "name": rel.get("name") or rel["tag_name"],
                "published_at": rel.get("published_at"),
                "downloads": rel_assets + (rel_image or 0),
                "image_downloads": rel_image,
                "asset_downloads": rel_assets,
                "assets": assets,
            }
        )
    per_release.sort(key=lambda r: r["published_at"] or "", reverse=True)
    return per_release, asset_total, asset_total + (image["total"] if image else 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default="jmcruvellier/wattslot", help="owner/repo GitHub")
    parser.add_argument("--package", default="wattslot", help="paquet de conteneur GHCR")
    parser.add_argument("--json", action="store_true", help="sortie JSON brute")
    parser.add_argument(
        "--clones", action="store_true", help="aussi lire les clones (jeton requis)"
    )
    parser.add_argument(
        "--history", metavar="CHEMIN", help="ajoute une ligne JSON (date + snapshot) à ce fichier"
    )
    args = parser.parse_args()

    owner, _, repo = args.repo.partition("/")
    token = os.environ.get("GITHUB_TOKEN")

    releases = releases_with_assets(owner, repo, token)
    image = None
    try:
        image = image_downloads(owner, args.package, {image_tag(r["tag_name"]) for r in releases})
    except (OSError, ValueError) as err:  # page indisponible ou balisage changé
        print(f"Avertissement : téléchargements de l'image indisponibles ({err}).", file=sys.stderr)
    per_release, asset_total, total = summarize(releases, image)

    result: dict = {
        "repo": args.repo,
        "total_downloads": total,
        "image": {"package": image["package"], "total": image["total"]} if image else None,
        "asset_downloads": asset_total,
        "releases": per_release,
    }

    if args.clones:
        if not token:
            print(
                "Avertissement : --clones sans jeton (variable GITHUB_TOKEN), clones ignorés.",
                file=sys.stderr,
            )
        else:
            try:
                result["clones_14j"] = clones(owner, repo, token)
            except (OSError, ValueError) as err:  # jeton refusé par l'API traffic, JSON en erreur
                print(f"Avertissement : clones indisponibles ({err}), ignorés.", file=sys.stderr)

    if args.history:
        path = Path(args.history)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {"date": datetime.now(UTC).isoformat(timespec="seconds"), **result}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"Dépôt : {args.repo}")
    print(f"Téléchargements (total) : {total}")
    if image:
        print(f"  image {image['package']} : {image['total']}")
    print(f"  assets des releases : {asset_total}")
    for rel in per_release:
        date = (rel["published_at"] or "")[:10]
        detail = "" if rel["image_downloads"] is None else f"  (image : {rel['image_downloads']})"
        print(f"  {rel['tag']:<10} {date}  {rel['downloads']:>6} téléchargement(s){detail}")
        for a in rel["assets"]:
            print(f"      {a['name']}  ({a['size']} o)  {a['downloads']} téléchargement(s)")
    if "clones_14j" in result:
        c = result["clones_14j"]
        print(f"Clones du dépôt sur 14 jours : {c['count']} (uniques : {c['uniques']})")
        for d in c["days"]:
            day = datetime.fromisoformat(d["day"].replace("Z", "+00:00")).astimezone(UTC)
            print(f"  {day:%Y-%m-%d}  {d['count']:>4} clones  ({d['uniques']} uniques)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
