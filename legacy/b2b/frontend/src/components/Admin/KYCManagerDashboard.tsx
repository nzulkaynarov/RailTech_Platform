import React, { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
	ShieldCheck, XCircle, Clock, FileText, Upload,
	ChevronRight, RefreshCw, Search,
	CheckCircle2, AlertTriangle, FileQuestion, BadgeCheck,
	Loader2, X
} from 'lucide-react';
import { Company, accountsApi } from '../../api/accountsApi';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

type FilterStatus = 'ALL' | 'L1_UNVERIFIED' | 'PROFILE_SUBMITTED' | 'L2_VERIFIED' | 'L3_CONTRACTED';

const STATUS_CONFIG = {
	L1_UNVERIFIED: {
		label: 'P_PENDING',
		icon: Clock,
		color: 'text-warning',
		bg: 'bg-warning/5',
		border: 'border-warning/20',
		badge: 'bg-warning/10 text-warning border border-warning/20',
	},
	PROFILE_SUBMITTED: {
		label: 'P_SUBMITTED',
		icon: FileText,
		color: 'text-primary',
		bg: 'bg-primary/5',
		border: 'border-primary/20',
		badge: 'bg-primary/10 text-primary border border-primary/20',
	},
	L2_VERIFIED: {
		label: 'V_VERIFIED_L2',
		icon: ShieldCheck,
		color: 'text-success',
		bg: 'bg-success/5',
		border: 'border-success/20',
		badge: 'bg-success/10 text-success border border-success/20',
	},
	L3_CONTRACTED: {
		label: 'V_PARTNER_L3',
		icon: BadgeCheck,
		color: 'text-primary',
		bg: 'bg-primary/5',
		border: 'border-primary/20',
		badge: 'bg-primary/10 text-primary border border-primary/20',
	},
};

const DOC_TYPE_KEYS = [
	{ value: 'CHARTER', labelKey: 'kycManager.docTypes.charter' },
	{ value: 'LICENSE', labelKey: 'kycManager.docTypes.license' },
	{ value: 'PASSPORT', labelKey: 'kycManager.docTypes.passport' },
	{ value: 'TAX_CERT', labelKey: 'kycManager.docTypes.taxCert' },
	{ value: 'OTHER', labelKey: 'kycManager.docTypes.other' },
];

// --- Company Detail Side Panel ---
interface SidePanelProps {
	company: Company;
	onClose: () => void;
	onVerify: (id: number, status: string, comment?: string) => void;
	onUpload: (id: number, file: File, docType: string) => void;
	busy: boolean;
}

