import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WithdrawalAutomationPolicy } from "@/lib/admin/types";

const saveWithdrawalAutomationPolicyAction = vi.fn();

vi.mock("@/lib/admin/live-actions", () => ({
  saveWithdrawalAutomationPolicyAction: (...args: unknown[]) =>
    saveWithdrawalAutomationPolicyAction(...args),
}));

import { WithdrawalAutomationCard, compareDecimalStrings } from "./withdrawal-automation-card";

/** Automation permitted by the deployment and switched off in the policy —
 * the state every installation starts in. */
const offPolicy: WithdrawalAutomationPolicy = {
  automation_active: false,
  effective_max_amount_tzs: "0",
  effective_rolling_24h_limit_tzs: "0",
  enabled: false,
  max_amount_tzs: "500000.00",
  merchant_rolling_24h_limit_tzs: "1000000.00",
  version: 1,
  updated_at: null,
  updated_by: null,
  updated_by_email: null,
  blocked_reason_code: "AUTO_POLICY_DISABLED",
  blocked_explanation:
    "Automatic processing is switched off. Every withdrawal is waiting for manual approval.",
  manual_only_override: false,
  deployment_automation_allowed: true,
  hard_max_amount_tzs: "500000",
  hard_rolling_24h_limit_tzs: "1000000",
  policy_unavailable: false,
  platform_min_withdrawal_amount_tzs: "1000",
  platform_max_withdrawal_amount_tzs: "5000000",
  platform_rolling_24h_limit_tzs: "10000000",
};

const onPolicy: WithdrawalAutomationPolicy = {
  ...offPolicy,
  automation_active: true,
  enabled: true,
  effective_max_amount_tzs: "500000.00",
  effective_rolling_24h_limit_tzs: "1000000.00",
  blocked_reason_code: null,
  blocked_explanation: null,
  updated_at: "2026-10-31T09:00:00Z",
  updated_by: "admin-uuid",
  updated_by_email: "admin@infinitypay.me",
};

