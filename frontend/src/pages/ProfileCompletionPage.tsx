import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, ArrowLeft, Check, CheckCircle2, MapPin, Phone, Save, UserRound } from 'lucide-react';
import { useRouter } from '../router/RouterContext';
import { useAuth } from '../context/AuthContext';
import { Badge } from '../components/modeza/Badge';
import { Button } from '../components/modeza/Button';
import { Card, CardContent, CardDescription, CardHeader } from '../components/modeza/Card';
import { Input, Select as InputSelect } from '../components/modeza/Input';
import { Progress } from '../components/modeza/Progress';
import { KENYA_COUNTIES, KENYA_COUNTY_SUBCOUNTIES } from '../data/kenyaLocations';
import { saveCustomerAddress } from '../services/addressService';
import { consumePostAuthDestination } from '../utils/postAuthRedirect';

type ProfileMessage = { type: 'success' | 'error'; text: string };

const Message: React.FC<{ message: ProfileMessage | null }> = ({ message }) => {
  if (!message) return null;

  const isSuccess = message.type === 'success';
  const Icon = isSuccess ? CheckCircle2 : AlertCircle;

  return (
    <div
      className={`mt-5 flex items-start gap-3 rounded-xl border px-4 py-3 text-sm leading-6 ${
        isSuccess
          ? 'border-[#C8D8CA] bg-[#F2F6F2] text-[#2E5A44]'
          : 'border-[#F8B4B4] bg-[#FDF2F2] text-[#9E332B]'
      }`}
      role={isSuccess ? 'status' : 'alert'}
      aria-live="polite"
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{message.text}</span>
    </div>
  );
};

