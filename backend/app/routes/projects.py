from datetime import datetime

from flask import Blueprint, request, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from app import db
from app.models.project import (Project, ProjectComponent, ProjectFile, ProjectAssemblyStep,
                                PROJECT_STATUSES, PROJECT_FILE_KINDS)
from app.models.component import Component
from app.models.tag import Tag
from app.services.file_service import FileService
from app.services.stock_service import adjust_stock, InsufficientStockError
from app.services.assembly_service import assembly_report, normalise_tags, resequence
from app.routes import paginate_query, parse_money

projects_bp = Blueprint('projects', __name__)


PROJECT_SORTS = {
    'name': Project.name,
    'status': Project.status,
    'created_at': Project.created_at,
    'updated_at': Project.updated_at,
}


def _apply_tags(project, tag_values):
    """Replace a project's tags from a list of names or ids"""
    tags = []
    for value in tag_values:
        if isinstance(value, int):
            tag = Tag.query.get(value)
            if tag:
                tags.append(tag)
        elif isinstance(value, str) and value.strip():
            tags.append(Tag.get_or_create(value, user_id=current_user.id))
    project.tags = tags


def _set_fields(project, data):
    """Apply updatable fields from a request payload"""
    for field in ('name', 'description', 'readme_md', 'repo_url'):
        if field in data:
            value = data[field]
            setattr(project, field, value.strip() if isinstance(value, str) and field == 'name' else value)

    if 'status' in data:
        if data['status'] not in PROJECT_STATUSES:
            raise ValueError(f'status must be one of {", ".join(PROJECT_STATUSES)}')
        project.status = data['status']

    if 'tags' in data and isinstance(data['tags'], list):
        _apply_tags(project, data['tags'])


@projects_bp.route('', methods=['GET'])
@projects_bp.route('/', methods=['GET'])
@login_required
def list_projects():
    """List projects with search / status / tag filters"""
    query = Project.query

    search = request.args.get('search', '').strip()
    if search:
        like = f'%{search}%'
        query = query.filter(or_(
            Project.name.ilike(like),
            Project.description.ilike(like),
        ))

    status = request.args.get('status')
    if status:
        query = query.filter(Project.status == status)

    tag = request.args.get('tag')
    if tag:
        query = query.join(Project.tags).filter(Tag.name == tag)

    return paginate_query(
        query, lambda p: p.to_dict(),
        sort_map=PROJECT_SORTS, default_sort='updated_at',
    ), 200


@projects_bp.route('/<int:id>', methods=['GET'])
@login_required
def get_project(id):
    """Get a project with BOM (availability annotated) and files"""
    project = Project.query.get_or_404(id)
    return project.to_dict(include_detail=True), 200


@projects_bp.route('', methods=['POST'])
@projects_bp.route('/', methods=['POST'])
@login_required
def create_project():
    """Create a new project"""
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    name = (data.get('name') or '').strip()
    if not name:
        return {'error': 'name is required'}, 400

    project = Project(name=name, user_id=current_user.id)

    try:
        _set_fields(project, data)
        db.session.add(project)
        db.session.commit()
        return project.to_dict(include_detail=True), 201
    except ValueError as e:
        db.session.rollback()
        return {'error': str(e)}, 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to create project: {e}')
        return {'error': 'Failed to create project'}, 500


@projects_bp.route('/<int:id>', methods=['PUT'])
@login_required
def update_project(id):
    """Update a project"""
    project = Project.query.get_or_404(id)
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    if 'name' in data and not (data.get('name') or '').strip():
        return {'error': 'name cannot be empty'}, 400

    try:
        _set_fields(project, data)
        db.session.commit()
        return project.to_dict(include_detail=True), 200
    except ValueError as e:
        db.session.rollback()
        return {'error': str(e)}, 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to update project: {e}')
        return {'error': 'Failed to update project'}, 500


@projects_bp.route('/<int:id>', methods=['DELETE'])
@login_required
def delete_project(id):
    """Delete a project, its BOM and its files"""
    project = Project.query.get_or_404(id)

    try:
        FileService.delete_project_files(project.id)
        db.session.delete(project)
        db.session.commit()
        return {'message': 'Project deleted successfully'}, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to delete project: {e}')
        return {'error': 'Failed to delete project'}, 500


# ==================== BOM ====================

