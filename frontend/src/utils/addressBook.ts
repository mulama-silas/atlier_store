export interface SavedAddress {
  id: string;
  label: string;
  firstName: string;
  lastName: string;
  phone: string;
  addressLine1: string;
  addressLine2: string;
  county: string;
  subcounty: string;
  city: string;
  postalCode: string;
  country: string;
  isDefault: boolean;
}

const STORAGE_PREFIX = 'modeza_addresses_v1';

export const EMPTY_ADDRESS: Omit<SavedAddress, 'id' | 'isDefault'> = {
  label: '',
  firstName: '',
  lastName: '',
  phone: '',
  addressLine1: '',
  addressLine2: '',
  county: '',
  subcounty: '',
  city: '',
  postalCode: '',
  country: 'Kenya',
};

function storageKey(userId: string): string {
  return `${STORAGE_PREFIX}:${userId}`;
}

function generateId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `addr-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function getSavedAddresses(userId: string): SavedAddress[] {
  try {
    const raw = localStorage.getItem(storageKey(userId));
    if (raw === null) return [];
    const parsed = JSON.parse(raw) as SavedAddress[];
    if (!Array.isArray(parsed)) return [];
    const addresses = parsed.filter((address) => address?.id !== 'addr-demo');
    if (addresses.length !== parsed.length) {
      localStorage.setItem(storageKey(userId), JSON.stringify(addresses));
    }
    return addresses;
  } catch {
    return [];
  }
}

export function getDefaultAddress(userId: string): SavedAddress | undefined {
  return getSavedAddresses(userId).find((address) => address.isDefault);
}

function persist(userId: string, addresses: SavedAddress[]): SavedAddress[] {
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(addresses));
  } catch {
    // storage unavailable — keep in-memory result only
  }
  return addresses;
}

export function upsertAddress(userId: string, address: Omit<SavedAddress, 'id' | 'isDefault'> & { id?: string }): SavedAddress[] {
  const addresses = getSavedAddresses(userId);
  const isEditing = Boolean(address.id) && addresses.some((a) => a.id === address.id);
  const makeDefault = !isEditing && addresses.length === 0;
  const next: SavedAddress = {
    ...EMPTY_ADDRESS,
    ...address,
    id: address.id ?? generateId(),
    isDefault: isEditing ? addresses.find((a) => a.id === address.id)?.isDefault ?? false : makeDefault,
  };
  if (isEditing) {
    return persist(
      userId,
      addresses.map((a) => (a.id === next.id ? next : a))
    );
  }
  return persist(userId, [...addresses, next]);
}

export function removeAddress(userId: string, id: string): SavedAddress[] {
  let addresses = getSavedAddresses(userId).filter((a) => a.id !== id);
  if (!addresses.some((a) => a.isDefault) && addresses.length > 0) {
    addresses = addresses.map((a, index) => ({ ...a, isDefault: index === 0 }));
  }
  return persist(userId, addresses);
}

export function setDefaultAddress(userId: string, id: string): SavedAddress[] {
  return persist(
    userId,
    getSavedAddresses(userId).map((a) => ({ ...a, isDefault: a.id === id }))
  );
}

export function clearSavedAddresses(userId: string): void {
  try {
    localStorage.removeItem(storageKey(userId));
  } catch {
    // The remote address book remains authoritative if local storage is unavailable.
  }
}
