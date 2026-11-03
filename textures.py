# 캔버스에 직접 그려서 만드는 질감(텍스처)들
import math
import random
from js import document, window

THREE = window.THREE
rng = random.Random(3)


def canvas(w, h):
    c = document.createElement("canvas")
    c.width, c.height = int(w), int(h)
    return c, c.getContext("2d")


def to_texture(c, rx=1, ry=1):
    t = THREE.CanvasTexture.new(c)
    t.colorSpace = THREE.SRGBColorSpace
    t.wrapS = THREE.RepeatWrapping
    t.wrapT = THREE.RepeatWrapping
    t.repeat.set(rx, ry)
    t.anisotropy = 4
    return t


def speckle(g, w, h, n, colors, size=(1, 3)):
    for _ in range(n):
        g.fillStyle = rng.choice(colors)
        s = rng.uniform(*size)
        g.fillRect(rng.uniform(0, w), rng.uniform(0, h), s, s)


def grass(base="#5f8a3e"):
    c, g = canvas(256, 256)
    g.fillStyle = base
    g.fillRect(0, 0, 256, 256)
    speckle(g, 256, 256, 2600, ["#6f9a48", "#53803a", "#7aa352", "#4b7333", "#86ad5c"])
    speckle(g, 256, 256, 60, ["#8a7a4c", "#9c8b57"], (2, 4))  # 마른 잎
    return to_texture(c)


def asphalt():
    c, g = canvas(256, 256)
    g.fillStyle = "#45474a"
    g.fillRect(0, 0, 256, 256)
    speckle(g, 256, 256, 3000, ["#505357", "#3c3e41", "#5a5d61", "#37393b"], (1, 2))
    return to_texture(c)


def pavers(base="#bdb8ae", line="rgba(0,0,0,0.10)", tiles=4):
    c, g = canvas(256, 256)
    g.fillStyle = base
    g.fillRect(0, 0, 256, 256)
    speckle(g, 256, 256, 1200, ["rgba(0,0,0,0.03)", "rgba(255,255,255,0.05)"], (1, 2))
    g.strokeStyle = line
    g.lineWidth = 2
    step = 256 / tiles
    for i in range(tiles + 1):
        g.beginPath(); g.moveTo(0, i * step); g.lineTo(256, i * step); g.stroke()
        g.beginPath(); g.moveTo(i * step, 0); g.lineTo(i * step, 256); g.stroke()
    return to_texture(c)


def roof_concrete():
    c, g = canvas(256, 256)
    g.fillStyle = "#9fa29e"
    g.fillRect(0, 0, 256, 256)
    speckle(g, 256, 256, 1800, ["#a9aca8", "#949793", "#8c8f8b", "#b0b3af"], (1, 4))
    return to_texture(c)


def metal_roof(color):
    c, g = canvas(64, 64)
    g.fillStyle = color
    g.fillRect(0, 0, 64, 64)
    for x in range(0, 64, 8):
        g.fillStyle = "rgba(255,255,255,0.18)"
        g.fillRect(x, 0, 2, 64)
        g.fillStyle = "rgba(0,0,0,0.15)"
        g.fillRect(x + 2, 0, 1, 64)
    return to_texture(c)


BRICKS = {  # 벽돌 색 묶음 (벽돌마다 조금씩 다른 색)
    "brick": ["#7d3f33", "#86463a", "#8f4d3f", "#733a2f", "#94523f", "#7a4236"],
    "brick_dark": ["#6a3830", "#733d33", "#5f322b", "#7b4237", "#683a31"],
    "brick_light": ["#b0624a", "#b86a50", "#a85b44", "#c07255", "#ad6047", "#b5664c"],
}


