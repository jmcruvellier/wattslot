"""Outils du serveur MCP (lots 6.1 et 6.2).

Chaque outil rend un objet JSON court, construit sur ce que la v2 calcule déjà (API des vues,
configuration, ingestion, diagnostic), avec les textes déjà rédigés dans la langue réglée pour
les notifications : le LLM n'a rien à recalculer. Tous lisent seulement, sauf
``request_device``, qui dépose une demande comme « Mes demandes » (lot 4.5). Les montants sont
écrits dans la devise de la maison (``currency.amount``).
"""

import re
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from wattslot import configuration, currency, home_model, notifications, user_requests
from wattslot.aggregation import HOUR
from wattslot.configuration import Behavior
from wattslot.detection import DeviceKind, Role
from wattslot.home_assistant import ConnectionState
from wattslot.home_model import LINES, Phase, Supply
from wattslot.languages import number
from wattslot.planning.explain import catalog
from wattslot.planning.journal import cycle_appliances
from wattslot.planning.tariff_sources import needs_states, tariff_context
from wattslot.planning.warning_texts import long_date
from wattslot.tariff import NO_CONTEXT, Tariff, TariffContext, TariffKind, off_peak_ranges
from wattslot.views.day import DayView
from wattslot.views.routes import day_view_of, objective_of, week_view_of
from wattslot.views.timeline import Bar

Day = Literal["yesterday", "today", "tomorrow"]

# Qualité de la journée (ensoleillée, mitigée, couverte, lot 5.1), dans la langue réglée.
WEATHER: dict[str, dict[str, str]] = {
    "fr": {
        "sunny": "journée ensoleillée",
        "mixed": "journée mitigée",
        "cloudy": "journée couverte",
    },
    "en": {"sunny": "sunny day", "mixed": "mixed day", "cloudy": "cloudy day"},
    "de": {"sunny": "sonniger Tag", "mixed": "wechselhafter Tag", "cloudy": "bedeckter Tag"},
    "nl": {"sunny": "zonnige dag", "mixed": "wisselvallige dag", "cloudy": "bewolkte dag"},
    "es": {"sunny": "día soleado", "mixed": "día variable", "cloudy": "día nublado"},
    "it": {
        "sunny": "giornata soleggiata",
        "mixed": "giornata variabile",
        "cloudy": "giornata nuvolosa",
    },
}
NO_PLAN = {"error": "no_plan", "hint": "No plan computed yet for this day."}

# Grandeurs « du moment » : puissances et niveau de charge (les compteurs d'énergie, eux,
# passent par get_energy).
NOW_ROLES = {
    Role.STATE_OF_CHARGE: "%",
    Role.POWER_PRODUCED: "W",
    Role.POWER_CONSUMED: "W",
}
# Équipements de la maison par rôle dans le plan : ceux que le calcul place quand il y a lieu,
# ceux qu'il pourrait placer mais qui sont exclus du calcul, le reste. « planned » se lisait
# « prévus aujourd'hui » (un modèle a annoncé le lave-vaisselle comme « l'autre appareil prévu »).
MANAGED = {Behavior.CYCLE, Behavior.ENERGY_BY_DEADLINE, Behavior.RUNTIME}
HOME_GROUP_OF = {Behavior.PRODUCTION: "solar", Behavior.GRID: "grid"}
HOME_GROUPS = (
    "placed_by_wattslot",
    "excluded_from_planning",
    "batteries",
    "solar",
    "grid",
    "other_loads",
)
OBJECTIVE_TEXT = {"autonomy": "import"}  # objectif → texte du catalogue (« objective.… »)
# Une question de request_device vaut confirmation pendant ce délai.
PENDING_FOR = timedelta(minutes=10)
FRESH = timedelta(hours=2)  # au-delà, un relevé ne dit plus « en ce moment »
RUNNING_W = 20  # en dessous, un appareil est en veille


def language(state: Any) -> str:
    """Langue des réponses : celle réglée pour les notifications (lot 5.6)."""
    return notifications.load(state.database).language


def today_of(state: Any) -> date:
    """Date du jour dans le fuseau de la maison."""
    return datetime.now(state.raw.zone).date()


def clock(hours: float) -> str:
    """Heure fractionnaire → « 13:05 »."""
    minutes = round(hours * 60)
    return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}"


def _plain(text: str) -> str:
    """Minuscules sans accents, pour retrouver « lave linge » dans « Lave-linge »."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    letters = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(letters.replace("-", " ").replace("_", " ").split())


def find_name(wanted: str, names: Sequence[str]) -> str | None:
    """Nom d'équipement qui correspond à ``wanted`` (exact, puis contenu, sans accents)."""
    key = _plain(wanted)
    for name in names:
        if _plain(name) == key:
            return name
    for name in names:
        if key and (key in _plain(name) or _plain(name) in key):
            return name
    return None


def _bars(bars: Sequence[Bar]) -> list[dict[str, Any]]:
    return [
        {
            "start": clock(b.start_hour),
            "end": clock(b.end_hour),
            "kwh": round(b.energy_kwh, 2),
            **({"action": b.action} if b.action else {}),
            **({"mode": b.mode} if b.mode else {}),
        }
        for b in bars
    ]


def _max_hour(hour: int) -> str:
    """Heure du maximum de la batterie : le niveau de charge du plan est celui de fin d'heure,
    d'où la tranche « 14:00-15:00 » pour la fin de l'heure 14 (le texte dit « vers 14 h ») ;
    0 : dès le départ, à minuit."""
    return "00:00" if hour <= 0 else f"{hour - 1:02d}:00-{hour:02d}:00"


def _percent(value: float, lang: str) -> str:
    """Pourcentage arrondi au format de la langue (« 12 % »)."""
    return f"{number(value, lang, 0)}\u00a0%"


