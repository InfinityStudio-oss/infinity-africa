"use client";

import Link from "next/link";
import { useState } from "react";

import { Icon } from "@/components/portal/icon";

import { DocsSidebar } from "./docs-sidebar";

export function DocsShell({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="min-h-screen bg-surface text-on-surface">
      <header className="sticky top-0 z-50 h-16 bg-surface/90 backdrop-blur-sm border-b border-outline-variant/60 flex items-center justify-between px-4 lg:px-8">
        <div className="flex items-center gap-3">
          <button onClick={() => setSidebarOpen(true)} className="lg:hidden text-on-surface-variant p-1" aria-label="Open menu">
            <Icon name="menu" />
          </button>
          <Link href="/" className="flex items-center">
            <span className="text-lg font-bold tracking-tight text-primary">InfinityPay</span>
          </Link>
          <span className="hidden sm:inline text-sm font-semibold text-on-surface-variant border-l border-outline-variant pl-3 ml-1">
            API Docs
          </span>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/" className="text-sm font-medium text-on-surface-variant hover:text-primary transition-colors">
            Back to site
          </Link>
        </div>
      </header>

      <DocsSidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      <main className="lg:ml-64 px-4 sm:px-8 lg:px-12 py-10 max-w-4xl">{children}</main>
    </div>
  );
}
