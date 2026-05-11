// Mock data so the app runs with `npm run dev` without the Python API.
// The shapes come from example_responses/today.json and schedule.json that
// the API tests produced. Times are written for the parishioner-on-Sunday
// scenario so the UI looks alive in dev.

import type {
  Bulletin,
  ScheduleResponse,
  TodayResponse,
} from "./types";

// Helper: produce a list of dated services for the next `days` days that
// looks like the St Patrick's recurring schedule + the 'temporary 5pm'
// exception. We use the *current* date so the schedule screen always
// shows future dates in dev — otherwise checking the app in 2027 against
// 2026 fixtures looks weird.
function buildMockSchedule(days: number): ScheduleResponse {
  const services: ScheduleResponse["services"] = [];
  const today = new Date();

  for (let offset = 0; offset < days; offset++) {
    const d = new Date(today);
    d.setDate(today.getDate() + offset);
    const isoDate = d.toISOString().slice(0, 10);
    const dow = d.getDay(); // 0 = Sun .. 6 = Sat

    if (dow >= 1 && dow <= 5) {
      // Mon–Fri daily Mass
      services.push({
        date: isoDate,
        start_time: "12:10",
        end_time: null,
        kind: "mass",
        language: "en",
        location_id: "main",
        notes: null,
        is_exception: false,
        intentions: [],
      });
    }
    if (dow === 6) {
      // Saturday confessions + vigil
      services.push({
        date: isoDate,
        start_time: "16:15",
        end_time: "16:45",
        kind: "confession",
        language: null,
        location_id: "main",
        notes: null,
        is_exception: false,
        intentions: [],
      });
      services.push({
        date: isoDate,
        start_time: "17:00",
        end_time: null,
        kind: "vigil_mass",
        language: "en",
        location_id: "main",
        notes: null,
        is_exception: false,
        intentions: [],
      });
    }
    if (dow === 0) {
      // Sunday lineup
      services.push(
        { date: isoDate, start_time: "09:00", end_time: null, kind: "mass", language: "es", location_id: "main", notes: null, is_exception: false, intentions: [] },
        { date: isoDate, start_time: "10:30", end_time: null, kind: "mass", language: "en", location_id: "main", notes: null, is_exception: false, intentions: [] },
        { date: isoDate, start_time: "12:00", end_time: null, kind: "mass", language: "it", location_id: "main", notes: null, is_exception: false, intentions: [] },
        { date: isoDate, start_time: "12:00", end_time: null, kind: "mass", language: "en", location_id: "mpb", notes: null, is_exception: false, intentions: [] },
        { date: isoDate, start_time: "14:00", end_time: null, kind: "mass", language: "vi", location_id: "mpb", notes: null, is_exception: false, intentions: [] },
        { date: isoDate, start_time: "17:00", end_time: null, kind: "mass", language: null, location_id: "main", notes: "Temporary 5:00pm English Mass until Pentecost.", is_exception: true, intentions: [] },
        { date: isoDate, start_time: "18:00", end_time: "18:45", kind: "confession", language: null, location_id: "main", notes: null, is_exception: false, intentions: [] },
        { date: isoDate, start_time: "19:00", end_time: null, kind: "mass", language: "en", location_id: "main", notes: null, is_exception: false, intentions: [] }
      );
    }
  }

  return { parish_id: "ny-old-st-patricks", days, services };
}

export async function mockToday(parishId: string): Promise<TodayResponse> {
  // Compute "today" view from the mock schedule: take today's services,
  // pick the next one (whichever start_time is closest to current local time).
  await new Promise((r) => setTimeout(r, 80)); // simulate latency

  const schedule = buildMockSchedule(7);
  const today = new Date().toISOString().slice(0, 10);
  const todays = schedule.services.filter((s) => s.date === today);
  const now = new Date();
  const nowStr = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  const remaining = todays.filter((s) => s.start_time >= nowStr);
  const nextToday = remaining[0] ?? null;
  // If nothing today, fall through to the first upcoming service this week.
  const nextService =
    nextToday ?? schedule.services.find((s) => s.date > today) ?? null;

  return {
    parish_id: parishId,
    as_of: now.toISOString(),
    today,
    next_service: nextService,
    today_services_remaining: remaining,
    this_week_exceptions: [
      {
        kind: "added",
        date: today,
        end_date: null,
        affects_service: "mass",
        affects_time: null,
        new_time: "17:00:00",
        description: "Temporary 5:00pm English Mass on Sundays until Pentecost.",
        location_id: "main",
      },
    ],
    high_priority_announcements: [
      {
        title: "OSP Hospitality Presents: The Saints",
        body: "Film screening with reception. Reception at 6:00 PM, screening at 7:00 PM. All are welcome, bring a friend!",
        category: "event",
        event_date: today,
        event_time: "18:00:00",
        location: null,
        contact_email: null,
        contact_phone: null,
        register_url: "https://luma.com/j2ydh30q",
        priority: 2,
      },
    ],
    todays_intentions: [
      {
        date: today,
        time: "12:10:00",
        intention_for: "Andrew & Irene Chan",
        requested_by: "Robert & Virginia Lugo",
        is_deceased: false,
        location_id: "main",
      },
    ],
  };
}

