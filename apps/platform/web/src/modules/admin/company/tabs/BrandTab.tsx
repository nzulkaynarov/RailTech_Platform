import { useQueryClient } from "@tanstack/react-query";
import { App, Checkbox, Collapse, Form, Input, Segmented } from "antd";
import { useMemo } from "react";
import { useSearchParams } from "react-router";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { BrandProfile, DocumentKind } from "../../../../shared/api/generated/model";
import {
  getGetBrandProfileQueryKey,
  useGetBrandProfile,
  useUpdateBrandProfile,
  useUploadBrandLogo,
} from "../../../../shared/api/generated/platform-bff";
import { DefinitionList } from "../../../../shared/ui/DefinitionList";
import { LogoField, QueryGate, ReadOnlyFence, SaveBlock, TabHeader } from "../common";
import { changedFields, isEmptyObject, omit } from "../diff";
import { SamplePdf } from "../SamplePdf";
import { errorFields } from "../errors";

/** ДОК-13: «Оформление», «Шрифт» и «Второй цвет» не показываются и не уходят — в договоре они устарели. */
const DEPRECATED = ["secondary_color", "layout_preset", "font_family"] as const;

type Values = Omit<BrandProfile, "logo_url" | "inherited" | (typeof DEPRECATED)[number]>;

const KINDS: DocumentKind[] = ["quote", "contract", "invoice", "act", "letter"];
const FLAGS = [
  "show_logo",
  "show_bank_in_header",
  "show_cover_letter",
  "show_lead_time",
  "show_fx_note",
] as const;
const WORDINGS = [
  "cover_letter_text",
  "contract_acceptance_text",
  "contract_liability_text",
  "contract_extra_terms_text",
  "act_closing_text",
] as const;
const HEX = /^#[0-9a-fA-F]{6}$/;
/** TPL-3 (план 2.7): поля бланка, у которых есть варианты на узбекском и английском */
const VARIANT_LANGS = ["uz", "en"] as const;
const VARIANT_FIELDS = [
  ["legal_name", 255],
  ["legal_address", 2000],
  ["signatory_position", 255],
  ["footer_text", 2000],
] as const;

const toValues = (brand: BrandProfile): Values =>
  omit(brand, ["logo_url", "inherited", ...DEPRECATED]);

/** Цвет бренда: выбор цвета и запись `#RRGGBB` рядом; `id` от `Form.Item` получает текстовое поле (связь с подписью). */
function ColorField({
  value,
  onChange,
  id,
  label,
}: {
  value?: string;
  onChange?: (next: string) => void;
  id?: string;
  label: string;
}) {
  const { t } = useTranslation("company");
  return (
    <div className="pf-co-swatch">
      <input
        type="color"
        aria-label={t("brand.pickColor", { label })}
        value={value && HEX.test(value) ? value : "#000000"}
        onChange={(event) => onChange?.(event.target.value)}
      />
      <Input
        id={id}
        value={value}
        maxLength={7}
        className="pf-co-mono"
        onChange={(event) => onChange?.(event.target.value)}
      />
    </div>
  );
}

/** Бланк и бренд документов компании (ERP `document-profile`): реквизиты на КП, договоре, счёте и акте; образец рядом. */
export function BrandTab() {
  const { t } = useTranslation("company");
  const query = useGetBrandProfile();
  return (
    <div className="pf-co-body">
      <TabHeader title={t("brand.title")} hint={t("brand.hint")} />
      <QueryGate query={query}>
        {(brand) => <BrandForm key={JSON.stringify(toValues(brand))} brand={brand} />}
      </QueryGate>
    </div>
  );
}

