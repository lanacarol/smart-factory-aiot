
<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import * as THREE from 'three'

const props = defineProps<{
  conveyorOn: boolean
  fanOn: boolean
  motorTemperature: number
  vibration: number
  ambientTemperature: number
  humidity: number
  online: boolean
}>()

const container = ref<HTMLDivElement | null>(null)
const selected = ref('Clique em um equipamento para consultar seu estado.')

let scene: THREE.Scene
let camera: THREE.PerspectiveCamera
let renderer: THREE.WebGLRenderer
let fanBlades: THREE.Group
let beltMarkers: THREE.Mesh[] = []
let motorMaterial: THREE.MeshStandardMaterial
let floorMaterial: THREE.MeshStandardMaterial
let animationId = 0
let observer: ResizeObserver
let previousTime = 0

const raycaster = new THREE.Raycaster()
const mouse = new THREE.Vector2()

function createBox(
  width: number,
  height: number,
  depth: number,
  color: number,
  x: number,
  y: number,
  z: number,
  parent: THREE.Object3D = scene
) {
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(width, height, depth),
    new THREE.MeshStandardMaterial({
      color,
      metalness: 0.35,
      roughness: 0.55
    })
  )

  mesh.position.set(x, y, z)
  mesh.castShadow = true
  mesh.receiveShadow = true
  parent.add(mesh)

  return mesh
}

function createFactory() {
  scene = new THREE.Scene()
  scene.background = new THREE.Color('#101b2c')
  scene.fog = new THREE.FogExp2('#101b2c', 0.012)

  const width = container.value!.clientWidth
  const height = container.value!.clientHeight

  camera = new THREE.PerspectiveCamera(
    45,
    width / height,
    0.1,
    100
  )
  camera.position.set(9, 7, 10)
  camera.lookAt(0, 0.7, 0)

  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(width, height)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.shadowMap.enabled = true
  renderer.outputColorSpace = THREE.SRGBColorSpace

  container.value!.appendChild(renderer.domElement)

  scene.add(new THREE.AmbientLight('#ffffff', 1.5))

  const light = new THREE.DirectionalLight('#ffffff', 3)
  light.position.set(5, 9, 6)
  light.castShadow = true
  scene.add(light)

  // Piso industrial
  const floor = createBox(
    12, 0.2, 8, 0x334155, 0, -0.2, 0
  )
  floorMaterial = floor.material as THREE.MeshStandardMaterial

  // Estrutura da esteira
  const conveyor = new THREE.Group()
  conveyor.userData.device = 'conveyor'
  scene.add(conveyor)

  createBox(6, 0.35, 1.8, 0x64748b, 0, 1.0, 0, conveyor)
  createBox(6, 0.06, 1.45, 0x172033, 0, 1.21, 0, conveyor)

  for (const x of [-2.5, 2.5]) {
    for (const z of [-0.65, 0.65]) {
      createBox(0.2, 1, 0.2, 0x94a3b8, x, 0.4, z, conveyor)
    }
  }

  // Peças transportadas pela esteira
  for (let i = 0; i < 4; i++) {
    const marker = createBox(
      0.5, 0.45, 0.65,
      i % 2 === 0 ? 0x38bdf8 : 0xf59e0b,
      -2.5 + i * 1.5,
      1.53,
      0,
      conveyor
    )
    beltMarkers.push(marker)
  }

  // Motor industrial
  const motor = new THREE.Group()
  motor.userData.device = 'motor'
  motor.position.set(-3.6, 0.55, 0.5)
  scene.add(motor)

  const motorBody = createBox(
    1.1, 0.9, 1.1, 0x16a34a, 0, 0, 0, motor
  )
  motorMaterial = motorBody.material as THREE.MeshStandardMaterial

  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(0.16, 0.16, 0.65, 24),
    new THREE.MeshStandardMaterial({ color: '#cbd5e1' })
  )
  shaft.rotation.z = Math.PI / 2
  shaft.position.x = 0.8
  motor.add(shaft)

  // Ventilador
  const fan = new THREE.Group()
  fan.userData.device = 'fan'
  fan.position.set(3.3, 2.4, -1.2)
  scene.add(fan)

  createBox(0.16, 2.6, 0.16, 0x94a3b8, 0, -1.3, 0, fan)

  fanBlades = new THREE.Group()
  fan.add(fanBlades)

  for (let i = 0; i < 4; i++) {
    const blade = createBox(
      0.3, 1.2, 0.08,
      0x22d3ee,
      0, 0.7, 0,
      fanBlades
    )
    blade.rotation.z = i * Math.PI / 2
    blade.position.set(
      -Math.sin(i * Math.PI / 2) * 0.7,
      Math.cos(i * Math.PI / 2) * 0.7,
      0
    )
  }

  const hub = new THREE.Mesh(
    new THREE.CylinderGeometry(0.25, 0.25, 0.2, 24),
    new THREE.MeshStandardMaterial({ color: '#e2e8f0' })
  )
  hub.rotation.x = Math.PI / 2
  fanBlades.add(hub)

  // Painel de controle
  const panel = new THREE.Group()
  panel.userData.device = 'panel'
  panel.position.set(3.8, 0, 2)
  scene.add(panel)

  createBox(1.2, 1.6, 0.35, 0x475569, 0, 1, 0, panel)
  createBox(0.8, 0.55, 0.05, 0x0ea5e9, 0, 1.25, 0.2, panel)
  createBox(0.18, 0.18, 0.08, 0x22c55e, -0.2, 0.75, 0.22, panel)
  createBox(0.18, 0.18, 0.08, 0xef4444, 0.2, 0.75, 0.22, panel)
}

