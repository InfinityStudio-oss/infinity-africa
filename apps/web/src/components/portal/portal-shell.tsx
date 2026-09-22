"use client";

import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { isPathAllowedForRole, USER_ROLE_LABELS } from "@/lib/portal/roles";

import { EmptyState } from "./empty-state";
import { RoleProvider, useRole } from "./role-context";
import { Sidebar } from "./sidebar";
import { Topbar } from "./topbar";

function RoleGuard({ children }: { children: React.ReactNode }) {
  const { role } = useRole();
  const pathname = usePathname();
  const router = useRouter();

  if (!isPathAllowedForRole(role, pathname)) {
    return (
      <EmptyState
        icon="lock"
        heading="Access restricted"
        body={`Your role (${USER_ROLE_LABELS[role]}) doesn't have access to this page. Switch roles from the topbar or head back to Overview.`}
        actionLabel="Go to Overview"
        onAction={() => router.push("/dashboard/overview")}
      />
    );
  }

  return <>{children}</>;
}

// Pages that need the full available dashboard width instead of the default
// 1280px-capped, centered column — e.g. API Credentials' side-by-side
// vertical-menu-plus-content layout. Decided here (by pathname) rather than
// via a prop threaded from each page, since every /portal/* page is already
// wrapped in exactly one PortalShell by app/portal/layout.tsx — a page
// rendering its own second PortalShell (as this one briefly did) double-
// nests the whole shell, sidebar, topbar, and auth checks included.
const FULL_WIDTH_PATHS = ["/portal/api-credentials"];

export function PortalShell({ children, banner }: { children: React.ReactNode; banner?: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const pathname = usePathname();
  const fullWidth = FULL_WIDTH_PATHS.some((path) => pathname.startsWith(path));

  // Two complete, separately-written class strings rather than splicing one
  // conflicting token (e.g. mx-auto vs. a fixed margin) into a shared
  // template — that ordering depends on how the CSS build happens to sort
  // utilities, which is exactly the kind of thing that silently breaks.
  const mainClassName = fullWidth
    ? "pt-20 md:pt-24 pb-16 px-4 md:px-8 md:ml-64 space-y-8"
    : "pt-20 md:pt-24 pb-16 px-4 md:px-8 md:ml-64 max-w-[1280px] mx-auto space-y-8";

  return (
    <RoleProvider>
      <div className="portal-shell-scope min-h-screen bg-background text-on-background">
        <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        <Topbar onOpenSidebar={() => setSidebarOpen(true)} />
        <main className={mainClassName}>
          {banner}
          <RoleGuard>{children}</RoleGuard>
        </main>
      </div>
    </RoleProvider>
  );
}
