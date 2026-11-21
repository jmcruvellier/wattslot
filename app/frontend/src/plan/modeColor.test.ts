import { describe, expect, it } from "vitest";

import themes from "../theme/themes.css?raw";
import { modeColor } from "./modeColor";

describe("couleur d'un mode de fonctionnement dans la frise", () => {
  it("donne sa couleur à chaque mode de la filtration", () => {
    expect(modeColor("silence")).toBe("var(--pool-silence)");
    expect(modeColor("eco")).toBe("var(--pool-eco)");
    expect(modeColor("boost")).toBe("var(--pool-boost)");
  });

  it("lit le nom donné par l'utilisateur sans majuscules ni accents", () => {
    expect(modeColor("Éco")).toBe("var(--pool-eco)");
    expect(modeColor(" BOOST ")).toBe("var(--pool-boost)");
    expect(modeColor("Silence")).toBe("var(--pool-silence)");
  });

  it("garde la couleur du silence pour un autre nom, ou sans vitesse réglée", () => {
    expect(modeColor("rapide")).toBe("var(--pool-silence)");
    expect(modeColor(null)).toBe("var(--pool-silence)");
    expect(modeColor(undefined)).toBe("var(--pool-silence)");
  });

  it("a ses trois couleurs définies dans les thèmes", () => {
    for (const name of ["--pool-silence:", "--pool-eco:", "--pool-boost:"]) expect(themes).toContain(name);
  });
});
