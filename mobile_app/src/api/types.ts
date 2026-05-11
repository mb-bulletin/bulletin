// API types matching bulletin_parser.api response models.
// These mirror the shapes returned by /v1/* endpoints; see
// example_responses/today.json and schedule.json for samples.
//
// We hand-write these rather than generating from openapi.json because
// the app is small enough that explicit types are clearer than generated
// ones, and we want the freedom to apply small client-side
// transformations (parsing dates, normalizing times) at the boundary.

export type ServiceKind =
  | "mass"
  | "vigil_mass"
  | "confession"
  | "adoration"
  | "rosary"
  | "benediction"
  | "novena"
  | "holy_hour"
  | "other";

export type Language =
  | "en"
  | "es"
  | "it"
  | "vi"
  | "la"
  | "pl"
  | "pt"
  | "fr"
  | "tl"
  | "ko"
  | "zh"
  | "other";

export type AnnouncementCategory =
  | "event"
  | "schedule_change"
  | "sacramental"
  | "ministry"
  | "stewardship"
  | "safety"
  | "operational"
  | "other";

export interface Parish {
  id: string;
  name: string;
  diocese: string | null;
  city: string | null;
  state: string | null;
  country: string;
  timezone: string;
  address?: string | null;
  postal_code?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  distance_km?: number | null;  // only set on near-search results
}

export interface ParishListResponse {
  parishes: Parish[];
  count: number;
}

export interface DatedService {
  date: string;            // YYYY-MM-DD
  start_time: string;      // HH:MM
  end_time: string | null;
  kind: ServiceKind;
  language: Language | null;
  location_id: string;
  notes: string | null;
  is_exception: boolean;
  intentions: string[];
}

export interface ScheduleException {
  kind: "added" | "cancelled" | "moved" | "modified";
  date: string;
  end_date: string | null;
  affects_service: ServiceKind;
  affects_time: string | null;
  new_time: string | null;
  description: string;
  location_id: string;
}

export interface Announcement {
  title: string;
  body: string;
  category: AnnouncementCategory;
  event_date: string | null;
  event_time: string | null;
  location: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  register_url: string | null;
  priority: number;
}

export interface MassIntention {
  date: string;
  time: string;
  intention_for: string;
  requested_by: string | null;
  is_deceased: boolean;
  location_id: string;
}

export interface TodayResponse {
  parish_id: string;
  as_of: string;       // ISO timestamp
  today: string;       // YYYY-MM-DD
  next_service: DatedService | null;
  today_services_remaining: DatedService[];
  this_week_exceptions: ScheduleException[];
  high_priority_announcements: Announcement[];
  todays_intentions: MassIntention[];
}

export interface ScheduleResponse {
  parish_id: string;
  days: number;
  services: DatedService[];
}

// We also use the full Bulletin response for the Announcements screen
// (which wants the complete list, not just high-priority).
export interface Bulletin {
  parish: {
    name: string;
    locations: Array<{
      id: string;
      name: string;
      address: string | null;
      phone: string | null;
      website: string | null;
    }>;
    staff: Array<{ name: string; role: string; email: string | null }>;
  };
  liturgical_day: {
    name: string;
    date: string;
    readings: string[];
  };
  week_starting: string;
  recurring_schedule: Array<{
    kind: ServiceKind;
    weekday: string;
    start_time: string;
    end_time: string | null;
    language: Language | null;
    location_id: string;
    notes: string | null;
  }>;
  schedule_exceptions: ScheduleException[];
  mass_intentions: MassIntention[];
  announcements: Announcement[];
  collections: Array<{ location_id: string; amount_usd: number; week_of: string | null }>;
}