def _summary(view: DayView, lang: str) -> dict[str, Any]:
    s = view.summary
    found: dict[str, Any] = {
        "production_kwh": round(s.production_kwh, 2),
        # « acheté », « revendu » : « import » et « export » se lisaient l'un pour l'autre.
        "bought_from_grid_kwh": round(s.grid_import_kwh, 2),
        "sold_to_grid_kwh": round(s.grid_export_kwh, 2),
    }
    if view.battery_capacity_kwh is not None:
        # En phrase : avec « battery_end_of_day_percent », qwen3 écrivait encore « la batterie se
        # charge à 12 % à la fin de la journée » (banc du 06/11) ; avant ce nom, « la batterie est
        # à 10 % » était lu comme le niveau actuel.
        # Maximum dès minuit : « part de », sans heure ; avec « monte au plus à 14 % (00:00) »,
        # qwen3 disait « la batterie monte jusqu'à 14 % » alors qu'elle ne fait que descendre.
        key = "assistant.battery_day" if s.soc_max_hour > 0 else "assistant.battery_day_from_start"
        found["battery"] = catalog(lang)[key].format(
            max=_percent(s.soc_max_percent, lang),
            at=_max_hour(s.soc_max_hour),
            end=_percent(s.soc_end_percent, lang),
        )
    # Indicateurs de la journée entière (Aujourd'hui, Hier : heures passées mesurées).
    found.update(_indicators(view, lang))
    return found


def _indicators(view: DayView, lang: str) -> dict[str, Any]:
    """Coût de la journée (achat moins revente, abonnement compris), part de la production
    consommée sur place, CO₂ quand il est connu."""
    i = view.indicators
    if i is None:
        return {}
    found: dict[str, Any] = {"cost": currency.amount(i.cost_eur, lang)}
    if i.self_consumption_percent is not None:
        found["self_consumption_percent"] = round(i.self_consumption_percent)
    if i.co2_kg is not None:
        found["co2_kg"] = round(i.co2_kg, 1)
    return found


def _next_action(view: DayView, lang: str) -> dict[str, Any] | None:
    """Prochain appareil à lancer aujourd'hui, et les autres départs permis avec leur écart de
    coût par rapport au plan."""
    action = view.next_action
    if action is None:
        return None
    found: dict[str, Any] = {
        "device": action.device,
        "start": clock(action.start_min / 60),
        "end": clock(action.end_min / 60),
    }
    if action.explanation:
        found["why"] = action.explanation
    if action.alternatives:
        found["other_starts"] = [
            {
                "start": clock(a.start_min / 60),
                "extra_cost": currency.amount(a.cost_eur_delta, lang, signed=True),
            }
            for a in action.alternatives
        ]
    return found


# Lignes du texte de recommandation reprises par le résumé : le bilan du plan au moment du calcul
# (« Bilan prévu : 0,99 € ») et la batterie en kWh, avec l'heure du maximum du plan. À côté du
# coût de la journée entière et de la batterie en pourcentage du résumé, deux chiffres pour une
# même question : les modèles prenaient l'un pour l'autre.
FIGURE_LINES = ("battery", "balance", "balance_rest")


def _pattern(template: str) -> re.Pattern[str]:
    """Début d'une ligne écrite d'après ``template`` (« {x} » : n'importe quel texte)."""
    parts = re.split(r"\{[a-z_]+\}", template)
    return re.compile(".+?".join(re.escape(p) for p in parts))


def plan_text(text: str | None, lang: str, day: Day = "today") -> str | None:
    """Texte de recommandation sans les lignes de chiffres que le résumé donne déjà. Rédigé comme
    la notification du jour, il dit « aujourd'hui » : pour un autre jour, le mot du jour voulu
    (une note en anglais à côté ne suffisait pas, « aujourd'hui » était repris pour demain)."""
    if text is None:
        return None
    texts = catalog(lang)
    patterns = [_pattern(texts[f"recommendation.{key}"]) for key in FIGURE_LINES]
    lines = [line for line in text.split("\n") if not any(p.match(line) for p in patterns)]
    found = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if day != "today":
        today = re.escape(texts["assistant.today"])
        found = re.sub(rf"\b{today}\b", texts[f"assistant.{day}"], found)
    return found


async def _next_planned(state: Any, after: date) -> dict[str, Any] | None:
    """Premier appareil que l'horizon place après ``after``."""
    lang = language(state)
    week = await week_view_of(state, lang)
    for other in week.days if week else []:
        if other.day > after and other.devices:
            first = min(other.devices, key=lambda p: p.start_min)
            return {
                "day": _when(other.day, today_of(state), lang),
                "device": first.device,
                "start": clock(first.start_min / 60),
                "end": clock(first.end_min / 60),
            }
    return None


async def get_day_plan(state: Any, day: Day = "today") -> dict[str, Any]:
    lang = language(state)
    view = await day_view_of(state, day, lang)
    if view is None:
        return NO_PLAN
    found: dict[str, Any] = {
        # Jours en mots, heures locales : une date au format brut était recopiée telle quelle.
        "day": _when(view.day, today_of(state), lang),
        "computed_at": _moment(view.computed_at, state, lang) if view.computed_at else None,
        "recommendation": plan_text(view.recommendation, lang, day),
        "summary": _summary(view, lang),
        "warnings": [n.text for n in view.notices],
    }
    if day == "today":
        # Une phrase plutôt qu'une valeur vide : les modèles recopiaient le champ « null ».
        found["next_appliance"] = _next_action(view, lang) or catalog(lang)["assistant.no_next"]
        if view.next_action is None:
            later = await _next_planned(state, view.day)
            if later is not None:
                found["next_planned"] = later
    return found


def _status_text(status: str, shift_min: int | None, lang: str) -> str:
    """État du cycle en une phrase (« on_time » était recopié tel quel)."""
    texts = catalog(lang)
    if status == "shifted" and shift_min:
        key = "late" if shift_min > 0 else "early"
        return texts[f"assistant.status.{key}"].format(minutes=abs(shift_min))
    return texts[f"assistant.status.{'on_time' if status == 'shifted' else status}"]


