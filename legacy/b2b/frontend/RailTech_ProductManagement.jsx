import { useState, useMemo } from "react";
import {
  Package, PackageCheck, Search as SearchIcon, SlidersHorizontal, MoreVertical,
  Download, Plus, ChevronLeft, ChevronRight, ChevronDown, LayoutDashboard,
  ShoppingCart, FileText, Factory, BarChart3, Settings, Plug, HelpCircle,
  Bell, MessageSquare, Layers, X, ArrowUpDown, PackageSearch, PackageX
} from "lucide-react";

// ─── Product Data (from Excel: Импорт 2026 год по УЭЛ для НХ) ─────────────────
const products = [
  { id: "P001", name: "Баббит Б-83", article: "MAT-001", gost: "ГОСТ 1320-74", uom: "тн", quantity: 20, domain: "GENERAL_GOODS", category: "Материалы", status: "in_stock", manufacturer: "ОАО ММЗ", addedDate: "15.01.2026" },
  { id: "P002", name: "Баббит БК-2", article: "MAT-002", gost: "ГОСТ 1209-90", uom: "тн", quantity: 30, domain: "GENERAL_GOODS", category: "Материалы", status: "in_stock", manufacturer: "ОАО ММЗ", addedDate: "15.01.2026" },
  { id: "P003", name: "Олово марка О1 пч", article: "MAT-003", gost: "ГОСТ 860-75", uom: "тн", quantity: 20, domain: "GENERAL_GOODS", category: "Материалы", status: "to_order", manufacturer: "АО Новосибирский ОЗ", addedDate: "20.01.2026" },
  { id: "P004", name: "Бронза оловянная Бр04Ц4С17", article: "MAT-004", gost: "Бр04Ц4С17", uom: "тн", quantity: 40, domain: "GENERAL_GOODS", category: "Материалы", status: "in_stock", manufacturer: "ОАО Кировский завод", addedDate: "22.01.2026" },
  { id: "P005", name: "Провод БПВЛ 1,5 мм²", article: "ELC-001", gost: "ТУ16.505.911-76", uom: "км", quantity: 300, domain: "RAILWAY_MACHINERY", category: "Электрооборудование", status: "in_stock", manufacturer: "АО МТЗ Трансмаш", addedDate: "01.02.2026" },
  { id: "P006", name: "Провод БПВЛ 2,5 мм²", article: "ELC-002", gost: "ТУ16.505.911-76", uom: "км", quantity: 300, domain: "RAILWAY_MACHINERY", category: "Электрооборудование", status: "to_order", manufacturer: "АО МТЗ Трансмаш", addedDate: "01.02.2026" },
  { id: "P007", name: "Круг ø120мм ст. 12ХН3А", article: "MET-001", gost: "ст. 12ХН3А", uom: "тн", quantity: 30, domain: "GENERAL_GOODS", category: "Металлопрокат", status: "in_stock", manufacturer: "ПАО Северсталь", addedDate: "05.02.2026" },
  { id: "P008", name: "Круг ø140мм ст. 12ХН3А", article: "MET-002", gost: "ст. 12ХН3А", uom: "тн", quantity: 25, domain: "GENERAL_GOODS", category: "Металлопрокат", status: "sourcing", manufacturer: "ПАО Северсталь", addedDate: "05.02.2026" },
  { id: "P009", name: "Круг ø160мм ст. 12ХН3А", article: "MET-003", gost: "ст. 12ХН3А", uom: "тн", quantity: 40, domain: "GENERAL_GOODS", category: "Металлопрокат", status: "in_stock", manufacturer: "ПАО Северсталь", addedDate: "10.02.2026" },
  { id: "P010", name: "Круг ø200мм ст. 12ХН3А", article: "MET-004", gost: "ст. 12ХН3А", uom: "тн", quantity: 20, domain: "GENERAL_GOODS", category: "Металлопрокат", status: "to_order", manufacturer: "ПАО Северсталь", addedDate: "10.02.2026" },
  { id: "P011", name: "Лента 0,5мм ст. 30ХГСА", article: "MET-005", gost: "30ХГСА", uom: "тн", quantity: 15, domain: "GENERAL_GOODS", category: "Металлопрокат", status: "in_stock", manufacturer: "ПАО НЛМК", addedDate: "12.02.2026" },
  { id: "P012", name: "Чугун ПЛ-2", article: "MET-006", gost: "—", uom: "тн", quantity: 10, domain: "GENERAL_GOODS", category: "Металлопрокат", status: "inactive", manufacturer: "ОАО ЧМЗ", addedDate: "15.02.2026" },
  { id: "P013", name: "Эмаль ЭЛКОМ ЭИ-401", article: "CHM-001", gost: "—", uom: "тн", quantity: 5, domain: "GENERAL_GOODS", category: "Химия и ЛКМ", status: "in_stock", manufacturer: "ООО ЭЛКОМ", addedDate: "18.02.2026" },
  { id: "P014", name: "Лента элмикатерм 0,08х20мм", article: "INS-001", gost: "—", uom: "тн", quantity: 8, domain: "RAILWAY_MACHINERY", category: "Изоляция", status: "sourcing", manufacturer: "ООО НПО САУТ", addedDate: "20.02.2026" },
  { id: "P015", name: "Стеклотекстолит СТЭФ-1 5мм", article: "INS-002", gost: "—", uom: "тн", quantity: 12, domain: "RAILWAY_MACHINERY", category: "Изоляция", status: "to_order", manufacturer: "ОАО ЭЛИЗ", addedDate: "25.02.2026" },
  { id: "P016", name: "Доставка ЖД транспортом (РФ-УЗ)", article: "SVC-001", gost: "—", uom: "рейс", quantity: 24, domain: "SERVICES", category: "Логистика", status: "in_stock", manufacturer: "ООО РТ Логистик", addedDate: "01.01.2026" },
  { id: "P017", name: "Таможенное оформление (импорт)", article: "SVC-002", gost: "—", uom: "партия", quantity: 48, domain: "SERVICES", category: "Таможня", status: "in_stock", manufacturer: "ООО РТ Логистик", addedDate: "01.01.2026" },
  { id: "P018", name: "Круг ø160мм ст. 38ХС", article: "MET-007", gost: "ст. 38ХС", uom: "тн", quantity: 35, domain: "GENERAL_GOODS", category: "Металлопрокат", status: "in_stock", manufacturer: "ПАО Северсталь", addedDate: "28.02.2026" },
  { id: "P019", name: "Круг ø160мм ст. У8", article: "MET-008", gost: "ст. У8", uom: "тн", quantity: 18, domain: "GENERAL_GOODS", category: "Металлопрокат", status: "to_order", manufacturer: "ПАО НЛМК", addedDate: "01.03.2026" },
  { id: "P020", name: "Полиамидная лента ПМ(л) 0,045х20мм", article: "INS-003", gost: "—", uom: "тн", quantity: 6, domain: "RAILWAY_MACHINERY", category: "Изоляция", status: "in_stock", manufacturer: "ООО НПО САУТ", addedDate: "05.03.2026" },
];

