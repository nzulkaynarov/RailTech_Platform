import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ShieldQuestion, UploadCloud } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

import { useUserStore } from '@/store/userStore';
import { useCreateRoleApplication } from '@/hooks/useAccounts';
import { accountsApi } from '@/api/accountsApi';

function FilePicker({
    label, value, onChange, accept = '.pdf,.doc,.docx',
}: {
    label: string;
    value: File | null;
    onChange: (f: File | null) => void;
    accept?: string;
}) {
    return (
        <div className="flex flex-col gap-2">
            <Label>{label}</Label>
            <label className="flex cursor-pointer items-center justify-between gap-3 rounded-md border border-dashed p-3 hover:bg-accent">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <UploadCloud className="size-4" />
                    {value ? value.name : label}
                </div>
                <input
                    type="file"
                    accept={accept}
                    className="hidden"
                    onChange={e => onChange(e.target.files?.[0] ?? null)}
                />
                <Badge variant={value ? 'default' : 'outline'}>
                    {value ? '✓' : '—'}
                </Badge>
            </label>
        </div>
    );
}

export function RoleApplicationForm() {
    const { t } = useTranslation();
    const { company } = useUserStore();
    const createMut = useCreateRoleApplication();

    const { data: allTypes = [] } = useQuery({
        queryKey: ['company-types'],
        queryFn: () => accountsApi.getCompanyTypes(),
        staleTime: 60 * 60_000,
    });

    const applicableTypes = useMemo(
        () => allTypes.filter(t => t.code === 'SUPPLIER' || t.code === 'MANUFACTURER'),
        [allTypes],
    );

    const [selectedTypeId, setSelectedTypeId] = useState<number | null>(null);
    const [contract, setContract] = useState<File | null>(null);
    const [nda, setNda] = useState<File | null>(null);
    const [partnership, setPartnership] = useState<File | null>(null);

    const selectedType = applicableTypes.find(t => t.id === selectedTypeId);
    const companyId = company.id;

    const handleSubmit = async () => {
        if (!companyId) {
            toast.error(t('common.error'));
            return;
        }
        if (!selectedType) {
            toast.error(t('roleApplication.errors.typeRequired'));
            return;
        }
        if (selectedType.code === 'SUPPLIER' && (!contract || !nda)) {
            toast.error(t('roleApplication.errors.contractAndNdaRequired'));
            return;
        }
        if (selectedType.code === 'MANUFACTURER' && !partnership) {
            toast.error(t('roleApplication.errors.partnershipRequired'));
            return;
        }
        try {
            await createMut.mutateAsync({
                company: companyId,
                requested_type: selectedType.id,
                contract_file: selectedType.code === 'SUPPLIER' ? contract : null,
                nda_file: selectedType.code === 'SUPPLIER' ? nda : null,
                partnership_agreement: selectedType.code === 'MANUFACTURER' ? partnership : null,
            });
            toast.success(t('roleApplication.submitted'));
            setContract(null); setNda(null); setPartnership(null); setSelectedTypeId(null);
        } catch (e) {
            const msg = (e as { response?: { data?: { detail?: string; error?: string } } })?.response?.data;
            toast.error(msg?.detail || msg?.error || t('common.error'));
        }
    };

    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                    <ShieldQuestion className="size-5 text-primary" />
                    {t('roleApplication.title')}
                </CardTitle>
                <CardDescription>{t('roleApplication.description')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
                <div className="space-y-2">
                    <Label>{t('roleApplication.requestedType')}</Label>
                    <Select
                        value={selectedTypeId ? String(selectedTypeId) : undefined}
                        onValueChange={(v) => setSelectedTypeId(Number(v))}
                    >
                        <SelectTrigger>
                            <SelectValue placeholder="—" />
                        </SelectTrigger>
                        <SelectContent>
                            {applicableTypes.map(ct => (
                                <SelectItem key={ct.id} value={String(ct.id)}>{ct.name}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>

                {selectedType?.code === 'SUPPLIER' && (
                    <>
                        <FilePicker label={t('roleApplication.contract')} value={contract} onChange={setContract} />
                        <FilePicker label={t('roleApplication.nda')} value={nda} onChange={setNda} />
                    </>
                )}
                {selectedType?.code === 'MANUFACTURER' && (
                    <FilePicker label={t('roleApplication.partnership')} value={partnership} onChange={setPartnership} />
                )}

                <Button
                    onClick={handleSubmit}
                    disabled={createMut.isPending || !selectedType}
                    className="w-full"
                >
                    {createMut.isPending ? t('common.saving') : t('roleApplication.submit')}
                </Button>
            </CardContent>
        </Card>
    );
}
