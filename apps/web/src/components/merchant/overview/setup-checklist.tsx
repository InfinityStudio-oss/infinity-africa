"use client";

import Link from "next/link";
import { useState } from "react";

import { Card } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";

/**
 * Setup tasks, below the reporting.
 *
 * It used to sit above everything, which meant a verified merchant with
 * nothing left to do still had to scroll past it to see their takings.
 * Reporting is what a working account opens this page for; setup is what
 * a new one needs. So it goes underneath, and once everything is done it
 * collapses to a single line rather than taking a screen to say nothing.
 *
 * Incomplete tasks stay easy to find: anything outstanding renders
 * expanded, with a count in the heading.
 */

export interface ChecklistTask {
  id: string;
  label: string;
  description: string;
  href: string;
  done: boolean;
  icon: string;
}

export function SetupChecklist({ tasks }: { tasks: ChecklistTask[] }) {
  const outstanding = tasks.filter((task) => !task.done);
  const allDone = outstanding.length === 0;
  // Collapsed only when there is nothing to do. An outstanding task must
  // never start hidden behind a disclosure.
  const [open, setOpen] = useState(!allDone);

  if (tasks.length === 0) return null;

  return (
    <Card>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <Icon
            name={allDone ? "task_alt" : "checklist"}
            className={allDone ? "text-accent-text" : "text-primary"}
          />
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-on-surface">
              {allDone ? "Setup complete" : "Finish setting up"}
            </h2>
            <p className="text-sm text-on-surface-variant">
              {allDone
                ? "Everything is in place."
                : `${outstanding.length} of ${tasks.length} task${
                    tasks.length === 1 ? "" : "s"
                  } still to do.`}
            </p>
          </div>
        </div>
        {allDone && (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            className="text-sm font-medium text-on-surface-variant hover:text-on-surface shrink-0"
          >
            {open ? "Hide" : "Review"}
          </button>
        )}
      </div>

      {open && (
        <ul className="mt-4 space-y-1">
          {tasks.map((task) => (
            <li key={task.id}>
              <Link
                href={task.href}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors ${
                  task.done ? "opacity-60 hover:bg-surface-container" : "hover:bg-surface-container"
                }`}
              >
                <Icon
                  name={task.done ? "check_circle" : task.icon}
                  filled={task.done}
                  className={task.done ? "text-accent-text shrink-0" : "text-primary shrink-0"}
                />
                <span className="flex-1 min-w-0">
                  <span
                    className={`block text-sm font-medium ${
                      task.done ? "text-on-surface-variant line-through" : "text-on-surface"
                    }`}
                  >
                    {task.label}
                  </span>
                  <span className="block text-xs text-on-surface-variant truncate">
                    {task.description}
                  </span>
                </span>
                {!task.done && (
                  <Icon name="arrow_forward" className="text-[18px] text-on-surface-variant shrink-0" />
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
