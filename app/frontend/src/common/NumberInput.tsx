// Champ de saisie d'un nombre (issue 131 sur GitHub). Un <input type="number"> contrôlé par la valeur
// enregistrée empêchait d'effacer (la valeur revenait aussitôt) ou remettait 0 au milieu de la
// frappe, et la virgule décimale n'était pas comprise partout. Ici, le texte tapé est gardé tel
// quel : la valeur n'est transmise que lorsqu'il forme un nombre dans les bornes ; en quittant le
// champ, le nombre est borné (et arrondi s'il doit être entier), et un champ vide reprend sa
// dernière valeur, ou passe à « aucune valeur » s'il est facultatif.

import { useState, type InputHTMLAttributes, type KeyboardEvent } from "react";

import { parseNumber } from "./parseNumber";

type Common = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "type" | "value" | "defaultValue" | "onChange" | "min" | "max" | "step" | "inputMode"
> & {
  min?: number;
  max?: number;
  step?: number; // pas des flèches du clavier ; 1 par défaut
  integer?: boolean; // arrondi à l'unité en quittant le champ
};

type Props = Common &
  (
    | { nullable?: false; value: number; onChange: (value: number) => void }
    | { nullable: true; value: number | null; onChange: (value: number | null) => void }
  );

function format(value: number | null): string {
  return value === null ? "" : String(value);
}

export default function NumberInput(props: Props) {
  const { value, onChange, nullable, min, max, step = 1, integer = false, className, onBlur, onKeyDown, ...rest } =
    props;
  const [text, setText] = useState(() => format(value));
  const [seen, setSeen] = useState(value);
  // Valeur changée de l'extérieur (réglage remis à zéro, autre champ) : le texte la suit, sauf
  // s'il l'écrit déjà autrement (« 3,60 » pour 3,6).
  if (value !== seen) {
    setSeen(value);
    if (parseNumber(text) !== value) setText(format(value));
  }

  const negative = min === undefined || min < 0;
  const inBounds = (found: number) => (min === undefined || found >= min) && (max === undefined || found <= max);
  const bound = (found: number) => {
    let result = integer ? Math.round(found) : found;
    if (min !== undefined) result = Math.max(min, result);
    if (max !== undefined) result = Math.min(max, result);
    return result;
  };
  // Les deux formes de onChange ne se distinguent que par nullable ; le type le garantit à l'appel.
  const send = (next: number | null) => (onChange as (value: number | null) => void)(next);

  const commit = (next: number) => {
    setText(format(next));
    if (next !== value) send(next);
  };

  return (
    <input
      {...rest}
      type="text"
      inputMode={integer && !negative ? "numeric" : "decimal"}
      autoComplete="off"
      className={className ? `number-input ${className}` : "number-input"}
      value={text}
      onChange={(event) => {
        const typed = event.target.value;
        // Seuls les chiffres, un séparateur décimal et un signe (si les négatifs sont permis).
        const allowed = negative ? /^\s*[-+]?[\d\s]*([.,][\d\s]*)?$/ : /^\s*[\d\s]*([.,][\d\s]*)?$/;
        if (!allowed.test(typed)) return;
        setText(typed);
        const found = parseNumber(typed);
        if (found === null) {
          if (nullable && typed.trim() === "" && value !== null) send(null);
          return;
        }
        if (inBounds(found) && (!integer || Number.isInteger(found)) && found !== value) send(found);
      }}
      onBlur={(event) => {
        const found = parseNumber(text);
        if (found !== null) commit(bound(found));
        else if (nullable && text.trim() === "") setText("");
        else setText(format(value));
        onBlur?.(event);
      }}
      onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
        if (event.key === "ArrowUp" || event.key === "ArrowDown") {
          event.preventDefault();
          const start = parseNumber(text) ?? value ?? min ?? 0;
          const moved = start + (event.key === "ArrowUp" ? step : -step);
          // Arrondi au pas pour éviter 0.30000000000000004.
          const decimals = (String(step).split(".")[1] ?? "").length;
          commit(bound(Number(moved.toFixed(decimals))));
        }
        onKeyDown?.(event);
      }}
    />
  );
}
