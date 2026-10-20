import { afterEach, describe, expect, it } from "vitest";

import { MENU_STORAGE_KEY, readCollapsed } from "./menu";
import { parseHash, resolveTarget, routeHash } from "./routes";

describe("adresses", () => {
  it("lit et écrit une adresse par section et par sous-page", () => {
    expect(parseHash("#/planning")).toEqual({ section: "planning", sub: null });
    expect(parseHash("#/settings/status")).toEqual({ section: "settings", sub: "status" });
    expect(parseHash("#/home/library")).toEqual({ section: "home", sub: "library" });
    expect(parseHash("#/ui")).toEqual({ section: "ui", sub: null });
    expect(routeHash({ section: "settings", sub: "connection" })).toBe("#/settings/connection");
  });

  it("refuse une adresse inconnue", () => {
    for (const hash of ["", "#", "#/nowhere", "#/home/status", "#/settings/status/x", "#/ui/x"]) {
      expect(parseHash(hash), hash).toBeNull();
    }
  });

  it("mène les anciennes pages du serveur à leur nouvelle place, ancre comprise", () => {
    expect(resolveTarget("home#tariff")).toEqual({ route: { section: "home", sub: null }, anchor: "tariff" });
    expect(resolveTarget("settings#notification")).toEqual({
      route: { section: "settings", sub: "notifications" },
      anchor: "notification",
    });
    expect(resolveTarget("settings#scheduler")?.route).toEqual({ section: "settings", sub: "calculation" });
    expect(resolveTarget("dashboard")).toEqual({ route: { section: "planning", sub: null }, anchor: null });
    expect(resolveTarget("diagnostic")?.route).toEqual({ section: "settings", sub: "status" });
    expect(resolveTarget("connection")?.route).toEqual({ section: "settings", sub: "connection" });
    expect(resolveTarget("library")?.route).toEqual({ section: "home", sub: "library" });
    expect(resolveTarget("#/assistant")?.route).toEqual({ section: "assistant", sub: null });
    expect(resolveTarget("unknown")).toBeNull();
  });

  it("range les écrans experts de Ma maison dans leurs sous-pages", () => {
    // Appareils et capteurs : dans la fiche de chaque appareil depuis la refonte de Ma maison.
    expect(parseHash("#/home/devices")).toBeNull();
    expect(parseHash("#/home/graph")).toEqual({ section: "home", sub: "graph" });
    expect(parseHash("#/settings/devices")).toBeNull();
    // Anciennes ancres de Ma maison, passées dans une sous-page.
    expect(resolveTarget("home#models")).toEqual({ route: { section: "home", sub: "templates" }, anchor: "models" });
    expect(resolveTarget("home#device-washer")).toEqual({ route: { section: "home", sub: null }, anchor: "device-washer" });
    expect(resolveTarget("home#battery")?.route).toEqual({ section: "home", sub: null });
    expect(resolveTarget("devices#add-device")).toEqual({
      route: { section: "home", sub: null },
      anchor: "add-device",
    });
  });
});

describe("menu replié", () => {
  afterEach(() => window.localStorage.clear());

  it("est ouvert au-delà de 1 280 px et replié en dessous, sauf choix gardé", () => {
    expect(readCollapsed(1440)).toBe(false);
    expect(readCollapsed(1024)).toBe(true);
    window.localStorage.setItem(MENU_STORAGE_KEY, "open");
    expect(readCollapsed(1024)).toBe(false);
    window.localStorage.setItem(MENU_STORAGE_KEY, "collapsed");
    expect(readCollapsed(1440)).toBe(true);
  });
});
