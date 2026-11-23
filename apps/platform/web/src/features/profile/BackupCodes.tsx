import { App, Button, Alert, Space } from "antd";
import { useTranslation } from "react-i18next";

/**
 * Резервные коды второго фактора: показываются один раз сразу после включения (профиль и обязательная настройка
 * при входе). «Я сохранил коды» закрывает показ.
 */
export function BackupCodes({ codes, onSaved }: { codes: string[]; onSaved: () => void }) {
  const { t } = useTranslation("profile");
  const { message } = App.useApp();

  const download = () => {
    const url = URL.createObjectURL(new Blob([`${codes.join("\n")}\n`], { type: "text/plain" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "backup-codes.txt";
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      <Alert type="success" showIcon message={t("secondFactor.backupTitle")} />
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("secondFactor.backupHint")}
      </p>
      <ul
        aria-label={t("secondFactor.backupTitle")}
        className="pf-num"
        style={{
          margin: 0,
          padding: 12,
          listStyle: "none",
          display: "grid",
          gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          gap: "4px 16px",
          background: "var(--rt-color-surface-subtle, #f5f5f5)",
          borderRadius: 6,
        }}
      >
        {codes.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <Space wrap>
        <Button onClick={download}>{t("secondFactor.download")}</Button>
        <Button
          onClick={() => {
            void navigator.clipboard.writeText(codes.join("\n"));
            void message.success(t("secondFactor.copied"));
          }}
        >
          {t("secondFactor.copy")}
        </Button>
        <Button type="primary" onClick={onSaved}>
          {t("secondFactor.saved")}
        </Button>
      </Space>
    </Space>
  );
}
