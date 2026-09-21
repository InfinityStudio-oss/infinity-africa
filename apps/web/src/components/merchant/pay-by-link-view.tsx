"use client";

import { useEffect, useRef, useState } from "react";

import { Card } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import {
  checkPayByLinkSlugAvailability,
  createPayByLink,
  getMyPayByLink,
  getMyMerchant,
  updatePayByLink,
} from "@/lib/portal/api";
import type { PayByLink } from "@/lib/portal/types";

import { PayByLinkQrCard } from "./pay-by-link-qr-card";

function whatsappShareUrl(link: PayByLink): string {
  return `https://wa.me/?text=${encodeURIComponent(
    `Pay me securely via InfinityPay: ${link.public_url}`,
  )}`;
}

const inputClass =
  "w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm";
const labelClass = "block text-sm font-medium text-on-surface-variant mb-1.5";

export function PayByLinkView() {
  const [loading, setLoading] = useState(true);
  const [link, setLink] = useState<PayByLink | null>(null);
  const [defaultName, setDefaultName] = useState("");
  const [message, setMessage] = useState<{ text: string; tone: "success" | "warning" } | null>(null);

  useEffect(() => {
    Promise.all([getMyPayByLink(), getMyMerchant()]).then(([existing, merchant]) => {
      setLink(existing);
      setDefaultName(merchant?.business_name ?? "");
      setLoading(false);
    });
  }, []);

  if (loading) {
    return (
      <div className="space-y-8">
        <PageHeader title="Pay by Link" description="A permanent link customers can pay you through, anytime." />
        <Card>
          <p className="text-sm text-on-surface-variant">Loading…</p>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Pay by Link"
        description="One permanent link for WhatsApp, Instagram, Facebook, TikTok, your website, or a printed poster QR — share it once, get paid anytime."
      />

      {message && (
        <div
          className={
            message.tone === "success"
              ? "rounded-lg bg-primary-container/10 text-primary px-4 py-3 text-sm font-medium"
              : "rounded-lg bg-[#FEFCE8] text-[#854D0E] px-4 py-3 text-sm font-medium"
          }
        >
          {message.text}
        </div>
      )}

      {!link ? (
        <CreatePanel defaultName={defaultName} onCreated={(created) => {
          setLink(created);
          setMessage({ text: "Permanent Pay by Link created.", tone: "success" });
        }} />
      ) : (
        <ManagePanel
          link={link}
          onUpdated={(updated, text) => {
            setLink(updated);
            setMessage({ text, tone: "success" });
          }}
        />
      )}
    </div>
  );
}

function CreatePanel({ defaultName, onCreated }: { defaultName: string; onCreated: (link: PayByLink) => void }) {
  // PayByLinkView only renders this panel once its own load of
  // getMyMerchant() has resolved (loading === false) and defaultName is
  // already set — so this initializer always sees the real business
  // name on first mount, no effect needed to sync it in afterwards.
  const [displayName, setDisplayName] = useState(defaultName);
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const created = await createPayByLink({
        display_name: displayName.trim() || null,
        description: description.trim() || null,
      });
      onCreated(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't create your Pay by Link. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-surface rounded-xl border border-surface-container-highest shadow-ambient p-6 space-y-5 max-w-xl"
    >
      <div>
        <h3 className="text-2xl font-semibold text-on-background mb-1">Create your Pay by Link</h3>
        <p className="text-sm text-on-surface-variant">
          We&apos;ll generate a web address like infinitypay.me/pay/your-name — you can customize it after creating.
        </p>
      </div>
      <div>
        <label className={labelClass}>Business / display name</label>
        <input
          className={inputClass}
          type="text"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          placeholder="e.g. Paul Masanja"
        />
      </div>
      <div>
        <label className={labelClass}>Description (optional)</label>
        <input
          className={inputClass}
          type="text"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="e.g. Freelance graphic design services"
          maxLength={500}
        />
      </div>
      {error && (
        <div className="rounded-lg bg-error-container/10 text-on-error-container px-4 py-3 text-sm font-medium">
          {error}
        </div>
      )}
      <button
        type="submit"
        disabled={submitting}
        className="w-full bg-primary-container text-on-primary text-sm font-medium py-3 rounded-lg hover:opacity-90 transition-opacity flex items-center justify-center gap-2 disabled:opacity-60"
      >
        <Icon name="storefront" className="text-[20px]" />
        {submitting ? "Creating…" : "Create Pay by Link"}
      </button>
    </form>
  );
}

function ManagePanel({
  link,
  onUpdated,
}: {
  link: PayByLink;
  onUpdated: (link: PayByLink, message: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [displayName, setDisplayName] = useState(link.display_name);
  const [description, setDescription] = useState(link.description ?? "");
  const [slug, setSlug] = useState(link.slug);
  const [slugWarningAcked, setSlugWarningAcked] = useState(true);
  const [slugAvailability, setSlugAvailability] = useState<{ available: boolean; reason?: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [togglingActive, setTogglingActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(link.public_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API unavailable — no-op, the URL is still visible/selectable.
    }
  }

  function startEditing() {
    setDisplayName(link.display_name);
    setDescription(link.description ?? "");
    setSlug(link.slug);
    setSlugAvailability(null);
    setSlugWarningAcked(true);
    setError(null);
    setEditing(true);
  }

  function handleSlugChange(value: string) {
    const normalized = value.trim().toLowerCase();
    setSlug(normalized);
    setSlugWarningAcked(normalized === link.slug);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (normalized === link.slug || !normalized) {
      setSlugAvailability(null);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      const result = await checkPayByLinkSlugAvailability(normalized);
      setSlugAvailability(result);
    }, 400);
  }

  async function handleSaveEdit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const updated = await updatePayByLink({
        display_name: displayName.trim(),
        description: description.trim() || undefined,
        slug: slug !== link.slug ? slug : undefined,
      });
      setEditing(false);
      onUpdated(updated, "Your Pay by Link is active.");
    } catch (err) {
      const code = (err as { code?: string } | undefined)?.code;
      setError(
        code === "conflict"
          ? "This slug is already taken."
          : err instanceof Error
            ? err.message
            : "Couldn't save your changes. Try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleToggleActive() {
    setTogglingActive(true);
    try {
      const updated = await updatePayByLink({ is_active: !link.is_active });
      onUpdated(updated, updated.is_active ? "Pay by Link enabled." : "Pay by Link disabled.");
    } finally {
      setTogglingActive(false);
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
      <div className="lg:col-span-3 bg-surface rounded-xl border border-surface-container-highest shadow-ambient p-6 space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-2xl font-semibold text-on-background mb-1">{link.display_name}</h3>
            <p className="text-sm text-on-surface-variant">
              {link.is_active ? "Active — customers can pay through this link." : "Disabled — this link is currently paused."}
            </p>
          </div>
          <button
            type="button"
            onClick={handleToggleActive}
            disabled={togglingActive}
            className={
              link.is_active
                ? "border border-error text-error text-sm font-medium py-2 px-4 rounded-lg hover:bg-error-container/10 transition-colors disabled:opacity-50"
                : "bg-primary-container text-on-primary text-sm font-medium py-2 px-4 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
            }
          >
            {link.is_active ? "Disable" : "Enable"}
          </button>
        </div>

        <div>
          <label className={labelClass}>Your permanent link</label>
          <div className="flex items-center gap-2">
            <input className={`${inputClass} flex-1 truncate`} readOnly value={link.public_url} />
            <button
              type="button"
              onClick={handleCopy}
              className="shrink-0 p-2.5 bg-primary-container/10 text-primary rounded-lg hover:bg-primary-container/20 transition-colors"
              title="Copy link"
            >
              <Icon name={copied ? "check" : "content_copy"} className="text-[20px]" />
            </button>
          </div>
          {copied && <p className="mt-1 text-xs font-medium text-primary">Pay by Link copied.</p>}
        </div>

        <div className="flex flex-col sm:flex-row gap-2.5">
          <a
            href={whatsappShareUrl(link)}
            target="_blank"
            rel="noreferrer"
            className="flex-1 flex items-center justify-center gap-2 bg-primary-container text-on-primary text-sm font-medium py-2.5 rounded-lg hover:opacity-90 transition-opacity"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
              <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z" />
              <path d="M12.001 2C6.478 2 2 6.477 2 12c0 1.802.472 3.552 1.369 5.09L2 22l5.03-1.319A9.96 9.96 0 0 0 12.001 22C17.523 22 22 17.523 22 12S17.523 2 12.001 2zm0 18.09c-1.61 0-3.19-.433-4.567-1.253l-.328-.194-3.03.795.81-2.955-.213-.34A8.075 8.075 0 0 1 3.91 12c0-4.465 3.63-8.09 8.091-8.09 4.462 0 8.09 3.625 8.09 8.09 0 4.465-3.628 8.09-8.09 8.09z" />
            </svg>
            Share on WhatsApp
          </a>
          <a
            href={link.public_url}
            target="_blank"
            rel="noreferrer"
            className="flex-1 flex items-center justify-center gap-2 border border-surface-container-highest text-on-surface text-sm font-medium py-2.5 rounded-lg hover:bg-surface-container-low transition-colors"
          >
            <Icon name="open_in_new" className="text-[18px]" />
            Preview
          </a>
          {!editing && (
            <button
              type="button"
              onClick={startEditing}
              className="flex-1 flex items-center justify-center gap-2 border border-surface-container-highest text-on-surface text-sm font-medium py-2.5 rounded-lg hover:bg-surface-container-low transition-colors"
            >
              <Icon name="edit" className="text-[18px]" />
              Edit
            </button>
          )}
        </div>

        {editing && (
          <form onSubmit={handleSaveEdit} className="space-y-4 pt-4 border-t border-surface-container-highest">
            <div>
              <label className={labelClass}>Display name</label>
              <input
                className={inputClass}
                type="text"
                required
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
              />
            </div>
            <div>
              <label className={labelClass}>Description</label>
              <input
                className={inputClass}
                type="text"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                maxLength={500}
              />
            </div>
            <div>
              <label className={labelClass}>Slug</label>
              <input
                className={inputClass}
                type="text"
                value={slug}
                onChange={(event) => handleSlugChange(event.target.value)}
              />
              {slugAvailability && !slugAvailability.available && (
                <p className="mt-1 text-xs font-medium text-error">
                  {slugAvailability.reason ?? "This slug is already taken."}
                </p>
              )}
              {slug !== link.slug && (
                <label className="mt-2 flex items-start gap-2 text-xs text-on-surface-variant">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={slugWarningAcked}
                    onChange={(event) => setSlugWarningAcked(event.target.checked)}
                  />
                  I understand any copies of my current link (/{link.slug}) will stop working once I save this
                  change.
                </label>
              )}
            </div>
            {error && (
              <div className="rounded-lg bg-error-container/10 text-on-error-container px-4 py-3 text-sm font-medium">
                {error}
              </div>
            )}
            <div className="flex gap-2.5">
              <button
                type="submit"
                disabled={submitting || (slug !== link.slug && (!slugWarningAcked || slugAvailability?.available === false))}
                className="flex-1 bg-primary-container text-on-primary text-sm font-medium py-2.5 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
              >
                {submitting ? "Saving…" : "Save changes"}
              </button>
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="flex-1 border border-surface-container-highest text-on-surface text-sm font-medium py-2.5 rounded-lg hover:bg-surface-container-low transition-colors"
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>

      <PayByLinkQrCard merchantName={link.display_name} slug={link.slug} publicUrl={link.public_url} />
    </div>
  );
}