def facade(wall, fh, style="school"):
    """건물 외벽 한 칸(폭 5m, 한 층 높이) 그림. 가로로 반복해서 붙인다."""
    ppm = 64
    w, h = 5 * ppm, int(fh * ppm)
    c, g = canvas(w, h)
    if style in ("brick", "brick_gym", "brick_plain", "brick_stair"):
        # 붉은 벽돌 벽 (로드뷰: 학교 건물은 모두 짙은 적갈색 벽돌)
        g.fillStyle = "#cbc3b8"  # 줄눈
        g.fillRect(0, 0, w, h)
        bh, bl = 5, 15
        for row in range(int(h / bh) + 1):
            off = (row % 2) * bl / 2
            x = -off
            while x < w:
                g.fillStyle = rng.choice(BRICKS[wall] if wall in BRICKS else [wall])
                g.fillRect(x + 0.6, row * bh + 0.6, bl - 1.2, bh - 1.2)
                x += bl
        if style == "brick_gym":  # 체육관: 아래쪽 벽돌 판 위에 흰 콘크리트 띠
            g.fillStyle = "#e9e6df"
            g.fillRect(0, (fh - 2.2) * ppm, w, 0.22 * ppm)
            g.fillStyle = "rgba(0,0,0,0.18)"  # 들어간 벽돌 판 그림자
            g.fillRect(0.25 * ppm, (fh - 2.0) * ppm, w - 0.5 * ppm, 3)
        if style == "brick_plain":
            return to_texture(c)
    else:
        g.fillStyle = wall
        g.fillRect(0, 0, w, h)
        speckle(g, w, h, 400, ["rgba(0,0,0,0.035)", "rgba(255,255,255,0.05)"], (1, 3))
        g.fillStyle = "rgba(0,0,0,0.13)"  # 층 사이 슬래브 띠
        g.fillRect(0, h - 0.32 * ppm, w, 0.32 * ppm)

    def window_box(x0, x1, top_m, bottom_m, cols=2):
        x0p, x1p = x0 * ppm, x1 * ppm
        t, b = top_m * ppm, bottom_m * ppm
        grad = g.createLinearGradient(0, t, 0, b)
        grad.addColorStop(0, "#b4cad9")
        grad.addColorStop(0.5, "#5f7d93")
        grad.addColorStop(1, "#2f4554")
        g.fillStyle = grad
        g.fillRect(x0p, t, x1p - x0p, b - t)
        g.fillStyle = "rgba(255,255,255,0.13)"  # 유리 반사
        g.beginPath()
        g.moveTo(x0p, b); g.lineTo(x0p + (x1p - x0p) * 0.45, t)
        g.lineTo(x0p + (x1p - x0p) * 0.65, t); g.lineTo(x0p + (x1p - x0p) * 0.2, b)
        g.closePath(); g.fill()
        g.strokeStyle = "#f2f2ef"
        g.lineWidth = 4
        g.strokeRect(x0p, t, x1p - x0p, b - t)
        g.lineWidth = 3
        for i in range(1, cols):
            x = x0p + (x1p - x0p) * i / cols
            g.beginPath(); g.moveTo(x, t); g.lineTo(x, b); g.stroke()
        g.beginPath(); g.moveTo(x0p, t + (b - t) * 0.28); g.lineTo(x1p, t + (b - t) * 0.28); g.stroke()
        g.fillStyle = "rgba(0,0,0,0.22)"  # 창턱 그림자
        g.fillRect(x0p - 2, b, x1p - x0p + 4, 5)

    if style == "brick_gym":  # 체육관: 위쪽에만 검은 틀의 가로 창
        window_box(0.3, 4.7, 0.5, 1.6, cols=3)
    elif style == "gym":
        window_box(0.4, 4.6, fh - 4.9, fh - 3.3, cols=3)
    elif style == "glass":
        window_box(0.15, 4.85, 0.35, fh - 0.7, cols=3)
    elif style == "brick":
        for x0_ in (0.55, 2.75):
            g.fillStyle = "#e6e2da"  # 창 위 흰 인방, 아래 창턱
            g.fillRect(x0_ * ppm - 4, (fh - 2.75) * ppm, 1.7 * ppm + 8, 0.12 * ppm)
            g.fillRect(x0_ * ppm - 4, (fh - 1.0) * ppm, 1.7 * ppm + 8, 0.1 * ppm)
            window_box(x0_, x0_ + 1.7, fh - 2.63, fh - 1.0, cols=2)
    elif style == "brick_stair":  # 계단실: 가운데 좁은 세로 창
        g.fillStyle = "#e6e2da"
        g.fillRect(1.9 * ppm, (fh - 2.6) * ppm, 1.2 * ppm, 0.1 * ppm)
        window_box(2.0, 3.0, fh - 2.5, fh - 1.2, cols=1)
    elif style == "apt":
        window_box(0.3, 2.3, fh - 2.4, fh - 0.9, cols=1)
        window_box(2.7, 4.7, fh - 2.4, fh - 0.9, cols=1)
        g.fillStyle = "rgba(255,255,255,0.55)"  # 베란다 난간
        g.fillRect(0, (fh - 1.05) * ppm, w, 4)
    else:
        window_box(0.55, 4.45, fh - 2.75, fh - 0.95, cols=3)
    return to_texture(c)