const CompanyDetailPanel: React.FC<SidePanelProps> = ({ company, onClose, onVerify, onUpload, busy }) => {
	const { t } = useTranslation();
	const [comment, setComment] = useState(company.kyc_notes || '');
	const [selectedDocType, setSelectedDocType] = useState('CHARTER');
	const fileInputRef = useRef<HTMLInputElement>(null);
	const statusKey = (company.verification_status_code || company.verification_status) as keyof typeof STATUS_CONFIG;
	const cfg = STATUS_CONFIG[statusKey] || STATUS_CONFIG.L1_UNVERIFIED;
	const StatusIcon = cfg.icon;

	return (
		<div className="w-full h-full flex flex-col border-l border-border bg-card overflow-hidden font-mono shadow-xl">
			{/* Panel Header */}
			<div className="p-4 border-b border-border flex items-center justify-between bg-muted/50">
				<div>
					<p className="text-xs font-black uppercase tracking-widest text-muted-foreground mb-0.5">{t('kycManager.entityReview')}</p>
					<h2 className="text-sm font-black text-foreground uppercase truncate max-w-[200px]">{company.name}</h2>
				</div>
				<Button variant="ghost" size="icon-xs" onClick={onClose}>
					<X className="w-4 h-4 text-muted-foreground" />
				</Button>
			</div>

			{/* Scrollable Content */}
			<div className="flex-1 overflow-y-auto p-4 space-y-6 custom-scrollbar">
				{/* Status */}
				<div>
					<p className="text-xs font-black uppercase tracking-widest text-muted-foreground mb-2">{t('kycManager.authStatus')}</p>
					<div className={`flex items-center gap-2.5 p-3 rounded border ${cfg.bg} ${cfg.border}`}>
						<StatusIcon className={`w-4 h-4 ${cfg.color}`} />
						<span className={`text-xs font-black ${cfg.color} tracking-tighter`}>{cfg.label}</span>
					</div>
				</div>

				{/* Company Info */}
				<div>
					<p className="text-xs font-black uppercase tracking-widest text-muted-foreground mb-2">{t('kycManager.registryData')}</p>
					<div className="space-y-1.5 border border-border rounded p-2">
						{[
							{ label: t('kycManager.registryFields.taxId'), value: company.inn },
							{ label: t('kycManager.registryFields.mfoCode'), value: company.mfo || 'NULL' },
							{ label: t('kycManager.registryFields.bankAcc'), value: company.bank_account || 'NULL' },
							{ label: t('kycManager.registryFields.opContact'), value: company.contact_person || 'NULL' },
						].map(({ label, value }) => (
							<div key={label} className="flex items-center justify-between py-1 text-xs">
								<span className="font-bold text-muted-foreground tracking-tighter uppercase">{label}</span>
								<span className="font-black text-foreground select-all">{value}</span>
							</div>
						))}
					</div>
					{company.legal_address && (
						<div className="mt-2 p-2 bg-muted/50 rounded border border-border">
							<span className="text-xs font-bold text-muted-foreground uppercase block mb-1">{t('kycManager.physicalAddress')}</span>
							<span className="text-xs font-medium text-foreground/80 leading-tight uppercase">{company.legal_address}</span>
						</div>
					)}
				</div>

				{/* Documents */}
				<div>
					<div className="flex items-center justify-between mb-2">
						<p className="text-xs font-black uppercase tracking-widest text-muted-foreground">{t('kycManager.docRecords')}</p>
						<span className="text-xs font-black text-muted-foreground bg-muted px-1.5 py-0.5 rounded">{t('kycManager.docCount', { count: company.kyc_documents?.length || 0 })}</span>
					</div>
					<div className="space-y-1 mb-4">
						{(company.kyc_documents || []).map(doc => (
							<div key={doc.id} className="flex items-center gap-2.5 p-2 rounded bg-muted/50 border border-border group">
								<FileText className="w-3.5 h-3.5 text-primary shrink-0" />
								<div className="min-w-0 flex-1">
									<p className="text-xs font-black text-foreground/80 truncate tracking-tight uppercase">{doc.original_filename}</p>
									<p className="text-xs text-muted-foreground font-bold uppercase">{doc.doc_type_display}</p>
								</div>
								<CheckCircle2 className="w-3.5 h-3.5 text-success shrink-0 opacity-50" />
							</div>
						))}
						{(company.kyc_documents || []).length === 0 && (
							<div className="p-4 rounded border border-dashed border-border text-center bg-muted/20">
								<FileQuestion className="w-6 h-6 text-muted-foreground/30 mx-auto mb-1.5" />
								<p className="text-xs font-bold text-muted-foreground uppercase tracking-widest">{t('kycManager.noDocuments')}</p>
							</div>
						)}
					</div>

					{/* Upload Action */}
					<div className="space-y-2">
						<select
							value={selectedDocType}
							onChange={e => setSelectedDocType(e.target.value)}
							className="w-full bg-muted border border-border rounded px-3 py-1.5 text-xs font-black text-foreground outline-none focus:border-primary transition-all uppercase"
						>
							{DOC_TYPE_KEYS.map(dt => <option key={dt.value} value={dt.value}>{t(dt.labelKey)}</option>)}
						</select>
						<input ref={fileInputRef} type="file" className="hidden" accept=".pdf,.doc,.docx,.jpg,.png"
							onChange={e => {
								const f = e.target.files?.[0];
								if (f) onUpload(company.id, f, selectedDocType);
								e.target.value = '';
							}}
						/>
						<Button
							variant="outline"
							onClick={() => fileInputRef.current?.click()}
							disabled={busy}
							className="w-full flex items-center justify-center gap-2 py-2 border-dashed text-xs font-black uppercase tracking-widest text-muted-foreground hover:border-primary/50 hover:text-primary"
						>
							<Upload className="w-3 h-3" />
							{t('kycManager.importDoc')}
						</Button>
					</div>
				</div>

				{/* Notes */}
				<div>
					<p className="text-xs font-black uppercase tracking-widest text-muted-foreground mb-2">{t('kycManager.observations')}</p>
					<Textarea
						value={comment}
						onChange={e => setComment(e.target.value)}
						placeholder={t('kycManager.observationsPlaceholder')}
						rows={3}
						className="resize-none text-xs"
					/>
				</div>
			</div>

			{/* Action Overrides */}
			<div className="p-4 border-t border-border shrink-0 space-y-2 bg-muted/30">
				{(getStatusCode(company) === 'L1_UNVERIFIED' || getStatusCode(company) === 'PROFILE_SUBMITTED') && (
					<Button
						onClick={() => onVerify(company.id, 'L2_VERIFIED', comment)}
						disabled={busy}
						className="w-full flex items-center justify-center gap-2 py-2.5 font-black text-xs uppercase tracking-widest active:scale-[0.98] shadow-sm"
					>
						{busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldCheck className="w-3.5 h-3.5" />}
						{t('kycManager.approveL2')}
					</Button>
				)}
				{getStatusCode(company) === 'L2_VERIFIED' && (
					<Button
						onClick={() => onVerify(company.id, 'L3_CONTRACTED', comment)}
						disabled={busy}
						className="w-full flex items-center justify-center gap-2 py-2.5 font-black text-xs uppercase tracking-widest active:scale-[0.98] shadow-sm"
					>
						{busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <BadgeCheck className="w-3.5 h-3.5" />}
						{t('kycManager.upgradeL3')}
					</Button>
				)}
				{getStatusCode(company) !== 'L1_UNVERIFIED' && (
					<Button
						variant="destructive"
						onClick={() => onVerify(company.id, 'L1_UNVERIFIED', comment)}
						disabled={busy}
						className="w-full flex items-center justify-center gap-2 py-2 font-black text-xs uppercase tracking-widest active:scale-[0.98]"
					>
						<XCircle className="w-3.5 h-3.5" />
						{t('kycManager.revokeL1')}
					</Button>
				)}
			</div>
		</div>
	);
};

