/**
 * 3D-format helpers, deliberately free of any three.js import: the viewer is
 * lazy-loaded, and pulling these from ModelViewer would drag the whole
 * three.js chunk into the main bundle just to read a file extension.
 */

// Formats we can actually draw. Everything else the API accepts (STEP, SCAD,
// F3D, gcode) is still storable and downloadable, it just has no preview.
export const VIEWABLE_EXTENSIONS = ['.stl', '.3mf', '.obj'];

export const extOf = (filename) => {
  const m = /\.[^./\\]+$/.exec(filename || '');
  return m ? m[0].toLowerCase() : '';
};

export const isViewable = (filename) => VIEWABLE_EXTENSIONS.includes(extOf(filename));
