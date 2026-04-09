import React, { useEffect, useState } from 'react';
import {
    Building2, Shield, FileText, Upload, Trash2,
    AlertTriangle, BadgeCheck, FileQuestion, Loader2
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { accountsApi, Company, KYCDocument } from '../../api/accountsApi';
import { useAuthStore } from '../../store/authStore';
import { CompanyTeamSettings } from './CompanyTeamSettings';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import { Button } from '@/components/ui/button';

const STATUS_CONFIG: Record<string, { icon: React.ElementType; color: string; bg: string; border: string }> = {
    L1_UNVERIFIED: { icon: AlertTriangle, color: 'text-warning', bg: 'bg-warning/10', border: 'border-warning/20' },
    PROFILE_SUBMITTED: { icon: FileText, color: 'text-primary', bg: 'bg-primary/10', border: 'border-primary/20' },
    L2_VERIFIED: { icon: Shield, color: 'text-success', bg: 'bg-success/10', border: 'border-success/20' },
    L3_CONTRACTED: { icon: BadgeCheck, color: 'text-primary', bg: 'bg-primary/10', border: 'border-primary/20' },
};

const DOC_TYPE_VALUES = ['CHARTER', 'LICENSE', 'PASSPORT', 'TAX_CERT', 'OTHER'] as const;

export const CompanyProfile: React.FC = () => {
    const { user } = useAuthStore();
    const { t } = useTranslation();
    const [company, setCompany] = useState<Company | null>(null);
    const [loading, setLoading] = useState(true);
    const [uploading, setUploading] = useState(false);
    const [selectedDocType, setSelectedDocType] = useState('CHARTER');

    useEffect(() => {
        const load = async () => {
            // Use the company embedded in the /me/ response (avoids 403 from manager-only getCompanies())
            if (user?.company) {
                // Fetch full company detail to get kyc_documents list
                if (user.company.id) {
                    try {
                        const resp = await accountsApi.getCompanyDetail(user.company.id);
                        setCompany(resp);
                    } catch {
                        // Fallback to partial user.company data if detail fetch fails
                        setCompany(user.company as Company);
                    }
                } else {
                    setCompany(user.company as Company);
                }
            } else {
                setCompany(null);
            }
            setLoading(false);
        };
        load();
    }, [user]);

    const handleDeleteDoc = async (docId: number) => {
        if (!company || !confirm(t('company.deleteConfirm'))) return;
        try {
            await accountsApi.deleteDocument(company.id, docId);
            const refreshed = await accountsApi.getCompanyDetail(company.id);
            setCompany(refreshed);
        } catch (err) { console.error('Operation failed', err); alert(t('company.deleteDocError')); }
    };

    const handleUpload = async (file: File) => {
        if (!company) return;
        setUploading(true);
        try {
            await accountsApi.uploadDocument(company.id, file, selectedDocType);
            // Reload company data via detail endpoint (getCompanies is manager-only)
            const refreshed = await accountsApi.getCompanyDetail(company.id);
            setCompany(refreshed);
        } catch (err) { console.error('Operation failed', err); alert(t('company.uploadError')); }
        finally { setUploading(false); }
    };

    if (loading) return (
        <div className="flex h-full items-center justify-center">
            <Loader2 className="w-8 h-8 text-muted-foreground animate-spin" />
        </div>
    );

    const kycInfo = company ? STATUS_CONFIG[company.verification_status] : null;
    const KycIcon = kycInfo?.icon || Shield;

    return (
        <div className="p-6 md:p-10 max-w-4xl mx-auto">
            <div className="mb-8">
                <h1 className="text-3xl font-black tracking-tight text-foreground mb-1">
                    {t('company.title')} <span className="text-primary">{t('company.titleHighlight')}</span>
                </h1>
                <p className="text-muted-foreground font-medium">{t('company.subtitle')}</p>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
                {/* Left — Company Info */}
                <div className="lg:col-span-3 space-y-6">
                    {/* KYC Status */}
                    {kycInfo && (
                        <div className={`flex items-center gap-4 p-5 rounded-2xl border ${kycInfo.bg} ${kycInfo.border}`}>
                            <KycIcon className={`w-6 h-6 shrink-0 ${kycInfo.color}`} />
                            <div>
                                <p className={`text-sm font-black ${kycInfo.color}`}>{t(`company.status.${company?.verification_status}`)}</p>
                                <p className="text-xs text-muted-foreground font-medium mt-0.5">
                                    {company?.verification_status === 'L1_UNVERIFIED'
                                        ? t('company.statusHint.unverified')
                                        : t('company.statusHint.verified')}
                                </p>
                            </div>
                        </div>
                    )}

                    {/* Company Details */}
                    <div className="bg-card border border-border rounded-3xl p-6">
                        <div className="flex items-center gap-3 mb-6">
                            <Building2 className="w-5 h-5 text-primary" />
                            <h2 className="text-base font-black text-foreground">{t('company.details')}</h2>
                        </div>
                        <div className="space-y-4">
                            {company ? (
                                <>
                                    {[
                                        { label: t('company.name'), value: company.name },
                                        { label: t('company.inn'), value: company.inn },
                                        { label: t('company.mfo'), value: company.mfo || '—' },
                                        { label: t('company.bankAccount'), value: company.bank_account || '—' },
                                        { label: t('company.contactPerson'), value: company.contact_person || '—' },
                                        { label: t('company.legalAddress'), value: company.legal_address || '—' },
                                    ].map(({ label, value }) => (
                                        <div key={label} className="flex justify-between items-start py-3 border-b border-border last:border-0">
                                            <span className="text-xs font-bold text-muted-foreground w-1/2">{label}</span>
                                            <span className="text-sm font-bold text-foreground text-right">{value}</span>
                                        </div>
                                    ))}
                                </>
                            ) : (
                                <p className="text-muted-foreground text-sm text-center py-6">{t('company.noCompany')}</p>
                            )}
                        </div>
                    </div>
                </div>

                {/* Right — Documents */}
                <div className="lg:col-span-2 space-y-6">
                    <div className="bg-card border border-border rounded-3xl p-6">
                        <div className="flex items-center gap-3 mb-5">
                            <FileText className="w-5 h-5 text-primary" />
                            <h2 className="text-base font-black text-foreground">{t('company.kycDocuments')}</h2>
                            <span className="ml-auto text-xs font-black text-muted-foreground">
                                {t('company.docCount', { count: company?.kyc_documents?.length || 0 })}
                            </span>
                        </div>

                        {/* Doc list */}
                        <div className="space-y-2 mb-5">
                            {(company?.kyc_documents || []).length === 0 ? (
                                <div className="py-8 text-center rounded-2xl bg-muted border border-dashed border-border">
                                    <FileQuestion className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                                    <p className="text-xs text-muted-foreground">{t('company.noDocuments')}</p>
                                </div>
                            ) : (
                                (company?.kyc_documents || []).map((doc: KYCDocument) => (
                                    <div key={doc.id} className="flex items-center gap-3 p-3 rounded-xl bg-muted border border-border">
                                        <FileText className="w-4 h-4 text-primary shrink-0" />
                                        <div className="min-w-0">
                                            <p className="text-xs font-black truncate text-foreground">{doc.original_filename}</p>
                                            <p className="text-xs text-muted-foreground">{doc.doc_type_display}</p>
                                        </div>
                                        <Button variant="ghost" size="icon" onClick={() => handleDeleteDoc(doc.id)} className="p-1 h-auto w-auto text-muted-foreground hover:text-destructive transition-colors rounded shrink-0 ml-auto" title={t('common.delete')}>
                                            <Trash2 className="w-3.5 h-3.5" />
                                        </Button>
                                    </div>
                                ))
                            )}
                        </div>

                        {/* Upload */}
                        {company && (
                            <div className="space-y-3">
                                <Select value={selectedDocType} onValueChange={setSelectedDocType}>
                                    <SelectTrigger className="w-full">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {DOC_TYPE_VALUES.map(dt => <SelectItem key={dt} value={dt}>{t(`company.docTypes.${dt}`)}</SelectItem>)}
                                    </SelectContent>
                                </Select>
                                <label className={`w-full flex items-center justify-center gap-2 py-3 border-2 border-dashed rounded-xl text-xs font-black uppercase tracking-widest transition-all cursor-pointer ${uploading
                                    ? 'border-ring text-muted-foreground'
                                    : 'border-border text-muted-foreground hover:border-ring hover:text-foreground'
                                    }`}>
                                    {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                                    {uploading ? t('company.uploading') : t('company.uploadDoc')}
                                    <input type="file" className="hidden" accept=".pdf,.doc,.docx,.jpg,.png"
                                        onChange={e => { const f = e.target.files?.[0]; if (f) handleUpload(f); e.target.value = ''; }}
                                    />
                                </label>
                            </div>
                        )}
                    </div>

                    {/* Contacts */}
                    <div className="bg-card border border-border rounded-3xl p-6">
                        <h2 className="text-sm font-black text-foreground mb-3">{t('company.manager')}</h2>
                        <p className="text-xs text-muted-foreground font-medium leading-relaxed">
                            {t('company.managerHint')}
                        </p>
                        <p className="text-sm font-black text-primary mt-2">managers@railtech.uz</p>
                    </div>
                </div>
            </div>

            <div className="mt-8 border-t border-border pt-8">
                <CompanyTeamSettings />
            </div>
        </div>
    );
};
