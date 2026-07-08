const canvas = document.querySelector("#three-background");

if (canvas) {
  startBackground(canvas);
}

async function startBackground(canvas) {
  try {
    const THREE = await import("https://cdn.jsdelivr.net/npm/three@0.166.1/build/three.module.js");
    createManifoldScene(THREE, canvas);
  } catch (error) {
    canvas.classList.add("background-fallback");
    console.warn("Three.js background unavailable:", error);
  }
}

function createManifoldScene(THREE, canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.7));

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 90);
  camera.position.set(0, 3.4, 11);
  camera.lookAt(0, 0, 0);

  const cols = 118;
  const rows = 54;
  const pointCount = cols * rows;
  const positions = new Float32Array(pointCount * 3);
  const base = new Float32Array(pointCount * 2);
  const colors = new Float32Array(pointCount * 3);
  const color = new THREE.Color();

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const index = row * cols + col;
      const x = (col / (cols - 1) - 0.5) * 18;
      const z = (row / (rows - 1) - 0.5) * 8.2;
      base[index * 2] = x;
      base[index * 2 + 1] = z;

      const fade = 0.34 + 0.48 * (row / rows);
      color.setRGB(fade, fade, fade);
      colors[index * 3] = color.r;
      colors[index * 3 + 1] = color.g;
      colors[index * 3 + 2] = color.b;
    }
  }

  const pointGeometry = new THREE.BufferGeometry();
  const positionAttribute = new THREE.BufferAttribute(positions, 3);
  positionAttribute.setUsage(THREE.DynamicDrawUsage);
  pointGeometry.setAttribute("position", positionAttribute);
  pointGeometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

  const pointMaterial = new THREE.PointsMaterial({
    size: 0.035,
    vertexColors: true,
    transparent: true,
    opacity: 0.62,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  const surface = new THREE.Points(pointGeometry, pointMaterial);
  surface.rotation.x = -0.72;
  surface.position.set(1.4, -1.1, -0.3);
  scene.add(surface);

  const lineGroup = new THREE.Group();
  lineGroup.position.copy(surface.position);
  lineGroup.rotation.copy(surface.rotation);
  scene.add(lineGroup);

  const streamLines = Array.from({ length: 9 }, (_, index) => {
    const geometry = new THREE.BufferGeometry();
    const linePositions = new Float32Array(cols * 3);
    const attr = new THREE.BufferAttribute(linePositions, 3);
    attr.setUsage(THREE.DynamicDrawUsage);
    geometry.setAttribute("position", attr);
    const material = new THREE.LineBasicMaterial({
      color: index % 3 === 0 ? 0xffffff : 0xb8c7d6,
      transparent: true,
      opacity: index % 3 === 0 ? 0.22 : 0.13,
      blending: THREE.AdditiveBlending,
    });
    const line = new THREE.Line(geometry, material);
    line.userData = { row: 5 + index * 5, phase: index * 0.61 };
    lineGroup.add(line);
    return line;
  });

  const pointer = new THREE.Vector2(0, 0);
  window.addEventListener("pointermove", (event) => {
    pointer.x = event.clientX / window.innerWidth - 0.5;
    pointer.y = event.clientY / window.innerHeight - 0.5;
  });

  function wave(x, z, time) {
    return (
      Math.sin(x * 0.72 + time * 0.78) * 0.44 +
      Math.sin((x + z) * 1.02 - time * 0.52) * 0.24 +
      Math.cos(z * 1.54 + time * 0.36) * 0.18
    );
  }

  function updateGeometry(time) {
    const array = positionAttribute.array;
    for (let index = 0; index < pointCount; index += 1) {
      const x = base[index * 2];
      const z = base[index * 2 + 1];
      const rowRatio = (z / 8.2) + 0.5;
      const drift = Math.sin(time * 0.18 + rowRatio * Math.PI) * 0.55;
      const y = wave(x + drift, z, time);
      const offset = index * 3;
      array[offset] = x + drift;
      array[offset + 1] = y;
      array[offset + 2] = z;
    }
    positionAttribute.needsUpdate = true;

    streamLines.forEach((line) => {
      const linePositions = line.geometry.getAttribute("position");
      const z = ((line.userData.row / (rows - 1)) - 0.5) * 8.2;
      for (let col = 0; col < cols; col += 1) {
        const x = (col / (cols - 1) - 0.5) * 18;
        const shimmer = Math.sin(col * 0.19 + time * 1.15 + line.userData.phase) * 0.15;
        linePositions.setXYZ(col, x + shimmer, wave(x, z, time) + 0.035, z);
      }
      linePositions.needsUpdate = true;
    });
  }

  function resize() {
    const width = canvas.clientWidth || window.innerWidth;
    const height = canvas.clientHeight || window.innerHeight;
    renderer.setSize(width, height, false);
    camera.aspect = width / Math.max(height, 1);
    camera.updateProjectionMatrix();
  }

  function animate(timeMs) {
    const time = timeMs * 0.001;
    updateGeometry(time);
    surface.rotation.z = pointer.x * 0.035;
    lineGroup.rotation.z = surface.rotation.z;
    surface.position.y = -1.12 + pointer.y * 0.18;
    lineGroup.position.y = surface.position.y;
    renderer.render(scene, camera);
  }

  resize();
  updateGeometry(0);
  window.addEventListener("resize", resize);
  renderer.setAnimationLoop(animate);
}
