// Display formatting helpers.
//
// All formatting decisions live here so we can change them in one place.
// In particular, time formatting uses 12-hour American convention since the
// app is initially US-targeted; future internationalization would change this.

import type { Language, ServiceKind } from "../api/types";

export function formatTime(time: string | null): string {
  // Accept HH:MM or HH:MM:SS and produce "9:00 AM" / "12:10 PM" / "5:00 PM"
  if (!time) return "";
  const [h, m] = time.split(":");
  const hour = parseInt(h, 10);
  const min = m ?? "00";
  const period = hour >= 12 ? "PM" : "AM";
  const h12 = hour % 12 === 0 ? 12 : hour % 12;
  return `${h12}:${min} ${period}`;
}

export function formatDate(date: string, opts: { weekday?: boolean; year?: boolean } = {}): string {
  const d = new Date(date + "T00:00:00");
  return d.toLocaleDateString(undefined, {
    weekday: opts.weekday ? "long" : undefined,
    month: "long",
    day: "numeric",
    year: opts.year ? "numeric" : undefined,
  });
}

export function formatShortDate(date: string): string {
  const d = new Date(date + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

const SERVICE_LABELS: Record<ServiceKind, string> = {
  mass: "Mass",
  vigil_mass: "Vigil Mass",
  confession: "Confessions",
  adoration: "Adoration",
  rosary: "Rosary",
  benediction: "Benediction",
  novena: "Novena",
  holy_hour: "Holy Hour",
  other: "Service",
};

export function formatServiceKind(k: ServiceKind): string {
  return SERVICE_LABELS[k];
}

const LANGUAGE_LABELS: Record<Language, string> = {
  en: "English",
  es: "Spanish",
  it: "Italian",
  vi: "Vietnamese",
  la: "Latin",
  pl: "Polish",
  pt: "Portuguese",
  fr: "French",
  tl: "Tagalog",
  ko: "Korean",
  zh: "Chinese",
  other: "Other",
};

export function formatLanguage(lang: Language | null): string {
  return lang ? LANGUAGE_LABELS[lang] : "";
}

export function formatLocation(locationId: string): string {
  if (locationId === "main") return "";
  // Future: look up against /parish endpoint. For now show the slug.
  if (locationId === "mpb") return "Most Precious Blood";
  return locationId;
}
