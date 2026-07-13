import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import projectService from '../services/projectService';
import ProjectForm from '../components/projects/ProjectForm';

const ProjectCreatePage = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (payload) => {
    setBusy(true);
    try {
      const data = await projectService.create(payload);
      const created = data?.project || data;
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      navigate(created?.id ? `/projects/${created.id}` : '/projects');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <div>
        <Link to="/projects" className="link text-sm">
          ← Projects
        </Link>
        <h1 className="mt-1">New Project</h1>
      </div>
      <ProjectForm onSubmit={handleSubmit} submitLabel="Create Project" busy={busy} />
    </div>
  );
};

export default ProjectCreatePage;
