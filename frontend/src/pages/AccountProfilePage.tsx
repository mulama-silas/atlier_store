import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  LockKeyhole,
  Mail,
  Phone,
  Save,
  ShieldCheck,
  UserRound,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { AccountPageHeader } from '../components/account/AccountPageHeader';
import { Badge } from '../components/modeza/Badge';
import { Button } from '../components/modeza/Button';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '../components/modeza/Card';
import { Input } from '../components/modeza/Input';

type ProfileMessage = { type: 'success' | 'error'; text: string };

export const AccountProfilePage: React.FC = () => {
  const { user, profile, profileLoading, profileError, isConfigured, updateProfile, refreshProfile } = useAuth();
  const [fullName, setFullName] = useState(profile?.fullName || '');
  const [phone, setPhone] = useState(profile?.phone || '');
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState<ProfileMessage | null>(null);

  useEffect(() => {
    if (!profile) return;
    setFullName(profile.fullName || '');
    setPhone(profile.phone || '');
  }, [profile]);

  const handleSave = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSaving || !isConfigured || !user) return;

    setMessage(null);
    setIsSaving(true);

    try {
      const result = await updateProfile({
        fullName: fullName.trim(),
        phone: phone.trim(),
      });

      setMessage(
        result.error
          ? { type: 'error', text: result.error }
          : { type: 'success', text: 'Profile details updated.' }
      );
    } catch {
      setMessage({ type: 'error', text: 'We could not save your profile. Please try again.' });
    } finally {
      setIsSaving(false);
    }
  };

  const saveNote = !isConfigured
    ? 'Profile updates are unavailable in preview mode.'
    : !user
      ? 'Sign in to update your personal information.'
      : profileLoading
        ? 'Loading your saved profile details.'
        : profileError
          ? profileError
          : 'Your name and phone are used for order updates and correspondence.';

  return (
    <section className="w-full space-y-6 sm:space-y-7" aria-label="Personal information settings">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <AccountPageHeader
          eyebrow="Account"
          title="Personal Information"
          description="Keep the details MODEZA uses for orders, delivery updates and correspondence current."
        />
        <Badge
          variant={!isConfigured ? 'warning' : user ? 'success' : 'default'}
          size="lg"
          className="w-fit shrink-0 gap-1.5"
        >
          {!isConfigured ? (
            <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
          ) : user ? (
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <LockKeyhole className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {!isConfigured ? 'Preview mode' : user ? 'Profile active' : 'Sign in required'}
        </Badge>
      </div>

      <Card className="overflow-hidden border-[#E8E5DF] shadow-sm">
        <form onSubmit={handleSave} aria-busy={isSaving}>
          <CardHeader className="flex-row items-start gap-4 border-b border-[#F3F1ED] bg-[#FAF9F6] p-5 sm:p-6">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[#F4ECE9] text-[#A2574F] ring-1 ring-[#E8E5DF]">
              <UserRound className="h-5 w-5" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2.5">
                <CardTitle className="text-xl sm:text-2xl">Your details</CardTitle>
                <Badge variant="outline" size="sm">Contact details</Badge>
              </div>
              <CardDescription className="mt-1.5 max-w-xl leading-relaxed">
                Fields marked with an asterisk are required.
              </CardDescription>
            </div>
          </CardHeader>

          <fieldset disabled={isSaving || !isConfigured || !user} className="min-w-0">
            <CardContent className="p-5 sm:p-6 lg:p-7">
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2 md:gap-6">
                <Input
                  id="profile-full-name"
                  name="fullName"
                  label="Full name"
                  type="text"
                  required
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  autoComplete="name"
                  placeholder="Elena Wambui"
                  helperText="Use the name you would like on your orders."
                  icon={<UserRound className="h-4 w-4" aria-hidden="true" />}
                  className="disabled:cursor-not-allowed disabled:bg-[#FAF9F6] disabled:text-[#827E77]"
                />
                <Input
                  id="profile-phone"
                  name="phone"
                  label="Phone number"
                  type="tel"
                  required
                  value={phone}
                  onChange={(event) => setPhone(event.target.value)}
                  autoComplete="tel"
                  placeholder="+254 700 000 000"
                  helperText="Include your country code for reliable updates."
                  icon={<Phone className="h-4 w-4" aria-hidden="true" />}
                  className="disabled:cursor-not-allowed disabled:bg-[#FAF9F6] disabled:text-[#827E77]"
                />
              </div>

              <div className="mt-6 rounded-2xl border border-[#E8E5DF] bg-[#FAF9F6] p-4 sm:p-5">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-[#A2574F] ring-1 ring-[#E8E5DF]">
                      <LockKeyhole className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-[#181716]">Sign-in email</p>
                      <p className="mt-1 text-xs leading-5 text-[#63605A]">
                        Your email identifies your account and cannot be edited here.
                      </p>
                    </div>
                  </div>
                  <Badge variant="default" size="sm" className="w-fit shrink-0">Locked</Badge>
                </div>
                <Input
                  id="profile-email"
                  name="email"
                  label="Email address"
                  type="email"
                  disabled
                  readOnly
                  value={profile?.email || user?.email || ''}
                  autoComplete="email"
                  helperText="Contact support to change the email used to sign in."
                  icon={<Mail className="h-4 w-4" aria-hidden="true" />}
                  className="mt-4 border-[#E8E5DF] bg-white text-[#827E77]"
                />
              </div>
            </CardContent>
          </fieldset>

          <CardFooter className="flex-col items-stretch gap-4 border-t border-[#F3F1ED] p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
            <div
              id="profile-save-feedback"
              className="min-w-0 flex-1"
              aria-live="polite"
              aria-atomic="true"
            >
              {message ? (
                <div
                  className={`flex items-start gap-2.5 text-sm leading-6 ${
                    message.type === 'success' ? 'text-[#2E5A44]' : 'text-[#9E332B]'
                  }`}
                  role={message.type === 'success' ? 'status' : 'alert'}
                >
                  {message.type === 'success' ? (
                    <CheckCircle2 className="mt-1 h-4 w-4 shrink-0" aria-hidden="true" />
                  ) : (
                    <AlertCircle className="mt-1 h-4 w-4 shrink-0" aria-hidden="true" />
                  )}
                  <span>{message.text}</span>
                </div>
              ) : (
                <div>
                  <p className="text-xs leading-5 text-[#63605A]">{saveNote}</p>
                  {profileError && (
                    <button type="button" onClick={() => void refreshProfile()} className="mt-1 text-xs font-medium text-[#A2574F] underline underline-offset-2">
                      Retry loading profile
                    </button>
                  )}
                </div>
              )}
            </div>
            <Button
              type="submit"
              size="md"
              isLoading={isSaving}
                disabled={!isConfigured || !user || profileLoading}
              aria-describedby="profile-save-feedback"
              aria-label={isSaving ? 'Saving profile details' : 'Save profile details'}
              className="w-full gap-2 sm:w-auto"
            >
              <Save className="h-3.5 w-3.5" aria-hidden="true" />
              Save profile
            </Button>
          </CardFooter>
        </form>
      </Card>
    </section>
  );
};
