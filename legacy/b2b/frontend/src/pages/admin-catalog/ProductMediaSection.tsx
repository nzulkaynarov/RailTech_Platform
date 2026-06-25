import { useTranslation } from 'react-i18next';
import { Label } from '@/components/ui/label';
import {
  useProduct,
  useUploadProductImage, useDeleteProductImage,
  useUploadProductDocument, useDeleteProductDocument,
} from '@/hooks/useCatalog';
import { ImageGalleryUpload } from '@/components/Shared/ImageGalleryUpload';
import { FileUpload } from '@/components/Shared/FileUpload';

export function ProductMediaSection({ productId }: { productId: number }) {
  const { t } = useTranslation();
  const { data: product } = useProduct(String(productId));
  const uploadImage = useUploadProductImage();
  const deleteImage = useDeleteProductImage();
  const uploadDoc = useUploadProductDocument();
  const deleteDoc = useDeleteProductDocument();

  const images = (product?.images ?? []).map(img => ({
    id: img.id,
    url: img.image ?? img.image_url,
    is_main: img.is_main,
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
        <ImageGalleryUpload
          images={images}
          onUpload={async (file, isMain) => {
            await uploadImage.mutateAsync({ productId, file, isMain });
          }}
          onRemove={async imageId => {
            await deleteImage.mutateAsync({ productId, imageId });
          }}
          className="mt-2"
        />
      </div>
      <div>
        <Label className="text-sm font-medium">{t('adminCatalog.media.documents')}</Label>
        <FileUpload
          className="mt-2"
          files={docs}
          onUpload={async file => {
            await uploadDoc.mutateAsync({ productId, file, name: file.name });
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
