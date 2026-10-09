import { Card, Descriptions, Tag, Typography } from "antd";

import { useMe } from "../../api/queries";
import { ModeSwitch } from "../../components/ModeSwitch";
import { t } from "../../i18n/ru";
import { roleLabel } from "../../domain/labels";

export function ProfilePage() {
  const { data } = useMe();
  if (!data) return <Card loading />;
  return (
    <Card title={t.profile.title}>
      <Descriptions column={1}>
        <Descriptions.Item label={t.users.fullName}>{data.full_name}</Descriptions.Item>
        <Descriptions.Item label={t.users.email}>{data.email}</Descriptions.Item>
        <Descriptions.Item label={t.users.roles}>
          {data.roles.map((r) => (
            <Tag key={r}>{roleLabel(r)}</Tag>
          ))}
        </Descriptions.Item>
        <Descriptions.Item label={t.users.telegram}>
          {data.tg_user_id ?? t.common.none}
        </Descriptions.Item>
      </Descriptions>
      <ModeSwitch />
      <Typography.Paragraph type="secondary">{t.profile.telegramHint}</Typography.Paragraph>
    </Card>
  );
}
