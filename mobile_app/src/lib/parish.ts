// Parish selection. The user picks a parish via the Search screen;
// the choice is persisted to localStorage along with the parish's name
// so screens don't have to re-fetch it for the header.

const ID_KEY = "bulletin.selectedParishId";
const NAME_KEY = "bulletin.selectedParishName";
const DEFAULT_PARISH = "ny-old-st-patricks";

export function getSelectedParishId(): string {
  try {
    return localStorage.getItem(ID_KEY) ?? DEFAULT_PARISH;
  } catch {
    return DEFAULT_PARISH;
  }
}

export function getSelectedParishName(): string | null {
  try {
    return localStorage.getItem(NAME_KEY);
  } catch {
    return null;
  }
}

export function setSelectedParish(id: string, name?: string): void {
  try {
    localStorage.setItem(ID_KEY, id);
    if (name) localStorage.setItem(NAME_KEY, name);
  } catch {
    // localStorage can throw in private-browsing on some browsers; ignore.
  }
}
