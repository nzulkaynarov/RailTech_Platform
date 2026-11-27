"""Роли компаний в строках списка «Контрагенты» (КОНТР-1б): один пакетный запрос на список.

Строка клиента приходит из CRM, но «Клиент» или «Партнёр» в списке говорит ERP: роли
компании с состояниями (`parties/organizations/role-states/`, до 100 id за запрос).
ERP не ответил — `None` у строки: список строится по-старому, а не пустеет."""

from app.clients.erp_company import ErpCompany
from app.deps import Authed
from app.errors import PlatformError
from app.schemas_supplier_access import CounterpartyRoleState, role_states_of

BATCH = 100


async def company_role_states(
    authed: Authed, company_ids: list[int]
) -> dict[int, list[CounterpartyRoleState]]:
    ids = sorted({i for i in company_ids if i})
    out: dict[int, list[CounterpartyRoleState]] = {}
    erp = ErpCompany(authed.call)
    for start in range(0, len(ids), BATCH):
        batch = ids[start : start + BATCH]
        try:
            data = await erp.data(
                "GET",
                "parties/organizations/role-states/",
                params={"ids": ",".join(str(i) for i in batch)},
            )
        except PlatformError:
            continue
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, dict):
            continue
        for key, rows in results.items():
            if str(key).isdigit():
                out[int(key)] = role_states_of(rows)
    return out
