import { useState, useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { HelpCircle, Search, MessageSquare, ChevronDown, ChevronRight, BookOpen } from 'lucide-react';

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
  SheetFooter,
} from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  HELP_ARTICLES,
  getArticlesForRoute,
  searchHelpArticles,
  type HelpArticle,
} from '@/lib/helpArticles';

export function HelpDrawer() {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();

  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const lang = (i18n.language.startsWith('uz') ? 'uz' : i18n.language.startsWith('en') ? 'en' : 'ru') as
    | 'ru'
    | 'uz'
    | 'en';

  const routeArticles = useMemo(() => getArticlesForRoute(location.pathname), [location.pathname]);

  const displayedArticles = useMemo(() => {
    if (search.trim()) {
      return searchHelpArticles(search, lang);
    }
    // Если поисковая строка пуста, сначала показываем подходящие к текущему роуту, затем остальные
    const routeIds = new Set(routeArticles.map((a) => a.id));
    const others = HELP_ARTICLES.filter((a) => !routeIds.has(a.id));
    return [...routeArticles, ...others];
  }, [search, lang, routeArticles]);

  const handleOpenChange = (isOpen: boolean) => {
    setOpen(isOpen);
    if (!isOpen) {
      setSearch('');
      setExpandedId(null);
    } else if (routeArticles.length > 0) {
      setExpandedId(routeArticles[0].id);
    }
  };

  const handleContactManager = () => {
    setOpen(false);
    navigate('/messages');
  };

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-9 rounded-xl text-muted-foreground hover:bg-accent hover:text-primary focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={t('help.trigger', 'Справка и подсказки')}
          title={t('help.trigger', 'Справка и подсказки')}
        >
          <HelpCircle className="size-5" aria-hidden="true" />
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="flex flex-col w-full sm:max-w-md p-0">
        <SheetHeader className="p-4 border-b border-border/60">
          <SheetTitle className="flex items-center gap-2 text-base font-semibold">
            <BookOpen className="size-5 text-primary" aria-hidden="true" />
            {t('help.drawerTitle', 'База знаний кабинета')}
          </SheetTitle>
          <div className="relative mt-2">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden="true" />
            <Input
              type="search"
              placeholder={t('help.searchPlaceholder', 'Поиск по статьям и инструкциям…')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 text-sm"
            />
          </div>
        </SheetHeader>

        <ScrollArea className="flex-1 px-4 py-3">
          <div className="space-y-3 pb-6">
            {!search && routeArticles.length > 0 && (
              <div className="text-xs font-medium text-primary uppercase tracking-wider px-1">
                {t('help.relevantSection', 'Подсказки для этого раздела')}
              </div>
            )}

            {displayedArticles.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                {t('help.noResults', 'Ничего не найдено по вашему запросу.')}
              </div>
            ) : (
              displayedArticles.map((article: HelpArticle) => {
                const isExpanded = expandedId === article.id;
                const isContextMatch = !search && routeArticles.some((ra) => ra.id === article.id);

                return (
                  <div
                    key={article.id}
                    className={`rounded-xl border transition-all ${
                      isContextMatch
                        ? 'border-primary/30 bg-primary/[0.02]'
                        : 'border-border/60 bg-card'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => setExpandedId(isExpanded ? null : article.id)}
                      className="w-full text-left p-3.5 flex items-start justify-between gap-3 outline-none focus-visible:ring-2 focus-visible:ring-primary rounded-xl"
                      aria-expanded={isExpanded}
                    >
                      <div className="space-y-1 pr-1">
                        <div className="text-sm font-semibold text-foreground leading-snug">
                          {article.title[lang]}
                        </div>
                        {!isExpanded && (
                          <div className="text-xs text-muted-foreground line-clamp-2">
                            {article.summary[lang]}
                          </div>
                        )}
                      </div>
                      <div className="text-muted-foreground mt-0.5 shrink-0">
                        {isExpanded ? (
                          <ChevronDown className="size-4" aria-hidden="true" />
                        ) : (
                          <ChevronRight className="size-4" aria-hidden="true" />
                        )}
                      </div>
                    </button>

                    {isExpanded && (
                      <div className="px-3.5 pb-4 pt-1 border-t border-border/40 text-xs text-muted-foreground space-y-2">
                        {article.content[lang].map((para, idx) => (
                          <p key={idx} className="leading-relaxed flex items-start gap-2">
                            <span className="text-primary font-bold shrink-0 mt-0.5">•</span>
                            <span>{para}</span>
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </ScrollArea>

        <SheetFooter className="p-4 border-t border-border/60 bg-muted/30">
          <div className="w-full space-y-2">
            <div className="text-xs text-muted-foreground text-center">
              {t('help.footerHint', 'Не нашли ответ на вопрос?')}
            </div>
            <Button
              variant="outline"
              onClick={handleContactManager}
              className="w-full gap-2 text-sm"
            >
              <MessageSquare className="size-4 text-primary" aria-hidden="true" />
              {t('help.contactManager', 'Написать персональному менеджеру')}
            </Button>
          </div>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

