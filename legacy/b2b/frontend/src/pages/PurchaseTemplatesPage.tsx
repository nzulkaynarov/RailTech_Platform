import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
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
import { Plus, FileText } from "lucide-react";

export function PurchaseTemplatesPage() {
  const { t } = useTranslation();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [templateDescription, setTemplateDescription] = useState("");

  const handleCreateTemplate = () => {
    // TODO: Wire to backend API when purchase-templates endpoint is ready
    setTemplateName("");
    setTemplateDescription("");
    setCreateDialogOpen(false);
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
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

      {/* Empty State */}
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-16 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
            <FileText className="h-8 w-8 text-muted-foreground" />
          </div>
          <h3 className="text-lg font-semibold">{t('purchaseTemplates.emptyTitle')}</h3>
          <p className="mt-2 max-w-md text-sm text-muted-foreground">{t('purchaseTemplates.emptyDescription')}</p>
        </CardContent>
      </Card>

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
