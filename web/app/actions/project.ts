"use server";

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";

import { createProjectServer, listProjectsServer } from "@/lib/api-server";
import { ACTIVE_PROJECT_COOKIE, ACTIVE_PROJECT_COOKIE_MAX_AGE } from "@/lib/project-cookie";
import type { Project } from "@/lib/types";

async function assertAccessibleProject(projectId: string): Promise<Project> {
  const { items } = await listProjectsServer();
  const project = items.find((item) => item.id === projectId);
  if (!project) {
    throw new Error("Project not found");
  }
  return project;
}

async function persistActiveProject(projectId: string): Promise<void> {
  await assertAccessibleProject(projectId);
  const cookieStore = await cookies();
  cookieStore.set(ACTIVE_PROJECT_COOKIE, projectId, {
    path: "/",
    maxAge: ACTIVE_PROJECT_COOKIE_MAX_AGE,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
  });
  revalidatePath("/", "layout");
}

export async function switchActiveProject(projectId: string): Promise<void> {
  await persistActiveProject(projectId);
}

export async function createProjectAndSwitch(name: string): Promise<Project> {
  const trimmed = name.trim();
  if (!trimmed) {
    throw new Error("Project name is required");
  }
  const project = await createProjectServer(trimmed);
  await persistActiveProject(project.id);
  return project;
}