export async function mockSchedule(
  parishId: string,
  days: number
): Promise<ScheduleResponse> {
  await new Promise((r) => setTimeout(r, 80));
  const s = buildMockSchedule(days);
  return { ...s, parish_id: parishId };
}

export async function mockBulletin(_parishId: string): Promise<Bulletin> {
  await new Promise((r) => setTimeout(r, 100));
  return {
    parish: {
      name: "Basilica of St. Patrick's Old Cathedral",
      locations: [
        {
          id: "main",
          name: "Basilica of St. Patrick's Old Cathedral",
          address: "263 Mulberry Street, New York, NY 10012",
          phone: "(212) 226-8075",
          website: "oldcathedral.org",
        },
        {
          id: "mpb",
          name: "Shrine Church of the Most Precious Blood",
          address: "113 Baxter Street, New York, NY 10013",
          phone: null,
          website: null,
        },
      ],
      staff: [
        { name: "Rev. Daniel Ray, LC", role: "Pastor", email: null },
        { name: "Rosa Jimenez", role: "Secretary & Wedding Coordinator", email: "rosa@oldcathedral.org" },
      ],
    },
    liturgical_day: {
      name: "Sixth Sunday of Easter",
      date: new Date().toISOString().slice(0, 10),
      readings: ["Acts 8:5-8, 14-17", "1 Peter 3:15-18", "John 14:15-21"],
    },
    week_starting: new Date().toISOString().slice(0, 10),
    recurring_schedule: [],
    schedule_exceptions: [],
    mass_intentions: [],
    announcements: [
      {
        title: "OSP Hospitality Presents: The Saints",
        body: "Film screening with reception. All are welcome, bring a friend!",
        category: "event",
        event_date: new Date().toISOString().slice(0, 10),
        event_time: "18:00:00",
        location: null,
        contact_email: null,
        contact_phone: null,
        register_url: "https://luma.com/j2ydh30q",
        priority: 2,
      },
      {
        title: "Marriage Convalidation",
        body: "Married by the state but not yet by the Catholic Church? Reach out about having your marriage convalidated. Doesn't require a big ceremony.",
        category: "sacramental",
        event_date: null,
        event_time: null,
        location: null,
        contact_email: "rosa@oldcathedral.org",
        contact_phone: null,
        register_url: null,
        priority: 5,
      },
      {
        title: "Book Club: The City of God",
        body: "Sundays at 5:50pm, 32 Prince St. Studying The City of God by Saint Augustine.",
        category: "ministry",
        event_date: null,
        event_time: "17:50:00",
        location: "32 Prince St",
        contact_email: null,
        contact_phone: null,
        register_url: null,
        priority: 4,
      },
      {
        title: "Recurring Giving via WeShare",
        body: "Set up weekly or monthly recurring donations through WeShare to support the parish even when away.",
        category: "stewardship",
        event_date: null,
        event_time: null,
        location: null,
        contact_email: null,
        contact_phone: null,
        register_url: null,
        priority: 7,
      },
      {
        title: "Catacombs by Candlelight Tours",
        body: "90-minute tour through two centuries of history. Visit oldcathedral.org/tours.",
        category: "operational",
        event_date: null,
        event_time: null,
        location: null,
        contact_email: null,
        contact_phone: null,
        register_url: null,
        priority: 8,
      },
      {
        title: "Victim Assistance",
        body: "To report alleged abuse, contact Eileen Mulcahy at 646-794-2949 or victimsassistance@archny.org.",
        category: "safety",
        event_date: null,
        event_time: null,
        location: null,
        contact_email: "victimsassistance@archny.org",
        contact_phone: "646-794-2949",
        register_url: null,
        priority: 6,
      },
    ],
    collections: [
      { location_id: "main", amount_usd: 9123.36, week_of: null },
      { location_id: "mpb", amount_usd: 668.0, week_of: null },
    ],
  };
}

