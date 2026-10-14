"""Seller branding bundle + document theme — the context every document PDF renders on.

One place resolves the branding bundle (issuing company + its CompanyDocumentProfile +
logo URL) that every seller-issued document PDF (КП / договор / инвойс / акт) extends the
shared base template `crm/templates/crm/_document_base.html` with. Keeping the four builders
on an identical context shape is what makes the documents read as one product (ADR-0006
document-polish P1).
"""

from typing import Optional

from core.validators import is_hex_color

_DEFAULT_ACCENT = "#15294d"
_DARK_INK = "#1b1f27"
_LIGHT_INK = "#ffffff"

# Document theme (D2, Odoo Document Layout model). Font stacks are limited to families the
# backend container actually ships (Rule 1 — offering a font WeasyPrint would silently
# substitute would be a fake choice). Print typography wave (2026-07-27, owner: «кривые
# шрифты»): the container now ships Inter (fonts-inter) and PT Sans/PT Serif
# (fonts-paratype — ParaType, designed for Russian document typography); DejaVu is demoted
# to fallback only. Web surfaces fall through to Helvetica/Georgia when Inter/PT are absent.
_LAYOUT_PRESETS = {"light", "boxed", "bold", "striped"}
_FONT_STACKS = {
    "sans": "'Inter', 'PT Sans', 'DejaVu Sans', 'Helvetica', 'Arial', sans-serif",
    "serif": "'PT Serif', 'DejaVu Serif', 'Georgia', 'Times New Roman', serif",
}
_DEFAULT_SECONDARY = "#f6f8fb"  # the historical panel/zebra tint — zero-diff default

# Logos above this size are dropped from the PDF render rather than inlined (a data: URI of a
# multi-MB upload would bloat every render); the letterhead then falls back to the text name.
_LOGO_EMBED_MAX_BYTES = 1_000_000


