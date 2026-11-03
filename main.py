import asyncio
import math
import random
from js import window, document, Object, Array

# Three.js(3D 엔진)가 다 불러와질 때까지 기다린다
while getattr(window, "THREE", None) is None:
    await asyncio.sleep(0.05)

from pyodide.ffi import to_js, create_proxy
from pyscript import when

try:
    import textures as tx
    import campus_data as cd
    import floors as fl
    cd.LANDMARKS, cd.PARK, tx.LABEL_STYLES  # 새 버전 파일인지 확인
except Exception as e:
    document.querySelector("#loading").textContent = (
        f"파일 버전이 맞지 않아요 ({e}). Ctrl + F5 로 새로고침해 주세요.")
    raise

try:  # 이름표 글꼴(Pretendard)이 준비될 때까지 잠깐 기다린다
    await document.fonts.load("700 44px Pretendard")
except Exception:
    pass

THREE = window.THREE
rng = random.Random(42)
state = {"school": "전체", "selected": None, "hover": None, "labels": True}
pickables = Array.new()  # 클릭할 수 있는 층 메시들
floor_of = {}            # 메시 id → (건물, 층)


# ---------- 기본 도구 ----------
def js(o):
    return to_js(o, dict_converter=Object.fromEntries)


CX, CY = cd.CENTER


def wx(X):  # 캠퍼스 좌표(m) → 3D 좌표 (북쪽이 -z)
    return X - CX


def wz(Y):
    return -(Y - CY)


def rect_cs(r):
    x0, x1, y0, y1 = r
    return wx((x0 + x1) / 2), wz((y0 + y1) / 2), x1 - x0, y1 - y0


def expand(r, m):
    return (r[0] - m, r[1] + m, r[2] - m, r[3] + m)


def inside(r, X, Y):
    return r[0] <= X <= r[1] and r[2] <= Y <= r[3]


def overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1] and a[2] < b[3] and b[2] < a[3]