async def explain_device(state: Any, device: str, day: Day = "today") -> dict[str, Any]:
    view = await day_view_of(state, day, language(state))
    if view is None:
        return NO_PLAN
    names = [r.device for r in view.timeline.rows] + [e.device for e in view.explanations]
    name = find_name(device, list(dict.fromkeys(names)))
    if name is None:
        absent = await _not_planned(state, device, view.day)
        if "error" in absent:
            # Appareil inconnu (« l'autre appareil ») : ceux qui tournent vraiment ce jour-là,
            # sans la batterie ni les lignes à l'arrêt ; avec toutes les lignes du plan, qwen3
            # annonçait « la batterie et la filtration » prévues, la filtration étant arrêtée.
            absent["appliances_this_day"] = _others(view, "", language(state))
        else:
            absent["other_appliances_this_day"] = _others(view, absent["device"], language(state))
            if view.day == today_of(state) and (now := _power_now(state, absent["device"])):
                absent["now"] = now
        return absent
    row = next((r for r in view.timeline.rows if r.device == name), None)
    status = next((s for s in view.timeline.statuses if s.device == name), None)
    explanation = next((e.text for e in view.explanations if e.device == name), None)
    found: dict[str, Any] = {
        "device": name,
        "day": _when(view.day, today_of(state), language(state)),
    }
    if row is not None:
        found["planned"] = _bars(row.planned)
        if row.actual:
            found["actual"] = _bars(row.actual)
    if status is not None:
        found["status"] = _status_text(status.status, status.shift_min, language(state))
    if explanation:
        found["why"] = explanation
    found["other_appliances_this_day"] = _others(view, name, language(state))
    if view.day == today_of(state) and (now := _power_now(state, name)):
        found["now"] = now
    return found


def _power_now(state: Any, name: str) -> str | None:
    """« En ce moment » d'un équipement : en marche (et sa puissance) ou à l'arrêt, d'après ses
    capteurs de puissance ; rien sans HA ni capteur. À « pourquoi le chauffe-eau tourne ? » avec
    seulement « pas prévu ce jour-là », les modèles du banc inventaient « activé manuellement »,
    « démarré spontanément » ou « il tourne parce que rien n'est prévu »."""
    if state.ingestor is None:
        return None
    home = home_model.load(state.graph)
    device = next((d for d in home.devices if find_name(name, [d.name]) is not None), None)
    if device is None:
        return None
    ids = {s.entity_id for s in device.sensors if s.role is Role.POWER_CONSUMED}
    readings = [
        e
        for e in state.ingestor.status().entities
        if e.entity_id in ids and e.last_value is not None and e.last_time is not None
    ]
    if not readings:
        return None
    now = datetime.now(UTC)
    # HA n'envoie un relevé qu'au changement : une puissance figée depuis longtemps est un
    # appareil à l'arrêt (0 W depuis des heures) ou un capteur muet, pas une marche en cours.
    watts = sum(e.last_value for e in readings if now - e.last_time <= FRESH)
    texts = catalog(language(state))
    if watts >= RUNNING_W:
        return texts["assistant.running_now"].format(power=f"{round(watts)} W")
    return texts["assistant.off_now"]


def _others(view: DayView, name: str, lang: str) -> list[dict[str, Any]] | str:
    """Autres appareils qui tournent ce jour-là, pour « Et l'autre appareil ? » ; aucun : une
    phrase (un modèle prenait le premier équipement de la maison pour « l'autre appareil »)."""
    others = [
        {"device": r.device, "planned": _bars(r.planned)}
        for r in view.timeline.rows
        if r.device != name and r.kind != "battery" and r.planned
    ]
    return others or catalog(lang)["assistant.no_other"]


async def _not_planned(state: Any, device: str, day: date) -> dict[str, Any]:
    """Équipement absent du plan de ce jour : s'il est dans la maison, il n'est simplement pas
    prévu (rien de demandé ni d'échu) ; on dit quand l'horizon le place et s'il peut être
    demandé. Sinon, équipement inconnu."""
    home = home_model.load(state.graph)
    name = find_name(device, [d.name for d in home.devices])
    if name is None:
        return {"error": "unknown_device", "hint": "Unknown appliance: ask the user which one."}
    # Textes dans la langue réglée et sans nom d'outil : les modèles les recopient tels quels.
    lang = language(state)
    texts = catalog(lang)
    today = today_of(state)
    # Sans « scheduled: false », que la raison dit déjà : le champ était cité tel quel.
    found: dict[str, Any] = {
        "device": name,
        "day": _when(day, today, lang),
        "reason": texts["assistant.not_planned"],
    }
    week = await week_view_of(state, language(state))
    for other in week.days if week else []:
        if other.day <= day:
            continue
        slot = next((p for p in other.devices if find_name(p.device, [name]) is not None), None)
        if slot is not None:
            found["next_planned"] = {
                "day": _when(other.day, today, lang),
                "start": clock(slot.start_min / 60),
                "end": clock(slot.end_min / 60),
            }
            break
    requestable = cycle_appliances(home, configuration.load(state.graph))
    if any(a.name == name for a in requestable):
        found["hint"] = texts["assistant.can_request"]
    return found


def _when(day: date, today: date, lang: str) -> str:
    """« aujourd'hui », « demain », « hier », sinon la date en toutes lettres."""
    texts = catalog(lang)
    near = {0: "today", 1: "tomorrow", -1: "yesterday"}.get((day - today).days)
    return texts[f"assistant.{near}"] if near else long_date(day, lang)


def _moment(moment: datetime, state: Any, lang: str) -> str:
    """Jour en mots et heure locale : « aujourd'hui 05:12 »."""
    local = moment.astimezone(state.raw.zone)
    return f"{_when(local.date(), today_of(state), lang)} {local:%H:%M}"


def _forecast_end(last: date, lang: str) -> str:
    """« Pas de prévision au-delà du Mardi 10 Novembre 2026. »"""
    return catalog(lang)["assistant.week_end"].format(date=long_date(last, lang))