// ---- Mock parishes for search ---------------------------------------------
//
// A small geographic spread so the three search modes have something to do
// in dev. Real coordinates so the map renders in the right place.

import type { Parish, ParishListResponse } from "./types";

const MOCK_PARISHES: Parish[] = [
  {
    id: "ny-old-st-patricks",
    name: "Basilica of St. Patrick's Old Cathedral",
    diocese: "Archdiocese of New York",
    city: "New York", state: "NY", country: "US",
    timezone: "America/New_York",
    address: "263 Mulberry Street, New York, NY 10012",
    postal_code: "10012",
    latitude: 40.7224, longitude: -73.9956,
  },
  {
    id: "ny-st-james-brooklyn",
    name: "Co-Cathedral of St. Joseph",
    diocese: "Diocese of Brooklyn",
    city: "Brooklyn", state: "NY", country: "US",
    timezone: "America/New_York",
    address: "856 Pacific Street, Brooklyn, NY 11238",
    postal_code: "11238",
    latitude: 40.6814, longitude: -73.9740,
  },
  {
    id: "ny-st-francis-of-assisi",
    name: "Church of St. Francis of Assisi",
    diocese: "Archdiocese of New York",
    city: "New York", state: "NY", country: "US",
    timezone: "America/New_York",
    address: "135 W 31st St, New York, NY 10001",
    postal_code: "10001",
    latitude: 40.7501, longitude: -73.9905,
  },
  {
    id: "il-holy-name",
    name: "Holy Name Cathedral",
    diocese: "Archdiocese of Chicago",
    city: "Chicago", state: "IL", country: "US",
    timezone: "America/Chicago",
    address: "735 N State St, Chicago, IL 60654",
    postal_code: "60654",
    latitude: 41.8961, longitude: -87.6286,
  },
  {
    id: "ca-mission-dolores",
    name: "Mission San Francisco de Asís",
    diocese: "Archdiocese of San Francisco",
    city: "San Francisco", state: "CA", country: "US",
    timezone: "America/Los_Angeles",
    address: "3321 16th St, San Francisco, CA 94114",
    postal_code: "94114",
    latitude: 37.7644, longitude: -122.4274,
  },
];

function haversineKm(a1: number, b1: number, a2: number, b2: number): number {
  const R = 6371;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dPhi = toRad(a2 - a1);
  const dLambda = toRad(b2 - b1);
  const x =
    Math.sin(dPhi / 2) ** 2 +
    Math.cos(toRad(a1)) * Math.cos(toRad(a2)) * Math.sin(dLambda / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}

export async function mockSearchByText(q: string): Promise<ParishListResponse> {
  await new Promise((r) => setTimeout(r, 80));
  const needle = q.toLowerCase().trim();
  if (!needle) return { parishes: [], count: 0 };
  const matches = MOCK_PARISHES.filter((p) =>
    [p.name, p.city ?? "", p.state ?? ""].some((field) =>
      field.toLowerCase().includes(needle)
    )
  );
  return { parishes: matches, count: matches.length };
}

export async function mockSearchByPostalCode(
  postalCode: string
): Promise<ParishListResponse> {
  await new Promise((r) => setTimeout(r, 80));
  const matches = MOCK_PARISHES.filter((p) =>
    (p.postal_code ?? "").startsWith(postalCode.trim())
  );
  return { parishes: matches, count: matches.length };
}

export async function mockSearchByLocation(
  lat: number,
  lng: number,
  radiusKm: number
): Promise<ParishListResponse> {
  await new Promise((r) => setTimeout(r, 80));
  const withDist: Parish[] = [];
  for (const p of MOCK_PARISHES) {
    if (p.latitude == null || p.longitude == null) continue;
    const d = haversineKm(lat, lng, p.latitude, p.longitude);
    if (d <= radiusKm) {
      withDist.push({ ...p, distance_km: d });
    }
  }
  withDist.sort((a, b) => (a.distance_km ?? 0) - (b.distance_km ?? 0));
  return { parishes: withDist, count: withDist.length };
}
