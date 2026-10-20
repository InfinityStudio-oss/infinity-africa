import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const SECRET = "7376c93bc6064782b2fd64ff040b046f0d928384b1ad4edf8f70d5607411ed1d";

vi.mock("@/lib/portal/api", () => ({
  getWebhookConfig: vi.fn().mockResolvedValue({
    webhook_url: "https://webhook.site/c888be49-d274-477d-b33d-5a587278c4ec",
    subscribed_events: null,
    has_secret: true,
    last_delivery: null,
  }),
  listWebhookEvents: vi.fn().mockResolvedValue([]),
  sendTestWebhook: vi.fn(),
  updateWebhookConfig: vi.fn(),
}));

const { getWebhookConfig, sendTestWebhook, updateWebhookConfig } = await import("@/lib/portal/api");

async function revealTheSecret() {
  vi.mocked(updateWebhookConfig).mockResolvedValue({
    webhook_url: "https://webhook.site/c888be49-d274-477d-b33d-5a587278c4ec",
    subscribed_events: null,
    has_secret: true,
    last_delivery: null,
    secret: SECRET,
  });
  const { WebhooksView } = await import("./webhooks-view");
  render(<WebhooksView />);

  fireEvent.click(await screen.findByText("Regenerate Secret"));
  await screen.findByText(SECRET);
}

describe("WebhooksView — copying the signing secret", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  });

  it("copies the whole secret, not a truncated display version", async () => {
    await revealTheSecret();

    fireEvent.click(screen.getByRole("button", { name: "Copy webhook signing secret" }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(SECRET));
  });

  it("confirms the copy, then goes back to offering one", async () => {
    await revealTheSecret();

    fireEvent.click(screen.getByRole("button", { name: "Copy webhook signing secret" }));

    await waitFor(() => expect(screen.getByText("Copied")).toBeInTheDocument());
  });

  it("leaves the secret on screen when the clipboard is unavailable", async () => {
    // An insecure origin, or an older browser: writeText rejects. The
    // secret is shown exactly once, so a failed copy must not hide it —
    // the merchant can still select it by hand.
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    await revealTheSecret();

    fireEvent.click(screen.getByRole("button", { name: "Copy webhook signing secret" }));

    await waitFor(() => expect(screen.getByText(SECRET)).toBeInTheDocument());
    expect(screen.queryByText("Copied")).not.toBeInTheDocument();
  });

  it("offers nothing to copy before a secret has been revealed", async () => {
    const { WebhooksView } = await import("./webhooks-view");
    render(<WebhooksView />);

    await screen.findByText("Webhook Configuration");
    expect(screen.queryByRole("button", { name: "Copy webhook signing secret" })).not.toBeInTheDocument();
  });
});

describe("WebhooksView — when the backend refuses", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the reason a test delivery was refused instead of swallowing it", async () => {
    // What production actually did: the backend rejects the test, the
    // rejection escapes handleTest as an unhandled promise rejection, the
    // merchant sees nothing, and Sentry records a production error.
    vi.mocked(getWebhookConfig).mockResolvedValue({
      webhook_url: "https://webhook.site/c888be49-d274-477d-b33d-5a587278c4ec",
      subscribed_events: null,
      has_secret: true,
      last_delivery: null,
    });
    vi.mocked(sendTestWebhook).mockRejectedValue(
      new Error("Configure a webhook URL before sending a test delivery"),
    );

    const { WebhooksView } = await import("./webhooks-view");
    render(<WebhooksView />);

    fireEvent.click(await screen.findByText("Send Test Webhook"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Configure a webhook URL before sending a test delivery",
    );
  });

  it("does not offer a test delivery until a webhook URL exists", async () => {
    // The empty state's own copy says "once you configure a webhook URL
    // above" — a Send Test button there could only ever fail.
    vi.mocked(getWebhookConfig).mockResolvedValue({
      webhook_url: null,
      subscribed_events: null,
      has_secret: false,
      last_delivery: null,
    });

    const { WebhooksView } = await import("./webhooks-view");
    render(<WebhooksView />);

    await screen.findByText("No webhook deliveries yet");
    // The toolbar button is rendered but disabled; the empty state must
    // not add an enabled second way in.
    const enabled = screen
      .getAllByRole("button", { name: "Send Test Webhook" })
      .filter((b) => !(b as HTMLButtonElement).disabled);
    expect(enabled).toHaveLength(0);
  });

  it("surfaces a failed save rather than losing it", async () => {
    vi.mocked(getWebhookConfig).mockResolvedValue({
      webhook_url: "https://webhook.site/c888be49-d274-477d-b33d-5a587278c4ec",
      subscribed_events: null,
      has_secret: true,
      last_delivery: null,
    });
    vi.mocked(updateWebhookConfig).mockRejectedValue(new Error("That URL is not reachable"));

    const { WebhooksView } = await import("./webhooks-view");
    render(<WebhooksView />);

    fireEvent.click(await screen.findByText("Save Configuration"));

    expect(await screen.findByRole("alert")).toHaveTextContent("That URL is not reachable");
  });
});

