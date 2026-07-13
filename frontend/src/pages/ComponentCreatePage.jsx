import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import componentService from '../services/componentService';
import ComponentForm from '../components/components/ComponentForm';

const ComponentCreatePage = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const draft = location.state?.draft || null;
  const initial = draft
    ? {
        name: draft.name || '',
        category: draft.category || '',
        manufacturer: draft.manufacturer || '',
        mpn: draft.mpn || '',
        description: draft.description || '',
        specs: draft.specs || {},
        datasheet_url: draft.datasheet_url || '',
        notes: draft.source_url ? `Source: ${draft.source_url}` : '',
      }
    : {};
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (payload, imageFile) => {
    setBusy(true);
    try {
      const data = await componentService.create(payload);
      const created = data?.component || data;
      if (imageFile && created?.id) {
        await componentService.uploadImage(created.id, imageFile);
      } else if (draft?.image_urls?.length && created?.id) {
        try {
          await componentService.attachImage(created.id, draft.image_urls);
        } catch {
          // image is nice-to-have; the component is already created
        }
      }
      queryClient.invalidateQueries({ queryKey: ['components'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      navigate(created?.id ? `/inventory/${created.id}` : '/inventory');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <div>
        <Link to="/inventory" className="link text-sm">
          ← Inventory
        </Link>
        <h1 className="mt-1">Add Component</h1>
        {draft && (
          <p className="text-sm text-dark-textMuted mt-1">
            Pre-filled from the product page - review before saving.
          </p>
        )}
      </div>
      <ComponentForm initial={initial} onSubmit={handleSubmit} submitLabel="Create Component" busy={busy} />
    </div>
  );
};

export default ComponentCreatePage;
