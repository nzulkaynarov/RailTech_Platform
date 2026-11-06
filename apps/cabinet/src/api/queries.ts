import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query';

import * as portal from './portal';

/**
 * React Query над портальным API — единственное хранилище данных экранов (CONVENTIONS.md §3).
 * Ключи — по эндпоинту; после действия (принять, подписать, вернуть…) мутация кладёт ответ ERP
 * в кэш и инвалидирует связанные списки: ERP — источник правды, Cabinet ничего не досчитывает.
 */
export const keys = {
  requests: ['requests'] as const,
  request: (id: number) => ['requests', id] as const,
  quotes: ['quotes'] as const,
  quote: (id: number) => ['quotes', id] as const,
  contracts: ['contracts'] as const,
  invoices: ['invoices'] as const,
  acts: ['acts'] as const,
  deliveries: ['deliveries'] as const,
  documents: (params: portal.DocumentsQuery = {}) => ['documents', params] as const,
  catalog: (params: portal.CatalogQuery) => ['catalog', params] as const,
  catalogCategories: ['catalog', 'categories'] as const,
  catalogItem: (id: number) => ['catalog', 'item', id] as const,
  company: ['company'] as const,
  team: ['team'] as const,
  // Не под ['me']: выход стирает всё, кроме ['me'], — статус Telegram прошлого контакта не должен пережить выход.
  telegram: ['telegram'] as const,
  /** Лента чата кабинета: первая страница, дальше опрос дописывает в тот же кэш (`hooks/useMessagesFeed.ts`). */
  messages: ['messages'] as const,
  partnerProducts: ['partner', 'products'] as const,
  partnerProductList: (params: portal.PartnerProductsQuery) => ['partner', 'products', 'list', params] as const,
  partnerProduct: (id: number) => ['partner', 'products', 'item', id] as const,
  priceListTask: (taskId: string) => ['partner', 'price-list', taskId] as const,
  verify: (code: string) => ['verify', code] as const,
  partnerApplication: ['company', 'partner-application'] as const,
};

/** Список раздела грузится, только если у сессии есть его модуль (партнёру клиентские разделы закрыты, ADR-0022). */
interface ListOptions {
  enabled?: boolean;
}

export const useRequests = ({ enabled = true }: ListOptions = {}) =>
  useQuery({ queryKey: keys.requests, queryFn: portal.listRequests, enabled });
export const useRequest = (id: number) =>
  useQuery({ queryKey: keys.request(id), queryFn: () => portal.getRequest(id), enabled: Number.isFinite(id) });
export const useQuotes = ({ enabled = true }: ListOptions = {}) =>
  useQuery({ queryKey: keys.quotes, queryFn: portal.listQuotes, enabled });
export const useQuote = (id: number) =>
  useQuery({ queryKey: keys.quote(id), queryFn: () => portal.getQuote(id), enabled: Number.isFinite(id) });
export const useContracts = ({ enabled = true }: ListOptions = {}) =>
  useQuery({ queryKey: keys.contracts, queryFn: portal.listContracts, enabled });
export const useInvoices = ({ enabled = true }: ListOptions = {}) =>
  useQuery({ queryKey: keys.invoices, queryFn: portal.listInvoices, enabled });
export const useActs = ({ enabled = true }: ListOptions = {}) =>
  useQuery({ queryKey: keys.acts, queryFn: portal.listActs, enabled });
export const useDeliveries = ({ enabled = true }: ListOptions = {}) =>
  useQuery({ queryKey: keys.deliveries, queryFn: portal.listDeliveries, enabled });
export const useDocuments = (params: portal.DocumentsQuery = {}) =>
  useQuery({ queryKey: keys.documents(params), queryFn: () => portal.listDocuments(params) });
export const useCatalogCategories = () =>
  useQuery({ queryKey: keys.catalogCategories, queryFn: portal.listCatalogCategories });
export const useCatalog = (params: portal.CatalogQuery, enabled = true) =>
  useQuery({
    queryKey: keys.catalog(params),
    queryFn: () => portal.listCatalog(params),
    placeholderData: keepPreviousData,
    enabled,
  });
export const useCatalogItem = (id: number) =>
  useQuery({ queryKey: keys.catalogItem(id), queryFn: () => portal.getCatalogItem(id), enabled: Number.isFinite(id) });
