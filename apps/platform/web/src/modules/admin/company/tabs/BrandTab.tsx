import { useQueryClient } from "@tanstack/react-query";
import { App, Checkbox, Collapse, Form, Input, Segmented, Select } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  BrandProfile,
  BrandProfileUpdate,
  DocumentKind,
} from "../../../../shared/api/generated/model";
import {
  getGetBrandProfileQueryKey,
  useGetBrandProfile,
  usePreviewBrandDocument,
  useUpdateBrandProfile,
  useUploadBrandLogo,
} from "../../../../shared/api/generated/platform-bff";
import { DefinitionList } from "../../../../shared/ui/DefinitionList";
import { LogoField, PreviewFrame, QueryGate, ReadOnlyFence, SaveBlock, TabHeader } from "../common";
import { changedFields, isEmptyObject, omit } from "../diff";
import { errorFields } from "../errors";

type Values = Omit<BrandProfile, "logo_url" | "inherited">;

const KINDS: DocumentKind[] = ["quote", "contract", "invoice", "act", "letter"];
const FLAGS = [
  "use_company_defaults",
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

const toValues = (brand: BrandProfile): Values => omit(brand, ["logo_url", "inherited"]);

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
  const [kind, setKind] = useState<DocumentKind>("quote");

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

  // Образец: БЕЗ сохранения — несохранённые правки уходят в `draft`; один запрос после паузы ввода.
  const preview = usePreviewBrandDocument();
  const { mutate: requestPreview } = preview;
  const draftKey = JSON.stringify(changed);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const draft = JSON.parse(draftKey) as BrandProfileUpdate;
      requestPreview({ data: { kind, ...(isEmptyObject(draft) ? {} : { draft }) } });
    }, 350);
    return () => {
      window.clearTimeout(timer);
    };
  }, [kind, draftKey, requestPreview]);

  const inherits = Form.useWatch("use_company_defaults", form);

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

  const colors = [
    ["accent_color", t("brand.accent")],
    ["secondary_color", t("brand.secondary")],
  ] as const;

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
          <div className="pf-co-grid">
            <Form.Item name="legal_name" label={t("brand.legalName")} className="pf-co-wide">
              <Input maxLength={255} disabled={inherits} />
            </Form.Item>
            <Form.Item name="inn" label={t("brand.inn")}>
              <Input maxLength={20} disabled={inherits} />
            </Form.Item>
            <Form.Item name="legal_address" label={t("brand.legalAddress")} className="pf-co-wide">
              <Input.TextArea rows={2} disabled={inherits} />
            </Form.Item>
            <Form.Item name="bank_details" label={t("brand.bankDetails")} className="pf-co-wide">
              <Input.TextArea rows={2} disabled={inherits} />
            </Form.Item>
            <Form.Item name="signatory_name" label={t("brand.signatoryName")}>
              <Input maxLength={255} />
            </Form.Item>
            <Form.Item name="signatory_position" label={t("brand.signatoryPosition")}>
              <Input maxLength={255} />
            </Form.Item>
            <Form.Item name="footer_text" label={t("brand.footer")} className="pf-co-wide">
              <Input.TextArea rows={2} />
            </Form.Item>
            {colors.map(([name, label]) => (
              <Form.Item
                key={name}
                name={name}
                label={label}
                rules={[{ pattern: HEX, message: t("brand.colorInvalid") }]}
              >
                <ColorField label={label} />
              </Form.Item>
            ))}
            <Form.Item name="layout_preset" label={t("brand.layout")}>
              <Select
                options={(["light", "boxed", "bold", "striped"] as const).map((value) => ({
                  value,
                  label: t(`brand.layouts.${value}`),
                }))}
              />
            </Form.Item>
            <Form.Item name="font_family" label={t("brand.font")}>
              <Select
                options={(["sans", "serif"] as const).map((value) => ({
                  value,
                  label: t(`brand.fonts.${value}`),
                }))}
              />
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
          {inherits && brand.inherited ? (
            <div className="pf-co-inherited">
              <p className="pf-co-hint">{t("brand.inheritedTitle")}</p>
              <DefinitionList
                items={Object.entries(brand.inherited).map(([key, value]) => ({
                  label: t(`brand.inheritedKeys.${key}`, { defaultValue: key }),
                  value,
                }))}
              />
            </div>
          ) : null}
          <Collapse
            ghost
            items={[
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
            consequence={[t("brand.consequence.documents"), t("brand.consequence.preview")]}
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
        <PreviewFrame
          html={preview.data?.html}
          title={t("brand.previewFrame", { kind: t(`kinds.${kind}`) })}
          loading={preview.isPending}
        />
        <p className="pf-co-hint">{t("brand.previewHint")}</p>
      </div>
    </div>
  );
}