const statusConfig = {
  in_stock:  { label: "В наличии",  bg: "bg-emerald-50",  text: "text-emerald-700", border: "border-emerald-200" },
  to_order:  { label: "Под заказ",  bg: "bg-amber-50",    text: "text-amber-700",   border: "border-amber-200" },
  sourcing:  { label: "Поиск",     bg: "bg-blue-50",     text: "text-blue-700",    border: "border-blue-200" },
  inactive:  { label: "Неактивно", bg: "bg-red-50",      text: "text-red-700",     border: "border-red-200" },
};

const domainConfig = {
  RAILWAY_MACHINERY: { label: "ЖД и Техника",   bg: "bg-indigo-50", text: "text-indigo-700", border: "border-indigo-200" },
  GENERAL_GOODS:     { label: "Общие товары",    bg: "bg-slate-100", text: "text-slate-700",  border: "border-slate-300" },
  SERVICES:          { label: "Услуги",          bg: "bg-violet-50", text: "text-violet-700", border: "border-violet-200" },
};

const navItems = [
  { icon: LayoutDashboard, label: "Дашборд" },
  { icon: Package, label: "Каталог", active: true, children: ["Номенклатура", "Категории", "Группы техники"] },
  { icon: ShoppingCart, label: "Закупки", children: ["Заявки", "Импорт Excel", "Smart Match"] },
  { icon: FileText, label: "CRM", badge: 3, children: ["Сделки", "Котировки", "Клиенты"] },
  { icon: Factory, label: "Производство", children: ["Заказы", "График"] },
  { icon: BarChart3, label: "Аналитика" },
];

const bottomNav = [
  { icon: Settings, label: "Настройки" },
  { icon: Plug, label: "Интеграции" },
  { icon: HelpCircle, label: "Помощь" },
];

