// A thin wrapper around navigator.geolocation that returns a Promise.
// Browsers vary in how they prompt for permission; this hook doesn't
// fight that — it just exposes the standard API as something we can
// `await` and time out cleanly.

export interface Coords {
  latitude: number;
  longitude: number;
  accuracy: number; // meters
}

export function getCurrentLocation(timeoutMs = 8000): Promise<Coords> {
  return new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) {
      reject(new Error("Geolocation is not available in this browser."));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        resolve({
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        });
      },
      (err) => {
        const messages: Record<number, string> = {
          1: "Location permission denied.",
          2: "Location currently unavailable.",
          3: "Location request timed out.",
        };
        reject(new Error(messages[err.code] || err.message));
      },
      { enableHighAccuracy: false, timeout: timeoutMs, maximumAge: 5 * 60 * 1000 }
    );
  });
}