export const useCompany = ({ enabled = true }: { enabled?: boolean } = {}) =>
  useQuery({ queryKey: keys.company, queryFn: portal.getCompany, enabled });
export const useTeam = ({ enabled = true }: { enabled?: boolean } = {}) =>
  useQuery({ queryKey: keys.team, queryFn: portal.listTeam, enabled });

/** Шаг опроса статуса Telegram; в тестах короткий, чтобы не ждать секунды реального времени. */
export const TELEGRAM_POLL_MS = import.meta.env.MODE === 'test' ? 50 : 3000;

/**
 * Статус Telegram контакта. `poll` — опрашивать, пока экран ждёт привязки или отключения (ADR-0023 п. 3: статус меняет
 * проекция CRM, обычно за секунды); без опроса — обычный запрос с кэшем.
 */
export const useTelegramStatus = ({ enabled = true, poll = false }: { enabled?: boolean; poll?: boolean } = {}) =>
  useQuery({
    queryKey: keys.telegram,
    queryFn: portal.getTelegramStatus,
    enabled,
    refetchInterval: poll ? TELEGRAM_POLL_MS : false,
  });
export const useCreateTelegramLink = () => useMutation({ mutationFn: portal.createTelegramLink });
/** Проверочное сообщение в Telegram; 409 `TELEGRAM_NOT_LINKED` — статус перечитывается (вызывающий решает по ошибке). */
export const useSendTelegramTest = () => useMutation({ mutationFn: portal.sendTelegramTest });
export const useUnlinkTelegram = () =>
  useInvalidatingMutation(portal.unlinkTelegram, [], (status, client) => client.setQueryData(keys.telegram, status));
export const usePartnerProducts = (
  params: portal.PartnerProductsQuery,
  options: { enabled?: boolean } = {},
) =>
  useQuery({
    queryKey: keys.partnerProductList(params),
    queryFn: () => portal.listPartnerProducts(params),
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });
export const usePartnerProduct = (id: number | null) =>
  useQuery({
    queryKey: keys.partnerProduct(id ?? 0),
    queryFn: () => portal.getPartnerProduct(id as number),
    enabled: id !== null,
  });

/** Состояние загрузки прайса: опрашивается, пока ERP обрабатывает файл (`pending` / `running`). */
export const PRICE_TASK_POLL_MS = 1500;
export const usePriceListTask = (taskId: string | null) =>
  useQuery({
    queryKey: keys.priceListTask(taskId ?? ''),
    queryFn: () => portal.getPriceListTask(taskId as string),
    enabled: taskId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'completed' || status === 'failed' ? false : PRICE_TASK_POLL_MS;
    },
    gcTime: 0,
  });

/** Мутация, после которой связанные списки перечитываются у ERP. */
function useInvalidatingMutation<TVars, TData>(
  mutationFn: (vars: TVars) => Promise<TData>,
  invalidate: QueryKey[],
  onData?: (data: TData, client: ReturnType<typeof useQueryClient>) => void,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: (data) => {
      onData?.(data, client);
      for (const queryKey of invalidate) void client.invalidateQueries({ queryKey });
    },
  });
}

export const useCreateRequest = () => useInvalidatingMutation(portal.createRequest, [keys.requests]);
export const useUploadFile = () => useMutation({ mutationFn: portal.uploadFile });

/** После акцепта ERP сам создаёт договор (BUSINESS §4, шаг 6) — перечитываем договоры и документы. */
export const useAcceptQuote = (id: number) =>
  useInvalidatingMutation(
    (code: string) => portal.acceptQuote(id, code),
    [keys.quotes, keys.contracts, keys.requests, ['documents']],
    (quote, client) => client.setQueryData(keys.quote(id), quote),
  );
/** Запрос кода акцепта: ERP отправляет код контакту; кэш не меняется. */
export const useRequestQuoteCode = (id: number) => useMutation({ mutationFn: () => portal.requestQuoteCode(id) });
export const useRejectQuote = (id: number) =>
  useInvalidatingMutation(
    (reason: string) => portal.rejectQuote(id, reason),
    [keys.quotes, keys.requests],
    (quote, client) => client.setQueryData(keys.quote(id), quote),
  );

/** Комментарий к КП: карточка КП перечитывается у ERP (лента `comments`). */
export const useAddQuoteComment = (id: number) =>
  useInvalidatingMutation((text: string) => portal.addQuoteComment(id, text), [keys.quote(id)]);

