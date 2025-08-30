#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py - Final refined version
Features implemented per user request:
- Play area moved left: left blank reduced (~1/3), right blank halved
- Single lane, notes drop at constant linear speed (no internal timing change during effects)
- Judgement text placed above the hitline
- Notes disappear immediately after judgement window if not hit
- Combo gimmick threshold: 20 combos (default); Yakubi (厄日) mode: gimmick every 10 notes spawned
- Yakubi mode toggle in Settings (checkbox). When ON, gimmicks occur every 10 spawned notes
- Gimmicks include lane wobble that shakes the whole play area
- Start screen: Start | Settings(center) | Gimmicks
- Game start includes a short prep interval (countdown)
- GameOver screen: Restart | Settings | Title
- "New gimmick occurred" notification rendered in bold with white background at bottom-right; cleared each frame
- Mokugyo reduced in size so it doesn't overflow the play area
- Robust fallbacks for missing assets; won't crash
"""
import os, sys, math, random, time
import pygame

# ----------------- Initialization -----------------
pygame.init()
try:
    pygame.mixer.init()
except Exception:
    pass

WIDTH, HEIGHT = 1280, 720
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("木魚リズム — Final")
clock = pygame.time.Clock()
FPS = 60

ASSETS = "assets"

# ----------------- Utilities -----------------
def now_s(): return pygame.time.get_ticks() / 1000.0
def clamp(v, a, b): return max(a, min(b, v))

# ----------------- Font loader -----------------
def load_jp_font(size):
    candidates = [
        os.path.join(ASSETS, "NotoSansJP-Regular.otf"),
        "Hiragino Kaku Gothic ProN",
        "HiraginoSans-W3",
        "YuGothic",
        None
    ]
    for c in candidates:
        try:
            if isinstance(c, str) and os.path.exists(c):
                return pygame.font.Font(c, size)
            else:
                f = pygame.font.SysFont(c, size)
                _ = f.render("テスト", True, (0,0,0))
                return f
        except Exception:
            continue
    return pygame.font.SysFont(None, size)

FONT_LG = load_jp_font(56)
FONT_MD = load_jp_font(28)
FONT_SM = load_jp_font(20)
FONT_BOLD = load_jp_font(24)

# ----------------- Safe asset loaders -----------------
def safe_image(name, scale=None, fallback=(80,80,80)):
    p = os.path.join(ASSETS, name)
    if os.path.exists(p):
        try:
            im = pygame.image.load(p).convert_alpha()
            if scale: im = pygame.transform.smoothscale(im, scale)
            return im
        except Exception:
            pass
    w,h = scale if scale else (200,200)
    s = pygame.Surface((w,h), pygame.SRCALPHA)
    s.fill(fallback)
    return s

def safe_sound(name):
    p = os.path.join(ASSETS, name)
    if os.path.exists(p):
        try:
            return pygame.mixer.Sound(p)
        except Exception:
            pass
    return None

# ----------------- Assets -----------------
BG_IMG = safe_image("bg_room.jpg", scale=(WIDTH, HEIGHT))
# Mokugyo smaller to avoid overflow
MOKUGYO_IMG = safe_image("mokugyo.png", scale=(100,100))
HANNYA_IMG = safe_image("hannya.png", scale=(240,240))

BGM = safe_sound("bgm.mp3")
SE_HIT = safe_sound("se_hit.mp3")
SE_MISS = safe_sound("se_miss.mp3")

BGM_LENGTH = None
if BGM:
    try: BGM_LENGTH = BGM.get_length()
    except Exception: BGM_LENGTH = None

# ----------------- Gameplay constants -----------------
BPM = 158
SPB = 60.0 / BPM             # seconds per quarter note
NOTE_TRAVEL_SEC = 1.6        # spawn -> hit time, constant linear speed
NOTE_RADIUS = 14

# Compute play area positions:
# Previous play width (approx) used earlier was ~WIDTH*0.38, with right edge at WIDTH/2.
# New requirement: move whole area left so left blank becomes ~1/3 of previous blank.
PREV_PLAY_WIDTH = int(WIDTH * 0.38)
PREV_LEFT_BLANK = (WIDTH//2) - PREV_PLAY_WIDTH
NEW_LEFT_BLANK = max(8, PREV_LEFT_BLANK // 3)  # roughly 1/3
# Place right edge at center, and width accordingly: right_center - left_blank
PLAY_AREA_RIGHT = WIDTH // 2
PLAY_WIDTH = PLAY_AREA_RIGHT - NEW_LEFT_BLANK
PLAY_AREA = pygame.Rect(NEW_LEFT_BLANK, 40, PLAY_WIDTH, int(HEIGHT * 0.86))

# Single lane and hitline
LANE_X = int(PLAY_AREA.left + PLAY_AREA.width * 0.25)
MOKUGYO_CENTER = (LANE_X, PLAY_AREA.bottom - 40)
HITLINE_Y = PLAY_AREA.bottom - 120

# Hannya area
HANNYA_TARGET_X = int(WIDTH * 0.82)
HANNYA_TARGET_Y = int(HEIGHT * 0.52)

# Judgement windows (seconds)
PERFECT_WINDOW = 0.05
GOOD_WINDOW = 0.09
OK_WINDOW = 0.14

# Difficulty & Miss limits
DIFFICULTY = "normal"
MISS_LIMIT_MAP = {"easy":12, "normal":6, "hard":1}
DIFF_WINDOW = {"easy":1.4, "normal":1.0, "hard":0.6}
HIDE_STEP = 4

# Effects durations
effects = {
    "shake_small": 0.0,
    "shake_big": 0.0,
    "rotate60": 0.0,
    "flash": 0.0,
    "slowmo": 0.0,
    "lane_wobble": 0.0,
    "ghost": 0.0,
    "spawn_rush": 0.0,
    "blackout": 0.0,
    "invert": 0.0
}
slowmo_current = 1.0
slowmo_target = 1.0

# Scenes
SCENE_START = "start"
SCENE_SETTINGS = "settings"
SCENE_GAME = "game"
SCENE_GAMEOVER = "gameover"
SCENE_CLEAR = "clear"
scene = SCENE_START

# Timing
start_time_s = None
next_beat_time = None
spawn_index = 0
spawned_target_times = set()
note_spawn_counter = 0  # counts spawned notes (for yakubi)

# Game state
notes = []
combo = 0
misses = 0
hannya_visible = False
hannya_hidden_behind = False
hannya_scale_base = 0.45

# Judgement display
judge_text = ""
judge_time_end = 0.0

# Settings
offset_seconds = 0.0
yakubi_mode = False   # 厄日モード checkbox

# Gimmicks tracking
triggered_gimmicks = []
GIMMICK_DESCRIPTIONS = {
    "shake_small": "軽い画面の揺れ（短時間）",
    "shake_big": "大きな画面の揺れ（長時間）",
    "rotate60": "画面が大きく傾く（最大60°）",
    "flash": "赤いフラッシュが発生する",
    "slowmo": "ノーツの見かけがだんだん遅くなる（表示のみ）",
    "lane_wobble": "レーンが左右にぶれてノーツが揺れる（枠全体が揺れます）",
    "ghost": "ノーツが半透明（見えにくくなる）",
    "spawn_rush": "灰色のダミーノーツが出現して惑わす",
    "blackout": "短時間暗転する",
    "invert": "疑似的な色調反転で不穏にする"
}

# New gimmick notification
new_gimmick_timer = 0.0
NEW_GIMMICK_DISPLAY_TIME = 4.0

# Outlined colours for judgement
OUTLINE_COLORS = {"PERFECT": (255,220,40), "GOOD": (220,40,40), "OK": (40,200,40), "MISS": (0,0,0)}

# Start delay (prep time) in seconds
START_PREP_DELAY = 1.6

# Gimmick thresholds
GIMMICK_COMBO_THRESHOLD = 20  # 20 combos by default

# ----------------- Drawing helpers -----------------
def draw_outlined_text(text, font, inner_color, outline_color, pos, outline_width=2):
    txt = font.render(text, True, inner_color)
    w,h = txt.get_size()
    surf = pygame.Surface((w + outline_width*2, h + outline_width*2), pygame.SRCALPHA)
    for dx in range(-outline_width, outline_width+1):
        for dy in range(-outline_width, outline_width+1):
            if dx == 0 and dy == 0: continue
            surf.blit(font.render(text, True, outline_color), (dx+outline_width, dy+outline_width))
    surf.blit(txt, (outline_width, outline_width))
    rect = surf.get_rect(center=pos)
    screen.blit(surf, rect)

def draw_bold_on_white(text, font, text_color, pos, padding=(8,4)):
    txt = font.render(text, True, text_color)
    tw,th = txt.get_size()
    w = tw + padding[0]*2
    h = th + padding[1]*2
    surf = pygame.Surface((w,h), pygame.SRCALPHA)
    surf.fill((255,255,255))  # white background
    surf.blit(txt, (padding[0], padding[1]))
    rect = surf.get_rect(bottomright=pos)
    screen.blit(surf, rect)
    return rect  # so caller can know area (not needed but available)

# ----------------- Audio functions -----------------
def play_bgm_once():
    global start_time_s, next_beat_time, spawn_index, prep_end_time
    if BGM:
        try:
            BGM.stop(); BGM.set_volume(0.95); BGM.play()
        except Exception:
            pass
    # We'll start beat timing after PREP_DELAY to give player prep time
    start_time_s = now_s()
    prep_end_time = start_time_s + START_PREP_DELAY
    next_beat_time = prep_end_time + offset_seconds
    spawn_index = 0
    spawned_target_times.clear()
    global note_spawn_counter
    note_spawn_counter = 0

def stop_bgm():
    if BGM:
        try: BGM.stop()
        except: pass

def play_bgm_soft_loop():
    if BGM:
        try:
            BGM.stop(); BGM.set_volume(0.18); BGM.play(loops=-1)
        except Exception:
            pass

def play_se(s):
    if s:
        try: s.play()
        except Exception:
            pass

# ----------------- Note class -----------------
class Note:
    def __init__(self, target_time, x, dummy=False):
        self.target_time = target_time
        self.spawn_time = target_time - NOTE_TRAVEL_SEC
        self.x = x
        self.start_y = -60
        self.hit_y = HITLINE_Y
        self.y = self.start_y
        self.hit = False
        self.dead = False
        self.dummy = dummy

    def update(self, t_now):
        total = max(0.001, NOTE_TRAVEL_SEC)
        p = (t_now - self.spawn_time) / total
        p = clamp(p, 0.0, 1.0)
        # linear motion for constant speed
        self.y = self.start_y + (self.hit_y - self.start_y) * p
        # disappear immediately after judgement window to keep view clear
        grace = OK_WINDOW * DIFF_WINDOW[DIFFICULTY] + 0.01
        if t_now - self.target_time > grace:
            self.dead = True

    def draw(self, ox=0, oy=0, ghost=False, lane_wobble_amt=0.0, play_area_offset=(0,0)):
        wob = 0
        if lane_wobble_amt != 0.0:
            phase = (self.spawn_time + self.y) * 0.085
            wob = math.sin(phase + time.time()*2.5) * lane_wobble_amt
        if self.dummy:
            col = (150,150,150) if not ghost else (130,130,130)
        else:
            col = (220,220,220) if ghost else (255,255,255)
        x = int(self.x + wob + ox + play_area_offset[0])
        y = int(self.y + oy + play_area_offset[1])
        pygame.draw.circle(screen, col, (x, y), NOTE_RADIUS)

# ----------------- Scheduling notes (beat-synced) -----------------
def schedule_notes_up_to(t_now):
    global spawn_index, next_beat_time, note_spawn_counter
    if next_beat_time is None:
        return
    while True:
        beat_time = next_beat_time + spawn_index * SPB
        spawn_time = beat_time - NOTE_TRAVEL_SEC
        if spawn_time <= t_now:
            if beat_time not in spawned_target_times:
                notes.append(Note(target_time=beat_time, x=LANE_X, dummy=False))
                spawned_target_times.add(beat_time)
                note_spawn_counter += 1
                # If yakubi mode: trigger gimmick every 10 notes spawned
                if yakubi_mode and (note_spawn_counter % 10 == 0):
                    trigger_random_gimmick_by_name(note_spawn_counter)
            spawn_index += 1
        else:
            break

# ----------------- Judgement -----------------
def compute_judgement(dt):
    w = DIFF_WINDOW[DIFFICULTY]
    if dt <= PERFECT_WINDOW * w: return "PERFECT"
    if dt <= GOOD_WINDOW * w: return "GOOD"
    if dt <= OK_WINDOW * w: return "OK"
    return "MISS"

def hit_check():
    global combo, misses, judge_text, judge_time_end, hannya_visible, hannya_hidden_behind, new_gimmick_timer
    tnow = now_s()
    best = None; best_dt = 1e9
    for n in notes:
        if n.dead or n.hit or n.dummy: continue
        dt = abs(n.target_time - tnow)
        if dt < best_dt:
            best_dt = dt; best = n
    if best:
        judg = compute_judgement(best_dt)
        if judg != "MISS":
            try: notes.remove(best)
            except: pass
            combo += 1
            # If not yakubi mode, trigger by combo threshold
            if not yakubi_mode and (combo % GIMMICK_COMBO_THRESHOLD == 0):
                trigger_random_gimmick_by_name(combo)
            play_se(SE_HIT)
        else:
            combo = 0
            misses += 1
            play_se(SE_MISS)
            if not hannya_visible: hannya_visible = True
            if misses >= HIDE_STEP and misses < MISS_LIMIT_MAP[DIFFICULTY]:
                hannya_hidden_behind = True
        judge_text = judg
        judge_time_end = tnow + 0.7
    else:
        combo = 0
        misses += 1
        play_se(SE_MISS)
        judge_text = "MISS"
        judge_time_end = now_s() + 0.7
        if not hannya_visible: hannya_visible = True
        if misses >= HIDE_STEP and misses < MISS_LIMIT_MAP[DIFFICULTY]:
            hannya_hidden_behind = True

# ----------------- Gimmicks -----------------
def record_gimmick(name):
    global new_gimmick_timer
    if name not in triggered_gimmicks:
        triggered_gimmicks.append(name)
        new_gimmick_timer = NEW_GIMMICK_DISPLAY_TIME

def trigger_random_gimmick_by_name(context_val):
    # choose random gimmick, record it, set effect timers
    opts = ["shake_small","shake_big","rotate60","flash","slowmo","lane_wobble","ghost","spawn_rush","blackout","invert", None]
    choice = random.choice(opts)
    if choice is None:
        return
    record_gimmick(choice)
    # intensity scales with misses
    intensity = 1.0 + (misses / max(1, MISS_LIMIT_MAP[DIFFICULTY])) * 1.5
    if choice == "shake_small":
        effects["shake_small"] = 1.6 * intensity
    elif choice == "shake_big":
        effects["shake_big"] = 2.8 * intensity
    elif choice == "rotate60":
        effects["rotate60"] = 3.6 * intensity
    elif choice == "flash":
        effects["flash"] = 0.6 * intensity
    elif choice == "slowmo":
        effects["slowmo"] = 5.0 * intensity
    elif choice == "lane_wobble":
        effects["lane_wobble"] = 4.0 * intensity
    elif choice == "ghost":
        effects["ghost"] = 4.0 * intensity
    elif choice == "spawn_rush":
        effects["spawn_rush"] = 6.0 * intensity
    elif choice == "blackout":
        effects["blackout"] = 3.0 * intensity
    elif choice == "invert":
        effects["invert"] = 4.0 * intensity

# ----------------- Neck snap (final kill) -----------------
def neck_snap_and_gameover():
    surf = screen.copy()
    seq = [(-12,140), (7,140), (180,260)]
    for angle, delay in seq:
        tmp = pygame.transform.rotozoom(surf, angle, 1.02 if abs(angle) < 90 else 1.0)
        r = tmp.get_rect(center=(WIDTH//2, HEIGHT//2))
        screen.fill((0,0,0))
        screen.blit(tmp, r)
        pygame.display.flip()
        pygame.time.delay(delay)
    pygame.time.delay(220)

# ----------------- Auto-miss when timed out -----------------
def register_auto_miss():
    global combo, misses, judge_text, judge_time_end, hannya_visible, hannya_hidden_behind
    combo = 0
    misses += 1
    play_se(SE_MISS)
    judge_text = "MISS"
    judge_time_end = now_s() + 0.7
    if not hannya_visible: hannya_visible = True
    if misses >= HIDE_STEP and misses < MISS_LIMIT_MAP[DIFFICULTY]:
        hannya_hidden_behind = True

# ----------------- Rendering -----------------
def draw_frame_bg():
    screen.fill((0,0,0))
    screen.blit(BG_IMG, (0,0))

def render_start(show_gimmicks_panel=False):
    draw_frame_bg()
    # Buttons: Start (left), Settings (center), Gimmicks (right) — ensure Settings is centered
    srect = pygame.Rect(WIDTH//2 - 160, HEIGHT//2 - 40, 140, 64)  # Start left of center
    crect = pygame.Rect(WIDTH//2 - 70, HEIGHT//2 - 40, 140, 64)   # Settings centered
    gimm_rect = pygame.Rect(WIDTH//2 + 20 + 80, HEIGHT//2 - 40, 140, 64)  # Gimmicks right
    pygame.draw.rect(screen, (255,255,255), srect, border_radius=8)
    draw_outlined_text("Start", FONT_MD, (0,0,0), (255,255,255), srect.center, outline_width=2)
    pygame.draw.rect(screen, (200,200,200), crect, border_radius=8)
    draw_outlined_text("Settings", FONT_MD, (0,0,0), (200,200,200), crect.center, outline_width=2)
    pygame.draw.rect(screen, (220,220,220), gimm_rect, border_radius=8)
    draw_outlined_text("異変", FONT_MD, (0,0,0), (220,220,220), gimm_rect.center, outline_width=2)

    if show_gimmicks_panel:
        w,h = 520, 320
        px,py = WIDTH//2 - w//2, HEIGHT//2 + 60
        panel = pygame.Surface((w,h), pygame.SRCALPHA)
        panel.fill((8,8,8,220))
        screen.blit(panel, (px,py))
        draw_outlined_text("発現した異変一覧", FONT_MD, (255,255,255), (0,0,0), (px + w//2, py + 30), outline_width=1)
        if not triggered_gimmicks:
            draw_outlined_text("まだ異変は発現していません", FONT_SM, (200,200,200), (0,0,0), (px + w//2, py + 80), outline_width=1)
        else:
            yy = py + 70
            for name in triggered_gimmicks:
                desc = GIMMICK_DESCRIPTIONS.get(name, "説明なし")
                draw_outlined_text(f"- {name}: {desc}", FONT_SM, (220,220,220), (0,0,0), (px + 20 + 300, yy), outline_width=1)
                yy += 34

    pygame.display.flip()

def render_settings():
    screen.fill((0,0,0))
    draw_outlined_text("Settings", FONT_LG, (255,255,255), (0,0,0), (WIDTH//2, 100), outline_width=2)
    draw_outlined_text(f"Difficulty: {DIFFICULTY}  (←/→)", FONT_MD, (220,220,220), (0,0,0), (WIDTH//2, 170), outline_width=1)
    draw_outlined_text(f"Judge pos: {'上' if DIFFICULTY_JUDGEPOS=='top' else '下'}  (↑/↓)", FONT_MD, (220,220,220), (0,0,0), (WIDTH//2, 220), outline_width=1)
    draw_outlined_text(f"Offset: {offset_seconds:+.3f}s  ([ / ] で調整)", FONT_MD, (200,200,200), (0,0,0), (WIDTH//2, 270), outline_width=1)
    # Yakubi mode checkbox
    checkbox_rect = pygame.Rect(WIDTH//2 - 140, 320, 20, 20)
    pygame.draw.rect(screen, (255,255,255), checkbox_rect, border_radius=3)
    if yakubi_mode:
        pygame.draw.line(screen, (200,20,20), (checkbox_rect.left+4, checkbox_rect.top+10), (checkbox_rect.right-4, checkbox_rect.top+10), 3)
    draw_outlined_text("厄日モード (Yakubi): 異変が10ノーツごとに発生", FONT_SM, (220,220,220), (0,0,0), (WIDTH//2 + 60, 330), outline_width=1)

    # Done button
    done_rect = pygame.Rect(WIDTH//2 - 70, HEIGHT//2 + 140, 140, 48)
    pygame.draw.rect(screen, (200,200,200), done_rect, border_radius=8)
    draw_outlined_text("完了", FONT_MD, (0,0,0), (200,200,200), done_rect.center, outline_width=1)
    pygame.display.flip()

def render_game(prep_countdown=None, play_area_offset=(0,0), show_new_notice_rect=None):
    global slowmo_current, slowmo_target
    draw_frame_bg()
    tnow = now_s()

    # schedule notes (only after prep_end_time)
    if next_beat_time is not None:
        schedule_notes_up_to(tnow)

    # update slowmo visual (does not change timing)
    if effects["slowmo"] > 0:
        slowmo_target = 0.55
    else:
        slowmo_target = 1.0
    ramp_speed = 0.6
    slowmo_current += (slowmo_target - slowmo_current) * min(1.0, ramp_speed * (1.0/FPS))

    # update notes and remove timed-out ones immediately
    for n in list(notes):
        n.update(tnow)
        if n.dead:
            try: notes.remove(n)
            except: pass
            register_auto_miss()

    # spawn dummy notes (spawn_rush)
    if effects["spawn_rush"] > 0 and random.random() < 0.03:
        notes.append(Note(target_time=tnow + NOTE_TRAVEL_SEC*0.5, x=LANE_X, dummy=True))

    # lane wobble amplitude
    lane_wobble_amt = 0.0
    if effects["lane_wobble"] > 0:
        base = 30.0
        intensity = 1.0 + (misses / max(1, MISS_LIMIT_MAP[DIFFICULTY])) * 1.2
        lane_wobble_amt = base * intensity

    # play area shake offsets (when shake_small/shake_big or lane_wobble active, the whole PLAY_AREA shakes)
    play_area_ox = play_area_oy = 0
    if effects["shake_small"] > 0:
        play_area_ox = int(math.sin(time.time()*8.0) * 6)
        play_area_oy = int(math.cos(time.time()*7.0) * 4)
    if effects["shake_big"] > 0:
        play_area_ox += int(math.sin(time.time()*10.0) * 14)
        play_area_oy += int(math.cos(time.time()*8.5) * 10)
    if effects["lane_wobble"] > 0:
        # smaller overall sway added
        play_area_ox += int(math.sin(time.time()*5.0) * (lane_wobble_amt*0.25))

    # camera offsets (small additional)
    cam_ox = cam_oy = 0

    # draw play area border (white) with applied play_area offsets
    pa_rect = pygame.Rect(PLAY_AREA.left + play_area_ox, PLAY_AREA.top + play_area_oy, PLAY_AREA.width, PLAY_AREA.height)
    pygame.draw.rect(screen, (255,255,255), pa_rect, width=4)

    # HUD (center top)
    draw_outlined_text(f"COMBO {combo}", FONT_MD, (255,215,0), (0,0,0), (WIDTH//2 + cam_ox, 30 + cam_oy), outline_width=2)
    draw_outlined_text(f"MISS {misses}/{MISS_LIMIT_MAP[DIFFICULTY]}", FONT_SM, (255,120,120), (0,0,0), (WIDTH//2 + cam_ox, 64 + cam_oy), outline_width=1)

    # left-top mark inside play area (account for play area offset)
    draw_outlined_text("お経開始", FONT_SM, (255,255,255), (0,0,0), (PLAY_AREA.left + 70 + play_area_ox, PLAY_AREA.top + 24 + play_area_oy), outline_width=1)

    # hitline matching play area inner extents
    hl_left = PLAY_AREA.left + 8 + play_area_ox
    hl_right = PLAY_AREA.right - 8 + play_area_ox
    pygame.draw.line(screen, (0,0,0), (hl_left, HITLINE_Y + play_area_oy), (hl_right, HITLINE_Y + play_area_oy), 4)

    # judgement text ABOVE the hitline
    if judge_text and now_s() < judge_time_end:
        out_c = OUTLINE_COLORS.get(judge_text, (0,0,0))
        draw_outlined_text(judge_text, FONT_MD, (255,255,255), out_c, (LANE_X + play_area_ox, HITLINE_Y - 48 + play_area_oy), outline_width=2)

    # draw notes; pass play_area_offset for entire-lane wobble
    ghost_flag = effects["ghost"] > 0
    for n in notes:
        n.draw(ox=0, oy=0, ghost=ghost_flag, lane_wobble_amt=lane_wobble_amt, play_area_offset=(play_area_ox, play_area_oy))

    # draw mokugyo (small) inside play area
    mok_rect = MOKUGYO_IMG.get_rect()
    mok_rect.center = (LANE_X - 30 + play_area_ox, MOKUGYO_CENTER[1] + play_area_oy)
    screen.blit(MOKUGYO_IMG, mok_rect)

    # draw hannya (on right side)
    if hannya_visible and not hannya_hidden_behind:
        maxp = max(1, MISS_LIMIT_MAP[DIFFICULTY] - 1)
        prog = min(misses / float(maxp), 1.0) if maxp > 0 else 1.0
        scale = hannya_scale_base + prog * 0.9
        img = pygame.transform.rotozoom(HANNYA_IMG, 0, scale)
        rect = img.get_rect(center=(HANNYA_TARGET_X, HANNYA_TARGET_Y))
        screen.blit(img, rect)

    # overlays (flash, blackout, invert)
    if effects["flash"] > 0:
        alpha = int(200 * min(1.0,effects["flash"]))
        s = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        s.fill((255,60,60,alpha))
        screen.blit(s, (0,0))
    if effects["blackout"] > 0:
        s = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        s.fill((0,0,0,int(220*min(1.0,effects["blackout"]))))
        screen.blit(s, (0,0))
    if effects["invert"] > 0:
        s = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        s.fill((180,180,255,int(90*min(1.0,effects["invert"]))))
        screen.blit(s, (0,0))

    # show prep countdown near center if within prep
    if 'prep_end_time' in globals() and prep_end_time and now_s() < prep_end_time:
        remain = max(0.0, prep_end_time - now_s())
        txt = f"Start in {int(math.ceil(remain))}"
        draw_outlined_text(txt, FONT_LG, (255,255,255), (0,0,0), (WIDTH//2, HEIGHT//2 - 40), outline_width=2)

    # show new gimmick notification (bottom-right) with white background and bold text if timer active
    if new_gimmick_timer > 0:
        txt = "新しい異変が発現しました。"
        # draw white rect + bold text (so it doesn't persist beyond timer)
        draw_bold_on_white(txt, FONT_BOLD, (200,30,30), (WIDTH - 12, HEIGHT - 12))

    pygame.display.flip()

def render_gameover():
    draw_frame_bg()
    draw_outlined_text("GAME OVER", FONT_LG, (255,200,200), (0,0,0), (WIDTH//2, HEIGHT//2 - 120), outline_width=2)
    draw_outlined_text("殺されてしまった…", FONT_MD, (255,120,120), (0,0,0), (WIDTH//2, HEIGHT//2 - 60), outline_width=1)
    # Buttons: Restart | Settings | Title
    bx = WIDTH//2 - 300
    by = HEIGHT//2 + 40
    w = 160; h = 56; gap = 40
    r1 = pygame.Rect(bx, by, w, h)
    r2 = pygame.Rect(bx + (w + gap), by, w, h)
    r3 = pygame.Rect(bx + 2*(w + gap), by, w, h)
    pygame.draw.rect(screen, (255,255,255), r1, border_radius=8)
    draw_outlined_text("Restart", FONT_MD, (0,0,0), (255,255,255), r1.center, outline_width=1)
    pygame.draw.rect(screen, (200,200,200), r2, border_radius=8)
    draw_outlined_text("Settings", FONT_MD, (0,0,0), (200,200,200), r2.center, outline_width=1)
    pygame.draw.rect(screen, (220,220,220), r3, border_radius=8)
    draw_outlined_text("Title", FONT_MD, (0,0,0), (220,220,220), r3.center, outline_width=1)
    pygame.display.flip()

def render_clear():
    draw_frame_bg()
    draw_outlined_text("CLEAR!", FONT_LG, (120,220,240), (0,0,0), (WIDTH//2, HEIGHT//2 - 60), outline_width=2)
    draw_outlined_text("お経を終えた…", FONT_MD, (160,220,240), (0,0,0), (WIDTH//2, HEIGHT//2), outline_width=1)
    pygame.display.flip()

def draw_frame_bg():
    screen.fill((0,0,0))
    screen.blit(BG_IMG, (0,0))

# ----------------- Main loop -----------------
DIFFICULTY_JUDGEPOS = "bottom"
running = True
show_gimmicks_panel = False

# Ensure initial globals
start_time_s = None
next_beat_time = None
spawn_index = 0
spawned_target_times = set()
note_spawn_counter = 0
prep_end_time = None

while running:
    dt = clock.tick(FPS) / 1000.0
    tnow = now_s()

    # Event handling
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:
            running = False

        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            mx,my = ev.pos
            if scene == SCENE_START:
                # Start button (left), Settings (center), Gimmicks (right)
                srect = pygame.Rect(WIDTH//2 - 160, HEIGHT//2 - 40, 140, 64)
                crect = pygame.Rect(WIDTH//2 - 70, HEIGHT//2 - 40, 140, 64)
                gimm_rect = pygame.Rect(WIDTH//2 + 20 + 80, HEIGHT//2 - 40, 140, 64)
                if srect.collidepoint((mx,my)):
                    notes.clear(); combo=0; misses=0; hannya_visible=False; hannya_hidden_behind=False
                    start_time_s = now_s()
                    prep_end_time = start_time_s + START_PREP_DELAY
                    next_beat_time = prep_end_time + offset_seconds
                    spawn_index = 0; spawned_target_times.clear()
                    note_spawn_counter = 0
                    judge_text=""; judge_time_end=0
                    show_gimmicks_panel = False
                    if BGM: play_bgm_once()
                    scene = SCENE_GAME
                elif crect.collidepoint((mx,my)):
                    scene = SCENE_SETTINGS
                elif gimm_rect.collidepoint((mx,my)):
                    show_gimmicks_panel = not show_gimmicks_panel

            elif scene == SCENE_SETTINGS:
                # Done button region
                done_rect = pygame.Rect(WIDTH//2 - 70, HEIGHT//2 + 140, 140, 48)
                # Yakubi checkbox area
                checkbox_rect = pygame.Rect(WIDTH//2 - 140, 320, 20, 20)
                if done_rect.collidepoint((mx,my)):
                    scene = SCENE_START
                elif checkbox_rect.collidepoint((mx,my)):
                    yakubi_mode = not yakubi_mode

            elif scene == SCENE_GAME:
                # Click on mokugyo
                mok_rect = MOKUGYO_IMG.get_rect(center=(LANE_X - 30, MOKUGYO_CENTER[1]))
                if mok_rect.collidepoint((mx,my)):
                    hit_check()

            elif scene == SCENE_GAMEOVER:
                # buttons: Restart | Settings | Title
                bx = WIDTH//2 - 300; by = HEIGHT//2 + 40; w=160; h=56; gap=40
                r1 = pygame.Rect(bx, by, w, h)
                r2 = pygame.Rect(bx + (w + gap), by, w, h)
                r3 = pygame.Rect(bx + 2*(w + gap), by, w, h)
                if r1.collidepoint((mx,my)):
                    # Restart
                    notes.clear(); combo=0; misses=0; hannya_visible=False; hannya_hidden_behind=False
                    start_time_s = now_s(); prep_end_time = start_time_s + START_PREP_DELAY
                    next_beat_time = prep_end_time + offset_seconds
                    spawn_index = 0; spawned_target_times.clear()
                    note_spawn_counter = 0
                    if BGM: play_bgm_once()
                    scene = SCENE_GAME
                elif r2.collidepoint((mx,my)):
                    scene = SCENE_SETTINGS
                elif r3.collidepoint((mx,my)):
                    scene = SCENE_START

            elif scene == SCENE_CLEAR:
                # Restart same as gameover restart
                bx = WIDTH//2 - 300; by = HEIGHT//2 + 40; w=160; h=56; gap=40
                r1 = pygame.Rect(bx, by, w, h)
                r2 = pygame.Rect(bx + (w + gap), by, w, h)
                r3 = pygame.Rect(bx + 2*(w + gap), by, w, h)
                if r1.collidepoint((mx,my)):
                    notes.clear(); combo=0; misses=0; hannya_visible=False; hannya_hidden_behind=False
                    start_time_s = now_s(); prep_end_time = start_time_s + START_PREP_DELAY
                    next_beat_time = prep_end_time + offset_seconds
                    spawn_index = 0; spawned_target_times.clear()
                    note_spawn_counter = 0
                    if BGM: play_bgm_once()
                    scene = SCENE_GAME
                elif r2.collidepoint((mx,my)):
                    scene = SCENE_SETTINGS
                elif r3.collidepoint((mx,my)):
                    scene = SCENE_START

        elif ev.type == pygame.KEYDOWN:
            if scene == SCENE_START:
                if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    notes.clear(); combo=0; misses=0; hannya_visible=False; hannya_hidden_behind=False
                    start_time_s = now_s(); prep_end_time = start_time_s + START_PREP_DELAY
                    next_beat_time = prep_end_time + offset_seconds
                    spawn_index = 0; spawned_target_times.clear()
                    note_spawn_counter = 0
                    judge_text=""; judge_time_end=0
                    if BGM: play_bgm_once()
                    scene = SCENE_GAME
                elif ev.key == pygame.K_s:
                    scene = SCENE_SETTINGS
                elif ev.key == pygame.K_g:
                    show_gimmicks_panel = not show_gimmicks_panel

            elif scene == SCENE_SETTINGS:
                if ev.key == pygame.K_ESCAPE:
                    scene = SCENE_START
                elif ev.key == pygame.K_LEFT:
                    if DIFFICULTY == "normal": DIFFICULTY = "easy"
                    elif DIFFICULTY == "hard": DIFFICULTY = "normal"
                elif ev.key == pygame.K_RIGHT:
                    if DIFFICULTY == "easy": DIFFICULTY = "normal"
                    elif DIFFICULTY == "normal": DIFFICULTY = "hard"
                elif ev.key in (pygame.K_UP, pygame.K_DOWN):
                    DIFFICULTY_JUDGEPOS = "top" if DIFFICULTY_JUDGEPOS == "bottom" else "bottom"
                elif ev.key == pygame.K_LEFTBRACKET:
                    offset_seconds -= 0.02
                elif ev.key == pygame.K_RIGHTBRACKET:
                    offset_seconds += 0.02
                elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    scene = SCENE_START
                elif ev.key == pygame.K_y:  # quick toggle yakubi with 'y'
                    yakubi_mode = not yakubi_mode

            elif scene == SCENE_GAME:
                if ev.key == pygame.K_SPACE:
                    hit_check()

            elif scene in (SCENE_GAMEOVER, SCENE_CLEAR):
                if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    notes.clear(); combo=0; misses=0; hannya_visible=False; hannya_hidden_behind=False
                    start_time_s = now_s(); prep_end_time = start_time_s + START_PREP_DELAY
                    next_beat_time = prep_end_time + offset_seconds
                    spawn_index = 0; spawned_target_times.clear()
                    note_spawn_counter = 0
                    if BGM: play_bgm_once()
                    scene = SCENE_GAME
                elif ev.key == pygame.K_s:
                    scene = SCENE_SETTINGS

    # Tick down effect timers & new gimmick timer
    for k in list(effects.keys()):
        if effects[k] > 0:
            effects[k] = max(0.0, effects[k] - dt)
    if new_gimmick_timer > 0:
        new_gimmick_timer = max(0.0, new_gimmick_timer - dt)

    # Scenes
    if scene == SCENE_START:
        render_start(show_gimmicks_panel)
        continue

    if scene == SCENE_SETTINGS:
        render_settings()
        continue

    if scene == SCENE_GAME:
        # If still in prep delay, show countdown but don't spawn notes until prep_end_time
        if 'prep_end_time' in globals() and prep_end_time and now_s() < prep_end_time:
            # simply render game status with countdown
            render_game()
            continue

        # schedule notes up to now
        if next_beat_time is not None:
            schedule_notes_up_to(now_s())

        # update notes and remove timed-out
        for n in list(notes):
            n.update(now_s())
            if n.dead:
                try: notes.remove(n)
                except: pass
                register_auto_miss()

        # spawn dummy notes when spawn_rush is active
        if effects["spawn_rush"] > 0 and random.random() < 0.03:
            notes.append(Note(target_time=now_s() + NOTE_TRAVEL_SEC*0.5, x=LANE_X, dummy=True))

        # BGM end -> CLEAR
        if BGM_LENGTH and start_time_s:
            if now_s() - start_time_s > BGM_LENGTH + START_PREP_DELAY:  # account for prep delay
                stop_bgm()
                play_bgm_soft_loop()
                scene = SCENE_CLEAR

        # Miss limit -> final sequence
        if misses >= MISS_LIMIT_MAP[DIFFICULTY]:
            hannya_hidden_behind = True
            neck_snap_and_gameover()
            stop_bgm()
            scene = SCENE_GAMEOVER
            render_gameover()
            continue

        render_game()
        continue

    if scene == SCENE_GAMEOVER:
        render_gameover()
        continue

    if scene == SCENE_CLEAR:
        render_clear()
        continue

# Cleanup
pygame.quit()
sys.exit(0)
