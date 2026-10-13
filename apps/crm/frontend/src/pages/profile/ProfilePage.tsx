import { LockOutlined } from "@ant-design/icons";
import { Button, Card, Descriptions, Flex, Tag, Typography } from "antd";
import { useNavigate } from "react-router";

import type { UserOut } from "../../api/generated/model";
import { useMe, usePermissionsQuery } from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { roleLabel } from "../../domain/labels";
import { t } from "../../i18n/ru";
import { NotifyCard } from "./NotifyCard";

/** Профиль: свои данные, смена пароля и уведомления. Режим «Админ/Менеджер» — только в шапке. */
export function ProfilePage() {
  const me = useMe();
  const perms = usePermissionsQuery();
  const navigate = useNavigate();
  // Подсказка про Telegram — только тем, кто забирает лидов кнопкой в канале (отчёт 2).
  const canTake = allowed(perms.data, "leads", "take");
  return (
    <PageBody>
      <PageHeader
        title={t.page.profile}
        extra={
          <Button
            icon={<LockOutlined aria-hidden />}
            onClick={() => {
              void navigate("/change-password");
            }}
          >
            {t.profile.changePassword}
          </Button>
        }
      />
      <PageState query={me}>
        {me.data ? (
          <Flex vertical gap="middle">
            <ProfileCard user={me.data} telegramHint={canTake} />
            <NotifyCard user={me.data} />
          </Flex>
        ) : null}
      </PageState>
    </PageBody>
  );
}

function ProfileCard({ user, telegramHint }: { user: UserOut; telegramHint: boolean }) {
  return (
    <Card>
      <Descriptions column={1}>
        <Descriptions.Item label={t.users.fullName}>{user.full_name}</Descriptions.Item>
        <Descriptions.Item label={t.users.email}>{user.email}</Descriptions.Item>
        <Descriptions.Item label={t.users.roles}>
          {user.roles.map((r) => (
            <Tag key={r}>{roleLabel(r)}</Tag>
          ))}
        </Descriptions.Item>
        <Descriptions.Item label={t.users.telegram}>
          {user.tg_user_id ?? t.common.none}
        </Descriptions.Item>
      </Descriptions>
      {telegramHint ? (
        <Typography.Paragraph type="secondary">{t.profile.telegramHint}</Typography.Paragraph>
      ) : null}
    </Card>
  );
}
