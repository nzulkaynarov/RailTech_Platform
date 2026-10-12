import { UploadOutlined } from "@ant-design/icons";
import { Upload } from "antd";
import type { UploadProps } from "antd";

import { t } from "../i18n/ru";

type Props = Omit<UploadProps, "beforeUpload" | "maxCount" | "children">;

/**
 * Выбор одного файла в форме диалога — antd `Upload.Dragger` (Refine/antd P2, п. 8): файл можно
 * перетащить в область или выбрать щелчком; область — кнопка в порядке Tab, Enter открывает выбор
 * файла (rc-upload). Файл не отправляется сам — его забирает `onFinish` формы, как раньше.
 * Форматы и предел размера — в подписи поля. `fileList`/`onChange`/`id` приходят от `Form.Item`.
 */
export function FileDragger(props: Props) {
  return (
    <Upload.Dragger {...props} beforeUpload={() => false} maxCount={1}>
      <p className="ant-upload-drag-icon">
        <UploadOutlined aria-hidden />
      </p>
      <p className="ant-upload-text">{t.upload.drag}</p>
      <p className="ant-upload-hint">{t.upload.hint}</p>
    </Upload.Dragger>
  );
}
