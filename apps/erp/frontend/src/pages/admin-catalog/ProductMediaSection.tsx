import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  useProduct,
  useUploadProductImage, useDeleteProductImage,
  useUploadProductDocument, useDeleteProductDocument,
} from '@/hooks/useCatalog';
import { ImageGalleryUpload } from '@/components/Shared/ImageGalleryUpload';
import { FileUpload } from '@/components/Shared/FileUpload';

/**
 * Медиа карточки товара.
 *
 * R7: подпись фото (`alt_text`) и название документа (`ProductDocument.name`) хранились в
 * модели и принимались эндпоинтом, но ввести их было негде — alt приезжал пустым, а имя
 * документа всегда равнялось имени файла («scan_0007.pdf» вместо «Паспорт изделия»).
 * Поле подписи стоит НАД загрузчиком и применяется к следующим файлам — так же, как
 * подпись задают перед загрузкой в Shopify и Akeneo; выбор файла обрабатывает сам
 * загрузчик, перехватить его между выбором и отправкой нечем.
 */
export function ProductMediaSection({ productId }: { productId: number }) {
  const { t } = useTranslation();
  const { data: product } = useProduct(String(productId));
  const uploadImage = useUploadProductImage();
  const deleteImage = useDeleteProductImage();
  const uploadDoc = useUploadProductDocument();
  const deleteDoc = useDeleteProductDocument();
  const [altText, setAltText] = useState('');
  const [docName, setDocName] = useState('');

  const images = (product?.images ?? []).map(img => ({
    id: img.id,
    url: img.image ?? img.image_url,
    is_main: img.is_main,
    // Подпись доезжает до <img alt>: без неё галерея отдавала скринридеру пустую строку.
    alt_text: img.alt_text,
  }));
  const docs = (product?.documents ?? []).map(doc => ({
    id: doc.id,
    name: doc.name,
    url: doc.file ?? doc.file_url,
  }));

  return (
    <div className="space-y-4">
      <div>
        <Label className="text-sm font-medium">{t('adminCatalog.media.images')}</Label>
        <div className="mt-2 space-y-1">
          <Label htmlFor="product-image-alt" className="text-xs font-normal text-muted-foreground">
            {t('adminCatalog.media.altText')}
          </Label>
          <Input
            id="product-image-alt"
            value={altText}
            onChange={e => setAltText(e.target.value)}
            placeholder={t('adminCatalog.media.altTextPlaceholder')}
          />
          <p className="text-xs text-muted-foreground">{t('adminCatalog.media.altTextHint')}</p>
        </div>
        <ImageGalleryUpload
          images={images}
          onUpload={async (file, isMain) => {
            await uploadImage.mutateAsync({ productId, file, isMain, altText: altText.trim() || undefined });
            setAltText('');
          }}
          onRemove={async imageId => {
            await deleteImage.mutateAsync({ productId, imageId });
          }}
          className="mt-2"
        />
      </div>
      <div>
        <Label className="text-sm font-medium">{t('adminCatalog.media.documents')}</Label>
        <div className="mt-2 space-y-1">
          <Label htmlFor="product-document-name" className="text-xs font-normal text-muted-foreground">
            {t('adminCatalog.media.documentName')}
          </Label>
          <Input
            id="product-document-name"
            value={docName}
            onChange={e => setDocName(e.target.value)}
            placeholder={t('adminCatalog.media.documentNamePlaceholder')}
          />
          <p className="text-xs text-muted-foreground">{t('adminCatalog.media.documentNameHint')}</p>
        </div>
        <FileUpload
          className="mt-2"
          files={docs}
          onUpload={async file => {
            // Пустое поле = прежнее поведение: именем становится имя файла.
            await uploadDoc.mutateAsync({ productId, file, name: docName.trim() || file.name });
            setDocName('');
          }}
          onRemove={async docId => {
            await deleteDoc.mutateAsync({ productId, docId: Number(docId) });
          }}
          description={t('adminCatalog.media.documentsHelp')}
        />
      </div>
    </div>
  );
}