describe("Automatic Withdrawal Controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("says Manual approval when nothing is automatic", () => {
    render(<WithdrawalAutomationCard policy={offPolicy} />);

    expect(screen.getByText("Manual approval")).toBeInTheDocument();
    expect(screen.getByText(/requests require manual approval/i)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /automatic processing/i })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("says Automatic processing enabled only when it really is", () => {
    render(<WithdrawalAutomationCard policy={onPolicy} />);

    expect(screen.getByText("Automatic processing enabled")).toBeInTheDocument();
    expect(screen.getByText(/can be processed\s+automatically after required verification and OTP/i)).toBeInTheDocument();
  });

  it("shows the effective state, not the stored switch, when a deployment override is forcing manual", () => {
    // The bug this prevents: the policy row says ON, a deployment
    // variable is forcing manual approval, and the page shows a green
    // switch. That would be a lie about whether money needs a human.
    render(
      <WithdrawalAutomationCard
        policy={{
          ...onPolicy,
          automation_active: false,
          manual_only_override: true,
          blocked_reason_code: "AUTO_POLICY_DISABLED",
          blocked_explanation:
            "A deployment override (REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS) is forcing manual approval for every withdrawal.",
        }}
      />,
    );

    expect(screen.getByText("Manual approval")).toBeInTheDocument();
    expect(screen.queryByText("Automatic processing enabled")).not.toBeInTheDocument();
    expect(screen.getByText(/deployment override/i)).toBeInTheDocument();
    // The switch cannot be operated into a state that would do nothing.
    expect(screen.getByRole("switch", { name: /automatic processing/i })).toBeDisabled();
  });

  it("disables the switch when the deployment has not permitted automation at all", () => {
    render(
      <WithdrawalAutomationCard
        policy={{
          ...offPolicy,
          deployment_automation_allowed: false,
          blocked_explanation:
            "This deployment has not enabled withdrawal automation (AUTO_WITHDRAWALS_ENABLED), so the switch below cannot take effect yet.",
        }}
      />,
    );

    expect(screen.getByRole("switch", { name: /automatic processing/i })).toBeDisabled();
    expect(screen.getByText(/has not enabled withdrawal automation/i)).toBeInTheDocument();
  });

  it("labels the ceiling inclusive and works the example from the entered value", () => {
    render(<WithdrawalAutomationCard policy={offPolicy} />);

    expect(screen.getByText(/Maximum automatic withdrawal amount — inclusive/)).toBeInTheDocument();
    expect(
      screen.getByText(
        /TZS 500,000.00 or less may process automatically; amounts above TZS 500,000.00 require approval/,
      ),
    ).toBeInTheDocument();
  });

  it("re-works the example as the operator types, so 500 is never read as 500,000", () => {
    render(<WithdrawalAutomationCard policy={offPolicy} />);

    fireEvent.change(screen.getByPlaceholderText("e.g. 500000"), { target: { value: "500" } });

    expect(
      screen.getByText(/TZS 500 or less may process automatically; amounts above TZS 500 require approval/),
    ).toBeInTheDocument();
  });

  it("says the threshold is the payout amount and that fees are still covered by the balance check", () => {
    render(<WithdrawalAutomationCard policy={offPolicy} />);

    expect(screen.getByText(/full wallet\s+debit, including fees/i)).toBeInTheDocument();
  });

  it("calls the rolling limit a real rolling window and says toggling does not reset it", () => {
    render(<WithdrawalAutomationCard policy={offPolicy} />);

    expect(screen.getByText(/Rolling 24-hour automatic limit per merchant/)).toBeInTheDocument();
    expect(screen.getByText(/Not a\s+calendar day, and not reset by switching this off and on/i)).toBeInTheDocument();
  });

  it("asks for confirmation before enabling, and names the effective limits", () => {
    render(<WithdrawalAutomationCard policy={offPolicy} />);

    fireEvent.click(screen.getByRole("switch", { name: /automatic processing/i }));
    fireEvent.click(screen.getByRole("button", { name: /review and save/i }));

    expect(screen.getByText("Confirm these limits")).toBeInTheDocument();
    expect(screen.getByText("Automatic processing: ON")).toBeInTheDocument();
    expect(screen.getByText(/Up to TZS 500,000.00 per withdrawal, inclusive/)).toBeInTheDocument();
    expect(screen.getByText(/1,000,000.00 per merchant per rolling 24 hours/)).toBeInTheDocument();
    // Eligibility is never presented as approval.
    expect(screen.getByText(/Verification, OTP, fraud checks, balance and destination rules still apply/i)).toBeInTheDocument();
    expect(saveWithdrawalAutomationPolicyAction).not.toHaveBeenCalled();
  });

  it("asks for confirmation before raising a limit", () => {
    render(<WithdrawalAutomationCard policy={onPolicy} />);

    fireEvent.change(screen.getByPlaceholderText("e.g. 500000"), { target: { value: "900000" } });

    expect(screen.getByRole("button", { name: /review and save/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^save$/i })).not.toBeInTheDocument();
  });

  it("never asks for confirmation to switch automation off", () => {
    render(<WithdrawalAutomationCard policy={onPolicy} />);

    fireEvent.click(screen.getByRole("switch", { name: /automatic processing/i }));

    // One click to the brake, not two.
    expect(screen.getByRole("button", { name: /^save$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /review and save/i })).not.toBeInTheDocument();
  });

  it("never asks for confirmation to lower a limit", () => {
    render(<WithdrawalAutomationCard policy={onPolicy} />);

    fireEvent.change(screen.getByPlaceholderText("e.g. 500000"), { target: { value: "1000" } });

    expect(screen.getByRole("button", { name: /^save$/i })).toBeInTheDocument();
  });

  it("warns when a limit is above what the deployment will allow", () => {
    render(<WithdrawalAutomationCard policy={onPolicy} />);

    fireEvent.change(screen.getByPlaceholderText("e.g. 500000"), { target: { value: "900000" } });

    expect(screen.getByText(/This deployment caps automatic processing at TZS 500,000/)).toBeInTheDocument();
  });

  it("reports a failed save and says nothing changed", async () => {
    saveWithdrawalAutomationPolicyAction.mockResolvedValue({
      error: "Couldn't reach InfinityPay.",
      ok: false,
      message: null,
      conflict: false,
      policy: null,
    });
    render(<WithdrawalAutomationCard policy={onPolicy} />);

    fireEvent.change(screen.getByPlaceholderText("e.g. 500000"), { target: { value: "1000" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(screen.getByText(/Couldn't reach InfinityPay\. Nothing was changed\./)).toBeInTheDocument(),
    );
    // And the headline has not moved: a failed save must not look like a
    // state change.
    expect(screen.getByText("Automatic processing enabled")).toBeInTheDocument();
  });

  it("tells the operator to reload when another administrator saved first", async () => {
    saveWithdrawalAutomationPolicyAction.mockResolvedValue({
      error: "This policy was changed by someone else while you were editing it.",
      ok: false,
      message: null,
      conflict: true,
      policy: null,
    });
    render(<WithdrawalAutomationCard policy={onPolicy} />);

    fireEvent.change(screen.getByPlaceholderText("e.g. 500000"), { target: { value: "1000" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(screen.getByText(/Reload the page to see the current settings/)).toBeInTheDocument());
  });

  it("confirms a successful save and follows the stored policy afterwards", async () => {
    saveWithdrawalAutomationPolicyAction.mockResolvedValue({
      error: null,
      ok: true,
      message: "Saved. Every withdrawal requires manual approval.",
      conflict: false,
      policy: { ...offPolicy, version: 2, max_amount_tzs: "1000.00" },
    });
    render(<WithdrawalAutomationCard policy={onPolicy} />);

    fireEvent.click(screen.getByRole("switch", { name: /automatic processing/i }));
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(screen.getByText("Saved. Every withdrawal requires manual approval.")).toBeInTheDocument(),
    );
    expect(screen.getByText("Manual approval")).toBeInTheDocument();
    expect(screen.getByText(/Policy version 2/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("e.g. 500000")).toHaveValue("1000.00");
  });

  it("submits the version it was editing, so a stale save can be refused", async () => {
    saveWithdrawalAutomationPolicyAction.mockResolvedValue({
      error: null,
      ok: true,
      message: "Saved.",
      conflict: false,
      policy: { ...onPolicy, version: 3 },
    });
    render(<WithdrawalAutomationCard policy={{ ...onPolicy, version: 2 }} />);

    fireEvent.change(screen.getByPlaceholderText("e.g. 500000"), { target: { value: "1000" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saveWithdrawalAutomationPolicyAction).toHaveBeenCalled());
    const formData = saveWithdrawalAutomationPolicyAction.mock.calls[0][1] as FormData;
    expect(formData.get("version")).toBe("2");
    expect(formData.get("max_amount_tzs")).toBe("1000");
    expect(formData.get("enabled")).toBe("true");
  });

  it("renders an explicit unavailable state rather than an empty form", () => {
    // A blank switch reads as OFF. "I looked and it said off" is the one
    // wrong conclusion this card must not invite.
    render(<WithdrawalAutomationCard policy={null} />);

    expect(screen.getByText("Automatic withdrawal controls unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(screen.getByText(/going to manual approval in the meantime/i)).toBeInTheDocument();
  });

  it("names the administrator and time of the last change", () => {
    render(<WithdrawalAutomationCard policy={onPolicy} />);

    expect(screen.getByText(/admin@infinitypay\.me/)).toBeInTheDocument();
    expect(screen.getByText(/Policy version 1/)).toBeInTheDocument();
  });

  it("does not claim someone changed a policy nobody has touched", () => {
    // Seen in production on the day this shipped. updated_at is never
    // null - the row is created with one - so the freshly seeded policy
    // read "Updated 31 Oct 2026, 18:54", which looks exactly like an
    // administrator having set the limits minutes earlier. updated_by is
    // the field that actually answers the question.
    render(
      <WithdrawalAutomationCard
        policy={{ ...offPolicy, updated_at: "2026-10-31T15:54:45Z", updated_by: null, updated_by_email: null }}
      />,
    );

    expect(screen.getByText("Not changed since setup")).toBeInTheDocument();
    expect(screen.queryByText(/^Updated /)).not.toBeInTheDocument();
  });

  it("shows amounts exactly as the API sent them, to the last decimal place", () => {
    // The API normalises money to two decimal places; the card must not
    // re-render it some other way. "TZS 500,000.0" on the one field where
    // 500 and 500,000 are a keystroke apart is the bug this pins.
    render(<WithdrawalAutomationCard policy={offPolicy} />);

    expect(screen.getByPlaceholderText("e.g. 500000")).toHaveValue("500000.00");
    expect(screen.queryByText(/TZS 500,000\.0 or less/)).not.toBeInTheDocument();
    expect(screen.getByText(/TZS 500,000\.00 or less may process automatically/)).toBeInTheDocument();
  });
});

describe("compareDecimalStrings", () => {
  // Used to decide whether a change is a widening, so it must not go
  // through a float: 0.1 + 0.2 arithmetic deciding whether an operator is
  // asked to confirm a money limit would be the wrong mechanism.
  it.each([
    ["500000", "500000", 0],
    ["500001", "500000", 1],
    ["499999", "500000", -1],
    ["1000000", "999999", 1],
    ["100.10", "100.1", 0],
    ["100.11", "100.10", 1],
    ["0100", "100", 0],
    ["1000.00", "999.99", 1],
  ])("compares %s to %s as %i", (a, b, expected) => {
    expect(compareDecimalStrings(a, b)).toBe(expected);
  });

  it("treats anything unreadable as no change, so it never invents a widening", () => {
    expect(compareDecimalStrings("abc", "100")).toBe(0);
    expect(compareDecimalStrings("", "100")).toBe(0);
    expect(compareDecimalStrings(null, "100")).toBe(0);
    expect(compareDecimalStrings("100", null)).toBe(0);
  });
});
