"use client";

import { useRouter } from "next/navigation";
import { Fragment, useActionState, useEffect, useRef, useState } from "react";
import { useFormStatus } from "react-dom";
import { COLLECTION_METHOD_LABELS, CollectionMethod } from "@infinity/shared";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { formatCurrency } from "@/lib/format";
import {
  activateCollectionPricingRuleAction,
  createMerchantCollectionPricingRuleAction,
  createPlatformFallbackCollectionPricingRuleAction,
  deactivateCollectionPricingRuleAction,
  updateCollectionPricingRuleAction,
  type CollectionPricingRuleActionState,
} from "@/lib/admin/live-actions";
import type { CollectionPricingRuleRow, Merchant } from "@/lib/admin/types";

const inputClass =
  "w-full px-3 py-2 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary";
const labelClass = "block text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-1.5";

function RuleFields({ rule }: { rule?: CollectionPricingRuleRow }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <div>
        <label className={labelClass}>Channel / Method (optional)</label>
        <select name="channel" defaultValue={rule?.channel ?? ""} className={inputClass}>
          <option value="">All channels</option>
          {Object.values(CollectionMethod).map((method) => (
            <option key={method} value={method}>
              {COLLECTION_METHOD_LABELS[method]}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelClass}>Percentage Fee (%)</label>
        <input
          name="percentage_fee"
          type="number"
          step="0.001"
          min="0"
          max="100"
          defaultValue={rule?.percentage_fee ?? "0.8"}
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass}>Effective From (optional, defaults to now)</label>
        <input
          name="effective_from"
          type="datetime-local"
          defaultValue={toDatetimeLocalValue(rule?.effective_from)}
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass}>Effective To (optional)</label>
        <input
          name="effective_to"
          type="datetime-local"
          defaultValue={toDatetimeLocalValue(rule?.effective_to)}
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass}>Label (optional)</label>
        <input name="label" defaultValue={rule?.label ?? ""} placeholder="e.g. Business A negotiated rate" className={inputClass} />
      </div>
      <div className="col-span-2 sm:col-span-4">
        <label className={labelClass}>Notes / Agreement Reference (optional)</label>
        <input
          name="notes"
          defaultValue={rule?.notes ?? ""}
          placeholder="e.g. Contract #2026-114, signed 2026-08-30 — never shown to the business"
          className={inputClass}
        />
      </div>
    </div>
  );
}

function toDatetimeLocalValue(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Shows "Saving…" and disables itself while its parent <form>'s action
 * is in flight — same fix applied to the withdrawal pricing rules form
 * after "Save Changes is not clickable" turned out to mean "gives no
 * feedback either way." Must be a child of the <form>, per
 * useFormStatus's own rule. */
function SubmitButton({ children }: { children: React.ReactNode }) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="bg-primary-container text-on-primary text-sm font-medium px-6 py-2.5 rounded-lg hover:opacity-90 disabled:opacity-60"
    >
      {pending ? "Saving…" : children}
    </button>
  );
}

function ActionError({ state }: { state: CollectionPricingRuleActionState }) {
  if (!state.error) return null;
  return <div className="rounded-lg bg-error/10 px-4 py-3 text-sm text-error">{state.error}</div>;
}

function RuleCreateForm({
  action,
}: {
  action: (
    prevState: CollectionPricingRuleActionState | null,
    formData: FormData,
  ) => Promise<CollectionPricingRuleActionState>;
}) {
  const [state, formAction] = useActionState(action, { error: null });
  return (
    <form action={formAction} className="p-5 border-t border-surface-container-highest space-y-4">
      <RuleFields />
      <ActionError state={state} />
      <SubmitButton>Create Rule</SubmitButton>
    </form>
  );
}

function RuleEditForm({ rule, onSaved }: { rule: CollectionPricingRuleRow; onSaved: () => void }) {
  const [state, formAction] = useActionState(updateCollectionPricingRuleAction.bind(null, rule.id), { error: null });
  // useActionState's initial state and a real "saved with no error" state are
  // both { error: null } — indistinguishable by value alone. Skip the effect
  // on mount (state is still the initial object then) so it only fires after
  // an actual submission resolves, then close the row once that submission
  // succeeded instead of leaving it open until the admin closes it by hand.
  const isFirstRender = useRef(true);
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    if (!state.error) {
      onSaved();
    }
  }, [state, onSaved]);
  return (
    <form action={formAction} className="space-y-4">
      <RuleFields rule={rule} />
      <ActionError state={state} />
      <SubmitButton>Save Changes</SubmitButton>
    </form>
  );
}

