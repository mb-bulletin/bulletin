// App root. Routes: the four bottom tabs (today/schedule/news/settings)
// plus 'search' which is reachable from Settings or from the cold-start
// path when no parish has been chosen yet.
//
// We keep the route in the URL hash so back/forward/refresh DTRT on mobile.

import { useCallback, useEffect, useState } from "react";
import type { Parish } from "./api/types";
import { NavBar, type Tab } from "./components/ui";
import { getSelectedParishId, getSelectedParishName, setSelectedParish } from "./lib/parish";
import { NewsScreen } from "./screens/News";
import { ScheduleScreen } from "./screens/Schedule";
import { SearchScreen } from "./screens/Search";
import { SettingsScreen } from "./screens/Settings";
import { TodayScreen } from "./screens/Today";

type Route = Tab | "search";

function routeFromHash(): Route {
  const h = window.location.hash.replace(/^#/, "");
  if (h === "schedule" || h === "news" || h === "settings" || h === "search") return h;
  return "today";
}

// First-run: if there's no localStorage parish AND no name cached, the
// user hasn't onboarded — send them to Search.
function isFirstRun(): boolean {
  try {
    return !localStorage.getItem("bulletin.selectedParishId");
  } catch {
    return false;
  }
}

export function App() {
  const [route, setRoute] = useState<Route>(() =>
    isFirstRun() ? "search" : routeFromHash()
  );
  const [parishId, setParishId] = useState<string>(getSelectedParishId);
  const [parishName, setParishName] = useState<string | null>(getSelectedParishName);

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Keep hash and route in sync the other direction too
  useEffect(() => {
    if (`#${route}` !== window.location.hash) {
      window.location.hash = route;
    }
  }, [route]);

  const goto = useCallback((r: Route) => setRoute(r), []);

  // When the user picks a parish from Search, persist + navigate home.
  const onParishSelected = useCallback((p: Parish) => {
    setSelectedParish(p.id, p.name);
    setParishId(p.id);
    setParishName(p.name);
    setRoute("today");
  }, []);

  const currentTab: Tab = route === "search" ? "settings" : route;

  return (
    <div className="min-h-full flex flex-col">
      <div className="flex-1">
        {route === "today" && <TodayScreen parishId={parishId} />}
        {route === "schedule" && <ScheduleScreen parishId={parishId} />}
        {route === "news" && <NewsScreen parishId={parishId} />}
        {route === "settings" && (
          <SettingsScreen
            parishId={parishId}
            onChangeParish={() => setRoute("search")}
          />
        )}
        {route === "search" && (
          <SearchScreen onParishSelected={onParishSelected} />
        )}
      </div>
      <NavBar current={currentTab} onSelect={(t) => goto(t)} />
      {/* parishName is currently unused at the App level but kept available
          for future header customization. */}
      <span hidden>{parishName}</span>
    </div>
  );
}