def in_poly(X, Y, poly):
    hit = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > Y) != (y2 > Y) and X < x1 + (Y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def seg_dist(X, Y, p, q):
    (x1, y1), (x2, y2) = p, q
    dx, dy = x2 - x1, y2 - y1
    t = max(0, min(1, ((X - x1) * dx + (Y - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(X - (x1 + t * dx), Y - (y1 + t * dy))


def line_dist(X, Y, pts):
    return min(seg_dist(X, Y, pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def poly_edge_dist(X, Y, poly):
    return min(seg_dist(X, Y, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def V3(x, y, z):
    return THREE.Vector3.new(x, y, z)


def std(color=None, map=None, rough=0.9, metal=0.0, **extra):
    o = {"roughness": rough, "metalness": metal, **extra}
    if color is not None:
        o["color"] = color
    if map is not None:
        o["map"] = map
    return THREE.MeshStandardMaterial.new(js(o))


# ---------- 렉 줄이기: 같은 재질끼리 모아서 한 번에 그린다 ----------
# 도로·인도·울타리·아파트처럼 움직이지 않는 것들은 모양을 모아 두었다가
# 마지막에 재질별로 하나로 합친다. 그림(텍스처)은 반복 횟수를 모양 쪽(UV)에 넣어서 공유한다.
batches = {}


def add_geo(key, mat, geo, cast=True):
    if key not in batches:
        batches[key] = {"mat": mat, "geos": [], "cast": cast}
    batches[key]["geos"].append(geo)


def flush_batches():
    for b in batches.values():
        merged = window.mergeGeometries(to_js(b["geos"]), False)
        m = THREE.Mesh.new(merged, b["mat"])
        m.castShadow = b["cast"]
        m.receiveShadow = True
        scene.add(m)
        for g in b["geos"]:
            g.dispose()
    batches.clear()


def scale_uv(geo, su, sv, first=0, count=None):
    uv = geo.attributes.uv
    end = uv.count if count is None else first + count
    for i in range(first, end):
        uv.setXY(i, uv.getX(i) * su, uv.getY(i) * sv)


def g_plane(rect, y, tile):
    x, z, w, d = rect_cs(rect)
    geo = THREE.PlaneGeometry.new(w, d)
    scale_uv(geo, w / tile, d / tile)
    geo.rotateX(-math.pi / 2)
    geo.translate(x, y, z)
    return geo


def g_seg(p, q, width, y, tile, offset=0.0, extend=0.0):
    """두 점 사이의 띠 모양 (비스듬한 도로·인도)"""
    (X0, Y0), (X1, Y1) = p, q
    dx, dy = X1 - X0, Y1 - Y0
    L = math.hypot(dx, dy)
    nx, ny = -dy / L, dx / L
    geo = THREE.PlaneGeometry.new(L + extend, width)
    scale_uv(geo, (L + extend) / tile, width / tile)
    geo.rotateX(-math.pi / 2)
    geo.rotateY(math.atan2(dy, dx))
    geo.translate(wx((X0 + X1) / 2 + nx * offset), y, wz((Y0 + Y1) / 2 + ny * offset))
    return geo


def g_box(x, y, z, w, h, d, rot=0.0):
    geo = THREE.BoxGeometry.new(w, h, d)
    if rot:
        geo.rotateY(rot)
    geo.translate(x, y, z)
    return geo


def facade_uv(geo, w, h, d, fh, roof_tile=10):
    """상자 옆면은 창문 칸(5m × 한 층) 수만큼, 윗면은 roof_tile m마다 반복"""
    for face, width in ((0, d), (1, d), (4, w), (5, w)):
        scale_uv(geo, max(1, round(width / 5)), max(1, round(h / fh)), face * 4, 4)
    for face in (2, 3):
        scale_uv(geo, w / roof_tile, d / roof_tile, face * 4, 4)


def plane(rect, mat, y):
    x, z, w, d = rect_cs(rect)
    m = THREE.Mesh.new(THREE.PlaneGeometry.new(w, d), mat)
    m.rotation.x = -math.pi / 2
    m.position.set(x, y, z)
    m.receiveShadow = True
    scene.add(m)
    return m


def shape_plane(points, mat, y):
    shape = THREE.Shape.new()
    for i, (X, Y) in enumerate(points):
        if i == 0:
            shape.moveTo(X - CX, Y - CY)
        else:
            shape.lineTo(X - CX, Y - CY)
    geo = THREE.ShapeGeometry.new(shape)
    geo.rotateX(-math.pi / 2)
    m = THREE.Mesh.new(geo, mat)
    m.position.y = y
    m.receiveShadow = True
    scene.add(m)
    return m


def box(x, y, z, w, h, d, mat, cast=True, parent=None, rot=0.0):
    m = THREE.Mesh.new(THREE.BoxGeometry.new(w, h, d), mat)
    m.position.set(x, y, z)
    m.rotation.y = rot
    m.castShadow = cast
    m.receiveShadow = True
    (parent or scene).add(m)
    return m


def cyl(x, y, z, r, h, mat, seg=12, r_top=None, parent=None):
    m = THREE.Mesh.new(THREE.CylinderGeometry.new(r if r_top is None else r_top, r, h, seg), mat)
    m.position.set(x, y, z)
    m.castShadow = True
    m.receiveShadow = True
    (parent or scene).add(m)
    return m


def instanced(geo, mat, transforms, colors=None):
    """같은 물건 여러 개를 한 번에: transforms = [(x, y, z, 회전, sx, sy, sz)]"""
    mesh = THREE.InstancedMesh.new(geo, mat, max(1, len(transforms)))
    mesh.count = len(transforms)
    d3 = THREE.Object3D.new()
    c3 = THREE.Color.new()
    for i, (x, y, z, rot, sx, sy, sz) in enumerate(transforms):
        d3.position.set(x, y, z)
        d3.rotation.set(0, rot, 0)
        d3.scale.set(sx, sy, sz)
        d3.updateMatrix()
        mesh.setMatrixAt(i, d3.matrix)
        if colors:
            c3.set(colors[i])
            mesh.setColorAt(i, c3)
    mesh.instanceMatrix.needsUpdate = True
    if colors and mesh.instanceColor:
        mesh.instanceColor.needsUpdate = True
    mesh.castShadow = True
    mesh.receiveShadow = True
    scene.add(mesh)
    return mesh


# ---------- 렌더러, 카메라, 하늘, 햇빛 ----------
def fail(msg):
    el = document.querySelector("#loading")
    el.textContent = msg
    raise SystemExit(msg)


def make_renderer():
    """3D 화면을 만든다. 안 되면 설정을 낮춰서 다시 시도한다."""
    errors = []
    try:
        safe_start = "safe=1" in str(window.location.search)
    except Exception:
        safe_start = False
    first = {"antialias": False} if safe_start else {"antialias": True, "powerPreference": "high-performance"}
    for opts in (first,
                 {"antialias": False},
                 {"antialias": False, "precision": "mediump", "failIfMajorPerformanceCaveat": False}):
        try:
            return THREE.WebGLRenderer.new(js(opts)), errors
        except Exception as e:
            errors.append(str(e))
    return None, errors


view = document.querySelector("#view")
renderer, render_errors = make_renderer()
if renderer is None:
    fail("이 브라우저에서 3D(WebGL)를 켤 수 없어요.\n"
         "브라우저가 그래픽카드 보호를 위해 3D를 잠시 막은 상태일 수 있어요.\n\n"
         "① 브라우저 창을 전부 닫고 (작업표시줄 오른쪽 아래 아이콘까지) 다시 열어 주세요.\n"
         "② 그래도 안 되면 컴퓨터를 다시 시작해 주세요.\n\n"
         f"(원인: {render_errors[-1][:150] if render_errors else '알 수 없음'})")
gl = renderer.getContext()
ext = gl.getExtension("WEBGL_debug_renderer_info")
gpu = str(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL if ext else gl.RENDERER))
SOFTWARE_GPU = ("swiftshader", "llvmpipe", "software", "basic render")
LITE = "lite=1" in str(window.location.search) or any(k in gpu.lower() for k in SOFTWARE_GPU)
# 안전 모드: 그래픽카드가 3D를 멈춘 적이 있으면 다음부터 자동으로 가장 가볍게
try:
    SAFE = "safe=1" in str(window.location.search) or window.localStorage.getItem("campus3d_safe") == "1"
except Exception:
    SAFE = "safe=1" in str(window.location.search)
try:  # 진짜 원인(해상도 바꾸기)을 고쳤으니, 예전에 저장된 안전 모드 표시는 지운다
    if "safe=1" not in str(window.location.search):
        window.localStorage.removeItem("campus3d_safe")
        SAFE = False
except Exception:
    pass
LITE = LITE or SAFE
if LITE:
    document.querySelector("#mode").textContent = "안전 모드" if SAFE else "가벼운 모드"

# 멈춰 있을 때는 선명하게, 움직이는 동안만 해상도를 낮춰서 부드럽게
HI_DPR = 1 if SAFE else min(max(window.devicePixelRatio, 1.25), 1.5 if LITE else 2)  # 이보다 높이면 일부 그래픽카드에서 3D가 멈춘다
LO_DPR = 0.7 if SAFE else max(0.8, HI_DPR * 0.6)
res = {"cur": HI_DPR, "last": 0.0}
renderer.setPixelRatio(HI_DPR)
renderer.setSize(view.clientWidth, view.clientHeight)
# 기본 모드: 진짜 그림자를 한 번만 계산해 두고 계속 쓴다 (건물이 안 움직이니까)
# 가벼운 모드: 진짜 그림자는 끄고, 바닥에 그려 넣은 그림자를 쓴다 (그래픽카드 부담 거의 없음)
renderer.shadowMap.enabled = not LITE
renderer.shadowMap.type = THREE.PCFSoftShadowMap
renderer.shadowMap.autoUpdate = False
renderer.toneMapping = THREE.ACESFilmicToneMapping
renderer.toneMappingExposure = 0.62 if LITE else 0.55
view.appendChild(renderer.domElement)
MAX_ANISO = 1 if SAFE else min(8, renderer.capabilities.getMaxAnisotropy())


def on_context_lost(ev):
    ev.preventDefault()
    if not SAFE:  # 처음 멈췄으면 안전 모드로 자동으로 다시 열기
        try:
            window.localStorage.setItem("campus3d_safe", "1")
        except Exception:
            pass
        window.location.replace("?lite=1&safe=1")
        return
    document.querySelector("#lost").style.display = "grid"


renderer.domElement.addEventListener("webglcontextlost", create_proxy(on_context_lost))

scene = THREE.Scene.new()
scene.fog = THREE.Fog.new(0xdce4ea, 420, 1100)

camera = THREE.PerspectiveCamera.new(40, view.clientWidth / view.clientHeight, 2, 7000)
camera.position.set(-150, 140, 190)
controls = window.MapControls.new(camera, renderer.domElement)  # 지도 앱처럼: 왼쪽 드래그 이동, 오른쪽 드래그 회전
controls.enableDamping = True
controls.dampingFactor = 0.1
controls.screenSpacePanning = False
controls.zoomToCursor = False
controls.enableRotate = True  # 오른쪽 드래그 / 두 손가락으로 돌리기
controls.rotateSpeed = 0.6
controls.listenToKeyEvents(window)  # 키보드 방향키로 이동
controls.keyPanSpeed = 25
controls.maxPolarAngle = math.pi * 0.47
controls.minDistance = 8
controls.maxDistance = 520
controls.target.set(0, 0, 0)

sky = window.Sky.new()
sky.scale.setScalar(5000)
u = sky.material.uniforms
u.turbidity.value = 6
u.rayleigh.value = 1.2
u.mieCoefficient.value = 0.005
u.mieDirectionalG.value = 0.82
sun = V3(0, 0, 0)
sun.setFromSphericalCoords(1, THREE.MathUtils.degToRad(90 - 33), THREE.MathUtils.degToRad(35))
u.sunPosition.value.copy(sun)
if not LITE:  # 하늘 빛을 건물에 반사시키는 효과
    pmrem = THREE.PMREMGenerator.new(renderer)
    env_scene = THREE.Scene.new()
    env_scene.add(sky)
    scene.environment = pmrem.fromScene(env_scene).texture
scene.add(sky)

scene.add(THREE.HemisphereLight.new(0xe6eef7, 0x6b6a58, 1.15 if LITE else 0.4))
sunlight = THREE.DirectionalLight.new(0xffeedd, 2.8)
sunlight.position.copy(sun).multiplyScalar(380)
sunlight.castShadow = not LITE
sunlight.shadow.mapSize.set(4096, 4096)
sc = sunlight.shadow.camera
sc.left, sc.right, sc.top, sc.bottom = -170, 170, 170, -170
sc.near, sc.far = 10, 1000
sunlight.shadow.bias = -0.0004
sunlight.shadow.normalBias = 0.9
scene.add(sunlight)
scene.add(sunlight.target)


def tile_mat(tex, **kw):
    """UV로 반복하는 공유 재질"""
    tex.anisotropy = MAX_ANISO
    return std(map=tex, **kw)


# ---------- 바닥 ----------
grass_tex = tx.grass("#6a8f4a")
grass_mat = tile_mat(grass_tex)
paver_mat = tile_mat(tx.pavers("#c4c0b7", "rgba(0,0,0,0.08)"))
asphalt_mat = tile_mat(tx.asphalt(), rough=0.95)
concrete_mat = tile_mat(tx.concrete(), rough=0.95)
walk_mat = tile_mat(tx.pavers("#bdb2a6", "rgba(0,0,0,0.10)", 4))
dirt_mat = tile_mat(tx.dirt())

# 학교 밖은 비우고, 학교 땅만 두께 있는 받침대(모형처럼)로 만든다
base_shape = THREE.Shape.new()
for i, (X, Y) in enumerate(cd.CAMPUS):
    if i == 0:
        base_shape.moveTo(X - CX, Y - CY)
    else:
        base_shape.lineTo(X - CX, Y - CY)
base_geo = THREE.ExtrudeGeometry.new(base_shape, js({"depth": 4, "bevelEnabled": False}))
base_geo.rotateX(-math.pi / 2)
base_geo.translate(0, -4, 0)
base_mesh = THREE.Mesh.new(base_geo, std(color="#8f8068", rough=0.95))
base_mesh.receiveShadow = True
scene.add(base_mesh)

# 학교 안은 잔디 바탕 (모양 그대로)
shape = THREE.Shape.new()
for i, (X, Y) in enumerate(cd.CAMPUS):
    if i == 0:
        shape.moveTo(X - CX, Y - CY)
    else:
        shape.lineTo(X - CX, Y - CY)
campus_geo = THREE.ShapeGeometry.new(shape)
scale_uv(campus_geo, 1 / 6, 1 / 6)
campus_geo.rotateX(-math.pi / 2)
campus_geo.translate(0, 0.04, 0)
add_geo("grass", grass_mat, campus_geo, cast=False)

paved = [expand(b["rect"], 4) for b in cd.BUILDINGS if b["floors"] >= 2]
paved += [cd.LANE, cd.PARKING, cd.BACK_PATH]  # 후문에서 운동장으로 가는 길 (위성사진)
for r in paved:
    add_geo("paver", paver_mat, g_plane(r, 0.07, 2), cast=False)

G = cd.GARDEN
garden_paths = [((G[0] + G[1]) / 2 - 1.3, (G[0] + G[1]) / 2 + 1.3, G[2], G[3]),
                (G[0], G[1], (G[2] + G[3]) / 2 - 1.3, (G[2] + G[3]) / 2 + 1.3)]
for r in garden_paths:
    add_geo("paver", paver_mat, g_plane(r, 0.1, 2), cast=False)


tz0, tz1 = cd.TOWER_ZONE
tz_poly = None

# 그림이 하나뿐인 바닥들 (운동장, 중정 등)
fw, fd = cd.FIELD[1] - cd.FIELD[0], cd.FIELD[3] - cd.FIELD[2]
plane(cd.FIELD, tile_mat(tx.soccer_field(fw, fd)), 0.1)
plane(cd.COURT, tile_mat(tx.basketball_court(cd.COURT[1] - cd.COURT[0], cd.COURT[3] - cd.COURT[2]), rough=0.7), 0.13)
plane(cd.PARKING, tile_mat(tx.parking(cd.PARKING[1] - cd.PARKING[0], cd.PARKING[3] - cd.PARKING[2]),
                           rough=0.95), 0.1)
plane(cd.PLAZA, tile_mat(tx.plaza(cd.PLAZA[1] - cd.PLAZA[0])), 0.1)


# ---------- 학교 둘레 도로 (위성사진 모양) ----------
# 길 하나를 조각 없이 이어진 띠 하나로 만든다 (꺾이는 곳도 겹치지 않게)
from js import Float32Array

line_mat = std(color="#e3c04a", rough=0.8)
white_line_mat = std(color="#ecebe6", rough=0.8)
earth_mat = std(color="#8f8068", rough=0.95, side=THREE.DoubleSide)
for _m in (asphalt_mat, walk_mat, line_mat):
    _m.side = THREE.DoubleSide  # 띠는 앞뒤 어느 쪽에서도 보이게


def ribbon(pts, d0, d1, y, tile):
    """꺾은선 pts를 따라 왼쪽 d0~d1 m 사이를 채운 띠 (모서리는 이어 붙임)"""
    a, b = cd.offset_line(pts, d0), cd.offset_line(pts, d1)
    pos, uv, idx = [], [], []
    s = 0.0
    for i in range(len(pts)):
        if i:
            s += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        for p, v in ((a[i], 0), (b[i], abs(d1 - d0))):
            pos += [wx(p[0]), y, wz(p[1])]
            uv += [s / tile, v / tile]
    for i in range(len(pts) - 1):
        k = i * 2
        idx += [k, k + 2, k + 1, k + 1, k + 2, k + 3]
    geo = THREE.BufferGeometry.new()
    geo.setAttribute("position", THREE.BufferAttribute.new(Float32Array.new(to_js(pos)), 3))
    geo.setAttribute("uv", THREE.BufferAttribute.new(Float32Array.new(to_js(uv)), 2))
    geo.setIndex(to_js(idx))
    geo.computeVertexNormals()
    return geo


def wall_strip(pts, d, y0, y1):
    """받침대 옆면 (띠 가장자리에서 아래로)"""
    line = cd.offset_line(pts, d)
    pos, uv, idx = [], [], []
    for i, p in enumerate(line):
        pos += [wx(p[0]), y1, wz(p[1]), wx(p[0]), y0, wz(p[1])]
        uv += [i, 1, i, 0]
    for i in range(len(line) - 1):
        k = i * 2
        idx += [k, k + 1, k + 2, k + 2, k + 1, k + 3]
    geo = THREE.BufferGeometry.new()
    geo.setAttribute("position", THREE.BufferAttribute.new(Float32Array.new(to_js(pos)), 3))
    geo.setAttribute("uv", THREE.BufferAttribute.new(Float32Array.new(to_js(uv)), 2))
    geo.setIndex(to_js(idx))
    geo.computeVertexNormals()
    return geo


def trimmed(road_i, end, by):
    """곁길이 큰길과 만나는 끝을 by m 만큼 당긴 꺾은선"""
    pts = list(road_lines[road_i])  # 앞에서 이미 당긴 끝은 그대로 두고
    if end == 0:
        (x0, y0), (x1, y1) = pts[0], pts[1]
    else:
        (x0, y0), (x1, y1) = pts[-1], pts[-2]
    L = math.hypot(x1 - x0, y1 - y0)
    p = (x0 + (x1 - x0) * by / L, y0 + (y1 - y0) * by / L)
    if end == 0:
        pts[0] = p
    else:
        pts[-1] = p
    return pts


road_lines = [list(r["pts"]) for r in cd.ROADS]
for side_i, end, main_i in cd.JOINS:  # 곁길은 큰길 인도 바깥에서 멈추고, 입구만 아스팔트로 잇는다
    road_lines[side_i] = trimmed(side_i, end, cd.ROADS[main_i]["w"] / 2 + 3)

for i, road in enumerate(cd.ROADS):
    pts, w = road_lines[i], road["w"]
    half = w / 2
    add_geo("asphalt", asphalt_mat, ribbon(pts, -half, half, 0.05, 10), cast=False)
    for sgn in (1, -1):
        add_geo("walk", walk_mat, ribbon(pts, sgn * half, sgn * (half + 3), 0.15, 2), cast=False)
        add_geo("earth", earth_mat, wall_strip(pts, sgn * (half + 3), -4, 0.15), cast=False)
    if w >= 14:  # 큰 길: 가운데 노란 겹선
        for off in (-0.25, 0.1):
            add_geo("yellow", line_mat, ribbon(pts, off, off + 0.15, 0.08, 1), cast=False)
    else:
        add_geo("yellow", line_mat, ribbon(pts, -0.08, 0.08, 0.08, 1), cast=False)
    add_geo("earth", earth_mat, ribbon(pts, -half - 3, half + 3, -4, 10), cast=False)  # 받침 바닥

for side_i, end, main_i in cd.JOINS:  # 교차로 입구: 큰길 쪽 인도를 덮는 아스팔트
    full = cd.ROADS[side_i]["pts"]
    a = full[0] if end == 0 else full[-1]
    b = road_lines[side_i][0] if end == 0 else road_lines[side_i][-1]
    add_geo("asphalt", asphalt_mat, ribbon([a, b], -cd.ROADS[side_i]["w"] / 2, cd.ROADS[side_i]["w"] / 2, 0.17, 10),
            cast=False)


def crosswalk(road, X, Y):
    """정문·후문 앞 횡단보도 (흰 줄무늬)"""
    pts, w = road["pts"], road["w"]
    best = min(range(len(pts) - 1), key=lambda i: seg_dist(X, Y, pts[i], pts[i + 1]))
    (X0, Y0), (X1, Y1) = pts[best], pts[best + 1]
    L = math.hypot(X1 - X0, Y1 - Y0)
    ux, uy = (X1 - X0) / L, (Y1 - Y0) / L
    t = (X - X0) * ux + (Y - Y0) * uy
    rot = math.atan2(uy, ux)
    for k in range(-4, 5):
        px, py = X0 + ux * (t + k * 1.0), Y0 + uy * (t + k * 1.0)
        add_geo("white", white_line_mat, g_box(wx(px), 0.09, wz(py), 0.5, 0.04, w - 1, rot), cast=False)


crosswalk(cd.ROADS[2], *cd.GATES[0])   # 후문 앞 (염화로)
crosswalk(cd.ROADS[0], *cd.GATES[1])   # 정문 앞 (화정로)


# ---------- 울타리와 문 ----------
wall_mat = std(color="#bdb8af", rough=0.9)
fence_mat = std(map=tx.iron_fence(), rough=0.5, metal=0.4, alphaTest=0.5, side=THREE.DoubleSide)
post_mat = std(color="#2e3a33", rough=0.5, metal=0.4)
fence_posts = []
gate_brick = tile_mat(tx.facade("brick", 2.6, "brick_plain"), rough=0.9)
steel_mat = std(color="#9aa0a6", rough=0.4, metal=0.6)
gate_iron = std(color="#1d1f22", rough=0.5, metal=0.5, transparent=True, opacity=0.85)


def fence_edge(p, q):
    (X0, Y0), (X1, Y1) = p, q
    L = math.hypot(X1 - X0, Y1 - Y0)
    ux, uy = (X1 - X0) / L, (Y1 - Y0) / L
    rot = math.atan2(Y1 - Y0, X1 - X0)
    gaps = []
    for gx, gy in cd.GATES:
        if seg_dist(gx, gy, p, q) < 3:
            t = (gx - X0) * ux + (gy - Y0) * uy
            gaps.append((t - 7, t + 7))
            for e in (t - 7, t + 7):
                add_geo("gate_brick", gate_brick, g_box(wx(X0 + ux * e), 1.3, wz(Y0 + uy * e), 1.1, 2.6, 1.1))
                add_geo("steel", steel_mat, THREE.CylinderGeometry.new(0.12, 0.12, 6, 8).translate(
                    wx(X0 + ux * e), 3, wz(Y0 + uy * e)))
            gx_, gz_ = wx(X0 + ux * t), wz(Y0 + uy * t)
            add_geo("steel", steel_mat, g_box(gx_, 6, gz_, 14, 0.15, 0.15, rot))   # 아치 위쪽
            add_geo("steel", steel_mat, g_box(gx_, 5.2, gz_, 14, 0.12, 0.12, rot))
            for k in range(-6, 7, 2):
                add_geo("steel", steel_mat, g_box(gx_ + math.cos(rot) * k, 5.6, gz_ - math.sin(rot) * k,
                                                  0.08, 0.8, 0.08, rot))
            add_geo("gate_iron", gate_iron, g_box(gx_, 0.9, gz_, 12.8, 1.8, 0.06, rot), cast=False)
    segs, start = [], 0
    for g0, g1 in sorted(gaps):
        segs.append((start, g0))
        start = g1
    segs.append((start, L))
    for s0, s1 in segs:
        if s1 - s0 <= 0.5:
            continue
        m = (s0 + s1) / 2
        x, z = wx(X0 + ux * m), wz(Y0 + uy * m)
        add_geo("wall", wall_mat, g_box(x, 0.3, z, s1 - s0, 0.6, 0.35, rot))
        fg = THREE.BoxGeometry.new(s1 - s0, 1.6, 0.04)
        scale_uv(fg, s1 - s0, 1)  # 1m마다 살 8개
        fg.rotateY(rot)
        fg.translate(x, 1.4, z)
        add_geo("fence", fence_mat, fg, cast=False)
        k = s0
        while k <= s1:
            fence_posts.append((wx(X0 + ux * k), 1.1, wz(Y0 + uy * k), 0, 1, 1, 1))
            k += 3


for i in range(len(cd.CAMPUS)):
    fence_edge(cd.CAMPUS[i], cd.CAMPUS[(i + 1) % len(cd.CAMPUS)])
instanced(THREE.BoxGeometry.new(0.08, 2.2, 0.08), post_mat, fence_posts)


# ---------- 이름표 ----------
LABEL_SIZE = {"building": 0.03, "place": 0.026, "road": 0.026, "gate": 0.026, "bus": 0.024}
landmark_labels = []


def make_label(text, style, x, y, z):
    """화면에서 항상 같은 크기로 보이는 이름표"""
    tex, aspect = tx.label(text, style)
    tex.anisotropy = MAX_ANISO
    mat = THREE.SpriteMaterial.new(js({"map": tex, "depthTest": False, "transparent": True,
                                       "sizeAttenuation": False}))
    spr = THREE.Sprite.new(mat)
    h = LABEL_SIZE[style]
    spr.scale.set(h * aspect, h, 1)
    spr.center.set(0.5, 0)  # 아래쪽 가운데를 그 지점에 맞춘다
    spr.position.set(x, y, z)
    spr.renderOrder = 10
    scene.add(spr)
    return spr


# ---------- 학교 건물 ----------
roof_tex = tx.roof_concrete()
solar_mat = tile_mat(tx.solar_panel(), rough=0.3, metal=0.45)
solar_geo = THREE.BoxGeometry.new(1.8, 0.06, 1.1)
unit_mat = std(color="#d9dbd8", rough=0.6, metal=0.2)


def glow(mats, color, strength):
    out = []
    for m in mats:
        c = m.clone()
        c.emissive = THREE.Color.new(color)
        c.emissiveIntensity = strength
        out.append(c)
    return to_js(out)


def solar_spots(x, z, w, d, tower):
    spots = []
    px = x - w / 2 + 2.5
    while px <= x + w / 2 - 2.5:
        pz = z - d / 2 + 2.2
        while pz <= z + d / 2 - 2.2:
            if not (tower and abs(px - tower[0]) < tower[2] / 2 + 1.5
                    and abs(pz - tower[1]) < tower[3] / 2 + 1.5):
                spots.append((px, pz))
            pz += 2.0
        px += 2.0
    return spots


def drawing_to_campus(b, plan, x0, x1, y0, y1):
    """도면 위 사각형(m) → 캠퍼스 좌표 사각형. 도면 전체를 건물 크기에 비율로 맞춘다."""
    X0, X1, Y0, Y1 = b["rect"]
    W, D, o = plan["W"], plan["D"], plan["orient"]
    pts = []
    for xd, yd in ((x0, y0), (x1, y1)):
        if o == "rot0":
            pts.append((X0 + xd / W * (X1 - X0), Y1 - yd / D * (Y1 - Y0)))
        elif o == "rot180":
            pts.append((X1 - xd / W * (X1 - X0), Y0 + yd / D * (Y1 - Y0)))
        elif o == "rot90":
            pts.append((X0 + yd / D * (X1 - X0), Y0 + xd / W * (Y1 - Y0)))
        else:
            pts.append((X1 - yd / D * (X1 - X0), Y1 - xd / W * (Y1 - Y0)))
    (ax, ay), (bx, by) = pts
    return (min(ax, bx), max(ax, bx), min(ay, by), max(ay, by))


def building_parts(b):
    """건물 바닥 모양 = 사각형 여러 개 (도면의 튀어나온 코어·계단·날개 포함)"""
    plan = fl.PLANS.get(b["id"])
    if not plan or "parts" not in plan:
        return [b["rect"]]
    return [drawing_to_campus(b, plan, *p) for p in plan["parts"]]


def add_building(b):
    fh, n = b["floor_h"], b["floors"]
    brick = b["wall"] in tx.BRICKS
    style = b.get("style", "brick" if brick else "school")
    wall = tile_mat(tx.facade(b["wall"], fh, style), rough=0.85)
    if style in ("gym", "brick_gym"):
        roof = tile_mat(tx.metal_roof(b["roof"]), rough=0.45, metal=0.35)
        roof_tile = 4
    else:
        roof = std(map=roof_tex, color=b["roof"] if b["roof"] != "#a3a6a2" else None, rough=0.9)
        roof_tile = 10
    b["mats"] = [wall, roof]
    b["mats_js"] = to_js([wall, wall, roof, roof, wall, wall])
    hl = glow([wall, roof], 0xff8c00, 0.8)     # 선택한 층
    hv = glow([wall, roof], 0xffffff, 0.12)    # 마우스 올린 층
    b["hl_js"] = to_js([hl[0], hl[0], hl[1], hl[1], hl[0], hl[0]])
    b["hv_js"] = to_js([hv[0], hv[0], hv[1], hv[1], hv[0], hv[0]])
    b["meshes"], b["extras"] = [], []
    b["parts"] = building_parts(b)
    for f in range(n):
        geos = []
        for r in b["parts"]:
            px, pz, pw, pd = rect_cs(r)
            geo = THREE.BoxGeometry.new(pw, fh, pd)
            facade_uv(geo, pw, fh, pd, fh, roof_tile)
            geo.translate(px, fh * f + fh / 2, pz)
            geos.append(geo)
        merged = window.mergeGeometries(to_js(geos), False)
        merged.clearGroups()  # 조각마다 6개 면(벽 4·지붕·바닥)에 재질 번호를 다시 붙인다
        for k in range(len(geos)):
            for j in range(6):
                merged.addGroup(k * 36 + j * 6, 6, j)
        m = THREE.Mesh.new(merged, b["mats_js"])
        m.castShadow = True
        m.receiveShadow = True
        scene.add(m)
        pickables.push(m)
        floor_of[m.id] = (b, f + 1)
        b["meshes"].append(m)

    # 옥상 난간: 모양 조각마다
    top = fh * n
    trim = std(color=b.get("trim", "#cfc9bf" if brick else b["wall"]), rough=0.9)
    b["trim"] = trim
    rails = []
    t, ph = 0.3, 0.8
    for r in b["parts"]:
        px, pz, pw, pd = rect_cs(r)
        for qx, qz, qw, qd in ((px, pz - pd / 2 + t / 2, pw, t), (px, pz + pd / 2 - t / 2, pw, t),
                               (px - pw / 2 + t / 2, pz, t, pd), (px + pw / 2 - t / 2, pz, t, pd)):
            rails.append(g_box(qx, top + ph / 2, qz, qw, ph, qd))
    m = THREE.Mesh.new(window.mergeGeometries(to_js(rails), False), trim)
    m.castShadow = True
    m.receiveShadow = True
    scene.add(m)
    b["extras"].append(m)

    big = max(b["parts"], key=lambda r: (r[1] - r[0]) * (r[3] - r[2]))
    bx, bz, bw, bd = rect_cs(big)
    if b["id"] in cd.SOLAR:  # 위성사진: 옥상 태양광
        spots = []
        for r in b["parts"]:
            px, pz, pw, pd = rect_cs(r)
            if pw > 6 and pd > 6:
                spots += solar_spots(px, pz, pw, pd, None)
        b["extras"].append(instanced(solar_geo, solar_mat, [(sx, top + 0.6, sz, 0, 1, 1, 1) for sx, sz in spots]))
    x, z, _, _ = rect_cs(b["rect"])
    b["label"] = make_label(b["name"], "building", bx, top + 3, bz)


solar_geo.rotateX(-0.26)  # 태양광 패널은 남쪽으로 15도 기울어져 있다
for b in cd.BUILDINGS:
    add_building(b)

banner = THREE.Mesh.new(THREE.PlaneGeometry.new(4.5, 9), std(map=tx.banner(), rough=0.8, side=THREE.DoubleSide))
banner.rotation.y = math.pi / 2
banner.position.set(wx(50.4) + 0.08, 8.5, wz(56))
scene.add(banner)

LABEL_HEIGHT = {"road": 1, "gate": 4, "bus": 4, "place": 14}
for name, LX, LY, kind in cd.LANDMARKS:
    landmark_labels.append(make_label(name, kind, wx(LX), LABEL_HEIGHT[kind], wz(LY)))

glass_mat = tile_mat(tx.facade("#f1f1ee", 3.8, "glass"), rough=0.6)
for r in cd.CORRIDORS:
    x, z, w, d = rect_cs(r)
    geo = g_box(0, 0, 0, w, 3.8, d)
    facade_uv(geo, w, 3.8, d, 3.8)
    geo.translate(x, 5.5, z)
    add_geo("glass", glass_mat, geo)
    add_geo("wall", wall_mat, g_box(x, 1.8, z, 0.7, 3.6, 0.7))


# ---------- 운동장 시설 ----------
white = std(color="#f4f4f4", rough=0.4, metal=0.3)
net = std(color="#ffffff", rough=0.9, transparent=True, opacity=0.18, side=THREE.DoubleSide)
F = cd.FIELD
fcx, fcy = (F[0] + F[1]) / 2, (F[2] + F[3]) / 2
for gy, out in ((fcy - tx.PITCH_L / 2, -1), (fcy + tx.PITCH_L / 2, 1)):
    for px in (fcx - 3.66, fcx + 3.66):
        add_geo("white", white, THREE.CylinderGeometry.new(0.07, 0.07, 2.44, 8).translate(wx(px), 1.22, wz(gy)))
    add_geo("white", white, g_box(wx(fcx), 2.44, wz(gy), 7.4, 0.12, 0.12))
    add_geo("net", net, g_box(wx(fcx), 1.22, wz(gy + out * 1), 7.32, 2.44, 2), cast=False)

# 운동장 서쪽 스탠드 (위성사진의 흰 지붕 줄)
stand_mat = std(color="#d9d6ce", rough=0.85)
sx, sz, sw, sd = rect_cs(cd.STANDS)
for i in range(4):
    add_geo("stand", stand_mat, g_box(sx - sw / 2 + 0.5 + i * 0.9, 0.3 + i * 0.45, sz, 0.9, 0.6 + i * 0.9, sd))
add_geo("white", white, g_box(sx, 4.2, sz, sw + 1.5, 0.2, sd))
for k in range(0, int(sd), 10):
    add_geo("post", post_mat, THREE.CylinderGeometry.new(0.1, 0.1, 4.2, 8).translate(sx - sw / 2, 2.1, sz - sd / 2 + k))

C_ = cd.COURT  # 농구 골대 (코트 양 끝)
for gx_ in (C_[0] + 1.2, C_[1] - 1.2):
    cyl(wx(gx_), 1.7, wz((C_[2] + C_[3]) / 2), 0.09, 3.4, post_mat, 8)
    box(wx(gx_ + (0.9 if gx_ < (C_[0] + C_[1]) / 2 else -0.9)), 3.4, wz((C_[2] + C_[3]) / 2), 0.05, 1.05, 1.8,
        std(color="#ffffff", rough=0.3))

pcx, pcz, _, _ = rect_cs(cd.PLAZA)
stone = std(color="#cfc9bd", rough=0.85)
water = std(color="#5b93b0", rough=0.08, metal=0.3)
cyl(pcx, 0.3, pcz, 6.5, 0.5, stone, 32)   # 중정 가운데 둥근 화단 (큰 나무가 서 있다)
cyl(pcx, 0.32, pcz, 6.0, 0.52, std(color="#5d7a3e", rough=0.95), 32)

flag_mat = std(map=tx.flag_korea(), rough=0.8, side=THREE.DoubleSide)
school_flag = std(color="#1f4e8c", rough=0.8, side=THREE.DoubleSide)
for i, fm in enumerate((school_flag, flag_mat, school_flag)):
    fx, fy = 58 + i * 4, -30
    add_geo("white", white, THREE.CylinderGeometry.new(0.07, 0.07, 10, 8).translate(wx(fx), 5, wz(fy)))
    f = THREE.Mesh.new(THREE.PlaneGeometry.new(1.8, 1.2), fm)
    f.position.set(wx(fx) + 0.95, 9.3, wz(fy))
    f.castShadow = True
    scene.add(f)


# ---------- 학교 주변 건물 ----------
APT_COLORS = ["#ece8e1", "#e3ded6", "#efece6", "#dedad3"]
apt_mats = {c: tile_mat(tx.facade(c, 2.9, "apt"), rough=0.85) for c in APT_COLORS}
apt_roof = std(color="#a6a7a3", rough=0.9)
school2_mat = tile_mat(tx.facade("#ebe4d7", 3.6, "school"), rough=0.85)


def facade_block(key, mat, x, z, w, h, d, fh, rot=0.0, y_base=0.0):
    geo = THREE.BoxGeometry.new(w, h, d)
    facade_uv(geo, w, h, d, fh, 1000)  # 윗면은 거의 벽색 하나로
    if rot:
        geo.rotateY(rot)
    geo.translate(x, y_base + h / 2, z)
    add_geo(key, mat, geo)
    # 옥상 슬래브 (벽보다 살짝 크게 덮어서 지붕색으로)
    add_geo("apt_roof", apt_roof, g_box(x, y_base + h + 0.15, z, w + 0.3 if not rot else w + 0.3, 0.3,
                                        d + 0.3, rot))


for TX_, TY_, h in cd.TOWERS:  # Y자 고층 아파트: 날개 3개
    color = rng.choice(APT_COLORS)
    base_rot = rng.uniform(0, 2.1)
    for k in range(3):
        a = base_rot + k * math.tau / 3
        facade_block(color, apt_mats[color], wx(TX_ + math.cos(a) * 9), wz(TY_ + math.sin(a) * 9),
                     18, h, 11, 2.9, rot=a)
    add_geo("apt_roof", apt_roof, g_box(wx(TX_), h + 2, wz(TY_), 8, 4, 8))
for s0, s1, t0, t1, h in cd.SLABS:
    color = rng.choice(APT_COLORS)
    x, z, w, d = rect_cs((s0, s1, t0, t1))
    facade_block(color, apt_mats[color], x, z, w, h, d, 2.9)
    add_geo("apt_roof", apt_roof, g_box(x, h + 1.4, z, min(w, 8), 2.8, min(d, 6)))
for s0, s1, t0, t1, h in cd.OTHER_SCHOOL:
    x, z, w, d = rect_cs((s0, s1, t0, t1))
    facade_block("school2", school2_mat, x, z, w, h, d, 3.6)

# 주택가: 학교·도로·아파트를 피해서 빈 땅을 집으로 채운다 (위성사진처럼 빽빽하게)
no_house = [expand((s0, s1, t0, t1), 8) for s0, s1, t0, t1, _ in cd.SLABS]
no_house += [expand(r[:4], 6) for r in cd.OTHER_SCHOOL] + [expand(cd.OTHER_FIELD, 4), expand(cd.PARK, 3)]
no_house += [(tx_ - 26, tx_ + 26, ty_ - 26, ty_ + 26) for tx_, ty_, _ in cd.TOWERS]


def house_ok(r):
    x0, x1, y0, y1 = r
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    for X, Y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1), (mx, my)):
        if in_poly(X, Y, cd.CAMPUS):
            return False
    if poly_edge_dist(mx, my, cd.CAMPUS) < 9:
        return False
    for road in cd.ROADS:
        if line_dist(mx, my, road["pts"]) < road["w"] / 2 + 3 + 5:
            return False
    if cd.TOWER_ZONE[0] < mx < cd.TOWER_ZONE[1] and my > cd.north_road_y(mx) + 14:
        return False
    return not any(overlaps(r, nb) for nb in no_house)


houses = []  # 학교만 보기: 주변 집은 만들지 않음

unit_geo = THREE.BoxGeometry.new(1, 1, 1)
unit_geo.translate(0, 0.5, 0)
tank_geo = THREE.CylinderGeometry.new(0.7, 0.7, 1.4, 10)
tank_geo.translate(0, 0.7, 0)
WALLS = ["#ece7de", "#e2dacd", "#d8cebf", "#d0c9bf", "#e6e3dc", "#d6c0ad", "#cbbba8"]
ROOFS = ["#6d9078"] * 4 + ["#6a908c"] * 2 + ["#7189a6"] * 2 + ["#9a6c5e", "#9c9e9a", "#9c9e9a"]
body_t, roof_t, tank_t = [], [], []
body_c, roof_c, tank_c = [], [], []
for r, h in houses:
    x, z, w, d = rect_cs(r)
    body_t.append((x, 0, z, 0, w, h, d))
    body_c.append(rng.choice(WALLS))
    roof_t.append((x, h, z, 0, w - 0.3, 0.3, d - 0.3))
    roof_c.append(rng.choice(ROOFS))
    if rng.random() < 0.4:
        tank_t.append((x + w * 0.25, h + 0.3, z - d * 0.25, 0, 1, 1, 1))
        tank_c.append(rng.choice(["#4a72b0", "#d9d3c2"]))
instanced(unit_geo, tile_mat(tx.house(), rough=0.9), body_t, body_c)
instanced(unit_geo, std(rough=0.75), roof_t, roof_c)
instanced(tank_geo, std(rough=0.45), tank_t, tank_c)


# ---------- 자동차, 가로등 (여러 개를 한 번에 그린다) ----------
def along(road, step, offset):
    """도로를 따라 step m마다 (X, Y, 방향) 점들"""
    pts = road["pts"]
    for i in range(len(pts) - 1):
        (X0, Y0), (X1, Y1) = pts[i], pts[i + 1]
        L = math.hypot(X1 - X0, Y1 - Y0)
        ux, uy = (X1 - X0) / L, (Y1 - Y0) / L
        k = step / 2
        while k < L:
            yield X0 + ux * k - uy * offset, Y0 + uy * k + ux * offset, math.atan2(Y1 - Y0, X1 - X0)
            k += step


cars = []  # (X, Y, 회전)
P = cd.PARKING
for k in range(int((P[1] - P[0] - 1) / 2.5)):
    for row_y in (P[2] + 2.5, P[3] - 2.5):
        if rng.random() < 0.7:
            cars.append((P[0] + 1.75 + k * 2.5, row_y, 0.0))

CAR_COLORS = ["#f2f2f2", "#c9ccd1", "#2b2d31", "#2a3f5c", "#7f2a2c", "#e8e4da", "#5a5e63"]
base3, part3, m4 = THREE.Object3D.new(), THREE.Object3D.new(), THREE.Matrix4.new()
body_mesh = THREE.InstancedMesh.new(THREE.BoxGeometry.new(1.8, 0.7, 4.4), std(rough=0.3, metal=0.55), len(cars))
cabin_mesh = THREE.InstancedMesh.new(THREE.BoxGeometry.new(1.6, 0.55, 2.3),
                                     std(color="#1b2630", rough=0.15, metal=0.5), len(cars))
wheel_geo = THREE.CylinderGeometry.new(0.34, 0.34, 0.24, 12)
wheel_geo.rotateZ(math.pi / 2)
wheel_mesh = THREE.InstancedMesh.new(wheel_geo, std(color="#161616", rough=0.85), len(cars) * 4)
c3 = THREE.Color.new()


def set_part(mesh, idx, ox, oy, oz):
    part3.position.set(ox, oy, oz)
    part3.updateMatrix()
    m4.multiplyMatrices(base3.matrix, part3.matrix)
    mesh.setMatrixAt(idx, m4)


for i, (X, Y, rot) in enumerate(cars):
    base3.position.set(wx(X), 0.08, wz(Y))
    base3.rotation.set(0, rot, 0)
    base3.updateMatrix()
    set_part(body_mesh, i, 0, 0.62, 0)
    c3.set(rng.choice(CAR_COLORS))
    body_mesh.setColorAt(i, c3)
    set_part(cabin_mesh, i, 0, 1.2, -0.15)
    for k, (ox, oz) in enumerate(((-0.85, -1.35), (0.85, -1.35), (-0.85, 1.35), (0.85, 1.35))):
        set_part(wheel_mesh, i * 4 + k, ox, 0.34, oz)
for m in (body_mesh, cabin_mesh, wheel_mesh):
    m.instanceMatrix.needsUpdate = True
    if m.instanceColor:
        m.instanceColor.needsUpdate = True
    m.castShadow = True
    m.receiveShadow = True
    scene.add(m)


# ---------- 나무 ----------
blocked = [expand(b["rect"], 3.5) for b in cd.BUILDINGS]
blocked += [expand(r, 2) for r in cd.CORRIDORS] + paved
blocked += [expand(cd.FIELD, 2), expand(cd.COURT, 2), expand(cd.STANDS, 2), *garden_paths, expand(cd.BACK_PATH, 1.5)]
blocked += [expand(r[:4], 4) for r in cd.OTHER_SCHOOL]
blocked += [expand((s0, s1, t0, t1), 4) for s0, s1, t0, t1, _ in cd.SLABS]
trees = []  # (X, Y, 종류, 크기)


def near_road(X, Y, m):
    return any(line_dist(X, Y, r["pts"]) < r["w"] / 2 + m for r in cd.ROADS)


def free(X, Y):
    if any(inside(r, X, Y) for r in blocked):
        return False
    if any(math.hypot(X - tx_, Y - ty_) < 22 for tx_, ty_, _ in cd.TOWERS):
        return False
    return all(math.hypot(X - gx_, Y - gy_) > 9 for gx_, gy_ in cd.GATES)


def add_tree(X, Y, kind=None, size=None):
    if kind is None:
        kind = "pine" if rng.random() < 0.22 else "leaf"
    trees.append((X, Y, kind, size or rng.uniform(0.8, 1.25)))


def scatter_poly(poly, bbox, tries, min_gap=4.5, kind=None):
    for _ in range(tries):
        X = rng.uniform(bbox[0], bbox[1])
        Y = rng.uniform(bbox[2], bbox[3])
        if poly and (not in_poly(X, Y, poly) or poly_edge_dist(X, Y, poly) < 2.5):
            continue
        if free(X, Y) and not near_road(X, Y, 3) and all(math.hypot(X - t[0], Y - t[1]) > min_gap for t in trees):
            add_tree(X, Y, kind)


# 위성사진의 숲 자리에 빽빽하게, 나머지 잔디밭에는 드문드문
for r, gap in cd.TREE_ZONES:
    area = (r[1] - r[0]) * (r[3] - r[2])
    scatter_poly(cd.CAMPUS, r, int(area / (gap * gap) * 2.2), gap)
for (ax, ay), (bx, by), step in cd.TREE_ROWS:
    L = math.hypot(bx - ax, by - ay)
    for k in range(int(L / step) + 1):
        X, Y = ax + (bx - ax) * k * step / L, ay + (by - ay) * k * step / L
        if free(X, Y):
            add_tree(X, Y, "leaf", rng.uniform(0.9, 1.1))
scatter_poly(None, cd.GARDEN, 140, 3.8, "leaf")   # 덕린관 남쪽 정원 (나무 많음)
scatter_poly(cd.CAMPUS, (-70, 170, -130, 160), 120, 9)  # 잔디밭 드문드문
add_tree(*cd.BIG_TREE, "leaf", 1.9)  # 중정 가운데 큰 나무
pcX, pcY = (cd.PLAZA[0] + cd.PLAZA[1]) / 2, (cd.PLAZA[2] + cd.PLAZA[3]) / 2
for base in (0, 90, 180, 270):
    for da, r in ((0, 14), (-15, 17), (15, 17)):
        a = math.radians(base + da)
        add_tree(pcX + r * math.cos(a), pcY + r * math.sin(a), "leaf", rng.uniform(0.7, 0.9))
for s0, s1, t0, t1, _ in cd.SLABS:
    scatter_poly(None, expand((s0, s1, t0, t1), 7), 12, 5, "leaf")

bushes = []
for b in cd.BUILDINGS:
    if b["floors"] < 3:
        continue
    bx0, bx1, by0, by1 = b["rect"]
    if bx1 - bx0 >= by1 - by0:
        for X in [bx0 + 1 + i * 2.2 for i in range(int((bx1 - bx0 - 2) / 2.2))]:
            if abs(X - (bx0 + bx1) / 2) > 6:
                bushes.append((X, by0 - 1.6))
    else:
        for Y in [by0 + 1 + i * 2.2 for i in range(int((by1 - by0 - 2) / 2.2))]:
            if abs(Y - (by0 + by1) / 2) > 6:
                bushes.append((bx0 - 1.6, Y))


def blob_geo(seg=10, noise=0.14):
    geo = THREE.SphereGeometry.new(1, seg, int(seg * 0.75))
    pos = geo.attributes.position
    for i in range(pos.count):
        x, y, z = pos.getX(i), pos.getY(i), pos.getZ(i)
        k = 1 + noise * (math.sin(x * 4.1 + 1.3) * math.sin(y * 3.7 + 0.7) + 0.6 * math.sin(z * 5.3 + 2.1))
        pos.setXYZ(i, x * k, y * k, z * k)
    geo.computeVertexNormals()
    return geo


def leaf_color(kind):
    """차분한 늦가을 색 (채도를 낮춰서 자연스럽게)"""
    roll = rng.random()
    if kind == "ginkgo":
        return rng.uniform(0.115, 0.135), rng.uniform(0.62, 0.72), rng.uniform(0.47, 0.53)
    if kind == "pine":
        return rng.uniform(0.3, 0.36), 0.32, rng.uniform(0.16, 0.21)
    if roll < 0.62:   # 초록
        return rng.uniform(0.2, 0.28), rng.uniform(0.3, 0.42), rng.uniform(0.22, 0.3)
    if roll < 0.82:   # 단풍
        return rng.uniform(0.03, 0.07), rng.uniform(0.45, 0.58), rng.uniform(0.36, 0.43)
    return rng.uniform(0.1, 0.13), 0.55, rng.uniform(0.44, 0.5)  # 노란 잎


def hsl_hex(h, s, l):
    c3.setHSL(h, s, l, THREE.SRGBColorSpace)
    return "#" + str(c3.getHexString(THREE.SRGBColorSpace))


CROWN_BLOBS = 3  # 잎 덩어리 3개로 풍성하게
trunk_t, crown_t, crown_c, cone_t, cone_c = [], [], [], [], []
for X, Y, kind, s in trees:
    x, z = wx(X), wz(Y)
    c = leaf_color(kind)
    if kind == "pine":
        h = 9 * s
        trunk_t.append((x, 0, z, 0, s, h * 0.3, s))
        r = h * 0.22
        cone_t += [(x, h * 0.18, z, 0, r, h * 0.55, r), (x, h * 0.45, z, 0, r * 0.72, h * 0.5, r * 0.72)]
        cone_c += [hsl_hex(*c)] * 2
    else:
        h = 7.5 * s if kind == "leaf" else 9 * s
        trunk_t.append((x, 0, z, 0, s, h * 0.55, s))
        r = h * (0.3 if kind == "leaf" else 0.22)
        crown_t.append((x, h * 0.68, z, rng.uniform(0, 6.3), r, r * (0.95 if kind == "leaf" else 1.35), r))
        crown_c.append(hsl_hex(*c))
        for _ in range(1, CROWN_BLOBS):
            a = rng.uniform(0, math.tau)
            crown_t.append((x + math.cos(a) * r * 0.5, h * 0.6, z + math.sin(a) * r * 0.5,
                            rng.uniform(0, 6.3), r * 0.7, r * 0.66, r * 0.7))
            crown_c.append(hsl_hex(c[0] + rng.uniform(-0.01, 0.01), c[1], c[2] + rng.uniform(-0.04, 0.03)))

trunk_geo = THREE.CylinderGeometry.new(0.16, 0.28, 1, 6)
trunk_geo.translate(0, 0.5, 0)
cone_geo = THREE.ConeGeometry.new(1, 1, 9)
cone_geo.translate(0, 0.5, 0)
instanced(trunk_geo, std(color="#5b4636"), trunk_t)
instanced(blob_geo(), std(rough=0.95), crown_t, crown_c)
instanced(cone_geo, std(rough=0.95), cone_t, cone_c)
instanced(blob_geo(8, 0.2), std(rough=0.95),
          [(wx(X), 0.55, wz(Y), rng.uniform(0, 6.3), 0.85, 0.7, 0.85) for X, Y in bushes],
          [hsl_hex(rng.uniform(0.24, 0.3), 0.38, rng.uniform(0.19, 0.25)) for _ in bushes])

def hull(pts):
    """점들을 감싸는 볼록 다각형"""
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


if LITE:
    # 해가 비추는 반대쪽으로 건물 높이만큼 늘인 어두운 바닥 모양 = 그림자
    sdx, sdy = -sun.x / sun.y, sun.z / sun.y   # 높이 1m당 그림자가 뻗는 방향 (캠퍼스 좌표)
    shade_mat = THREE.MeshBasicMaterial.new(js({"color": 0x1a2230, "transparent": True, "opacity": 0.26,
                                                "depthWrite": False}))

    def rect_corners(r):
        return [(r[0], r[2]), (r[1], r[2]), (r[1], r[3]), (r[0], r[3])]

    casters = [(rect_corners(r), b["floors"] * b["floor_h"] + 0.8) for b in cd.BUILDINGS for r in b["parts"]]
    casters += [(rect_corners(r[:4]), r[4]) for r in cd.SLABS + cd.OTHER_SCHOOL]
    casters += [(rect_corners(r), h) for r, h in houses]
    for TX_, TY_, h in cd.TOWERS:
        casters.append(([(TX_ + 22 * math.cos(k * math.tau / 6), TY_ + 22 * math.sin(k * math.tau / 6))
                         for k in range(6)], h))
    for corners, h in casters:
        poly = hull(corners + [(X + sdx * h, Y + sdy * h) for X, Y in corners])
        shp = THREE.Shape.new()
        for i, (X, Y) in enumerate(poly):
            if i == 0:
                shp.moveTo(X - CX, Y - CY)
            else:
                shp.lineTo(X - CX, Y - CY)
        geo = THREE.ShapeGeometry.new(shp)
        geo.rotateX(-math.pi / 2)
        geo.translate(0, 0.16, 0)
        add_geo("shade", shade_mat, geo, cast=False)
    # 나무 그림자: 잎 높이만큼 떨어진 곳에 둥근 그림자
    circle = THREE.CircleGeometry.new(1, 14)
    circle.rotateX(-math.pi / 2)
    tree_shade = []
    for X, Y, kind, s_ in trees:
        h = (9 if kind != "leaf" else 7.5) * s_ * 0.65
        r = h * 0.42
        tree_shade.append((wx(X + sdx * h), 0.17, wz(Y + sdy * h), 0, r, 1, r))
    ts = instanced(circle, THREE.MeshBasicMaterial.new(js({"color": 0x1a2230, "transparent": True,
                                                           "opacity": 0.22, "depthWrite": False})),
                   tree_shade)
    ts.castShadow = False
    ts.receiveShadow = False

flush_batches()
renderer.shadowMap.needsUpdate = True  # 진짜 그림자는 여기서 딱 한 번 계산


# ---------- 화면 조작 ----------
gate_x, gate_y = cd.GATES[1]  # 화정로 정문
VIEWS = {
    "위": ((0, 360, 2), (0, 0, 0)),  # 북쪽이 위로
    "옆": ((0, 35, 300), (0, 10, 0)),
    "입체": ((-150, 140, 190), (0, 0, 0)),
    "정문": ((wx(gate_x), 1.7, wz(gate_y - 6)), (wx(30), 8, wz(30))),
}
fly = {"pos": None, "look": None}


def fly_to(pos, look):
    fly["pos"], fly["look"] = pos, look


def stop_fly(*_):
    fly["pos"] = None


controls.addEventListener("start", create_proxy(stop_fly))


def ghosted(b):
    return state["school"] != "전체" and b["school"] != state["school"]


def refresh_floors():
    for b in cd.BUILDINGS:
        for f, m in enumerate(b["meshes"], start=1):
            key = (b["id"], f)
            if state["selected"] == key:
                m.material = b["hl_js"]
            elif state["hover"] == key:
                m.material = b["hv_js"]
            else:
                m.material = b["mats_js"]
    mark_dirty()


def apply_filter():
    for b in cd.BUILDINGS:
        g = ghosted(b)
        for m in b["mats"] + [b["trim"]]:
            m.transparent = g
            m.opacity = 0.2 if g else 1
            m.depthWrite = not g
            m.needsUpdate = True
        for e in b["extras"]:
            e.visible = not g
        b["label"].visible = state["labels"] and not g
    for spr in landmark_labels:
        spr.visible = state["labels"]
    if state["selected"] and any(ghosted(b) for b in cd.BUILDINGS if b["id"] == state["selected"][0]):
        state["selected"] = None
    refresh_floors()


ray = THREE.Raycaster.new()
ndc = THREE.Vector2.new()
tip = document.querySelector("#tip")


def pick(ev):
    r = renderer.domElement.getBoundingClientRect()
    ndc.set((ev.clientX - r.left) / r.width * 2 - 1, -(ev.clientY - r.top) / r.height * 2 + 1)
    ray.setFromCamera(ndc, camera)
    for h in ray.intersectObjects(pickables, False):
        hit = floor_of.get(h.object.id)
        if hit and not ghosted(hit[0]):
            return hit
    return None


def show_info(b, f):
    panel = document.querySelector("#info")
    panel.innerHTML = ""
    title = document.createElement("h2")
    title.textContent = f'{b["name"]} {f}층'
    tag = document.createElement("p")
    tag.className = "tag"
    tag.textContent = f'{b["school"]} · 지상 {b["floors"]}층 건물'
    ul = document.createElement("ul")
    for item in b["info"].get(f, []):
        li_el = document.createElement("li")
        li_el.textContent = item
        ul.appendChild(li_el)
    btn = document.createElement("button")
    btn.className = "plan-btn"
    page = cd.PLAN_PAGES.get(b["id"], {}).get(f)
    btn.textContent = "📐 이 층 도면 보기" if page else "도면 없음"
    btn.disabled = page is None
    btn.onclick = create_proxy(lambda e: open_plan(b, f))
    for el in (title, tag, ul, btn):
        panel.appendChild(el)


def open_plan(b, f):
    """층을 누르면 처음에 받은 평면도 PDF의 그 층 쪽을 연다"""
    page = cd.PLAN_PAGES.get(b["id"], {}).get(f)
    if not page:
        return
    document.querySelector("#plan-title").textContent = f'{b["name"]} {f}층 평면도 (2023년 도면 {page}쪽)'
    document.querySelector("#plan-frame").src = f"plans.pdf#page={page}&view=Fit&toolbar=0"
    document.querySelector("#plan").style.display = "grid"


@when("click", "#plan-close")
def close_plan(event):
    document.querySelector("#plan").style.display = "none"
    document.querySelector("#plan-frame").src = "about:blank"


down = {"x": 0, "y": 0, "btn": 0}
mouse = {"busy": False}


def on_down(ev):
    down["x"], down["y"], down["btn"] = ev.clientX, ev.clientY, ev.button
    mouse["busy"] = True


# ---------- 층 보기: 누른 층만 남기고 그 층 방 배치를 보여 준다 ----------
fv = {"active": None, "objs": [], "plan": None, "rooms": [], "sel": None}
ORIENT_ROT = {"rot0": 0, "rot180": math.pi, "rot90": math.pi / 2, "rot270": -math.pi / 2}
floor_wall_mat = std(color="#7d4034", rough=0.9)


def set_ghost(b, g):
    for m in b["mats"] + [b["trim"]]:
        m.transparent = g
        m.opacity = 0.15 if g else 1
        m.depthWrite = not g
        m.needsUpdate = True
    for e in b["extras"]:
        e.visible = not g
    b["label"].visible = state["labels"] and not g


def enter_floor(b, f):
    clear_floor()
    fv["active"], fv["sel"] = (b, f), None
    for b2 in cd.BUILDINGS:
        if b2 is b:
            set_ghost(b2, False)
            for i, m in enumerate(b2["meshes"], start=1):
                m.visible = i < f  # 누른 층과 그 위층은 숨긴다
            for e in b2["extras"]:
                e.visible = False
            b2["label"].visible = False
        else:
            set_ghost(b2, True)
    for spr in landmark_labels:
        spr.visible = False
    x, z, w, d = rect_cs(b["rect"])
    y = (f - 1) * b["floor_h"] + (0.16 if f == 1 else 0.06)
    plan = fl.PLANS.get(b["id"])
    rooms = plan["floors"].get(f, []) if plan else []
    fv["rooms"] = rooms
    if rooms:
        o = plan["orient"]
        geo = THREE.PlaneGeometry.new(w, d) if o in ("rot0", "rot180") else THREE.PlaneGeometry.new(d, w)
        geo.rotateX(-math.pi / 2)
        geo.rotateY(ORIENT_ROT[o])
        geo.translate(x, y, z)
        mesh = THREE.Mesh.new(geo, THREE.MeshBasicMaterial.new(
            js({"map": tx.floor_plan(rooms, plan["W"], plan["D"], fl.kind_of, text_rot=ORIENT_ROT[o],
                                     parts=plan.get("parts")), "transparent": True, "alphaTest": 0.05})))
        scene.add(mesh)
        fv["objs"].append(mesh)
        fv["plan"] = mesh
    t = 0.3
    for r in b["parts"]:  # 바깥벽은 낮게만 (모양 조각마다)
        qx, qz, qw, qd = rect_cs(r)
        for px, pz, pw, pd in ((qx, qz - qd / 2, qw + t, t), (qx, qz + qd / 2, qw + t, t),
                               (qx - qw / 2, qz, t, qd + t), (qx + qw / 2, qz, t, qd + t)):
            fv["objs"].append(box(px, y + 0.6, pz, pw, 1.2, pd, floor_wall_mat))
    L = max(w, d)
    fly_to(V3(x, y + L * 0.95 + 25, z + L * 0.5 + 15), V3(x, y, z))
    show_floor_panel()
    refresh_floors()


def clear_floor():
    for o in fv["objs"]:
        scene.remove(o)
        o.geometry.dispose()
    fv["objs"], fv["plan"], fv["rooms"] = [], None, []


def exit_floor(*_, fly=True):
    if not fv["active"]:
        return
    clear_floor()
    fv["active"] = None
    for b2 in cd.BUILDINGS:
        for m in b2["meshes"]:
            m.visible = True
    apply_filter()
    show_home_panel()
    if fly:
        pos, look = VIEWS["입체"]
        fly_to(V3(*pos), V3(*look))


def pick_room(ev):
    if not fv["plan"]:
        return None
    r = renderer.domElement.getBoundingClientRect()
    ndc.set((ev.clientX - r.left) / r.width * 2 - 1, -(ev.clientY - r.top) / r.height * 2 + 1)
    ray.setFromCamera(ndc, camera)
    hits = ray.intersectObject(fv["plan"], False)
    if hits.length == 0:
        return None
    plan = fl.PLANS[fv["active"][0]["id"]]
    uv = hits[0].uv
    xd, yd = uv.x * plan["W"], (1 - uv.y) * plan["D"]
    found = [rm for rm in fv["rooms"] if rm[1] <= xd <= rm[2] and rm[3] <= yd <= rm[4]]
    found.sort(key=lambda rm: (fl.kind_of(rm[0]) in ("hall", "void"), (rm[2] - rm[1]) * (rm[4] - rm[3])))
    return found[0] if found else None


def el(tag, text="", cls=None):
    e = document.createElement(tag)
    if text:
        e.textContent = text
    if cls:
        e.className = cls
    return e


def show_floor_panel():
    b, f = fv["active"]
    panel = document.querySelector("#info")
    panel.innerHTML = ""
    back = el("button", "← 학교 전체 보기", "back-btn")
    back.onclick = create_proxy(lambda e: exit_floor())
    panel.appendChild(back)
    panel.appendChild(el("h2", f'{b["name"]} {f}층'))
    floors_row = el("div", cls="floor-row")
    for k in range(1, b["floors"] + 1):
        fb = el("button", f"{k}층", "floor-btn active" if k == f else "floor-btn")
        fb.onclick = create_proxy(lambda e, k=k: enter_floor(b, k))
        floors_row.appendChild(fb)
    panel.appendChild(floors_row)
    if fv["sel"]:
        name = fv["sel"][0].replace("\n", " ")
        box_ = el("div", cls="sel-box")
        box_.appendChild(el("b", f"선택한 곳: {name}"))
        if fl.kind_of(fv["sel"][0]) == "toilet":
            box_.appendChild(el("p", "🚻 다음 버전: 여기서 화장실 불편 신고를 할 수 있어요.", "note"))
        panel.appendChild(box_)
    else:
        panel.appendChild(el("p", "방을 누르면 이름이 나와요. 파란색이 화장실이에요.", "note"))
    toilets = [rm for rm in fv["rooms"] if fl.kind_of(rm[0]) == "toilet"]
    if toilets:
        panel.appendChild(el("p", f"🚻 이 층 화장실·샤워실 {len(toilets)}곳", "tag"))
    legend = el("div", cls="legend")
    for kind, label in (("class", "교실·특별실"), ("toilet", "화장실"), ("office", "교무·행정"),
                        ("rest", "휴게·식당"), ("stair", "계단")):
        chip = el("span", label, "chip")
        chip.style.setProperty("--c", tx.ROOM_COLORS[kind][0])
        legend.appendChild(chip)
    panel.appendChild(legend)
    if cd.PLAN_PAGES.get(b["id"], {}).get(f):
        pdf = el("button", "원본 도면(PDF) 보기", "pdf-btn")
        pdf.onclick = create_proxy(lambda e: open_plan(b, f))
        panel.appendChild(pdf)


def show_home_panel():
    panel = document.querySelector("#info")
    panel.innerHTML = ""
    panel.appendChild(el("h2", "건물의 층을 누르세요"))
    panel.appendChild(el("p", "누른 층만 남고, 그 층의 방 배치가 보여요.", "note"))
    keys = el("div", cls="keys")
    for k_, v_ in (("왼쪽 드래그", "이동"), ("오른쪽 드래그", "돌리기·기울이기"), ("마우스 휠", "확대·축소"),
                   ("오른쪽 아래 막대", "마우스 없이 돌리기·기울이기"), ("키보드", "Q·E 돌리기, R·F 기울이기"),
                   ("휴대폰", "한 손가락 이동, 두 손가락 확대·돌리기")):
        keys.appendChild(el("b", k_))
        keys.appendChild(el("span", v_))
    panel.appendChild(keys)


def on_up(ev):
    mouse["busy"] = False
    if ev.button != 0 or math.hypot(ev.clientX - down["x"], ev.clientY - down["y"]) > 6:
        return
    if fv["active"]:  # 층 보기 중: 방 고르기
        room = pick_room(ev)
        if room:
            fv["sel"] = room
            show_floor_panel()
        return
    hit = pick(ev)
    if hit:
        enter_floor(*hit)


hover_job = {"ev": None}


def on_move(ev):
    if mouse["busy"]:  # 드래그 중에는 건물 찾기를 쉬어서 부드럽게
        tip.style.display = "none"
        return
    hover_job["ev"] = ev  # 실제 검사는 다음 화면 그릴 때 한 번만


def do_hover():
    ev = hover_job["ev"]
    if ev is None:
        return
    hover_job["ev"] = None
    if fv["active"]:
        room = pick_room(ev)
        if room:
            tip.textContent = room[0].replace("\n", " ")
            tip.style.left = f"{ev.clientX + 14}px"
            tip.style.top = f"{ev.clientY + 14}px"
            tip.style.display = "block"
            renderer.domElement.style.cursor = "pointer"
        else:
            tip.style.display = "none"
            renderer.domElement.style.cursor = "grab"
        return
    hit = pick(ev)
    key = (hit[0]["id"], hit[1]) if hit else None
    if key != state["hover"]:
        state["hover"] = key
        refresh_floors()
    if hit:
        tip.textContent = f'{hit[0]["name"]} {hit[1]}층'
        tip.style.left = f"{ev.clientX + 14}px"
        tip.style.top = f"{ev.clientY + 14}px"
        tip.style.display = "block"
        renderer.domElement.style.cursor = "pointer"
    else:
        tip.style.display = "none"
        renderer.domElement.style.cursor = "grab"


cv = renderer.domElement
cv.addEventListener("pointerdown", create_proxy(on_down))
cv.addEventListener("pointerup", create_proxy(on_up))
cv.addEventListener("pointermove", create_proxy(on_move))
cv.addEventListener("contextmenu", create_proxy(lambda e: e.preventDefault()))


def on_resize(*_):
    renderer.setSize(view.clientWidth, view.clientHeight)
    camera.aspect = view.clientWidth / view.clientHeight
    camera.updateProjectionMatrix()
    mark_dirty()


window.addEventListener("resize", create_proxy(on_resize))


def orbit_by(angle):
    off = camera.position.clone().sub(controls.target)
    off.applyAxisAngle(V3(0, 1, 0), angle)
    fly_to(controls.target.clone().add(off), controls.target.clone())


def zoom_by(factor):
    off = camera.position.clone().sub(controls.target).multiplyScalar(factor)
    fly_to(controls.target.clone().add(off), controls.target.clone())


@when("click", ".view")
def on_view(event):
    exit_floor(fly=False)
    pos, look = VIEWS[event.currentTarget.dataset.view]
    fly_to(V3(*pos), V3(*look))


@when("click", ".nav")
def on_nav(event):
    act = event.currentTarget.dataset.nav
    if act == "in":
        zoom_by(0.7)
    elif act == "out":
        zoom_by(1.4)
    elif act == "left":
        orbit_by(math.pi / 8)
    elif act == "right":
        orbit_by(-math.pi / 8)
    elif act == "home":
        if fv["active"]:
            exit_floor()
        else:
            pos, look = VIEWS["입체"]
            fly_to(V3(*pos), V3(*look))


def set_view_angles(spin_deg=None, tilt_deg=None):
    """슬라이더: 돌리기(좌우)·기울기(위아래)를 각도로 바로 맞춘다"""
    off = camera.position.clone().sub(controls.target)
    sph = THREE.Spherical.new().setFromVector3(off)
    if spin_deg is not None:
        sph.theta = math.radians(spin_deg)
    if tilt_deg is not None:
        sph.phi = math.radians(max(5, min(84, 90 - tilt_deg)))
    off.setFromSpherical(sph)
    camera.position.copy(controls.target).add(off)
    camera.lookAt(controls.target)
    fly["pos"] = None
    mark_moving()


def sync_sliders(*_):
    off = camera.position.clone().sub(controls.target)
    sph = THREE.Spherical.new().setFromVector3(off)
    document.querySelector("#spin").value = str(round(math.degrees(sph.theta)))
    document.querySelector("#tilt").value = str(round(90 - math.degrees(sph.phi)))


@when("input", "#spin")
def on_spin(event):
    set_view_angles(spin_deg=float(event.currentTarget.value))


@when("input", "#tilt")
def on_tilt(event):
    set_view_angles(tilt_deg=float(event.currentTarget.value))


def on_key(ev):  # 키보드 Q/E: 돌리기, R/F: 기울기
    k = str(ev.key).lower()
    if k in ("q", "e"):
        orbit_by(math.pi / 12 if k == "q" else -math.pi / 12)
    elif k in ("r", "f"):
        off = camera.position.clone().sub(controls.target)
        sph = THREE.Spherical.new().setFromVector3(off)
        set_view_angles(tilt_deg=90 - math.degrees(sph.phi) + (8 if k == "r" else -8))


window.addEventListener("keydown", create_proxy(on_key))
controls.addEventListener("end", create_proxy(sync_sliders))


@when("click", ".school")
def on_school(event):
    exit_floor(fly=False)
    state["school"] = event.currentTarget.dataset.school
    for btn in document.querySelectorAll(".school"):
        btn.classList.toggle("active", btn.dataset.school == state["school"])
    apply_filter()


@when("click", "#labels")
def on_labels(event):
    state["labels"] = not state["labels"]
    event.currentTarget.classList.toggle("active", state["labels"])
    apply_filter()


dirty = {"on": True}  # 화면이 바뀐 프레임에만 다시 그린다


def mark_dirty(*_):
    dirty["on"] = True


def mark_moving(*_):
    dirty["on"] = True
    res["last"] = window.performance.now()


controls.addEventListener("change", create_proxy(mark_moving))
for ev_name in ("click", "keydown"):
    window.addEventListener(ev_name, create_proxy(mark_dirty))


def animate(*_):
    if fly["pos"] is not None:
        camera.position.lerp(fly["pos"], 0.08)
        controls.target.lerp(fly["look"], 0.08)
        mark_moving()
        if camera.position.distanceTo(fly["pos"]) < 0.4:
            fly["pos"] = None
    controls.update()
    # 해상도는 바꾸지 않는다: 움직일 때마다 화면 크기를 바꾸면 일부 그래픽카드에서 3D가 멈춘다
    if window.performance.now() - res["last"] > 150:
        do_hover()
    if dirty["on"]:
        dirty["on"] = False
        renderer.render(scene, camera)


renderer.setAnimationLoop(create_proxy(animate))
show_home_panel()
document.querySelector("#loading").remove()
