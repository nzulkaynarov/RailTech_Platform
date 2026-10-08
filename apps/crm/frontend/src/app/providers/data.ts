import type { DataProvider } from "@refinedev/core";

import {
  createUser,
  getLead,
  getUser,
  listLeads,
  listUsers,
  updateUser,
} from "../../api/generated/crm";
import type { UserCreate, UserUpdate } from "../../api/generated/model";
import { unwrap } from "../../api/http";

const unsupported = (what: string): never => {
  throw new Error(`dataProvider: ${what} не поддерживается`);
};

// Refine типизирует записи обобщённо; конкретные типы — из сгенерированной модели.
const asRecord = (value: unknown): never => value as never;

/** dataProvider Refine поверх сгенерированного клиента (ресурсы `leads`, `users`). */
export const dataProvider: DataProvider = {
  getApiUrl: () => "/api/v1",
  async getList({ resource, pagination }: Parameters<DataProvider["getList"]>[0]) {
    if (resource === "leads") {
      const size = pagination?.pageSize ?? 50;
      const page = pagination?.currentPage ?? 1;
      const page_ = unwrap(await listLeads({ limit: size, offset: (page - 1) * size }));
      return { data: asRecord(page_.items), total: page_.total };
    }
    if (resource === "users") {
      const users = unwrap(await listUsers());
      return { data: asRecord(users), total: users.length };
    }
    return unsupported(`getList ${resource}`);
  },
  async getOne({ resource, id }: Parameters<DataProvider["getOne"]>[0]) {
    if (resource === "leads") return { data: asRecord(unwrap(await getLead(Number(id)))) };
    if (resource === "users") return { data: asRecord(unwrap(await getUser(Number(id)))) };
    return unsupported(`getOne ${resource}`);
  },
  async create({ resource, variables }: Parameters<DataProvider["create"]>[0]) {
    if (resource !== "users") return unsupported(`create ${resource}`);
    return { data: asRecord(unwrap(await createUser(variables as UserCreate))) };
  },
  async update({ resource, id, variables }: Parameters<DataProvider["update"]>[0]) {
    if (resource !== "users") return unsupported(`update ${resource}`);
    return { data: asRecord(unwrap(await updateUser(Number(id), variables as UserUpdate))) };
  },
  deleteOne: () => unsupported("deleteOne"),
};