export const useSignContract = () => useInvalidatingMutation(portal.signContract, [keys.contracts, ['documents']]);
/**
 * Приёмка акта: если приложен скан — сначала `POST /uploads`, затем `POST /acts/{id}/accept {upload_id}`;
 * без скана — приёмка без тела. Ошибка любого шага — ошибка мутации (диалог показывает её текстом).
 */
export const useAcceptAct = () =>
  useInvalidatingMutation(
    async ({ id, scan }: { id: number; scan?: File | null }) => {
      const uploadId = scan ? (await portal.uploadFile(scan)).upload_id : undefined;
      return portal.acceptAct(id, uploadId);
    },
    [keys.acts, ['documents']],
  );
/**
 * «Я оплатил»: сначала файл в `POST /uploads`, затем `POST /invoices/{id}/proofs {upload_id, …}`. Ошибка любого шага —
 * ошибка мутации; после успеха счета перечитываются (платёжка появится в `proofs` со статусом «на проверке»).
 */
export const useSubmitPaymentProof = () =>
  useInvalidatingMutation(
    async ({ id, file, ...rest }: { id: number; file: File } & Omit<portal.PaymentProofCreate, 'upload_id'>) => {
      const { upload_id } = await portal.uploadFile(file);
      return portal.submitPaymentProof(id, { upload_id, ...rest });
    },
    [keys.invoices],
  );
export const useReturnAct = () =>
  useInvalidatingMutation(
    ({ id, reason }: { id: number; reason: string }) => portal.returnAct(id, reason),
    [keys.acts],
  );

/** Поставка принята или оспорена клиентом — строка заменяется ответом ERP, список перечитывается. */
function replaceDeliveryLine(line: portal.DeliveryLine, client: ReturnType<typeof useQueryClient>) {
  client.setQueryData<portal.DeliveryLine[]>(keys.deliveries, (lines) =>
    lines?.map((item) => (item.id === line.id ? line : item)),
  );
}
export const useAcceptDelivery = () =>
  useInvalidatingMutation(portal.acceptDelivery, [keys.deliveries], replaceDeliveryLine);
export const useDisputeDelivery = () =>
  useInvalidatingMutation(
    ({ id, reason }: { id: number; reason: string }) => portal.disputeDelivery(id, reason),
    [keys.deliveries],
    replaceDeliveryLine,
  );

export const useUpdateCompany = () =>
  useInvalidatingMutation(portal.updateCompany, [['me']], (company, client) =>
    client.setQueryData(keys.company, company),
  );
export const useInviteTeamMember = () => useInvalidatingMutation(portal.inviteTeamMember, [keys.team]);

// --- «Мои товары» партнёра (PART-2) -------------------------------------------------------------

export const useUploadPriceList = () => useMutation({ mutationFn: portal.uploadPriceList });
/** Реальная загрузка меняет карточки и цены; предпросмотр — нет, список перечитывает мастер после записи. */
export const useSubmitPartnerProducts = () =>
  useInvalidatingMutation(portal.submitPartnerProducts, [keys.partnerProducts]);
export const useConfirmPartnerOffers = () =>
  useInvalidatingMutation(portal.confirmPartnerOffers, [keys.partnerProducts]);

// --- публичная проверка официальных документов (ADR-0024 §6, SIGN-VERIFY-1) -----------------------

export const useVerifyDocument = (code: string, enabled = true) =>
  useQuery({
    queryKey: keys.verify(code),
    queryFn: () => portal.verifyDocument(code),
    enabled: Boolean(code) && enabled,
    retry: false,
  });

// --- заявки кандидатов в партнёры (ADR-0022, DECISIONS 2026-11-05, PART-ONBOARD-1) --------------

export const useCompanyPartnerApplication = (options: { enabled?: boolean } = {}) =>
  useQuery({
    queryKey: keys.partnerApplication,
    queryFn: portal.getCompanyPartnerApplication,
    enabled: options.enabled ?? true,
  });

export const useSubmitCompanyPartnerApplication = () =>
  useInvalidatingMutation(portal.submitCompanyPartnerApplication, [keys.partnerApplication]);

export const useAgreeCompanyPartnerContract = () =>
  useInvalidatingMutation(portal.agreeCompanyPartnerContract, [keys.partnerApplication]);

export const useSubmitPartnerApplication = () =>
  useMutation({ mutationFn: portal.submitPartnerApplication });
