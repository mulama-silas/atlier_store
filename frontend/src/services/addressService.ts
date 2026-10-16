import { api } from './apiClient';
import { CustomerAddressDTO } from '../types/api';
import { SavedAddress, clearSavedAddresses, getSavedAddresses } from '../utils/addressBook';

function sameAddress(left: SavedAddress, right: CustomerAddressDTO): boolean {
  return left.addressLine1.trim().toLowerCase() === right.addressLine1.trim().toLowerCase()
    && left.city.trim().toLowerCase() === right.city.trim().toLowerCase()
    && left.phone.replace(/\D/g, '') === right.phone.replace(/\D/g, '');
}

export async function listCustomerAddresses(userId: string): Promise<SavedAddress[]> {
  let addresses = await api.getAddresses();
  const legacy = getSavedAddresses(userId);
  if (legacy.length) {
    for (const oldAddress of legacy) {
      if (addresses.some((address) => sameAddress(oldAddress, address))) continue;
      const created = await api.createAddress({
        label: oldAddress.label,
        firstName: oldAddress.firstName,
        lastName: oldAddress.lastName,
        phone: oldAddress.phone,
        addressLine1: oldAddress.addressLine1,
        addressLine2: oldAddress.addressLine2,
        county: oldAddress.county,
        subcounty: oldAddress.subcounty,
        city: oldAddress.city,
        postalCode: oldAddress.postalCode,
        country: oldAddress.country,
        isDefault: oldAddress.isDefault,
      });
      addresses = [...addresses, created];
    }
    clearSavedAddresses(userId);
    addresses = await api.getAddresses();
  }
  return addresses;
}

export async function saveCustomerAddress(
  address: Omit<SavedAddress, 'id'> & { id?: string },
): Promise<SavedAddress[]> {
  const { id, ...payload } = address;
  if (id) await api.updateAddress(id, payload);
  else await api.createAddress(payload);
  return listCustomerAddressesFromServer();
}

export async function removeCustomerAddress(id: string): Promise<SavedAddress[]> {
  await api.deleteAddress(id);
  return listCustomerAddressesFromServer();
}

export async function setCustomerDefaultAddress(id: string): Promise<SavedAddress[]> {
  await api.updateAddress(id, { isDefault: true });
  return listCustomerAddressesFromServer();
}

async function listCustomerAddressesFromServer(): Promise<SavedAddress[]> {
  return (await api.getAddresses()).map((address) => ({ ...address }));
}
