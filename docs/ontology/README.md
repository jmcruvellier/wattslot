# WattSlot ontology

*[Version française](../fr/ontology/README.md)*

WattSlot stores your home as an RDF graph. Its vocabulary has permanent addresses under `https://w3id.org/wattslot/`. Each address redirects here, or to the Turtle file when a client asks for `text/turtle`.

| Address | What it is | Turtle |
|---|---|---|
| `https://w3id.org/wattslot/ontology#…` | Every class and property of WattSlot (prefix `wattslot:`) | [ontology.ttl](ontology.ttl) |
| `https://w3id.org/wattslot/ontology/library/home-energy` | "Home energy" library: the home, devices, sensors and their roles, quantities, aggregates of readings | [home-energy.ttl](home-energy.ttl) |
| `https://w3id.org/wattslot/ontology/schema` | The application's schema: what it saves from your settings (device behaviours, tariff, battery, constraints, recurrences, objective) | [schema.ttl](schema.ttl) |
| `https://w3id.org/wattslot/home/…` | Your own home's devices and sensors. They exist only in your installation, never online | — |

The library builds on [SAREF](https://saref.etsi.org/core/), [SAREF4ENER](https://saref.etsi.org/saref4ener/), [SOSA and SSN](https://www.w3.org/TR/vocab-ssn/). Labels are in English and French.

## For developers

These files are generated from the application's files (`app/backend/src/wattslot/ontology/`), whose addresses are relative. After a change there, run:

```bash
python dev/tools/ontology_files.py
```

The tests of `dev/` fail when the files here no longer match. The w3id redirections are in [`dev/w3id/`](../../dev/w3id/).
