import { Drawer, List, Space, Typography } from "antd";

import { useKbChunks } from "../../api/adminQueries";
import type { KbDocumentOut } from "../../api/generated/model";
import { PageState } from "../../components/PageState";
import { t } from "../../i18n/ru";

/** Фрагменты документа, как их видит поиск бота. */
export function KbChunksDrawer({
  doc,
  onClose,
}: {
  doc: KbDocumentOut | null;
  onClose: () => void;
}) {
  const chunks = useKbChunks(doc?.id ?? null);
  return (
    <Drawer open={doc !== null} title={doc?.title} width="min(640px, 100vw)" onClose={onClose}>
      {doc ? (
        <PageState query={chunks} variant="section">
          <List
            dataSource={chunks.data ?? []}
            renderItem={(c) => (
              <List.Item>
                <Space direction="vertical" size={0}>
                  <Typography.Text type="secondary">
                    #{c.position} · {c.heading_path ?? ""} · {c.token_count} {t.kb.tokens}
                  </Typography.Text>
                  <Typography.Paragraph className="settings-preview">
                    {c.content}
                  </Typography.Paragraph>
                </Space>
              </List.Item>
            )}
          />
        </PageState>
      ) : null}
    </Drawer>
  );
}