/** Get verification status code string regardless of API response format */
function getStatusCode(company: Company): string {
	return (company.verification_status_code || String(company.verification_status)) as string;
}

// --- Main Dashboard ---
export const KYCManagerDashboard: React.FC = () => {
	const { t } = useTranslation();
	const [companies, setCompanies] = useState<Company[]>([]);
	const [loading, setLoading] = useState(true);
	const [filter, setFilter] = useState<FilterStatus>('ALL');
	const [search, setSearch] = useState('');
	const [selectedCompany, setSelectedCompany] = useState<Company | null>(null);
	const [busy, setBusy] = useState(false);

	const loadCompanies = async () => {
		setLoading(true);
		try {
			const data = await accountsApi.getCompanies();
			setCompanies(data);
		} catch (error) {
			console.error('Failed to load companies', error);
		} finally {
			setLoading(false);
		}
	};

	useEffect(() => { loadCompanies(); }, []);

	const handleVerify = async (id: number, status: string, comment?: string) => {
		setBusy(true);
		try {
			await accountsApi.verifyCompany(id, status, comment);
			await loadCompanies();
			setSelectedCompany(prev => {
				if (!prev || prev.id !== id) return prev;
				return null;
			});
		} catch {
			toast.error(t('kycManager.operationFailure'));
		} finally {
			setBusy(false);
		}
	};

	const handleUpload = async (companyId: number, file: File, docType: string) => {
		setBusy(true);
		try {
			await accountsApi.uploadDocument(companyId, file, docType);
			await loadCompanies();
		} catch {
			toast.error(t('kycManager.uploadFailure'));
		} finally {
			setBusy(false);
		}
	};

	const counts = {
		ALL: companies.length,
		L1_UNVERIFIED: companies.filter(c => getStatusCode(c) === 'L1_UNVERIFIED').length,
		PROFILE_SUBMITTED: companies.filter(c => getStatusCode(c) === 'PROFILE_SUBMITTED').length,
		L2_VERIFIED: companies.filter(c => getStatusCode(c) === 'L2_VERIFIED').length,
		L3_CONTRACTED: companies.filter(c => getStatusCode(c) === 'L3_CONTRACTED').length,
	};

	const filtered = companies
		.filter(c => filter === 'ALL' || getStatusCode(c) === filter)
		.filter(c =>
			!search ||
			c.name.toLowerCase().includes(search.toLowerCase()) ||
			c.inn.includes(search)
		);

	return (
		<div className="h-full flex overflow-hidden animate-in fade-in duration-300 font-mono">
			{/* Main Panel */}
			<div className={`flex flex-col transition-all duration-300 border-r border-border ${selectedCompany ? 'w-full md:w-3/5' : 'w-full'}`}>
				{/* Header */}
				<div className="p-4 border-b border-border bg-card shrink-0">
					<div className="flex items-end justify-between mb-4">
						<div>
							<h1 className="text-xl font-black tracking-tight text-foreground uppercase leading-none">
								{t('kycManager.title')} <span className="text-primary">{t('kycManager.titleHighlight')}</span>
							</h1>
							<p className="text-xs font-bold text-muted-foreground uppercase tracking-widest leading-none mt-1">
								{t('kycManager.subtitle')}
							</p>
						</div>
						<div className="flex gap-2">
							<Button variant="outline" size="icon-xs" onClick={loadCompanies} className="shadow-sm">
								<RefreshCw className={`w-3.5 h-3.5 text-muted-foreground ${loading ? 'animate-spin' : ''}`} />
							</Button>
						</div>
					</div>

					{/* Stats Tabs */}
					<div className="flex gap-1.5 flex-wrap">
						{(['ALL', 'L1_UNVERIFIED', 'PROFILE_SUBMITTED', 'L2_VERIFIED', 'L3_CONTRACTED'] as FilterStatus[]).map(s => {
							const label = s === 'ALL' ? t('kycManager.globalView') : STATUS_CONFIG[s as keyof typeof STATUS_CONFIG].label;
							const count = counts[s];
							const isActive = filter === s;
							return (
								<Button
									key={s}
									variant={isActive ? 'default' : 'ghost'}
									size="xs"
									onClick={() => setFilter(s)}
									className={`flex items-center gap-2 text-xs font-black uppercase tracking-widest ${isActive
										? 'bg-foreground text-background hover:bg-foreground/90'
										: 'text-muted-foreground'
										}`}
								>
									{label}
									<span className={`px-1 rounded text-xs font-black ${isActive ? 'bg-background/20 text-background' : 'bg-muted text-muted-foreground'
										}`}>{count}</span>
								</Button>
							);
						})}
					</div>
				</div>

				{/* Search + List */}
				<div className="flex-1 overflow-y-auto p-4 space-y-2 bg-muted/20 custom-scrollbar">
					{/* Search */}
					<div className="relative group mb-4">
						<Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground group-focus-within:text-primary transition-colors pointer-events-none" />
						<Input
							type="text"
							placeholder={t('kycManager.searchPlaceholder')}
							value={search}
							onChange={e => setSearch(e.target.value)}
							className="pl-9 text-xs font-mono"
						/>
					</div>

					{loading ? (
						<div className="flex items-center justify-center py-20">
							<Loader2 className="w-6 h-6 text-primary animate-spin" />
						</div>
					) : filtered.length === 0 ? (
						<div className="text-center py-20 rounded border border-dashed border-border bg-card/50">
							<AlertTriangle className="w-8 h-8 text-muted-foreground/30 mx-auto mb-2" />
							<p className="text-xs font-black uppercase tracking-widest text-muted-foreground">{t('kycManager.emptyState')}</p>
						</div>
					) : (
						filtered.map(company => {
							const cfg = STATUS_CONFIG[getStatusCode(company) as keyof typeof STATUS_CONFIG] || STATUS_CONFIG.L1_UNVERIFIED;
							const CfgIcon = cfg.icon;
							const isSelected = selectedCompany?.id === company.id;
							return (
								<div
									key={company.id}
									onClick={() => setSelectedCompany(isSelected ? null : company)}
									className={`group flex items-center justify-between p-3 rounded border cursor-pointer transition-all duration-200 ${isSelected
										? 'bg-primary/5 border-primary/40 relative before:absolute before:left-0 before:top-2 before:bottom-2 before:w-1 before:bg-primary shadow-sm'
										: 'bg-card border-border hover:border-border'
										}`}
								>
									<div className="flex items-center gap-4 min-w-0">
										<div className={`w-9 h-9 shrink-0 rounded flex items-center justify-center border ${cfg.bg} ${cfg.border} transition-transform`}>
											<CfgIcon className={`w-4 h-4 ${cfg.color}`} />
										</div>
										<div className="min-w-0">
											<h3 className="text-xs font-black text-foreground uppercase truncate tracking-tight">{company.name}</h3>
											<div className="flex items-center gap-2.5 mt-0.5">
												<span className="text-xs text-muted-foreground font-bold tracking-widest">ID: {company.inn}</span>
												<span className={`text-xs font-black uppercase tracking-wider px-1.5 py-0.5 rounded ${cfg.badge}`}>
													{cfg.label}
												</span>
												{(company.kyc_documents?.length || 0) > 0 && (
													<span className="flex items-center gap-1 text-xs text-muted-foreground font-bold uppercase tracking-widest">
														<FileText className="w-2.5 h-2.5" />
														{company.kyc_documents!.length} DOCS
													</span>
												)}
											</div>
										</div>
									</div>
									<ChevronRight className={`w-4 h-4 transition-all ${isSelected ? 'text-primary rotate-90' : 'text-muted-foreground group-hover:text-muted-foreground group-hover:translate-x-0.5'}`} />
								</div>
							);
						})
					)}
				</div>
			</div>

			{/* Side Panel Desktop */}
			{selectedCompany && (
				<div className="hidden md:flex w-2/5 h-full animate-in slide-in-from-right duration-300 border-l border-border">
					<CompanyDetailPanel
						company={selectedCompany}
						onClose={() => setSelectedCompany(null)}
						onVerify={handleVerify}
						onUpload={handleUpload}
						busy={busy}
					/>
				</div>
			)}
		</div>
	);
};
