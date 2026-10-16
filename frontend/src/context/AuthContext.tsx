import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { User } from '@supabase/supabase-js';
import { supabase } from '../services/supabaseClient';
import { api } from '../services/apiClient';
import { CustomerProfileDTO } from '../types/api';
import { audit } from '../lib/logger';

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  isConfigured: boolean;
  isPasswordRecovery: boolean;
  profile: CustomerProfileDTO | null;
  profileLoading: boolean;
  profileError: string | null;
  refreshProfile: () => Promise<CustomerProfileDTO | null>;
  signIn: (email: string, password: string) => Promise<{ error?: string; needsVerification?: boolean }>;
  signUp: (email: string, password: string, profile: { fullName: string; phone: string }) => Promise<{ error?: string; needsVerification?: boolean }>;
  requestPasswordReset: (email: string) => Promise<{ error?: string }>;
  updateRecoveredPassword: (newPassword: string) => Promise<{ error?: string }>;
  signInWithGoogle: () => Promise<{ error?: string }>;
  updateProfile: (profile: { fullName: string; phone: string }) => Promise<{ error?: string }>;
  updatePassword: (currentPassword: string, newPassword: string) => Promise<{ error?: string }>;
  signOut: () => Promise<{ error?: string }>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isPasswordRecovery, setIsPasswordRecovery] = useState(false);
  const [profile, setProfile] = useState<CustomerProfileDTO | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const profileRequestUserId = useRef<string | null>(null);

  useEffect(() => {
    if (!supabase) {
      setIsLoading(false);
      return;
    }

    let mounted = true;
    let receivedAuthEvent = false;
    const { data } = supabase.auth.onAuthStateChange((event, session) => {
      if (!mounted) return;
      receivedAuthEvent = true;
      setUser(session?.user || null);
      setIsPasswordRecovery(event === 'PASSWORD_RECOVERY');
      setIsLoading(false);
    });

    void supabase.auth.getSession()
      .then(({ data: sessionData }) => {
        if (!mounted) return;
        if (!receivedAuthEvent) setUser(sessionData.session?.user || null);
        setIsLoading(false);
      })
      .catch(() => {
        if (!mounted) return;
        if (!receivedAuthEvent) setUser(null);
        setIsLoading(false);
      });

    return () => {
      mounted = false;
      data.subscription.unsubscribe();
    };
  }, []);

  const refreshProfile = useCallback(async () => {
    if (!user) {
      profileRequestUserId.current = null;
      setProfile(null);
      setProfileError(null);
      setProfileLoading(false);
      return null;
    }

    const requestedUserId = user.id;
    profileRequestUserId.current = requestedUserId;
    setProfileLoading(true);
    setProfileError(null);
    try {
      const currentProfile = await api.getProfile();
      if (profileRequestUserId.current !== requestedUserId) return null;
      setProfile(currentProfile);
      return currentProfile;
    } catch (error) {
      if (profileRequestUserId.current !== requestedUserId) return null;
      setProfile(null);
      setProfileError(error instanceof Error ? error.message : 'Your profile could not be loaded.');
      return null;
    } finally {
      if (profileRequestUserId.current === requestedUserId) setProfileLoading(false);
    }
  }, [user]);

  useEffect(() => {
    void refreshProfile();
  }, [refreshProfile]);

  const signIn = async (email: string, password: string) => {
    if (!supabase) return { error: 'Account access is not configured yet.' };
    const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
    if (error) {
      void audit('login_failed', 'Storefront sign-in failed.', {}, { reason: error.message });
      return { error: error.message };
    }
    void audit('login', 'Storefront sign-in succeeded.', { provider: 'supabase' });
    return {};
  };

  const signUp = async (email: string, password: string, profile: { fullName: string; phone: string }) => {
    if (!supabase) return { error: 'Account access is not configured yet.' };
    if (password.length < 8) return { error: 'Password must be at least 8 characters long.' };
    if (!profile.fullName.trim() || !profile.phone.trim()) {
      return { error: 'Enter your name and phone number to create an account.' };
    }
    const { data, error } = await supabase.auth.signUp({
      email: email.trim(),
      password,
      options: {
        emailRedirectTo: typeof window !== 'undefined'
          ? `${window.location.origin}/account`
          : undefined,
        data: {
          full_name: profile.fullName.trim(),
          phone: profile.phone.trim(),
        },
      },
    });
    if (error) {
      void audit('registration_failed', 'Storefront account creation failed.', {}, { reason: error.message });
      return { error: error.message };
    }
    void audit('signup', 'New storefront account created.', { provider: 'supabase' }, {
      needsVerification: !data.session,
    });
    return { needsVerification: !data.session };
  };

  const requestPasswordReset = async (email: string) => {
    if (!supabase) return { error: 'Account access is not configured yet.' };
    const { error } = await supabase.auth.resetPasswordForEmail(email.trim(), {
      redirectTo: typeof window !== 'undefined'
        ? `${window.location.origin}/account`
        : undefined,
    });
    if (error) return { error: error.message };
    return {};
  };

  const updateRecoveredPassword = async (newPassword: string) => {
    if (!supabase) return { error: 'Account access is not configured yet.' };
    if (!isPasswordRecovery) return { error: 'Open the password reset link from your email first.' };
    if (newPassword.length < 8) return { error: 'Password must be at least 8 characters long.' };
    const { error } = await supabase.auth.updateUser({ password: newPassword });
    if (error) return { error: error.message };
    setIsPasswordRecovery(false);
    void audit('password_reset', 'Account password reset completed.');
    return {};
  };

  const signInWithGoogle = async () => {
    if (!supabase) return { error: 'Account access is not configured yet.' };
    const redirectTo = typeof window !== 'undefined'
      ? `${window.location.origin}/account/complete-profile`
      : undefined;
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo },
    });
    if (error) {
      void audit('login_failed', 'Storefront Google sign-in failed.', {}, { reason: error.message });
      return { error: error.message };
    }
    void audit('login', 'Storefront Google sign-in initiated.', { provider: 'google' });
    return {};
  };

  const signOut = async () => {
    if (!supabase) return { error: 'Account access is not configured yet.' };
    const { error } = await supabase.auth.signOut();
    if (error) return { error: error.message };
    void audit('logout', 'Storefront sign-out.');
    return {};
  };

  const updateProfile = async (profile: { fullName: string; phone: string }) => {
    if (!supabase) return { error: 'Account access is not configured yet.' };
    if (!user) return { error: 'You must be signed in to update your profile.' };
    try {
      const updatedProfile = await api.updateProfile({
        fullName: profile.fullName.trim(),
        phone: profile.phone.trim(),
      });
      setProfile(updatedProfile);
      setProfileError(null);
      void audit('profile_updated', 'Account profile updated.');
      return {};
    } catch (error) {
      const apiError = error as Error & { details?: unknown };
      if (apiError.details && typeof apiError.details === 'object') {
        const details = Object.values(apiError.details as Record<string, unknown>)
          .flatMap((value) => Array.isArray(value) ? value : [value])
          .find((value) => typeof value === 'string');
        if (typeof details === 'string') return { error: details };
      }
      return { error: error instanceof Error ? error.message : 'Your profile could not be saved.' };
    }
  };

  const updatePassword = async (currentPassword: string, newPassword: string) => {
    if (!supabase) return { error: 'Account access is not configured yet.' };
    if (!user?.email) return { error: 'You must be signed in to change your password.' };
    if (newPassword.length < 8) return { error: 'Password must be at least 8 characters long.' };
    if (newPassword === currentPassword) return { error: 'New password must be different from the current one.' };

    // Verify the current password by re-authenticating before allowing the change.
    try {
      const { data: verification, error: verifyError } = await supabase.auth.signInWithPassword({
        email: user.email,
        password: currentPassword,
      });
      if (verifyError || verification.user?.id !== user.id) {
        return { error: 'Current password is incorrect.' };
      }

      const { error } = await supabase.auth.updateUser({ password: newPassword });
      if (!error) {
        void audit('password_reset', 'Account password updated.');
      }
      return error ? { error: error.message } : {};
    } catch {
      return { error: 'We could not verify your account. Please try again.' };
    }
  };

  const currentUserProfile = user && profile?.id === user.id ? profile : null;

  return (
    <AuthContext.Provider value={{ user, isLoading, isConfigured: Boolean(supabase), isPasswordRecovery, profile: currentUserProfile, profileLoading, profileError, refreshProfile, signIn, signUp, requestPasswordReset, updateRecoveredPassword, signInWithGoogle, updateProfile, updatePassword, signOut }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};
