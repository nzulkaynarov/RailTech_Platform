import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import {
  HelpCircle, FileText, MessageSquare, Mail, ChevronDown, ShieldCheck, Calculator, Boxes, Truck, Wallet, Crown, Eye,
} from 'lucide-react';
import { PageShell } from './shared/PageShell';

export function HelpPage() {
  const { t } = useTranslation();

  const roles: Array<{
    icon: React.ReactNode;
    key: 'administrator' | 'calculation' | 'catalogSupply' | 'fulfillment' | 'finance' | 'head' | 'viewer';
  }> = [
    // Роли бэк-офиса M1-ERP-05 (BUSINESS §11) + администратор (суперпользователь из CRM).
    { icon: <Calculator className="h-4 w-4" />, key: 'calculation' },
    { icon: <Boxes className="h-4 w-4" />, key: 'catalogSupply' },
    { icon: <Truck className="h-4 w-4" />, key: 'fulfillment' },
    { icon: <Wallet className="h-4 w-4" />, key: 'finance' },
    { icon: <Crown className="h-4 w-4" />, key: 'head' },
    { icon: <Eye className="h-4 w-4" />, key: 'viewer' },
    { icon: <ShieldCheck className="h-4 w-4" />, key: 'administrator' },
  ];

  const categories = [
    {
      title: t('pages.help.sections.gettingStarted'),
      items: [
        { question: t('pages.help.faq.howAddEmployees'), answer: t('pages.help.faq.howAddEmployeesAnswer') },
        { question: t('pages.help.faq.howSwitchStatus'), answer: t('pages.help.faq.howSwitchStatusAnswer') },
      ],
    },
    {
      title: t('pages.help.sections.procurement'),
      items: [
        { question: t('pages.help.faq.howCreateRequest'), answer: t('pages.help.faq.howCreateRequestAnswer') },
        { question: t('pages.help.faq.excelFormats'), answer: t('pages.help.faq.excelFormatsAnswer') },
        { question: t('pages.help.faq.whatIsSmartMatch'), answer: t('pages.help.faq.whatIsSmartMatchAnswer') },
      ],
    },
    {
      title: t('pages.help.sections.quotesAndPricing'),
      items: [
        { question: t('pages.help.faq.howLandedCost'), answer: t('pages.help.faq.howLandedCostAnswer') },
        { question: t('pages.help.faq.canEditSentQuote'), answer: t('pages.help.faq.canEditSentQuoteAnswer') },
        { question: t('pages.help.faq.howRequestDiscount'), answer: t('pages.help.faq.howRequestDiscountAnswer') },
      ],
    },
    {
      title: t('pages.help.sections.securityAndAccess'),
      items: [
        { question: t('pages.help.faq.whatRoles'), answer: t('pages.help.faq.whatRolesAnswer') },
        { question: t('pages.help.faq.howResetPassword'), answer: t('pages.help.faq.howResetPasswordAnswer') },
      ],
    },
  ];

  return (
    <PageShell
      title={t('pages.help.title')}
      description={t('pages.help.description')}
      icon={<HelpCircle className="h-5 w-5" />}
    >
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Quick Actions */}
        <div className="lg:col-span-3 grid gap-4 grid-cols-1 sm:grid-cols-3">
          {[
            { icon: <FileText className="h-5 w-5" />, title: t('pages.help.quickActions.apiDocs'), desc: t('pages.help.quickActions.apiDocsDesc') },
            { icon: <MessageSquare className="h-5 w-5" />, title: t('pages.help.quickActions.telegramSupport'), desc: t('pages.help.quickActions.telegramSupportDesc') },
            { icon: <Mail className="h-5 w-5" />, title: t('pages.help.quickActions.emailSupport'), desc: t('pages.help.supportEmail') },
          ].map((action, i) => (
            <Card key={i} className="cursor-pointer hover:shadow-md transition-shadow">
              <CardContent className="p-4 flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg flex items-center justify-center flex-shrink-0 bg-primary/10 text-primary">
                  {action.icon}
                </div>
                <div>
                  <p className="text-sm font-medium">{action.title}</p>
                  <p className="text-xs text-muted-foreground">{action.desc}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Role Responsibilities (ADR-0002) */}
        <div className="lg:col-span-3">
          <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
            {t('pages.help.sections.roleResponsibilities')}
          </h3>
          <p className="text-xs text-muted-foreground mb-3">
            {t('pages.help.roleResponsibilities.intro')}
          </p>
          <div className="space-y-2">
            {roles.map((role) => (
              <Collapsible key={role.key}>
                <Card className="border">
                  <CardContent className="p-0">
                    <CollapsibleTrigger asChild>
                      <Button variant="ghost" className="w-full p-4 flex items-center justify-between hover:bg-muted/50 transition-colors h-auto">
                        <span className="flex items-center gap-2 font-medium text-sm text-left">
                          <span className="h-7 w-7 rounded-md flex items-center justify-center bg-primary/10 text-primary">
                            {role.icon}
                          </span>
                          {t(`pages.help.roleResponsibilities.${role.key}.title`)}
                        </span>
                        <ChevronDown className="h-4 w-4 transition-transform flex-shrink-0 ml-2" />
                      </Button>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <div className="border-t bg-muted/30 p-4 text-sm space-y-3">
                        <p className="text-muted-foreground">
                          {t(`pages.help.roleResponsibilities.${role.key}.summary`)}
                        </p>
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
                            {t('pages.help.roleResponsibilities.does')}
                          </p>
                          <ul className="list-disc pl-5 space-y-1 text-sm">
                            {(t(`pages.help.roleResponsibilities.${role.key}.does`, { returnObjects: true }) as string[]).map((item, i) => (
                              <li key={i}>{item}</li>
                            ))}
                          </ul>
                        </div>
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
                            {t('pages.help.roleResponsibilities.doesNot')}
                          </p>
                          <p className="text-sm text-muted-foreground">
                            {t(`pages.help.roleResponsibilities.${role.key}.doesNot`)}
                          </p>
                        </div>
                      </div>
                    </CollapsibleContent>
                  </CardContent>
                </Card>
              </Collapsible>
            ))}
          </div>
          <p className="text-xs text-muted-foreground mt-3">
            {t('pages.help.roleResponsibilities.escalation')}
          </p>
        </div>

        {/* FAQ Sections */}
        <div className="lg:col-span-3 space-y-6">
          {categories.map((cat, catIdx) => (
            <div key={catIdx}>
              <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">{cat.title}</h3>
              <div className="space-y-2">
                {cat.items.map((faq, idx) => (
                  <Collapsible key={idx}>
                    <Card className="border">
                      <CardContent className="p-0">
                        <CollapsibleTrigger asChild>
                          <Button variant="ghost" className="w-full p-4 flex items-center justify-between hover:bg-muted/50 transition-colors h-auto">
                            <span className="font-medium text-sm text-left">{faq.question}</span>
                            <ChevronDown className="h-4 w-4 transition-transform flex-shrink-0 ml-2" />
                          </Button>
                        </CollapsibleTrigger>
                        <CollapsibleContent>
                          <div className="border-t bg-muted/30 p-4 text-sm text-muted-foreground">
                            {faq.answer}
                          </div>
                        </CollapsibleContent>
                      </CardContent>
                    </Card>
                  </Collapsible>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Support Contact */}
        <Card className="lg:col-span-3 border-primary/20 bg-primary/5">
          <CardContent className="p-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 justify-between">
              <div>
                <h3 className="font-semibold text-base mb-1">{t('pages.help.needHelp')}</h3>
                <p className="text-sm text-muted-foreground">{t('pages.help.supportHours')}</p>
                <div className="flex items-center gap-4 mt-2 text-sm">
                  <a href={`mailto:${t('pages.help.supportEmail')}`} className="flex items-center gap-1.5 hover:text-primary transition-colors">
                    <Mail className="h-3.5 w-3.5" /> {t('pages.help.supportEmail')}
                  </a>
                  <a href={`tel:${t('pages.help.supportPhone').replace(/[^+\d]/g, '')}`} className="flex items-center gap-1.5 hover:text-primary transition-colors">
                    <MessageSquare className="h-3.5 w-3.5" /> {t('pages.help.supportPhone')}
                  </a>
                </div>
              </div>
              <Button asChild>
                <a href={`mailto:${t('pages.help.supportEmail')}`}>{t('pages.help.contactSupport')}</a>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}

export default HelpPage;