PITCH_W, PITCH_L = 64, 100  # 트랙 안쪽 축구장 크기 (m) - 위성사진 기준
TRACK_W = 8                  # 트랙 폭 (m)


def stadium_path(g, cx, cy, w, l):
    """세로로 긴 경기장 트랙 모양(양 끝이 반원) 경로"""
    r = w / 2
    half = l / 2 - r
    g.beginPath()
    g.arc(cx, cy - half, r, math.pi, 0)
    g.lineTo(cx + r, cy + half)
    g.arc(cx, cy + half, r, 0, math.pi)
    g.closePath()


def soccer_field(fw, fd, courts=()):
    """운동장: 바깥 잔디 + 트랙 + 안쪽 인조잔디 축구장 (1m = 16px)"""
    ppm = 16
    W, H = fw * ppm, fd * ppm
    c, g = canvas(W, H)
    g.fillStyle = "#5f8a3e"
    g.fillRect(0, 0, W, H)
    speckle(g, W, H, 2500, ["#6f9a48", "#53803a", "#7aa352"], (1, 3))
    cx, cy = W / 2, H / 2
    stadium_path(g, cx, cy, W - 2, H - 2)  # 트랙 (마사토색)
    g.fillStyle = "#c9ad86"
    g.fill()
    speckle(g, W, H, 1500, ["rgba(0,0,0,0.04)"], (1, 2))
    g.strokeStyle = "rgba(255,255,255,0.75)"
    g.lineWidth = 1.5
    for k in range(1, 4):
        inset = k * TRACK_W / 4 * ppm * 2
        stadium_path(g, cx, cy, W - 2 - inset, H - 2 - inset)
        g.stroke()
    inner_w, inner_l = W - 2 - 2 * TRACK_W * ppm, H - 2 - 2 * TRACK_W * ppm
    stadium_path(g, cx, cy, inner_w, inner_l)  # 안쪽 인조잔디
    g.save()
    g.clip()
    for i in range(int(fd / 5) + 1):
        g.fillStyle = "#3f8a3a" if i % 2 else "#4b9844"
        g.fillRect(0, i * 5 * ppm, W, 5 * ppm)
    g.restore()

    pw, pl = PITCH_W * ppm, PITCH_L * ppm
    left, top = cx - pw / 2, cy - pl / 2
    g.strokeStyle = "rgba(255,255,255,0.92)"
    g.lineWidth = 2.2
    g.strokeRect(left, top, pw, pl)
    g.beginPath(); g.moveTo(left, cy); g.lineTo(left + pw, cy); g.stroke()
    g.beginPath(); g.arc(cx, cy, 0.12 * pl, 0, math.tau); g.stroke()
    g.fillStyle = "white"
    g.beginPath(); g.arc(cx, cy, 3, 0, math.tau); g.fill()
    for x0, x1, y0, y1 in courts:  # 트랙 안 양쪽 끝 모래 코트 (위성사진)
        X0, Y0, Wc, Hc = x0 * ppm, y0 * ppm, (x1 - x0) * ppm, (y1 - y0) * ppm
        g.fillStyle = "#d8c49c"
        g.fillRect(X0, Y0, Wc, Hc)
        speckle(g, W, H, 0, [])
        g.strokeStyle = "rgba(255,255,255,0.7)"
        g.lineWidth = 2
        cw_, ch_ = min(28, x1 - x0 - 2) * ppm, min(15, y1 - y0 - 2) * ppm  # 농구 코트 라인
        cx_, cy_ = X0 + Wc / 2, Y0 + Hc / 2
        g.strokeRect(cx_ - cw_ / 2, cy_ - ch_ / 2, cw_, ch_)
        g.beginPath(); g.moveTo(cx_, cy_ - ch_ / 2); g.lineTo(cx_, cy_ + ch_ / 2); g.stroke()
        g.beginPath(); g.arc(cx_, cy_, 1.8 * ppm, 0, math.tau); g.stroke()
    g.strokeStyle = "rgba(255,255,255,0.92)"
    g.lineWidth = 2.2
    for end, sign in ((top, 1), (top + pl, -1)):
        bw, bd = 0.6 * pw, 0.18 * pl
        gw, gd = 0.3 * pw, 0.07 * pl
        g.strokeRect(cx - bw / 2, end if sign > 0 else end - bd, bw, bd)
        g.strokeRect(cx - gw / 2, end if sign > 0 else end - gd, gw, gd)
        g.beginPath(); g.arc(cx, end + sign * 0.12 * pl, 3, 0, math.tau); g.fill()
    return to_texture(c)


