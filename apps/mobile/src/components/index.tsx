/** The small set of pieces every screen is built from.
 *
 * Kept in one file on purpose: there are ten of them, none is more than
 * a few lines, and a folder of ten one-component files costs more to
 * read than it saves. Split it when one grows a mind of its own.
 */

import { ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
  ViewStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, radius, spacing, typography } from "../theme";

/** Every screen's outer shell: safe area, page background, and the
 * pull-to-refresh that a merchant checking a balance will try first. */
export function AppScreen({
  children,
  refreshing,
  onRefresh,
  scroll = true,
}: {
  children: ReactNode;
  refreshing?: boolean;
  onRefresh?: () => void;
  scroll?: boolean;
}) {
  const body = scroll ? (
    <ScrollView
      contentContainerStyle={s.scrollBody}
      refreshControl={
        onRefresh ? (
          <RefreshControl refreshing={Boolean(refreshing)} onRefresh={onRefresh} tintColor={colors.primary} />
        ) : undefined
      }
    >
      {children}
    </ScrollView>
  ) : (
    <View style={s.scrollBody}>{children}</View>
  );

  return (
    <SafeAreaView style={s.screen} edges={["top", "left", "right"]}>
      {body}
    </SafeAreaView>
  );
}

export function AppCard({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  return <View style={[s.card, style]}>{children}</View>;
}

/** A headline number. `tone="brand"` is the dark emerald treatment used
 * for the figure a merchant opens the app to see. */
export function StatCard({
  label,
  value,
  caption,
  tone = "plain",
}: {
  label: string;
  value: string;
  caption?: string;
  tone?: "plain" | "brand";
}) {
  const brand = tone === "brand";
  return (
    <View style={[s.card, s.statCard, brand && s.statCardBrand]}>
      <Text style={[s.statLabel, brand && s.statLabelBrand]}>{label.toUpperCase()}</Text>
      <Text style={[s.statValue, brand && s.statValueBrand]} numberOfLines={1} adjustsFontSizeToFit>
        {value}
      </Text>
      {caption ? <Text style={[s.statCaption, brand && s.statLabelBrand]}>{caption}</Text> : null}
    </View>
  );
}

export function SectionHeader({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <View style={s.sectionHeader}>
      <Text style={s.sectionTitle}>{title}</Text>
      {action}
    </View>
  );
}

/** Says what would be here and why it is not. An empty list with no
 * explanation reads as a broken screen. */
export function EmptyState({ title, message }: { title: string; message?: string }) {
  return (
    <View style={s.centred}>
      <Text style={s.emptyTitle}>{title}</Text>
      {message ? <Text style={s.emptyMessage}>{message}</Text> : null}
    </View>
  );
}

export type StatusTone = "success" | "pending" | "failed" | "neutral";

/** Maps the API's status vocabulary onto four tones. Anything
 * unrecognised reads neutral rather than guessing — an unknown status
 * shown as green would be a lie about money. */
export function StatusBadge({ status }: { status: string }) {
  const key = (status ?? "").toLowerCase();
  let tone: StatusTone = "neutral";
  if (["successful", "success", "completed", "delivered", "active", "paid"].includes(key)) tone = "success";
  else if (["processing", "pending", "retrying", "pending_review", "pending_admin_approval"].includes(key))
    tone = "pending";
  else if (["failed", "rejected", "cancelled", "reversed", "expired", "revoked"].includes(key)) tone = "failed";

  const palette = {
    success: { bg: colors.successContainer, fg: colors.success },
    pending: { bg: colors.warningContainer, fg: colors.warning },
    failed: { bg: colors.errorContainer, fg: colors.onErrorContainer },
    neutral: { bg: colors.neutralContainer, fg: colors.neutral },
  }[tone];

  return (
    <View style={[s.badge, { backgroundColor: palette.bg }]}>
      <Text style={[s.badgeText, { color: palette.fg }]}>{humanise(status)}</Text>
    </View>
  );
}

export function PrimaryButton({
  label,
  onPress,
  disabled,
  loading,
  variant = "primary",
}: {
  label: string;
  onPress?: () => void;
  disabled?: boolean;
  loading?: boolean;
  variant?: "primary" | "outline";
}) {
  const isDisabled = Boolean(disabled || loading);
  const outline = variant === "outline";
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: isDisabled, busy: Boolean(loading) }}
      onPress={isDisabled ? undefined : onPress}
      style={({ pressed }) => [
        s.button,
        outline ? s.buttonOutline : s.buttonPrimary,
        isDisabled && s.buttonDisabled,
        pressed && !isDisabled && s.buttonPressed,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={outline ? colors.primary : colors.onPrimary} />
      ) : (
        <Text style={[s.buttonText, outline && s.buttonTextOutline]}>{label}</Text>
      )}
    </Pressable>
  );
}

