import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import componentService from '../services/componentService';
import ComponentForm from '../components/components/ComponentForm';

const ComponentCreatePage = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (payload, imageFile) => {
    setBusy(true);
    try {
      const data = await componentService.create(payload);
      const created = data?.component || data;
      if (imageFile && created?.id) {
        await componentService.uploadImage(created.id, imageFile);
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
      </div>
      <ComponentForm onSubmit={handleSubmit} submitLabel="Create Component" busy={busy} />
    </div>
  );
};

export default ComponentCreatePage;