def solar_panel():
    c, g = canvas(128, 80)
    g.fillStyle = "#1b2d4c"
    g.fillRect(0, 0, 128, 80)
    g.strokeStyle = "#3b5680"
    g.lineWidth = 1
    for x in range(0, 128, 13):
        g.beginPath(); g.moveTo(x, 0); g.lineTo(x, 80); g.stroke()
    for y in range(0, 80, 13):
        g.beginPath(); g.moveTo(0, y); g.lineTo(128, y); g.stroke()
    g.strokeStyle = "#c3c7cc"
    g.lineWidth = 4
    g.strokeRect(0, 0, 128, 80)
    return to_texture(c)


def house():
    """동네 주택 외벽 (인스턴스 색으로 벽 색을 바꾼다)"""
    c, g = canvas(128, 128)
    g.fillStyle = "#ffffff"
    g.fillRect(0, 0, 128, 128)
    speckle(g, 128, 128, 200, ["rgba(0,0,0,0.04)"], (1, 3))
    for row in (14, 74):
        for col in (14, 74):
            g.fillStyle = "#3b4a56"
            g.fillRect(col, row, 40, 30)
            g.fillStyle = "rgba(255,255,255,0.18)"
            g.fillRect(col + 4, row + 3, 12, 24)
            g.strokeStyle = "#e9e9e6"
            g.lineWidth = 3
            g.strokeRect(col, row, 40, 30)
    return to_texture(c)


def shop(sign_color):
    """1층 가게 (폭 6m, 높이 3.5m): 간판 띠 + 유리창"""
    ppm = 40
    W, H = 6 * ppm, int(3.5 * ppm)
    c, g = canvas(W, H)
    g.fillStyle = "#d8d4cc"
    g.fillRect(0, 0, W, H)
    g.fillStyle = sign_color
    g.fillRect(0, 0, W, 0.9 * ppm)
    g.fillStyle = "rgba(255,255,255,0.9)"
    for i in range(rng.randint(3, 5)):
        g.fillRect(20 + i * 34, 10, 24, 0.9 * ppm - 20)
    grad = g.createLinearGradient(0, 1.1 * ppm, 0, H)
    grad.addColorStop(0, "#9fb4c2")
    grad.addColorStop(1, "#3a4a55")
    g.fillStyle = grad
    g.fillRect(0.3 * ppm, 1.1 * ppm, W - 0.6 * ppm, H - 1.1 * ppm)
    g.strokeStyle = "#2b2b2b"
    g.lineWidth = 4
    g.strokeRect(0.3 * ppm, 1.1 * ppm, W - 0.6 * ppm, H - 1.1 * ppm)
    g.beginPath(); g.moveTo(W * 0.62, 1.1 * ppm); g.lineTo(W * 0.62, H); g.stroke()
    return to_texture(c)


def basketball_court(cw, cd):
    ppm = 20
    W, H = cw * ppm, cd * ppm
    c, g = canvas(W, H)
    g.fillStyle = "#3f6b55"
    g.fillRect(0, 0, W, H)
    lw, ld = 15 * ppm, 28 * ppm
    x0, y0 = (W - lw) / 2, (H - ld) / 2
    g.fillStyle = "#4f7fa8"
    g.fillRect(x0, y0, lw, ld)
    speckle(g, W, H, 1500, ["rgba(0,0,0,0.05)", "rgba(255,255,255,0.05)"], (1, 2))
    g.strokeStyle = "white"
    g.lineWidth = 3
    g.strokeRect(x0, y0, lw, ld)
    g.beginPath(); g.moveTo(x0, H / 2); g.lineTo(x0 + lw, H / 2); g.stroke()
    g.beginPath(); g.arc(W / 2, H / 2, 1.8 * ppm, 0, math.tau); g.stroke()
    for end, sign in ((y0, 1), (y0 + ld, -1)):
        kw, kd = 4.9 * ppm, 5.8 * ppm
        g.fillStyle = "#b5654a"
        g.fillRect(W / 2 - kw / 2, end if sign > 0 else end - kd, kw, kd)
        g.strokeRect(W / 2 - kw / 2, end if sign > 0 else end - kd, kw, kd)
        hoop = end + sign * 1.6 * ppm
        g.beginPath()
        if sign > 0:
            g.arc(W / 2, hoop, 6.75 * ppm, 0.12, math.pi - 0.12)
        else:
            g.arc(W / 2, hoop, 6.75 * ppm, math.pi + 0.12, math.tau - 0.12)
        g.stroke()
    return to_texture(c)