async def get_week(state: Any) -> dict[str, Any]:
    lang = language(state)
    view = await week_view_of(state, lang)
    if view is None:
        return NO_PLAN
    today = today_of(state)
    # À partir de demain : avec aujourd'hui en tête, « le reste de la semaine » le comptait encore
    # (aujourd'hui est dans le plan du jour).
    days = [d for d in view.days if d.day > today]
    return {
        "today": long_date(today, lang),
        "days": [
            {
                # En mots seulement : avec la date, un modèle comptait encore aujourd'hui, et
                # une date au format brut était recopiée.
                # Demain avec sa date : avec « demain » seul, trois profils du banc en
                # déduisaient un faux jour (« Demain (jeu) » un jeudi).
                "when": (
                    f"{_when(d.day, today, lang)}, {long_date(d.day, lang)}"
                    if d.day == today + timedelta(days=1)
                    else _when(d.day, today, lang)
                ),
                "production_kwh": round(d.production_kwh, 1),
                # La qualité en toutes lettres seulement : « sunny » était recopié tel quel.
                **({"weather": WEATHER[lang][d.weather]} if d.weather else {}),
                # En phrase : avec « battery_end_of_day_percent: 12 », qwen3-4b-thinking écrivait
                # « la batterie se charge à 12 % chaque jour » (banc du 06/11).
                **(
                    {
                        "battery": catalog(lang)["assistant.battery_end_of_day"].format(
                            percent=_percent(d.soc_end_percent, lang)
                        )
                    }
                    if d.soc_end_percent is not None
                    else {}
                ),
                "bought_from_grid_kwh": round(d.grid_import_kwh, 2),
                "devices": [
                    {
                        "device": p.device,
                        "start": clock(p.start_min / 60),
                        "end": clock(p.end_min / 60),
                    }
                    for p in d.devices
                ],
                "warnings": [n.text for n in d.notices],
            }
            for d in days
        ],
        # Les prévisions s'arrêtent au dernier jour : sans le dire, « dans 10 jours » donnait
        # les sept jours connus, ou « seulement aujourd'hui et demain ».
        **({"forecast_end": _forecast_end(view.days[-1].day, lang)} if view.days else {}),
        "warnings": [n.text for n in view.notices],
    }


async def get_current_status(state: Any) -> dict[str, Any]:
    ingestor = state.ingestor
    if ingestor is None:
        return {"error": "not_connected", "hint": "Home Assistant is not connected."}
    home = home_model.load(state.graph)
    names = {sensor.entity_id: device.name for device in home.devices for sensor in device.sensors}
    now = datetime.now(UTC)
    # HA n'envoie un relevé qu'au changement : un niveau de charge stable reste valable, une
    # puissance figée depuis longtemps vient d'un capteur muet (panneaux la nuit…).
    fresh = [
        e
        for e in ingestor.status().entities
        if e.role in NOW_ROLES
        and e.last_value is not None
        and e.last_time is not None
        and (e.role is Role.STATE_OF_CHARGE or now - e.last_time <= FRESH)
    ]
    found: dict[str, Any] = {}
    # Phrase « En ce moment » de Planning (lot 6b.3) : qui alimente la maison, au dernier quart
    # d'heure clos.
    view = await day_view_of(state, "today", language(state))
    if view is not None and view.now is not None and view.now.sentence:
        found["now"] = view.now.sentence
        found["off_peak"] = view.now.off_peak
    # Un résumé plutôt que tous les relevés (~2 000 tokens, heures en UTC) : le niveau de la
    # batterie s'y cherchait sous le nom de l'appareil.
    levels = {e.entity_id: e.last_value for e in fresh if e.role is Role.STATE_OF_CHARGE}
    batteries = [
        (device, levels[sensor.entity_id])
        for device in home.devices
        if device.kind is DeviceKind.BATTERY
        for sensor in device.sensors
        if sensor.role is Role.STATE_OF_CHARGE and sensor.entity_id in levels
    ]
    if batteries:
        # Plusieurs batteries : leur moyenne pondérée par la capacité, comme l'écran Aujourd'hui
        # et le calcul ; sans capacité connue, leur moyenne simple.
        weights = [device.capacity_kwh or 0.0 for device, _ in batteries]
        if any(weight <= 0 for weight in weights):
            weights = [1.0] * len(batteries)
        total = sum(w * level for w, (_, level) in zip(weights, batteries, strict=True))
        found["battery_percent"] = round(total / sum(weights))
        if len(batteries) > 1:
            lang = language(state)
            found["batteries"] = [
                {"name": device.name, "charge": _percent(level, lang)}
                for device, level in batteries
            ]
    elif levels:
        found["battery_percent"] = round(sum(levels.values()) / len(levels))
    solar = [e.last_value for e in fresh if e.role is Role.POWER_PRODUCED]
    if solar:
        found["solar_power_w"] = round(sum(solar))
    running = sorted(
        (
            (names.get(e.entity_id, e.entity_id), round(e.last_value))
            for e in fresh
            if e.role is Role.POWER_CONSUMED and e.last_value >= RUNNING_W
        ),
        key=lambda r: -r[1],
    )
    found["appliances_on"] = [{"device": d, "power_w": w} for d, w in running]
    if fresh:
        latest = max(e.last_time for e in fresh if e.last_time is not None)
        found["measured_at"] = latest.astimezone(state.raw.zone).strftime("%H:%M")
    return found


# Totaux mesurés tirés des compteurs d'énergie de la maison, par rôle. « acheté », « revendu » :
# un modèle a lu « grid_import » comme de l'énergie injectée.
TOTALS = {
    Role.ENERGY_PRODUCED: "production_kwh",
    Role.ENERGY_IMPORTED: "bought_from_grid_kwh",
    Role.ENERGY_EXPORTED: "sold_to_grid_kwh",
    Role.ENERGY_CHARGED: "battery_charge_kwh",
    Role.ENERGY_DISCHARGED: "battery_discharge_kwh",
}


def day_of(state: Any, day: str) -> date | None:
    """« today », « yesterday » ou une date AAAA-MM-JJ, dans le fuseau de la maison."""
    today = datetime.now(state.raw.zone).date()
    if day == "today":
        return today
    if day == "yesterday":
        return today - timedelta(days=1)
    try:
        return date.fromisoformat(day)
    except ValueError:
        return None


