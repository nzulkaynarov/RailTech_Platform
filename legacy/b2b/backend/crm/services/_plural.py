"""Russian noun pluralization for audit / ActivityLog detail strings.

Audit-log `detail` text is operator-facing Russian free text (NOT the user-facing UI —
that goes through i18n `t()` per Rule 5). A raw f"{n} позиций" / f"{n} продавцов" reads
ungrammatically for small counts («1 позиций», «1 продавцов»). This tiny helper picks the
correct case form by the standard Slavic plural rule so the trail reads naturally.

Deliberately NOT an i18n framework (Django would drag gettext/locale machinery into a plain
log line): three explicit forms in, the agreeing one out.
"""


def pluralize_ru(count: int, one: str, few: str, many: str) -> str:
    """Return the Russian noun form agreeing with ``count``.

    Standard Slavic plural rule (units = n % 10, tens = n % 100):
      * ``one``  — count ends in 1 but not 11        → «1 позиция», «1 продавцу», «21 позиция»
      * ``few``  — count ends in 2-4 but not 12-14   → «2 позиции», «3 продавцам», «22 позиции»
      * ``many`` — everything else (0, 5-20, …)      → «5 позиций», «11 позиций», «20 продавцам»

    Only the noun form is returned; callers prepend the number themselves. ``count`` is taken
    by absolute value so a negative never slips through the modulo branches.
    """
    absolute = abs(int(count))
    tens = absolute % 100
    units = absolute % 10
    if 11 <= tens <= 14:
        return many
    if units == 1:
        return one
    if 2 <= units <= 4:
        return few
    return many
