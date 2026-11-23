import { act, render } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Cadrage du graphe de la maison : le dessin est centré dans la zone libre du canevas, entre le
// bas de la boîte de recherche et le bas du canevas, avec la même marge au-dessus et au-dessous.
// Le cadrage attend que les éléments soient mesurés ; celui de l'ouverture n'est pas animé, et un
// filet le refait tant que la vue est restée celle de départ (coin haut gauche, échelle 1). Une
// vue déplacée ou zoomée par l'utilisateur n'est jamais touchée. L'instance de React Flow est
// simulée : jsdom ne mesure rien.

const viewport = { x: 0, y: 0, zoom: 1 };
const state = { initialized: true, applies: true, measured: true };
// Nos éléments, tels que getNodes() les rend (sans taille), et leurs mesures (100 × 40), portées
// par les éléments internes de React Flow. Dessin large et bas, de 1 000 × 200 : c'est la largeur
// qui fixe l'échelle, et la hauteur qui reste à répartir.
const SIZE = { width: 100, height: 40 };
const nodes = [
  { id: "a", position: { x: 0, y: 0 }, data: { label: "A" } },
  { id: "b", position: { x: 450, y: 80 }, data: { label: "B" } },
  { id: "c", position: { x: 900, y: 160 }, data: { label: "C" } },
];
const DRAWING_HEIGHT = 200;

const instance = {
  getNodes: vi.fn(() => nodes),
  getInternalNode: vi.fn((id: string) => (state.measured && nodes.some((n) => n.id === id) ? { measured: SIZE } : undefined)),
  getViewport: vi.fn(() => ({ ...viewport })),
  setViewport: vi.fn(async (next: typeof viewport) => {
    if (state.applies) Object.assign(viewport, next);
    return true;
  }),
};

vi.mock("@xyflow/react", async (original) => ({
  ...(await original<typeof import("@xyflow/react")>()),
  useReactFlow: () => instance,
  useNodesInitialized: () => state.initialized,
}));

const { Fitter } = await import("./HomeGraph");

const CANVAS = { width: 1000, height: 600 };
const SEARCH_BOTTOM = 56;
let resized: (() => void) | null = null;

function Canvas({ ids, fullscreen = false, search = "" }: { ids: string[]; fullscreen?: boolean; search?: string }) {
  return (
    <div ref={canvas}>
      <div className="react-flow" />
      <div className="graph-search" />
      <Fitter nodes={nodes.filter((node) => ids.includes(node.id))} fullscreen={fullscreen} search={search} canvas={canvas} />
    </div>
  );
}
const canvas = createRef<HTMLDivElement>();

const calls = () => instance.setViewport.mock.calls as unknown as [typeof viewport, { duration?: number }][];