function RuleRow({ rule, onEdit }: { rule: CollectionPricingRuleRow; onEdit: () => void }) {
  return (
    <tr className="border-t border-surface-container-highest">
      <td className={`${tdClass} text-on-surface-variant`}>{rule.label || "—"}</td>
      <td className={`${tdClass} text-on-surface-variant`}>
        {rule.channel ? COLLECTION_METHOD_LABELS[rule.channel] : "All channels"}
      </td>
      <td className={tdClass}>{rule.percentage_fee}%</td>
      <td className={tdClass}>{formatCurrency(rule.flat_fee, "TZS")}</td>
      <td className={`${tdClass} text-on-surface-variant text-xs`}>{rule.notes || "—"}</td>
      <td className={tdClass}>
        {rule.is_active ? (
          <span className="inline-flex items-center gap-1 bg-accent text-primary px-2.5 py-1 rounded-full text-xs font-semibold border border-primary/20">
            <Icon name="check" className="text-[12px] font-bold" />
            Active
          </span>
        ) : (
          <span className="bg-surface-container-highest text-on-surface-variant px-2.5 py-1 rounded-full text-xs font-semibold">
            Inactive
          </span>
        )}
      </td>
      <td className={`${tdClass} text-right whitespace-nowrap`}>
        <button onClick={onEdit} className="p-1.5 text-on-surface-variant hover:text-primary mr-1" title="Edit">
          <Icon name="edit" className="text-[18px]" />
        </button>
        {rule.is_active ? (
          <form action={deactivateCollectionPricingRuleAction.bind(null, rule.id)} className="inline">
            <button className="p-1.5 text-on-surface-variant hover:text-error" title="Deactivate">
              <Icon name="block" className="text-[18px]" />
            </button>
          </form>
        ) : (
          <form action={activateCollectionPricingRuleAction.bind(null, rule.id)} className="inline">
            <button className="p-1.5 text-on-surface-variant hover:text-primary" title="Activate">
              <Icon name="bolt" className="text-[18px]" />
            </button>
          </form>
        )}
      </td>
    </tr>
  );
}

function RuleSection({
  title,
  description,
  rules,
  createAction,
}: {
  title: string;
  description: string;
  rules: CollectionPricingRuleRow[];
  createAction: (
    prevState: CollectionPricingRuleActionState | null,
    formData: FormData,
  ) => Promise<CollectionPricingRuleActionState>;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  return (
    <Card padded={false}>
      <div className="p-5 pb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-2xl font-semibold text-on-background">{title}</h3>
          <p className="text-sm text-on-surface-variant mt-0.5">{description}</p>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate((v) => !v)}
          className="flex items-center gap-2 bg-primary-container text-on-primary px-4 py-2.5 rounded-lg text-sm font-medium hover:opacity-90 transition-opacity w-fit"
        >
          <Icon name="add" className="text-[20px]" />
          Add Collection Pricing Rule
        </button>
      </div>

      {showCreate && <RuleCreateForm action={createAction} />}

      {rules.length === 0 ? (
        <p className="p-6 text-sm text-on-surface-variant">No collection pricing rules yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[780px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Label</th>
                <th className={thClass}>Channel</th>
                <th className={thClass}>Percentage</th>
                <th className={thClass}>Flat Fee</th>
                <th className={thClass}>Notes</th>
                <th className={thClass}>Status</th>
                <th className={`${thClass} text-right`}>Actions</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {rules.map((rule) => (
                <Fragment key={rule.id}>
                  <RuleRow rule={rule} onEdit={() => setEditingId((id) => (id === rule.id ? null : rule.id))} />
                  {editingId === rule.id && (
                    <tr className="border-t border-surface-container-highest bg-surface-container-low">
                      <td className={tdClass} colSpan={7}>
                        <RuleEditForm rule={rule} onSaved={() => setEditingId(null)} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function CollectionPricingRulesView({
  merchants,
  platformRules,
  selectedMerchantId,
  merchantRules,
}: {
  merchants: Merchant[];
  platformRules: CollectionPricingRuleRow[];
  selectedMerchantId: string | null;
  merchantRules: CollectionPricingRuleRow[];
}) {
  const router = useRouter();

  return (
    <div className="space-y-8">
      <div className="rounded-lg bg-primary-container/10 text-on-background px-4 py-3 text-sm flex items-start gap-2.5">
        <Icon name="info" className="text-[18px] shrink-0 mt-0.5 text-primary" />
        <div className="space-y-1">
          <p>These fees apply to collection transactions only. Withdrawals do not charge business fees during MVP.</p>
          <p className="text-on-surface-variant">Collection pricing is negotiated separately with each business/customer.</p>
        </div>
      </div>

      <Card>
        <label className={labelClass}>Select a merchant to view or set their negotiated collection pricing</label>
        <select
          value={selectedMerchantId ?? ""}
          onChange={(event) => {
            const value = event.target.value;
            router.push(value ? `/super-admin/pricing-rules?merchant_id=${value}` : "/super-admin/pricing-rules");
          }}
          className={inputClass}
        >
          <option value="">Choose a merchant…</option>
          {merchants.map((merchant) => (
            <option key={merchant.merchant_id} value={merchant.merchant_id}>
              {merchant.business_name}
            </option>
          ))}
        </select>
      </Card>

      {selectedMerchantId && (
        <RuleSection
          title="Business Collection Pricing Rules"
          description="Negotiated collection fees for this business — take precedence over the platform default below."
          rules={merchantRules}
          createAction={createMerchantCollectionPricingRuleAction.bind(null, selectedMerchantId)}
        />
      )}

      <RuleSection
        title="Platform Fallback Collection Rules"
        description="Applied to any business with no matching business-specific rule."
        rules={platformRules}
        createAction={createPlatformFallbackCollectionPricingRuleAction}
      />
    </div>
  );
}