function updateSimulation(delta: number) {
  const isActive = props.online

  // Esteira: só movimenta com comando ON e dados recentes.
  if (isActive && props.conveyorOn) {
    for (const marker of beltMarkers) {
      marker.position.x += delta * 1.4

      if (marker.position.x > 2.8) {
        marker.position.x = -2.8
      }
    }
  }

  // Ventilador: anima somente quando o simulador informa ON.
  if (isActive && props.fanOn) {
    fanBlades.rotation.z -= delta * 5
  }

  // Cor do motor baseada na temperatura recebida.
  if (!isActive) {
    motorMaterial.color.set('#64748b')
  } else if (props.motorTemperature >= 85) {
    motorMaterial.color.set('#ef4444')
  } else if (props.motorTemperature >= 70) {
    motorMaterial.color.set('#f59e0b')
  } else {
    motorMaterial.color.set('#22c55e')
  }

  // Ambiente reage à temperatura e à umidade simuladas.
  const hot = isActive && props.ambientTemperature >= 35
  floorMaterial.color.set(
    !isActive ? '#334155' : hot ? '#64433b' : '#33546a'
  )

  const fog = scene.fog as THREE.FogExp2
  fog.density = isActive
    ? 0.008 + Math.min(100, Math.max(0, props.humidity)) * 0.00012
    : 0.012
}

function animate(time: number) {
  animationId = requestAnimationFrame(animate)

  const delta = previousTime
    ? Math.min((time - previousTime) / 1000, 0.05)
    : 0

  previousTime = time

  updateSimulation(delta)
  renderer.render(scene, camera)
}

function resize() {
  if (!container.value || !renderer) return

  const width = container.value.clientWidth
  const height = container.value.clientHeight

  camera.aspect = width / height
  camera.updateProjectionMatrix()
  renderer.setSize(width, height)
}

function handleClick(event: MouseEvent) {
  if (!container.value) return

  const bounds = renderer.domElement.getBoundingClientRect()

  mouse.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1
  mouse.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1

  raycaster.setFromCamera(mouse, camera)

  const intersections = raycaster.intersectObjects(
    scene.children,
    true
  )

  for (const intersection of intersections) {
    let object: THREE.Object3D | null = intersection.object

    while (object && !object.userData.device) {
      object = object.parent
    }

    if (!object) continue

    const device = object.userData.device

    if (device === 'conveyor') {
      selected.value = `Esteira: ${
        props.online
          ? props.conveyorOn ? 'Ligada' : 'Desligada'
          : 'Sem dados'
      }`
    } else if (device === 'motor') {
      selected.value = `Motor: ${props.motorTemperature.toFixed(1)} °C · Vibração: ${props.vibration.toFixed(2)} mm/s`
    } else if (device === 'fan') {
      selected.value = `Ventilador: ${
        props.online
          ? props.fanOn ? 'Ligado' : 'Desligado'
          : 'Sem dados'
      }`
    } else if (device === 'panel') {
      selected.value = 'Painel de controle industrial'
    }

    return
  }
}

onMounted(() => {
  createFactory()

  observer = new ResizeObserver(resize)
  observer.observe(container.value!)

  renderer.domElement.addEventListener('click', handleClick)
  animationId = requestAnimationFrame(animate)
})

onUnmounted(() => {
  cancelAnimationFrame(animationId)
  observer?.disconnect()

  renderer?.domElement.removeEventListener('click', handleClick)

  scene?.traverse(object => {
    if (object instanceof THREE.Mesh) {
      object.geometry.dispose()

      const materials = Array.isArray(object.material)
        ? object.material
        : [object.material]

      materials.forEach(material => material.dispose())
    }
  })

  renderer?.dispose()
  renderer?.domElement.remove()
})
</script>

<template>
  <div class="factory-card">
    <div class="factory-heading">
      <div>
        <h2>Gêmeo Digital 3D</h2>
        <p>Representação conectada ao simulador industrial</p>
      </div>

      <span class="live-status" :class="{ active: online }">
        {{ online ? 'Dados ao vivo' : 'Sem conexão' }}
      </span>
    </div>

    <div ref="container" class="factory-canvas"></div>

    <div class="factory-info">
      {{ selected }}
    </div>

    <div class="factory-legend">
      <span>🟢 Normal</span>
      <span>🟠 Temperatura elevada</span>
      <span>🔴 Temperatura crítica</span>
    </div>

    <p class="factory-note">
      Cores de temperatura ilustrativas; limites provisórios
      da visualização, não diagnóstico industrial.
    </p>
  </div>
</template>

<style scoped>
.factory-card {
  background: #141f31;
  border: 1px solid #26364c;
  border-radius: 16px;
  padding: 22px;
  margin-bottom: 32px;
}

.factory-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 15px;
  margin-bottom: 18px;
}

.factory-heading h2 {
  color: #e2e8f0;
  font-size: 19px;
  margin: 0 0 6px;
}

.factory-heading p,
.factory-note {
  color: #94a3b8;
  font-size: 12px;
  margin: 0;
}

.factory-canvas {
  width: 100%;
  height: 420px;
  overflow: hidden;
  border-radius: 12px;
  background: #101b2c;
  cursor: pointer;
}

.live-status {
  color: #fbbf24;
  background: #332318;
  padding: 8px 12px;
  border-radius: 20px;
  font-size: 12px;
  white-space: nowrap;
}

.live-status.active {
  color: #6ee7b7;
  background: #11352d;
}

.factory-info {
  margin-top: 14px;
  padding: 13px;
  border-radius: 9px;
  background: #0b1220;
  color: #cbd5e1;
  font-size: 13px;
}

.factory-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 15px;
  color: #94a3b8;
  font-size: 12px;
}

.factory-note {
  margin-top: 12px;
}

@media (max-width: 600px) {
  .factory-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .factory-canvas {
    height: 310px;
  }
}
</style>
