import React, { useEffect, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  Bell,
  CheckCircle2,
  KeyRound,
  Heart,
  History,
  Info,
  Lock,
  LogOut,
  Mail,
  MapPin,
  Menu,
  Package,
  Phone,
  ShieldCheck,
  Truck,
  UserRound,
} from "lucide-react";
import { useRouter } from "../router/RouterContext";
import { useAuth } from "../context/AuthContext";
import { CollapsibleGroup } from "../components/CollapsibleGroup";
import { consumePostAuthDestination } from "../utils/postAuthRedirect";
import { Badge } from "../components/modeza/Badge";
import { Button } from "../components/modeza/Button";
import { Card } from "../components/modeza/Card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "../components/modeza/Dialog";
import { Input } from "../components/modeza/Input";
import { Progress } from "../components/modeza/Progress";
import { AccountOverviewPage } from "./AccountOverviewPage";
import { AccountOrdersPage } from "./AccountOrdersPage";
import { AccountNotificationsPage } from "./AccountNotificationsPage";
import { AccountProfilePage } from "./AccountProfilePage";
import { AccountAddressesPage } from "./AccountAddressesPage";
import { AccountSecurityPage } from "./AccountSecurityPage";

interface NavigationItem {
  label: string;
  href: string;
  icon: React.ReactNode;
}

interface AccountNavigationProps {
  activePath: string;
  mobile?: boolean;
  onNavigate: (path: string) => void;
}

const NAV_GROUPS: { label: string; items: NavigationItem[] }[] = [
  {
    label: "Account",
    items: [
      {
        label: "Overview",
        href: "/account",
        icon: <UserRound className="h-4 w-4" />,
      },
      {
        label: "Orders",
        href: "/account/orders",
        icon: <Package className="h-4 w-4" />,
      },
      {
        label: "Notifications",
        href: "/account/notifications",
        icon: <Bell className="h-4 w-4" />,
      },
    ],
  },
  {
    label: "Settings",
    items: [
      {
        label: "Personal Info",
        href: "/account/profile",
        icon: <UserRound className="h-4 w-4" />,
      },
      {
        label: "Addresses",
        href: "/account/addresses",
        icon: <MapPin className="h-4 w-4" />,
      },
      {
        label: "Security",
        href: "/account/security",
        icon: <ShieldCheck className="h-4 w-4" />,
      },
    ],
  },
  {
    label: "Storefront",
    items: [
      {
        label: "Track Order",
        href: "/track",
        icon: <Truck className="h-4 w-4" />,
      },
      {
        label: "Wishlist",
        href: "/wishlist",
        icon: <Heart className="h-4 w-4" />,
      },
      {
        label: "Recently Viewed",
        href: "/recently-viewed",
        icon: <History className="h-4 w-4" />,
      },
    ],
  },
];

const GoogleMark: React.FC = () => (
  <svg className="h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
    <path
      fill="#4285F4"
      d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
    />
    <path
      fill="#34A853"
      d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
    />
    <path
      fill="#FBBC05"
      d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
    />
    <path
      fill="#EA4335"
      d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
    />
  </svg>
);

