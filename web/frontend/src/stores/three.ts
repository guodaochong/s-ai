import { defineStore } from 'pinia'
import { nextTick, ref } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

export const useThreeStore = defineStore('three', () => {
  const show3D = ref(false)
  const waterLevel = ref(0)
  const waterLabel = ref('0m (0%)')
  const hydroFrames = ref<any[]>([])
  const hydroIdx = ref(0)
  const hydroPlaying = ref(false)
  const hydroSpeedVal = ref(1)
  const hydroInfo = ref('')
  const hydroTimeLabel = ref('0.0h')
  const hmBounds = ref<number[][] | null>(null)

  let scene: THREE.Scene | null = null
  let camera: THREE.PerspectiveCamera | null = null
  let renderer: THREE.WebGLRenderer | null = null
  let controls: OrbitControls | null = null
  let terrainMesh: THREE.Mesh | null = null
  let waterMesh: THREE.Mesh | null = null
  let animId = 0
  let clock = new THREE.Clock()
  let heightData: any = null
  let elevMin = 0
  let elevRange = 1
  let hydro3DGroup: THREE.Group | null = null
  let tinMeshGroup: THREE.Group | null = null
  let hydroMeshMat: THREE.ShaderMaterial | null = null
  let hydroTimer: ReturnType<typeof setTimeout> | null = null
  let _hydroBounds: number[][] | null = null
  let _tinLng: Float32Array | null = null
  let _tinLat: Float32Array | null = null
  let _tinElev: Float32Array | null = null
  let _tinSimplices: number[][] | null = null
  let container: HTMLDivElement | null = null
  let hmResolve: (() => void) | null = null
  const hmReady = new Promise<void>(resolve => { hmResolve = resolve })

  function elevColor(t: number): THREE.Color {
    if (t < 0.08) return new THREE.Color(0x0d3b66)
    if (t < 0.16) return new THREE.Color(0x1a5e7a)
    if (t < 0.25) return new THREE.Color(0x1b7a3d)
    if (t < 0.35) return new THREE.Color(0x2d9e57)
    if (t < 0.45) return new THREE.Color(0x6abf59)
    if (t < 0.55) return new THREE.Color(0xa8c256)
    if (t < 0.65) return new THREE.Color(0xc9b23a)
    if (t < 0.75) return new THREE.Color(0xd4952b)
    if (t < 0.85) return new THREE.Color(0xb05c28)
    if (t < 0.92) return new THREE.Color(0x8b6142)
    return new THREE.Color(0xe8e8ec)
  }

  function init3D(el: HTMLDivElement) {
    container = el
    const W = el.clientWidth || 800
    const H = el.clientHeight || 600

    scene = new THREE.Scene()
    scene.background = new THREE.Color(0x070b14)
    scene.fog = new THREE.FogExp2(0x070b14, 0.00015)

    camera = new THREE.PerspectiveCamera(50, W / H, 1, 50000)
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setSize(W, H)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFSoftShadowMap
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.1
    el.appendChild(renderer.domElement)

    controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.08
    controls.maxPolarAngle = Math.PI * 0.48
    controls.minDistance = 100
    controls.maxDistance = 8000
    controls.target.set(0, 50, 0)
    controls.update()

    scene.add(new THREE.AmbientLight(0x334466, 0.8))

    const sun = new THREE.DirectionalLight(0xffeedd, 1.8)
    sun.position.set(600, 1000, 400)
    sun.castShadow = true
    sun.shadow.mapSize.width = 2048
    sun.shadow.mapSize.height = 2048
    sun.shadow.camera.near = 1
    sun.shadow.camera.far = 4000
    sun.shadow.camera.left = -1500
    sun.shadow.camera.right = 1500
    sun.shadow.camera.top = 1500
    sun.shadow.camera.bottom = -1500
    sun.shadow.bias = -0.001
    scene.add(sun)

    scene.add(new THREE.HemisphereLight(0x88bbff, 0x445533, 0.6))

    const rimLight = new THREE.DirectionalLight(0x6699ff, 0.5)
    rimLight.position.set(-400, 200, -300)
    scene.add(rimLight)

    const skyGeo = new THREE.SphereGeometry(15000, 32, 32)
    const skyMat = new THREE.ShaderMaterial({
      uniforms: {
        topColor: { value: new THREE.Color(0x0a1628) },
        bottomColor: { value: new THREE.Color(0x1a0a2e) },
        offset: { value: 10 },
        exponent: { value: 0.6 },
      },
      vertexShader: 'varying vec3 vWorldPos;void main(){vec4 wp=modelMatrix*vec4(position,1.0);vWorldPos=wp.xyz;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
      fragmentShader: 'uniform vec3 topColor;uniform vec3 bottomColor;uniform float offset;uniform float exponent;varying vec3 vWorldPos;void main(){float h=normalize(vWorldPos+offset).y;gl_FragColor=vec4(mix(bottomColor,topColor,max(pow(max(h,0.0),exponent),0.0)),1.0);}',
      side: THREE.BackSide,
      depthWrite: false,
    })
    scene.add(new THREE.Mesh(skyGeo, skyMat))

    fetch('/api/heightmap?size=256')
      .then(r => r.json())
      .then(data => {
        if (data.error) { console.error(data.error); return }
        heightData = data
        elevMin = data.min_elev
        elevRange = data.max_elev - data.min_elev
        if (data.bounds_wgs84) {
          const b = data.bounds_wgs84
          hmBounds.value = [[b.sw[0], b.sw[1]], [b.ne[0], b.ne[1]]]
        }
        buildTerrain(data)
        buildWater(data)
        animate()
        if (hmResolve) { hmResolve(); hmResolve = null }
      })
      .catch(e => console.error('heightmap failed', e))
  }

  function buildTerrain(data: any) {
    if (!scene) return
    const rows = data.height, cols = data.width
    const elev = data.elevation
    const sY = 300 / Math.max(elevRange, 1)
    const geo = new THREE.PlaneGeometry(2000, 2000 * rows / cols, cols - 1, rows - 1)
    const pos = geo.attributes.position
    const colors = new Float32Array(pos.count * 3)
    for (let i = 0; i < pos.count; i++) {
      const r = Math.floor(i / cols)
      const c = i % cols
      const rowArr = elev[r]
      const e = rowArr ? (rowArr[c] ?? elevMin) : elevMin
      pos.setZ(i, (e - elevMin) * sY)
      const t = (e - elevMin) / Math.max(elevRange, 1)
      const col = elevColor(t)
      colors[i * 3] = col.r; colors[i * 3 + 1] = col.g; colors[i * 3 + 2] = col.b
    }
    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3))
    geo.computeVertexNormals();
    (pos as THREE.BufferAttribute).needsUpdate = true
    const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.78, metalness: 0.05, flatShading: false })
    terrainMesh = new THREE.Mesh(geo, mat)
    terrainMesh.rotation.x = -Math.PI / 2
    terrainMesh.receiveShadow = true
    terrainMesh.castShadow = true
    scene.add(terrainMesh)
  }

  function buildWater(data: any) {
    if (!scene) return
    const geo = new THREE.PlaneGeometry(2200, 2200 * data.height / data.width, 64, 64)
    const mat = new THREE.MeshPhysicalMaterial({
      color: 0x0088cc, transparent: true, opacity: 0.45,
      roughness: 0.05, metalness: 0.2, side: THREE.DoubleSide,
      clearcoat: 0.8, clearcoatRoughness: 0.1, envMapIntensity: 1.0,
    })
    waterMesh = new THREE.Mesh(geo, mat)
    waterMesh.rotation.x = -Math.PI / 2
    const sY = 300 / Math.max(elevRange, 1)
    waterMesh.position.y = (elevMin - 50) * sY
    waterMesh.receiveShadow = true
    scene.add(waterMesh)
  }

  function setWaterLevel(pct: number) {
    waterLevel.value = pct
    if (!waterMesh || !heightData) return
    const waterElev = elevMin + elevRange * (pct / 100)
    waterMesh.position.y = waterElev
    waterLabel.value = `${Math.round(waterElev)}m (${pct}%)`
  }

  function buildTinMesh3D(data: any) {
    if (!scene) return
    if (tinMeshGroup) scene.remove(tinMeshGroup)
    tinMeshGroup = new THREE.Group()
    const geo = data.tin_geojson
    if (!geo?.features) return
    const minE = data.elevation_range_m[0], maxE = data.elevation_range_m[1]
    const eRange = Math.max(maxE - minE, 1)
    const sY = 300 / Math.max(elevRange || eRange, 1)
    const em = elevMin || minE
    const hb = hmBounds.value || [[104.84, 33.12], [104.94, 33.24]]
    const lngMin = hb[0][0], latMin = hb[0][1], lngMax = hb[1][0], latMax = hb[1][1]
    const dLng = Math.max(lngMax - lngMin, 0.0001), dLat = Math.max(latMax - latMin, 0.0001)
    const features = geo.features
    const maxF = Math.min(features.length, 50000)
    for (let i = 0; i < maxF; i++) {
      const f = features[i]
      const coords = f.geometry.coordinates[0]
      if (!coords || coords.length < 3) continue
      const triGeo = new THREE.BufferGeometry()
      const verts = new Float32Array(9)
      const eVals: number[] = []
      for (let j = 0; j < 3; j++) {
        const px = (coords[j][0] - lngMin) / dLng * 2000 - 1000
        const pz = (coords[j][1] - latMin) / dLat * 2000 - 1000
        const z = coords[j].length >= 3 ? coords[j][2] : (f.properties.elevation_m || minE)
        eVals.push(z)
        verts[j * 3] = px
        verts[j * 3 + 1] = (z - em) * sY
        verts[j * 3 + 2] = pz
      }
      triGeo.setAttribute('position', new THREE.BufferAttribute(verts, 3))
      triGeo.computeVertexNormals()
      const avgE = (eVals[0] + eVals[1] + eVals[2]) / 3
      const t = (avgE - minE) / eRange
      let cr: number, cg: number, cb: number
      if (t < 0.25) { cr = 0.06; cg = 0.73; cb = 0.51 }
      else if (t < 0.5) { cr = 0.50; cg = 0.87; cb = 0.72 }
      else if (t < 0.75) { cr = 0.96; cg = 0.62; cb = 0.04 }
      else { cr = 0.94; cg = 0.27; cb = 0.27 }
      const faceMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(cr, cg, cb), transparent: true, opacity: 0.5, side: THREE.DoubleSide, roughness: 0.7, metalness: 0.1 })
      tinMeshGroup!.add(new THREE.Mesh(triGeo, faceMat))
      const wireMat = new THREE.MeshBasicMaterial({ color: 0x00d4ff, wireframe: true, transparent: true, opacity: 0.8 })
      tinMeshGroup!.add(new THREE.Mesh(triGeo, wireMat))
    }
    tinMeshGroup.rotation.x = -Math.PI / 2
    scene.add(tinMeshGroup)
  }

  function buildHydroFrame3D(frame: any) {
    if (!scene || !controls || !camera) return
    if (hydro3DGroup) scene.remove(hydro3DGroup)
    hydro3DGroup = new THREE.Group()
    const sY = 300 / Math.max(elevRange || 1, 1)
    const em = elevMin || 0
    const hb = hmBounds.value
    if (!hb) return
    const lngMin = hb[0][0], latMin = hb[0][1], lngMax = hb[1][0], latMax = hb[1][1]
    const dLng = Math.max(lngMax - lngMin, 0.0001), dLat = Math.max(latMax - latMin, 0.0001)
    const hydroB = _hydroBounds || hb
    const depthScale = 1
    const depthThresh = 0.01

    const tLng = _tinLng, tLat = _tinLat, tElev = _tinElev, tSimp = _tinSimplices
    const depths = frame.tin_vertex_depths

    if (tLng && tLat && tElev && tSimp && tSimp.length > 0 && depths) {
      const nV = tLng.length
      const posX = new Float32Array(nV)
      const posY = new Float32Array(nV)
      const posZ = new Float32Array(nV)
      const vertDepth = new Float32Array(nV)
      const wet = new Uint8Array(nV)
      let wetCount = 0
      for (let i = 0; i < nV; i++) {
        posX[i] = (tLng[i] - lngMin) / dLng * 2000 - 1000
        posZ[i] = -((tLat[i] - latMin) / dLat * 2000 - 1000)
        posY[i] = (tElev[i] - em) * sY
        const h = depths[i] || 0
        vertDepth[i] = h
        if (h >= depthThresh) {
          posY[i] += h * sY * depthScale
          wet[i] = 1
          wetCount++
        }
      }
      const positions: number[] = []
      const vertDepthsAttr: number[] = []
      let triCount = 0
      for (let ti = 0; ti < tSimp.length; ti++) {
        const s = tSimp[ti]
        if (wet[s[0]] + wet[s[1]] + wet[s[2]] < 1) continue
        positions.push(posX[s[0]], posY[s[0]], posZ[s[0]])
        positions.push(posX[s[1]], posY[s[1]], posZ[s[1]])
        positions.push(posX[s[2]], posY[s[2]], posZ[s[2]])
        vertDepthsAttr.push(vertDepth[s[0]], vertDepth[s[1]], vertDepth[s[2]])
        triCount++
      }
      if (positions.length >= 9) {
        const bGeo = new THREE.BufferGeometry()
        bGeo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
        bGeo.setAttribute('aDepth', new THREE.Float32BufferAttribute(vertDepthsAttr, 1))
        bGeo.computeVertexNormals()
        hydroMeshMat = new THREE.ShaderMaterial({
          uniforms: {
            uTime: { value: 0 },
            uDeepColor: { value: new THREE.Color(0x003366) },
            uShallowColor: { value: new THREE.Color(0x00aaff) },
            uFoamColor: { value: new THREE.Color(0xaaeeff) },
            uOpacity: { value: 0.72 },
          },
          vertexShader: [
            'attribute float aDepth;',
            'varying float vDepth;',
            'varying vec3 vNorm;',
            'varying vec3 vWorldPos;',
            'uniform float uTime;',
            'void main(){',
            '  vDepth=aDepth;',
            '  vNorm=normalize(normalMatrix*normal);',
            '  vec3 pos=position;',
            '  pos.y+=sin(pos.x*0.02+uTime*1.5)*0.8+cos(pos.z*0.025+uTime*1.2)*0.6;',
            '  vec4 wp=modelMatrix*vec4(pos,1.0);',
            '  vWorldPos=wp.xyz;',
            '  gl_Position=projectionMatrix*viewMatrix*wp;',
            '}',
          ].join('\n'),
          fragmentShader: [
            'uniform vec3 uDeepColor;',
            'uniform vec3 uShallowColor;',
            'uniform vec3 uFoamColor;',
            'uniform float uOpacity;',
            'uniform float uTime;',
            'varying float vDepth;',
            'varying vec3 vNorm;',
            'varying vec3 vWorldPos;',
            'void main(){',
            '  float t=clamp(vDepth/3.0,0.0,1.0);',
            '  vec3 base=mix(uShallowColor,uDeepColor,t);',
            '  float fresnel=pow(1.0-abs(dot(vNorm,vec3(0,1,0))),2.5);',
            '  vec3 viewDir=normalize(cameraPosition-vWorldPos);',
            '  float spec=pow(max(dot(reflect(-normalize(vec3(0.5,1,0.3)),vNorm),viewDir),0.0),64.0);',
            '  float wave=sin(vWorldPos.x*0.04+uTime*2.0)*cos(vWorldPos.z*0.03+uTime*1.5);',
            '  float foam=smoothstep(0.6,1.0,wave)*smoothstep(0.01,0.15,vDepth);',
            '  vec3 col=base+fresnel*vec3(0.15,0.25,0.35)+spec*vec3(0.9,0.95,1.0)+foam*uFoamColor*0.3;',
            '  float alpha=mix(0.5,0.85,t)+foam*0.15;',
            '  gl_FragColor=vec4(col,alpha*uOpacity);',
            '}',
          ].join('\n'),
          transparent: true,
          side: THREE.DoubleSide,
          depthWrite: false,
        })
        const hydroMeshObj = new THREE.Mesh(bGeo, hydroMeshMat)
        hydroMeshObj.castShadow = true
        hydroMeshObj.renderOrder = 1
        hydro3DGroup.add(hydroMeshObj)
      }
    }

    scene.add(hydro3DGroup)
    if (hydro3DGroup.children.length > 0 && controls) {
      const cenLng = (hydroB[0][0] + hydroB[1][0]) / 2
      const cenLat = (hydroB[0][1] + hydroB[1][1]) / 2
      const tgtX = (cenLng - lngMin) / dLng * 2000 - 1000
      const tgtZ = -((cenLat - latMin) / dLat * 2000 - 1000)
      controls.target.set(tgtX, 100, tgtZ)
      controls.update()
      camera.position.set(tgtX + 800, 400, tgtZ + 600)
    }
  }

  function animate() {
    animId = requestAnimationFrame(animate)
    const dt = clock.getDelta()
    if (hydroMeshMat) {
      hydroMeshMat.uniforms.uTime.value += dt
    }
    controls?.update()
    if (renderer && scene && camera) {
      renderer.render(scene, camera)
    }
  }

  function toggle3D(_opts?: { hideWater?: boolean }) {
    show3D.value = !show3D.value
    if (!show3D.value) {
      stopAnimation()
    }
  }

  function stopAnimation() {
    if (animId) { cancelAnimationFrame(animId); animId = 0 }
  }

  function hydroSeek(idx: number) {
    idx = Math.max(0, Math.min(idx, hydroFrames.value.length - 1))
    hydroIdx.value = idx
    const f = hydroFrames.value[idx]
    if (!f) return
    hydroTimeLabel.value = f.time_hr + 'h'
    if (show3D.value && scene) {
      buildHydroFrame3D(f)
    }
  }

  function hydroPlayToggle() {
    if (hydroPlaying.value) {
      hydroPlaying.value = false
      if (hydroTimer) { clearTimeout(hydroTimer); hydroTimer = null }
    } else {
      hydroPlaying.value = true
      startHydroPlay()
    }
  }

  function startHydroPlay() {
    if (!hydroPlaying.value) return
    const idx = hydroIdx.value + 1
    if (idx >= hydroFrames.value.length - 1) {
      hydroPlaying.value = false
      return
    }
    hydroSeek(idx)
    hydroTimer = setTimeout(startHydroPlay, 1000 / hydroSpeedVal.value)
  }

  function setHydroSpeed(s: number) {
    hydroSpeedVal.value = s
  }

  function loadHydroSimulation(result: any) {
    hydroFrames.value = result.frames || []
    const bounds = result.bounds_wgs84
    if (bounds) {
      _hydroBounds = bounds
    }
    hydroInfo.value = `${result.grid_size || '?'} | ${result.total_steps || '?'} steps | peak ${result.peak_max_depth_m || '?'}m`
    if (result.tin_vertex_lng) {
      _tinLng = result.tin_vertex_lng
      _tinLat = result.tin_vertex_lat
      _tinElev = result.tin_vertex_elev
      _tinSimplices = result.tin_simplices || []
    }

    const needInit = !show3D.value
    if (needInit) {
      show3D.value = true
    }

    const runPlayback = () => {
      if (show3D.value && scene && hmBounds.value) {
        hydroSeek(0)
        hydroPlaying.value = true
        startHydroPlay()
      }
    }

    if (needInit) {
      nextTick(() => {
        hmReady.then(() => setTimeout(runPlayback, 200))
      })
    } else if (scene && hmBounds.value) {
      runPlayback()
    } else {
      hmReady.then(runPlayback)
    }
  }

  function handleResize() {
    if (!container || !camera || !renderer) return
    const w = container.clientWidth, h = container.clientHeight
    if (w && h) {
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    }
  }

  function dispose() {
    if (animId) cancelAnimationFrame(animId)
    if (hydroTimer) clearTimeout(hydroTimer)
    renderer?.dispose()
    scene?.clear()
    scene = null; camera = null; renderer = null; controls = null
    terrainMesh = null; waterMesh = null
  }

  return {
    show3D, waterLevel, waterLabel,
    hydroFrames, hydroIdx, hydroPlaying, hydroSpeedVal,
    hydroInfo, hydroTimeLabel,
    init3D, toggle3D, stopAnimation, setWaterLevel, handleResize, dispose,
    buildTinMesh3D, buildHydroFrame3D,
    hydroSeek, hydroPlayToggle, setHydroSpeed, loadHydroSimulation,
  }
})
