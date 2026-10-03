import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    // The option now carries the merchant code too, so an admin can tell
    // two similarly-named businesses apart.
    expect(screen.getByRole("option", { name: /Juma Traders Ltd — 27048391/ })).toBeInTheDocument();
    expect(screen.getAllByText("Add Collection Pricing Rule").length).toBeGreaterThan(0);
    // Exact: the Assigned Merchant cell also reads "All businesses
    // (platform default)", so a substring match would hit both.
    expect(screen.getByText("Platform default", { exact: true })).toBeInTheDocument();
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

  // --- which business a rule is assigned to -------------------------------

  it("names the assigned business and its merchant ID on a negotiated rule", async () => {
    const merchantRule: CollectionPricingRuleRow = {
      ...platformRule,
      id: "rule-2",
      merchant_id: "merchant-1",
      label: "Negotiated 0.5%",
      percentage_fee: "0.500",
    };
    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[merchant]}
        platformRules={[]}
        selectedMerchantId="merchant-1"
        merchantRules={[merchantRule]}
      />,
    );

    const row = screen.getByText("Negotiated 0.5%").closest("tr") as HTMLElement;
    expect(within(row).getByText("Juma Traders Ltd")).toBeInTheDocument();
    expect(within(row).getByText("27048391")).toBeInTheDocument();
  });

  it("labels a platform fallback rule as applying to everyone, not to a business", async () => {
    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[merchant]}
        platformRules={[platformRule]}
        selectedMerchantId={null}
        merchantRules={[]}
      />,
    );

    const row = screen.getByText("Platform default").closest("tr") as HTMLElement;
    expect(within(row).getByText("All businesses (platform default)")).toBeInTheDocument();
    expect(within(row).queryByText("Juma Traders Ltd")).not.toBeInTheDocument();
  });

  it("reads the assignment from the rule rather than from the table it is shown in", async () => {
    // A merchant-assigned rule must never render as the platform default
    // just because of where it appears, and vice versa.
    const otherMerchant: Merchant = {
      ...merchant,
      merchant_id: "merchant-2",
      merchant_code: "27099999",
      business_name: "Bahari Foods",
    };
    const ruleForOther: CollectionPricingRuleRow = {
      ...platformRule,
      id: "rule-3",
      merchant_id: "merchant-2",
      label: "Bahari rate",
    };
    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[merchant, otherMerchant]}
        platformRules={[]}
        selectedMerchantId="merchant-1"
        merchantRules={[ruleForOther]}
      />,
    );

    const row = screen.getByText("Bahari rate").closest("tr") as HTMLElement;
    expect(within(row).getByText("Bahari Foods")).toBeInTheDocument();
    expect(within(row).getByText("27099999")).toBeInTheDocument();
  });

  it("puts the selected business's name in the section heading", async () => {
    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[merchant]}
        platformRules={[platformRule]}
        selectedMerchantId="merchant-1"
        merchantRules={[]}
      />,
    );

    expect(screen.getByText("Negotiated Collection Pricing — Juma Traders Ltd")).toBeInTheDocument();
  });

  // --- verification gates creating, never viewing -------------------------

  it("refuses to create a negotiated rate for a business that is not verified", async () => {
    const unverified: Merchant = { ...merchant, kyc_status: "pending", production_api_eligible: false };
    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[unverified]}
        platformRules={[]}
        selectedMerchantId="merchant-1"
        merchantRules={[]}
      />,
    );

    expect(screen.getByText(/is not verified and approved yet/)).toBeInTheDocument();
    // The platform fallback section still has its own Add button; the
    // business section must not.
    expect(screen.queryAllByText("Add Collection Pricing Rule")).toHaveLength(1);
  });

  it("still lists and allows editing an existing rule for a business that lost its verification", async () => {
    // The case a hard filter on the selector would break: pricing was
    // agreed while the business was verified, and it is now suspended.
    const suspended: Merchant = { ...merchant, account_status: "suspended" };
    const existing: CollectionPricingRuleRow = {
      ...platformRule,
      id: "rule-4",
      merchant_id: "merchant-1",
      label: "Agreed before suspension",
    };
    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[suspended]}
        platformRules={[]}
        selectedMerchantId="merchant-1"
        merchantRules={[existing]}
      />,
    );

    expect(screen.getByRole("option", { name: /Juma Traders Ltd/ })).toBeInTheDocument();
    expect(screen.getByText("Agreed before suspension")).toBeInTheDocument();
    expect(screen.getByTitle("Edit")).toBeInTheDocument();
  });

  it("allows creating a negotiated rate for a verified business", async () => {
    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[merchant]}
        platformRules={[]}
        selectedMerchantId="merchant-1"
        merchantRules={[]}
      />,
    );

    expect(screen.queryByText(/is not verified and approved yet/)).not.toBeInTheDocument();
    expect(screen.queryAllByText("Add Collection Pricing Rule")).toHaveLength(2);
  });

  // --- saying which rate wins ----------------------------------------------
  //
  // A Super Admin changed the platform fallback and believed it had
  // overwritten every negotiated rate. It had not — the backend stops at
  // the first matching tier — but two near-identical tables gave no way
  // to see that from the screen.

  it("spells out the order a rate is chosen in", async () => {
    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[merchant]}
        platformRules={[platformRule]}
        selectedMerchantId={null}
        merchantRules={[]}
      />,
    );

    expect(screen.getByText("How a rate is chosen")).toBeInTheDocument();
    expect(screen.getByText(/never reaches the fallback/i)).toBeInTheDocument();
  });

  it("says editing the fallback leaves negotiated rates alone", async () => {
    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[merchant]}
        platformRules={[platformRule]}
        selectedMerchantId={null}
        merchantRules={[]}
      />,
    );

    expect(screen.getByText(/does not change any negotiated rate/i)).toBeInTheDocument();
  });

  it("marks a negotiated row as overriding the fallback, on the row itself", async () => {
    const { CollectionPricingRulesView } = await import("./collection-pricing-rules-view");
    render(
      <CollectionPricingRulesView
        merchants={[merchant]}
        platformRules={[platformRule]}
        selectedMerchantId={merchant.merchant_id}
        merchantRules={[{ ...platformRule, id: "rule-2", merchant_id: merchant.merchant_id }]}
      />,
    );

    expect(screen.getByText("Negotiated — overrides the platform fallback")).toBeInTheDocument();
  });
});
