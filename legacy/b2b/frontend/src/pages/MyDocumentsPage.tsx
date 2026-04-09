import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { FileText, Download } from 'lucide-react';
import { PageShell } from './shared/PageShell';

export function MyDocumentsPage() {
  const { t } = useTranslation();
  // Documents are loaded from the backend API
  // TODO: Replace with useEffect + API call when documents endpoint is ready
  const documents: { type: string; number: string; date: string; counterparty: string; status: string; statusLabel: string; amount: string }[] = [];

  return (
    <PageShell
      title={t('pages.documents.title')}
      description={t('pages.documents.description')}
      icon={<FileText className="h-5 w-5" />}
      actions={[{ label: t('pages.documents.uploadDocument') }]}
    >
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('pages.documents.table.type')}</TableHead>
                <TableHead>{t('pages.documents.table.number')}</TableHead>
                <TableHead>{t('pages.documents.table.date')}</TableHead>
                <TableHead>{t('pages.documents.table.counterparty')}</TableHead>
                <TableHead>{t('pages.documents.table.status')}</TableHead>
                <TableHead className="text-right">{t('pages.documents.table.amount')}</TableHead>
                <TableHead className="text-center">{t('pages.documents.table.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {documents.map((doc, idx) => (
                <TableRow key={idx}>
                  <TableCell className="font-medium">{doc.type}</TableCell>
                  <TableCell>{doc.number}</TableCell>
                  <TableCell>{doc.date}</TableCell>
                  <TableCell>{doc.counterparty}</TableCell>
                  <TableCell>
                    <Badge variant={
                      doc.status === 'signed' ? 'default' :
                      doc.status === 'pending' ? 'secondary' :
                      doc.status === 'forSignature' ? 'outline' :
                      'secondary'
                    }>
                      {doc.statusLabel}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums font-medium">{doc.amount}</TableCell>
                  <TableCell className="text-center">
                    <Button variant="ghost" size="sm" className="h-8 w-8">
                      <Download className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </PageShell>
  );
}

export default MyDocumentsPage;
