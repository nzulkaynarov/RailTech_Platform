import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { LifeBuoy } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
    DialogFooter, DialogTrigger,
} from '@/components/ui/dialog';
import {
    Tooltip, TooltipContent, TooltipTrigger,
} from '@/components/ui/tooltip';

import { useCreateSupportTicket } from '@/hooks/useSupport';
import type { SupportTicketCategory, SupportTicketPriority } from '@/api/supportApi';

const CATEGORIES: SupportTicketCategory[] = [
    'QUESTION', 'BUG', 'BILLING', 'FEATURE', 'OTHER',
];
const PRIORITIES: SupportTicketPriority[] = ['LOW', 'NORMAL', 'HIGH', 'URGENT'];

export function SupportButton() {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const [subject, setSubject] = useState('');
    const [description, setDescription] = useState('');
    const [category, setCategory] = useState<SupportTicketCategory>('QUESTION');
    const [priority, setPriority] = useState<SupportTicketPriority>('NORMAL');
    const createTicket = useCreateSupportTicket();

    const reset = () => {
        setSubject('');
        setDescription('');
        setCategory('QUESTION');
        setPriority('NORMAL');
    };

    const handleSubmit = async () => {
        if (!subject.trim() || !description.trim()) return;
        try {
            await createTicket.mutateAsync({
                subject: subject.trim(),
                description: description.trim(),
                category,
                priority,
            });
            toast.success(t('admin.support.userForm.success'));
            setOpen(false);
            reset();
        } catch {
            toast.error(t('common.error'));
        }
    };

    return (
        <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) reset(); }}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <DialogTrigger asChild>
                        <Button variant="ghost" size="icon" aria-label={t('admin.support.userForm.fab')}>
                            <LifeBuoy className="h-5 w-5" />
                        </Button>
                    </DialogTrigger>
                </TooltipTrigger>
                <TooltipContent>{t('admin.support.userForm.fab')}</TooltipContent>
            </Tooltip>
            <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                    <DialogTitle>{t('admin.support.userForm.title')}</DialogTitle>
                    <DialogDescription>{t('admin.support.userForm.subtitle')}</DialogDescription>
                </DialogHeader>
                <div className="space-y-4">
                    <div className="space-y-2">
                        <Label>{t('admin.support.userForm.subject')}</Label>
                        <Input
                            value={subject}
                            onChange={(e) => setSubject(e.target.value)}
                            placeholder={t('admin.support.userForm.subjectPlaceholder')}
                            maxLength={255}
                        />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-2">
                            <Label>{t('admin.support.userForm.category')}</Label>
                            <Select value={category} onValueChange={(v) => setCategory(v as SupportTicketCategory)}>
                                <SelectTrigger><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    {CATEGORIES.map((c) => (
                                        <SelectItem key={c} value={c}>
                                            {t(`admin.support.category.${c}`)}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-2">
                            <Label>{t('admin.support.userForm.priority')}</Label>
                            <Select value={priority} onValueChange={(v) => setPriority(v as SupportTicketPriority)}>
                                <SelectTrigger><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    {PRIORITIES.map((p) => (
                                        <SelectItem key={p} value={p}>
                                            {t(`admin.support.priority.${p}`)}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    </div>
                    <div className="space-y-2">
                        <Label>{t('admin.support.userForm.description')}</Label>
                        <Textarea
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            placeholder={t('admin.support.userForm.descriptionPlaceholder')}
                            rows={5}
                        />
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => setOpen(false)}>
                        {t('admin.support.userForm.cancel')}
                    </Button>
                    <Button
                        onClick={handleSubmit}
                        disabled={!subject.trim() || !description.trim() || createTicket.isPending}
                    >
                        {t('admin.support.userForm.submit')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

export default SupportButton;
