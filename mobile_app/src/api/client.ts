// Typed API client.
//
// In dev, when VITE_API_BASE_URL is unset OR points at /mock, we serve
// canned responses from src/api/mock_data.ts so the app runs end-to-end
// without standing up the Python backend. In any other build the
// production base URL is used and real HTTP requests go out.
//
// The service worker handles caching transparently; this module doesn't
// implement its own cache. Errors propagate to the caller so the UI can
// render a "couldn't reach the server" state instead of stale-without-warning.

import type {
  Bulletin,
  ParishListResponse,
  ScheduleResponse,
  TodayResponse,
} from "./types";
import {
  mockBulletin,
  mockSchedule,
  mockSearchByLocation,
  mockSearchByPostalCode,
  mockSearchByText,
  mockToday,
} from "./mock_data";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/mock";
const IS_MOCK = API_BASE_URL === "/mock";

async function http<T>(path: string): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  const resp = await fetch(url, {
    headers: { Accept: "application/json" },
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, `GET ${path} -> ${resp.status}`);
  }
  return (await resp.json()) as T;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export async function getToday(parishId: string): Promise<TodayResponse> {
  if (IS_MOCK) return mockToday(parishId);
  return http<TodayResponse>(`/v1/parishes/${parishId}/today`);
}

export async function getSchedule(
  parishId: string,
  days = 7
): Promise<ScheduleResponse> {
  if (IS_MOCK) return mockSchedule(parishId, days);
  return http<ScheduleResponse>(`/v1/parishes/${parishId}/schedule?days=${days}`);
}

export async function getCurrentBulletin(parishId: string): Promise<Bulletin> {
  if (IS_MOCK) return mockBulletin(parishId);
  return http<Bulletin>(`/v1/parishes/${parishId}/bulletins/current`);
}

// ---- Search ---------------------------------------------------------------

export async function searchParishesByText(q: string): Promise<ParishListResponse> {
  if (IS_MOCK) return mockSearchByText(q);
  return http<ParishListResponse>(`/v1/parishes?q=${encodeURIComponent(q)}`);
}

export async function searchParishesByPostalCode(
  postalCode: string
): Promise<ParishListResponse> {
  if (IS_MOCK) return mockSearchByPostalCode(postalCode);
  return http<ParishListResponse>(
    `/v1/parishes?postal_code=${encodeURIComponent(postalCode)}`
  );
}

export async function searchParishesByLocation(
  lat: number,
  lng: number,
  radiusKm = 25
): Promise<ParishListResponse> {
  if (IS_MOCK) return mockSearchByLocation(lat, lng, radiusKm);
  return http<ParishListResponse>(
    `/v1/parishes?near=${lat},${lng}&radius_km=${radiusKm}`
  );
}

export const apiInfo = {
  baseUrl: API_BASE_URL,
  isMock: IS_MOCK,
};
