import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useCart } from '../context/CartContext';
import { useOrders } from '../context/OrdersContext';
import { useRouter } from '../router/RouterContext';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/apiClient';
import { audit } from '../lib/logger';
import { setPostAuthDestination } from '../utils/postAuthRedirect';
import { getSavedAddresses } from '../utils/addressBook';
import type { SavedAddress } from '../utils/addressBook';
import type { PaymentMethod } from '../types';
import { Price } from '../components/ui/Price';
import { ProductImage } from '../components/ui/ProductImage';
import { Badge } from '../components/modeza/Badge';
import { Button } from '../components/modeza/Button';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '../components/modeza/Card';
import { Checkbox } from '../components/modeza/Checkbox';
import { Input, Select as InputSelect } from '../components/modeza/Input';
import { Progress } from '../components/modeza/Progress';
import { RadioGroup, RadioGroupItem } from '../components/modeza/RadioGroup';
import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCircle2,
  CreditCard,
  Lock,
  MapPin,
  Package,
  Send,
  ShieldCheck,
  ShoppingBag,
  Smartphone,
  Tag,
  Truck,
  User,
} from 'lucide-react';
import { formatPrice, EXPRESS_SHIPPING_COST, FREE_SHIPPING_THRESHOLD, VAT_RATE } from '../utils/currency';
import {
  KENYA_COUNTIES,
  KENYA_COUNTY_SUBCOUNTIES,
  KENYA_SUBCOUNTY_CITIES,
} from '../data/kenyaLocations';
import { motion } from 'motion/react';

interface SectionCardProps {
  step: number;
  title: string;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
  children: React.ReactNode;
}

const SectionCard: React.FC<SectionCardProps> = ({ step, title, icon, badge, children }) => (
  <motion.div
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
  >
    <Card className="overflow-hidden">
      <CardHeader className="flex-row items-center justify-between gap-4 border-b border-[#F3F1ED] p-5 sm:p-6">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#A2574F] text-xs font-bold text-[#FAF9F6]"
            aria-hidden="true"
          >
            {step}
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <CardTitle className="truncate text-lg">{title}</CardTitle>
              {icon && <span className="shrink-0 text-[#A2574F]">{icon}</span>}
            </div>
          </div>
        </div>
        {badge && <div className="shrink-0">{badge}</div>}
      </CardHeader>
      <CardContent className="p-5 pt-5 sm:p-6 sm:pt-6">{children}</CardContent>
    </Card>
  </motion.div>
);

interface LabeledInputProps {
  label: string;
  id: string;
  name: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  type?: React.HTMLInputTypeAttribute;
  placeholder?: string;
  required?: boolean;
  readOnly?: boolean;
  disabled?: boolean;
  icon?: React.ReactNode;
  autoComplete?: string;
  className?: string;
}

const LabeledInput: React.FC<LabeledInputProps> = ({
  label,
  id,
  name,
  value,
  onChange,
  type = 'text',
  placeholder,
  required,
  readOnly,
  disabled,
  icon,
  autoComplete,
  className = '',
}) => (
  <Input
    id={id}
    name={name}
    label={label}
    type={type}
    value={value}
    onChange={onChange}
    placeholder={placeholder}
    required={required}
    readOnly={readOnly}
    disabled={disabled}
    icon={icon}
    autoComplete={autoComplete}
    className={`${readOnly ? 'bg-[#FAF9F6] text-[#827E77]' : ''} ${disabled ? 'cursor-not-allowed opacity-60' : ''} ${className}`.trim()}
  />
);

interface LabeledSelectProps {
  label: string;
  id: string;
  name: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  options: string[];
  placeholder?: string;
  required?: boolean;
  disabled?: boolean;
}

const LabeledSelect: React.FC<LabeledSelectProps> = ({
  label,
  id,
  name,
  value,
  onChange,
  options,
  placeholder = 'Select...',
  required,
  disabled,
}) => (
  <InputSelect
    id={id}
    name={name}
    label={label}
    value={value}
    onChange={onChange}
    options={options.map((option) => ({ value: option, label: option }))}
    placeholder={placeholder}
    required={required}
    disabled={disabled}
  />
);

const PAYMENT_OPTIONS: Array<{ id: PaymentMethod; label: string; detail: string }> = [
  { id: 'mpesa', label: 'M-Pesa', detail: 'Prompt on your phone' },
  { id: 'card', label: 'Card', detail: 'Sandbox preview' },
  { id: 'pay_on_delivery', label: 'Pay on delivery', detail: 'Pay on handover' },
];

