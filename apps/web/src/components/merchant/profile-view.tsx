"use client";

import { useEffect, useState } from "react";

import { Card } from "@/components/portal/card";
import { getMyMembership, getMyMerchant, updateMyMerchantProfile } from "@/lib/portal/api";
import { USER_ROLE_LABELS } from "@/lib/portal/roles";
import type { MerchantProfile, MerchantUser } from "@/lib/portal/types";

export function ProfileView({ email }: { email: string }) {
  const [merchant, setMerchant] = useState<MerchantProfile | null>(null);
  const [membership, setMembership] = useState<MerchantUser | null>(null);
  const [loading, setLoading] = useState(true);

  const [businessName, setBusinessName] = useState("");
  const [legalName, setLegalName] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([getMyMerchant(), getMyMembership()]).then(([merchantProfile, myMembership]) => {
      setMerchant(merchantProfile);
      setMembership(myMembership);
      if (merchantProfile) {
        setBusinessName(merchantProfile.business_name);
        setLegalName(merchantProfile.legal_name ?? "");
        setContactPhone(merchantProfile.contact_phone ?? "");
      }
      setLoading(false);
    });
  }, []);

  async function handleSave(event: React.FormEvent) {
    event.preventDefault();
    if (!merchant) return;

    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const updated = await updateMyMerchantProfile(merchant.id, {
        business_name: businessName,
        legal_name: legalName,
        contact_phone: contactPhone,
      });
      setMerchant(updated);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <Card>
        <p className="text-sm text-on-surface-variant">Loading your profile…</p>
      </Card>
    );
  }

  const canEdit = membership?.role === "MERCHANT_ADMIN";

  return (
    <div className="space-y-8">
      <Card id="account" className="scroll-mt-24">
        <h3 className="text-2xl font-semibold text-on-background mb-5">My Account</h3>
        <div className="grid sm:grid-cols-3 gap-5">
          <div>
            <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-1">Full Name</p>
            <p className="text-sm text-on-background">{membership?.full_name ?? "—"}</p>
          </div>
          <div>
            <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-1">Email</p>
            <p className="text-sm text-on-background">{email}</p>
          </div>
          <div>
            <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-1">Role</p>
            <p className="text-sm text-on-background">
              {membership ? USER_ROLE_LABELS[membership.role] : "—"}
            </p>
          </div>
        </div>
      </Card>

      <Card id="profile" className="scroll-mt-24">
        <h3 className="text-2xl font-semibold text-on-background mb-5">Business Profile</h3>
        {!merchant ? (
          <p className="text-sm text-on-surface-variant">
            We couldn&apos;t load your business profile right now. Try again shortly.
          </p>
        ) : (
          <form onSubmit={handleSave} className="grid sm:grid-cols-2 gap-5">
            {!canEdit && (
              <p className="sm:col-span-2 text-xs text-on-surface-variant">
                Only a Merchant Admin can edit the business profile.
              </p>
            )}
            {saved && (
              <div className="sm:col-span-2 rounded-lg bg-primary-container/10 px-4 py-3 text-sm text-on-surface">
                Profile updated.
              </div>
            )}
            {error && (
              <div className="sm:col-span-2 rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error">
                {error}
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">ID</label>
              <p className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm font-mono text-on-surface-variant">
                {merchant.merchant_code ?? "—"}
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Business Name</label>
              <input
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm disabled:text-on-surface-variant"
                type="text"
                value={businessName}
                onChange={(event) => setBusinessName(event.target.value)}
                disabled={!canEdit}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Legal Name</label>
              <input
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm disabled:text-on-surface-variant"
                type="text"
                value={legalName}
                onChange={(event) => setLegalName(event.target.value)}
                disabled={!canEdit}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Registered Email</label>
              <input
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm text-on-surface-variant"
                value={merchant.contact_email}
                type="email"
                disabled
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Phone Number</label>
              <input
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm disabled:text-on-surface-variant"
                type="tel"
                value={contactPhone}
                onChange={(event) => setContactPhone(event.target.value)}
                disabled={!canEdit}
              />
            </div>
            {canEdit && (
              <button
                className="sm:col-span-2 w-full sm:w-auto bg-primary-container text-on-primary text-sm font-medium py-3 px-6 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
                type="submit"
                disabled={saving}
              >
                {saving ? "Saving…" : "Save Profile"}
              </button>
            )}
          </form>
        )}
      </Card>
    </div>
  );
}
