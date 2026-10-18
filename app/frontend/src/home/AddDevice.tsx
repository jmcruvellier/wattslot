// Ajout d'un équipement absent du tableau Énergie de HA (lot 2t.2, « Ma maison ») : un nom, un
// type (de la bibliothèque ou propre) et, pour chaque capteur attendu de ce type, une entité de
// HA dont l'unité convient. L'équipement rejoint le brouillon ; « Enregistrer » le valide.

import { useState } from "react";

import { ApiError, getJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { MANUAL_PREFIX, slug, type DraftDevice } from "./draft";
import { DEVICE_KINDS, type DeviceKind, type DeviceType, type LibraryType, type Role } from "./types";

interface EntityChoice {
  entity_id: string;
  name: string | null;
  unit: string | null;
  roles: Role[];
}

type Entities = { status: "idle" | "loading" | "not_connected" | "failed" } | { status: "ready"; list: EntityChoice[] };

export default function AddDevice({ library, types, existing, onAdd }: {
  library: LibraryType[];
  types: DeviceType[];
  existing: string[]; // clés déjà prises
  onAdd: (device: DraftDevice) => void;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [entities, setEntities] = useState<Entities>({ status: "idle" });
  const [name, setName] = useState("");
  const [choice, setChoice] = useState<string>("OtherLoad");
  const [chosen, setChosen] = useState<Partial<Record<Role, string>>>({});

  const own = choice.startsWith("custom:") ? types.find((type) => type.key === choice.slice(7)) : undefined;
  const kind: DeviceKind = own ? own.parent : (choice as DeviceKind);
  const roles = library.find((type) => type.kind === kind)?.roles ?? [];

  const start = async () => {
    setOpen(true);
    setEntities({ status: "loading" });
    try {
      setEntities({ status: "ready", list: await getJson<EntityChoice[]>("api/home/entities") });
    } catch (error) {
      setEntities({ status: error instanceof ApiError && error.status === 503 ? "not_connected" : "failed" });
    }
  };

  const add = () => {
    const base = `${MANUAL_PREFIX}${slug(name) || "device"}`;
    let key = base;
    for (let n = 2; existing.includes(key); n += 1) key = `${base}-${n}`;
    const list = entities.status === "ready" ? entities.list : [];
    onAdd({
      key,
      included: true,
      kind,
      customType: own?.key ?? null,
      name: name.trim(),
      capacityKwh: null,
      capacitySource: null,
      issues: [],
      sensors: roles
        .filter((role) => chosen[role])
        .map((role) => {
          const entity = list.find((e) => e.entity_id === chosen[role]);
          return {
            entity_id: chosen[role] as string,
            role,
            name: entity?.name ?? null,
            unit: entity?.unit ?? null,
            resets_daily: false,
            excluded: false,
            issues: [],
            included: true,
          };
        }),
    });
    setOpen(false);
    setName("");
    setChosen({});
  };

  if (!open) {
    return (
      <button type="button" onClick={() => void start()}>
        {t("home.add.open")}
      </button>
    );
  }
  return (
    <fieldset aria-label={t("home.add.title")}>
      <legend>{t("home.add.title")}</legend>
      <p>{t("home.add.intro")}</p>
      <label>
        {t("home.name")} <input value={name} onChange={(event) => setName(event.target.value)} />
      </label>{" "}
      <label>
        {t("home.kind")}{" "}
        <select
          value={choice}
          onChange={(event) => {
            setChoice(event.target.value);
            setChosen({});
          }}
        >
          {DEVICE_KINDS.map((k) => (
            <option key={k} value={k}>
              {t(`kind.${k}`)}
            </option>
          ))}
          {types.map((type) => (
            <option key={type.key} value={`custom:${type.key}`}>
              {t("home.custom_kind", { name: type.name, parent: t(`kind.${type.parent}`) })}
            </option>
          ))}
        </select>
      </label>
      {entities.status === "loading" && <p>{t("home.add.loading")}</p>}
      {(entities.status === "not_connected" || entities.status === "failed") && (
        <p role="alert">{t(`home.add.${entities.status}`)}</p>
      )}
      {entities.status === "ready" && (
        <ul>
          {roles.map((role) => (
            <li key={role}>
              <label>
                {t(`role.${role}`)}{" "}
                <select
                  value={chosen[role] ?? ""}
                  onChange={(event) => setChosen({ ...chosen, [role]: event.target.value || undefined })}
                >
                  <option value="">{t("home.add.no_sensor")}</option>
                  {entities.list
                    .filter((entity) => entity.roles.includes(role))
                    .map((entity) => (
                      <option key={entity.entity_id} value={entity.entity_id}>
                        {entity.name ? `${entity.name} (${entity.entity_id})` : entity.entity_id}
                      </option>
                    ))}
                </select>
              </label>
            </li>
          ))}
        </ul>
      )}
      <button type="button" disabled={!name.trim()} onClick={add}>
        {t("home.add.confirm")}
      </button>{" "}
      <button type="button" onClick={() => setOpen(false)}>
        {t("home.add.cancel")}
      </button>
    </fieldset>
  );
}
