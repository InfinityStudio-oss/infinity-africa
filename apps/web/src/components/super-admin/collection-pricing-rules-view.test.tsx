import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CollectionPricingRuleRow, Merchant } from "@/lib/admin/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/admin/live-actions", () => ({
  createMerchantCollectionPricingRuleAction: vi.fn(),
  createPlatformFallbackCollectionPricingRuleAction: vi.fn(),
  updateCollectionPricingRuleAction: vi.fn(),
  deactivateCollectionPricingRuleAction: vi.fn(),
  activateCollectionPricingRuleAction: vi.fn(),
}));

const merchant: Merchant = {
  merchant_id: "merchant-1",
  merchant_code: "27048391",
  business_name: "Juma Traders Ltd",
  owner_name: null,
  email: "juma@example.com",
  contact_phone: null,
  nature_of_business: null,
  physical_address: null,
  account_status: "active",
  kyc_status: "verified",
  api_access_suspended: false,
  production_api_eligible: true,
  available_balance: "0",
  created_at: "2026-08-01T00:00:00Z",
};

const platformRule: CollectionPricingRuleRow = {
  id: "rule-1",
  merchant_id: null,
  channel: null,
  percentage_fee: "0.800",
  flat_fee: "0.00",
  minimum_fee: null,
  maximum_fee: null,
  effective_from: "2026-08-01T00:00:00Z",
  effective_to: null,
  is_active: true,
  label: "Platform default",
  notes: null,
  created_by: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("CollectionPricingRulesView", () => {
  beforeEach(() => {
    // The action mocks are shared module-level vi.fn()s — clear call
    // history between tests so one test's "toHaveBeenCalledTimes"
    // assertion isn't polluted by a previous test's call. Does not wipe
    // a mockResolvedValue set within a given test, since each test sets
    // its own after this runs.
    vi.clearAllMocks();
  });

  it("shows the required helper text, a merchant selector, and the Add Collection Pricing Rule action", async () => {
    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[merchant]}
        platformRules={[platformRule]}
        selectedMerchantId={null}
        merchantRules={[]}
      />,
    );

    expect(
      screen.getByText("These fees apply to collection transactions only. Withdrawals do not charge business fees during MVP."),
    ).toBeInTheDocument();
    expect(screen.getByText("Collection pricing is negotiated separately with each business/customer.")).toBeInTheDocument();
    expect(screen.getByText("Juma Traders Ltd")).toBeInTheDocument();
    expect(screen.getAllByText("Add Collection Pricing Rule").length).toBeGreaterThan(0);
    expect(screen.getByText("Platform default", { exact: false })).toBeInTheDocument();
  });

  it("surfaces a failed save's error message instead of doing nothing", async () => {
    const { updateCollectionPricingRuleAction } = await import("@/lib/admin/live-actions");
    vi.mocked(updateCollectionPricingRuleAction).mockResolvedValue({
      error: "maximum_fee must be greater than or equal to minimum_fee",
    });

    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[merchant]}
        platformRules={[platformRule]}
        selectedMerchantId={null}
        merchantRules={[]}
      />,
    );

    fireEvent.click(screen.getByTitle("Edit"));
    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));

    await waitFor(() =>
      expect(screen.getByText("maximum_fee must be greater than or equal to minimum_fee")).toBeInTheDocument(),
    );
    expect(updateCollectionPricingRuleAction).toHaveBeenCalledTimes(1);
  });

  it("does not show the flat/minimum/maximum fee fields or the suggested-default copy", async () => {
    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[merchant]}
        platformRules={[platformRule]}
        selectedMerchantId={null}
        merchantRules={[]}
      />,
    );

    fireEvent.click(screen.getByTitle("Edit"));

    expect(screen.queryByText("Flat Fee (TZS, optional)")).not.toBeInTheDocument();
    expect(screen.queryByText("Minimum Fee (TZS, optional)")).not.toBeInTheDocument();
    expect(screen.queryByText("Maximum Fee (TZS, optional)")).not.toBeInTheDocument();
    expect(screen.queryByText("Suggested MVP default: 0.8% — adjust as needed.", { exact: false })).not.toBeInTheDocument();
  });

  it("edits an existing rule without resending flat/minimum/maximum fee (leaves them untouched server-side)", async () => {
    const { updateCollectionPricingRuleAction } = await import("@/lib/admin/live-actions");
    vi.mocked(updateCollectionPricingRuleAction).mockResolvedValue({ error: null });

    const ruleWithFees: CollectionPricingRuleRow = {
      ...platformRule,
      flat_fee: "500.00",
      minimum_fee: "100.00",
      maximum_fee: "9999.00",
    };
    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[merchant]}
        platformRules={[ruleWithFees]}
        selectedMerchantId={null}
        merchantRules={[]}
      />,
    );

    fireEvent.click(screen.getByTitle("Edit"));
    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));

    await waitFor(() => expect(updateCollectionPricingRuleAction).toHaveBeenCalledTimes(1));
    const submittedFormData = vi.mocked(updateCollectionPricingRuleAction).mock.calls[0][2] as FormData;
    expect(submittedFormData.get("flat_fee")).toBeNull();
    expect(submittedFormData.get("minimum_fee")).toBeNull();
    expect(submittedFormData.get("maximum_fee")).toBeNull();
  });

  it("closes the edit row after a successful save instead of leaving it open", async () => {
    const { updateCollectionPricingRuleAction } = await import("@/lib/admin/live-actions");
    vi.mocked(updateCollectionPricingRuleAction).mockResolvedValue({ error: null });

    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[merchant]}
        platformRules={[platformRule]}
        selectedMerchantId={null}
        merchantRules={[]}
      />,
    );

    fireEvent.click(screen.getByTitle("Edit"));
    expect(screen.getByRole("button", { name: "Save Changes" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));

    await waitFor(() => expect(screen.queryByRole("button", { name: "Save Changes" })).not.toBeInTheDocument());
  });

  it("shows an Activate action for a deactivated rule, not a second Deactivate", async () => {
    const inactiveRule: CollectionPricingRuleRow = { ...platformRule, is_active: false };
    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[merchant]}
        platformRules={[inactiveRule]}
        selectedMerchantId={null}
        merchantRules={[]}
      />,
    );

    expect(screen.getByTitle("Activate")).toBeInTheDocument();
    expect(screen.queryByTitle("Deactivate")).not.toBeInTheDocument();
  });
});
