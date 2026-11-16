"use client";

import { useState } from "react";

import { AdminSidebar } from "./sidebar";
import { AdminTopbar } from "./topbar";

export function AdminShell({
  children,
  notificationCount = 0,
  adminEmail = "",
  adminFullName = null,
}: {
  children: React.ReactNode;
  notificationCount?: number;
  adminEmail?: string;
  adminFullName?: string | null;
}) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="admin-shell-scope app-gradient-surface min-h-screen bg-background text-on-background">
      <AdminSidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <AdminTopbar
        onOpenSidebar={() => setSidebarOpen(true)}
        notificationCount={notificationCount}
        adminEmail={adminEmail}
        adminFullName={adminFullName}
      />
      <main className="on-gradient pt-20 md:pt-24 pb-16 px-4 md:px-8 md:ml-64 max-w-[1280px] mx-auto space-y-8">
        {children}
      </main>
    </div>
  );
}
