import { ArrowDownOutlined, ArrowUpOutlined, StarFilled, StarOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { App, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CatalogImage, CatalogItemDetail } from "../../../shared/api/generated/model";
import {
  getGetCatalogItemImageContentUrl,
  getGetCatalogItemQueryKey,
  useDeleteCatalogItemImage,
  useUpdateCatalogItemImage,
  useUploadCatalogItemImage,
} from "../../../shared/api/generated/platform-bff";
import { FilePicker } from "../../../shared/ui/FileField";
import { FormModal } from "./common";
import { catalogErrorText } from "./errors";

export const MAX_PHOTOS = 10;
const MAX_PHOTO_BYTES = 5 * 1024 * 1024;
const ACCEPT = ".jpg,.jpeg,.png,.webp";

/**
 * Карточка товара · Фото (CAT-CARD-1): до 10 фото, ровно одно главное (звезда и слово), порядок стрелками, удаление с
 * подтверждением. Файл сразу уходит в карточку; подсказка про размер и фон ничего не блокирует (GS1 Product Image
 * Specification). Картинки показываются через BFF (`…/images/{id}/content`): CSP Платформы не пускает адреса хранилища.
 */
export function ItemPhotos({ card, editable }: { card: CatalogItemDetail; editable: boolean }) {
  const { t } = useTranslation("catalog");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [removing, setRemoving] = useState<{ image: CatalogImage; n: number } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const images = card.images;
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: getGetCatalogItemQueryKey(card.id) });
  const upload = useUploadCatalogItemImage();
  const update = useUpdateCatalogItemImage({
    mutation: {
      onSuccess: () => void refresh(),
      onError: (error) => void message.error(catalogErrorText(t, error)),
    },
  });
  const remove = useDeleteCatalogItemImage({
    mutation: {
      onSuccess: () => {
        void refresh();
        void message.success(t("photos.deleted"));
        setRemoving(null);
      },
    },
  });
  const full = images.length >= MAX_PHOTOS;

  const pick = async (files: File[]) => {
    setProblem(null);
    const room = MAX_PHOTOS - images.length;
    const take: File[] = [];
    for (const file of files) {
      if (!ACCEPT.split(",").some((ext) => file.name.toLowerCase().endsWith(ext))) {
        setProblem(t("errors.reason.file_type_not_allowed"));
        return;
      }
      if (file.size > MAX_PHOTO_BYTES) {
        setProblem(t("errors.reason.file_too_large"));
        return;
      }
      take.push(file);
    }
    if (take.length > room) setProblem(t("errors.reason.image_limit_reached"));
    setUploading(true);
    try {
      for (const file of take.slice(0, room)) {
        await upload.mutateAsync({ id: card.id, data: { image: file } });
      }
      void message.success(t("photos.uploaded"));
    } catch (error) {
      setProblem(catalogErrorText(t, error));
    } finally {
      setUploading(false);
      void refresh();
    }
  };

  return (
    <section aria-labelledby="pf-photos-title">
      <h3 className="pf-cat-section" id="pf-photos-title">
        {t("photos.title")}{" "}
        <span className="pf-hint pf-num">
          {t("photos.count", { count: images.length, max: MAX_PHOTOS })}
        </span>
      </h3>
      {images.length === 0 ? (
        <p className="pf-cat-note">{t("photos.empty")}</p>
      ) : (
        <ul className="pf-cat-photos" aria-label={t("photos.list")}>
          {images.map((image, index) => {
            const n = index + 1;
            return (
              <li key={image.id} className="pf-cat-photo">
                <img
                  src={getGetCatalogItemImageContentUrl(card.id, image.id)}
                  alt={image.alt || t("photos.alt", { n, total: images.length })}
                  loading="lazy"
                />
                <div className="pf-cat-photo-bar">
                  {image.is_main ? (
                    <span className="pf-cat-photo-main">
                      <StarFilled aria-hidden /> {t("photos.main")}
                    </span>
                  ) : editable ? (
                    <Button
                      size="small"
                      icon={<StarOutlined aria-hidden />}
                      aria-label={t("photos.makeMainNamed", { n })}
                      disabled={update.isPending}
                      onClick={() => {
                        update.mutate({ id: card.id, imageId: image.id, data: { is_main: true } });
                      }}
                    >
                      {t("photos.makeMain")}
                    </Button>
                  ) : null}
                  {editable ? (
                    <span className="pf-cat-photo-tools">
                      <Button
                        size="small"
                        icon={<ArrowUpOutlined aria-hidden />}
                        aria-label={t("photos.upNamed", { n })}
                        disabled={index === 0 || update.isPending}
                        onClick={() => {
                          update.mutate({
                            id: card.id,
                            imageId: image.id,
                            data: { sort_order: index - 1 },
                          });
                        }}
                      />
                      <Button
                        size="small"
                        icon={<ArrowDownOutlined aria-hidden />}
                        aria-label={t("photos.downNamed", { n })}
                        disabled={index === images.length - 1 || update.isPending}
                        onClick={() => {
                          update.mutate({
                            id: card.id,
                            imageId: image.id,
                            data: { sort_order: index + 1 },
                          });
                        }}
                      />
                      <Button
                        size="small"
                        danger
                        aria-label={t("photos.removeNamed", { n })}
                        onClick={() => {
                          setRemoving({ image, n });
                        }}
                      >
                        {t("photos.remove")}
                      </Button>
                    </span>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {editable ? (
        <div className="pf-cat-photo-add">
          <FilePicker
            accept={ACCEPT}
            multiple
            disabled={full}
            loading={uploading}
            buttonLabel={t("photos.add")}
            inputLabel={t("photos.fileLabel")}
            onPick={(files) => void pick(files)}
          />
          {full ? <span className="pf-hint">{t("photos.limit", { max: MAX_PHOTOS })}</span> : null}
        </div>
      ) : null}
      <p className="pf-hint">{t("photos.hint")}</p>
      {problem ? (
        <p className="pf-cat-note" role="alert">
          {problem}
        </p>
      ) : null}
      {removing ? (
        <FormModal
          title={t("photos.deleteTitle", { n: removing.n })}
          okLabel={t("photos.remove")}
          loading={remove.isPending}
          error={remove.error}
          onOk={() => {
            remove.mutate({ id: card.id, imageId: removing.image.id });
          }}
          onCancel={() => {
            setRemoving(null);
          }}
        >
          <img
            className="pf-cat-photo-confirm"
            src={getGetCatalogItemImageContentUrl(card.id, removing.image.id)}
            alt={t("photos.alt", { n: removing.n, total: images.length })}
          />
        </FormModal>
      ) : null}
    </section>
  );
}
