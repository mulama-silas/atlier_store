import React, { useCallback, useEffect, useState } from 'react';
import { Check, MapPin, Pencil, Plus, Star, Trash2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { AccountPageHeader } from '../components/account/AccountPageHeader';
import { Button } from '../components/modeza/Button';
import { Badge } from '../components/modeza/Badge';
import { Card, CardFooter, CardHeader, CardTitle } from '../components/modeza/Card';
import { Input, Select as InputSelect } from '../components/modeza/Input';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../components/modeza/Dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../components/modeza/AlertDialog';
import {
  EMPTY_ADDRESS,
  SavedAddress,
} from '../utils/addressBook';
import {
  listCustomerAddresses,
  removeCustomerAddress,
  saveCustomerAddress,
  setCustomerDefaultAddress,
} from '../services/addressService';
import { KENYA_COUNTIES, KENYA_COUNTY_SUBCOUNTIES, KENYA_SUBCOUNTY_CITIES } from '../data/kenyaLocations';

export const AccountAddressesPage: React.FC = () => {
  const { user } = useAuth();

  const [addresses, setAddresses] = useState<SavedAddress[]>([]);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState({ ...EMPTY_ADDRESS });
  const [deleteTarget, setDeleteTarget] = useState<SavedAddress | null>(null);
  const [isLoadingAddresses, setIsLoadingAddresses] = useState(false);
  const [addressError, setAddressError] = useState('');

  const userId = user?.id ?? '';

  useEffect(() => {
    if (!userId) {
      setAddresses([]);
      return;
    }
    let active = true;
    setIsLoadingAddresses(true);
    setAddressError('');
    void listCustomerAddresses(userId).then((loaded) => {
      if (active) setAddresses(loaded);
    }).catch((error: unknown) => {
      if (active) setAddressError(error instanceof Error ? error.message : 'Saved addresses could not be loaded.');
    }).finally(() => {
      if (active) setIsLoadingAddresses(false);
    });
    return () => { active = false; };
  }, [userId]);

  const openAdd = useCallback(() => {
    setDraft({ ...EMPTY_ADDRESS });
    setEditingId(null);
    setIsFormOpen(true);
  }, []);

  const openEdit = useCallback((address: SavedAddress) => {
    setDraft({ ...address });
    setEditingId(address.id);
    setIsFormOpen(true);
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userId) return;
    setAddressError('');
    try {
      setAddresses(await saveCustomerAddress({
        ...draft,
        id: editingId ?? undefined,
        isDefault: addresses.find((address) => address.id === editingId)?.isDefault ?? addresses.length === 0,
      }));
      setIsFormOpen(false);
    } catch (error: unknown) {
      setAddressError(error instanceof Error ? error.message : 'Address could not be saved.');
    }
  };

  const handleRemove = async () => {
    if (!userId || !deleteTarget) return;
    try {
      setAddresses(await removeCustomerAddress(deleteTarget.id));
      setDeleteTarget(null);
    } catch (error: unknown) {
      setAddressError(error instanceof Error ? error.message : 'Address could not be removed.');
    }
  };

  const handleSetDefault = async (id: string) => {
    if (!userId) return;
    try {
      setAddresses(await setCustomerDefaultAddress(id));
    } catch (error: unknown) {
      setAddressError(error instanceof Error ? error.message : 'Default address could not be updated.');
    }
  };

  const handleDraftChange = (name: keyof typeof EMPTY_ADDRESS, value: string) => {
    setDraft((prev) => {
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

  const subcountiesForCounty = KENYA_COUNTY_SUBCOUNTIES[draft.county] || [];
  const citiesForSubcounty = KENYA_SUBCOUNTY_CITIES[draft.subcounty] || (draft.subcounty ? [draft.subcounty] : []);

  if (!user) {
    return (
      <section className="w-full space-y-6">
        <AccountPageHeader
          eyebrow="Account"
          title="Addresses"
          description="Delivery details saved for a seamless checkout."
        />
        <Card className="border-[#E8E5DF] p-8 text-center sm:p-10">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#F4ECE9] text-[#A2574F]">
            <MapPin className="h-6 w-6" strokeWidth={1.5} aria-hidden="true" />
          </div>
          <Badge variant="outline" size="sm" className="mt-5">Private address book</Badge>
          <p className="mx-auto mt-4 max-w-md text-sm leading-relaxed text-[#63605A]">Sign in to manage your saved delivery addresses.</p>
        </Card>
      </section>
    );
  }

  return (
    <section className="w-full space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <AccountPageHeader
          eyebrow="Account"
          title="Addresses"
          description="Delivery details saved for a seamless checkout."
        />
        <Badge variant="outline" size="lg" className="w-fit gap-2">
          <MapPin className="h-3.5 w-3.5" aria-hidden="true" />
          {addresses.length} {addresses.length === 1 ? 'address' : 'addresses'}
        </Badge>
      </div>

      <div className="space-y-4">
        {addressError && <p role="alert" className="rounded-xl border border-[#F8B4B4] bg-[#FDF2F2] px-4 py-3 text-sm text-[#9B1C1C]">{addressError}</p>}
        {isLoadingAddresses && <p role="status" className="text-sm text-[#827E77]">Loading saved addresses...</p>}
        {addresses.length === 0 ? (
          <Card className="border-[#E8E5DF] p-8 text-center sm:p-12">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full border border-[#E8E5DF] bg-[#F4ECE9] text-[#A2574F]">
              <MapPin className="h-7 w-7" strokeWidth={1.5} aria-hidden="true" />
            </div>
            <Badge variant="outline" size="sm" className="mt-5">Ready when you are</Badge>
            <h2 className="mt-4 font-serif text-2xl text-[#181716]">No saved addresses yet</h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-[#63605A]">Add a delivery address so future checkout is a single tap.</p>
            <Button type="button" variant="primary" size="md" className="mt-7 gap-2" onClick={openAdd}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add a New Address
            </Button>
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {addresses.map((address) => {
              const addressName = address.label || 'Saved Address';
              return (
                <article key={address.id} className="h-full">
                  <Card className="flex h-full flex-col border-[#E8E5DF]">
                    <CardHeader className="flex-row items-start gap-4 p-5 sm:p-6">
                      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[#F4ECE9] text-[#A2574F] ring-1 ring-[#E8E5DF]">
                        <MapPin className="h-5 w-5" aria-hidden="true" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <CardTitle className="truncate text-lg">{addressName}</CardTitle>
                          {address.isDefault ? (
                            <Badge variant="new" size="sm">Default</Badge>
                          ) : (
                            <Button
                              type="button"
                              variant="modeza-outline"
                              size="sm"
                              className="h-7 shrink-0 gap-1 px-2.5 text-[10px]"
                              onClick={() => handleSetDefault(address.id)}
                              aria-label={`Set ${addressName} as default address`}
                            >
                              <Star className="h-3 w-3" aria-hidden="true" />
                              Set Default
                            </Button>
                          )}
                        </div>
                        <address className="mt-3 text-sm not-italic leading-relaxed text-[#181716]">
                          <p className="font-semibold">
                            {address.firstName} {address.lastName}
                          </p>
                          <p className="text-[#63605A]">{address.addressLine1}</p>
                          {address.addressLine2 && <p className="text-[#63605A]">{address.addressLine2}</p>}
                          <p className="text-[#63605A]">{address.city}, {address.county}</p>
                          <p className="text-[#63605A]">{address.country} {address.postalCode}</p>
                          <p className="mt-1.5 text-xs text-[#827E77]">Phone: {address.phone}</p>
                        </address>
                      </div>
                    </CardHeader>
                    <CardFooter className="mt-auto flex-col gap-2 border-t border-[#F3F1ED] p-5 sm:flex-row sm:justify-end sm:p-6">
                      <Button type="button" variant="outline" size="sm" className="w-full gap-1.5 sm:w-auto" onClick={() => openEdit(address)}>
                        <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                        Edit
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="w-full gap-1.5 text-[#9E332B] hover:bg-[#FDF2F2] hover:text-[#9E332B] sm:w-auto"
                        onClick={() => setDeleteTarget(address)}
                        aria-label={`Remove ${addressName}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                        Remove
                      </Button>
                    </CardFooter>
                  </Card>
                </article>
              );
            })}
          </div>
        )}

        {addresses.length > 0 && (
          <Button
            type="button"
            variant="outline"
            size="md"
            className="w-full gap-2 border-dashed sm:w-auto"
            onClick={openAdd}
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            Add a New Address
          </Button>
        )}
      </div>

      <Dialog
        open={isFormOpen}
        onOpenChange={(open) => {
          if (!open) setIsFormOpen(false);
        }}
      >
        <DialogContent className="block max-h-[calc(100dvh-1.5rem)] w-[calc(100%_-_1.5rem)] overflow-y-auto p-0 sm:max-w-3xl sm:w-full">
          <DialogHeader className="border-b border-[#F3F1ED] p-5 pr-12 sm:p-6 sm:pr-14">
            <DialogTitle>{editingId ? 'Edit Address' : 'Add a New Address'}</DialogTitle>
            <DialogDescription>Keep your delivery details ready for a faster checkout.</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSave} className="space-y-5 p-5 sm:p-6">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Input
                id="address-label"
                name="label"
                label="Address Label"
                value={draft.label}
                onChange={(event) => handleDraftChange('label', event.target.value)}
                placeholder="Home"
                helperText="A short name for this address."
                autoComplete="address-label"
              />
              <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2">
                <Input
                  id="address-first-name"
                  name="firstName"
                  label="First Name"
                  required
                  value={draft.firstName}
                  onChange={(event) => handleDraftChange('firstName', event.target.value)}
                  placeholder="Jane"
                  autoComplete="given-name"
                />
                <Input
                  id="address-last-name"
                  name="lastName"
                  label="Last Name"
                  required
                  value={draft.lastName}
                  onChange={(event) => handleDraftChange('lastName', event.target.value)}
                  placeholder="Doe"
                  autoComplete="family-name"
                />
              </div>
            </div>

            <Input
              id="address-line-1"
              name="addressLine1"
              label="Street Address"
              required
              value={draft.addressLine1}
              onChange={(event) => handleDraftChange('addressLine1', event.target.value)}
              placeholder="123 Moi Avenue"
              autoComplete="address-line1"
            />
            <Input
              id="address-line-2"
              name="addressLine2"
              label="Apartment, Suite, Unit (Optional)"
              value={draft.addressLine2}
              onChange={(event) => handleDraftChange('addressLine2', event.target.value)}
              placeholder="Apt 4B"
              autoComplete="address-line2"
            />

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <InputSelect
                id="address-country"
                name="country"
                label="Country"
                value={draft.country}
                options={[{ value: 'Kenya', label: 'Kenya' }]}
                disabled
                className="cursor-not-allowed bg-[#FAF9F6] text-[#827E77]"
              />
              <InputSelect
                id="address-county"
                name="county"
                label="County"
                required
                value={draft.county}
                onChange={(event) => handleDraftChange('county', event.target.value)}
                options={KENYA_COUNTIES.map((county) => ({ value: county, label: county }))}
                placeholder="Select County"
              />
              <InputSelect
                id="address-subcounty"
                name="subcounty"
                label="Subcounty"
                required
                value={draft.subcounty}
                onChange={(event) => handleDraftChange('subcounty', event.target.value)}
                options={subcountiesForCounty.map((subcounty) => ({ value: subcounty, label: subcounty }))}
                placeholder="Select Subcounty"
                disabled={!draft.county || subcountiesForCounty.length === 0}
                helperText={!draft.county ? 'Choose a county first.' : undefined}
                className="disabled:cursor-not-allowed disabled:bg-[#FAF9F6] disabled:text-[#A29E96]"
              />
              <InputSelect
                id="address-city"
                name="city"
                label="City"
                required
                value={draft.city}
                onChange={(event) => handleDraftChange('city', event.target.value)}
                options={citiesForSubcounty.map((city) => ({ value: city, label: city }))}
                placeholder="Select City"
                disabled={!draft.subcounty || citiesForSubcounty.length === 0}
                helperText={!draft.subcounty ? 'Choose a subcounty first.' : undefined}
                className="disabled:cursor-not-allowed disabled:bg-[#FAF9F6] disabled:text-[#A29E96]"
              />
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Input
                id="address-postal"
                name="postalCode"
                label="Postal Code"
                required
                value={draft.postalCode}
                onChange={(event) => handleDraftChange('postalCode', event.target.value)}
                placeholder="00100"
                autoComplete="postal-code"
              />
              <Input
                id="address-phone"
                name="phone"
                label="Phone Number"
                type="tel"
                required
                value={draft.phone}
                onChange={(event) => handleDraftChange('phone', event.target.value)}
                placeholder="+254 7XX XXX XXX"
                autoComplete="tel"
                inputMode="tel"
              />
            </div>

            <DialogFooter className="gap-3 border-t border-[#F3F1ED] px-0 pb-0 pt-5 sm:space-x-0">
              <Button type="button" variant="outline" size="sm" onClick={() => setIsFormOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" size="sm" className="gap-1.5">
                <Check className="h-3.5 w-3.5" aria-hidden="true" />
                {editingId ? 'Save Changes' : 'Save Address'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Remove address?</AlertDialogTitle>
            <AlertDialogDescription>
              {deleteTarget
                ? `Remove "${deleteTarget.label || 'Saved Address'}" (${deleteTarget.addressLine1}) from your book?`
                : ''}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="gap-3 sm:space-x-0">
            <AlertDialogCancel asChild>
              <Button type="button" variant="outline" size="sm">Cancel</Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button type="button" variant="destructive" size="sm" className="gap-1.5" onClick={handleRemove}>
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                Remove
              </Button>
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <div className="flex items-start gap-2 rounded-xl border border-[#E8E5DF] bg-[#FAF9F6] px-4 py-3 text-xs leading-relaxed text-[#827E77]">
        <MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#A2574F]" aria-hidden="true" />
        <p>Addresses are stored securely with your account and are available on your signed-in devices.</p>
      </div>
    </section>
  );
};