export const CheckoutPage: React.FC = () => {
  const { cart, subtotal, discountAmount, appliedPromo, clearCart } = useCart();
  const { createOrder } = useOrders();
  const { navigate } = useRouter();
  const { user, isLoading: isAuthLoading } = useAuth();

  const [deliveryMethod, setDeliveryMethod] = useState<'standard' | 'express'>('standard');
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>('mpesa');
  const [formData, setFormData] = useState({
    email: '',
    phone: '',
    firstName: '',
    lastName: '',
    address: '',
    apartment: '',
    country: 'Kenya',
    county: '',
    subcounty: '',
    city: '',
    postalCode: '',
    orderNotes: '',
    sameBilling: true,
  });

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [checkoutError, setCheckoutError] = useState('');
  const [paymentIntentId, setPaymentIntentId] = useState<string | null>(null);
  const [pendingOrderNumber, setPendingOrderNumber] = useState<string | null>(null);
  const [paymentPending, setPaymentPending] = useState(false);
  const [savedAddresses, setSavedAddresses] = useState<SavedAddress[]>([]);
  const [selectedAddressId, setSelectedAddressId] = useState('');
  const addressPrefillApplied = useRef(false);

  const applySavedAddress = useCallback((address: SavedAddress) => {
    setFormData((prev) => ({
      ...prev,
      firstName: address.firstName,
      lastName: address.lastName,
      phone: address.phone,
      address: address.addressLine1,
      apartment: address.addressLine2,
      county: address.county,
      subcounty: address.subcounty,
      city: address.city,
      postalCode: address.postalCode,
    }));
  }, []);

  useEffect(() => {
    if (!user || addressPrefillApplied.current) return;
    const loaded = getSavedAddresses(user.id);
    setSavedAddresses(loaded);
    const defaultAddress = loaded.find((address) => address.isDefault) ?? loaded[0];
    if (defaultAddress) {
      applySavedAddress(defaultAddress);
    }
    addressPrefillApplied.current = true;
  }, [user, applySavedAddress]);

  useEffect(() => {
    if (!user) return;

    const meta = user.user_metadata ?? {};
    const firstNameMeta =
      (meta.first_name as string | undefined) ||
      (meta.given_name as string | undefined) ||
      '';
    const lastNameMeta =
      (meta.last_name as string | undefined) ||
      (meta.surname as string | undefined) ||
      (meta.family_name as string | undefined) ||
      '';
    const fullName =
      (meta.full_name as string | undefined) ||
      (meta.name as string | undefined) ||
      (user.identities?.[0]?.identity_data?.full_name as string | undefined) ||
      '';

    const rawPhoneCandidates = [
      meta.phone as string | undefined,
      meta.telephone as string | undefined,
      meta.mobile as string | undefined,
    ];
    const phone = rawPhoneCandidates.find((candidate) => {
      if (!candidate || !candidate.trim()) return false;
      const normalized = candidate.replace(/[^+0-9\s().-]/g, '');
      return normalized.length >= 9 && normalized.length <= 18 && !/[a-z]/i.test(candidate);
    }) || '';

    const tokens = fullName.trim().split(/\s+/).filter(Boolean);
    const fallbackFirstName = tokens.shift() || '';
    const fallbackLastName = tokens.join(' ');

    setFormData((prev) => ({
      ...prev,
      email: user.email || prev.email,
      phone: phone || prev.phone,
      firstName: firstNameMeta || fallbackFirstName || prev.firstName,
      lastName: lastNameMeta || fallbackLastName || prev.lastName,
    }));
  }, [user]);

  const standardDeliveryCost = subtotal === 0 || subtotal >= FREE_SHIPPING_THRESHOLD
    ? 0
    : Math.round(subtotal * 0.2);
  const deliveryCost = deliveryMethod === 'express' ? EXPRESS_SHIPPING_COST : standardDeliveryCost;
  const taxableSubtotal = Math.max(0, subtotal - discountAmount);
  const tax = Math.round(taxableSubtotal * VAT_RATE);
  const grandTotal = taxableSubtotal + deliveryCost + tax;
  const checkoutBusy = isSubmitting || paymentPending;
  const checkoutProgress = paymentPending ? 100 : isSubmitting ? 70 : 35;
  const currentCheckoutStep = paymentPending ? 3 : isSubmitting ? 2 : 1;

  const deliveryOptions = [
    {
      id: 'standard' as const,
      title: 'Standard carbon-neutral courier',
      description: '2–4 business days',
      cost: standardDeliveryCost,
      label: 'Standard',
    },
    {
      id: 'express' as const,
      title: 'Priority dedicated air courier',
      description: 'Guaranteed next-day dispatch',
      cost: EXPRESS_SHIPPING_COST,
      label: 'Priority air',
    },
  ];

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => {
      const next = { ...prev, [name]: value };
      if (name === 'county') {
        next.subcounty = '';
        next.city = '';
      }
      if (name === 'subcounty') {
        next.city = '';
      }
      return next;
    });
  };

  const subcountiesForCounty = KENYA_COUNTY_SUBCOUNTIES[formData.county] || [];
  const citiesForSubcounty = KENYA_SUBCOUNTY_CITIES[formData.subcounty] || (formData.subcounty ? [formData.subcounty] : []);

  const handleSubmitOrder = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting || paymentPending) return;
    if (!user) {
      setPostAuthDestination('/checkout');
      navigate('/account');
      return;
    }
    setCheckoutError('');
    setIsSubmitting(true);

    try {
      void audit(
        'checkout_started',
        'Authorizing modeza order.',
        { payment_method: paymentMethod },
        {
          item_count: cart.length,
          total_minor: Math.round(grandTotal * 100),
        }
      );
      const result = await createOrder({
        customer: {
          firstName: formData.firstName,
          lastName: formData.lastName,
          email: formData.email,
          phone: formData.phone,
          addressLine1: formData.address,
          addressLine2: formData.apartment,
          city: formData.city,
          stateOrProvince: formData.county,
          postalCode: formData.postalCode,
          country: formData.country,
        },
        items: cart,
        shippingMethod: deliveryMethod,
        paymentMethod,
        discountCode: appliedPromo ? appliedPromo.code : undefined,
        notes: formData.orderNotes,
      });

      if (result.success && result.order) {
        if (paymentMethod === 'pay_on_delivery') {
          setIsSubmitting(false);
          await clearCart();
          navigate(`/order/success?order=${result.order.orderNumber}`);
          return;
        }

        const intent = paymentMethod === 'card'
          ? await api.createPaymentIntent(result.order.orderNumber, 'card')
          : await api.createPaymentIntent(result.order.orderNumber, 'mpesa', formData.phone);
        setPaymentIntentId(intent.id);
        setPendingOrderNumber(result.order.orderNumber);

        if (intent.status === 'succeeded') {
          // The sandbox gateway settles the intent synchronously, so there is
          // nothing to poll for — go straight to the confirmation page rather
          // than parking the customer behind a "Payment pending" button.
          setIsSubmitting(false);
          await clearCart();
          navigate(`/order/success?order=${result.order.orderNumber}`);
          return;
        }

        setPaymentPending(true);
        setIsSubmitting(false);
      } else {
        setIsSubmitting(false);
        setCheckoutError(result.error || 'Failed to place order. Please check inventory levels.');
        void audit('checkout_failed', 'Order placement failed.', {}, { reason: result.error });
      }
    } catch (err: unknown) {
      const errorObj = err as Error;
      setIsSubmitting(false);
      setCheckoutError(errorObj.message || 'An unexpected error occurred during checkout.');
      void audit('checkout_failed', 'Order placement failed.', {}, { message: errorObj.message });
    }
  };

  const handleConfirmPayment = async () => {
    if (!paymentIntentId || !pendingOrderNumber || isSubmitting) return;

    setCheckoutError('');
    setIsSubmitting(true);
    try {
      const order = await api.confirmPayment(pendingOrderNumber, paymentIntentId);
      await clearCart();
      navigate(`/order/success?order=${order.orderNumber}`);
    } catch (err: unknown) {
      const errorObj = err as Error;
      setCheckoutError(errorObj.message || 'Payment could not be confirmed. Please retry.');
      setIsSubmitting(false);
      void audit('payment_failed', 'Payment confirmation failed.', {}, { message: errorObj.message });
    }
  };

  useEffect(() => {
    if (!paymentPending || !pendingOrderNumber) return;
    let stopped = false;
    let pollCount = 0;
    const MAX_POLLS = 30;
    const timer = window.setInterval(async () => {
      pollCount += 1;
      try {
        const order = await api.getOrder(pendingOrderNumber);
        if (order.paymentStatus === 'paid') {
          stopped = true;
          window.clearInterval(timer);
          await clearCart();
          navigate(`/order/success?order=${order.orderNumber}`);
          return;
        }
      } catch {
      }
      if (stopped) {
        window.clearInterval(timer);
        return;
      }
      if (pollCount >= MAX_POLLS) {
        // Give up loudly. Silently stopping here left customers staring at a
        // permanently disabled "Payment pending" button with no explanation.
        window.clearInterval(timer);
        setCheckoutError(
          paymentMethod === 'card'
            ? 'Payment was not confirmed automatically. Your order has been placed — use "Confirm sandbox payment" below, or find it under My Orders.'
            : 'Payment was not confirmed automatically. Your order has been placed — use "I have completed payment" below, or find it under My Orders.'
        );
      }
    }, 4000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [paymentPending, pendingOrderNumber, paymentMethod]);

  if (cart.length === 0) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 sm:py-24">
        <Card className="border-[#E8E5DF] p-8 text-center shadow-sm sm:p-14">
          <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-full border border-[#E8E5DF] bg-[#FAF9F6] text-[#A2574F]">
            <ShoppingBag className="h-7 w-7" strokeWidth={1.5} aria-hidden="true" />
          </div>
          <Badge variant="default" size="sm" className="mb-4">Checkout is waiting</Badge>
          <h1 className="mb-3 font-serif text-2xl text-[#181716] sm:text-3xl">No items in checkout</h1>
          <p className="mx-auto mb-7 max-w-md text-sm leading-relaxed text-[#63605A]">
            Your bag is empty. Select pieces from the collection before proceeding to checkout.
          </p>
          <Button type="button" variant="primary" size="lg" onClick={() => navigate('/shop')} className="gap-2">
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            <span>Return to shop</span>
          </Button>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6 sm:py-12 lg:px-8 2xl:max-w-[88rem]">
      <header className="flex flex-col gap-5 border-b border-[#E8E5DF] pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-[#A2574F]">Secure checkout</p>
          <h1 className="font-serif text-3xl font-normal tracking-tight text-[#181716] sm:text-4xl">Complete your order</h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-[#63605A]">Review your pieces, delivery, and payment details before placing your MODEZA order.</p>
        </div>
        <Badge variant="success" size="lg" className="w-fit gap-1.5">
          <Lock className="h-3.5 w-3.5" aria-hidden="true" />
          Encrypted checkout
        </Badge>
      </header>

      <Card className="border-[#E8E5DF] bg-white shadow-sm">
        <div className="grid gap-5 p-5 sm:p-6 lg:grid-cols-[auto_1fr_auto] lg:items-center">
          <Button type="button" variant="ghost" size="sm" onClick={() => navigate('/cart')} className="w-fit gap-1.5 px-0 hover:bg-transparent hover:text-[#A2574F]">
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Return to cart</span>
          </Button>
          <div className="min-w-0">
            <div className="mb-3 flex items-center justify-between gap-3 text-xs">
              <div className="flex min-w-0 items-center gap-2 sm:gap-4">
                {[
                  { label: 'Details', number: 1 },
                  { label: 'Delivery', number: 2 },
                  { label: 'Payment', number: 3 },
                ].map((step, index) => {
                  const done = step.number < currentCheckoutStep;
                  const active = step.number === currentCheckoutStep;
                  return (
                    <React.Fragment key={step.label}>
                      <span
                        className={`flex items-center gap-1.5 font-medium ${active || done ? 'text-[#181716]' : 'text-[#827E77]'}`}
                        aria-current={active ? 'step' : undefined}
                      >
                        <span
                          className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] ${
                            done
                              ? 'bg-[#2E5A44] text-white'
                              : active
                              ? 'bg-[#A2574F] text-white'
                              : 'bg-[#F4ECE9] text-[#827E77]'
                          }`}
                          aria-hidden="true"
                        >
                          {done ? <Check className="h-3 w-3" /> : step.number}
                        </span>
                        <span className="hidden sm:inline">{step.label}</span>
                      </span>
                      {index < 2 && <span className="text-[#A29E96]" aria-hidden="true">→</span>}
                    </React.Fragment>
                  );
                })}
              </div>
              <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wider text-[#827E77]">{Math.round(checkoutProgress)}%</span>
            </div>
            <Progress value={checkoutProgress} className="h-1.5" aria-label="Checkout progress" />
          </div>
          <div className="flex items-center gap-1.5 text-xs font-medium text-[#2E5A44] lg:justify-self-end">
            <Lock className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="hidden sm:inline">Protected checkout</span>
            <span className="sm:hidden">Secure</span>
          </div>
        </div>
      </Card>

      {!user && (
        <Card className="border-[#E8E5DF] bg-white shadow-sm">
          <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[#E8E5DF] bg-[#FAF9F6] text-[#A2574F]">
                <User className="h-4.5 w-4.5" strokeWidth={1.5} aria-hidden="true" />
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-[#181716]">Sign in to place your order</p>
                <p className="mt-1 text-xs leading-relaxed text-[#63605A]">Your cart is saved. You will sign in before confirming your order and following delivery.</p>
              </div>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isAuthLoading}
              isLoading={isAuthLoading}
              onClick={() => {
                setPostAuthDestination('/checkout');
                navigate('/account');
              }}
              className="shrink-0"
            >
              Sign in
            </Button>
          </div>
        </Card>
      )}

      <form onSubmit={handleSubmitOrder}>
        <div className="grid grid-cols-1 items-start gap-8 lg:grid-cols-12 lg:gap-10">
          <div className="space-y-6 lg:col-span-7">
            <SectionCard
              step={1}
              title="Contact information"
              icon={<User className="h-4 w-4" aria-hidden="true" />}
              badge={<Badge variant="outline" size="sm">Step 1 of 3</Badge>}
            >
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <LabeledInput
                  label="Email address"
                  id="checkout-email"
                  name="email"
                  type="email"
                  required
                  value={formData.email}
                  onChange={handleInputChange}
                  placeholder="you@example.com"
                  icon={<Send className="h-3.5 w-3.5" aria-hidden="true" />}
                  autoComplete="email"
                />
                <LabeledInput
                  label="Telephone"
                  id="contact-phone"
                  name="phone"
                  type="tel"
                  required
                  value={formData.phone}
                  onChange={handleInputChange}
                  placeholder="+254 7XX XXX XXX"
                  icon={<Smartphone className="h-3.5 w-3.5" aria-hidden="true" />}
                  autoComplete="tel"
                />
              </div>
            </SectionCard>

            <SectionCard
              step={2}
              title="Shipping destination"
              icon={<MapPin className="h-4 w-4" aria-hidden="true" />}
              badge={<Badge variant="default" size="sm">Delivery details</Badge>}
            >
              {savedAddresses.length > 0 && (
                <Card className="mb-5 rounded-xl border-[#E8E5DF] bg-[#FAF9F6] p-4 shadow-none">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <p className="text-xs font-semibold uppercase tracking-wider text-[#63605A]">Saved addresses</p>
                    <Button type="button" variant="ghost" size="sm" onClick={() => navigate('/account/addresses')} className="h-7 px-2 text-xs text-[#A2574F] hover:bg-[#F7ECEA]">
                      Manage
                    </Button>
                  </div>
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                    <InputSelect
                      id="saved-address"
                      name="saved-address"
                      label="Choose a saved address"
                      value={selectedAddressId}
                      onChange={(event) => setSelectedAddressId(event.target.value)}
                      options={savedAddresses.map((address) => ({
                        value: address.id,
                        label: `${address.label || 'Saved address'} — ${address.addressLine1}, ${address.city}`,
                      }))}
                      placeholder="Choose a saved address"
                      className="text-sm"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={!selectedAddressId || checkoutBusy}
                      onClick={() => {
                        const address = savedAddresses.find((savedAddress) => savedAddress.id === selectedAddressId);
                        if (address) applySavedAddress(address);
                      }}
                      className="shrink-0"
                    >
                      Apply
                    </Button>
                  </div>
                </Card>
              )}

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <LabeledInput label="First name" id="first-name" name="firstName" required value={formData.firstName} onChange={handleInputChange} placeholder="Jane" autoComplete="given-name" />
                <LabeledInput label="Last name" id="last-name" name="lastName" required value={formData.lastName} onChange={handleInputChange} placeholder="Doe" autoComplete="family-name" />
              </div>

              <div className="mt-4 space-y-4">
                <LabeledInput label="Street address" id="street-address" name="address" required value={formData.address} onChange={handleInputChange} placeholder="123 Moi Avenue" icon={<MapPin className="h-3.5 w-3.5" aria-hidden="true" />} autoComplete="street-address" />
                <LabeledInput label="Apartment, suite, unit (optional)" id="apartment" name="apartment" value={formData.apartment} onChange={handleInputChange} placeholder="Apt 4B" autoComplete="address-line2" />
              </div>

              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <LabeledInput label="Country" id="country" name="country" required value={formData.country} onChange={handleInputChange} readOnly autoComplete="country-name" />
                <LabeledSelect
                  label="County"
                  id="county"
                  name="county"
                  required
                  value={formData.county}
                  onChange={handleInputChange}
                  options={KENYA_COUNTIES}
                  placeholder="Select county"
                />
              </div>

              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <LabeledSelect
                  label="Subcounty"
                  id="subcounty"
                  name="subcounty"
                  required
                  value={formData.subcounty}
                  onChange={handleInputChange}
                  options={subcountiesForCounty}
                  placeholder="Select subcounty"
                  disabled={!formData.county || subcountiesForCounty.length === 0}
                />
                <LabeledSelect
                  label="City"
                  id="city"
                  name="city"
                  required
                  value={formData.city}
                  onChange={handleInputChange}
                  options={citiesForSubcounty}
                  placeholder="Select city"
                  disabled={!formData.subcounty || citiesForSubcounty.length === 0}
                />
              </div>

              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <LabeledInput label="Postal code" id="postal-code" name="postalCode" required value={formData.postalCode} onChange={handleInputChange} placeholder="00100" autoComplete="postal-code" />
                <LabeledInput label="Phone number" id="shipping-phone" name="phone" type="tel" required value={formData.phone} onChange={handleInputChange} placeholder="+254 7XX XXX XXX" icon={<Smartphone className="h-3.5 w-3.5" aria-hidden="true" />} autoComplete="tel" />
              </div>
            </SectionCard>

            <SectionCard
              step={3}
              title="MODEZA delivery speed"
              icon={<Truck className="h-4 w-4" aria-hidden="true" />}
              badge={<Badge variant="default" size="sm">Choose a courier</Badge>}
            >
              <RadioGroup
                value={deliveryMethod}
                onValueChange={(value) => {
                  if (value === 'standard' || value === 'express') {
                    setDeliveryMethod(value);
                  }
                }}
                disabled={checkoutBusy}
                aria-label="Delivery method"
                className="space-y-3"
              >
                {deliveryOptions.map((option) => {
                  const selected = deliveryMethod === option.id;
                  return (
                    <label
                      key={option.id}
                      htmlFor={`delivery-${option.id}`}
                      className={`flex items-center justify-between gap-4 rounded-xl border p-4 transition-all ${
                        selected
                          ? 'border-[#A2574F] bg-[#F7ECEA] shadow-sm'
                          : 'border-[#E8E5DF] bg-white hover:border-[#A2574F] hover:bg-[#FAF9F6]'
                      } ${checkoutBusy ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'}`}
                    >
                      <span className="flex min-w-0 items-start gap-3">
                        <RadioGroupItem id={`delivery-${option.id}`} value={option.id} className="mt-0.5 shrink-0" />
                        <span className="min-w-0">
                          <span className="block font-serif text-sm font-medium text-[#181716]">{option.title}</span>
                          <span className="mt-0.5 block text-xs text-[#827E77]">{option.description}</span>
                          <span className="mt-2 flex flex-wrap items-center gap-2">
                            <Badge variant={selected ? 'outline' : 'default'} size="sm">{option.label}</Badge>
                            {selected && <Badge variant="success" size="sm">Selected</Badge>}
                          </span>
                        </span>
                      </span>
                      <span className="shrink-0 text-right text-xs font-semibold text-[#181716]">
                        {option.cost === 0 ? 'Complimentary' : formatPrice(option.cost)}
                      </span>
                    </label>
                  );
                })}
              </RadioGroup>
            </SectionCard>

            <SectionCard
              step={4}
              title="Payment protocol"
              icon={<CreditCard className="h-4 w-4" aria-hidden="true" />}
              badge={<Badge variant="success" size="sm" className="gap-1"><ShieldCheck className="h-3 w-3" aria-hidden="true" /> Sandbox</Badge>}
            >
              <div className="space-y-4">
                <RadioGroup
                  value={paymentMethod}
                  onValueChange={(value) => {
                    if (value === 'mpesa' || value === 'card' || value === 'pay_on_delivery') {
                      setPaymentMethod(value);
                    }
                  }}
                  disabled={checkoutBusy}
                  aria-label="Payment method"
                  className="grid grid-cols-1 gap-3 sm:grid-cols-2"
                >
                  {PAYMENT_OPTIONS.map((option) => {
                    const selected = paymentMethod === option.id;
                    return (
                      <label
                        key={option.id}
                        htmlFor={`payment-${option.id}`}
                        className={`flex items-center gap-3 rounded-xl border p-3.5 transition-all ${
                          selected
                            ? 'border-[#A2574F] bg-[#F7ECEA] shadow-sm'
                            : 'border-[#E8E5DF] bg-[#FAF9F6] hover:border-[#A2574F] hover:bg-white'
                        } ${checkoutBusy ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'}`}
                      >
                        <RadioGroupItem id={`payment-${option.id}`} value={option.id} className="shrink-0" />
                        <span className="min-w-0">
                          <span className="block text-xs font-semibold text-[#181716]">{option.label}</span>
                          <span className="mt-0.5 block text-[11px] text-[#827E77]">{option.detail}</span>
                        </span>
                      </label>
                    );
                  })}
                </RadioGroup>

                {paymentMethod === 'card' ? (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="rounded-xl border border-[#E8E5DF] bg-[#FAF9F6] px-4 py-3.5 text-[11px] leading-relaxed text-[#63605A]"
                  >
                    Card payments run in <span className="font-semibold text-[#A2574F]">sandbox preview</span>: this storefront does not yet connect a live card gateway, so no card details are collected. Confirming the order completes it and marks it paid <span className="font-semibold">without charging a real card</span>.
                  </motion.div>
                ) : (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="rounded-xl border border-[#E8E5DF] bg-[#FAF9F6] px-4 py-3 text-[11px] leading-relaxed text-[#63605A]"
                  >
                    {paymentMethod === 'pay_on_delivery'
                      ? 'Pay on delivery selected — the order will be paid when the package is handed over.'
                      : 'M-Pesa selected — a sandbox gateway settles the payment as soon as the order is placed; no real prompt is sent to your phone.'}
                  </motion.div>
                )}

                <div className="flex items-start gap-3 rounded-xl border border-[#E8E5DF] bg-white p-3.5">
                  <Checkbox
                    id="same-billing"
                    checked={formData.sameBilling}
                    onCheckedChange={(checked) => {
                      setFormData((prev) => ({ ...prev, sameBilling: checked === true }));
                    }}
                    disabled={checkoutBusy}
                    className="mt-0.5"
                  />
                  <label htmlFor="same-billing" className="cursor-pointer text-xs leading-relaxed text-[#63605A]">
                    Billing address matches shipping destination
                  </label>
                </div>
              </div>
            </SectionCard>
          </div>

          <aside className="space-y-4 lg:col-span-5 lg:sticky lg:top-24" aria-labelledby="order-review-heading">
            <Card className="relative overflow-hidden rounded-3xl shadow-xl">
              <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-transparent via-[#A2574F]/25 to-transparent" />
              <CardHeader className="flex-row items-start justify-between gap-3 p-5 pb-5 sm:p-7 sm:pb-6">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#F7ECEA] text-[#A2574F]">
                    <Package className="h-4 w-4" aria-hidden="true" />
                  </div>
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#A2574F]">Final review</p>
                    <CardTitle id="order-review-heading" className="mt-1 text-lg">Your order</CardTitle>
                  </div>
                </div>
                <Badge variant="outline" size="sm">{cart.length} {cart.length === 1 ? 'piece' : 'pieces'}</Badge>
              </CardHeader>
              <CardContent className="space-y-6 p-5 pt-0 sm:p-7 sm:pt-0">
                <div>
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#827E77]">Items reserved after placement</p>
                    <span className="text-[10px] text-[#827E77]">{cart.length} lines</span>
                  </div>
                  <div className="max-h-64 space-y-2 overflow-y-auto pr-1" role="list" aria-label="Items in your order">
                    {cart.map((item) => (
                      <div key={item.id} role="listitem" className="-m-1.5 flex items-center gap-3.5 rounded-lg p-1.5 transition-colors hover:bg-[#FAF9F6]">
                        <div className="h-16 w-14 shrink-0 overflow-hidden rounded-lg border border-[#E8E5DF] bg-[#F4ECE9]">
                          <ProductImage src={item.image} alt={item.name} className="h-full w-full" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <h3 className="truncate font-serif text-xs font-medium text-[#181716]">{item.name}</h3>
                          <p className="mt-1 text-[11px] text-[#827E77]">Size: {item.size} <span aria-hidden="true">•</span> Qty: {item.quantity}</p>
                        </div>
                        <Price amount={item.price * item.quantity} size="sm" />
                      </div>
                    ))}
                  </div>
                </div>

                <dl className="space-y-3 border-t border-[#F3F1ED] pt-4 text-xs text-[#63605A]">
                  <div className="flex items-center justify-between gap-4">
                    <dt>Cart subtotal</dt>
                    <dd className="font-medium text-[#181716]">{formatPrice(subtotal)}</dd>
                  </div>
                  {appliedPromo && (
                    <div className="flex items-center justify-between gap-4 text-[#2E5A44]">
                      <dt className="flex items-center gap-1.5">
                        <Tag className="h-3.5 w-3.5" aria-hidden="true" />
                        <span>Privilege code ({appliedPromo.code})</span>
                      </dt>
                      <dd className="font-medium">-{formatPrice(discountAmount)}</dd>
                    </div>
                  )}
                  <div className="flex items-center justify-between gap-4">
                    <dt>Delivery ({deliveryMethod === 'express' ? 'Priority air' : 'Standard'})</dt>
                    <dd className="font-medium text-[#181716]">{deliveryCost === 0 ? 'Complimentary' : formatPrice(deliveryCost)}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-4">
                    <dt>Estimated VAT (16%)</dt>
                    <dd className="font-medium text-[#181716]">{formatPrice(tax)}</dd>
                  </div>
                  <div className="mt-3 flex items-baseline justify-between gap-4 border-t border-[#F3F1ED] pt-3 text-base font-medium text-[#181716]">
                    <dt className="font-serif">Total amount</dt>
                    <dd className="font-serif text-xl">{formatPrice(grandTotal)}</dd>
                  </div>
                </dl>

                {checkoutError && (
                  <div className="flex items-start gap-2 rounded-xl border border-[#F8B4B4] bg-[#FDF2F2] p-3.5 text-xs text-[#9B1C1C]" role="alert">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    <span>{checkoutError}</span>
                  </div>
                )}

                {paymentPending && (
                  <Card className="rounded-2xl border-[#C8D8CA] bg-[#F5F8F4] p-4 shadow-none" role="status" aria-live="polite">
                    <div className="flex items-start gap-2 text-xs text-[#2E5A44]">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="font-semibold">
                            {paymentMethod === 'card' ? 'Card payment intent created' : 'M-Pesa payment request created'}
                          </p>
                          <Badge variant="warning" size="sm">Awaiting confirmation</Badge>
                        </div>
                        <p className="mt-1 leading-relaxed text-[#4B6B57]">
                          {paymentMethod === 'card'
                            ? 'No card will be charged — confirm below to complete the order in sandbox and mark it paid.'
                            : 'No real STK prompt is sent in sandbox mode. If payment does not confirm on its own, use the button below to mark it received.'}
                        </p>
                      </div>
                    </div>
                    <Button
                      type="button"
                      variant="secondary"
                      size="md"
                      fullWidth
                      disabled={isSubmitting}
                      isLoading={isSubmitting}
                      onClick={() => void handleConfirmPayment()}
                      className="mt-4 text-xs"
                    >
                      {!isSubmitting && (paymentMethod === 'card' ? 'Confirm sandbox payment' : 'I have completed payment')}
                    </Button>
                  </Card>
                )}
              </CardContent>
              <CardFooter className="block space-y-3 border-t border-[#F3F1ED] p-5 pt-5 sm:p-7 sm:pt-5">
                <Button
                  type="submit"
                  variant="primary"
                  size="lg"
                  fullWidth
                  disabled={checkoutBusy}
                  isLoading={isSubmitting}
                  className="gap-2"
                  aria-describedby="checkout-terms"
                >
                  {!isSubmitting && (paymentPending ? 'Payment pending' : `Place order • ${formatPrice(grandTotal)}`)}
                </Button>
                <p id="checkout-terms" className="text-center text-[11px] leading-relaxed text-[#827E77]">
                  By placing your order, you confirm acceptance of our Conditions of Sale and cancellation rights.
                </p>
                <div className="flex items-center justify-center gap-2 pt-1 text-[11px] text-[#827E77]">
                  <ShieldCheck className="h-3.5 w-3.5 text-[#A2574F]" aria-hidden="true" />
                  <span>256-bit SSL encrypted transaction</span>
                </div>
              </CardFooter>
            </Card>
          </aside>
        </div>
      </form>
    </div>
  );
};
