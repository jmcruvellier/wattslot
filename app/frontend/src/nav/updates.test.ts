import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { isNewer, RELEASES_URL, UPDATE_CHECK_MS, UPDATE_STORAGE_KEY, UPDATE_TICK_MS, useUpdate } from "./updates";

const RELEASE = { tag_name: "v0.9.0", html_url: "https://github.com/jmcruvellier/wattslot/releases/tag/v0.9.0" };

function mockGitHub(response: () => Response) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async () => response());
}

describe("nouvelle version", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("compare les versions X.Y.Z nombre par nombre", () => {
    expect(isNewer("0.9.0", "0.8.0")).toBe(true);
    expect(isNewer("0.10.0", "0.9.3")).toBe(true);
    expect(isNewer("1.0.0", "0.99.99")).toBe(true);
    expect(isNewer("0.8.0", "0.8.0")).toBe(false);
    expect(isNewer("0.7.9", "0.8.0")).toBe(false);
    expect(isNewer("1.0.0-beta", "0.8.0")).toBe(false);
  });

  it("signale la dernière release du dépôt public quand elle est plus récente", async () => {
    const fetchMock = mockGitHub(() => Response.json(RELEASE));

    const { result } = renderHook(() => useUpdate("0.8.0"));

    await waitFor(() => expect(result.current.status).toBe("available"));
    expect(result.current).toEqual({ status: "available", latest: { version: "0.9.0", url: RELEASE.html_url } });
    expect(fetchMock).toHaveBeenCalledWith(RELEASES_URL, expect.anything());
  });

  it("dit que la version est la plus récente", async () => {
    mockGitHub(() => Response.json({ ...RELEASE, tag_name: "v0.8.0" }));

    const { result } = renderHook(() => useUpdate("0.8.0"));

    await waitFor(() => expect(result.current.status).toBe("current"));
  });

  it("dépôt absent ou hors ligne : vérification impossible, sans erreur", async () => {
    mockGitHub(() => new Response(null, { status: 404 }));

    const { result } = renderHook(() => useUpdate("0.8.0"));

    await waitFor(() => expect(result.current.status).toBe("unavailable"));
  });

  it("garde le résultat une heure et le partage : pas de nouvel appel à GitHub", async () => {
    window.localStorage.setItem(
      UPDATE_STORAGE_KEY,
      JSON.stringify({ checked_at: Date.now() - 10 * 60 * 1000, release: { version: "0.9.0", url: RELEASE.html_url } }),
    );
    const fetchMock = mockGitHub(() => Response.json(RELEASE));

    const { result } = renderHook(() => useUpdate("0.8.0"));

    await waitFor(() => expect(result.current.status).toBe("available"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("revérifie toutes les heures tant que l'application est ouverte", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = mockGitHub(() => Response.json({ ...RELEASE, tag_name: "v0.8.0" }));

    const { result } = renderHook(() => useUpdate("0.8.0"));
    await waitFor(() => expect(result.current.status).toBe("current"));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fetchMock.mockImplementation(async () => Response.json(RELEASE));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPDATE_TICK_MS); // relecture du résultat gardé, encore frais
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPDATE_CHECK_MS);
    });
    await waitFor(() => expect(result.current.status).toBe("available"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("sans version servie : rien à dire", () => {
    mockGitHub(() => Response.json(RELEASE));

    const { result } = renderHook(() => useUpdate(null));

    expect(result.current.status).toBe("unknown");
  });
});
