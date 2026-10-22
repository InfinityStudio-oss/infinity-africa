import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EffectiveSettingsCard } from "./effective-settings-card";

/**
 * A variable that is absent, misspelled or unreadable all produce the same
 * outcome - the field's default - and two of those three are completely
 * silent. On 2026-10-22 that cost an evening: Selcom callbacks kept being
 * rejected after the flag enabling them had reportedly been set, 177 went
 * unprocessed after a confirmed deploy, and there was no way to tell from
 * outside whether the process had ever seen the variable.
 *
 * This card exists so that question is answered at a glance, which means
 * the "not set" state has to be impossible to miss.
 */

const report = (settings: Record<string, { value: unknown; source: "env" | "default" }>) =>
  ({ settings } as never);

describe("EffectiveSettingsCard", () => {
  it("shows a value that came from the environment as set", () => {
    render(
      <EffectiveSettingsCard
        report={report({
          selcom_outbound_max_per_minute: { value: 300, source: "env" },
        })}
      />,
    );

    // Scoped to the table: the same phrase appears in the description
    // above it, explaining what the column means.
    const table = within(screen.getByRole("table"));
    expect(table.getByText("300")).toBeInTheDocument();
    expect(table.getByText("Set in Railway")).toBeInTheDocument();
  });

  it("calls out a setting nothing supplied", () => {
    // The case that was invisible, and the whole reason for the card.
    render(
      <EffectiveSettingsCard
        report={report({
          selcom_checkout_accept_unsigned_callbacks: { value: false, source: "default" },
        })}
      />,
    );

    expect(screen.getByText("Default — not set")).toBeInTheDocument();
  });

  it("renders booleans as on and off rather than true and false", () => {
    render(
      <EffectiveSettingsCard
        report={report({
          require_super_admin_mfa: { value: true, source: "env" },
          cache_enabled: { value: false, source: "default" },
        })}
      />,
    );

    expect(screen.getByText("on")).toBeInTheDocument();
    expect(screen.getByText("off")).toBeInTheDocument();
  });

  it("shows the variable name so it can be copied into the hosting dashboard", () => {
    render(
      <EffectiveSettingsCard
        report={report({
          selcom_outbound_max_concurrent: { value: 20, source: "env" },
        })}
      />,
    );

    expect(screen.getByText("SELCOM_OUTBOUND_MAX_CONCURRENT")).toBeInTheDocument();
  });

  it("says the read failed rather than showing an empty table", () => {
    // "No settings" is impossible - the API always reports every field -
    // so an empty render would be the page lying about what it knows.
    render(<EffectiveSettingsCard report={null} />);

    expect(screen.getByText(/Couldn't read the live configuration/)).toBeInTheDocument();
  });
});