export const ProfileCompletionPage: React.FC = () => {
  const { navigate } = useRouter();
  const {
    user,
    isLoading: authLoading,
    profile,
    profileLoading,
    profileError,
    refreshProfile,
    updateProfile,
  } = useAuth();

  const [step, setStep] = useState<'profile' | 'address'>('profile');
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState<ProfileMessage | null>(null);

  const [fullName, setFullName] = useState('');
  const [phone, setPhone] = useState('');

  const [addressLine1, setAddressLine1] = useState('');
  const [addressLine2, setAddressLine2] = useState('');
  const [county, setCounty] = useState('');
  const [subcounty, setSubcounty] = useState('');
  const [city, setCity] = useState('');
  const [postalCode, setPostalCode] = useState('');
  const [country] = useState('Kenya');
  const profileCheckUserId = useRef<string | null>(null);

  const counties = KENYA_COUNTIES;
  const subcounties = county ? KENYA_COUNTY_SUBCOUNTIES[county] || [] : [];
  const completionValue = step === 'profile' ? 50 : 100;

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      navigate('/account');
      return;
    }
    if (profileLoading || profileCheckUserId.current === user.id) return;
    if (profileError || !profile) return;

    profileCheckUserId.current = user.id;
    setFullName(profile.fullName || user.user_metadata?.full_name || '');
    setPhone(profile.phone || user.user_metadata?.phone || '');
    if (profile.isComplete) {
      navigate(consumePostAuthDestination() || '/');
      return;
    }
    setStep('profile');
  }, [authLoading, user, profile, profileLoading, profileError, navigate]);

  const handleProfileSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isLoading) return;

    setMessage(null);
    setIsLoading(true);

    try {
      const result = await updateProfile({
        fullName: fullName.trim(),
        phone: phone.trim(),
      });

      if (result.error) {
        setMessage({ type: 'error', text: result.error });
        setIsLoading(false);
        return;
      }

      setMessage({ type: 'success', text: 'Profile details saved. Add a delivery address to finish setup.' });
      setStep('address');
      setIsLoading(false);
    } catch {
      setMessage({ type: 'error', text: 'We could not save your profile. Please try again.' });
      setIsLoading(false);
    }
  };

  const handleAddressSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isLoading) return;

    setMessage(null);
    setIsLoading(true);

    if (!user) {
      setMessage({ type: 'error', text: 'Session expired. Please sign in again.' });
      setIsLoading(false);
      return;
    }

    const addressData = {
      label: 'Home',
      firstName: fullName.split(' ')[0] || '',
      lastName: fullName.split(' ').slice(1).join(' ') || '',
      phone,
      addressLine1,
      addressLine2,
      county,
      subcounty,
      city,
      postalCode,
      country,
      isDefault: true,
    };

    try {
      await saveCustomerAddress({ ...addressData, isDefault: true });
      setMessage({ type: 'success', text: 'Profile completed successfully!' });
      setTimeout(() => {
        navigate(consumePostAuthDestination() || '/');
      }, 1500);
    } catch {
      setMessage({ type: 'error', text: 'Failed to save address. Please try again.' });
      setIsLoading(false);
    }
  };

  const handleSkipAddress = () => {
    if (isLoading) return;
    navigate(consumePostAuthDestination() || '/');
  };

  if (authLoading || (user && (profileLoading || (!profile && !profileError)))) {
    return (
      <main className="mx-auto flex min-h-[55vh] max-w-2xl items-center justify-center px-4 py-16 sm:px-6">
        <Card className="w-full max-w-md p-8 text-center shadow-sm" aria-busy="true">
          <div className="mx-auto h-9 w-9 animate-spin rounded-full border-2 border-[#E8E5DF] border-t-[#A2574F]" aria-hidden="true" />
          <p className="mt-5 font-serif text-2xl text-[#181716]">Loading profile setup</p>
          <p className="mt-2 text-sm text-[#63605A]">Checking your secure session...</p>
          <Progress value={70} className="mx-auto mt-6 max-w-xs" aria-label="Loading profile setup" />
        </Card>
      </main>
    );
  }

  if (user && (profileError || !profile)) {
    return (
      <main className="mx-auto flex min-h-[55vh] w-full max-w-2xl items-center justify-center px-4 py-10 sm:px-6">
        <Card className="w-full max-w-lg p-7 text-center sm:p-9">
          <AlertCircle className="mx-auto h-8 w-8 text-[#A2574F]" aria-hidden="true" />
          <h1 className="mt-4 font-serif text-2xl text-[#181716]">We couldn’t load your profile</h1>
          <p className="mt-2 text-sm leading-6 text-[#63605A]">{profileError || 'Your saved profile is not available right now. Please try again.'}</p>
          <div className="mt-6 flex flex-col justify-center gap-3 sm:flex-row">
            <Button type="button" onClick={() => void refreshProfile()}>Try again</Button>
            <Button type="button" variant="outline" onClick={() => navigate('/')}>Continue shopping</Button>
          </div>
        </Card>
      </main>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8 sm:px-6 sm:py-14">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => navigate('/')}
        className="-ml-4 gap-1.5 px-4 text-[11px]"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
        Return to storefront
      </Button>

      <Card className="mt-6 overflow-hidden shadow-[0_20px_60px_rgba(24,23,22,0.05)]">
        <div className="h-1.5 bg-gradient-to-r from-[#A2574F] via-[#C0857B] to-[#E68057]" />
        <CardHeader className="space-y-3 p-6 text-center sm:p-10">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#FAF9F6] ring-1 ring-[#E8E5DF]">
            <UserRound className="h-6 w-6 text-[#A2574F]" aria-hidden="true" />
          </span>
          <Badge variant={step === 'address' ? 'success' : 'outline'} size="sm" className="mx-auto">
            {step === 'profile' ? 'Step 1 of 2' : 'Step 2 of 2'}
          </Badge>
          <h1 className="font-serif text-3xl tracking-tight text-[#181716] sm:text-4xl">
            {step === 'profile' ? 'Tell us about yourself' : 'Add a delivery address'}
          </h1>
          <CardDescription className="mx-auto max-w-md text-sm leading-6">
            {step === 'profile'
              ? 'This helps us personalize your experience and speed up checkout.'
              : 'Save an address so future checkout is a single tap.'}
          </CardDescription>
        </CardHeader>

        <CardContent className="p-6 pt-0 sm:p-10 sm:pt-0">
          <div className="mb-7" aria-label="Profile completion progress">
            <div className="flex items-center justify-between gap-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#827E77]">
              <span className={step === 'profile' ? 'text-[#A2574F]' : 'text-[#2E5A44]'}>Profile</span>
              <span className={step === 'address' ? 'text-[#A2574F]' : ''}>Address</span>
            </div>
            <Progress
              value={completionValue}
              className="mt-3 h-2.5"
              aria-label="Profile completion progress"
              aria-valuetext={step === 'profile' ? 'Profile details' : 'Profile and address complete'}
            />
          </div>

          <Message message={message} />

          {step === 'profile' && (
            <form onSubmit={handleProfileSubmit} className="mt-6" aria-busy={isLoading}>
              <fieldset disabled={isLoading} className="space-y-4">
                <Input
                  id="completion-full-name"
                  label="Full name"
                  type="text"
                  required
                  placeholder="Elena Wambui"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  autoComplete="name"
                  icon={<UserRound className="h-4 w-4" />}
                />
                <Input
                  id="completion-phone"
                  label="Phone number"
                  type="tel"
                  required
                  placeholder="+254 700 000 000"
                  value={phone}
                  onChange={(event) => setPhone(event.target.value)}
                  autoComplete="tel"
                  icon={<Phone className="h-4 w-4" />}
                />
                <Button type="submit" fullWidth size="lg" isLoading={isLoading}>
                  Continue
                </Button>
              </fieldset>
            </form>
          )}

          {step === 'address' && (
            <form onSubmit={handleAddressSubmit} className="mt-6" aria-busy={isLoading}>
              <fieldset disabled={isLoading} className="space-y-4">
                <div className="rounded-xl border border-[#E8E5DF] bg-[#FAF9F6] p-4 text-sm leading-6 text-[#63605A]">
                  <div className="flex items-start gap-3">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-[#2E5A44]" aria-hidden="true" />
                    <span>Your profile details are ready. Complete the address you want us to use for delivery.</span>
                  </div>
                </div>
                <Input
                  id="completion-address-line-1"
                  label="Street address"
                  type="text"
                  required
                  placeholder="14 Riverside Drive, Westlands"
                  value={addressLine1}
                  onChange={(event) => setAddressLine1(event.target.value)}
                  autoComplete="street-address"
                  icon={<MapPin className="h-4 w-4" />}
                />
                <Input
                  id="completion-address-line-2"
                  label="Apartment, suite, etc. (optional)"
                  type="text"
                  placeholder="Apt 4B, Building C"
                  value={addressLine2}
                  onChange={(event) => setAddressLine2(event.target.value)}
                  autoComplete="address-line2"
                  icon={<MapPin className="h-4 w-4" />}
                />
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <InputSelect
                    id="completion-county"
                    label="County"
                    required
                    value={county}
                    onChange={(event) => {
                      setCounty(event.target.value);
                      setSubcounty('');
                      setCity('');
                    }}
                    options={counties.map((item) => ({ value: item, label: item }))}
                    placeholder="Select county"
                    disabled={isLoading}
                  />
                  <InputSelect
                    id="completion-subcounty"
                    label="Sub-county"
                    required
                    value={subcounty}
                    onChange={(event) => {
                      setSubcounty(event.target.value);
                      setCity('');
                    }}
                    options={subcounties.map((item) => ({ value: item, label: item }))}
                    placeholder={county ? 'Select sub-county' : 'Select a county first'}
                    disabled={!county || isLoading}
                  />
                </div>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Input
                    id="completion-city"
                    label="City / Town"
                    type="text"
                    required
                    placeholder="Westlands"
                    value={city}
                    onChange={(event) => setCity(event.target.value)}
                    autoComplete="address-level2"
                    disabled={!subcounty || isLoading}
                  />
                  <Input
                    id="completion-postal-code"
                    label="Postal code"
                    type="text"
                    placeholder="00100"
                    value={postalCode}
                    onChange={(event) => setPostalCode(event.target.value)}
                    autoComplete="postal-code"
                  />
                </div>
                <div className="mt-6 flex flex-col items-start gap-3 border-t border-[#F3F1ED] pt-6 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-xs leading-relaxed text-[#63605A]">
                    We&apos;ll save this as your default delivery address in Kenya.
                  </p>
                  <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleSkipAddress}
                      disabled={isLoading}
                      className="w-full justify-center text-xs sm:w-auto"
                    >
                      Skip for now
                    </Button>
                    <Button type="submit" isLoading={isLoading} className="w-full justify-center gap-2 text-xs sm:w-auto">
                      <Save className="h-3.5 w-3.5" aria-hidden="true" />
                      Complete setup
                    </Button>
                  </div>
                </div>
              </fieldset>
            </form>
          )}
        </CardContent>
      </Card>

      <p className="mt-6 text-center text-xs leading-5 text-[#827E77]">
        By continuing, you agree to MODEZA&apos;s{' '}
        <a href="/terms" className="underline transition-colors hover:text-[#181716]">Terms</a>{' '}
        and{' '}
        <a href="/privacy" className="underline transition-colors hover:text-[#181716]">Privacy Policy</a>.
      </p>
    </main>
  );
};