@projects_bp.route('/<int:id>/bom', methods=['POST'])
@login_required
def add_bom_line(id):
    """Add a component to a project's BOM"""
    project = Project.query.get_or_404(id)
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    component = Component.query.get(data.get('component_id') or 0)
    if not component:
        return {'error': 'component_id is required and must exist'}, 400

    if project.bom.filter_by(component_id=component.id).first():
        return {'error': 'Component is already on this BOM'}, 409

    qty_planned = data.get('qty_planned', 1)
    if not isinstance(qty_planned, int) or qty_planned < 1:
        return {'error': 'qty_planned must be a positive integer'}, 400

    try:
        est_unit_cost = (parse_money(data['est_unit_cost'], 'est_unit_cost')
                         if 'est_unit_cost' in data else None)
    except ValueError as e:
        return {'error': str(e)}, 400

    try:
        line = ProjectComponent(
            project_id=project.id,
            component_id=component.id,
            qty_planned=qty_planned,
            note=(data.get('note') or '').strip() or None,
            est_unit_cost=est_unit_cost,
        )
        db.session.add(line)
        db.session.commit()
        return line.to_dict(), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to add BOM line: {e}')
        return {'error': 'Failed to add BOM line'}, 500


@projects_bp.route('/<int:id>/bom/<int:line_id>', methods=['PUT'])
@login_required
def update_bom_line(id, line_id):
    """Update a BOM line (qty_planned / note)"""
    line = ProjectComponent.query.filter_by(id=line_id, project_id=id).first_or_404()
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    if 'qty_planned' in data:
        qty_planned = data['qty_planned']
        if not isinstance(qty_planned, int) or qty_planned < 1:
            return {'error': 'qty_planned must be a positive integer'}, 400
        line.qty_planned = qty_planned

    if 'note' in data:
        line.note = (data.get('note') or '').strip() or None

    # Clearing this (null / '') falls the line back to the component's own
    # estimate rather than pricing it at zero.
    if 'est_unit_cost' in data:
        try:
            line.est_unit_cost = parse_money(data['est_unit_cost'], 'est_unit_cost')
        except ValueError as e:
            return {'error': str(e)}, 400

    try:
        db.session.commit()
        return line.to_dict(), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to update BOM line: {e}')
        return {'error': 'Failed to update BOM line'}, 500


@projects_bp.route('/<int:id>/bom/<int:line_id>', methods=['DELETE'])
@login_required
def delete_bom_line(id, line_id):
    """Remove a component from a project's BOM"""
    line = ProjectComponent.query.filter_by(id=line_id, project_id=id).first_or_404()

    try:
        db.session.delete(line)
        db.session.commit()
        return {'message': 'BOM line removed'}, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to delete BOM line: {e}')
        return {'error': 'Failed to delete BOM line'}, 500


@projects_bp.route('/<int:id>/bom/<int:line_id>/consume', methods=['POST'])
@login_required
def consume_bom_line(id, line_id):
    """Consume stock for a BOM line (decrements via project_use transaction)"""
    line = ProjectComponent.query.filter_by(id=line_id, project_id=id).first_or_404()
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    qty = data.get('qty')
    if not isinstance(qty, int) or qty < 1:
        return {'error': 'qty must be a positive integer'}, 400

    try:
        adjust_stock(
            line.component, -qty, 'project_use',
            user_id=current_user.id,
            project_component_id=line.id,
            note=f'Consumed by project "{line.project.name}"',
        )
        line.qty_used = (line.qty_used or 0) + qty
        db.session.commit()
        return line.to_dict(), 200
    except InsufficientStockError as e:
        db.session.rollback()
        return {'error': str(e)}, 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to consume stock: {e}')
        return {'error': 'Failed to consume stock'}, 500


# ==================== Files ====================

@projects_bp.route('/<int:id>/files', methods=['POST'])
@login_required
def upload_project_file(id):
    """Upload a project file (multipart, kind=image|pdf|schematic|firmware|model3d|other)"""
    project = Project.query.get_or_404(id)

    file = request.files.get('file')
    if not file:
        return {'error': 'No file provided'}, 400

    kind = request.form.get('kind', 'other')
    if kind not in PROJECT_FILE_KINDS:
        return {'error': f'kind must be one of {", ".join(PROJECT_FILE_KINDS)}'}, 400

    try:
        project_file = FileService.save_project_file(project.id, file, kind=kind)
        return project_file.to_dict(), 201
    except ValueError as e:
        return {'error': str(e)}, 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to save project file: {e}')
        return {'error': 'Failed to save file'}, 500


@projects_bp.route('/<int:id>/files/<int:file_id>', methods=['DELETE'])
@login_required
def delete_project_file(id, file_id):
    """Delete a project file"""
    project_file = ProjectFile.query.filter_by(id=file_id, project_id=id).first_or_404()

    try:
        FileService.delete_project_file(project_file)
        return {'message': 'File deleted successfully'}, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to delete project file: {e}')
        return {'error': 'Failed to delete file'}, 500


# ==================== Assembly order ====================
#
# Steps are always returned through assembly_report(), never raw, so that a
# caller cannot read the order without also being handed the conflicts in it.
# That is the whole point of the feature: the list and the check are one thing.

def _assembly_payload(project):
    """Steps + conflicts + BOM hazards for one project"""
    lines = project.bom.options(joinedload(ProjectComponent.component)).all()
    return assembly_report(project.assembly_steps.all(), lines)