/** One row of a list, optionally tappable. `right` carries the amount
 * or badge; `meta` the quiet second line. */
export function ListRow({
  title,
  meta,
  right,
  rightMeta,
  onPress,
}: {
  title: string;
  meta?: string;
  right?: ReactNode;
  rightMeta?: string;
  onPress?: () => void;
}) {
  const content = (
    <View style={s.row}>
      <View style={s.rowMain}>
        <Text style={s.rowTitle} numberOfLines={1}>
          {title}
        </Text>
        {meta ? <Text style={s.rowMeta} numberOfLines={1}>{meta}</Text> : null}
      </View>
      <View style={s.rowRight}>
        {right}
        {rightMeta ? <Text style={s.rowMeta}>{rightMeta}</Text> : null}
      </View>
    </View>
  );
  if (!onPress) return content;
  return (
    <Pressable accessibilityRole="button" onPress={onPress} style={({ pressed }) => pressed && s.rowPressed}>
      {content}
    </Pressable>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <View style={s.centred}>
      <ActivityIndicator color={colors.primary} />
      <Text style={s.emptyMessage}>{label}</Text>
    </View>
  );
}

/** Shows the server's own message. These are written for merchants —
 * see failure_reasons.py — so inventing a friendlier one here would
 * only hide what actually happened. */
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <View style={s.centred}>
      <Text style={s.errorTitle}>Something went wrong</Text>
      <Text style={s.emptyMessage}>{message}</Text>
      {onRetry ? (
        <View style={s.retry}>
          <PrimaryButton label="Try again" onPress={onRetry} variant="outline" />
        </View>
      ) : null}
    </View>
  );
}

export function humanise(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  scrollBody: { padding: spacing.lg, paddingBottom: spacing.xxl, gap: spacing.md },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.outlineVariant,
  },
  statCard: { gap: spacing.xs, flex: 1, minWidth: 150 },
  statCardBrand: { backgroundColor: colors.primary, borderColor: colors.primary },
  statLabel: { ...typography.caption, color: colors.onSurfaceVariant, letterSpacing: 0.5 },
  statLabelBrand: { color: colors.onPrimaryContainer },
  statValue: { ...typography.amount, color: colors.onSurface },
  statValueBrand: { color: colors.onPrimary },
  statCaption: { ...typography.caption, color: colors.onSurfaceVariant },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: spacing.sm,
  },
  sectionTitle: { ...typography.title, color: colors.onSurface },
  centred: { alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: spacing.sm },
  emptyTitle: { ...typography.heading, color: colors.onSurface, textAlign: "center" },
  emptyMessage: { ...typography.body, color: colors.onSurfaceVariant, textAlign: "center" },
  errorTitle: { ...typography.heading, color: colors.error, textAlign: "center" },
  retry: { marginTop: spacing.sm, alignSelf: "stretch" },
  badge: { paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderRadius: radius.pill },
  badgeText: { ...typography.caption, fontWeight: "600" },
  button: {
    borderRadius: radius.pill,
    paddingVertical: spacing.md + 2,
    paddingHorizontal: spacing.xl,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 48,
  },
  buttonPrimary: { backgroundColor: colors.primary },
  buttonOutline: { backgroundColor: "transparent", borderWidth: 1, borderColor: colors.outlineVariant },
  buttonDisabled: { opacity: 0.45 },
  buttonPressed: { opacity: 0.85 },
  buttonText: { ...typography.label, color: colors.onPrimary, fontWeight: "600" },
  buttonTextOutline: { color: colors.primary },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.outlineVariant,
  },
  rowPressed: { opacity: 0.6 },
  rowMain: { flex: 1, gap: 2 },
  rowRight: { alignItems: "flex-end", gap: 4 },
  rowTitle: { ...typography.label, color: colors.onSurface },
  rowMeta: { ...typography.caption, color: colors.onSurfaceVariant },
});
