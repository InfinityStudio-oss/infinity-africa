import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Merchant, PricingRuleRow } from "@/lib/admin/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/admin/live-actions", () => ({
  createMerchantPricingRuleAction: vi.fn(),
  createPlatformFallbackPricingRuleAction: vi.fn(),
  updatePricingRuleAction: vi.fn(),
  deactivatePricingRuleAction: vi.fn(),
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
    live_api_without_webhook: false,
  available_balance: "0",
  created_at: "2026-08-01T00:00:00Z",
};

const platformRule: PricingRuleRow = {
  id: "rule-1",
  merchant_id: null,
  channel: null,
  destination_code: null,
  percentage_fee: "1.000",
  flat_fee: "500.00",
  minimum_fee: null,
  maximum_fee: null,
  processor_fee_flat: "300.00",
  processor_fee_pass_through: true,
  effective_from: "2026-08-01T00:00:00Z",
  effective_to: null,
  is_active: true,
  label: "Platform default",
  created_by: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("PricingRulesView", () => {
  it("shows a merchant selector and the Add Pricing Rule action", async () => {
    const { PricingRulesView } = await import("./pricing-rules-view");
    render(
      <PricingRulesView
        merchants={[merchant]}
        platformRules={[platformRule]}
        selectedMerchantId={null}
        merchantRules={[]}
      />,
    );

    expect(screen.getByText("Juma Traders Ltd")).toBeInTheDocument();
    expect(screen.getAllByText("Add Pricing Rule").length).toBeGreaterThan(0);
    expect(screen.getByText("Platform default", { exact: false })).toBeInTheDocument();
  });

  it(
    "surfaces a failed save's error message instead of doing nothing " +
      "(regression: reported as \"Save Changes is not clickable\" — the " +
      "plain <form action> previously gave no feedback on click at all, " +
      "success or failure)",
    async () => {
      const { updatePricingRuleAction } = await import("@/lib/admin/live-actions");
      vi.mocked(updatePricingRuleAction).mockResolvedValue({
        error: "maximum_fee must be greater than or equal to minimum_fee",
      });

      const { PricingRulesView } = await import("./pricing-rules-view");
      render(
        <PricingRulesView
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
      expect(updatePricingRuleAction).toHaveBeenCalledTimes(1);
    },
  );
});