def measured_energy(state: Any, day: date) -> dict[str, Any] | None:
    """Énergie mesurée d'un jour, tirée des agrégats horaires des compteurs (lot 1.3) : totaux
    par rôle, consommation de la maison par bilan, et par équipement mesuré. ``None`` sans
    agrégats (HA non connecté)."""
    aggregator = state.aggregator
    if aggregator is None:
        return None
    zone = state.raw.zone
    start = datetime.combine(day, time(), zone)
    end = datetime.combine(day + timedelta(days=1), time(), zone)
    totals: dict[str, float] = {}
    devices: dict[str, float] = {}
    for device in home_model.load(state.graph).devices:
        for sensor in home_model.counted_sensors(device):
            if sensor.role not in TOTALS and sensor.role is not Role.ENERGY_CONSUMED:
                continue
            values = [
                a.energy_kwh
                for a in aggregator.read(sensor.entity_id, HOUR, start, end)
                if a.energy_kwh is not None
            ]
            if not values:
                continue
            kwh = sum(values)
            if sensor.role is Role.ENERGY_CONSUMED:
                devices[device.name] = devices.get(device.name, 0.0) + kwh
            else:
                key = TOTALS[sensor.role]
                totals[key] = totals.get(key, 0.0) + kwh
    if not totals and not devices:
        return {}
    found: dict[str, Any] = {key: round(value, 2) for key, value in totals.items()}
    if "production_kwh" in totals and "bought_from_grid_kwh" in totals:
        # Bilan de la maison : produit + acheté - injecté + rendu par la batterie - stocké.
        found["consumption_kwh"] = round(
            totals["production_kwh"]
            + totals["bought_from_grid_kwh"]
            - totals.get("sold_to_grid_kwh", 0.0)
            + totals.get("battery_discharge_kwh", 0.0)
            - totals.get("battery_charge_kwh", 0.0),
            2,
        )
    if devices:
        found["devices"] = {name: round(kwh, 2) for name, kwh in devices.items()}
    return found


async def get_energy(state: Any, day: str = "today") -> dict[str, Any]:
    """Énergie mesurée d'un jour (agrégats, n'importe quel jour gardé), et ce que prévoyait le
    plan quand il existe encore (aujourd'hui, hier)."""
    wanted = day_of(state, day)
    if wanted is None:
        return {"error": "invalid_date", "hint": "Use today, yesterday or YYYY-MM-DD."}
    if wanted > datetime.now(state.raw.zone).date():
        return {"error": "invalid_date", "hint": "The day is in the future: see get_forecast."}
    measured = measured_energy(state, wanted)
    view = None
    for kind in ("today", "yesterday"):
        found = await day_view_of(state, kind, language(state))
        if found is not None and found.day == wanted:
            view = found
            break
    if not measured and view is None:
        return {
            "error": "no_data",
            "hint": "No measurement kept for this day, and no plan.",
        }
    lang = language(state)
    today = today_of(state)
    result: dict[str, Any] = {
        "day": _when(wanted, today, lang),
        "measured": _energy_texts(measured, lang) if measured else None,
    }
    if view is None:
        return result
    production = round(sum(h.production_kwh for h in view.hours), 2)
    consumption = round(sum(h.consumption_kwh for h in view.hours), 2)
    devices = {
        row.device: round(sum(b.energy_kwh for b in row.planned), 2)
        for row in view.timeline.rows
        if row.kind != "battery"
    }
    if measured:
        result["planned"] = _energy_texts(
            {"production_kwh": production, "consumption_kwh": consumption, "devices": devices},
            lang,
        )
        return result
    # Rien de mesuré (tôt le matin, ou sans HA) : en phrases, « prévu » collé aux chiffres. Avec
    # les champs du plan à côté d'un « measured » vide, les quatre modèles du banc d'essai
    # répondaient « la maison a consommé 9,69 kWh » à 0 h 30.
    texts = catalog(lang)
    result["measured"] = texts[
        "assistant.no_measure_today" if wanted == today else "assistant.no_measure_day"
    ]
    result["planned"] = texts["assistant.planned_not_measured"].format(
        consumption=number(consumption, lang, 2), production=number(production, lang, 2)
    )
    if devices:
        result["planned_appliances_kwh"] = _energy_texts(devices, lang)
    return result


def _energy_texts(values: dict[str, Any], lang: str) -> dict[str, Any]:
    """Énergies au format de la langue, unité comprise (« 0,89 kWh ») : avec les nombres bruts,
    les modèles du banc recopiaient « 0.89 kWh » en français (banc du 06/11)."""
    return {
        key: _energy_texts(value, lang)
        if isinstance(value, dict)
        else f"{number(value, lang, 2)}\u00a0kWh"
        for key, value in values.items()
    }


async def get_forecast(state: Any, day: str = "today") -> dict[str, Any]:
    """Prévision d'un jour : heure par heure aujourd'hui et demain, la journée ensuite, et la fin
    des prévisions au-delà. Avec « today » ou « tomorrow » seulement, qwen3 répondait « je ne
    vois que deux jours » à « dans 10 jours », sans chercher plus loin."""
    lang = language(state)
    today = today_of(state)
    relative = {"today": today, "tomorrow": today + timedelta(days=1)}
    asked = day.strip().lower()
    try:
        if asked.lstrip("+").isdigit():
            # Un nombre de jours à partir d'aujourd'hui : le modèle ne connaît pas la date du
            # jour, et à « dans 10 jours » qwen3 refusait sans appeler l'outil (banc du 06/11).
            wanted = today + timedelta(days=int(asked.lstrip("+")))
        else:
            wanted = relative.get(asked) or date.fromisoformat(asked)
    except (ValueError, OverflowError):
        return {
            "error": "invalid_date",
            "hint": "Use today, tomorrow, a number of days from today or YYYY-MM-DD; "
            f"today is {today.isoformat()}.",
        }
    if wanted < today:
        # La date du jour et la fin de la prévision : à « dans 10 jours », qwen3.5 demandait une
        # date de 2025 ; renvoyé seulement vers l'énergie mesurée, il donnait celle d'août 2025.
        past: dict[str, Any] = {
            "error": "invalid_date",
            "hint": f"{wanted.isoformat()} is past; today is {today.isoformat()}. "
            "Measured energy of a past day: get_energy.",
        }
        week = await week_view_of(state, lang)
        if week is not None and week.days:
            past["forecast_end"] = _forecast_end(week.days[-1].day, lang)
        return past
    if wanted > today + timedelta(days=1):
        return await _later_forecast(state, wanted, today, lang)
    return await _hourly_forecast(state, "today" if wanted == today else "tomorrow")


