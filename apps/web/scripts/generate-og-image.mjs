// Generates the official Open Graph / Twitter card image from the current
// brand mark — apps/web/public/brand/infinity-mark.png — so the social
// preview (Discord, WhatsApp, X, etc.) never drifts from whatever logo is
// actually used across the live app. Run with:
//
//   node apps/web/scripts/generate-og-image.mjs
//
// Re-run this whenever the brand mark or copy changes, rather than hand-editing
// the PNG in public/og/ — it's generated output, not an original asset.
// Uses next/og's ImageResponse (Satori + resvg, the same renderer Next.js
// itself uses for the opengraph-image.tsx file convention) directly under
// plain Node, per node_modules/next/dist/docs/.../opengraph-image.md's own
// "Using Node.js runtime with local assets" example — no dev server needed.
//
// Plain object element trees (not JSX) on purpose: this is a standalone
// .mjs script with no build step to strip JSX, so each node is written out
// as the same {type, props} shape JSX would otherwise compile down to —
// satori (next/og's renderer) only cares about that shape, not that it came
// from an actual React.createElement call.

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { ImageResponse } from "next/og.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const webRoot = join(__dirname, "..");

const OUTPUT_PATH = join(webRoot, "public", "og", "infinitypay-og-v1.png");
const MARK_PATH = join(webRoot, "public", "brand", "infinity-mark.png");

// Same tokens as apps/web/src/app/globals.css (--color-primary /
// --color-primary-fixed) and app/services/email.py's _email_shell — one
// brand identity across the web app, transactional emails, and this image.
const BRAND_GREEN = "#04332a";
const BRAND_ACCENT = "#9cf5c1";

function el(type, props, ...children) {
  return { type, props: { ...props, children: children.length === 1 ? children[0] : children } };
}

async function main() {
  const markBase64 = await readFile(MARK_PATH, "base64");
  const markSrc = `data:image/png;base64,${markBase64}`;

  const tree = el(
    "div",
    {
      style: {
        width: "1200px",
        height: "630px",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: BRAND_GREEN,
        fontFamily: "sans-serif",
      },
    },
    el("img", { src: markSrc, width: 168, height: 168, style: { borderRadius: 28 } }),
    el(
      "div",
      {
        style: {
          display: "flex",
          marginTop: 36,
          fontSize: 72,
          fontWeight: 700,
          color: "#ffffff",
          letterSpacing: "-0.02em",
        },
      },
      "InfinityPay",
    ),
    el(
      "div",
      {
        style: {
          display: "flex",
          marginTop: 20,
          fontSize: 30,
          color: BRAND_ACCENT,
          textAlign: "center",
        },
      },
      "Payment infrastructure for African merchants",
    ),
  );

  const image = new ImageResponse(tree, { width: 1200, height: 630 });

  const buffer = Buffer.from(await image.arrayBuffer());
  await mkdir(dirname(OUTPUT_PATH), { recursive: true });
  await writeFile(OUTPUT_PATH, buffer);
  console.log(`Wrote ${OUTPUT_PATH} (${buffer.length} bytes)`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