// ─── Sub-components ────────────────────────────────────────────────────────

function Badge({ children, className = "" }) {
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${className}`}>{children}</span>;
}

function StatusBadge({ status }) {
  const c = statusConfig[status];
  return <Badge className={`${c.bg} ${c.text} ${c.border}`}>{c.label}</Badge>;
}

function DomainBadge({ domain }) {
  const c = domainConfig[domain];
  return <Badge className={`${c.bg} ${c.text} ${c.border}`}>{c.label}</Badge>;
}

function KPICard({ title, value, change, icon: Icon, changeColor }) {
  const sign = change > 0 ? "+" : "";
  return (
    <div className="rounded-xl border bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between">
        <div className="flex flex-col gap-1">
          <p className="text-2xl font-bold tracking-tight">
            {value.toLocaleString("ru-RU")}
            <span className={`ml-2 text-xs font-medium ${changeColor}`}>{sign}{change}</span>
          </p>
          <p className="text-xs text-gray-500">{title}</p>
        </div>
        <div className="rounded-lg border p-2 text-gray-400">
          <Icon size={20} />
        </div>
      </div>
    </div>
  );
}

function NavItem({ item, depth = 0 }) {
  const [open, setOpen] = useState(item.active || false);
  const Icon = item.icon;
  const hasChildren = item.children && item.children.length > 0;
  const isActive = item.active || false;

  return (
    <div>
      <button
        onClick={() => hasChildren && setOpen(!open)}
        className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors hover:bg-gray-100
          ${isActive ? "text-gray-900" : "text-gray-500"}`}
      >
        <Icon size={16} />
        <span className="flex-1 text-left">{item.label}</span>
        {item.badge && (
          <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-gray-900 px-1.5 text-[10px] font-medium text-white">
            {item.badge}
          </span>
        )}
        {hasChildren && <ChevronDown size={16} className={`transition-transform ${open ? "rotate-180" : ""}`} />}
      </button>
      {hasChildren && open && (
        <div className="ml-4 mt-1 flex flex-col gap-0.5 border-l pl-3">
          {item.children.map((child, i) => (
            <button
              key={i}
              className={`rounded-md px-3 py-1.5 text-left text-sm transition-colors hover:bg-gray-100
                ${i === 0 && item.active ? "bg-gray-100 font-medium text-gray-900" : "text-gray-500"}`}
            >
              {child}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ProductDetailModal({ product, onClose }) {
  if (!product) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-2xl" onClick={e => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-bold">{product.name}</h2>
            <p className="text-sm text-gray-500">Карточка товара — {product.article}</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 hover:bg-gray-100"><X size={20} /></button>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div><p className="text-xs text-gray-400">Артикул</p><p className="text-sm font-mono">{product.article}</p></div>
            <div><p className="text-xs text-gray-400">ГОСТ / Чертёж</p><p className="text-sm">{product.gost}</p></div>
          </div>
          <hr />
          <div className="grid grid-cols-2 gap-4">
            <div><p className="text-xs text-gray-400">Домен</p><div className="mt-1"><DomainBadge domain={product.domain} /></div></div>
            <div><p className="text-xs text-gray-400">Категория</p><p className="text-sm">{product.category}</p></div>
          </div>
          <hr />
          <div className="grid grid-cols-3 gap-4">
            <div><p className="text-xs text-gray-400">Ед. измерения</p><p className="text-sm">{product.uom}</p></div>
            <div><p className="text-xs text-gray-400">Количество</p><p className="text-sm font-medium tabular-nums">{product.quantity.toLocaleString("ru-RU")}</p></div>
            <div><p className="text-xs text-gray-400">Статус</p><div className="mt-1"><StatusBadge status={product.status} /></div></div>
          </div>
          <hr />
          <div className="grid grid-cols-2 gap-4">
            <div><p className="text-xs text-gray-400">Производитель</p><p className="text-sm">{product.manufacturer}</p></div>
            <div><p className="text-xs text-gray-400">Дата добавления</p><p className="text-sm">{product.addedDate}</p></div>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border px-4 py-2 text-sm font-medium hover:bg-gray-50">Закрыть</button>
          <button className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800">Добавить в запрос</button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Component ────────────────────────────────────────────────────────

export default function App() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [domainFilter, setDomainFilter] = useState("all");
  const [currentPage, setCurrentPage] = useState(1);
  const [perPage, setPerPage] = useState(10);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [activeTab, setActiveTab] = useState("product_list");
  const [detailProduct, setDetailProduct] = useState(null);
  const [menuOpenId, setMenuOpenId] = useState(null);

  const filtered = useMemo(() => {
    return products.filter(p => {
      const s = search.toLowerCase();
      const matchSearch = !s || p.name.toLowerCase().includes(s) || p.article.toLowerCase().includes(s) || p.gost.toLowerCase().includes(s) || p.manufacturer.toLowerCase().includes(s);
      const matchStatus = statusFilter === "all" || p.status === statusFilter;
      const matchDomain = domainFilter === "all" || p.domain === domainFilter;
      return matchSearch && matchStatus && matchDomain;
    });
  }, [search, statusFilter, domainFilter]);

  const totalPages = Math.ceil(filtered.length / perPage);
  const paginated = filtered.slice((currentPage - 1) * perPage, currentPage * perPage);

  const inStockCount = products.filter(p => p.status === "in_stock").length;
  const toOrderCount = products.filter(p => p.status === "to_order").length;
  const sourcingCount = products.filter(p => p.status === "sourcing").length;

  const toggleSelect = id => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    setSelectedIds(prev => prev.size === paginated.length ? new Set() : new Set(paginated.map(p => p.id)));
  };

  const tabs = [
    { id: "product_list", label: "Список товаров" },
    { id: "categories", label: "Категории" },
    { id: "equipment_groups", label: "Группы техники" },
  ];

  return (
    <div className="flex h-screen bg-gray-50 font-sans text-gray-900" style={{ fontFamily: "'Inter', system-ui, -apple-system, sans-serif" }}>
      {/* ─── Sidebar ─── */}
      <aside className="flex w-64 flex-col border-r bg-white">
        <div className="flex h-14 items-center gap-2 border-b px-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gray-900 text-white"><Layers size={16} /></div>
          <span className="text-base font-bold tracking-tight">RAILTECH</span>
        </div>
        <div className="px-3 pt-3">
          <div className="relative">
            <SearchIcon size={16} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input placeholder="Поиск..." className="h-8 w-full rounded-md border bg-transparent pl-8 pr-3 text-xs outline-none focus:ring-2 focus:ring-gray-200" />
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-3">
          {navItems.map(item => <NavItem key={item.label} item={item} />)}
        </nav>
        <hr />
        <nav className="space-y-0.5 px-3 py-2">
          {bottomNav.map(item => <NavItem key={item.label} item={item} />)}
        </nav>
        <hr />
        <div className="p-3">
          <div className="flex items-center gap-3 rounded-lg px-2 py-2 hover:bg-gray-50">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-900 text-xs font-bold text-white">RT</div>
            <div className="flex-1">
              <p className="text-sm font-medium leading-none">RailTech</p>
              <p className="mt-0.5 text-xs text-gray-500">Менеджер</p>
            </div>
            <ChevronDown size={16} className="text-gray-400" />
          </div>
        </div>
      </aside>

      {/* ─── Main Area ─── */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top bar */}
        <header className="flex h-14 items-center justify-between border-b bg-white px-6">
          <div />
          <div className="flex items-center gap-1">
            <button className="relative rounded-lg p-2 hover:bg-gray-100"><MessageSquare size={18} className="text-gray-500" /></button>
            <button className="relative rounded-lg p-2 hover:bg-gray-100">
              <Bell size={18} className="text-gray-500" />
              <span className="absolute right-1 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white">5</span>
            </button>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-y-auto p-6">
          <div className="mx-auto flex max-w-7xl flex-col gap-6">
            {/* Header */}
            <div className="flex items-center justify-between">
              <h1 className="text-2xl font-bold tracking-tight">Номенклатура</h1>
              <div className="flex items-center gap-2">
                <button className="flex items-center gap-2 rounded-lg border bg-white px-4 py-2 text-sm font-medium hover:bg-gray-50">
                  <Download size={16} /> Экспорт CSV
                </button>
                <button className="flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800">
                  <Plus size={16} /> Добавить
                </button>
              </div>
            </div>

            {/* Tabs */}
            <div className="flex gap-1 rounded-lg bg-gray-100 p-1 w-fit">
              {tabs.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors
                    ${activeTab === tab.id ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"}`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* KPI Cards */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <KPICard title="Всего позиций" value={products.length} change={3} icon={Package} changeColor="text-emerald-600" />
              <KPICard title="В наличии" value={inStockCount} change={2} icon={PackageCheck} changeColor="text-emerald-600" />
              <KPICard title="Под заказ" value={toOrderCount} change={-1} icon={PackageSearch} changeColor="text-red-500" />
              <KPICard title="На поиске" value={sourcingCount} change={1} icon={PackageX} changeColor="text-amber-600" />
            </div>

            {/* Filters */}
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="relative w-full max-w-sm">
                <SearchIcon size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  placeholder="Поиск..."
                  className="h-9 w-full rounded-md border bg-white pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-gray-200"
                  value={search}
                  onChange={e => { setSearch(e.target.value); setCurrentPage(1); }}
                />
              </div>
              <div className="flex items-center gap-2">
                <select
                  value={domainFilter}
                  onChange={e => { setDomainFilter(e.target.value); setCurrentPage(1); }}
                  className="h-9 rounded-md border bg-white px-3 text-sm outline-none focus:ring-2 focus:ring-gray-200"
                >
                  <option value="all">Все домены</option>
                  <option value="RAILWAY_MACHINERY">ЖД и Техника</option>
                  <option value="GENERAL_GOODS">Общие товары</option>
                  <option value="SERVICES">Услуги</option>
                </select>
                <select
                  value={statusFilter}
                  onChange={e => { setStatusFilter(e.target.value); setCurrentPage(1); }}
                  className="h-9 rounded-md border bg-white px-3 text-sm outline-none focus:ring-2 focus:ring-gray-200"
                >
                  <option value="all">Все статусы</option>
                  <option value="in_stock">В наличии</option>
                  <option value="to_order">Под заказ</option>
                  <option value="sourcing">Поиск</option>
                  <option value="inactive">Неактивно</option>
                </select>
              </div>
            </div>

            {/* Table */}
            <div className="overflow-hidden rounded-xl border bg-white shadow-sm">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-gray-50/60">
                      <th className="w-10 px-4 py-3">
                        <input
                          type="checkbox"
                          checked={paginated.length > 0 && selectedIds.size === paginated.length}
                          onChange={toggleAll}
                          className="h-4 w-4 rounded border-gray-300"
                        />
                      </th>
                      <th className="px-3 py-3 text-left font-medium text-gray-700">
                        <span className="flex items-center gap-1">Наименование <ArrowUpDown size={12} className="text-gray-400" /></span>
                      </th>
                      <th className="px-3 py-3 text-left font-medium text-gray-700">
                        <span className="flex items-center gap-1">Артикул <ArrowUpDown size={12} className="text-gray-400" /></span>
                      </th>
                      <th className="px-3 py-3 text-left font-medium text-gray-700">ГОСТ / Чертёж</th>
                      <th className="px-3 py-3 text-left font-medium text-gray-700">Домен</th>
                      <th className="px-3 py-3 text-left font-medium text-gray-700">Категория</th>
                      <th className="px-3 py-3 text-left font-medium text-gray-700">Ед. изм</th>
                      <th className="px-3 py-3 text-right font-medium text-gray-700">
                        <span className="flex items-center justify-end gap-1">Кол-во <ArrowUpDown size={12} className="text-gray-400" /></span>
                      </th>
                      <th className="px-3 py-3 text-left font-medium text-gray-700">
                        <span className="flex items-center gap-1">Добавлен <ArrowUpDown size={12} className="text-gray-400" /></span>
                      </th>
                      <th className="px-3 py-3 text-left font-medium text-gray-700">Статус</th>
                      <th className="w-10 px-3 py-3" />
                    </tr>
                  </thead>
                  <tbody>
                    {paginated.length === 0 ? (
                      <tr>
                        <td colSpan={11} className="py-16 text-center">
                          <div className="flex flex-col items-center gap-2 text-gray-400">
                            <PackageSearch size={32} />
                            <p className="text-sm">Товары не найдены</p>
                            <p className="text-xs">Попробуйте изменить параметры поиска</p>
                          </div>
                        </td>
                      </tr>
                    ) : paginated.map(product => (
                      <tr
                        key={product.id}
                        className="border-b transition-colors hover:bg-gray-50/60 cursor-pointer"
                        onClick={() => setDetailProduct(product)}
                      >
                        <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={selectedIds.has(product.id)}
                            onChange={() => toggleSelect(product.id)}
                            className="h-4 w-4 rounded border-gray-300"
                          />
                        </td>
                        <td className="px-3 py-3">
                          <div className="flex flex-col">
                            <span className="font-medium">{product.name}</span>
                            <span className="text-xs text-gray-500">{product.manufacturer}</span>
                          </div>
                        </td>
                        <td className="px-3 py-3 font-mono text-xs text-blue-600">{product.article}</td>
                        <td className="px-3 py-3 text-xs text-gray-500">{product.gost}</td>
                        <td className="px-3 py-3"><DomainBadge domain={product.domain} /></td>
                        <td className="px-3 py-3">{product.category}</td>
                        <td className="px-3 py-3">{product.uom}</td>
                        <td className="px-3 py-3 text-right font-medium tabular-nums">{product.quantity.toLocaleString("ru-RU")}</td>
                        <td className="px-3 py-3 text-xs text-gray-500">{product.addedDate}</td>
                        <td className="px-3 py-3"><StatusBadge status={product.status} /></td>
                        <td className="px-3 py-3" onClick={e => e.stopPropagation()}>
                          <div className="relative">
                            <button
                              onClick={() => setMenuOpenId(menuOpenId === product.id ? null : product.id)}
                              className="rounded-lg p-1 hover:bg-gray-100"
                            >
                              <MoreVertical size={16} className="text-gray-400" />
                            </button>
                            {menuOpenId === product.id && (
                              <>
                                <div className="fixed inset-0 z-40" onClick={() => setMenuOpenId(null)} />
                                <div className="absolute right-0 z-50 mt-1 w-40 rounded-lg border bg-white py-1 shadow-lg">
                                  <button onClick={() => { setDetailProduct(product); setMenuOpenId(null); }} className="w-full px-3 py-1.5 text-left text-sm hover:bg-gray-50">Подробнее</button>
                                  <button onClick={() => setMenuOpenId(null)} className="w-full px-3 py-1.5 text-left text-sm hover:bg-gray-50">Редактировать</button>
                                  <button onClick={() => setMenuOpenId(null)} className="w-full px-3 py-1.5 text-left text-sm hover:bg-gray-50">В запрос</button>
                                  <button onClick={() => setMenuOpenId(null)} className="w-full px-3 py-1.5 text-left text-sm text-red-600 hover:bg-red-50">Удалить</button>
                                </div>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="flex items-center justify-between border-t px-4 py-3">
                <select
                  value={perPage}
                  onChange={e => { setPerPage(Number(e.target.value)); setCurrentPage(1); }}
                  className="h-8 rounded-md border bg-white px-2 text-xs outline-none"
                >
                  <option value={10}>10 записей</option>
                  <option value={20}>20 записей</option>
                  <option value={50}>50 записей</option>
                </select>

                <div className="flex items-center gap-1">
                  <button
                    disabled={currentPage === 1}
                    onClick={() => setCurrentPage(p => p - 1)}
                    className="flex h-8 w-8 items-center justify-center rounded-md border bg-white text-sm disabled:opacity-40 hover:bg-gray-50"
                  >
                    <ChevronLeft size={16} />
                  </button>
                  {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
                    let page;
                    if (totalPages <= 5) page = i + 1;
                    else if (currentPage <= 3) page = i + 1;
                    else if (currentPage >= totalPages - 2) page = totalPages - 4 + i;
                    else page = currentPage - 2 + i;
                    return (
                      <button
                        key={page}
                        onClick={() => setCurrentPage(page)}
                        className={`flex h-8 w-8 items-center justify-center rounded-md text-sm font-medium
                          ${currentPage === page ? "bg-gray-900 text-white" : "border bg-white hover:bg-gray-50"}`}
                      >
                        {page}
                      </button>
                    );
                  })}
                  <button
                    disabled={currentPage === totalPages || totalPages === 0}
                    onClick={() => setCurrentPage(p => p + 1)}
                    className="flex h-8 w-8 items-center justify-center rounded-md border bg-white text-sm disabled:opacity-40 hover:bg-gray-50"
                  >
                    <ChevronRight size={16} />
                  </button>
                  <span className="ml-2 text-xs text-gray-500">
                    {(currentPage - 1) * perPage + 1}–{Math.min(currentPage * perPage, filtered.length)} из {filtered.length}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>

      {/* Detail Modal */}
      <ProductDetailModal product={detailProduct} onClose={() => setDetailProduct(null)} />
    </div>
  );
}
