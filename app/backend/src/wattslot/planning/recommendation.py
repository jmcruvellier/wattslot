"""Texte de recommandation du jour, envoyé en notification par HA (lot 3.7).

Construit à partir des **explications** du plan (``planning/explain.py``) et de ses indicateurs,
dans la langue voulue (catalogues ``planning/locales``), à la place des textes par règles de la
v1 : objectif du calcul, équipements à lancer avec les bornes exactes de leur cycle et pourquoi
(surplus solaire, heures creuses, ordre, contraintes, autre départ possible), tâches reportées,
batterie (SoC initial, maximum prévu, final, et son fonctionnement), durées à placer, bilan prévu,
avertissements. Texte entièrement déterministe, sans LLM : il ne peut pas inventer une heure ni
un avertissement. Un plan sans explications (calculé avant le lot 3.7) donne le même texte, sans
les raisons.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from wattslot.home_assistant import HomeAssistantClient
from wattslot.languages import number
from wattslot.planning.explain import catalog, render
from wattslot.planning.plan import Explanation, Indicators, RuntimePlan, Slot
from wattslot.planning.plan import Plan as DayPlan
from wattslot.planning.warning_texts import warning_text
from wattslot.views.timeline import cycle_bounds


def _text(lang: str, key: str, **params: Any) -> str:
    return catalog(lang)[f"recommendation.{key}"].format(**params)


def _hhmm(minutes: int) -> str:
    """« 10h », « 11h20 » (minutes depuis minuit)."""
    hours, rest = divmod(int(minutes), 60)
    return f"{hours}h{rest:02d}" if rest else f"{hours}h"


def _bounds(item: Mapping[str, Any]) -> tuple[int, int]:
    """Bornes exactes du cycle (``bornes_minutes`` de la v1, reprise par la frise)."""
    start, end = cycle_bounds(item)
    return int(start), int(end)


def _why(explanation: Explanation | None, lang: str) -> str:
    """Raisons d'un élément, l'objectif mis à part (dit une fois en tête)."""
    if explanation is None:
        return ""
    text = render(explanation, lang, without=("objective",))
    return f" {text}" if text else ""


def _objective(day: DayPlan) -> str | None:
    for item in day.items:
        if item.explanation is None:
            continue
        for reason in item.explanation.reasons:
            if reason.code == "objective":
                return str(reason.params["objective"])
    return None


def _appliances(day: DayPlan, raw: Sequence[Mapping[str, Any]], lang: str) -> list[str]:
    found = []
    for item, source in zip(day.items, raw, strict=True):
        if not isinstance(item, Slot):
            continue
        start, end = _bounds(source)
        line = _text(
            lang,
            "appliance",
            device=item.device,
            start=_hhmm(start),
            end=_hhmm(end),
            energy=number(item.energy_kwh or 0.0, lang, 2),
        )
        found.append((start, line + _why(item.explanation, lang)))
    return [line for _, line in sorted(found, key=lambda f: f[0])]  # dans l'ordre de la journée


def _battery(day: DayPlan, lang: str) -> str:
    battery = day.battery
    if battery is None:
        return _text(lang, "battery_unknown")
    soc = battery.soc_kwh
    if not soc:
        return _text(lang, "battery_still") + _why(battery.explanation, lang)
    hour = max(soc, key=lambda h: soc[h])
    return _text(
        lang,
        "battery",
        start=number(battery.start_kwh or 0.0, lang, 2),
        top=number(soc[hour], lang, 2),
        hour=hour,
        end=number(battery.end_kwh or 0.0, lang, 2),
    ) + _why(battery.explanation, lang)


def _runtime(item: RuntimePlan, lang: str) -> str:
    active = [s for s in item.segments if s.mode != "off"]
    if not active:
        return _text(lang, "runtime_off", device=item.device) + _why(item.explanation, lang)
    spans: list[list[Any]] = []  # [début, fin, modes] : segments contigus réunis
    for segment in active:
        if spans and spans[-1][1] == segment.start_hour:
            spans[-1][1] = segment.end_hour
            spans[-1][2].append(segment.mode)
        else:
            spans.append([segment.start_hour, segment.end_hour, [segment.mode]])
    ranges = ", ".join(
        f"{start}h-{end}h ({'/'.join(dict.fromkeys(modes))})" for start, end, modes in spans
    )
    return _text(lang, "runtime", device=item.device, ranges=ranges) + _why(item.explanation, lang)


def _balance(indicators: Indicators | None, lang: str) -> str | None:
    if indicators is None:
        return None
    text = _text(
        lang,
        "balance",
        cost=number(indicators.cost_eur, lang, 2),
        grid=number(indicators.import_kwh, lang, 1),
    )
    if indicators.self_consumption_percent is not None:
        percent = round(indicators.self_consumption_percent)
        text += " " + _text(lang, "balance_self", percent=percent)
    if indicators.co2_kg is not None:
        text += " " + _text(lang, "balance_co2", co2=number(indicators.co2_kg, lang, 2))
    return text


def title(lang: str = "fr") -> str:
    return _text(lang, "title")


def recommendation(state: Mapping[str, Any], lang: str = "fr") -> str:
    """Texte du plan du jour (format de la v1, explications comprises), dans la langue voulue."""
    raw = list(state.get("planning", []))
    day = DayPlan.from_v1(dict(state))
    lines = []
    objective = _objective(day)
    if objective is not None:
        lines += [_text(lang, "objective", objective=catalog(lang)[f"objective.{objective}"]), ""]
    appliances = _appliances(day, raw, lang)
    lines += [_text(lang, "appliances"), *(appliances or [_text(lang, "none")])]
    reports = state.get("reports") or []
    if reports:
        lines += [
            "",
            _text(lang, "postponed"),
            *(f"- {warning_text(r, lang)}" for r in reports),
        ]
    lines += ["", _battery(day, lang)]
    runtimes = day.runtimes
    lines += [_runtime(item, lang) for item in runtimes] or [_text(lang, "runtime_none")]
    balance = _balance(day.indicators, lang)
    if balance is not None:
        lines += ["", balance]
    warnings = state.get("avertissements", [])
    if warnings:
        lines += [
            "",
            _text(lang, "warnings"),
            *(f"- {warning_text(w, lang)}" for w in warnings),
        ]
    return "\n".join(lines)


async def send(client: HomeAssistantClient, service: str, message: str, lang: str = "fr") -> None:
    """Notification par un service ``notify.*`` de HA."""
    domain, name = service.split(".", 1)
    await client.command(
        "call_service",
        domain=domain,
        service=name,
        service_data={"title": title(lang), "message": message},
    )
