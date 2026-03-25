import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Plus,
  ShoppingCart,
  Clock,
  FileText,
  RotateCcw,
  Star,
} from "lucide-react";

interface Template {
  id: number;
  name: string;
  itemCount: number;
  lastOrderDate: string;
  totalAmount: string;
}

interface RecentOrder {
  id: string;
  date: string;
  itemCount: number;
  amount: string;
  status: string;
  statusVariant: "default" | "secondary" | "destructive" | "outline";
}

const templates: Template[] = [
  {
    id: 1,
    name: "Квартальная закупка ТЭД",
    itemCount: 5,
    lastOrderDate: "15.02.2026",
    totalAmount: "$142,500",
  },
  {
    id: 2,
    name: "Расходные материалы",
    itemCount: 8,
    lastOrderDate: "01.03.2026",
    totalAmount: "$23,800",
  },
  {
    id: 3,
    name: "Комплект подшипников",
    itemCount: 3,
    lastOrderDate: "20.01.2026",
    totalAmount: "$67,200",
  },
];

const recentOrders: RecentOrder[] = [
  {
    id: "ORD-2026-0147",
    date: "01.03.2026",
    itemCount: 8,
    amount: "$23,800",
    status: "Доставлен",
    statusVariant: "default",
  },
  {
    id: "ORD-2026-0132",
    date: "15.02.2026",
    itemCount: 5,
    amount: "$142,500",
    status: "В обработке",
    statusVariant: "secondary",
  },
  {
    id: "ORD-2026-0098",
    date: "20.01.2026",
    itemCount: 3,
    amount: "$67,200",
    status: "Доставлен",
    statusVariant: "default",
  },
];

export function PurchaseTemplatesPage() {
  const { t } = useTranslation();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [templateDescription, setTemplateDescription] = useState("");

  const handleCreateTemplate = () => {
    setTemplateName("");
    setTemplateDescription("");
    setCreateDialogOpen(false);
  };

  return (
    <div className="space-y-8 p-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            {t('purchaseTemplates.title')}
          </h1>
          <p className="text-muted-foreground mt-1">
            {t('purchaseTemplates.subtitle')}
          </p>
        </div>
        <Button onClick={() => setCreateDialogOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          {t('purchaseTemplates.createTemplate')}
        </Button>
      </div>

      {/* Template Cards */}
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {templates.map((template) => (
          <Card key={template.id} className="flex flex-col">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Star className="h-5 w-5 text-yellow-500 fill-yellow-500" />
                {template.name}
              </CardTitle>
              <CardDescription className="flex flex-col gap-1 pt-1">
                <span className="flex items-center gap-1.5">
                  <FileText className="h-3.5 w-3.5" />
                  {t('purchaseTemplates.itemCount', { count: template.itemCount })}
                </span>
                <span className="flex items-center gap-1.5">
                  <Clock className="h-3.5 w-3.5" />
                  {t('purchaseTemplates.lastOrder')}: {template.lastOrderDate}
                </span>
              </CardDescription>
            </CardHeader>
            <CardContent className="mt-auto space-y-4">
              <div className="text-2xl font-bold">{template.totalAmount}</div>
              <div className="flex gap-2">
                <Button className="flex-1">
                  <ShoppingCart className="mr-2 h-4 w-4" />
                  {t('purchaseTemplates.reorder')}
                </Button>
                <Button variant="outline">{t('purchaseTemplates.details')}</Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Separator />

      {/* Recent Orders Section */}
      <div className="space-y-4">
        <h2 className="text-2xl font-semibold tracking-tight">
          {t('purchaseTemplates.recentOrders')}
        </h2>
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('purchaseTemplates.table.number')}</TableHead>
                  <TableHead>{t('purchaseTemplates.table.date')}</TableHead>
                  <TableHead>{t('purchaseTemplates.table.itemCount')}</TableHead>
                  <TableHead>{t('purchaseTemplates.table.amount')}</TableHead>
                  <TableHead>{t('purchaseTemplates.table.status')}</TableHead>
                  <TableHead className="text-right">{t('purchaseTemplates.table.action')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentOrders.map((order) => (
                  <TableRow key={order.id}>
                    <TableCell className="font-medium">{order.id}</TableCell>
                    <TableCell>{order.date}</TableCell>
                    <TableCell>{order.itemCount}</TableCell>
                    <TableCell>{order.amount}</TableCell>
                    <TableCell>
                      <Badge variant={order.statusVariant}>
                        {order.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="outline" size="sm">
                        <RotateCcw className="mr-2 h-3.5 w-3.5" />
                        {t('purchaseTemplates.repeat')}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      {/* Create Template Dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('purchaseTemplates.createTemplate')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="template-name">{t('purchaseTemplates.dialog.name')}</Label>
              <Input
                id="template-name"
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                placeholder={t('purchaseTemplates.dialog.namePlaceholder')}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="template-description">{t('purchaseTemplates.dialog.description')}</Label>
              <Textarea
                id="template-description"
                value={templateDescription}
                onChange={(e) => setTemplateDescription(e.target.value)}
                placeholder={t('purchaseTemplates.dialog.descriptionPlaceholder')}
                rows={3}
                className="resize-none"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setCreateDialogOpen(false)}
            >
              {t('common.cancel')}
            </Button>
            <Button onClick={handleCreateTemplate} disabled={!templateName}>
              {t('purchaseTemplates.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