const MemberAvatar: React.FC<{ initials: string; className?: string }> = ({
  initials,
  className = "",
}) => (
  <span
    className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[#A2574F] font-serif text-base tracking-wide text-[#FAF9F6] ${className}`}
    aria-hidden="true"
  >
    {initials}
  </span>
);

const AccountNavigation: React.FC<AccountNavigationProps> = ({
  activePath,
  mobile = false,
  onNavigate,
}) => (
  <nav
    className={mobile ? "space-y-2" : "space-y-6"}
    aria-label="Account navigation"
  >
    {NAV_GROUPS.map((group) => {
      const groupActive = group.items.some(({ href }) => href === activePath);
      const items = (
        <div className="space-y-1">
          {group.items.map(({ label, href, icon }) => {
            const active = activePath === href;
            return (
              <button
                key={href}
                type="button"
                onClick={() => onNavigate(href)}
                aria-current={active ? "page" : undefined}
                className={`flex w-full items-center rounded-xl text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] ${
                  mobile
                    ? `gap-3 px-4 py-3 text-sm ${active ? "bg-[#A2574F] font-medium text-[#FAF9F6] shadow-sm" : "text-[#63605A] hover:bg-[#F4ECE9] hover:text-[#181716]"}`
                    : `gap-3 px-3 py-2.5 text-[11px] font-semibold uppercase tracking-[0.12em] ${active ? "bg-[#A2574F] text-[#FAF9F6] shadow-xs" : "text-[#63605A] hover:bg-[#FAF9F6] hover:text-[#181716]"}`
                }`}
              >
                <span className={active ? "text-[#FAF9F6]" : "text-[#A2574F]"}>
                  {icon}
                </span>
                {label}
              </button>
            );
          })}
        </div>
      );
      if (mobile) {
        return (
          <CollapsibleGroup
            key={group.label}
            title={group.label}
            defaultOpen={groupActive}
            active={groupActive}
          >
            {items}
          </CollapsibleGroup>
        );
      }
      return (
        <div key={group.label}>
          <p className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-[#827E77]">
            {group.label}
          </p>
          {items}
        </div>
      );
    })}
  </nav>
);

type AuthMode = "signIn" | "signUp" | "forgotPassword";
type AuthMessage = { type: "error" | "info" | "success"; text: string };

const AuthFeedback: React.FC<{ message: AuthMessage | null }> = ({
  message,
}) => {
  if (!message) return null;

  const isError = message.type === "error";
  const isInfo = message.type === "info";
  const Icon = isError ? AlertCircle : isInfo ? Info : CheckCircle2;

  return (
    <div
      className={`mt-5 flex items-start gap-3 rounded-xl border px-4 py-3 text-sm leading-6 ${
        isError
          ? "border-[#F8B4B4] bg-[#FDF2F2] text-[#9E332B]"
          : isInfo
            ? "border-[#C8D4F0] bg-[#EFF2FA] text-[#3A5BA0]"
            : "border-[#C8D8CA] bg-[#F2F6F2] text-[#2E5A44]"
      }`}
      role={isError ? "alert" : "status"}
      aria-live="polite"
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{message.text}</span>
    </div>
  );
};

export const AccountPage: React.FC = () => {
  const { navigate, route } = useRouter();
  const {
    user,
    profile,
    isLoading,
    isConfigured,
    signIn,
    signUp,
    requestPasswordReset,
    isPasswordRecovery,
    updateRecoveredPassword,
    signInWithGoogle,
    signOut,
  } = useAuth();
  const [mode, setMode] = useState<AuthMode>("signIn");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [recoveryPassword, setRecoveryPassword] = useState("");
  const [recoveryPasswordConfirm, setRecoveryPasswordConfirm] = useState("");
  const [isRecoverySubmitting, setIsRecoverySubmitting] = useState(false);
  const [recoveryComplete, setRecoveryComplete] = useState(false);
  const [message, setMessage] = useState<AuthMessage | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState('');

  useEffect(() => {
    if (!user) return;
    setFullName(user.user_metadata?.full_name || "");
    setPhone(user.user_metadata?.phone || "");
  }, [user]);

  const switchMode = (nextMode: AuthMode) => {
    if (isSubmitting) return;
    setMode(nextMode);
    setMessage(null);
    setPassword("");
    setPasswordConfirm("");
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitting) return;

    setMessage(null);
    setIsSubmitting(true);

    if (mode === "signUp" && password !== passwordConfirm) {
      setMessage({ type: "error", text: "The password confirmation does not match." });
      setIsSubmitting(false);
      return;
    }

    try {
      const result: { error?: string; needsVerification?: boolean } =
        mode === "signIn"
          ? await signIn(email, password)
          : mode === "signUp"
            ? await signUp(email, password, { fullName, phone })
            : await requestPasswordReset(email);

      if (mode === "forgotPassword" && !result.error) {
        setMessage({
          type: "success",
          text: "If an account exists for that email, we’ve sent a secure password reset link.",
        });
        setIsSubmitting(false);
        return;
      }

      if (!result.error && !result.needsVerification) {
        const destination = consumePostAuthDestination();
        navigate(destination || "/");
        return;
      }

      setMessage({
        type: result.error ? "error" : "info",
        text:
          result.error ||
          (result.needsVerification
            ? "Check your email to verify your account."
            : "Welcome back to MODEZA."),
      });
      setIsSubmitting(false);
    } catch {
      setMessage({
        type: "error",
        text: "We could not complete that request. Please try again.",
      });
      setIsSubmitting(false);
    }
  };

  const handleRecoverySubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isRecoverySubmitting) return;
    if (recoveryPassword.length < 8) {
      setMessage({ type: "error", text: "Choose a password with at least 8 characters." });
      return;
    }
    if (recoveryPassword !== recoveryPasswordConfirm) {
      setMessage({ type: "error", text: "The password confirmation does not match." });
      return;
    }

    setMessage(null);
    setIsRecoverySubmitting(true);
    try {
      const result = await updateRecoveredPassword(recoveryPassword);
      if (result.error) {
        setMessage({ type: "error", text: result.error });
        return;
      }
      setRecoveryPassword("");
      setRecoveryPasswordConfirm("");
      setRecoveryComplete(true);
      setMessage({ type: "success", text: "Your password has been reset. Your account is ready to use." });
    } catch {
      setMessage({ type: "error", text: "We could not reset your password. Request a new reset link and try again." });
    } finally {
      setIsRecoverySubmitting(false);
    }
  };

  const handleGoogleSignIn = async () => {
    if (isSubmitting) return;

    setMessage(null);
    setIsSubmitting(true);

    try {
      const result = await signInWithGoogle();
      if (result.error) {
        setMessage({ type: "error", text: result.error });
        setIsSubmitting(false);
      }
    } catch {
      setMessage({
        type: "error",
        text: "Google sign-in could not be started. Please try again.",
      });
      setIsSubmitting(false);
    }
  };

  const handleSignOut = async () => {
    if (isSigningOut) return;
    setIsSigningOut(true);
    setSignOutError('');
    try {
      const result = await signOut();
      if (result.error) setSignOutError(result.error);
    } catch {
      setSignOutError('We could not sign you out. Check your connection and try again.');
    } finally {
      setIsSigningOut(false);
    }
  };

  if (route.path === "/account/complete-profile") {
    return null;
  }

  if (isLoading) {
    return (
      <main className="mx-auto flex min-h-[55vh] max-w-2xl items-center justify-center px-4 py-16 sm:px-6">
        <Card
          className="w-full max-w-md p-8 text-center shadow-sm"
          aria-busy="true"
        >
          <div
            className="mx-auto h-9 w-9 animate-spin rounded-full border-2 border-[#E8E5DF] border-t-[#A2574F]"
            aria-hidden="true"
          />
          <p className="mt-5 font-serif text-2xl text-[#181716]">
            Loading your account
          </p>
          <p className="mt-2 text-sm text-[#63605A]">
            Checking your secure session...
          </p>
          <Progress
            value={70}
            className="mx-auto mt-6 max-w-xs"
            aria-label="Loading account"
          />
        </Card>
      </main>
    );
  }

  if ((isPasswordRecovery || recoveryComplete) && user) {
    return (
      <main className="mx-auto flex min-h-[70vh] w-full max-w-2xl items-center px-4 py-10 sm:px-6">
        <Card className="mx-auto w-full max-w-lg overflow-hidden shadow-[0_24px_70px_rgba(24,23,22,0.10)]">
          <div className="h-1.5 bg-gradient-to-r from-[#A2574F] via-[#C0857B] to-[#E68057]" />
          <div className="p-6 sm:p-10">
            <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#F4ECE9] text-[#A2574F] ring-1 ring-[#E8E5DF]">
              <KeyRound className="h-6 w-6" aria-hidden="true" />
            </span>
            <header className="mt-5 space-y-2 text-center">
              <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">Account recovery</p>
              <h1 className="font-serif text-3xl tracking-tight text-[#181716]">{recoveryComplete ? "Password updated" : "Choose a new password"}</h1>
              <p className="text-sm leading-6 text-[#63605A]">{recoveryComplete ? "Your MODEZA account is secure and ready to use." : "Set a new password to secure your MODEZA account."}</p>
            </header>
            <AuthFeedback message={message} />
            {recoveryComplete ? (
              <Button type="button" fullWidth size="lg" className="mt-6" onClick={() => { setRecoveryComplete(false); navigate("/account"); }}>Continue to your account</Button>
            ) : <form onSubmit={handleRecoverySubmit} className="mt-6" aria-busy={isRecoverySubmitting}>
              <fieldset disabled={isRecoverySubmitting} className="space-y-4">
                <Input id="recovery-password" label="New password" type="password" required minLength={8} autoComplete="new-password" value={recoveryPassword} onChange={(event) => setRecoveryPassword(event.target.value)} helperText="Use at least 8 characters." icon={<Lock className="h-4 w-4" />} />
                <Input id="recovery-password-confirm" label="Confirm new password" type="password" required minLength={8} autoComplete="new-password" value={recoveryPasswordConfirm} onChange={(event) => setRecoveryPasswordConfirm(event.target.value)} icon={<Lock className="h-4 w-4" />} />
                <Button type="submit" fullWidth size="lg" isLoading={isRecoverySubmitting}>Reset password</Button>
              </fieldset>
            </form>}
          </div>
        </Card>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto w-full max-w-6xl px-4 py-7 sm:px-6 sm:py-12">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => navigate("/")}
          className="-ml-4 gap-1.5 px-4 text-[11px]"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
          Return to storefront
        </Button>

        <div className="mt-5 grid items-stretch gap-4 lg:grid-cols-[0.92fr_1.08fr] lg:gap-5">
          <section className="relative hidden min-h-[610px] overflow-hidden rounded-[28px] bg-[#281715] p-9 text-[#FAF7F2] lg:flex lg:flex-col lg:justify-between xl:p-11" aria-label="MODEZA member benefits">
            <div className="pointer-events-none absolute -right-24 -top-20 h-80 w-80 rounded-full border border-white/10" />
            <div className="pointer-events-none absolute -right-8 top-8 h-48 w-48 rounded-full border border-[#C0857B]/30" />
            <div className="pointer-events-none absolute -bottom-36 -left-24 h-80 w-80 rounded-full bg-[#A2574F]/20 blur-3xl" />
            <div className="relative">
              <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-[#D6A39A]">MODEZA <span className="px-1 text-white/30">/</span> THE MEMBER EDIT</p>
              <p className="mt-16 max-w-sm font-serif text-5xl leading-[1.08] tracking-tight xl:text-6xl">Style that feels like <span className="italic text-[#D6A39A]">you.</span></p>
              <p className="mt-5 max-w-sm text-sm leading-7 text-white/65">A more personal way to discover pieces you love and keep every order close at hand.</p>
            </div>
            <div className="relative space-y-4 border-t border-white/15 pt-6">
              <div className="flex items-center gap-3 text-sm text-white/80"><span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10 text-[#E2B6AF]"><Package className="h-4 w-4" /></span>Order updates, all in one place</div>
              <div className="flex items-center gap-3 text-sm text-white/80"><span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10 text-[#E2B6AF]"><Heart className="h-4 w-4" /></span>Save your favourites for later</div>
              <div className="flex items-center gap-3 text-sm text-white/80"><span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10 text-[#E2B6AF]"><ShieldCheck className="h-4 w-4" /></span>Your account, protected by Supabase</div>
              <p className="pt-4 text-[10px] uppercase tracking-[0.2em] text-white/35">Thoughtfully chosen. Made to be yours.</p>
            </div>
          </section>

        <Card className="overflow-hidden rounded-[28px] border-[#E8E5DF] shadow-[0_24px_70px_rgba(24,23,22,0.08)]">
          <div className="h-1.5 bg-gradient-to-r from-[#A2574F] via-[#C0857B] to-[#E68057] lg:hidden" />
          <div className="p-6 sm:p-9 lg:p-10">
            <header className="space-y-3 text-center">
              <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#F4ECE9] ring-1 ring-[#E8E5DF]">
                <UserRound
                  className="h-6 w-6 text-[#A2574F]"
                  aria-hidden="true"
                />
              </span>
              <Badge variant="outline" size="sm" className="mx-auto">
                MODEZA member
              </Badge>
              <h1 className="font-serif text-3xl tracking-tight text-[#181716] sm:text-4xl">
                {mode === "signIn" ? "Welcome back" : mode === "signUp" ? "Join MODEZA" : "Reset your password"}
              </h1>
              <p className="mx-auto max-w-sm text-sm leading-6 text-[#63605A]">
                {mode === "signIn"
                  ? "Sign in to follow your orders and save your details."
                  : mode === "signUp"
                    ? "Save your details and follow every order in one place."
                    : "Enter your email and we’ll send a secure reset link if an account exists."}
              </p>
            </header>

            <div className="mt-7">
              {!isConfigured ? (
                <div className="space-y-4">
                  <div
                    className="rounded-2xl border border-[#E7D8B3] bg-[#FFF8F0] p-5 text-sm leading-6 text-[#9A6A2B]"
                    role="status"
                  >
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <span className="font-semibold">
                        Account access is in preview mode
                      </span>
                      <Badge variant="warning" size="sm">
                        Offline
                      </Badge>
                    </div>
                    Account access will be available once Supabase browser
                    credentials are configured.
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    fullWidth
                    onClick={() => navigate("/")}
                  >
                    Continue shopping
                  </Button>
                </div>
              ) : (
                <>
                  {mode !== "forgotPassword" && <div
                    className="grid grid-cols-2 gap-1 rounded-full border border-[#E8E5DF] bg-[#FAF9F6] p-1"
                    role="group"
                    aria-label="Account access mode"
                  >
                    {(["signIn", "signUp"] as const).map((itemMode) => {
                      const selected = mode === itemMode;
                      return (
                        <button
                          key={itemMode}
                          type="button"
                          aria-pressed={selected}
                          disabled={isSubmitting}
                          onClick={() => switchMode(itemMode)}
                          className={`rounded-full px-3 py-2.5 text-[11px] font-semibold uppercase tracking-[0.14em] transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] disabled:cursor-not-allowed disabled:opacity-50 ${
                            selected
                              ? "bg-[#A2574F] text-[#FAF9F6] shadow-xs"
                              : "text-[#63605A] hover:text-[#181716]"
                          }`}
                        >
                          {itemMode === "signIn" ? "Sign in" : "Create account"}
                        </button>
                      );
                    })}
                  </div>}

                  <AuthFeedback message={message} />

                  <form
                    onSubmit={handleSubmit}
                    className="mt-6"
                    aria-busy={isSubmitting}
                  >
                    <fieldset disabled={isSubmitting} className="space-y-4">
                      {mode === "signUp" && (
                        <div className="grid gap-4 sm:grid-cols-2">
                          <Input
                            id="auth-full-name"
                            label="Full name"
                            type="text"
                            required
                            placeholder="Elena Wambui"
                            value={fullName}
                            onChange={(event) =>
                              setFullName(event.target.value)
                            }
                            autoComplete="name"
                            icon={<UserRound className="h-4 w-4" />}
                          />
                          <Input
                            id="auth-phone"
                            label="Phone number"
                            type="tel"
                            required
                            placeholder="+254 700 000 000"
                            value={phone}
                            onChange={(event) => setPhone(event.target.value)}
                            autoComplete="tel"
                            icon={<Phone className="h-4 w-4" />}
                          />
                        </div>
                      )}
                      <Input
                        id="auth-email"
                        label="Email address"
                        type="email"
                        required
                        placeholder="you@modeza.com"
                        value={email}
                        onChange={(event) => setEmail(event.target.value)}
                        autoComplete="email"
                        icon={<Mail className="h-4 w-4" />}
                      />
                      {mode !== "forgotPassword" && <Input
                        id="auth-password"
                        label="Password"
                        type="password"
                        required
                        minLength={8}
                        placeholder="••••••••"
                        value={password}
                        onChange={(event) => setPassword(event.target.value)}
                        autoComplete={
                          mode === "signIn"
                            ? "current-password"
                            : "new-password"
                        }
                        helperText={
                          mode === "signUp"
                            ? "Use at least 8 characters."
                            : undefined
                        }
                        icon={<Lock className="h-4 w-4" />}
                      />}
                      {mode === "signUp" && <Input
                        id="auth-password-confirm"
                        label="Confirm password"
                        type="password"
                        required
                        minLength={8}
                        placeholder="Re-enter your password"
                        value={passwordConfirm}
                        onChange={(event) => setPasswordConfirm(event.target.value)}
                        autoComplete="new-password"
                        icon={<Lock className="h-4 w-4" />}
                      />}
                      {mode === "signIn" && <button
                        type="button"
                        onClick={() => switchMode("forgotPassword")}
                        className="-mt-2 block text-xs font-medium text-[#A2574F] underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F]"
                      >Forgot password?</button>}
                      {mode !== "forgotPassword" && <Button
                        type="button"
                        variant="outline"
                        fullWidth
                        onClick={() => void handleGoogleSignIn()}
                        isLoading={isSubmitting}
                        className="normal-case tracking-normal"
                      >
                        <GoogleMark />
                        <span>Continue with Google</span>
                      </Button>}
                      {mode !== "forgotPassword" && <div className="relative py-1" aria-hidden="true">
                        <div className="absolute inset-0 flex items-center">
                          <div className="w-full border-t border-[#E8E5DF]" />
                        </div>
                        <div className="relative flex justify-center text-xs uppercase tracking-[0.14em] text-[#827E77]">
                          <span className="bg-white px-2">or use email</span>
                        </div>
                      </div>}
                      <Button
                        type="submit"
                        fullWidth
                        size="lg"
                        isLoading={isSubmitting}
                      >
                        {mode === "signIn" ? "Sign in" : mode === "signUp" ? "Create account" : "Send reset link"}
                      </Button>
                    </fieldset>
                  </form>

                  <button
                    type="button"
                    onClick={() =>
                      switchMode(mode === "signIn" ? "signUp" : "signIn")
                    }
                    disabled={isSubmitting}
                    className="mt-5 w-full rounded-lg py-2 text-xs text-[#63605A] transition-colors hover:text-[#181716] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {mode === "signIn"
                      ? "New to MODEZA? Create an account"
                      : mode === "signUp"
                        ? "Already have an account? Sign in"
                        : "Back to sign in"}
                  </button>
                </>
              )}
            </div>
          </div>
        </Card>
        </div>

        <p className="mt-6 text-center text-xs leading-5 text-[#827E77]">
          Secure access for your MODEZA orders, saved pieces and member details.
        </p>
      </main>
    );
  }

  const displayName: string = profile?.fullName || user.user_metadata?.full_name || "MODEZA Client";
  const userEmail = user.email || user.user_metadata?.email || "";
  const nameParts = displayName.split(/\s+/).filter(Boolean);
  const initials =
    nameParts
      .slice(0, 2)
      .map((part) => part.charAt(0))
      .join("")
      .toUpperCase() ||
    userEmail.charAt(0).toUpperCase() ||
    "M";

  const closeMobileMenu = () => setIsMobileMenuOpen(false);

  const navigateAndCloseMobile = (path: string) => {
    navigate(path);
    closeMobileMenu();
  };

  const accountContent = (() => {
    if (route.path === "/account/orders") return <AccountOrdersPage />;
    if (route.path === "/account/notifications")
      return <AccountNotificationsPage />;
    if (route.path === "/account/profile") return <AccountProfilePage />;
    if (route.path === "/account/addresses") return <AccountAddressesPage />;
    if (route.path === "/account/security") return <AccountSecurityPage />;
    if (route.path === "/account") return <AccountOverviewPage />;
    return null;
  })();

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-10 lg:px-8">
      <div className="mb-5 lg:hidden">
        <Button
          type="button"
          variant="outline"
          fullWidth
          onClick={() => setIsMobileMenuOpen(true)}
          aria-expanded={isMobileMenuOpen}
          aria-haspopup="dialog"
          aria-controls="account-mobile-navigation"
          className="justify-between px-4 text-[11px]"
        >
          <span className="flex items-center gap-2">
            <Menu className="h-4 w-4 text-[#A2574F]" aria-hidden="true" />
            Account menu
          </span>
          <span className="text-[10px] uppercase tracking-[0.12em] text-[#A2574F]">
            Browse account
          </span>
        </Button>
      </div>

      <div className="mb-6 flex items-center gap-3 rounded-2xl border border-[#E8E5DF] bg-white p-4 shadow-xs lg:hidden">
        <MemberAvatar initials={initials} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-serif text-lg leading-tight text-[#181716]">
            {displayName}
          </p>
          <p className="truncate text-xs text-[#827E77]">{userEmail}</p>
        </div>
        <Badge variant="success" size="sm">
          Customer
        </Badge>
      </div>

      <div className="grid items-start gap-8 lg:grid-cols-[17rem_minmax(0,1fr)]">
        <aside className="hidden h-[calc(100dvh-7rem)] self-start lg:sticky lg:top-24 lg:block">
          <Card className="flex h-full min-h-0 flex-col overflow-hidden shadow-sm">
            <div className="flex shrink-0 items-center gap-3.5 border-b border-[#F3F1ED] bg-[#FAF9F6] px-5 py-5">
              <MemberAvatar initials={initials} />
              <div className="min-w-0">
                <p className="truncate font-serif text-lg leading-tight text-[#181716]">
                  {displayName}
                </p>
                <p className="truncate text-xs text-[#827E77]">{userEmail}</p>
              </div>
            </div>
            <div className="account-sidebar-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 py-4">
              <AccountNavigation
                activePath={route.path}
                onNavigate={navigate}
              />
            </div>
            <div className="shrink-0 border-t border-[#F3F1ED] p-4">
              <Button
                type="button"
                variant="ghost"
                fullWidth
                onClick={() => void handleSignOut()}
                isLoading={isSigningOut}
                className="justify-start gap-3 px-3 text-[11px] text-[#9E332B] hover:bg-[#FDF2F2]"
              >
                <LogOut className="h-4 w-4" aria-hidden="true" />
                Sign out
              </Button>
            </div>
          </Card>
        </aside>

        <main id="account-content" className="min-w-0">
          {signOutError && (
            <p className="mb-5 rounded-xl border border-[#F8B4B4] bg-[#FDF2F2] px-4 py-3 text-sm text-[#9E332B]" role="alert">
              {signOutError}
            </p>
          )}
          {accountContent}
        </main>
      </div>

      <Dialog open={isMobileMenuOpen} onOpenChange={setIsMobileMenuOpen}>
        <DialogContent
          id="account-mobile-navigation"
          className="left-auto right-0 top-0 z-[500] h-dvh max-h-dvh w-[min(90vw,380px)] max-w-none translate-x-0 translate-y-0 rounded-none border-y-0 border-r-0 p-0 lg:hidden"
        >
          <div className="flex h-full min-h-0 flex-col bg-[#FAF9F6]">
            <DialogHeader className="border-b border-[#E8E5DF] px-5 py-5 pr-14 text-left sm:px-6">
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#827E77]">
                MODEZA
              </p>
              <DialogTitle className="mt-1 font-serif text-2xl text-[#181716]">
                Account
              </DialogTitle>
              <DialogDescription>
                Manage your orders, details and saved pieces.
              </DialogDescription>
            </DialogHeader>
            <div className="account-sidebar-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-6 sm:px-6">
              <div className="mb-6 flex items-center gap-3 rounded-xl border border-[#E8E5DF] bg-white p-4">
                <MemberAvatar initials={initials} />
                <div className="min-w-0">
                  <p className="truncate font-serif text-lg leading-tight text-[#181716]">
                    {displayName}
                  </p>
                  <p className="truncate text-xs text-[#827E77]">{userEmail}</p>
                </div>
              </div>
              <AccountNavigation
                activePath={route.path}
                mobile
                onNavigate={navigateAndCloseMobile}
              />
            </div>
            <div className="border-t border-[#E8E5DF] bg-white p-5 sm:px-6">
              <Button
                type="button"
                variant="ghost"
                fullWidth
                onClick={() => {
                  closeMobileMenu();
                  void handleSignOut();
                }}
                isLoading={isSigningOut}
                className="justify-start gap-3 px-3 text-[#9E332B] hover:bg-[#FDF2F2]"
              >
                <LogOut className="h-4 w-4" aria-hidden="true" />
                Sign out
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};
