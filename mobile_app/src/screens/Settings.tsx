// Settings screen — current parish + a button to change it via Search.
//
// The hardcoded list is gone; real parish discovery lives in the Search
// screen, which uses the /v1/parishes search endpoints.

import { apiInfo } from "../api/client";
import { Header } from "../components/ui";
import { getSelectedParishName } from "../lib/parish";

interface Props {
  parishId: string;
  onChangeParish: () => void;
}

export function SettingsScreen({ parishId, onChangeParish }: Props) {
  const parishName = getSelectedParishName() ?? parishId;
  return (
    <>
      <Header title="Settings" />
      <main className="px-4 pt-5 pb-24 space-y-4">
        <section className="card">
          <h2 className="font-medium text-stone-900 mb-2">My parish</h2>
          <p className="text-stone-900">{parishName}</p>
          <p className="text-xs text-stone-500 mt-0.5 font-mono">{parishId}</p>
          <button
            onClick={onChangeParish}
            className="mt-3 px-4 py-2 rounded bg-parish-700 text-white font-medium"
          >
            Change parish
          </button>
        </section>

        <section className="card">
          <h2 className="font-medium text-stone-900 mb-2">About</h2>
          <dl className="text-sm text-stone-700 space-y-1">
            <div className="row">
              <dt>Version</dt>
              <dd className="text-stone-600">0.1.0</dd>
            </div>
            <div className="row">
              <dt>Mode</dt>
              <dd className="text-stone-600">
                {apiInfo.isMock ? "Mock data" : "Live API"}
              </dd>
            </div>
            <div className="row">
              <dt>API</dt>
              <dd className="text-stone-600 text-xs truncate max-w-[60%]">
                {apiInfo.baseUrl}
              </dd>
            </div>
          </dl>
        </section>
      </main>
    </>
  );
}
