import { create } from "zustand";

interface AppState {
  currentWorkspaceId: string | null;
  currentWorkspaceName: string | null;
  setCurrentWorkspace: (id: string | null, name?: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  currentWorkspaceId: null,
  currentWorkspaceName: null,
  setCurrentWorkspace: (id, name = null) => set({ currentWorkspaceId: id, currentWorkspaceName: name }),
}));