def rubber_court(cw, cd):
    ppm = 10
    W, H = cw * ppm, cd * ppm
    c, g = canvas(W, H)
    g.fillStyle = "#b8664b"
    g.fillRect(0, 0, W, H)
    speckle(g, W, H, 3000, ["rgba(0,0,0,0.06)", "rgba(255,255,255,0.05)"], (1, 2))
    g.strokeStyle = "rgba(255,255,255,0.9)"
    g.lineWidth = 2
    g.strokeRect(2 * ppm, 2 * ppm, W - 4 * ppm, H - 4 * ppm)
    g.beginPath(); g.moveTo(W / 2, 2 * ppm); g.lineTo(W / 2, H - 2 * ppm); g.stroke()
    g.beginPath(); g.arc(W / 2, H / 2, 3 * ppm, 0, math.tau); g.stroke()
    return to_texture(c)


def parking(pw, pd):
    ppm = 20
    W, H = pw * ppm, pd * ppm
    c, g = canvas(W, H)
    g.fillStyle = "#4a4c4f"
    g.fillRect(0, 0, W, H)
    speckle(g, W, H, 2500, ["#55585c", "#3e4043", "#5f6266"], (1, 2))
    g.strokeStyle = "rgba(255,255,255,0.85)"
    g.lineWidth = 3
    x = 0.5 * ppm
    while x < W:
        for y0, y1 in ((0, 5 * ppm), (H - 5 * ppm, H)):
            g.beginPath(); g.moveTo(x, y0); g.lineTo(x, y1); g.stroke()
        x += 2.5 * ppm
    return to_texture(c)


def plaza(size):
    """중정: 잔디 + X자 길 + 가운데 원형 광장"""
    ppm = 10
    W = size * ppm
    c, g = canvas(W, W)
    g.fillStyle = "#5f8f42"
    g.fillRect(0, 0, W, W)
    speckle(g, W, W, 3000, ["#6f9a48", "#53803a", "#7aa352"], (1, 3))
    stone = "#d6d0c4"
    g.strokeStyle = stone
    g.lineWidth = 3 * ppm
    g.strokeRect(1.5 * ppm, 1.5 * ppm, W - 3 * ppm, W - 3 * ppm)
    g.lineWidth = 4 * ppm
    g.beginPath(); g.moveTo(0, 0); g.lineTo(W, W); g.stroke()
    g.beginPath(); g.moveTo(W, 0); g.lineTo(0, W); g.stroke()
    g.fillStyle = stone
    g.beginPath(); g.arc(W / 2, W / 2, 10 * ppm, 0, math.tau); g.fill()
    g.strokeStyle = "rgba(0,0,0,0.08)"
    g.lineWidth = 2
    for r in (4, 7, 10):
        g.beginPath(); g.arc(W / 2, W / 2, r * ppm, 0, math.tau); g.stroke()
    return to_texture(c)


LABEL_STYLES = {
    # 종류: (모양, 배경·테두리색, 글자색) - 지도 앱처럼 깔끔하게
    "building": ("pill", "rgba(24,32,44,0.82)", "#ffffff"),
    "place": ("halo", "#ffffff", "#2b3440"),
    "road": ("halo", "rgba(70,84,104,0.95)", "#ffffff"),
    "gate": ("pill", "rgba(214,98,26,0.95)", "#ffffff"),
    "bus": ("pill", "rgba(38,128,82,0.95)", "#ffffff"),
}
FONT = "'Pretendard', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif"