async def _later_forecast(state: Any, wanted: date, today: date, lang: str) -> dict[str, Any]:
    """Après demain : la journée telle que l'horizon la prévoit, ou la fin des prévisions."""
    week = await week_view_of(state, lang)
    if week is None or not week.days:
        return NO_PLAN
    found = next((d for d in week.days if d.day == wanted), None)
    if found is None:
        return {
            "day": _when(wanted, today, lang),
            "forecast_end": _forecast_end(week.days[-1].day, lang),
        }
    return {
        "day": _when(wanted, today, lang),
        "production_kwh": round(found.production_kwh, 1),
        **({"weather": WEATHER[lang][found.weather]} if found.weather else {}),
    }


async def _hourly_forecast(state: Any, day: Day) -> dict[str, Any]:
    view = await day_view_of(state, day, language(state))
    if view is None:
        return NO_PLAN
    when = _when(view.day, today_of(state), language(state))
    if not view.solar:  # maison sans installation solaire (lot 7.4)
        return {"day": when, "solar_installation": False, "production_kwh": 0}
    lang = language(state)
    producing = [h for h in view.hours if h.production_kwh]
    peak = max(producing, key=lambda h: h.production_kwh, default=None)
    kwh = round(view.weather.production_kwh, 1)
    # Le résumé en une phrase, avant le détail : un modèle recopiait les onze heures une à une ;
    # avec des champs « production_hours » et « peak_hour », qwen3 lisait les heures de
    # production comme celles du maximum, et lfm3-rapide détaillait les heures sans le total.
    summary = (
        catalog(lang)["assistant.forecast_summary"].format(
            kwh=number(kwh, lang, 1),
            start=clock(producing[0].hour),
            end=clock(producing[-1].hour + 1),
            peak_start=clock(peak.hour),
            peak_end=clock(peak.hour + 1),
        )
        if peak is not None
        else None
    )
    return {
        "day": when,
        **({"summary": summary} if summary else {}),
        "production_kwh": kwh,
        **({"weather": WEATHER[lang][view.weather.quality]} if view.weather.quality else {}),
        "hourly_kwh": {f"{h.hour:02d}:00": round(h.production_kwh, 2) for h in producing},
    }


def get_home(state: Any) -> dict[str, Any]:
    home = home_model.load(state.graph)
    saved = configuration.load(state.graph)
    settings = {d.key: d for d in configuration.effective(home, saved).devices}
    house_battery = configuration.battery_of(saved)
    tariff = configuration.tariff_of(saved)
    three_phase = home.supply is Supply.THREE
    meter = "sums" if home.meter_sums_phases else "separate"
    lang = language(state)
    texts = catalog(lang)
    preset = objective_of(state, saved).value
    # Groupes par rôle dans le plan plutôt que les codes de la configuration : « scheduled »
    # valait vrai pour tout (même le réseau), d'où « tous les équipements sont planifiés ».
    groups: dict[str, list[Any]] = {key: [] for key in HOME_GROUPS}
    phases: dict[str, str] = {}  # maison en triphasé : phase de chaque équipement qui en a une
    for d in home.devices:
        setting = settings.get(d.key)
        behavior = setting.behavior if setting else Behavior.UNCONTROLLED
        if three_phase and d.phase is not None and behavior is not Behavior.UNCONTROLLED:
            phases[d.name] = _phase(d.phase, texts)
        if behavior is Behavior.STORAGE:
            # Valeurs écrites dans la langue réglée (« 5,12 kWh ») et réserve nommée pour ce
            # qu'elle est : « floor_percent: 12.0 » se lisait « 12.0 % d'espace ».
            groups["batteries"].append(
                {
                    "name": d.name,
                    **(
                        {"capacity": f"{number(d.capacity_kwh, lang, 2)}\u00a0kWh"}
                        if d.capacity_kwh
                        else {}
                    ),
                    # Ses propres réglages, sinon ceux de la maison.
                    "never_below": _percent(
                        ((setting.battery if setting else None) or house_battery).floor_percent,
                        lang,
                    ),
                }
            )
        elif behavior in MANAGED:
            key = "placed_by_wattslot" if setting and setting.planned else "excluded_from_planning"
            groups[key].append(d.name)
        else:
            groups[HOME_GROUP_OF.get(behavior, "other_loads")].append(d.name)
    # Les autres charges mesurées en nombre seulement : leur liste, souvent longue, était
    # recopiée en entier (16 s de réponse) et la batterie oubliée.
    others = groups.pop("other_loads")
    return {
        # En tête : à « Et l'autre appareil ? », qwen3 prenait le premier de la liste pour prévu.
        "about": texts["assistant.home_about"],
        **{key: values for key, values in groups.items() if values},
        **(
            {"other_loads": texts["assistant.other_loads"].format(count=len(others))}
            if others
            else {}
        ),
        "tariff": texts[f"assistant.tariff.{tariff.kind.value}"],
        "objective": texts[f"objective.{OBJECTIVE_TEXT.get(preset, preset)}"],
        # Maison en triphasé seulement : en monophasé, rien de plus à dire.
        **(
            {
                "grid_connection": {
                    "supply": texts["assistant.supply.three_phase"],
                    "meter": texts[f"assistant.meter.{meter}"],
                    **(
                        {
                            "limit": texts["assistant.phase_limit"].format(
                                kva=number(tariff.contract_kva / 3, lang, 1)
                            )
                        }
                        if tariff.contract_kva
                        else {}
                    ),
                },
                **({"connected_to": phases} if phases else {}),
            }
            if three_phase
            else {}
        ),
    }


