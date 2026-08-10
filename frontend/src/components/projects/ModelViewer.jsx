import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { ThreeMFLoader } from 'three/examples/jsm/loaders/3MFLoader.js';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { extOf } from './modelFormats';

/**
 * Binary STL is 84 bytes of header plus 50 per triangle, exactly. ASCII STL
 * opens with "solid", but so do plenty of binary files whose header happens
 * to start that way — the size arithmetic is the reliable test, and it is
 * what STLLoader itself uses.
 */
const isBinarySTL = (buffer) => {
  if (buffer.byteLength < 84) return false;
  const triangles = new DataView(buffer).getUint32(80, true);
  return 84 + triangles * 50 === buffer.byteLength;
};

/** Parse an arraybuffer into a THREE.Object3D, by extension. */
const parseModel = (buffer, ext) => {
  if (ext === '.stl') {
    const geometry = new STLLoader().parse(buffer);
    geometry.computeVertexNormals();
    const material = new THREE.MeshStandardMaterial({
      color: 0x8f979f, // neutral gray: this is a part, not a status indicator
      roughness: 0.75,
      metalness: 0.05,
      flatShading: false,
    });
    return { object: new THREE.Mesh(geometry, material), format: isBinarySTL(buffer) ? 'binary STL' : 'ASCII STL' };
  }

  if (ext === '.3mf') {
    return { object: new ThreeMFLoader().parse(buffer), format: '3MF' };
  }

  if (ext === '.obj') {
    const object = new OBJLoader().parse(new TextDecoder().decode(buffer));
    object.traverse((child) => {
      if (child.isMesh) {
        child.material = new THREE.MeshStandardMaterial({ color: 0x8f979f, roughness: 0.75, metalness: 0.05 });
        if (child.geometry) child.geometry.computeVertexNormals();
      }
    });
    return { object, format: 'OBJ' };
  }

  throw new Error(`No viewer for ${ext || 'this file'}`);
};

/** Triangle count across every mesh in an object tree. */
const countTriangles = (object) => {
  let total = 0;
  object.traverse((child) => {
    if (!child.isMesh || !child.geometry) return;
    const geom = child.geometry;
    total += geom.index ? geom.index.count / 3 : (geom.attributes.position?.count || 0) / 3;
  });
  return Math.round(total);
};

/**
 * Interactive preview of one 3D model: drag to orbit, scroll to zoom.
 *
 * Renders on demand rather than on an animation frame — a project page can
 * hold a dozen of these, and idle spinning canvases would cook a laptop for
 * no benefit.
 */
const ModelViewer = ({ url, filename, onLoad, className = '' }) => {
  const mountRef = useRef(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    let disposed = false;
    const width = mount.clientWidth || 320;
    const height = mount.clientHeight || 220;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0f1419); // dark.bg
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 10000);
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'low-power' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(1, 1.4, 1);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.5);
    fill.position.set(-1, -0.6, -0.8);
    scene.add(fill);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = false;
    controls.enablePan = false;

    const render = () => renderer.render(scene, camera);
    controls.addEventListener('change', render);

    const onResize = () => {
      if (disposed || !mount.clientWidth) return;
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
      render();
    };
    window.addEventListener('resize', onResize);

    let object = null;

    // Same-origin fetch so the login cookie rides along: /uploads is
    // auth-gated by design and returns 401 without a session.
    fetch(url, { credentials: 'same-origin' })
      .then((res) => {
        if (!res.ok) throw new Error(res.status === 401 ? 'Not signed in' : `HTTP ${res.status}`);
        return res.arrayBuffer();
      })
      .then((buffer) => {
        if (disposed) return;
        const parsed = parseModel(buffer, extOf(filename));
        object = parsed.object;

        // Center the model on the origin and frame it, so wildly different
        // part sizes (a 4 mm standoff, a 300 mm panel) both fill the canvas.
        const box = new THREE.Box3().setFromObject(object);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        object.position.sub(center);
        scene.add(object);

        const radius = Math.max(size.x, size.y, size.z) || 1;
        const distance = (radius / 2) / Math.tan((camera.fov * Math.PI) / 360) * 1.5;
        camera.position.set(distance * 0.7, distance * 0.55, distance * 0.7);
        camera.near = distance / 100;
        camera.far = distance * 100;
        camera.updateProjectionMatrix();
        controls.target.set(0, 0, 0);
        controls.update();
        render();

        setLoading(false);
        onLoad?.({
          dims: { x: size.x, y: size.y, z: size.z },
          triangles: countTriangles(object),
          format: parsed.format,
        });
      })
      .catch((err) => {
        if (disposed) return;
        setLoading(false);
        setError(err.message || 'Could not load model');
      });

    return () => {
      disposed = true;
      window.removeEventListener('resize', onResize);
      controls.removeEventListener('change', render);
      controls.dispose();
      if (object) {
        object.traverse((child) => {
          if (child.isMesh) {
            child.geometry?.dispose();
            const materials = Array.isArray(child.material) ? child.material : [child.material];
            materials.forEach((m) => m?.dispose());
          }
        });
      }
      renderer.dispose();
      // WebGL contexts are a scarce browser resource (~16 live at once) and
      // are not freed by dispose() alone; a page of models leaks without this.
      renderer.forceContextLoss?.();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
    };
  }, [url, filename, onLoad]);

  return (
    <div className={`relative bg-dark-bg border border-dark-border rounded-lg overflow-hidden ${className}`}>
      <div ref={mountRef} className="w-full h-full cursor-move" />
      {loading && !error && (
        <div className="absolute inset-0 flex items-center justify-center text-xs text-dark-textMuted">
          Loading model…
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center px-3 text-center text-xs text-dark-error">
          {error}
        </div>
      )}
    </div>
  );
};

export default ModelViewer;