def label(text, style="building"):
    """이름표 그림. (텍스처, 가로/세로 비율)을 돌려준다."""
    kind, color, fg = LABEL_STYLES[style]
    weight = "700" if style in ("building", "road") else "600"
    font = f"{weight} 44px {FONT}"
    c, g = canvas(16, 16)
    g.font = font
    dot = 26 if style == "place" else 0
    w = int(g.measureText(text).width) + 48 + dot
    c.width, c.height = w, 80
    g.font = font  # 캔버스 크기를 바꾸면 글꼴 설정이 초기화된다
    g.textAlign = "center"
    g.textBaseline = "middle"
    cx = w / 2 + dot / 2
    if kind == "pill":
        g.fillStyle = color
        g.beginPath()
        g.roundRect(2, 8, w - 4, 64, 32)
        g.fill()
    else:  # 지도 글씨처럼 테두리(헤일로)만
        g.lineJoin = "round"
        g.lineWidth = 10
        g.strokeStyle = color
        g.strokeText(text, cx, 42)
    if dot:
        g.fillStyle = "#e0533d"
        g.beginPath(); g.arc(20, 40, 9, 0, math.tau); g.fill()
        g.lineWidth = 4
        g.strokeStyle = "#ffffff"
        g.stroke()
    g.fillStyle = fg
    g.fillText(text, cx, 42)
    t = THREE.CanvasTexture.new(c)
    t.colorSpace = THREE.SRGBColorSpace
    return t, w / 80


def flag_korea():
    c, g = canvas(150, 100)
    g.fillStyle = "white"
    g.fillRect(0, 0, 150, 100)
    g.save()
    g.translate(75, 50)
    g.rotate(math.atan2(2, 3))
    g.fillStyle = "#c60c30"
    g.beginPath(); g.arc(0, 0, 25, math.pi, 0); g.fill()
    g.fillStyle = "#003478"
    g.beginPath(); g.arc(0, 0, 25, 0, math.pi); g.fill()
    g.fillStyle = "#c60c30"
    g.beginPath(); g.arc(-12.5, 0, 12.5, 0, math.pi); g.fill()
    g.fillStyle = "#003478"
    g.beginPath(); g.arc(12.5, 0, 12.5, math.pi, math.tau); g.fill()
    g.restore()
    g.fillStyle = "black"
    for ang in (math.atan2(2, 3), math.pi - math.atan2(2, 3)):
        for side in (1, -1):
            g.save()
            g.translate(75, 50)
            g.rotate(-ang if side > 0 else math.pi - ang)
            for i in range(3):
                g.fillRect(-8, -44 + i * 6, 16, 4)
            g.restore()
    return to_texture(c)


def concrete():
    """동네 골목·마당 바닥 (밝은 회색 콘크리트·아스팔트 섞임)"""
    c, g = canvas(256, 256)
    g.fillStyle = "#8d8f8f"
    g.fillRect(0, 0, 256, 256)
    speckle(g, 256, 256, 2500, ["#979999", "#838585", "#a1a3a2", "#7b7d7e"], (1, 3))
    return to_texture(c)


def dirt():
    """흙 운동장 (마사토)"""
    c, g = canvas(256, 256)
    g.fillStyle = "#c8b18b"
    g.fillRect(0, 0, 256, 256)
    speckle(g, 256, 256, 3000, ["#d2bc97", "#bba47e", "#c1a983", "#d8c4a2"], (1, 3))
    return to_texture(c)


def mini_pitch(pw, pd):
    """작은 인조잔디 운동장 (1m = 10px)"""
    ppm = 10
    W, H = pw * ppm, pd * ppm
    c, g = canvas(W, H)
    for i in range(int(pd / 4) + 1):
        g.fillStyle = "#3f8a3a" if i % 2 else "#4b9844"
        g.fillRect(0, i * 4 * ppm, W, 4 * ppm)
    g.strokeStyle = "rgba(255,255,255,0.9)"
    g.lineWidth = 2
    g.strokeRect(1.5 * ppm, 1.5 * ppm, W - 3 * ppm, H - 3 * ppm)
    g.beginPath(); g.moveTo(1.5 * ppm, H / 2); g.lineTo(W - 1.5 * ppm, H / 2); g.stroke()
    g.beginPath(); g.arc(W / 2, H / 2, 3 * ppm, 0, math.tau); g.stroke()
    return to_texture(c)


