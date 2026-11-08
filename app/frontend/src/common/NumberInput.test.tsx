import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import NumberInput from "./NumberInput";
import { parseNumber } from "./parseNumber";

function Required({ start, onChange, ...bounds }: {
  start: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  integer?: boolean;
  step?: number;
}) {
  const [value, setValue] = useState(start);
  return (
    <>
      <NumberInput
        aria-label="Puissance"
        value={value}
        onChange={(next) => {
          setValue(next);
          onChange(next);
        }}
        {...bounds}
      />
      <button type="button" onClick={() => setValue(5)}>
        Remettre
      </button>
    </>
  );
}

function Optional({ onChange }: { onChange: (value: number | null) => void }) {
  const [value, setValue] = useState<number | null>(4);
  return (
    <NumberInput
      aria-label="Onduleur"
      nullable
      min={0.1}
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

describe("parseNumber", () => {
  it("lit la virgule comme le point, refuse ce qui n'est pas un nombre", () => {
    expect(parseNumber("3,6")).toBe(3.6);
    expect(parseNumber(" 3.6 ")).toBe(3.6);
    expect(parseNumber("1 200")).toBe(1200);
    expect(parseNumber("3,")).toBe(3);
    expect(parseNumber(",5")).toBe(0.5);
    expect(parseNumber("")).toBeNull();
    expect(parseNumber("-")).toBeNull();
    expect(parseNumber(",")).toBeNull();
  });
});

describe("NumberInput", () => {
  it("laisse effacer puis retaper une valeur décimale avec une virgule (issue 131 sur GitHub)", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Required start={3} min={0.1} onChange={onChange} />);
    const field = screen.getByLabelText("Puissance");

    await user.clear(field);
    expect(field).toHaveValue("");
    expect(onChange).not.toHaveBeenCalled();

    await user.type(field, "3,6");
    expect(field).toHaveValue("3,6");
    expect(onChange).toHaveBeenLastCalledWith(3.6);

    await user.tab();
    expect(field).toHaveValue("3.6");
  });

  it("reprend la dernière valeur quand on quitte un champ obligatoire vide", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Required start={3} min={0.1} onChange={onChange} />);
    const field = screen.getByLabelText("Puissance");

    await user.clear(field);
    await user.tab();
    expect(field).toHaveValue("3");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("ne remplace pas la saisie par le minimum pendant la frappe, borne en quittant le champ", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Required start={7} min={1} max={90} integer onChange={onChange} />);
    const field = screen.getByLabelText("Puissance");

    await user.clear(field);
    await user.type(field, "12");
    expect(field).toHaveValue("12");
    expect(onChange).toHaveBeenLastCalledWith(12);

    await user.clear(field);
    await user.type(field, "95");
    expect(field).toHaveValue("95");
    expect(onChange).toHaveBeenLastCalledWith(9); // « 9 », dans les bornes ; « 95 » ne l'est pas
    await user.tab();
    expect(field).toHaveValue("90");
    expect(onChange).toHaveBeenLastCalledWith(90);

    await user.clear(field);
    await user.type(field, "2,4");
    await user.tab();
    expect(field).toHaveValue("2");
    expect(onChange).toHaveBeenLastCalledWith(2);
  });

  it("ignore les lettres et le signe moins quand les négatifs sont exclus", async () => {
    const user = userEvent.setup();
    render(<Required start={3} min={0} onChange={vi.fn()} />);
    const field = screen.getByLabelText("Puissance");

    await user.clear(field);
    await user.type(field, "-a4b");
    expect(field).toHaveValue("4");
  });

  it("passe un champ facultatif vidé à aucune valeur", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Optional onChange={onChange} />);
    const field = screen.getByLabelText("Onduleur");

    await user.clear(field);
    expect(onChange).toHaveBeenLastCalledWith(null);
    await user.tab();
    expect(field).toHaveValue("");
  });

  it("suit une valeur changée de l'extérieur et répond aux flèches du clavier", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Required start={3} min={0} step={0.1} onChange={onChange} />);
    const field = screen.getByLabelText("Puissance");

    await user.click(screen.getByRole("button", { name: "Remettre" }));
    expect(field).toHaveValue("5");

    await user.click(field);
    await user.keyboard("{ArrowUp}");
    expect(field).toHaveValue("5.1");
    expect(onChange).toHaveBeenLastCalledWith(5.1);
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(field).toHaveValue("4.9");
  });
});
