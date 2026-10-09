/** Support — the quickest way to reach a person.
 *
 * Deliberately plain links rather than an in-app ticket form. A merchant
 * whose payments are failing wants a human, and email and WhatsApp are
 * what the team actually watches. Addresses match the web contact page.
 */

import { Linking, StyleSheet, Text } from "react-native";

import { api } from "../../src/api/client";
import { useApi } from "../../src/api/useApi";
import { AppCard, AppScreen, ListRow, SectionHeader } from "../../src/components";
import { colors, spacing, typography } from "../../src/theme";

const WHATSAPP = "https://wa.me/255747730270";

export default function SupportScreen() {
  const { data } = useApi(() => api.me());

  /** The merchant code goes in the subject line so support can find the
   * account without asking. Nothing else about the merchant is sent. */
  const subject = encodeURIComponent(
    data?.merchant_code ? `Support request — ${data.merchant_code}` : "Support request",
  );

  return (
    <AppScreen>
      <SectionHeader title="Talk to us" />
      <AppCard>
        <ListRow
          title="Support"
          meta="support@infinitypay.me"
          onPress={() => void Linking.openURL(`mailto:support@infinitypay.me?subject=${subject}`)}
        />
        <ListRow
          title="Help"
          meta="help@infinitypay.me"
          onPress={() => void Linking.openURL(`mailto:help@infinitypay.me?subject=${subject}`)}
        />
        <ListRow
          title="WhatsApp"
          meta="+255 747 730 270"
          onPress={() => void Linking.openURL(WHATSAPP)}
        />
        <ListRow
          title="Business enquiries"
          meta="info@infinitypay.me"
          onPress={() => void Linking.openURL("mailto:info@infinitypay.me")}
        />
      </AppCard>

      {data?.merchant_code ? (
        <Text style={s.note}>
          Quote your merchant ID {data.merchant_code} so we can find your account straight away.
        </Text>
      ) : null}

      <AppCard style={s.notice}>
        <Text style={s.noticeTitle}>We will never ask for your keys</Text>
        <Text style={s.noticeBody}>
          InfinityPay staff will never ask for your password, your secret API key or a one-time code. Anyone
          who does is not us.
        </Text>
      </AppCard>
    </AppScreen>
  );
}

const s = StyleSheet.create({
  note: { ...typography.caption, color: colors.onSurfaceVariant, textAlign: "center" },
  notice: { backgroundColor: colors.warningContainer, borderColor: colors.warningContainer, gap: spacing.xs },
  noticeTitle: { ...typography.heading, color: colors.warning },
  noticeBody: { ...typography.body, color: colors.warning },
});
