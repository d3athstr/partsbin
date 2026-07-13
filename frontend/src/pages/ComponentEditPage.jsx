import { useState } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import componentService from '../services/componentService';
import ComponentForm from '../components/components/ComponentForm';

const ComponentEditPage = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ['component', id],
    queryFn: () => componentService.get(id),
  });

  const component = data?.component || data;

  const handleSubmit = async (payload, imageFile) => {
    setBusy(true);
    try {
      await componentService.update(id, payload);
      if (imageFile) {
        await componentService.uploadImage(id, imageFile);
      }
      queryClient.invalidateQueries({ queryKey: ['component', id] });
      queryClient.invalidateQueries({ queryKey: ['components'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      navigate(`/inventory/${id}`);
    } finally {
      setBusy(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <div className="w-10 h-10 border-4 border-dark-accent border-t-transparent rounded-full spinner"></div>
      </div>
    );
  }

  if (error) {
    return <div className="alert-error">Failed to load component: {error.message}</div>;
  }

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <div>
        <Link to={`/inventory/${id}`} className="link text-sm">
          ← {component?.name}
        </Link>
        <h1 className="mt-1">Edit Component</h1>
      </div>
      <ComponentForm
        initial={component || {}}
        onSubmit={handleSubmit}
        submitLabel="Save Changes"
        busy={busy}
      />
    </div>
  );
};

export default ComponentEditPage;
