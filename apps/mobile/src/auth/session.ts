/** Merchant sign-in, against the same Supabase project as the portal.
 *
 * There is no mobile account system. A merchant signs in here with the
 * credentials they already use at infinitypay.me, Supabase issues the
 * same JWT the web portal gets, and the API applies the same ownership
 * and role checks to it. Signing up, resetting a password, being
 * approved or being suspended all still happen in one place.
 *
 * The session lives in the device keychain (expo-secure-store), not in
 * AsyncStorage: it is a bearer token for a merchant's money, and
 * AsyncStorage is plain files readable on a rooted device.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { createClient } from "@supabase/supabase-js";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

const SUPABASE_URL = process.env.EXPO_PUBLIC_SUPABASE_URL ?? "";
const SUPABASE_ANON_KEY = process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY ?? "";

/** SecureStore rejects values over ~2KB, and a Supabase session with a
 * long JWT can exceed that. Chunking keeps the whole session in the
 * keychain rather than silently falling back to somewhere weaker. */
const CHUNK_SIZE = 1800;

const secureStorage = {
  async getItem(key: string): Promise<string | null> {
    try {
      const count = await SecureStore.getItemAsync(`${key}__parts`);
      if (!count) return await SecureStore.getItemAsync(key);
      const parts = await Promise.all(
        Array.from({ length: Number(count) }, (_, i) => SecureStore.getItemAsync(`${key}__${i}`)),
      );
      return parts.every((p) => p !== null) ? parts.join("") : null;
    } catch {
      // A keychain that cannot be read is an unauthenticated app, not a
      // crash on launch.
      return null;
    }
  },
  async setItem(key: string, value: string): Promise<void> {
    try {
      if (value.length <= CHUNK_SIZE) {
        await SecureStore.deleteItemAsync(`${key}__parts`);
        await SecureStore.setItemAsync(key, value);
        return;
      }
      const parts = value.match(new RegExp(`.{1,${CHUNK_SIZE}}`, "g")) ?? [];
      await Promise.all(parts.map((part, i) => SecureStore.setItemAsync(`${key}__${i}`, part)));
      await SecureStore.setItemAsync(`${key}__parts`, String(parts.length));
    } catch {
      // Nothing to do but stay signed out.
    }
  },
  async removeItem(key: string): Promise<void> {
    try {
      const count = await SecureStore.getItemAsync(`${key}__parts`);
      if (count) {
        await Promise.all(
          Array.from({ length: Number(count) }, (_, i) => SecureStore.deleteItemAsync(`${key}__${i}`)),
        );
        await SecureStore.deleteItemAsync(`${key}__parts`);
      }
      await SecureStore.deleteItemAsync(key);
    } catch {
      // Already gone is the outcome we wanted.
    }
  },
};

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    // Web uses localStorage; a phone uses the keychain. Same session,
    // stored the way each platform can store it safely.
    storage: Platform.OS === "web" ? AsyncStorage : secureStorage,
    autoRefreshToken: true,
    persistSession: true,
    // No URL to detect a session in — this is not a browser.
    detectSessionInUrl: false,
  },
});

export function isSupabaseConfigured(): boolean {
  return Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);
}

/** The current access token, or null. Used only to set the
 * Authorization header; never logged, never rendered, never written
 * anywhere but the keychain. */
export async function getAccessToken(): Promise<string | null> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

export async function signIn(email: string, password: string): Promise<{ error: string | null }> {
  const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
  // Supabase's own wording is fine to show: it is deliberately vague
  // about whether the address exists.
  return { error: error?.message ?? null };
}

export async function signOut(): Promise<void> {
  await supabase.auth.signOut();
}
