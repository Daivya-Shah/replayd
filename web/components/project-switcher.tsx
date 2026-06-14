"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";

import {
  createProjectAndSwitch,
  switchActiveProject,
} from "@/app/actions/project";
import { useActiveProject } from "@/components/active-project-provider";

function ProjectMenuItem({
  project,
  active,
  onSelect,
}: {
  project: { id: string; name: string; slug: string };
  active: boolean;
  onSelect: (projectId: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(project.id)}
      className={`flex w-full flex-col gap-0.5 rounded-md px-3 py-2 text-left transition ${
        active
          ? "bg-zinc-100 dark:bg-zinc-900"
          : "hover:bg-zinc-50 dark:hover:bg-zinc-900/60"
      }`}
    >
      <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
        {project.name}
      </span>
      <span className="font-mono text-xs text-zinc-500 dark:text-zinc-500">
        {project.slug}
      </span>
    </button>
  );
}

export function ProjectSwitcher() {
  const router = useRouter();
  const { scopingEnabled, activeProject, projects, selectProject } = useActiveProject();
  const [open, setOpen] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [error, setError] = useState<string>();
  const [isPending, startTransition] = useTransition();
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    function handleClick(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setOpen(false);
        setShowCreate(false);
        setError(undefined);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  if (!scopingEnabled || !activeProject) {
    return null;
  }

  function handleSwitch(projectId: string) {
    selectProject(projectId);
    startTransition(async () => {
      try {
        await switchActiveProject(projectId);
        setOpen(false);
        setShowCreate(false);
        setError(undefined);
        router.refresh();
      } catch {
        setError("Could not switch project.");
      }
    });
  }

  function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    startTransition(async () => {
      try {
        const project = await createProjectAndSwitch(projectName);
        selectProject(project.id, project);
        setProjectName("");
        setShowCreate(false);
        setOpen(false);
        setError(undefined);
        router.refresh();
      } catch {
        setError("Could not create project.");
      }
    });
  }

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => {
          setOpen((current) => !current);
          setShowCreate(false);
          setError(undefined);
        }}
        disabled={isPending}
        className="inline-flex max-w-[12rem] items-center gap-2 rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-900 transition hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span className="truncate">{activeProject.name}</span>
        <span className="text-zinc-400 dark:text-zinc-500" aria-hidden>
          ▾
        </span>
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-72 rounded-lg border border-zinc-200 bg-white p-2 shadow-lg dark:border-zinc-800 dark:bg-zinc-950">
          <div className="px-2 py-1.5 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Projects
          </div>
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {projects.map((project) => (
              <ProjectMenuItem
                key={project.id}
                project={project}
                active={project.id === activeProject.id}
                onSelect={handleSwitch}
              />
            ))}
          </div>

          <div className="my-2 border-t border-zinc-200 dark:border-zinc-800" />

          {!showCreate ? (
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="flex w-full rounded-md px-3 py-2 text-left text-sm font-medium text-zinc-900 transition hover:bg-zinc-50 dark:text-zinc-100 dark:hover:bg-zinc-900/60"
            >
              New project
            </button>
          ) : (
            <form className="space-y-2 px-1" onSubmit={handleCreate}>
              <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400">
                Project name
              </label>
              <input
                type="text"
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
                placeholder="Staging"
                className="h-8 w-full rounded-md border border-zinc-200 bg-white px-2.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                autoFocus
              />
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={isPending || !projectName.trim()}
                  className="inline-flex h-8 flex-1 items-center justify-center rounded-md bg-zinc-900 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
                >
                  {isPending ? "Creating..." : "Create"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowCreate(false);
                    setProjectName("");
                  }}
                  className="inline-flex h-8 items-center rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-700 transition hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}

          {error && (
            <p className="mt-2 px-2 text-xs text-red-700 dark:text-red-300">{error}</p>
          )}
        </div>
      )}
    </div>
  );
}
