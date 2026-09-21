"use client";

import { useRef, useState } from "react";

const inputClass =
  "w-full border-0 border-b border-outline-variant bg-transparent pb-2 text-sm text-on-surface placeholder-outline focus:outline-none focus:border-primary-container transition-colors";
const labelClass = "block text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2";

export function ContactForm() {
  const [fullName, setFullName] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [businessType, setBusinessType] = useState("");
  const [location, setLocation] = useState("");
  const [message, setMessage] = useState("");

  const [status, setStatus] = useState<"idle" | "loading" | "sent" | "error">("idle");
  const [error, setError] = useState("");
  const errorRef = useRef<HTMLDivElement>(null);

  function showError(message: string) {
    setError(message);
    // The submit button lives at the bottom of a long form — without this,
    // a validation/network error rendered up at the top can be scrolled
    // completely out of view, and clicking Send looks like it does nothing.
    requestAnimationFrame(() => errorRef.current?.scrollIntoView?.({ behavior: "smooth", block: "center" }));
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError("");

    if (!fullName.trim() || !email.trim() || !message.trim()) {
      showError("Please fill in your name, email, and how we can help.");
      return;
    }

    setStatus("loading");
    try {
      const context = [businessType && `Business Type: ${businessType}`, location && `Location: ${location}`]
        .filter(Boolean)
        .join("\n");
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/public/inquiries`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: fullName,
          business_name: businessName || null,
          email,
          phone: phone || null,
          message: context ? `${context}\n\n${message}` : message,
          source: "contact_page",
        }),
      });
      if (!response.ok) throw new Error("request failed");
      setStatus("sent");
    } catch {
      setStatus("error");
      showError("Something went wrong sending your message. Please try again, or email info@infinitypay.me directly.");
    }
  }

  if (status === "sent") {
    return (
      <div className="rounded-lg bg-primary-container/10 px-4 py-4 text-sm text-on-surface">
        Thanks, {fullName.split(" ")[0]} — we&apos;ve received your message and will be in touch soon.
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-7">
      {error && (
        <div ref={errorRef} className="rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error">
          {error}
        </div>
      )}

      <div className="grid sm:grid-cols-2 gap-7">
        <div>
          <label className={labelClass}>Full Name</label>
          <input
            type="text"
            required
            placeholder="e.g. Amani Mushi"
            className={inputClass}
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
          />
        </div>
        <div>
          <label className={labelClass}>Business / Company Name</label>
          <input
            type="text"
            placeholder="e.g. Amani Traders Ltd"
            className={inputClass}
            value={businessName}
            onChange={(event) => setBusinessName(event.target.value)}
          />
        </div>
      </div>
      <div className="grid sm:grid-cols-2 gap-7">
        <div>
          <label className={labelClass}>Email</label>
          <input
            type="email"
            required
            placeholder="you@business.co.tz"
            className={inputClass}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>
        <div>
          <label className={labelClass}>Phone (optional)</label>
          <input
            type="tel"
            placeholder="+255 7XX XXX XXX"
            className={inputClass}
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
          />
        </div>
      </div>
      <div>
        <label className={labelClass}>Business Type / Service Offered</label>
        <input
          type="text"
          placeholder="e.g. Online Retail, Event Planning, Delivery Service"
          className={inputClass}
          value={businessType}
          onChange={(event) => setBusinessType(event.target.value)}
        />
      </div>
      <div>
        <label className={labelClass}>Physical Location</label>
        <input
          type="text"
          placeholder="e.g. Kinondoni, Dar es Salaam"
          className={inputClass}
          value={location}
          onChange={(event) => setLocation(event.target.value)}
        />
      </div>
      <div>
        <label className={labelClass}>How Can We Help?</label>
        <textarea
          rows={3}
          required
          placeholder="Tell us about your business and what you need"
          className={`${inputClass} resize-none`}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
      </div>
      <button
        type="submit"
        disabled={status === "loading"}
        className="inline-flex items-center gap-2 bg-primary-container text-on-primary text-sm font-medium px-6 py-3.5 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
      >
        {status === "loading" ? "Sending…" : "Send Message"}
      </button>
    </form>
  );
}
