"use client";

import { useEffect, useState } from "react";

import { Card } from "@/components/portal/card";
import { EmptyState } from "@/components/portal/empty-state";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import { createSupportTicket, listSupportTickets } from "@/lib/portal/api";
import type { SupportTicket } from "@/lib/portal/types";

const CONTACT_CARDS = [
  { icon: "mail", label: "Email", value: "info@infinitypay.me", href: "mailto:info@infinitypay.me" },
  { icon: "call", label: "Phone / WhatsApp", value: "+255 747 730 270", href: "https://wa.me/255747730270" },
  { icon: "location_on", label: "Location", value: "Mbezi Luis - Ubungo - Dar es Salaam", href: null },
];

const CATEGORIES = ["Payments", "Payouts & Withdrawals", "API & Integration", "Billing", "Other"];

const FAQS = [
  { q: "How long do Selcom Pesa withdrawals take?", a: "Most Selcom Pesa withdrawals settle in under a minute." },
  { q: "Can I customize my payment link's expiry date?", a: "Yes — set any future expiry date when creating a link." },
  { q: "What happens if an invoice isn't paid by the due date?", a: "It's automatically marked Overdue and you can resend the Pay Now link." },
  { q: "How do I switch from Sandbox to Live API keys?", a: "Generate a Live key from the API Keys page once your account is verified." },
];

export default function SupportPage() {
  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    listSupportTickets().then(setTickets);
  }, []);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!subject || !message) return;

    setSubmitting(true);
    try {
      const ticket = await createSupportTicket({ subject, category });
      setTickets((prev) => [ticket, ...prev]);
      setSubject("");
      setMessage("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader title="Support" description="We're here to help — reach out any time." />

      <section className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {CONTACT_CARDS.map((card) => {
          const content = (
            <div className="flex items-center gap-3">
              <div className="w-11 h-11 rounded-lg bg-primary-container/10 text-primary flex items-center justify-center shrink-0">
                <Icon name={card.icon} />
              </div>
              <div>
                <p className="text-xs text-on-surface-variant">{card.label}</p>
                <p className="text-sm font-medium text-on-background">{card.value}</p>
              </div>
            </div>
          );
          return card.href ? (
            <a key={card.label} href={card.href} className="bg-surface rounded-xl border border-surface-container-highest shadow-ambient p-5 hover:border-primary/50 transition-colors">
              {content}
            </a>
          ) : (
            <div key={card.label} className="bg-surface rounded-xl border border-surface-container-highest shadow-ambient p-5">
              {content}
            </div>
          );
        })}
      </section>

      <Card>
        <h3 className="text-2xl font-semibold text-on-background mb-5">Create a Support Ticket</h3>
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Subject</label>
            <input
              className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
              placeholder="Brief summary of your issue"
              type="text"
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Category</label>
            <select
              className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
            >
              {CATEGORIES.map((option) => (
                <option key={option}>{option}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Message</label>
            <textarea
              className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm resize-none"
              placeholder="Describe your issue in detail"
              rows={4}
              value={message}
              onChange={(event) => setMessage(event.target.value)}
            />
          </div>
          <button
            className="bg-primary-container text-on-primary text-sm font-medium py-3 px-6 rounded-lg hover:opacity-90 transition-opacity flex items-center justify-center gap-2 disabled:opacity-60"
            type="submit"
            disabled={submitting}
          >
            <Icon name="send" className="text-[20px]" />
            {submitting ? "Submitting…" : "Submit Ticket"}
          </button>
        </form>
      </Card>

      <Card>
        <h3 className="text-2xl font-semibold text-on-background mb-4">Your Tickets</h3>
        {tickets.length === 0 ? (
          <EmptyState
            icon="confirmation_number"
            heading="No support tickets yet"
            body="Questions you submit will show up here so you can track their status."
            actionLabel="Create Your First Ticket"
            onAction={() => document.querySelector("form")?.requestSubmit()}
          />
        ) : (
          <div className="divide-y divide-surface-container-highest">
            {tickets.map((ticket) => (
              <div key={ticket.id} className="flex items-center justify-between py-3.5 first:pt-0 last:pb-0">
                <div>
                  <p className="font-medium text-sm text-on-background">{ticket.subject}</p>
                  <p className="text-xs text-on-surface-variant">
                    {ticket.category} · {formatDateTime(ticket.created_at)}
                  </p>
                </div>
                <StatusBadge label={ticket.status === "open" ? "Open" : "Resolved"} tone={ticket.status === "open" ? "info" : "positive"} />
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <h3 className="text-2xl font-semibold text-on-background mb-4">Frequently Asked Questions</h3>
        <div className="space-y-3">
          {FAQS.map((faq) => (
            <div key={faq.q} className="bg-surface-container-low rounded-lg p-4">
              <p className="font-semibold text-sm text-on-background">{faq.q}</p>
              <p className="text-sm text-on-surface-variant mt-1">{faq.a}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
