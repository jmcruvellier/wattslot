// Onglet « Bibliothèque » (lot 2t.2, designer d'ontologie) : les types de la bibliothèque
// « Énergie domestique » (comportements permis, rôles attendus de leurs capteurs) et les types
// propres à l'installation, sous-types de l'un d'eux (création, renommage, suppression).

import { useEffect, useState } from "react";

import { ApiError, getJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import type { DeviceKind, DeviceType, DeviceTypes } from "../home/types";

type Load = { status: "loading" } | { status: "ready"; types: DeviceTypes } | { status: "error" };
type Message = "created" | "renamed" | "deleted" | "in_use" | "invalid" | "failed" | null;

async function send(method: string, url: string, body?: unknown): Promise<void> {
  const response = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new ApiError(response.status);
}

export default function LibraryScreen() {
  const { t } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [message, setMessage] = useState<Message>(null);
  const [name, setName] = useState("");
  const [parent, setParent] = useState<DeviceKind | "">("");
  const [names, setNames] = useState<Record<string, string>>({});
  const [version, setVersion] = useState(0); // relit les types après chaque modification

  useEffect(() => {
    const controller = new AbortController();
    getJson<DeviceTypes>("api/home/types", controller.signal)
      .then((types) => {
        setLoad({ status: "ready", types });
        setNames(Object.fromEntries(types.types.map((own) => [own.key, own.name])));
      })
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, [version]);

  const act = async (done: Message, action: () => Promise<void>) => {
    try {
      await action();
      setMessage(done);
      setVersion((count) => count + 1);
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 0;
      setMessage(status === 409 ? "in_use" : status === 422 ? "invalid" : "failed");
    }
  };

  if (load.status === "loading") return <p>{t("library.loading")}</p>;
  if (load.status === "error") return <p role="alert">{t("library.error")}</p>;
  const { library, parents, types } = load.types;

  return (
    <section aria-labelledby="library-title">
      <h2 className="visually-hidden" id="library-title">{t("library.title")}</h2>
      <p>{t("library.intro")}</p>

      <h3>{t("library.library_types")}</h3>
      <table>
        <thead>
          <tr>
            <th>{t("library.type")}</th>
            <th>{t("library.behaviors")}</th>
            <th>{t("library.roles")}</th>
          </tr>
        </thead>
        <tbody>
          {library.map((type) => (
            <tr key={type.kind}>
              <th scope="row">{t(`kind.${type.kind}`)}</th>
              <td>{type.behaviors.map((b) => t(`behavior.${b}`)).join(", ")}</td>
              <td>{type.roles.map((r) => t(`role.${r}`)).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>{t("library.own_types")}</h3>
      <p>{t("library.own_intro")}</p>
      {types.length === 0 && <p>{t("library.none")}</p>}
      <ul>
        {types.map((own: DeviceType) => (
          <li key={own.key} aria-label={own.name}>
            <label>
              {t("library.name")}{" "}
              <input
                value={names[own.key] ?? own.name}
                onChange={(event) => setNames({ ...names, [own.key]: event.target.value })}
              />
            </label>{" "}
            {t("library.parent_of", { parent: t(`kind.${own.parent}`) })}{" "}
            <button
              type="button"
              disabled={!(names[own.key] ?? "").trim() || names[own.key] === own.name}
              onClick={() =>
                void act("renamed", () =>
                  send("PATCH", `api/home/types/${own.key}`, { name: names[own.key] }),
                )
              }
            >
              {t("library.rename")}
            </button>{" "}
            <button
              type="button"
              onClick={() => void act("deleted", () => send("DELETE", `api/home/types/${own.key}`))}
            >
              {t("library.delete")}
            </button>
          </li>
        ))}
      </ul>

      <form
        aria-label={t("library.create")}
        onSubmit={(event) => {
          event.preventDefault();
          void act("created", async () => {
            await send("POST", "api/home/types", { name, parent });
            setName("");
            setParent("");
          });
        }}
      >
        <label>
          {t("library.name")}{" "}
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>{" "}
        <label>
          {t("library.parent")}{" "}
          <select value={parent} onChange={(event) => setParent(event.target.value as DeviceKind)}>
            <option value="">{t("library.choose")}</option>
            {parents.map((kind) => (
              <option key={kind} value={kind}>
                {t(`kind.${kind}`)}
              </option>
            ))}
          </select>
        </label>{" "}
        <button type="submit" disabled={!name.trim() || !parent}>
          {t("library.create")}
        </button>
      </form>
      {message && (
        <p role={["in_use", "invalid", "failed"].includes(message) ? "alert" : "status"}>
          {t(`library.messages.${message}`)}
        </p>
      )}
    </section>
  );
}
