import os
import uuid
import magic
import shutil
from werkzeug.utils import secure_filename
from flask import current_app
from app import db
from app.models.project import ProjectFile

# Content types for the 3D formats we accept. Mostly informational: the
# viewer picks its loader from the extension, but a stored MIME beats
# "application/octet-stream" for every mesh in the API payload.
MODEL_MIME_TYPES = {
    '.stl': 'model/stl',
    '.3mf': 'model/3mf',
    '.obj': 'model/obj',
    '.step': 'model/step',
    '.stp': 'model/step',
    '.scad': 'text/x-scad',
    '.gcode': 'text/x.gcode',
    '.bgcode': 'application/x.bgcode',
    '.f3d': 'application/x-fusion360',
}


class FileService:
    """Service for handling file uploads and storage.

    Files live under UPLOAD_FOLDER (outside the app package):
        uploads/components/<component_id>/<name>
        uploads/projects/<project_id>/<name>
    They are served in dev by the /uploads route and by nginx->gunicorn in prod.
    """

    @staticmethod
    def validate_file(file, allowed_types, max_size):
        """
        Validate file type and size

        Args:
            file: FileStorage object
            allowed_types: Set of allowed MIME types (None = any type)
            max_size: Maximum file size in bytes

        Returns:
            tuple: (is_valid, error_message, detected_mime_type)
        """
        if not file:
            return False, 'No file provided', None

        if file.filename == '':
            return False, 'No file selected', None

        # Check file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)  # Reset to beginning

        if file_size > max_size:
            return False, f'File too large (max {max_size // 1024 // 1024}MB)', None

        # Check MIME type using magic numbers
        mime = magic.Magic(mime=True)
        file_data = file.read(2048)  # Read first 2KB
        file.seek(0)  # Reset to beginning

        detected_type = mime.from_buffer(file_data)

        if allowed_types is not None and detected_type not in allowed_types:
            return False, f'Invalid file type. Allowed: {", ".join(sorted(allowed_types))}', detected_type

        return True, None, detected_type

    @staticmethod
    def save_component_image(component, file):
        """
        Save (or replace) a component's image.

        Args:
            component: Component instance
            file: FileStorage object

        Returns:
            str: Relative file path (e.g. 'components/3/a1b2c3d4.png')
        """
        is_valid, error, _ = FileService.validate_file(
            file,
            current_app.config['ALLOWED_IMAGE_TYPES'],
            current_app.config['MAX_IMAGE_SIZE']
        )
        if not is_valid:
            raise ValueError(error)

        upload_dir = os.path.join(
            current_app.config['UPLOAD_FOLDER'], 'components', str(component.id)
        )
        os.makedirs(upload_dir, exist_ok=True)

        ext = os.path.splitext(file.filename)[1].lower() or '.jpg'
        filename = f'{uuid.uuid4().hex[:12]}{ext}'
        file.save(os.path.join(upload_dir, filename))

        # Remove the previous image, if any
        if component.image:
            old_path = FileService.get_file_path(component.image)
            if os.path.isfile(old_path):
                try:
                    os.remove(old_path)
                except OSError:
                    current_app.logger.warning(f'Could not remove old image {old_path}')

        return f'components/{component.id}/{filename}'

    @staticmethod
    def save_project_file(project_id, file, kind='other'):
        """
        Save a project file to the filesystem and create a database record.

        Args:
            project_id: Project ID
            file: FileStorage object
            kind: image | pdf | schematic | firmware | model3d | other

        Returns:
            ProjectFile: created database record
        """
        # Images and PDFs get strict type checks; other kinds only a size cap
        if kind == 'image':
            allowed = current_app.config['ALLOWED_IMAGE_TYPES']
            max_size = current_app.config['MAX_IMAGE_SIZE']
        elif kind == 'pdf':
            allowed = current_app.config['ALLOWED_PDF_TYPES']
            max_size = current_app.config['MAX_PDF_SIZE']
        elif kind == 'model3d':
            # Extension check instead of MIME (see ALLOWED_MODEL_EXTENSIONS)
            ext = FileService.model_extension(file.filename)
            allowed_ext = current_app.config['ALLOWED_MODEL_EXTENSIONS']
            if ext not in allowed_ext:
                raise ValueError(
                    f'Not a supported 3D model file ({ext or "no extension"}). '
                    f'Allowed: {", ".join(sorted(allowed_ext))}'
                )
            allowed = None
            max_size = current_app.config['MAX_MODEL_SIZE']
        else:
            allowed = None
            max_size = current_app.config['MAX_FILE_SIZE']

        is_valid, error, mime_type = FileService.validate_file(file, allowed, max_size)
        if not is_valid:
            raise ValueError(error)

        if kind == 'model3d':
            # magic sniffs meshes as octet-stream/text-plain; record the real
            # format so a download and the viewer both know what they have.
            mime_type = MODEL_MIME_TYPES.get(
                FileService.model_extension(file.filename), mime_type
            )

        upload_dir = os.path.join(
            current_app.config['UPLOAD_FOLDER'], 'projects', str(project_id)
        )
        os.makedirs(upload_dir, exist_ok=True)

        original = secure_filename(file.filename) or 'file'
        filename = f'{uuid.uuid4().hex[:12]}_{original}'
        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)

        project_file = ProjectFile(
            project_id=project_id,
            kind=kind,
            filename=file.filename,
            file_path=f'projects/{project_id}/{filename}',
            mime_type=mime_type,
            size=os.path.getsize(filepath),
        )
        db.session.add(project_file)
        db.session.commit()

        return project_file

    @staticmethod
    def delete_project_file(project_file):
        """Delete a project file record and its file on disk"""
        filepath = FileService.get_file_path(project_file.file_path)
        if os.path.isfile(filepath):
            try:
                os.remove(filepath)
            except OSError:
                current_app.logger.warning(f'Could not remove file {filepath}')
        db.session.delete(project_file)
        db.session.commit()

    @staticmethod
    def delete_component_files(component_id):
        """Delete all files associated with a component"""
        component_dir = os.path.join(
            current_app.config['UPLOAD_FOLDER'], 'components', str(component_id)
        )
        if os.path.exists(component_dir):
            shutil.rmtree(component_dir)

    @staticmethod
    def delete_project_files(project_id):
        """Delete all files associated with a project"""
        project_dir = os.path.join(
            current_app.config['UPLOAD_FOLDER'], 'projects', str(project_id)
        )
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)

    @staticmethod
    def model_extension(filename):
        """Lowercase extension of a filename ('' when it has none)"""
        return os.path.splitext(filename or '')[1].lower()

    @staticmethod
    def get_file_path(relative_path):
        """
        Get absolute file path from relative path

        Args:
            relative_path: Relative path (e.g. 'components/1/abc.jpg')

        Returns:
            str: Absolute file path
        """
        return os.path.join(current_app.config['UPLOAD_FOLDER'], relative_path)

    @staticmethod
    def file_exists(relative_path):
        """Check if file exists"""
        return os.path.isfile(FileService.get_file_path(relative_path))