def _phase(phase: Phase, texts: dict[str, str]) -> str:
    """« phase 2 », ou « les trois phases » pour un équipement triphasé."""
    if phase is Phase.ALL:
        return texts["assistant.all_phases"]
    return texts["assistant.phase"].format(number=LINES.index(phase) + 1)


def _fill(template: str, params: dict[str, str]) -> str:
    """« {device} : … » complété ; un paramètre absent laisse un vide, comme l'interface."""
    return re.sub(r"\{(\w+)\}", lambda m: params.get(m.group(1), ""), template)


RESOURCE_CODES = {"disk_low", "backup_space", "memory_high", "memory_heavy"}


def problem_text(code: str, params: dict[str, str], lang: str) -> str:
    """Phrase d'un problème, comme l'écran Diagnostic (``ProblemsSection``), avec les textes de
    l'interface copiés dans les catalogues du serveur (``problem.*``)."""
    texts = catalog(lang)
    params = dict(params)
    issue = params.pop("issue", "")
    if code == "configuration_issue":
        return _fill(texts.get(f"problem.configuration_issue.{issue}", issue), params)
    if code == "energy_dashboard_issue":
        detail = _fill(texts.get(f"problem.issue.{issue}", issue), params)
        return _fill(texts["problem.code.energy_dashboard_issue"], {**params, "issue": detail})
    if code in ("impossible_data", "impossible_data_unknown"):
        hour = texts["problem.hour"]
        params.update(
            day=long_date(params.get("day", ""), lang),
            hour=_fill(hour, {"hour": params.get("hour", "")}),
            kwh=number(float(params.get("kwh", 0)), lang, 0),
            limit=number(float(params.get("limit", 0)), lang, 1),
        )
        if code == "impossible_data":
            params.update(
                when=long_date(params.get("when", ""), lang),
                when_hour=_fill(hour, {"hour": params.get("when_hour", "")}),
                source_kwh=number(float(params.get("source_kwh", 0)), lang, 0),
                until=long_date(params.get("until", ""), lang),
            )
    # Ressources : nombres bruts du serveur, écrits dans la langue réglée.
    for key, digits in (("free", 1), ("needed", 1), ("used", 0)):
        if code in RESOURCE_CODES and params.get(key):
            params[key] = number(float(params[key]), lang, digits)
    if "error_code" in params:
        error = params.pop("error_code")
        params["error"] = texts.get(
            f"problem.connection_error.{error}", texts["problem.connection_error.unknown"]
        )
    if "role" in params:
        params["role"] = texts.get(f"problem.role.{params['role']}", params["role"])
    if "component" in params:
        params["component"] = texts.get(
            f"problem.component.{params['component']}", params["component"]
        )
    return _fill(texts.get(f"problem.code.{code}", code), params).strip()


async def get_problems(
    state: Any, problems: Callable[[], Awaitable[Sequence[Any]]]
) -> dict[str, Any]:
    """Problèmes en phrases, avec leur gravité et le geste à faire, dans la langue réglée : avec
    les codes et leurs paramètres, un modèle aurait recopié « sensor_silent »."""
    found = await problems()
    lang = language(state)
    texts = catalog(lang)
    if not found:
        return {"problems": texts["problem.none"]}
    return {
        "problems": [
            {
                "severity": texts[f"problem.severity.{p.severity.value}"],
                "problem": problem_text(p.code, p.params, lang),
                **(
                    {"what_to_do": texts[f"problem.action.{p.code}"]}
                    if f"problem.action.{p.code}" in texts
                    else {}
                ),
            }
            for p in found
        ]
    }


def _pending(state: Any) -> dict[tuple[str, date | None], datetime]:
    """Questions posées par request_device et pas encore confirmées : (équipement, date limite)
    → moment de la question. En mémoire : une question ne survit pas à un redémarrage."""
    found: dict[tuple[str, date | None], datetime] | None = getattr(
        state, "assistant_pending", None
    )
    if found is None:
        found = {}
        state.assistant_pending = found
    return found


def request_device(
    state: Any, device: str, latest_date: str | None = None, confirm: bool = False
) -> dict[str, Any]:
    """Demande pour un équipement (lot 4.5), au plus tard ``latest_date`` (AAAA-MM-JJ) ; une
    demande déjà ouverte pour lui change seulement de date. Le calcul suivant la place.

    En deux temps : sans ``confirm``, rien n'est déposé, l'outil rend la question à poser et la
    retient ; la demande n'est déposée qu'avec ``confirm`` après cette question, et dans les
    ``PENDING_FOR`` qui suivent. Les deux modèles essayés déposaient la demande sans rien
    demander malgré la règle du prompt ; un code rendu avec la question était montré à
    l'utilisateur."""
    home = home_model.load(state.graph)
    requestable = cycle_appliances(home, configuration.load(state.graph))
    names = [a.name for a in requestable]
    name = find_name(device, names)
    if name is None:
        return {"error": "unknown_device", "devices": names}
    today = datetime.now(state.raw.zone).date()
    # « Avant demain soir » : les modèles passent « tomorrow » sans connaître la date du jour.
    relative = {"today": today, "tomorrow": today + timedelta(days=1)}
    latest = None
    if latest_date:
        try:
            latest = relative.get(latest_date.strip().lower()) or date.fromisoformat(latest_date)
        except ValueError:
            return {
                "error": "invalid_date",
                "hint": f"Use today, tomorrow or YYYY-MM-DD; today is {today.isoformat()}.",
            }
        if latest < today:
            return {
                "error": "invalid_date",
                "hint": f"The date is in the past; today is {today.isoformat()}.",
            }
    key = next(a.key for a in requestable if a.name == name)
    now = datetime.now(UTC)
    pending = _pending(state)
    if not confirm:
        pending[(key, latest)] = now
        lang = language(state)
        texts = catalog(lang)
        question = (
            texts["assistant.request_by"].format(device=name, date=long_date(latest, lang))
            if latest
            else texts["assistant.request"].format(device=name)
        )
        return {
            "device": name,
            "latest_date": latest.isoformat() if latest else None,
            "filed": False,
            "question": question,
            "next": "Nothing filed yet. Ask the user this question as it is. Only if they agree, "
            "call again with the same device and latest_date and confirm true.",
        }
    asked = pending.pop((key, latest), None)
    if asked is None or now - asked > PENDING_FOR:
        return {
            "error": "not_asked",
            "hint": "Nothing filed. Call request_device without confirm, ask the user the "
            "question it returns and wait for their answer.",
        }
    found = user_requests.ask(state.database, key, latest, now)
    return {
        "device": name,
        "latest_date": found.latest.isoformat() if found.latest else None,
        "filed": True,
        "status": found.status.value,
        "note": "Filed. The next computation of the plan places it at the best time.",
    }