def accent_contrast(accent_hex: Optional[str]) -> str:
    """Readable text color to place ON the accent fill (table head / ИТОГО row). WeasyPrint can't
    compute contrast, so we pick it here: dark ink on a light brand accent, white on a dark one.
    Uses the WCAG relative-luminance threshold; malformed/short hex falls back to white."""
    value = (accent_hex or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return _LIGHT_INK
    try:
        red, green, blue = (int(value[index : index + 2], 16) / 255 for index in (0, 2, 4))
    except ValueError:
        return _LIGHT_INK

    def _linear(channel):
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * _linear(red) + 0.7152 * _linear(green) + 0.0722 * _linear(blue)
    return _DARK_INK if luminance > 0.45 else _LIGHT_INK


def seller_logo_url(seller_profile) -> Optional[str]:
    """The seller's logo URL, or None when unset / the storage backend can't resolve it."""
    if not seller_profile or not seller_profile.logo:
        return None
    try:
        return seller_profile.logo.url
    except (ValueError, OSError):  # storage backend unavailable / missing key
        return None


def brand_context_for_pdf(brand: dict) -> dict:
    """Prepare a brand context for a WeasyPrint render: inline the seller logo as a data: URI.

    On prod (FileSystemStorage) ``seller_logo_url`` is a RELATIVE ``/media/…`` URL — WeasyPrint
    renders from ``HTML(string=…)`` with no ``base_url`` and deliberately no network fetching, so
    the logo came out as a broken-image box on every prod PDF. Browser surfaces (public pages,
    settings iframe, SPA) resolve the same URL fine, so the swap happens ONLY at PDF render time —
    never in the stored brand_snapshot or serializer slices (a data: URI there would bloat every
    row). Absolute http(s) URLs (e.g. dev MinIO, reachable in-network) are left as-is; missing or
    oversized files degrade to no logo (the template then prints the text name, not a broken box).
    """
    import base64
    import mimetypes

    from django.conf import settings

    logo_url = brand.get("seller_logo_url")
    if not logo_url or logo_url.startswith("data:"):
        return brand

    data = None
    name = ""
    # Live render context carries the real CompanyDocumentProfile — read its file straight from
    # storage (works for ANY backend/URL shape: prod relative /media, dev MinIO absolute URL that
    # the container can't reach back through, future CDN). Snapshot renders carry a
    # SimpleNamespace without the FieldFile — those fall to the MEDIA_URL-relative branch below.
    profile = brand.get("seller_profile")
    logo_field = getattr(profile, "logo", None)
    if logo_field is not None and hasattr(logo_field, "open"):
        try:
            with logo_field.open("rb") as file_handle:
                data = file_handle.read(_LOGO_EMBED_MAX_BYTES + 1)
            name = logo_field.name or ""
        except (OSError, ValueError, FileNotFoundError):
            data = None
    if data is None and logo_url.startswith(settings.MEDIA_URL):
        from django.core.files.storage import default_storage

        name = logo_url[len(settings.MEDIA_URL) :]
        try:
            with default_storage.open(name, "rb") as file_handle:
                data = file_handle.read(_LOGO_EMBED_MAX_BYTES + 1)
        except (OSError, ValueError, FileNotFoundError):
            data = None
    if data is None:
        # Unresolvable absolute URL (or dangling key): degrade to NO logo — the letterhead then
        # prints the text name, never a broken-image box (WeasyPrint deliberately fetches nothing).
        return {**brand, "seller_logo_url": None}
    if len(data) > _LOGO_EMBED_MAX_BYTES:
        return {**brand, "seller_logo_url": None}
    mime = mimetypes.guess_type(name)[0] or "image/png"
    encoded = base64.b64encode(data).decode("ascii")
    return {**brand, "seller_logo_url": f"data:{mime};base64,{encoded}"}


def document_brand_context(seller_company) -> dict:
    """The branding bundle every concrete document template feeds the base with. Resolves the
    seller's CompanyDocumentProfile + logo. Safe when `seller_company` is None (renders the
    neutral platform fallback — never fake counterparty data)."""
    from accounts.models import CompanyDocumentProfile

    # ONE read of the profile row (never creates).
    row = CompanyDocumentProfile.objects.filter(company=seller_company).first() if seller_company else None
    return _brand_context_from_row(seller_company, row)


def _apply_company_defaults(seller_company, row) -> None:
    """Overlay the live Company data onto an in-memory profile row (never .save()).

    Single source of truth (#287): with use_company_defaults ON the Company is authoritative
    — its values OVERRIDE the profile row so a stale name/ИНН in the profile can never shadow
    the live company data. Falls back to the profile value only where the Company field is
    blank (so we never wipe a manual entry with an empty company field).
    """
    row.legal_name = seller_company.name or row.legal_name
    row.inn = seller_company.inn or row.inn
    row.legal_address = seller_company.legal_address or row.legal_address
    if seller_company.logo:
        row.logo = seller_company.logo
    bank_parts = []
    if seller_company.bank_account:
        bank_parts.append(f"р/с: {seller_company.bank_account}")
    if seller_company.mfo:
        bank_parts.append(f"МФО: {seller_company.mfo}")
    if bank_parts:
        row.bank_details = ", ".join(bank_parts)
    # ПОДПИСАНТ СЮДА НЕ ПОДСТАВЛЯЕТСЯ.
    #
    # `Company.contact_person` — это «с кем связаться», а подписант — «кто подписывает»; в
    # юридическом документе роли разные. Раньше контактное лицо перекрывало `signatory_name`, и
    # в акте с квитанцией печаталось «Подписант: System Admin» — контакт демо-компании (проход
    # глазами 03-08). Эталон: у DocuSign и Adobe Sign подписант — отдельно назначаемая роль, у
    # Odoo «Ответственный» (`user_id`) не равен подписи компании.
    #
    # Правило #287 «Company authoritative» остаётся в силе для остальных полей — имя, ИНН,
    # адрес, банк действительно живут в карточке компании. Подпись живёт в профиле документов;
    # пусто там — документ печатает «Подпись / дата», а не чужое имя.


def _brand_context_from_row(seller_company, row) -> dict:
    """Build the brand context from an ALREADY-FETCHED profile row (may be mutated in-memory by
    the caller — the draft-preview path applies unsaved overrides before delegating here).

    Branding (legal name / logo / requisites) only renders when actually filled
    (_profile_has_branding) → the template falls back to the Company otherwise. The layout
    TOGGLES and the document THEME (layout preset / font / secondary tint) read from the raw
    row regardless, so a seller can restyle documents without also filling their legal name.
    """
    from ..quotes import _profile_has_branding

    if row and getattr(row, "use_company_defaults", False) and seller_company:
        _apply_company_defaults(seller_company, row)

    branded = row if _profile_has_branding(row) else None
    # SEC (audit #9): accent goes raw into a <style> block, so neutralize anything that
    # isn't a #hex colour at render time too — defence-in-depth for any historical row
    # written before update_document_profile validated it (belt-and-suspenders vs CSS
    # injection → WeasyPrint SSRF).
    raw_accent = getattr(branded, "accent_color", None) if branded else None
    accent = raw_accent if is_hex_color(raw_accent) else _DEFAULT_ACCENT
    # Theme reads from the RAW row (like the toggles) and is allowlist-validated at render
    # time too — defence-in-depth: layout lands in a class attr, secondary in a <style> block.
    raw_layout = getattr(row, "layout_preset", None) if row else None
    layout_preset = raw_layout if raw_layout in _LAYOUT_PRESETS else "light"
    raw_font = getattr(row, "font_family", None) if row else None
    font_stack = _FONT_STACKS.get(raw_font, _FONT_STACKS["sans"])
    raw_secondary = getattr(row, "secondary_color", None) if row else None
    secondary = raw_secondary if is_hex_color(raw_secondary) else _DEFAULT_SECONDARY
    return {
        "seller": seller_company,
        "seller_profile": branded,
        "seller_logo_url": seller_logo_url(branded),
        "show_logo": row.show_logo if row else True,
        "show_lead_time": row.show_lead_time if row else True,
        "show_fx_note": row.show_fx_note if row else False,
        # Full-theming inputs for _document_base.html (F-03): every accent surface reads --accent,
        # and text on the accent fill reads --accent-contrast so a light brand accent stays legible.
        "accent": accent,
        "accent_contrast": accent_contrast(accent),
        # D2 document theme — one theme drives all the company's PDFs.
        "layout_preset": layout_preset,
        "font_stack": font_stack,
        "secondary": secondary,
    }
