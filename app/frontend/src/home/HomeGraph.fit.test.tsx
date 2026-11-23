import { act, render } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Cadrage du graphe de la maison : celui de l'ouverture n'est pas animé, et un filet le refait
// tant que la vue est restée celle de départ (coin haut gauche, échelle 1) — une page ouverte
// sans être affichée laissait parfois le dessin non cadré. Une vue déplacée ou zoomée par
// l'utilisateur n'est jamais touchée. L'instance de React Flow est simulée : jsdom ne mesure rien.

const viewport = { x: 0, y: 0, zoom: 1 };
const instance = {
  fitView: vi.fn(async () => true),
  getViewport: vi.fn(() => ({ ...viewport })),
  getNodes: vi.fn(() => []),
};

vi.mock("@xyflow/react", async (original) => ({
  ...(await original<typeof import("@xyflow/react")>()),
  useReactFlow: () => instance,
}));

const { Fitter } = await import("./HomeGraph");

let resized: (() => void) | null = null;

function show(zoomed: string | null = null) {
  const canvas = createRef<HTMLDivElement>();
  const view = render(
    <div ref={canvas}>
      <Fitter zoomed={zoomed} fullscreen={false} search="" canvas={canvas} />
    </div>,
  );
  return {
    zoomTo: (next: string | null) =>
      view.rerender(
        <div ref={canvas}>
          <Fitter zoomed={next} fullscreen={false} search="" canvas={canvas} />
        </div>,
      ),
  };
}

const durations = () => instance.fitView.mock.calls.map((call) => (call as unknown[])[0] as { duration?: number }).map((options) => options.duration);

describe("Fitter", () => {
  beforeEach(() => {
    Object.assign(viewport, { x: 0, y: 0, zoom: 1 });
    instance.fitView.mockClear();
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
    vi.unstubAllGlobals();
    resized = null;
  });

  it("cadre l'ouverture sans animation, puis les changements de vue avec", async () => {
    instance.fitView.mockImplementation(async () => {
      Object.assign(viewport, { x: 400, y: 300, zoom: 0.15 });
      return true;
    });
    const graph = show();
    await act(async () => {});
    expect(durations()).toEqual([0]);

    graph.zoomTo("device:washer");
    await act(async () => {});
    expect(durations()).toEqual([0, 300]);
  });

  it("refait le cadrage quand la vue est restée celle de départ", async () => {
    instance.fitView.mockImplementation(async () => true); // cadrage resté sans effet
    show();
    await act(async () => {});
    expect(instance.fitView).toHaveBeenCalledTimes(2);
    expect(durations()[1]).toBeUndefined(); // filet : sans animation
  });

  it("recadre quand le canevas change de taille, tant que la vue n'a pas été cadrée", async () => {
    instance.fitView.mockImplementation(async () => true);
    show();
    await act(async () => {});
    instance.fitView.mockClear();

    act(() => resized?.());
    expect(instance.fitView).toHaveBeenCalledTimes(1);

    Object.assign(viewport, { x: 120, y: -40, zoom: 0.4 }); // vue déplacée par l'utilisateur
    instance.fitView.mockClear();
    act(() => resized?.());
    expect(instance.fitView).not.toHaveBeenCalled();
  });
});