/**
 * A webhook URL with no signing secret is delivered unsigned: the server
 * omits X-Infinity-Signature entirely, so the receiver cannot tell a real
 * InfinityPay event from a forged POST to the same URL.
 *
 * A review on 2026-10-20 found this to be the common case rather than the
 * exception, and nothing in the product mentioned it: a secret is only
 * created when "Generate Secret" is pressed, and saving a URL never
 * prompts for one.
 *
 * Exact figures deliberately left out of this public repository; they are
 * in the private inspection report.
 */
describe("WebhooksView - warning about unsigned deliveries", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function configured({ has_secret }: { has_secret: boolean }) {
    vi.mocked(getWebhookConfig).mockResolvedValue({
      webhook_url: "https://webhook.site/c888be49-d274-477d-b33d-5a587278c4ec",
      subscribed_events: null,
      has_secret,
      last_delivery: null,
    });
  }

  it("warns when a URL is configured with no signing secret", async () => {
    configured({ has_secret: false });

    const { WebhooksView } = await import("./webhooks-view");
    render(<WebhooksView />);

    expect(await screen.findByText("These deliveries are unsigned")).toBeInTheDocument();
  });

  it("names the missing header so a developer can act on it", async () => {
    configured({ has_secret: false });

    const { WebhooksView } = await import("./webhooks-view");
    render(<WebhooksView />);

    await screen.findByText("These deliveries are unsigned");
    expect(screen.getByText("X-Infinity-Signature")).toBeInTheDocument();
  });

  it("stays quiet once a secret exists", async () => {
    configured({ has_secret: true });

    const { WebhooksView } = await import("./webhooks-view");
    render(<WebhooksView />);

    await screen.findByText("Regenerate Secret");
    expect(screen.queryByText("These deliveries are unsigned")).not.toBeInTheDocument();
  });

  it("does not warn before a URL is configured at all", async () => {
    // Nothing is being delivered yet, so there is nothing unsigned. A
    // warning here would just be noise on an empty form.
    vi.mocked(getWebhookConfig).mockResolvedValue({
      webhook_url: null,
      subscribed_events: null,
      has_secret: false,
      last_delivery: null,
    });

    const { WebhooksView } = await import("./webhooks-view");
    render(<WebhooksView />);

    await screen.findByText("Generate Secret");
    expect(screen.queryByText("These deliveries are unsigned")).not.toBeInTheDocument();
  });

  it("clears the warning as soon as the merchant generates one", async () => {
    configured({ has_secret: false });
    vi.mocked(updateWebhookConfig).mockResolvedValue({
      webhook_url: "https://webhook.site/c888be49-d274-477d-b33d-5a587278c4ec",
      subscribed_events: null,
      has_secret: true,
      last_delivery: null,
      secret: SECRET,
    });

    const { WebhooksView } = await import("./webhooks-view");
    render(<WebhooksView />);

    fireEvent.click(await screen.findByText("Generate Secret"));

    await screen.findByText(SECRET);
    expect(screen.queryByText("These deliveries are unsigned")).not.toBeInTheDocument();
  });
});
