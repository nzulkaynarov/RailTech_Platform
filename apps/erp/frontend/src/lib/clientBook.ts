import type { Contact } from '@/api/crmApi';

/** Клиент = компания и её контакты (строка книги). */
export interface ClientRow {
  id: number;
  name: string;
  isRegistered: boolean;
  contacts: Contact[];
  primary: Contact | undefined;
  createdAt: string;
}

/** Группирует контакты по компании; основной контакт — `is_primary`, иначе первый заведённый. */
export function groupContactsByCompany(contacts: Contact[]): ClientRow[] {
  const byCompany = new Map<number, ClientRow>();
  for (const contact of contacts) {
    const row = byCompany.get(contact.company) ?? {
      id: contact.company,
      name: contact.company_name,
      isRegistered: contact.company_is_registered,
      contacts: [],
      primary: undefined,
      createdAt: contact.created_at,
    };
    row.contacts.push(contact);
    if (contact.created_at < row.createdAt) row.createdAt = contact.created_at;
    byCompany.set(contact.company, row);
  }
  for (const row of byCompany.values()) {
    row.contacts.sort((a, b) => a.created_at.localeCompare(b.created_at));
    row.primary = row.contacts.find((contact) => contact.is_primary) ?? row.contacts[0];
  }
  return [...byCompany.values()];
}