function BrandForm({ brand }: { brand: BrandProfile }) {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<Values>();
  const initial = useMemo(() => toValues(brand), [brand]);
  const watched = Form.useWatch([], form);
  const changed = changedFields(initial, watched);
  // Какой образец открыт — в адресе (`?sample=`): после F5 и по ссылке «на весь экран» тот же документ.
  const [params, setParams] = useSearchParams();
  const asked = params.get("sample");
  const kind: DocumentKind = KINDS.find((value) => value === asked) ?? "quote";
  const setKind = (next: DocumentKind) => {
    setParams(
      (previous) => {
        const copy = new URLSearchParams(previous);
        copy.set("sample", next);
        return copy;
      },
      { replace: true },
    );
  };

  const keep = (next: BrandProfile) => {
    queryClient.setQueryData(getGetBrandProfileQueryKey(), next);
  };
  const update = useUpdateBrandProfile({
    mutation: {
      onSuccess: (next) => {
        keep(next);
        void message.success(t("saved"));
      },
    },
  });
  const upload = useUploadBrandLogo({
    mutation: {
      onSuccess: (next) => {
        keep(next);
        void message.success(t("logo.uploaded"));
      },
    },
  });

  const submit = () => {
    update.mutate(
      { data: changed },
      {
        onError: (error) => {
          form.setFields(
            errorFields(error)
              .filter((name) => name in initial)
              .map((name) => ({ name: name as keyof Values, errors: [t("brand.invalidField")] })),
          );
        },
      },
    );
  };

  return (
    <div className="pf-co-split">
      <ReadOnlyFence block>
        <LogoField
          url={brand.logo_url}
          label={t("brand.logo")}
          uploading={upload.isPending}
          error={upload.error}
          onUpload={(file) => {
            upload.mutate({ data: { logo: file } });
          }}
        />
        <Form<Values> form={form} layout="vertical" initialValues={initial} onFinish={submit}>
          {brand.inherited ? (
            <div className="pf-co-inherited">
              <p className="pf-co-hint">{t("brand.inheritedTitle")}</p>
              <DefinitionList
                items={Object.entries(brand.inherited).map(([key, value]) => ({
                  label: t(`brand.inheritedKeys.${key}`, { defaultValue: key }),
                  value: value || "—",
                }))}
              />
              <Link to="/admin/company?part=details">{t("brand.inheritedEdit")}</Link>
            </div>
          ) : null}
          <div className="pf-co-grid">
            <Form.Item name="signatory_name" label={t("brand.signatoryName")}>
              <Input maxLength={255} />
            </Form.Item>
            <Form.Item name="signatory_position" label={t("brand.signatoryPosition")}>
              <Input maxLength={255} />
            </Form.Item>
            <Form.Item name="footer_text" label={t("brand.footer")} className="pf-co-wide">
              <Input.TextArea rows={2} />
            </Form.Item>
            <Form.Item
              name="accent_color"
              label={t("brand.accent")}
              rules={[{ pattern: HEX, message: t("brand.colorInvalid") }]}
            >
              <ColorField label={t("brand.accent")} />
            </Form.Item>
          </div>
          <fieldset className="pf-co-fieldset">
            <legend className="pf-co-legend">{t("brand.printLegend")}</legend>
            {FLAGS.map((name) => (
              <Form.Item
                key={name}
                name={name}
                valuePropName="checked"
                style={{ margin: "0 0 4px" }}
              >
                <Checkbox>{t(`brand.flags.${name}`)}</Checkbox>
              </Form.Item>
            ))}
          </fieldset>
          <Collapse
            ghost
            items={[
              {
                key: "languages",
                label: t("brand.languages.title"),
                forceRender: true,
                children: (
                  <>
                    <p className="pf-co-hint">{t("brand.languages.hint")}</p>
                    {VARIANT_LANGS.map((lang) => (
                      <fieldset key={lang} className="pf-co-fieldset">
                        <legend className="pf-co-legend">{t(`brand.languages.${lang}`)}</legend>
                        {VARIANT_FIELDS.map(([field, max]) => (
                          <Form.Item
                            key={field}
                            name={["translations", lang, field]}
                            label={t(`brand.languages.fields.${field}`)}
                          >
                            {max > 255 ? (
                              <Input.TextArea rows={2} maxLength={max} />
                            ) : (
                              <Input maxLength={max} />
                            )}
                          </Form.Item>
                        ))}
                      </fieldset>
                    ))}
                  </>
                ),
              },
              {
                key: "wording",
                label: t("brand.wordingTitle"),
                children: WORDINGS.map((name) => (
                  <Form.Item key={name} name={name} label={t(`brand.wording.${name}`)}>
                    <Input.TextArea rows={3} />
                  </Form.Item>
                )),
                forceRender: true,
              },
            ]}
          />
          <SaveBlock
            label={t("brand.save")}
            loading={update.isPending}
            disabled={isEmptyObject(changed)}
            error={update.error}
            onDiscard={() => {
              form.resetFields();
              update.reset();
            }}
          />
        </Form>
      </ReadOnlyFence>
      <div className="pf-co-panel">
        <div className="pf-co-toolbar">
          <h3 className="pf-co-title">{t("brand.previewTitle")}</h3>
          <Segmented<DocumentKind>
            aria-label={t("brand.previewKind")}
            value={kind}
            onChange={setKind}
            options={KINDS.map((value) => ({ value, label: t(`kinds.${value}`) }))}
          />
        </div>
        <SamplePdf
          request={{ kind, ...(isEmptyObject(changed) ? {} : { draft: changed }) }}
          title={t("brand.previewFrame", { label: t(`kinds.${kind}`) })}
        />
        <p className="pf-co-hint">{t("brand.previewHint")}</p>
      </div>
    </div>
  );
}
