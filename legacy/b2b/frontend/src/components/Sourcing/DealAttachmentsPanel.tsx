import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { sourcingApi } from '@/api/sourcingApi';
import { FileUpload } from '@/components/Shared/FileUpload';
import { useTranslation } from 'react-i18next';

interface DealAttachmentsPanelProps {
    dealId: number;
    className?: string;
    label?: string;
    description?: string;
}

export function DealAttachmentsPanel({
    dealId, className, label, description,
}: DealAttachmentsPanelProps) {
    const { t } = useTranslation();
    const qc = useQueryClient();

    const { data: files = [] } = useQuery({
        queryKey: ['deal-attachments', dealId],
        queryFn: () => sourcingApi.listAttachments({ deal: dealId }),
        enabled: Number.isFinite(dealId) && dealId > 0,
    });

    const uploadMut = useMutation({
        mutationFn: (file: File) => sourcingApi.uploadAttachment({ deal: dealId }, file),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['deal-attachments', dealId] }),
    });

    const removeMut = useMutation({
        mutationFn: (id: number) => sourcingApi.deleteAttachment(id),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['deal-attachments', dealId] }),
    });

    return (
        <FileUpload
            className={className}
            label={label ?? t('dealAttachments.title')}
            description={description ?? t('dealAttachments.description')}
            files={files.map(f => ({
                id: f.id,
                name: f.original_filename,
                url: f.file,
                uploaded_at: f.uploaded_at,
            }))}
            onUpload={async (file) => { await uploadMut.mutateAsync(file); }}
            onRemove={async (id) => { await removeMut.mutateAsync(Number(id)); }}
        />
    );
}
