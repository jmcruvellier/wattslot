"""Contrôle des données personnelles (lot 7.1). Les exemples sont assemblés par morceaux : écrits en
entier, ils seraient eux-mêmes signalés, ce fichier étant publié."""

from pathlib import Path

from tools.privacy_check import Finding, personal_terms, published, scan

PRIVATE_IP = "192." + "168.10.75"
JWT = "ey" + "JhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature"
GITHUB = "gh" + "p_" + "a" * 36
EMAIL = "jean" + "@" + "maison.fr"
MAC = "b0:81:84" + ":e9:b1:e0"


def rules(text: str, terms: list[str] | None = None) -> list[str]:
    return [finding.rule for finding in scan("f.py", text, terms or [])]


def test_the_manifest_keeps_its_files_and_folders() -> None:
    files = ["app/main.py", "apps/x.py", "private/v1.py", "repository.yaml", "dev/tools/a.py"]
    manifest = ["# commentaire", "app/", "repository.yaml", "", "dev/"]

    assert published(files, manifest) == ["app/main.py", "repository.yaml", "dev/tools/a.py"]


def test_generic_rules() -> None:
    assert rules(f'URL = "http://{PRIVATE_IP}:5000"') == ["ipv4-privee"]
    assert rules(f"token = {JWT}") == ["jeton-jwt"]
    assert rules(f"token = {GITHUB}") == ["jeton-github"]
    assert rules(f"contact : {EMAIL}") == ["e-mail"]
    assert rules(f"mac {MAC}") == ["adresse-mac"]


def test_public_values_pass() -> None:
    supervisor = "172." + "30.32.2"
    assert rules(f'INGRESS = "{supervisor}"') == []
    assert rules('APP = "http://192.0.2.10:8100"') == []  # plage de documentation (RFC 5737)
    assert rules('USER = "41898282+github-actions[bot]@users.noreply.github.com"') == []
    assert rules('MAIL = "someone@example.com"') == []
    assert rules("version 10.2.3") == []  # pas une adresse : trois nombres seulement


def test_personal_terms_match_whole_words_without_case() -> None:
    terms = ["lea", "srv-1"]

    assert rules("sensor.prise_chambre_LEA_tv", terms) == ["terme personnel n° 1"]
    assert rules("ssh root@srv-1", terms) == ["terme personnel n° 2"]
    assert rules("Les galeas", terms) == []  # « lea » dans un mot


def test_the_marker_allows_a_line_and_the_output_hides_the_value() -> None:
    assert rules(f'IP = "{PRIVATE_IP}"  # privacy: ok, exemple de la documentation') == []
    finding = Finding("app/a.py", 3, "terme personnel n° 1")
    assert str(finding) == "app/a.py:3: terme personnel n° 1"


def test_personal_terms_come_from_the_secret_then_from_a_file(tmp_path: Path) -> None:
    file = tmp_path / "terms.txt"
    file.write_text("# prénoms\nalpha\n\n beta \n", encoding="utf-8")

    assert personal_terms({"PRIVACY_TERMS": "un\ndeux"}) == ["un", "deux"]
    assert personal_terms({"PRIVACY_TERMS_FILE": str(file)}) == ["alpha", "beta"]
    assert personal_terms({"PRIVACY_TERMS_FILE": str(tmp_path / "absent.txt")}) == []
