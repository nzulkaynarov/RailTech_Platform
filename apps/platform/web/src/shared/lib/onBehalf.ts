import type { OnBehalfChannel } from "../api/generated/model";

/** Как контрагент сообщил решение (контракт `OnBehalfChannel`, A1 и A2 волны 18a), в порядке выбора. */
export const ON_BEHALF_CHANNELS: readonly OnBehalfChannel[] = [
  "email",
  "messenger",
  "phone",
  "in_person",
  "paper",
];