def banner():
    """만대관 벽에 걸린 태극기 현수막 (로드뷰)"""
    c, g = canvas(180, 360)
    g.fillStyle = "#2c3f6c"
    g.fillRect(0, 0, 180, 360)
    g.fillStyle = "#ffffff"
    g.fillRect(12, 40, 156, 104)
    flag = flag_korea().image
    g.drawImage(flag, 15, 42, 150, 100)
    g.fillStyle = "#ffffff"
    g.font = "700 22px 'Pretendard', 'Malgun Gothic', sans-serif"
    g.textAlign = "center"
    g.fillText("태극기 상설 전시관", 90, 190)
    g.font = "600 16px 'Pretendard', 'Malgun Gothic', sans-serif"
    g.fillText("광덕고등학교", 90, 330)
    return to_texture(c)


def iron_fence():
    """검은 철제 울타리 (세로 살 + 위아래 가로대). 살 사이는 투명"""
    c, g = canvas(64, 64)
    g.clearRect(0, 0, 64, 64)
    g.fillStyle = "#1c1e20"
    for x in range(2, 64, 8):
        g.fillRect(x, 0, 3, 64)
    g.fillRect(0, 2, 64, 4)
    g.fillRect(0, 56, 64, 4)
    return to_texture(c)


ROOM_COLORS = {  # 종류: (바닥색, 글자색)
    "class": ("#f3dca8", "#3a2d14"),
    "office": ("#dcd3ea", "#2e2640"),
    "rest": ("#cfe5c4", "#20361a"),
    "toilet": ("#3d86d8", "#ffffff"),
    "stair": ("#b9bec6", "#2b3038"),
    "hall": ("#f4f1ea", "#7a7468"),
    "void": ("rgba(0,0,0,0)", "#7a7468"),
}


def floor_plan(rooms, W, D, kind_of, ppm=22, text_rot=0.0, parts=None):
    """층 평면도 그림: 방마다 색칠하고 이름을 크게 쓴다 (도면 치수 비율 그대로)"""
    c, g = canvas(W * ppm, D * ppm)
    g.clearRect(0, 0, W * ppm, D * ppm)  # 건물 바깥은 투명
    g.fillStyle = "#e9e4d8"  # 건물 안 바탕(복도)
    for x0, x1, y0, y1 in (parts or [(0, W, 0, D)]):
        g.fillRect(x0 * ppm, y0 * ppm, (x1 - x0) * ppm, (y1 - y0) * ppm)
    order = sorted(rooms, key=lambda r: {"hall": 0, "void": 0}.get(kind_of(r[0]), 1))
    for name, x0, x1, y0, y1 in order:
        bg, fg = ROOM_COLORS[kind_of(name)]
        X, Y, Wd, H = x0 * ppm, y0 * ppm, (x1 - x0) * ppm, (y1 - y0) * ppm
        g.fillStyle = bg
        g.fillRect(X, Y, Wd, H)
        g.strokeStyle = "#5b5348"
        g.lineWidth = 3
        g.strokeRect(X + 1.5, Y + 1.5, Wd - 3, H - 3)
        if kind_of(name) == "stair":  # 계단 줄무늬
            g.strokeStyle = "rgba(60,64,72,0.35)"
            g.lineWidth = 2
            k = 6
            while k < Wd:
                g.beginPath(); g.moveTo(X + k, Y + 4); g.lineTo(X + k, Y + H - 4); g.stroke()
                k += 10
        lines = name.split("\n")
        tw, th = (H, Wd) if abs(math.sin(text_rot)) > 0.5 else (Wd, H)  # 글자를 돌리면 가로·세로가 바뀐다
        size = max(13, min(40, min(tw / max(len(s) for s in lines) * 1.1, th / (len(lines) + 0.6))))
        g.save()
        g.translate(X + Wd / 2, Y + H / 2)
        g.rotate(text_rot)  # 화면에서 똑바로 읽히게 글자만 돌린다
        g.font = f"700 {int(size)}px {FONT}"
        g.textAlign = "center"
        g.textBaseline = "middle"
        g.fillStyle = fg
        for i, s in enumerate(lines):
            g.fillText(s, 0, (i - (len(lines) - 1) / 2) * size * 1.15)
        g.restore()
    t = THREE.CanvasTexture.new(c)
    t.colorSpace = THREE.SRGBColorSpace
    t.anisotropy = 8
    return t