def get_requests(state: Any) -> dict[str, Any]:
    """Demandes ouvertes, puis celles closes depuis une semaine, comme « Mes demandes ». État
    et jours en mots : « cancelled » et les dates au format brut étaient recopiés. Ouvertes et
    closes à part, avec une phrase quand aucune n'est ouverte : dans une seule liste, les trois
    modèles essayés présentaient les demandes annulées ou faites comme « en cours »."""
    names = {d.key: d.name for d in home_model.load(state.graph).devices}
    lang = language(state)
    texts = catalog(lang)
    today = today_of(state)
    found = user_requests.recent(state.database, datetime.now(UTC))

    def described(r: user_requests.UserRequest) -> dict[str, Any]:
        return {
            "device": names.get(r.device, r.device),
            **(
                {"status": texts[f"assistant.request_status.{r.status.value}"]}
                if r.status is not user_requests.Status.OPEN
                else {}
            ),
            "asked_on": _when(r.created_at.astimezone(state.raw.zone).date(), today, lang),
            "latest_date": _when(r.latest, today, lang) if r.latest else None,
            **({"launched_on": _when(r.launched_on, today, lang)} if r.launched_on else {}),
        }

    opened = [described(r) for r in found if r.status is user_requests.Status.OPEN]
    closed = [described(r) for r in found if r.status is not user_requests.Status.OPEN]
    return {
        "open": opened or texts["assistant.no_open_request"],
        **({"closed_this_week": closed} if closed else {}),
    }


async def _tariff_context(state: Any, tariff: Tariff, today: date) -> TariffContext:
    """Couleur des jours et prix publiés, lus dans HA comme pour le calcul ; sans HA, aucun."""
    client = getattr(state, "home_assistant", None)
    if not needs_states(tariff) or client is None:
        return NO_CONTEXT
    if client.status.state is not ConnectionState.CONNECTED:
        return NO_CONTEXT
    try:
        states = await client.command("get_states")
    except Exception:  # noqa: BLE001 — HA injoignable à cet instant : prix saisis seulement
        return NO_CONTEXT
    return tariff_context(tariff, states or [], today, state.raw.zone)


def _price_ranges(
    prices: dict[int, float], lang: str, periods: bool = False
) -> list[dict[str, str]]:
    """Heures consécutives au même prix, réunies : 00:00-06:00, « 0,210 €/kWh ». ``periods`` :
    chaque plage dit si elle est en heures creuses (moins chère que l'heure la plus chère, comme
    ``off_peak_ranges``) ou pleines ; avec les seules plages d'heures creuses à côté, un modèle a
    appelé « heures creuses » la plage la plus chère."""
    ranges: list[tuple[int, int, float]] = []
    for hour in range(24):
        if ranges and ranges[-1][2] == prices[hour]:
            ranges[-1] = (ranges[-1][0], hour + 1, prices[hour])
        else:
            ranges.append((hour, hour + 1, prices[hour]))
    texts = catalog(lang)
    top = max(prices.values())
    labelled = periods and len(ranges) > 1
    return [
        {
            "start": clock(start),
            "end": clock(end),
            "price": currency.per_kwh(price, lang),
            **(
                {"period": texts[f"assistant.period.{'off_peak' if price < top else 'peak'}"]}
                if labelled
                else {}
            ),
        }
        for start, end, price in ranges
    ]


async def get_tariff(state: Any, day: Literal["today", "tomorrow"] = "today") -> dict[str, Any]:
    """Prix du kWh par plage horaire, heures creuses, couleur du jour (Tempo) ; prix de revente
    quand il y en a un."""
    lang = language(state)
    tariff = configuration.tariff_of(configuration.load(state.graph))
    today = today_of(state)
    wanted = today + timedelta(days=1) if day == "tomorrow" else today
    context = await _tariff_context(state, tariff, today)
    found: dict[str, Any] = {
        "day": _when(wanted, today, lang),
        "tariff": catalog(lang)[f"assistant.tariff.{tariff.kind.value}"],
        # Heures creuses et pleines des tarifs par plages (Tempo compris) ; un prix dynamique n'a
        # que des heures moins chères que la plus chère, pas d'heures creuses à proprement parler.
        "prices": _price_ranges(
            tariff.hourly(wanted, context), lang, tariff.kind is not TariffKind.DYNAMIC
        ),
        "off_peak": [
            {"start": clock(start), "end": clock(end)}
            for start, end in off_peak_ranges(tariff, wanted, context)
        ],
    }
    if tariff.kind is TariffKind.DAY_COLOR:
        found["color"] = context.colors.get(wanted)  # aucune : pas encore annoncée
        if found["color"] is None:
            found["note"] = "Color of this day not announced yet: default prices shown."
    if tariff.kind is TariffKind.DYNAMIC and wanted not in context.prices:
        found["note"] = "Prices of this day not published yet: default price shown."
    export = tariff.export_hourly(wanted, context)
    if any(export.values()):
        found["export_prices"] = _price_ranges(export, lang)
    return found