describe("Fitter", () => {
  beforeEach(() => {
    Object.assign(viewport, { x: 0, y: 0, zoom: 1 });
    Object.assign(state, { initialized: true, applies: true, measured: true });
    instance.setViewport.mockClear();
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(CANVAS.width);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(CANVAS.height);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const bottom = this.classList.contains("graph-search") ? SEARCH_BOTTOM : CANVAS.height;
      return { top: 0, bottom, left: 0, right: CANVAS.width, width: CANVAS.width, height: bottom, x: 0, y: 0 } as DOMRect;
    });
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          resized = callback;
        }
        observe() {}
        disconnect() {}
      },
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    resized = null;
  });

  it("centre le dessin entre le bas de la recherche et le bas du canevas", async () => {
    render(<Canvas ids={["a", "b", "c"]} />);
    await act(async () => {});
    const [{ y, zoom }] = calls()[0];
    const above = y - SEARCH_BOTTOM;
    const below = CANVAS.height - (y + DRAWING_HEIGHT * zoom);
    expect(above).toBeGreaterThan(0);
    expect(above).toBeCloseTo(below, 0);
  });

  it("attend que les éléments soient mesurés, puis cadre l'ouverture sans animation", async () => {
    Object.assign(state, { initialized: false, measured: false });
    const view = render(<Canvas ids={["a", "b", "c"]} />);
    await act(async () => {});
    expect(instance.setViewport).not.toHaveBeenCalled();

    Object.assign(state, { initialized: true, measured: true });
    view.rerender(<Canvas ids={["a", "b", "c"]} />);
    await act(async () => {});
    expect(calls().map(([, options]) => options.duration)).toEqual([0]);
  });

  it("réessaie à l'image suivante quand les éléments sont mesurés sans nouveau rendu", async () => {
    // Après un double-clic, les éléments de la nouvelle vue sont mesurés par React Flow sans que
    // l'indicateur « éléments mesurés » change pour Fitter.
    state.measured = false;
    render(<Canvas ids={["a", "b", "c"]} />);
    await act(async () => {});
    expect(instance.setViewport).not.toHaveBeenCalled();

    state.measured = true;
    await act(() => new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0))));
    expect(instance.setViewport).toHaveBeenCalledTimes(1);
  });

  it("anime les changements de vue et ne recadre pas une vue inchangée", async () => {
    const view = render(<Canvas ids={["a", "b", "c"]} />);
    await act(async () => {});
    view.rerender(<Canvas ids={["a", "b", "c"]} />);
    await act(async () => {});
    expect(instance.setViewport).toHaveBeenCalledTimes(1);

    view.rerender(<Canvas ids={["a", "b"]} />); // double-clic : l'intérieur d'un élément
    await act(async () => {});
    view.rerender(<Canvas ids={["a", "b"]} fullscreen />);
    await act(async () => {});
    expect(calls().map(([, options]) => options.duration)).toEqual([0, 300, 300]);
  });

  it("refait le cadrage quand la vue est restée celle de départ", async () => {
    state.applies = false; // cadrage resté sans effet
    render(<Canvas ids={["a", "b", "c"]} />);
    await act(async () => {});
    expect(calls().map(([, options]) => options.duration)).toEqual([0, 0]);
  });

  it("recadre quand le canevas change de taille, tant que la vue n'a pas été cadrée", async () => {
    state.applies = false;
    render(<Canvas ids={["a", "b", "c"]} />);
    await act(async () => {});
    instance.setViewport.mockClear();

    act(() => resized?.());
    expect(instance.setViewport).toHaveBeenCalledTimes(1);

    Object.assign(viewport, { x: 120, y: -40, zoom: 0.4 }); // vue déplacée par l'utilisateur
    instance.setViewport.mockClear();
    act(() => resized?.());
    expect(instance.setViewport).not.toHaveBeenCalled();
  });

  it("recadre sur les résultats de la recherche, dans la même zone libre", async () => {
    const view = render(<Canvas ids={["a", "b", "c"]} />);
    await act(async () => {});
    view.rerender(<Canvas ids={["a", "b", "c"]} search="b" />);
    await act(async () => {});
    const [{ x, y, zoom }, options] = calls().at(-1)!;
    expect(options.duration).toBe(300);
    expect(zoom).toBe(1); // un seul élément : pas de grossissement au-delà de l'échelle 1
    // L'élément B (450, 80), 100 × 40, au milieu de la zone libre.
    expect(x + 450 + SIZE.width / 2).toBeCloseTo(CANVAS.width / 2, 0);
    expect(y + 80 - SEARCH_BOTTOM).toBeCloseTo(CANVAS.height - (y + 80 + SIZE.height), 0);
  });

  it("cadre sur les positions de la vue, même si React Flow garde encore les anciennes", async () => {
    // Après un double-clic, la vue place les éléments ailleurs : le cadrage suit la vue reçue.
    const moved = nodes.map((node) => ({ ...node, position: { x: node.position.x + 5000, y: node.position.y + 3000 } }));
    render(
      <div ref={canvas}>
        <div className="react-flow" />
        <div className="graph-search" />
        <Fitter nodes={moved} fullscreen={false} search="" canvas={canvas} />
      </div>,
    );
    await act(async () => {});
    const [{ x, y, zoom }] = calls()[0];
    expect(x + (5000 + 500) * zoom).toBeCloseTo(CANVAS.width / 2, 0);
    expect(y + 3000 * zoom - SEARCH_BOTTOM).toBeCloseTo(CANVAS.height - (y + (3000 + DRAWING_HEIGHT) * zoom), 0);
  });
});
