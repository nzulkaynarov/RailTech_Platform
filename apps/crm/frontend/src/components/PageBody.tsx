import { Flex } from "antd";
import type { ReactNode } from "react";

/**
 * Вертикальная раскладка страницы с единым отступом между `PageHeader` и блоками
 * контента (16 px). `PageHeader` своего внешнего отступа не имеет.
 */
export function PageBody({ children }: { children: ReactNode }) {
  return (
    <Flex vertical gap="middle" className="page-body">
      {children}
    </Flex>
  );
}
