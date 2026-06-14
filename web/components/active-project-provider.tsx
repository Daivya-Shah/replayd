"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import type { ActiveProjectContext, ActiveProjectValue } from "@/lib/active-project-types";
import type { Project } from "@/lib/types";

const defaultContext: ActiveProjectContext = {
  scopingEnabled: false,
  activeProject: null,
  projects: [],
  selectProject: () => {},
};

const ActiveProjectContextValue = createContext<ActiveProjectContext>(defaultContext);

export function ActiveProjectProvider({
  value: serverValue,
  children,
}: {
  value: ActiveProjectValue;
  children: React.ReactNode;
}) {
  const [pendingProjectId, setPendingProjectId] = useState<string | null>(null);
  const [extraProjects, setExtraProjects] = useState<Project[]>([]);

  useEffect(() => {
    if (
      pendingProjectId !== null &&
      serverValue.activeProject?.id === pendingProjectId
    ) {
      setPendingProjectId(null);
      setExtraProjects([]);
    }
  }, [pendingProjectId, serverValue.activeProject?.id]);

  const projects = useMemo(() => {
    const seen = new Set(serverValue.projects.map((project) => project.id));
    const merged = [...serverValue.projects];
    for (const project of extraProjects) {
      if (!seen.has(project.id)) {
        merged.push(project);
        seen.add(project.id);
      }
    }
    return merged;
  }, [extraProjects, serverValue.projects]);

  const selectProject = useCallback((projectId: string, project?: Project) => {
    setPendingProjectId(projectId);
    if (project) {
      setExtraProjects((current) =>
        current.some((item) => item.id === project.id)
          ? current
          : [...current, project],
      );
    }
  }, []);

  const activeProject = useMemo(() => {
    const targetId = pendingProjectId ?? serverValue.activeProject?.id;
    if (!targetId) {
      return serverValue.activeProject;
    }
    return projects.find((project) => project.id === targetId) ?? serverValue.activeProject;
  }, [pendingProjectId, projects, serverValue.activeProject]);

  const value = useMemo<ActiveProjectContext>(
    () => ({
      scopingEnabled: serverValue.scopingEnabled,
      activeProject,
      projects,
      selectProject,
    }),
    [activeProject, projects, selectProject, serverValue.scopingEnabled],
  );

  return (
    <ActiveProjectContextValue.Provider value={value}>
      {children}
    </ActiveProjectContextValue.Provider>
  );
}

export function useActiveProject(): ActiveProjectContext {
  return useContext(ActiveProjectContextValue);
}

export function useActiveProjectId(): string | undefined {
  const { scopingEnabled, activeProject } = useActiveProject();
  return scopingEnabled ? activeProject?.id : undefined;
}
