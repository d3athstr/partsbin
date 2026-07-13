import { useState } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import projectService from '../services/projectService';
import ProjectForm from '../components/projects/ProjectForm';

const ProjectEditPage = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ['project', id],
    queryFn: () => projectService.get(id),
  });

  const project = data?.project || data;

  const handleSubmit = async (payload) => {
    setBusy(true);
    try {
      await projectService.update(id, payload);
      queryClient.invalidateQueries({ queryKey: ['project', id] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      navigate(`/projects/${id}`);
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
    return <div className="alert-error">Failed to load project: {error.message}</div>;
  }

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <div>
        <Link to={`/projects/${id}`} className="link text-sm">
          ← {project?.name}
        </Link>
        <h1 className="mt-1">Edit Project</h1>
      </div>
      <ProjectForm
        initial={project || {}}
        onSubmit={handleSubmit}
        submitLabel="Save Changes"
        busy={busy}
      />
    </div>
  );
};

export default ProjectEditPage;