def _set_step_fields(step, data):
    """Apply updatable fields to an assembly step from a request payload"""
    if 'title' in data:
        title = (data.get('title') or '').strip()
        if not title:
            raise ValueError('title cannot be empty')
        step.title = title[:200]

    if 'body_md' in data:
        step.body_md = data['body_md'] or None

    if 'component_id' in data:
        component_id = data['component_id']
        if component_id in (None, '', 0):
            step.component_id = None
        else:
            component = Component.query.get(component_id)
            if not component:
                raise ValueError('component_id must reference an existing component')
            step.component_id = component.id

    for field in ('obstructs', 'needs_access'):
        if field in data:
            setattr(step, field, normalise_tags(data[field]))

    if 'done' in data:
        done = bool(data['done'])
        # Only move done_at on an actual transition, so re-saving a finished
        # step does not keep resetting when it was finished.
        if done and not step.done:
            step.done_at = datetime.utcnow()
        elif not done:
            step.done_at = None
        step.done = done


@projects_bp.route('/<int:id>/assembly', methods=['GET'])
@login_required
def get_assembly(id):
    """Get a project's assembly order, checked for access conflicts"""
    project = Project.query.get_or_404(id)
    return _assembly_payload(project), 200


@projects_bp.route('/<int:id>/assembly', methods=['POST'])
@login_required
def add_assembly_step(id):
    """Append an assembly step, or insert one at `seq`"""
    project = Project.query.get_or_404(id)
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    if not (data.get('title') or '').strip():
        return {'error': 'title is required'}, 400

    existing = project.assembly_steps.all()

    # An explicit seq inserts AT that position and pushes the rest down; no seq
    # appends. Inserting matters more than appending here - the usual edit is
    # "this has to happen before that", which is an insert.
    requested = data.get('seq')
    if isinstance(requested, int) and requested >= 1:
        position = min(requested, len(existing) + 1)
        for other in existing:
            if other.seq >= position:
                other.seq += 1
    else:
        position = len(existing) + 1

    step = ProjectAssemblyStep(project_id=project.id, seq=position, title='')

    try:
        _set_step_fields(step, data)
        db.session.add(step)
        db.session.flush()
        resequence(existing + [step])
        db.session.commit()
        return {'step': step.to_dict(), 'assembly': _assembly_payload(project)}, 201
    except ValueError as e:
        db.session.rollback()
        return {'error': str(e)}, 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to add assembly step: {e}')
        return {'error': 'Failed to add assembly step'}, 500


@projects_bp.route('/<int:id>/assembly/<int:step_id>', methods=['PUT'])
@login_required
def update_assembly_step(id, step_id):
    """Update an assembly step (title / body / component / tags / done)"""
    step = ProjectAssemblyStep.query.filter_by(id=step_id, project_id=id).first_or_404()
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    try:
        _set_step_fields(step, data)
        db.session.commit()
        return {'step': step.to_dict(), 'assembly': _assembly_payload(step.project)}, 200
    except ValueError as e:
        db.session.rollback()
        return {'error': str(e)}, 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to update assembly step: {e}')
        return {'error': 'Failed to update assembly step'}, 500


@projects_bp.route('/<int:id>/assembly/<int:step_id>', methods=['DELETE'])
@login_required
def delete_assembly_step(id, step_id):
    """Delete an assembly step and close the gap in the numbering"""
    project = Project.query.get_or_404(id)
    step = ProjectAssemblyStep.query.filter_by(id=step_id, project_id=id).first_or_404()

    try:
        db.session.delete(step)
        db.session.flush()
        resequence(project.assembly_steps.all())
        db.session.commit()
        return {'message': 'Assembly step removed', 'assembly': _assembly_payload(project)}, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to delete assembly step: {e}')
        return {'error': 'Failed to delete assembly step'}, 500


@projects_bp.route('/<int:id>/assembly/reorder', methods=['POST'])
@login_required
def reorder_assembly(id):
    """Reorder the whole assembly order: {"order": [step_id, step_id, ...]}

    Takes the complete list rather than a move-one-step verb, because moving a
    step is precisely the operation that can introduce or clear a conflict and
    the response re-checks the order as a whole.
    """
    project = Project.query.get_or_404(id)
    data = request.get_json()

    if not data or not isinstance(data.get('order'), list):
        return {'error': 'order must be a list of step ids'}, 400

    steps = {s.id: s for s in project.assembly_steps.all()}
    order = data['order']

    if len(order) != len(steps) or set(order) != set(steps):
        return {'error': 'order must list every step of this project exactly once'}, 400

    try:
        for index, step_id in enumerate(order, start=1):
            steps[step_id].seq = index
        db.session.commit()
        return _assembly_payload(project), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to reorder assembly steps: {e}')
        return {'error': 'Failed to reorder assembly steps'}, 500
