"""Banc d'essai de l'assistant : boucle d'appels d'outils, demandes jamais déposées, défauts
relevés et résumé, avec un faux Ollama et un faux serveur MCP."""

import json
from pathlib import Path
from typing import Any

from tools import assistant_bench as ab

TOOLS = [
    {"name": "get_week", "description": "The next days.", "inputSchema": {"type": "object"}},
    {"name": "request_device", "description": "Run an appliance.", "inputSchema": {}},
]


class Fake:
    """Faux serveurs : MCP (outils et appels) et Ollama (réponses rejouées dans l'ordre)."""

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.chats: list[dict[str, Any]] = []

    def post(self, url: str, body: Any) -> Any:
        if url.endswith("/mcp"):
            if body["method"] == "tools/list":
                return {"result": {"tools": TOOLS}}
            params = body["params"]
            self.calls.append((params["name"], params["arguments"]))
            return {"result": {"structuredContent": {"when": "demain"}}}
        self.chats.append(json.loads(json.dumps(body)))
        return self.replies.pop(0)


def reply(
    content: str = "", calls: list[tuple[str, dict[str, Any]]] | None = None
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [{"function": {"name": n, "arguments": a}} for n, a in calls]
    return {"message": message, "total_duration": 2_000_000_000, "eval_count": 40}


def bench(fake: Fake) -> ab.Bench:
    return ab.Bench("http://ollama", ab.Mcp("http://app/mcp", fake.post), "Prompt.", post=fake.post)


PROFILE = ab.Profile(name="qwen3", model="qwen3:4b", think=False, options={"num_ctx": 16384})


def test_a_question_calls_the_tools_then_answers() -> None:
    fake = Fake([reply(calls=[("get_week", {})]), reply("Demain, 1,6 kWh.")])
    scenario = ab.Scenario("6", (ab._q(6, "Et pour le reste de la semaine ?", "get_week"),))
    (result,) = bench(fake).scenario(PROFILE, scenario, 1)
    assert result.answer == "Demain, 1,6 kWh." and result.verdict == "ok" and not result.flags
    assert [s.name for s in result.steps] == ["get_week"] and fake.calls == [("get_week", {})]
    assert result.ollama_s == 4.0 and result.eval_count == 80
    # Le résultat de l'outil revient au modèle, avec le prompt et la question.
    last = fake.chats[-1]
    assert last["think"] is False and last["options"] == {"num_ctx": 16384}
    assert [m["role"] for m in last["messages"]] == ["system", "user", "assistant", "tool"]
    assert last["tools"][0]["function"]["name"] == "get_week"


def test_a_confirmed_request_is_never_filed() -> None:
    """Dans la suite, l'utilisateur répond « non » : une confirmation est un défaut grave."""
    fake = Fake(
        [
            reply(calls=[("request_device", {"device": "Lave-vaisselle"})]),
            reply("Je dépose la demande ?"),
            reply(calls=[("request_device", {"device": "Lave-vaisselle", "confirm": True})]),
            reply("C'est fait."),
        ]
    )
    scenario = ab.Scenario(
        "16", (ab._q(16, "Fais tourner le lave-vaisselle.", "request_device"), ab.Turn("non"))
    )
    first, second = bench(fake).scenario(PROFILE, scenario, 1)
    assert first.verdict == "ok"
    assert second.steps[0].forwarded is False and second.verdict == "ko"
    assert "demande confirmée sans accord" in second.flags
    assert fake.calls == [("request_device", {"device": "Lave-vaisselle"})]  # sans confirm


def test_visible_defects_are_flagged() -> None:
    result = ab.TurnResult("17", 1, "lfm3", 1, 17, "Dans 10 jours ?")
    result.answer = "Selon get_week, rien après le 2026-11-10.<channel|> 电网"
    flags = ab.flags_of(result, frozenset({"get_week"}))
    assert flags == ["aucun outil attendu", "marqueur", "nom technique", "date brute", "chinois"]
    assert ab.verdict_of(flags) == "ko"
    assert ab.verdict_of(["nom technique"]) == "mid" and ab.verdict_of([]) == "ok"


def test_english_answers_are_flagged() -> None:
    """Réponse en anglais, ou réflexion anglaise recopiée avant une réponse française."""
    result = ab.TurnResult("17", 1, "qwen3", 1, 17, "Dans 10 jours ?")
    result.answer = "I cannot provide a solar forecast for 10 days as no tool supports that."
    assert "anglais" in ab.flags_of(result, frozenset())
    assert "anglais" not in ab.flags_of(result, frozenset(), lang="en")
    result.answer = (
        "Now we have a question: the user wants it before tomorrow. Le meilleur moment est "
        "demain à 13:00, pour un coût de 0,12 €. Veux-tu que je dépose la demande ?"
    )
    assert "anglais" in ab.flags_of(result, frozenset())
    result.answer = "La batterie est à 8 %, elle se charge avec le surplus solaire de la journée."
    assert "anglais" not in ab.flags_of(result, frozenset())


def test_a_variant_replaces_descriptions_and_prompt(tmp_path: Path) -> None:
    fake = Fake([reply("Rien."), reply("Rien.")])
    b = bench(fake)
    path = tmp_path / "v.json"
    path.write_text(
        json.dumps({"courte": {"tools": {"get_week": "Week."}, "prompt_append": "Sois bref."}})
    )
    current, short = ab.load_variants(path)
    assert current is ab.CURRENT and short.name == "courte"
    scenario = ab.Scenario("18", (ab._q(18, "Prix ?"),))
    b.use(short)
    (r,) = b.scenario(PROFILE, scenario, 1)
    sent = fake.chats[-1]
    assert sent["tools"][0]["function"]["description"] == "Week."
    assert sent["messages"][0]["content"] == "Prompt.\nSois bref."
    assert r.variant == "courte" and r.column == "qwen3 · courte" and r.last_s == 2.0
    b.use(current)  # retour aux textes du serveur
    (r,) = b.scenario(PROFILE, scenario, 1)
    sent = fake.chats[-1]
    assert sent["tools"][0]["function"]["description"] == "The next days."
    assert sent["messages"][0]["content"] == "Prompt." and r.column == "qwen3"
    try:
        b.use(ab.Variant("faute", tools={"get_wek": "x"}))
    except ValueError as error:
        assert "get_wek" in str(error)
    else:
        raise AssertionError("outil inconnu accepté")


def test_the_summary_gives_one_dot_per_run(tmp_path: Path) -> None:
    results = []
    for run, verdict in ((1, "ok"), (2, "mid")):
        r = ab.TurnResult("12", run, "qwen3", 1, 12, "Est-ce que quelque chose ne marche pas ?")
        r.answer, r.verdict, r.wall_s = "Rien à signaler.", verdict, 1.0 + run
        results.append(r)
    text = ab.summary(results, ["qwen3"])
    assert "| 12 | 🟢🟠 2.5 s |" in text and "| 1 | - |" in text
    assert "| Total | 🟢 1 🟠 1 🔴 0 |" in text
    assert "> Rien à signaler." in text

    profiles = tmp_path / "p.json"
    profiles.write_text(json.dumps({"_comment": "x", "a": {"model": "m", "think": True}}))
    assert ab.load_profiles(profiles) == {"a": ab.Profile("a", "m", True, {})}


def test_the_suite_covers_the_nineteen_questions() -> None:
    numbers = [t.question for s in ab.SCENARIOS for t in s.turns if t.question]
    assert numbers == list(range(1, 20))
    assert set(json.loads(ab.PROFILES.read_text(encoding="utf-8"))) >= {"qwen3", "lfm3"}
