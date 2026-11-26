import tkinter as tk
from tkinter import ttk
from coat_painter import BODY, HEAD, TAIL, BOB_X, BOB_Y, BOB_RADIUS, CoatPainter, leg_projection, heel_outline, coat_outline
from cat_colors import CatColors, PRESETS, KEY_BASE, KEY_ACCENTS
from cat_updates import UpdateReminder
import ctypes
from ctypes import wintypes
import time
import math
import argparse
import random
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass, field
from collections import deque
import os
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageFilter, ImageChops

parser = argparse.ArgumentParser()
parser.add_argument('--smoke-test', action='store_true')
args = parser.parse_args()
user32 = ctypes.windll.user32
try:
    user32.SetProcessDPIAware()
except Exception:
    pass
root = tk.Tk()
root.title('小黑猫 · 键盘伙伴')
root.overrideredirect(True)
root.attributes('-topmost', True)
root.configure(bg='#ff00ff')
root.wm_attributes('-transparentcolor', '#ff00ff')
W, H = 400, 414
colors = CatColors(root)
root.attributes('-alpha', 1 - colors.transparency_percent / 100)

class PetCanvas(tk.Canvas):
    """Draw in the original pose coordinates at the selected display size."""
    keyboard_style = None
    keyboard_tags = ()

    def set_brightness(self, percent):
        self.keyboard_style = None
        # Darken towards black or lift towards white, retaining detail at both ends.
        change = (percent - 100) / 100
        self.tone = [round(i + change * (255-i if change > 0 else i)) for i in range(256)] if change else None
        self.display_color.cache_clear()

    @lru_cache(maxsize=512)
    def display_color(self, color):
        rgb = self.winfo_rgb(color)
        return '#%02x%02x%02x' % tuple(self.tone[channel // 257] for channel in rgb)

    def _create(self, item_type, args, options):
        if self.keyboard_tags:
            options['tags'] = self.keyboard_tags
        if self.tone is not None:
            for key in ('fill', 'outline'):
                if options.get(key):
                    options[key] = self.display_color(options[key])
        if self.zoom != 1:
            args = tuple(n * self.zoom for n in tk._flatten(args))
            options = options.copy()
            if 'width' in options:
                options['width'] *= self.zoom
            if 'font' in options:
                family, size, *styles = options['font']
                options['font'] = (family, max(1, round(size * self.zoom)), *styles)
        return super()._create(item_type, args, options)

    def photo(self, source, fur_base=None):
        if self.zoom != 1:
            source = source.resize(tuple(max(1, round(n * self.zoom)) for n in source.size),
                                   Image.Resampling.LANCZOS)
        if fur_base is not None:
            # Windows removes only exact color-key pixels. Blend soft coat edges
            # with fur before Tk draws them over the magenta window background.
            alpha = source.getchannel('A')
            fur = Image.new('RGBA', source.size, fur_base)
            fur.alpha_composite(source)
            fur.putalpha(alpha.point(lambda a: 255 if a >= 128 else 0))
            source = fur
        if self.tone is not None:
            source = source.convert('RGBA').point(self.tone * 3 + list(range(256)))
        return ImageTk.PhotoImage(source)

c = PetCanvas(root, bg='#ff00ff', highlightthickness=0)
c.set_brightness(colors.brightness_percent)
c.zoom = colors.size_percent / 100
width, height = round(W*c.zoom), round(H*c.zoom)
root.geometry('%dx%d+%d+%d' % (width,height,max(0,root.winfo_screenwidth()-width-45),
                                max(0,root.winfo_screenheight()-height-85)))
c.pack(fill='both', expand=True)
ink, cream, gold = '#191a1d', '#fff5d9', '#edc95b'
STROKE_TIME = .22
CONTACT_TIME = .14
SLEEP_AFTER = 20
CAT_ORIGIN_X = 42
paw_rest = {"left":(CAT_ORIGIN_X+331*.34,297.54),"right":(CAT_ORIGIN_X+447*.34,297.54)}

@dataclass
class PetPose:
    last_activity: float = field(default_factory=time.monotonic)
    mouse_work_until: float = 0
    mouse_blocked: bool = False
    mouse_active_until: float = 0
    last_key_time: float = 0
    mouse_offset: tuple = (0.,0.)
    mouse_lean: float = 0
    look_turn: float = 0
    head_pitch: float = 0
    eye_lowering: float = 0
    face_gaze_x: float = 0
    typing_balance: float = 0
    body_follow: tuple = (0.,0.)
    expression: str = ''
    expression_start: float = 0
    paused: bool = False
    drag: dict = None
    paw_positions: dict = field(default_factory=paw_rest.copy)
    targets: dict = field(default_factory=lambda:{'left':(145,320),'right':(225,320)})
    until: dict = field(default_factory=lambda:dict.fromkeys(paw_rest,0))
    stroke_start: dict = field(default_factory=lambda:dict.fromkeys(paw_rest,-10.))
    stroke_speed: dict = field(default_factory=lambda:dict.fromkeys(paw_rest,0.))
    stroke_key: dict = field(default_factory=lambda:dict.fromkeys(paw_rest))
    stroke_origin: dict = field(default_factory=paw_rest.copy)
    key_contact: dict = field(default_factory=dict)
    pressed_until: dict = field(default_factory=dict)
    click_started: dict = field(default_factory=dict)

live = PetPose()
previous = set()
last_mouse = None

def move_mini_mouse(offset, dx, dy):
    # The seated cat faces the user: its forward and right are screen-down and left.
    gain = .11
    return (max(-14, min(10, offset[0] - gain * dx)),
            max(-12, min(12, offset[1] - gain * dy)))
pet_count = 0
last_pet = -10.0
ANGER_DURATION = 2.4
keys = []
c.label_cache = {}
volume_cache = {}
windows_fonts = Path(os.environ['WINDIR']) / 'Fonts'
for font_name in ('msyh.ttc', 'segoeui.ttf', 'arial.ttf'):
    try:
        label_font = ImageFont.truetype(str(windows_fonts / font_name), 22)
        break
    except OSError:
        continue
else:
    label_font = ImageFont.load_default(size=22)
def keyrow(y, entries):
    x = 76
    for label, code, units, color in entries:
        width = units * 15.8
        keys.append((x,y,width-2,11,label,code,color))
        x += width
white = KEY_BASE
blue, pink, green, orange, aqua = KEY_ACCENTS
keyrow(300, [('Esc',27,1.5,pink)]+[('F'+str(i),111+i,1,white) for i in range(1,13)])
keyrow(314, [('`',192,1,white)]+[(v,ord(v),1,white) for v in '1234567890']+[('-',189,1,white),('=',187,1,white),('Back',8,2,pink)])
keyrow(328, [('Tab',9,1.5,blue)]+[(v,ord(v),1,white) for v in 'QWERTYUIOP']+[('[',219,1,white),(']',221,1,white),('\\',220,1.5,white)])
keyrow(342, [('Caps',20,1.8,green)]+[(v,ord(v),1,white) for v in 'ASDFGHJKL']+[(';',186,1,white),("'",222,1,white),('Enter',13,2.2,blue)])
keyrow(356, [('Shift',16,2.3,orange)]+[(v,ord(v),1,white) for v in 'ZXCVBNM']+[(',',188,1,white),('.',190,1,white),('/',191,1,white),('Shift',16,2.7,orange)])
keyrow(370, [('Ctrl',17,1.4,blue),('Win',91,1.2,white),('Alt',18,1.3,green),('空格',32,6.1,aqua),('Alt',18,1.3,green),('Win',92,1.2,white),('Ctrl',17,1.5,blue)])
def project(x, y, z=0):
    # Rotate the board towards the cat and project its plane into a slanted view.
    u = 1-(x-69)/252
    v = 1-(y-292)/95
    return (97-25*v+u*(219+40*v), 303+66*v+9*u-z)

key_positions = {code:project(x+w/2,y+h/2,6) for x,y,w,h,label,code,color in reversed(keys)}
show_keys = tk.BooleanVar(root, value=True)
floating_keys = []
FLOAT_SLOTS = 6
FLOAT_SPACING = 27
float_colors = KEY_ACCENTS
RISE_TIME, HOVER_TIME = .76, .5

def add_floating_key(code, now):
    if 96 <= code <= 105:
        code = ord('0') + code - 96
    if not (48 <= code <= 57 or 65 <= code <= 90):
        return
    x,y = key_positions[code]
    # Start near the middle after a pause; a full row wraps to the oldest slot.
    slot = (FLOAT_SLOTS-1)//2
    if floating_keys and now-floating_keys[-1][0] < RISE_TIME+HOVER_TIME:
        slot = (floating_keys[-1][-1]+1) % FLOAT_SLOTS
    if len(floating_keys) == FLOAT_SLOTS:
        floating_keys.pop(0)
    floating_keys.append((now,chr(code),random.choice(float_colors),x,y-13,slot))

def pale(color, amount):
    rgb = [int(color[i:i+2],16) for i in (1,3,5)]
    return '#'+''.join(f'{round(n+(245-n)*amount):02x}' for n in rgb)

DARK_PALETTE = {white:'#181a1d', blue:'#375875', pink:'#814650', green:'#4c633f',
                orange:'#815632', aqua:'#376565'}

def dark_color(color):
    if color in DARK_PALETTE:
        return DARK_PALETTE[color]
    if min(bytes.fromhex(color[1:])) >= 242:
        return DARK_PALETTE[white]
    return shade(color,.54)

def draw_floating_keys(now, chest):
    floating_keys[:] = [item for item in floating_keys if now-item[0] < RISE_TIME+HOVER_TIME]
    dark = colors.themes['浮字按键提示'].get()
    display_style = colors.floating_style.get()
    for born,label,color,x,y,slot in floating_keys:
        color=colors.palette_color('浮字按键提示',color)
        end_x = chest[0]+(slot-(FLOAT_SLOTS-1)/2)*FLOAT_SPACING
        end_y = chest[1]
        progress = min(1,(now-born)/RISE_TIME)
        travel = 1-(1-progress)**2
        cx = x+(end_x-x)*travel
        cy = y+(end_y-y)*travel
        face_color = pale(dark_color(color),.18*(1-progress)) if dark else pale(color,.75*(1-progress))
        if display_style == 'bubble':
            tint = dark_color(color) if dark else color
            radius = 7+4*travel
            # Sparse fill lets the cat and the transparent desktop show through.
            c.create_oval(cx-radius,cy-radius,cx+radius,cy+radius,
                          fill=pale(tint,.55),stipple='gray25',outline=shade(tint,.78),
                          width=2,tags='floating_key')
            c.create_arc(cx-radius+3,cy-radius+3,cx+radius-3,cy+radius-3,
                         start=95,extent=50,style=tk.ARC,outline=pale(tint,.8),
                         width=1,tags='floating_key')
            continue
        if display_style == 'keycap':
            c.create_line(cx-4,cy,cx+4,cy,width=18,capstyle=tk.ROUND,
                          fill=face_color,tags='floating_key')
            c.create_text(cx,cy,text=label,font=('Microsoft YaHei UI',9,'bold'),
                          fill='#ffffff' if dark else pale('#29363d',.32*(1-progress)),tags='floating_key')
            continue
        style = dict(text=label,font=('Microsoft YaHei UI',11,'bold'),tags='floating_key')
        if display_style == 'text':
            c.create_text(cx+1,cy+1,fill=shade(face_color,.68),**style)
            c.create_text(cx-1,cy-1,fill=pale(face_color,.72),**style)
            c.create_text(cx,cy,fill=face_color,**style)
            continue
        ink_color = {'black':'#000000','white':'#ffffff'}.get(display_style,colors.floating_ink)
        if ink_color == '#ff00ff':
            ink_color = '#fe00ff'
        c.create_text(cx,cy,fill=ink_color,**style)

def toggle_key_display():
    floating_keys.clear()
    c.delete('floating_key')
    floating_menu.entryconfigure('浮字样式', state='normal' if show_keys.get() else 'disabled')

def key_label(c,label, x, y, dark):
    label_cache = c.label_cache
    cache_key = (label, x, y, dark)
    if cache_key not in label_cache:
        # Render small type at 4x resolution, then map its plane using the
        # same local projection as the keycap (rotation, shear and foreshortening).
        src = Image.new('RGBA',(240,80))
        d = ImageDraw.Draw(src)
        d.text((120,40),label,font=label_font,anchor='mm',fill='#ffffff' if dark else '#000000')
        px,py = project(x,y)
        ax,ay = project(x+1,y)
        bx,by = project(x,y+1)
        a,b,cc,dd = ax-px,bx-px,ay-py,by-py
        det = a*dd-b*cc
        ia,ib,ic,id_ = dd/det,-b/det,-cc/det,a/det
        coeff=(4*ia,4*ib,120-4*ia*40-4*ib*20,
               4*ic,4*id_,40-4*ic*40-4*id_*20)
        out=src.transform((80,40),Image.Transform.AFFINE,coeff,Image.Resampling.BICUBIC)
        label_cache[cache_key]=c.photo(out)
    return label_cache[cache_key]

def quad(c,points, color, outline=''):
    return c.create_polygon(*[n for point in points for n in point],fill=color,outline=outline,width=1)

def shade(color, factor):
    return '#'+''.join('%02x'%min(255,int(int(color[i:i+2],16)*factor)) for i in (1,3,5))

def board_rect(x,y,w,h,z=0):
    return [project(x,y,z),project(x+w,y,z),project(x+w,y+h,z),project(x,y+h,z)]

def oval(c,x1,y1,x2,y2,fill,outline='',width=1):
    return c.create_oval(x1,y1,x2,y2,fill=fill,outline=outline,width=width)

def volume(name, points, box, dy=0, smooth=True):
    """Cached code-drawn surface with a soft upper-left light source."""
    if name not in volume_cache:
        x0,y0,x1,y1=box
        scale=3
        width,height=int((x1-x0)*scale),int((y1-y0)*scale)
        mask=Image.new('L',(width,height))
        outline=[]
        if smooth:
            for i,p in enumerate(points):
                prev=points[i-1];nxt=points[(i+1)%len(points)]
                a=((prev[0]+p[0])/2,(prev[1]+p[1])/2)
                b=((nxt[0]+p[0])/2,(nxt[1]+p[1])/2)
                for j in range(12):
                    t=j/12
                    outline.append(((1-t)**2*a[0]+2*(1-t)*t*p[0]+t*t*b[0],
                                    (1-t)**2*a[1]+2*(1-t)*t*p[1]+t*t*b[1]))
        else:
            outline=points
        ImageDraw.Draw(mask).polygon([((x-x0)*scale,(y-y0)*scale) for x,y in outline],fill=255)
        tex=Image.new('RGBA',(width,height))
        pixels=tex.load();alpha=mask.load()
        for py in range(height):
            for px in range(width):
                if not alpha[px,py]:
                    continue
                nx=(px/width-.5)*2;ny=(py/height-.5)*2
                nz=math.sqrt(max(0,1-nx*nx-ny*ny))
                diffuse=max(0,-.42*nx-.48*ny+.77*nz)
                sheen=math.exp(-((nx+.40)**2/.15+(ny+.42)**2/.28))
                tone=int(12+28*diffuse+9*sheen)
                pixels[px,py]=(tone,tone+2,tone+5,255)
        tex=tex.resize((int(x1-x0),int(y1-y0)),Image.Resampling.LANCZOS)
        volume_cache[name]=c.photo(tex)
    c.create_image(box[0],box[1]+dy,image=volume_cache[name],anchor='nw')

def round_volume(name,x,y,w,h,dy=0):
    points=[(x+w/2+math.cos(i*math.pi/24)*w/2,
             y+h/2+math.sin(i*math.pi/24)*h/2) for i in range(48)]
    volume(name,points,(x,y,x+w,y+h),dy,smooth=False)

def draw_paw(c,x,bottom,w,h,tag,fur,stroke,tip_color,wide_tip=False):
    c.create_oval(x-w,bottom-2*h,x+w,bottom,fill=fur,outline='',tags=tag)
    outer,inner=[],[]
    for degrees in range(0,181,3):
        angle=math.radians(degrees)
        dx,dy=math.cos(angle),math.sin(angle)
        thickness=(w*.21)*math.sin(angle)**1.15
        px,py=x+w*dx,bottom-h+h*dy
        normal=math.hypot(dx/w,dy/h)
        outer.append((px,py))
        if wide_tip:
            inner.append((px,bottom-h+.22*h*dy))
        else:
            inner.append((px-thickness*dx/(w*normal),py-thickness*dy/(h*normal)))
    c.create_polygon(*[v for point in outer+inner[::-1] for v in point],
                     fill=tip_color,outline='',smooth=True,tags=tag)
    if stroke:
        c.create_line(*[v for point in outer for v in point],fill=stroke,
                      width=1.5,smooth=True,capstyle=tk.ROUND,tags=tag)

c.coat_overlay = {}

def draw_coat_shading(c,shapes):
    # Match Tk's closed quadratic splines. Blur the combined silhouette so the
    # neck and patch boundaries stay continuous as the head and shoulders move.
    coat_overlay = c.coat_overlay
    geometry = tuple(tuple((round(x),round(y)) for x,y in shape) for shape in shapes)
    if geometry != coat_overlay.get('geometry'):
        points = [p for shape in geometry for p in shape]
        left,top = min(x for x,y in points)-2,min(y for x,y in points)-2
        size = (max(x for x,y in points)-left+3,max(y for x,y in points)-top+3)
        mask = Image.new('L',size,0)
        brush = ImageDraw.Draw(mask)
        for shape in geometry:
            path=[]
            for i,(x,y) in enumerate(shape):
                ax,ay=shape[i-1]
                bx,by=shape[(i+1)%len(shape)]
                for step in range(8):
                    t=step/8
                    path.append((x+((ax-x)*(1-t)**2+(bx-x)*t*t)/2-left,
                                 y+((ay-y)*(1-t)**2+(by-y)*t*t)/2-top))
            brush.polygon(path,fill=255)
        # Pad before blurring so all four sides have the same soft falloff.
        padded=Image.new('L',(size[0]+48,size[1]+48))
        padded.paste(mask,(24,24))
        blurred=padded.filter(ImageFilter.GaussianBlur(8)).crop((24,24,24+size[0],24+size[1]))
        alpha=ImageChops.subtract(mask,blurred).point(lambda n: min(38,round(n*.27)))
        alpha=ImageChops.multiply(alpha,mask.filter(ImageFilter.MinFilter(3)))
        tint=Image.new('RGBA',size,(0,0,0,0))
        tint.putalpha(alpha)
        coat_overlay.update(geometry=geometry,image=c.photo(tint),origin=(left,top))
    c.create_image(*coat_overlay['origin'],image=coat_overlay['image'],anchor='nw')

TOYS = ('paper', 'bubble', 'wand', 'box')


def ramp(value):
    t = max(0., min(1., value))
    return t*t*(3-2*t)


def passes_near(a, b, center, radius):
    dx, dy = b[0]-a[0], b[1]-a[1]
    t = max(0., min(1., ((center[0]-a[0])*dx+(center[1]-a[1])*dy)/max(1., dx*dx+dy*dy)))
    return math.dist((a[0]+t*dx, a[1]+t*dy), center) <= radius


class CatPlay:
    def __init__(self):
        self.kind = ''
        self.end = self.began = 0
        self.side = 'left'
        self.eyes = (175, 100)
        self.chin = (175, 137)
        self.face_item = None
        self.torso_item = None
        self.neck_bottom = 0
        self.tap_squint_until = 0
        self.target = self.eyes
        self.direction = self.turns = 0
        self.extreme = self.last_turn = 0
        self.hover = None
        self.hover_since = 0
        self.hover_origin = None
        self.paper_side = 'right'
        self.next_invite = 0
        self.invite_side = 'right'
        self.circle_path = deque()
        self.phase = ''
        self.previous_pointer = None
        self.point_time = 0
        self.fast_return = False
        self.swat_start = -100.
        self.aim = self.eyes
        self.anchor = None
        self.still_since = 0
        self.next_peek = math.inf
        self.exit_pose = (0., 0.)

    def begin(self, kind, now, duration, side):
        self.kind, self.began, self.end, self.side = kind, now, now+duration, side
        self.direction = self.turns = 0

    def start_toy(self, kind, now):
        if live.paused:
            return
        self.hover = self.previous_pointer = self.anchor = None
        self.circle_path.clear()
        self.swat_start = -100.
        self.fast_return = False
        self.phase = 'play'
        live.last_activity = now
        if kind == 'paper':
            self.paper_side = 'left' if self.paper_side=='right' else 'right'
        self.begin(kind, now, {'paper':6.55,'bubble':4.2,'wand':20.,'box':math.inf}[kind], self.paper_side)
        if kind == 'bubble':
            self.bubble_tint = random.choice(KEY_ACCENTS)
            self.bubble_miss = random.random() < .25
            self.target = self.bubble_position(now)
        elif kind == 'wand':
            self.target = (220, 157)
            self.still_since = now
        elif kind == 'box':
            self.box_entered = now
            self.target = (175, 222)
            self.next_peek = now+1.2+random.uniform(3.,5.)

    def toss(self):
        self.start_toy('paper', time.monotonic())

    def ball(self, now):
        t = max(0, min(1, (now-self.began)/self.paper_duration()))
        sign = -1 if self.side=='left' else 1
        # Roll in, meet the paw, then bounce back towards the same edge.
        distance = (1-t/.53)**1.2 if t<.53 else ((t-.53)/.47)**.8
        # Leave the returned ball beside the keyboard, within a short swipe.
        x = 185+sign*(52+62*distance)
        bounce = 12*abs(math.sin(math.pi*2*(t-.53)/.47))*(1-t) if t>.53 else 0
        return x, 312+9*distance-bounce

    def paper_duration(self):
        return .92 if self.fast_return else 1.55

    def bubble_position(self, now):
        t = min(1., max(0., (now-self.began)/4.2))
        sign = -1 if self.side == 'left' else 1
        return (178+sign*(40+15*math.sin(2*math.pi*t)), 304-274*t)

    def update_toy(self, now, cursor, typing):
        if typing:
            if self.kind != 'box':
                self.kind = ''
                return False
            if self.phase != 'exit':
                self.exit_pose = self.box_pose(now)
                self.phase, self.began, self.end = 'exit', now, now+.38
        previous = self.previous_pointer
        dt = max(.01, now-self.point_time)
        self.previous_pointer, self.point_time = cursor, now
        if self.kind == 'paper':
            self.target = self.ball(now)
            if now-self.began >= self.paper_duration() and previous:
                toward = 1 if self.side=='left' else -1
                dx = (cursor[0]-previous[0])*toward
                if dx > .25 and passes_near(previous, cursor, self.target, 15):
                    self.fast_return = dx/dt > 320
                    self.began = now
                    self.end = now+self.paper_duration()+5
        elif self.kind == 'bubble' and self.phase == 'play':
            self.target = self.bubble_position(now)
            age = now-self.began
            if previous and passes_near(previous, cursor, self.target, 13):
                self.pop(now)
            elif age >= 2.55 and self.swat_start < self.began:
                self.swat_start = now
                self.aim = self.bubble_position(now+.19)
                if self.bubble_miss:
                    self.aim = (self.aim[0], self.aim[1]+28)
            elif not self.bubble_miss and 0 <= now-self.swat_start < .45 and now-self.swat_start >= .19:
                self.pop(now)
        elif self.kind == 'wand':
            x, y = cursor
            if not (12 <= x <= W-12 and 18 <= y <= H-18):
                self.anchor = None
                self.still_since = now
                return True
            self.target = cursor
            if self.anchor is None or math.dist(cursor,self.anchor)>5:
                self.anchor, self.still_since = cursor, now
            elif now-self.still_since >= .7 and now-self.swat_start >= .85:
                self.aim, self.swat_start = cursor, now
                self.side = 'left' if x<175 else 'right'
                self.still_since = now
            # A successful catch makes the feather flutter. Moving it away is a dodge.
            if .17 <= now-self.swat_start <= .35 and math.dist(cursor,self.aim)<13 and math.dist(cursor,paw_rest[self.side])<154:
                self.phase = 'caught'
            elif now-self.swat_start > .45:
                self.phase = 'play'
        elif self.kind=='box' and self.phase!='exit' and now>=self.next_peek:
            side = random.choice((-1,1))
            self.begin_peek(now, side, .18)
            self.target = (175+side*64, 193)
        return True

    def pop(self, now):
        self.phase, self.pop_time, self.end = 'pop', now, now+.45

    def box_tail_fold(self, now):
        if self.phase == 'exit':
            folded = ramp((self.began-self.box_entered)/.28)
            return folded*(1-ramp((now-self.began-.20)/.18))
        return ramp((now-self.box_entered)/.28)

    def box_pose(self, now):
        age = now-self.began
        if self.phase == 'exit':
            f = 1-ramp(age/.38)
            return self.exit_pose[0]*f, self.exit_pose[1]*f
        tucked = ramp((age-.55)/.65)
        if self.phase == 'peek':
            rise = ramp((now-self.peek_time)/.28)
            visible = ramp((self.peek_time+1.25-now)/.38)
            start_tuck,start_x = self.peek_origin
            depth,offset = self.peek_target
            return (1-((1-start_tuck)*(1-rise)+depth*rise)*visible,
                    (start_x*(1-rise)+offset*rise)*visible)
        return tucked, 0.

    def begin_peek(self, now, side, depth):
        # A tap can redirect an ongoing peek without snapping back into the box.
        self.peek_origin = self.box_pose(now)
        self.peek_target = (depth, side*26*depth/.32)
        self.phase, self.peek_time = 'peek', now
        self.next_peek = now+1.25+random.uniform(3.,5.)

    def touch_box(self, now, point):
        x,y = point
        if self.kind=='box' and self.phase!='exit' and now-self.began>=1.2 and 70<=x<=282 and 200<=y<=240:
            self.begin_peek(now, -1 if x<176 else 1, .32)
            self.target = point
            return True
        return False

    def wand_motion(self, now):
        if self.kind != 'wand':
            return 0., 0., 0.
        wiggle = 0.
        if self.anchor is not None:
            until_swat = max(self.still_since+.7, self.swat_start+.85)-now
            envelope = ramp((.42-until_swat)/.13)*ramp(until_swat/.06)
            wiggle = envelope*math.sin(until_swat*math.tau*7)
        # Lock the pounce to the feather's position at takeoff, even if it dodges.
        age = now-self.swat_start
        reach = ramp(age/.18)*ramp((.50-age)/.28)
        sideways = max(-1., min(1., (self.aim[0]-175)/76))
        forward = max(0., min(1., (self.aim[1]-170)/125))
        return 24*sideways*reach, (4+12*(1-abs(sideways))+8*forward)*reach, wiggle

    def toy_paw(self, side, rest, now):
        if self.kind=='paper':
            t = (now-self.began)/self.paper_duration()
            amount = max(0., 1-abs(t-.53)/.26)
            if side!=self.side and not self.fast_return:
                return rest
            x,y = self.ball(now)
            x += (-8 if side=='left' else 8) if self.fast_return else 0
        elif self.kind in ('bubble','wand') and side==self.side:
            age = now-self.swat_start
            amount = ramp(age/.18)*ramp((.46-age)/.25)
            x,y = self.aim
            distance = max(1.,math.dist(rest,self.aim))
            amount *= min(1., (184 if self.kind=='bubble' else 154)/distance)
        else:
            return rest
        return rest[0]+(x-rest[0])*amount, rest[1]+(y-rest[1])*amount

    def near_face(self, cursor):
        x,y = cursor
        if abs(x-self.eyes[0])<85 and abs(y-self.eyes[1])<36:
            return True
        px,py = x*c.zoom,y*c.zoom
        return self.face_item in c.find_overlapping(px,py,px,py)

    def near_neck(self,cursor):
        x,y=cursor
        if self.torso_item is None or y>self.neck_bottom:
            return False
        px,py=x*c.zoom,y*c.zoom
        return self.torso_item in c.find_overlapping(px,py,px,py)

    def high_five(self,now):
        if self.kind in ('offer','invite'):
            self.begin('tap',now,.32,self.side)
            self.tap_squint_until=now+.65 if random.randrange(3)==0 else 0

    def nearby_paw(self, cursor):
        # The hand moves away from the pointer as it leaves the mouse. Keep
        # its approach path interactive so the user can follow it to the chest.
        if self.hover:
            ax,ay = self.hover_origin
            bx,by = live.paw_positions[self.hover]
            dx,dy = bx-ax,by-ay
            t = max(0,min(1,((cursor[0]-ax)*dx+(cursor[1]-ay)*dy)/max(1,dx*dx+dy*dy)))
            if math.dist(cursor,(ax+t*dx,ay+t*dy)) <= 32:
                return self.hover
        distances = {side:min(math.dist(cursor,point),math.dist(cursor,paw_rest[side]))
                     for side,point in live.paw_positions.items()}
        closest = min(distances,key=distances.get)
        return closest if distances[closest]<=24 else None

    def circling(self, now, cursor):
        path = self.circle_path
        if path and now-path[-1][0] > .35:
            path.clear()
        if path and math.dist(cursor,path[-1][1]) < 2:
            return False
        path.append((now,cursor))
        while len(path)>1 and path[1][0] <= now-3:
            path.popleft()
        if now-path[0][0] < 3:
            return False
        # Fit each second separately so circles can drift across the face.
        direction = 0
        for start in (now-3, now-2, now-1):
            points = [p for t,p in path if start-.05 <= t <= start+1]
            if len(points)<5:
                return False
            xs,ys = zip(*points)
            width,height = max(xs)-min(xs),max(ys)-min(ys)
            if min(width,height) < max(10,.28*max(width,height)):
                return False
            area2 = sum(x*v-y*u for (x,y),(u,v) in zip(points,points[1:]+points[:1]))
            if abs(area2)<.6*width*height:
                return False
            cx,cy = (max(xs)+min(xs))/2,(max(ys)+min(ys))/2
            angles = [math.atan2(y-cy,x-cx) for x,y in points]
            turns = [(b-a+math.pi)%math.tau-math.pi for a,b in zip(angles,angles[1:])]
            arc = sum(turns)
            if abs(arc)<1.5*math.pi or abs(arc)<.72*sum(map(abs,turns)) or arc*direction<0:
                return False
            direction = arc
        path.clear()
        return True

    def update(self, now, cursor, pressed, near):
        if now>=self.end:
            if self.kind=='tap':
                self.hover_since=now
            self.kind = ''
        if self.kind in TOYS and not live.paused:
            return self.update_toy(now, cursor, bool(pressed-{1,2}))
        if near and not (live.paused or live.drag or pressed) and self.kind in ('','tease'):
            if self.circling(now,cursor):
                self.begin('dizzy',now,2.4,'left')
        else:
            self.circle_path.clear()
        if live.drag and live.drag.get('rub') and not live.paused and not pressed:
            self.kind='chin'
            self.end=now+.5
        if live.paused or pressed.intersection(key_positions):
            if self.kind!='stretch' or live.paused:
                self.kind = ''
            self.hover = None
            self.direction = self.turns = 0
            return False
        if self.kind=='invite' and math.dist(cursor,live.paw_positions[self.side])<=19:
            self.high_five(now)
        if self.kind in ('offer','invite','tap'):
            self.direction = self.turns = 0
            return True
        if self.kind or live.drag or pressed:
            self.direction = self.turns = 0
            self.hover = None
            return bool(self.kind or (live.drag and live.drag.get('chin')))
        x,y = cursor
        if near:
            self.target = cursor
            if not self.direction or now-self.last_turn>.65:
                self.extreme, self.direction, self.turns, self.last_turn = x, 1, 0, now
            delta = (x-self.extreme)*self.direction
            if delta>0:
                self.extreme = x
            elif delta < -11:
                self.direction *= -1
                self.extreme, self.last_turn = x, now
                self.turns += 1
                if self.turns>=4:
                    self.target = cursor
                    self.begin('tease', now, .8, 'left' if x<self.eyes[0] else 'right')
        else:
            self.direction = self.turns = 0
        hover = self.nearby_paw(cursor)
        if hover!=self.hover:
            self.hover, self.hover_since = hover, now
            self.hover_origin = cursor if hover else None
        if hover and now-self.hover_since>.45:
            self.begin('offer', now, 1.6, hover)
        elif (not near and not hover and 10<=now-live.last_activity<13 and now>=self.next_invite
              and not (painter.window and painter.window.winfo_exists())):
            self.begin('invite',now,5,self.invite_side)
            self.invite_side='left' if self.invite_side=='right' else 'right'
            self.next_invite=now+60
        return near or bool(hover)

    def paw(self, now, rest):
        x,y = rest
        sign = -1 if self.side=='left' else 1
        t = max(0,min(1,(now-self.began)/(self.end-self.began)))
        if self.kind in ('offer','invite','tap'):
            return x+sign*8, y-(52+8*math.sin(math.pi*t) if self.kind=='tap' else 52)
        gx,gy = self.target
        amount = math.sin(math.pi*max(0,min(1,(t-.24)/.7)))
        gy = max(gy, y-107)
        return x+(gx-x)*amount,y+(gy-y)*amount

play = CatPlay()

def draw(now, mouse, pressed):
    render_scene(c,painter,play,live,now,mouse,pressed)

def draw_box(canvas, front):
    tag = 'box_front' if front else 'box_back'
    def panel(points, fill):
        canvas.create_polygon(*points, fill=fill, outline='#815535', width=1.5, tags=tag)
    if front:
        panel((80,218, 256,218, 249,319, 92,319), '#d6a36e')
        panel((256,218, 273,202, 265,299, 249,319), '#bb8658')
        panel((80,218, 256,218, 249,232, 73,232), '#e8bd8c')
        panel((256,218, 273,202, 279,214, 262,230), '#ddb07d')
        canvas.create_line(154,245, 161,252, 170,253, 178,246, smooth=True,
                           fill='#9b7048',width=2,tags=tag)
    else:
        panel((80,218, 97,202, 273,202, 256,218), '#886144')
        panel((97,202, 87,190, 261,190, 273,202), '#e1b687')

def draw_air_toy(canvas, play, now):
    x,y = play.target
    if play.kind=='bubble':
        tint = colors.palette_color('浮字按键提示', play.bubble_tint)
        if colors.themes['浮字按键提示'].get():
            tint = dark_color(tint)
        edge = shade(tint,.76)
        if play.phase=='pop':
            age = (now-play.pop_time)/.29
            if age>=1:
                return
            for i in range(8):
                a = math.tau*i/8
                r = 13+age*11
                dx,dy = math.cos(a), math.sin(a)
                canvas.create_line(x+r*dx,y+r*dy,x+(r+4*(1-age))*dx,y+(r+4*(1-age))*dy,
                                   fill=edge,width=2,tags='toy_bubble')
        else:
            canvas.create_oval(x-13,y-13,x+13,y+13,fill=pale(tint,.5),stipple='gray25',
                               outline=edge,width=2,tags='toy_bubble')
            canvas.create_arc(x-10,y-10,x+10,y+10,start=93,extent=56,style=tk.ARC,
                              outline=pale(tint,.83),width=2,tags='toy_bubble')
    elif play.kind=='wand':
        # The feather tip follows the pointer; the shaft trails off to the side.
        sign = 1 if x<W-87 else -1
        up = -1 if y>76 else 1
        sway = (7 if play.phase=='caught' else 2)*math.sin((now-play.began)*22)
        tx,ty = x+sign*(19+sway),y+up*20
        canvas.create_line(x+sign*80,y+up*70,x+sign*42,y+up*50,fill='#8f603e',width=4.5,
                           capstyle=tk.ROUND,tags='toy_wand')
        canvas.create_line(x+sign*42,y+up*50,tx+sign*13,ty+up*2,tx,ty,fill='#9e837d',
                           smooth=True,width=2,tags='toy_wand')
        canvas.create_polygon(tx,ty,tx-sign*18,ty+up*6,x-sign*8,y-up*10,x+sign*15,y-up*2,tx,ty,
                              smooth=True,fill='#e98e94',outline='#975662',tags='toy_wand')
        canvas.create_line(x-sign*5,y-up*5,tx,ty,fill='#ffe1c9',width=2,tags='toy_wand')

def draw_keyboard(c, dark, pose, now, pressed):
    cap_colors = {key: colors.palette_color('键盘', key) for key in (white,) + KEY_ACCENTS}
    base_color = cap_colors[white]
    keyboard_labels = colors.keyboard_labels.get()
    style = (c.zoom, dark, keyboard_labels, tuple(cap_colors.values()))
    if c.keyboard_style != style:
        c.delete('keyboard_layer')
        c.keyboard_tags = ('keyboard_layer',)
        try:
            top=board_rect(69,292,252,95)
            bottom=[(x,y+10) for x,y in top]
            if base_color!=white:
                shell=dark_color(base_color) if dark else base_color
                front,side,edge,plate,rim,well=[shade(shell,n) for n in (.68,.78,.55,.94,1.08,.81)]
            elif dark:
                front,side,edge,plate,rim,well=('#24292e','#333a40','#121518','#22262a','#4b5258','#101215')
            else:
                front,side,edge,plate,rim,well=('#9ca9b0','#b2bec3','#77868e','#e9eeee','#fafdfd','#c4ced0')
            board_layer=quad(c,[top[0],top[1],bottom[1],bottom[0]],front,edge)
            quad(c,[top[0],top[3],bottom[3],bottom[0]],side,edge)
            quad(c,top,plate,rim)
            quad(c,board_rect(73,296,244,87),well)
            if dark:
                cap_colors={key:dark_color(value) for key,value in cap_colors.items()}
            for x,y,w,h,label,code,key_color in sorted(keys,key=lambda k:project(k[0],k[1])[1]):
                c.keyboard_tags = ('keyboard_layer',)
                quad(c,board_rect(x-.5,y-.5,w+1,h+1),'#383d42' if dark else '#7e8a90')
                for down in (False, True):
                    c.keyboard_tags = ('keyboard_layer', f'cap_{code}_{int(down)}', 'cap_down' if down else 'cap_up')
                    height = .5 if down else 6
                    color=cap_colors[key_color]
                    color = shade(color,.93) if down else color
                    base=board_rect(x,y,w,h)
                    cap=board_rect(x+.5,y+.5,w-1,h-1,height)
                    quad(c,[cap[0],cap[1],base[1],base[0]],shade(color,.72))
                    quad(c,[cap[0],cap[3],base[3],base[0]],shade(color,.83))
                    quad(c,cap,color,shade(color,.86))
                    tx,ty=project(x+w/2,y+h/2,height)
                    if keyboard_labels:
                        c.create_image(tx,ty,image=key_label(c,label,x+w/2,y+h/2,dark))
        finally:
            c.keyboard_tags = ()
        c.itemconfigure('cap_down', state='hidden')
        c.keyboard_board = board_layer
        c.down_keys = set()
        c.keyboard_style = style
    down_keys = {code for code,impact in pose.key_contact.items()
                 if not pose.paused and impact <= now and (code in pressed or now < impact+.075)}
    for code in down_keys ^ c.down_keys:
        down = int(code in down_keys)
        c.itemconfigure(f'cap_{code}_{1-down}', state='hidden')
        c.itemconfigure(f'cap_{code}_{down}', state='normal')
    c.down_keys = down_keys
    c.tag_raise('keyboard_layer')
    return c.keyboard_board


def render_scene(c,painter,play,pose,now,mouse,pressed):
    c.delete('!keyboard_layer')
    boxed = play.kind=='box'
    tuck, peek = play.box_pose(now) if boxed else (0., 0.)
    tail_fold = play.box_tail_fold(now) if boxed else 0.
    box_visible = tail_fold >= .95
    if box_visible:
        draw_box(c,False)
    stretch = 0.0
    if play.kind=='stretch':
        phase = (now-play.began)/(play.end-play.began)
        # Push forward quickly, hold the extended pose, then rise more slowly.
        stretch = ramp(min(phase/.32,(1-phase)/.48))
    idle = now-pose.last_activity >= SLEEP_AFTER and not play.kind
    quiet = max(0, now-pose.last_activity-2)
    breath = .005*(1-math.cos(2*math.pi*quiet/4)) if not pressed and not pose.paused else 0
    # Trace the supplied front-view reference in its original proportions.
    held_buttons = pressed & {1,2}
    mouse_buttons = held_buttons or {button for button in (1,2) if now < pose.pressed_until.get(button,0)}
    if pose.paused or pose.mouse_blocked:
        mouse_buttons = set()
    mouse_down = bool(mouse_buttons)
    mouse_pose = not pose.paused and (now < pose.mouse_work_until or
                                 (now < pose.mouse_active_until and now-pose.last_key_time>.35))
    leaning = mouse_pose or mouse_down
    if play.kind:
        leaning = False
    # Bridge the short gaps between taps so the torso settles during a word.
    sharing = leaning and now < pose.until['right'] + .18 and now-pose.last_key_time < .34
    pose.typing_balance += (float(sharing)-pose.typing_balance)*.32
    pose.mouse_lean += (float(leaning)-pose.mouse_lean)*.38
    if pose.mouse_lean < .002:
        pose.mouse_lean = 0.0

    # A forward push is screen-down for the cat. Reach a little left and down.
    mx,my = pose.mouse_offset
    target_x = .24*mx - .33*my if leaning else 0.0
    target_y = 28 + 3*pose.typing_balance + .60*my if leaning else 0.0
    gaze_key = None
    if leaning and now < pose.until['right'] and pose.stroke_key['right'] is not None:
        # The free paw can cross the entire board. Look at its actual target.
        gaze_key = pose.targets['right']
        idle = False
    elif not leaning and not pose.paused:
        # Prefer held keys; retain a short tap just long enough to see it.
        held = pressed.intersection(key_positions)
        visible = held or {k for k in key_positions if pose.pressed_until.get(k,0)>now}
        letters = [k for k in visible if 65 <= k <= 90]
        points = [key_positions[k] for k in (letters or visible)]
        if points:
            idle = False
            gx = sum(p[0] for p in points)/len(points)
            gy = sum(p[1] for p in points)/len(points)
            gaze_key = (gx,gy)
            # Balance around the middle of the displayed letter rows.
            center_x = (key_positions[ord('Q')][0]+key_positions[ord('P')][0])/2
            target_x = max(-15,min(15,(gx-center_x)*.19))
            target_y = 30
    if play.kind in TOYS or play.kind=='tease' or play.direction:
        gaze_key = play.target
        idle = False
    if boxed and play.phase=='play':
        target_y += 13*math.sin(math.pi*ramp((now-play.began)/.55))
    elif play.kind=='wand' and play.anchor is not None:
        target_y += 9*ramp((now-play.still_since-.27)/.4)
    if play.kind=='chin':
        target_y -= 9
    follow_x,follow_y = pose.body_follow
    shoulder_rate=.15 if gaze_key is not None else .28
    pose.body_follow = (follow_x+shoulder_rate*(target_x-follow_x), follow_y+shoulder_rate*(target_y-follow_y))
    # Add a small yaw around the existing three-quarter pose, eased with the reach.
    yaw = math.radians(max(-3.3,min(3.3,.75*pose.body_follow[0])))
    width_change = math.cos(math.radians(18)-yaw)/math.cos(math.radians(18))-1

    # Dual-input reference: the head sits about one sixth of a head-width
    # towards the mouse from the hips. The forelegs can still reach fully.
    torso_lean = pose.mouse_lean * (1-.70*pose.typing_balance)
    face_turn = pose.mouse_lean * (1-.83*pose.typing_balance)
    if gaze_key is not None:
        look_direction=(gaze_key[0]-(CAT_ORIGIN_X+390*.34+pose.body_follow[0]))/100
    else:
        look_direction=2*mouse[0]/max(1,root.winfo_screenwidth())-1
    pose.look_turn += .36*((0 if idle or pose.paused else max(-1,min(1,look_direction)))-pose.look_turn)
    pounce_x,pounce_y,hunt_wiggle = play.wand_motion(now)
    def ref(x,y,tilt=True):
        x += (x-390)*.7*breath
        y += (y-852)*breath
        weight = max(0,min(1,(790-y)/430)) if tilt else 0
        x += (x-390)*width_change*weight
        if stretch:
            # The haunches advance slightly; the chest folds down between the
            # reaching forelegs. Move the head as one shape above the neck.
            x += (x-390)*.08*stretch
            y += (15+.47*min(470,max(0,852-y)))*stretch
        px = CAT_ORIGIN_X+(x-208*torso_lean*weight)*.34 + pose.body_follow[0]*weight
        py = 15+y*.34 + pose.body_follow[1]*weight
        if play.kind=='wand':
            # The hips wiggle under a steady gaze. The chest leads on takeoff.
            hip = max(0., min(1., (y-300)/450))
            px += pounce_x*(1-.42*hip) + 3.2*hunt_wiggle*(.15+.85*hip)
            py += pounce_y*(1-.55*hip)
        if boxed:
            px += (175-px)*.34*tuck+peek
            py += (191-.61*py)*tuck
        return px,py
    # Measure height from the cat's eyes, even after the window is dragged.
    eye_screen_y = c.winfo_rooty() + c.zoom * ref(390,246)[1]
    distance_y = mouse[1] - eye_screen_y
    pitch_target = math.copysign(min(1,max(0,abs(distance_y)-10)/140),distance_y)
    if idle or pose.paused or gaze_key is not None:
        pitch_target = 0
    pose.head_pitch += .17*(pitch_target-pose.head_pitch)
    age=max(0,now-pose.expression_start)
    reaction=pose.expression if age < {'squint':.82,'yawn':1.55,'annoyed':ANGER_DURATION}.get(pose.expression,0) else ''
    if not reaction and now<play.tap_squint_until:
        reaction='squint'
    if play.kind=='chin':
        reaction='squint'
        pose.head_pitch += .3*(-1-pose.head_pitch)
    if play.kind=='stretch':
        reaction='yawn'
        gape=stretch
    else:
        gape=math.sin(math.pi*age/1.55)**1.3 if reaction=='yawn' else 0
    horizontal_turn=1.1*pose.look_turn-face_turn+2*math.sin(yaw)
    dizzy = play.kind=='dizzy'
    spin = now-play.began if dizzy else 0
    sway = math.sin(spin*7)*min(1,spin*6,max(0,(play.end-now)*3)) if dizzy else 0
    def face(x,y,depth=0):
        # Fur follows the curved face: the blaze projects farther forward
        # than the cheeks, while the ears and outer contour stay anchored.
        cheek_curve=max(0,1-((x-390)/175)**2)
        brow_curve=max(0,1-((y-250)/120)**2)
        surface_depth=depth or 36*cheek_curve*brow_curve
        fx=x+horizontal_turn*surface_depth-.08*face_turn*(x-390)
        fx+=pose.look_turn*12-abs(pose.look_turn)*.047*(x-390)
        fy=y+(face_turn*.08+pose.look_turn*.024)*(x-390)
        if play.kind=='tease':
            fy += .065*(1 if play.side=='right' else -1)*(x-390)
        if dizzy:
            fx += .07*sway*(385-y)
            fy += .07*sway*(x-390)
        # Keep the neck anchored; the ears and forward facial features move most.
        fy+=pose.head_pitch*(.057*(397-y)+.42*depth)
        return ref(fx,fy-8*gape)
    play.eyes, play.chin = face(390,246,28), face(390,358)
    def contour(points,fill=ink,width=0,project_point=ref):
        return c.create_polygon(*[n for x,y in points for n in project_point(x,y)],
                         fill=fill,smooth=True,splinesteps=24,outline=stroke if width else '',width=width)
    # Fuchsia is the window's transparency key. Use its closest opaque neighbour.
    def visible(color):
        return '#fe00ff' if color=='#ff00ff' else color
    coat=visible(colors.current['身体'])
    artwork = painter.active() if pose is live else painter.record
    if artwork:
        coat = visible(artwork['base'])
    ginger_white=coat=='ginger_white'
    patched=coat in ('calico','ginger_white')
    orange_tabby=not artwork and coat==PRESETS['身体']['橘色']
    tabby=coat=='tabby' or orange_tabby
    white_tuxedo=coat=='tuxedo_white'
    tuxedo=coat=='tuxedo' or white_tuxedo
    white_fur='#f3f1eb'
    flat='#151515' if tuxedo else {'calico':white_fur,'ginger_white':white_fur,'tabby':'#94816b'}.get(coat,coat)
    patch_color='#d98543' if ginger_white else '#191919'
    stripe='#af5628' if orange_tabby else '#493c34'
    face_fur=white_fur if tuxedo else flat
    toe_fur=white_fur if tuxedo else flat
    iris=visible(colors.current['眼睛'])
    pupil=visible(colors.current['瞳孔'])
    dark=colors.themes['键盘'].get()
    mouse_color=visible(colors.current['鼠标'])
    if colors.themes['鼠标'].get():
        mouse_color=dark_color(mouse_color)
    red,green_channel,blue_channel=bytes.fromhex(face_fur[1:])
    whisker='#191919' if .2126*red+.7152*green_channel+.0722*blue_channel>135 else '#eeeee7'
    eye_outline='#171717' if whisker=='#191919' else '#050505'
    stroke=coat_outline(artwork['base']) if artwork else eye_outline
    turn = yaw/math.radians(3.3)
    root_x,root_y=TAIL[0]
    hip_x,hip_y=ref(root_x,root_y)
    rest_x,rest_y=ref(root_x,root_y,tilt=False)
    def tail_point(x,y):
        px,py=ref(x,y,tilt=False)
        # Keep the root tucked behind the leaning hip; taper the shift towards the tip.
        anchor=pose.mouse_lean*max(0,min(1,(TAIL[-1][0]-x)/(TAIL[-1][0]-root_x)))
        px+=(hip_x-rest_x-6)*anchor
        py+=(hip_y-rest_y)*anchor
        bend=((x-565)/214)**2*turn
        tip = (x-root_x)/(TAIL[-1][0]-root_x)
        px += 2*bend
        py -= bend+32*stretch*tip*tip
        if hunt_wiggle:
            tail_flex = max(0., min(1., tip))
            px += 8*tail_flex*hunt_wiggle
            py -= 10*tail_flex*hunt_wiggle
        if tail_fold:
            # Draw the tail in behind the hip before the cat ducks. The head
            # can peek over either rim while the tail stays inside the box.
            px += ((hip_x-px)*.76-32)*tail_fold
            py += (hip_y-py)*.65*tail_fold
        return px,py

    def hind_paw_point(x,y):
        px,py=ref(x,y)
        # Shift weight above the sole; the nearer paw shows a little more white.
        height=max(0,min(1,(852-y)/71))
        side=-1 if x<390 else 1
        return px+1.4*height*turn,py+.8*height*turn*side

    # Tail, broad pear-shaped torso, and tucked white hind toes.
    tail_fur={'calico':'#151515','ginger_white':patch_color}.get(coat,flat)
    band=stripe if tabby else '#e69a55'
    if colors.short_tail.get():
        # Clip the original root band to the ball in coat coordinates.
        outline=[(BOB_X+BOB_RADIUS*math.cos(i*math.tau/72),
                  BOB_Y+BOB_RADIUS*math.sin(i*math.tau/72)) for i in range(72)]
        contour(outline,tail_fur,width=1.6,project_point=tail_point)
        if patched or tabby:
            # The first stripe starts at the centre and points along (28,-4).
            half_width=8.5/.34
            arc=math.asin(half_width/BOB_RADIUS)
            local=[(0,-half_width)]
            for i in range(33):
                angle=-arc+2*arc*i/32
                local.append((BOB_RADIUS*math.cos(angle),BOB_RADIUS*math.sin(angle)))
            local.append((0,half_width))
            length=math.hypot(28,4)
            segment=[(BOB_X+(28*x+4*y)/length,BOB_Y+(-4*x+28*y)/length) for x,y in local]
            c.create_polygon(*[n for point in segment for n in tail_point(*point)],fill=band)
    else:
        tail=[n for x,y in TAIL for n in tail_point(x,y)]
        if stroke:
            c.create_line(*tail,fill=stroke,width=22,smooth=True,capstyle=tk.ROUND)
        c.create_line(*tail,fill=tail_fur,width=19,smooth=True,capstyle=tk.ROUND)
        if tuxedo:
            c.create_line(*tail_point(758,566),*tail_point(779,560),
                          fill=white_fur,width=18,capstyle=tk.ROUND)
        if patched or tabby:
            for a,b in [((606,690),(634,686)),((671,660),(688,635)),((715,599),(733,580))]:
                c.create_line(*tail_point(*a),*tail_point(*b),fill=band,width=17,capstyle=tk.BUTT)
            if tabby:
                c.create_line(*tail_point(757,567),*tail_point(779,560),fill=stripe,width=18,capstyle=tk.ROUND)
    if artwork:
        painter.render('tail', tail_point)
    body_shape, head_shape = BODY, HEAD
    # Put both silhouettes' borders beneath both fills, hiding their common seam.
    if stroke:
        contour(body_shape,flat,width=1.6)
        contour(head_shape,face_fur,width=1.6,project_point=face)
    torso_item = contour(body_shape,flat)
    play.torso_item=torso_item
    play.neck_bottom=ref(390,475)[1]
    if artwork:
        painter.render('body', ref)
    if white_tuxedo:
        # The bib widens at both shoulders, then narrows between the hind paws.
        contour([(249,370),(310,344),(435,343),(502,367),(524,432),
                 (542,513),(551,592),(537,667),(504,717),(466,740),
                 (439,770),(392,788),(342,771),(313,743),(272,731),
                 (238,692),(221,625),(221,545),(233,459)],white_fur)
    elif tuxedo:
        # Foreshorten the lower bib with the reach so both shoulders meet black fur.
        lift=pose.mouse_lean*60
        contour([(249,370),(310,344),(435,343),(502,367),(518,430),
                 (523,474),(507,529-lift*.4),(473,558-lift*.7),(432,574-lift),
                 (393,593-lift),(362,579-lift),(317,570-lift),(267,545-lift),
                 (238,511-lift*.6),(229,468-lift*.3),(232,435)],white_fur)
    if patched:
        # Keep the mouse-side shoulder and its full reach corridor white.
        contour([(474,411),(497,403),(515,418),(527,448),(517,466),
                 (492,456),(479,439),(462,430)],'#e69a55')
        contour([(522,479),(538,467),(548,484),(551,508),
                 (537,522),(520,511),(513,497)],patch_color)
    if ginger_white:
        contour([(216,569),(236,551),(253,560),(247,585),(271,600),
                 (279,629),(256,650),(225,642),(201,618)],'#e69a55')
        contour([(562,568),(581,586),(586,636),(576,659),(555,649),
                 (549,620),(526,607),(530,583)],patch_color)
    if tabby:
        contour([(273,392),(365,379),(481,392),(472,451),(444,509),
                 (396,573),(371,589),(334,550),(293,481)],'#f4be83' if orange_tabby else '#c8b599')
        for side in (-1,1):
            for height,outer in ((458,151),(521,167),(589,184),(655,192)):
                contour([(390+side*outer,height),(390+side*(outer-14),height+18),
                         (390+side*(outer-62),height+31),(390+side*(outer-92),height+44),
                         (390+side*(outer-58),height+17),(390+side*(outer-16),height-5)],stripe)
    for heel_x in (250,528):
        outline=heel_outline(heel_x)
        # The black foot covers the upper rim and leaves a sliver along the sole.
        contour(outline,flat if artwork else '#eeeDE8',width=1.5,project_point=hind_paw_point)
        contour([(x,y-5) for x,y in outline],toe_fur,project_point=hind_paw_point)
        if artwork:
            painter.render(str(heel_x), hind_paw_point)
    # One continuous head-and-ears outline, without inner ears or a nose.
    play.face_item = contour(head_shape,face_fur,project_point=face)
    if tuxedo:
        # Follow the ear silhouette. The lower edge wraps both eyes and
        # turns up between them to leave a tapered white blaze above the muzzle.
        mask=head_shape[:18]+[(565,302),(545,313),(513,320),(475,316),
             (446,307),(419,292),(402,264),(391,226),(379,203),
             (383,240),(378,270),(362,300),(331,317),(294,327),
             (254,324),(224,312)]+head_shape[-3:]
        contour(mask,flat,project_point=face)
    if patched:
        contour([(229,207),(230,148),(241,103),(253,83),(271,86),(304,118),
                 (329,141),(355,136),(388,133),(383,174),(364,199),(359,246),
                 (341,276),(303,285),(277,303),(240,312),(215,299),(211,269)],
                patch_color,project_point=face)
        contour([(390,134),(417,135),(447,142),(476,108),(503,82),(520,82),
                 (539,111),(545,158),(545,215),(561,252),(564,288),(551,305),
                 (520,301),(487,279),(454,278),(427,260),(419,219),(402,208),
                 (408,182),(395,195)],'#e69a55',project_point=face)
    if tabby:
        contour([(337,143),(354,155),(368,179),(386,151),(397,145),
                 (413,178),(435,148),(447,143),(426,190),(412,205),
                 (391,167),(368,205),(353,184)],stripe,project_point=face)
        for side in (-1,1):
            for y in (276,302):
                contour([(390+side*167,y),(390+side*149,y+12),
                         (390+side*105,y+24),(390+side*132,y+8),
                         (390+side*158,y-6)],stripe,project_point=face)
    if artwork:
        painter.render('head', face)
    if colors.body_shadow.get():
        draw_coat_shading(c,([ref(x,y) for x,y in body_shape],[face(x,y) for x,y in head_shape]))
    blink = idle or (now % 5.5 < .13)
    if gaze_key is not None:
        cx,cy=face(388,246,depth=28)
        down=gaze_key[1]-cy
        lowering=max(0,down/max(1,math.hypot(gaze_key[0]-cx,down)))
    else:
        lowering=.35*max(0,pose.head_pitch)
    pose.eye_lowering+=(lowering-pose.eye_lowering)*(.34 if lowering>pose.eye_lowering else .18)
    eye_scale=1-.22*pose.eye_lowering
    tracking_face = bool(play.direction or play.kind=='tease')
    if tracking_face:
        cursor_x = (mouse[0]-c.winfo_rootx())/c.zoom
        eye_mid_x = (face(316,246,28)[0]+face(459,246,28)[0])/2
        target_dx = max(-8, min(8, (cursor_x-eye_mid_x)*.16))
        pose.face_gaze_x += .35*(target_dx-pose.face_gaze_x)
    else:
        pose.face_gaze_x = 0.0
    for ex in (316,459):
        x,y=face(ex,246,depth=28)
        eye_width=17-face_turn*(3.5 if ex==316 else .8)
        eye_width-=1.9*max(0,pose.look_turn if ex==459 else -pose.look_turn)
        if dizzy:
            oval(c,x-eye_width,y-13,x+eye_width,y+13,iris,eye_outline,1.5)
            spiral=[]
            for i in range(41):
                a=spin*4+i*.24
                spiral.extend((x+(.7+i*.20)*math.cos(a),y+(.7+i*.20)*math.sin(a)))
            c.create_line(*spiral,fill=pupil,width=2,capstyle=tk.ROUND,tags='dizzy_eye')
        elif reaction in ('squint','yawn','annoyed'):
            slant=(1 if ex==316 else -1)*4 if reaction=='annoyed' else 0
            curve=1 if reaction=='annoyed' else -5
            coords=(x-eye_width+2,y-slant,x,y+curve,x+eye_width-2,y+slant)
            c.create_line(*coords,fill=eye_outline,width=5,smooth=True,capstyle=tk.ROUND)
            c.create_line(*coords,fill=iris,width=2.5,smooth=True,capstyle=tk.ROUND)
        elif blink:
            if stroke:
                c.create_line(x-eye_width+2,y,x,y+3,x+eye_width-2,y,fill=eye_outline,width=5,smooth=True,capstyle=tk.ROUND)
            c.create_line(x-eye_width+2,y,x,y+3,x+eye_width-2,y,fill=iris,width=3,smooth=True)
        else:
            y+=1.2*pose.eye_lowering
            oval(c,x-eye_width,y-14*eye_scale,x+eye_width,y+14*eye_scale,iris,eye_outline,1.5)
            dx=max(-4,min(4,(mouse[0]/max(1,root.winfo_screenwidth())-.5)*8))
            dy=2*pose.head_pitch
            if gaze_key is not None:
                vx,vy=gaze_key[0]-x,gaze_key[1]-y
                distance=max(1,math.hypot(vx,vy))
                dx,dy=10*vx/distance,3.8*vy/distance
            if tracking_face:
                dx=pose.face_gaze_x
            oval(c,x-5+dx,y+(-10+dy)*eye_scale,x+5+dx,y+(10+dy)*eye_scale,pupil)
    if dizzy:
        x,y=face(390,78)
        for i in range(3):
            angle=spin*3+i*math.tau/3
            sx,sy=x+36*math.cos(angle),y-9+6*math.sin(angle)
            star=[]
            for j in range(8):
                r=5 if j%2==0 else 1.6
                star.extend((sx+r*math.cos(j*math.pi/4),sy+r*math.sin(j*math.pi/4)))
            c.create_polygon(*star,fill='#ffdb73',outline='#916834',width=.8,tags='dizzy_star')
    elif reaction=='yawn':
        x,y=face(390,320,14)
        oval(c,x-3-5*gape,y-1-8*gape,x+3+5*gape,y+1+9*gape,'#462b31','#241d20')
        if gape>.45:
            oval(c,x-4*gape,y+3*gape,x+4*gape,y+7*gape,'#d98e92')
    elif reaction=='annoyed':
        x,y=face(498,165)
        y-=2*math.sin(min(1,age/.2)*math.pi)
        for dx,dy in ((-1,-1),(1,-1),(-1,1),(1,1)):
            c.create_line(x+dx*8,y+dy*3,x+dx*3,y+dy*3,x+dx*3,y+dy*8,
                          smooth=True,fill='#ed5552',width=2.6,capstyle=tk.ROUND)
        x,y=face(390,321)
        c.create_line(x-5,y+2,x,y-1,x+5,y+1,smooth=True,fill=whisker,width=1.5)
    for side in (-1,1):
        for i in range(3):
            innerx=301 if side<0 else 477
            outerx=230 if side<0 else 547
            pts=[face(innerx,325+i*19,24),face((innerx+outerx)/2,324+i*25,16),face(outerx,334+i*32,8)]
            c.create_line(*[n for pt in pts for n in pt],fill=whisker,width=1,smooth=True)
    # Pastel keyboard drawn from the supplied reference, kept crisp at pet size.
    for item in c.find_withtag('!keyboard_layer'):
        if c.type(item)!='image' and 'box_back' not in c.gettags(item):
            c.addtag_withtag('pet_target',item)
    if box_visible:
        draw_box(c,True)
    board_layer=draw_keyboard(c, dark, pose, now, pressed)
    # Mouse in the cat's operating direction: palm end near the cat,
    # front buttons farther away, towards the viewer's lower left.
    def mp(x,y,z=0):
        return (57+pose.mouse_offset[0]+17*x-11*y, 318+pose.mouse_offset[1]+7*x+18*y-z)
    def mouse_shape(points,color,z=0,outline=''):
        c.create_polygon(*[v for x,y in points for v in mp(x,y,z)],
                         fill=color,outline=outline,smooth=True)
    shell=[(-.9,-.65),(-.6,-1),(.45,-1),(.95,-.5),(1,.65),
           (.7,1),(-.65,1),(-1,.6)]
    mouse_shape(shell,shade(mouse_color,.66),-5,shade(mouse_color,.6))
    mouse_shape(shell,mouse_color,1,shade(mouse_color,.78))
    # Two broad front buttons and central wheel at the far end.
    # Positive local x is screen-right, the seated cat's left.
    left_down = 1 in mouse_buttons
    right_down = 2 in mouse_buttons
    mouse_shape([(-.92,.05),(-.08,.08),(-.08,.96),(-.7,.96),(-.96,.63)],
                shade(mouse_color,.78 if right_down else 1.05),1-3*right_down,shade(mouse_color,.8))
    mouse_shape([(.08,.08),(.94,.03),(.98,.6),(.67,.96),(.08,.96)],
                shade(mouse_color,.78 if left_down else .98),1-3*left_down,shade(mouse_color,.8))
    x1,y1=mp(0,.32,2);x2,y2=mp(0,.62,2)
    c.create_line(x1,y1,x2,y2,fill=shade(mouse_color,.52),width=4,capstyle=tk.ROUND)
    c.create_line(x1,y1,x2,y2,fill=pale(mouse_color,.55),width=2,capstyle=tk.ROUND)
    x1,y1=mp(-.6,-.65,3);x2,y2=mp(.25,-.83,3)
    c.create_line(x1,y1,x2,y2,fill=shade(mouse_color,1.15),width=2,smooth=True)
    for side in ('left','right'):
        reach=pose.mouse_lean
        if side=='left':
            start=ref(306-36*reach,609-94*reach)
            rest=ref(331,831)
            # Rest between the buttons and pivot slightly towards the clicked side.
            palm_y = .40 - (.12 if mouse_down else .35)*pose.typing_balance
            contact=mp(.22*(int(left_down)-int(right_down)),palm_y,2 if mouse_down else 4)
        else:
            # Let the shoulder follow the turned chest while the paw stays planted.
            start=ref(458+12*reach-18*torso_lean,609-43*reach)
            rest=ref(447,831)
            edge_x,edge_y=project(190,387)
            contact=(edge_x,edge_y+3)
        active = now < pose.until[side] and not pose.paused
        shoulder_drop = max(0,pose.body_follow[1])*.29
        if side=='left':
            shoulder_drop += 5*reach
        start=(start[0], start[1]+shoulder_drop)
        kx,ky = pose.targets[side] if active else rest
        if active:
            ky+=5.5
            elapsed=max(0,now-pose.stroke_start[side])
            duration=CONTACT_TIME-.085*pose.stroke_speed[side]
            lift_time=.46*duration
            ox,oy=pose.stroke_origin[side]
            # Fold the paw towards the chest before extending to the key.
            apex=(start[0]+(-8 if side=='left' else 8),start[1]+20)
            speed=pose.stroke_speed[side]
            apex=(apex[0]*(1-speed)+(.6*ox+.4*kx)*speed,
                  apex[1]*(1-speed)+(min(oy,ky)-11)*speed)
            if elapsed < lift_time:
                ax,ay=ox,oy
                bx,by=apex
                phase=elapsed/lift_time
            else:
                ax,ay=apex
                bx,by=kx,ky
                phase=min(1,(elapsed-lift_time)/(duration-lift_time))
            blend=phase*phase*(3-2*phase)
            kx,ky=ax+(bx-ax)*blend,ay+(by-ay)*blend
        elif not leaning and now < pose.until['right' if side=='left' else 'left']+.28 and not pose.paused:
            kx,ky=start[0]+(-8 if side=='left' else 8),start[1]+22
        hand_reach = 0 if active and side=='right' else reach
        tx=kx+(contact[0]-kx)*hand_reach
        ty=ky+(contact[1]-ky)*hand_reach
        if not active and play.kind=='stretch':
            spread = -28 if side=='left' else 28
            tx,ty = rest[0]+spread*stretch,rest[1]+54*stretch
        elif not active and play.kind in TOYS:
            tx,ty = play.toy_paw(side,rest,now)
        elif not active and side==play.side and play.kind in ('tease','offer','invite','tap'):
            tx,ty = play.paw(now,rest)
        oldx,oldy=pose.paw_positions[side]
        if not active and pose is live:
            tx,ty=oldx+(tx-oldx)*.6,oldy+(ty-oldy)*.6
        pose.paw_positions[side]=(tx,ty)
        sx,sy=start
        tag='foreleg_'+side
        lift=max(0,min(1,(rest[1]-ty)/max(1,rest[1]-sy-22)))
        extension=max(0,min(1,(ty-rest[1])/24))
        if side=='left':
            extension=max(extension,reach)
        toe_width=13-(3 if side=='left' else 1)*reach+4*lift+2*extension
        # A near-semicircular underside, including when the paw is resting.
        toe_height=toe_width*(.92+.06*lift)
        toe_bottom=ty+9
        # Sample both contours along the moving leg, in shoulder-to-wrist order.
        vx,vy=tx-sx,ty-sy
        length=max(1,math.hypot(vx,vy))
        nx,ny=vy/length,-vx/length
        edges=[[],[]]
        for t,radius in [(0,18),(.18,17),(.48,14),(.72,12),(.94,11.5),(1,11)]:
            radius -= (2 if side=='left' else 1)*reach
            for edge,sign in zip(edges,(-1,1)):
                edge.append((sx+t*vx+sign*radius*nx,sy+t*vy+sign*radius*ny))
        outline=edges[0]+[(tx,ty+3)]+edges[1][::-1]
        c.create_polygon(*[v for pt in outline for v in pt],smooth=True,
                         fill=white_fur if white_tuxedo else flat,outline='',tags=tag)
        if artwork:
            painter.render(side,leg_projection(side,start,(tx,ty),reach),tag)
        for edge in edges:
            if side=='left' and (leaning or reach>.05):
                # Only ink the exposed segment. Each edge exits the curved torso
                # at a different point as the shoulder and mouse move.
                def inside(pt):
                    x,y=pt
                    return torso_item in c.find_overlapping(*[v*c.zoom for v in (x-.7,y-.7,x+.7,y+.7)])
                outside=next((i for i,p in enumerate(edge) if not inside(p)),len(edge))
                if outside==len(edge):
                    continue
                if outside:
                    lo,hi=edge[outside-1],edge[outside]
                    for _ in range(7):
                        mid=((lo[0]+hi[0])/2,(lo[1]+hi[1])/2)
                        if inside(mid):
                            lo=mid
                        else:
                            hi=mid
                    edge=[hi]+edge[outside:]
            if stroke:
                c.create_line(*[v for pt in edge for v in pt],smooth=True,
                              fill=stroke,width=1.3,tags=tag)
            # A narrow ribbon fades to a point where the foreleg meets the chest.
            widths=(0,.28,.68,.90,.57,.12)
            if len(edge)!=len(widths):
                widths=tuple(.85*math.sin(math.pi*i/(len(edge)-1)) for i in range(len(edge)))
            if side=='left' and reach>0:
                # Retract the trim towards the wrist as the arm leaves the chest.
                ex,ey=edge[-1]
                trim=.78*reach
                edge=[(x+(ex-x)*trim,y+(ey-y)*trim) for x,y in edge]
            ribbon=[(x+nx*w,y+ny*w) for (x,y),w in zip(edge,widths)]
            ribbon+=list(reversed([(x-nx*w,y-ny*w) for (x,y),w in zip(edge,widths)]))
            c.create_polygon(*[v for pt in ribbon for v in pt],smooth=True,fill=flat if artwork else '#a6a69f',tags=tag)
        draw_paw(c,tx,toe_bottom,toe_width,toe_height,tag,toe_fur,stroke if artwork or whisker=='#191919' else '',
                 flat if artwork else stripe if tabby else '#f6f5ed',wide_tip=orange_tabby)
        if artwork:
            center = 331 if side=='left' else 447
            painter.render(side+'_paw', lambda x,y: (tx+(x-center)*.34*toe_width/13,
                toe_bottom + ((y-831)*.34-9)*toe_height/(13*.92)), tag)
        if box_visible and not active:
            c.tag_lower(tag,'box_front')
        elif side=='right' and reach>.5 and not active:
            c.tag_lower(tag,board_layer)
    if colors.click_marks.get() and not pose.paused:
        for button,born in pose.click_started.items():
            phase=(now-born)/.23
            if not 0 <= phase < 1:
                continue
            sign=1 if button==1 else -1
            px,py=mp(sign*.75,.7)
            for degrees in (20,49,78):
                angle=math.radians(degrees)
                dx,dy=sign*math.cos(angle),math.sin(angle)
                r=11+9*phase
                end=r+4+9*(1-phase)
                segment=(px+dx*r,py+dy*r,px+dx*end,py+dy*end)
                for width,color in ((4,'#383536'),(2,'#fff2c8')):
                    c.create_line(*segment,width=width,fill=color,capstyle=tk.ROUND,tags='click_mark')
    if play.kind=='paper':
        x,y=play.ball(now)
        angle=min(now-play.began,play.paper_duration())*7
        points=[]
        for i,r in enumerate((11,9,12,9,11,8,11)):
            a=angle+2*math.pi*i/7
            points.append((x+r*math.cos(a), y+r*math.sin(a)))
        c.create_polygon(*[v for point in points for v in point],fill='#fff4dd',outline='#71695c',width=1.3)
        c.create_line(*points[0],x-1,y+1,*points[3],fill='#b8ab96',width=1)
    elif play.kind in ('bubble','wand'):
        draw_air_toy(c,play,now)
    if pose is live and floating_keys:
        draw_floating_keys(now,ref(390,575))

def tick():
    global previous,last_mouse
    now=time.monotonic()
    point=wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    mouse=(point.x,point.y)
    cursor=((mouse[0]-c.winfo_rootx())/c.zoom,(mouse[1]-c.winfo_rooty())/c.zoom)
    near_face=play.near_face(cursor)
    watched={1,2,*key_positions}
    if show_keys.get():
        watched.update(range(96,106))
    pressed={k for k in watched if user32.GetAsyncKeyState(k)&0x8000}
    if live.drag and live.drag['hit']:
        pressed.discard(1)
    fresh=pressed-previous
    was_playing_toy = play.kind in TOYS
    playing=play.update(now,cursor,pressed,near_face)
    live.mouse_blocked=bool(near_face or play.near_neck(cursor) or playing or play.hover or
                            play.kind in ('paper','offer','invite','tap','chin') or
                            (live.drag and (live.drag.get('chin') or live.drag.get('tap'))))
    mouse_moved=last_mouse is not None and mouse!=last_mouse
    if not live.paused and not live.mouse_blocked and mouse_moved:
        live.mouse_offset = move_mini_mouse(live.mouse_offset, mouse[0]-last_mouse[0], mouse[1]-last_mouse[1])
    was_asleep=not live.paused and not was_playing_toy and now-live.last_activity>=SLEEP_AFTER
    waking=was_asleep and bool(fresh.intersection(key_positions))
    if was_asleep and not waking and not live.mouse_blocked and (mouse_moved or fresh & {1,2}):
        live.expression,live.expression_start='yawn',now
    if colors.click_marks.get() and not live.paused and not live.mouse_blocked:
        for button in fresh & {1,2}:
            live.click_started[button]=now
    if mouse_moved or pressed & {1,2}:
        live.mouse_active_until=now+2
        live.mouse_work_until=now+.35
    if live.mouse_blocked:
        live.mouse_active_until=live.mouse_work_until=0
    if fresh-{1,2}:
        live.last_key_time=now
    if not live.paused:
        for code in pressed:
            live.pressed_until[code]=now+.10
    if pressed or previous or mouse_moved or was_playing_toy:
        live.last_activity=now
    if not live.paused:
        for side,code in live.stroke_key.items():
            if code is None:
                continue
            impact=live.key_contact[code]
            if code in pressed:
                live.last_key_time=now
            elif code not in pressed:
                live.until[side]=min(live.until[side],max(now,impact+STROKE_TIME-CONTACT_TIME))
        if now < live.mouse_work_until and now < live.until['left']:
            if live.until['left'] >= live.until['right']:
                live.targets['right']=live.targets['left']
                live.until['right']=live.until['left']
                live.stroke_origin['right']=live.paw_positions['right']
                live.stroke_key['right']=live.stroke_key['left']
                live.stroke_start['right']=live.stroke_start['left']
                live.stroke_speed['right']=live.stroke_speed['left']
            live.until['left']=0
            live.stroke_key['left']=None
        for k in sorted(fresh-{1,2}):
            if show_keys.get() and 96<=k<=105:
                add_floating_key(k,now)
            if k in key_positions:
                position = key_positions[k]
                side='left' if position[0]<194 and now>=live.mouse_work_until else 'right'
                if waking:
                    play.begin('stretch',now,1.45,'right' if side=='left' else 'left')
                    waking=False
                old=live.stroke_key[side]
                origin=live.paw_positions[side]
                if old is not None and old!=k and live.key_contact[old]>now:
                    live.key_contact[old]=now
                    origin=(live.targets[side][0],live.targets[side][1]+5.5)
                gap=now-live.stroke_start[side]
                live.stroke_speed[side]=max(0,min(1,(.34-gap)/.22))
                live.stroke_start[side]=now
                live.targets[side]=position
                live.stroke_origin[side]=origin
                live.stroke_key[side]=k
                live.until[side]=math.inf  # Release the paw when the physical key comes up.
                live.key_contact[k]=now+CONTACT_TIME-.085*live.stroke_speed[side]
                if show_keys.get():
                    add_floating_key(k,now)
    previous=pressed
    last_mouse=mouse
    draw(now,mouse,pressed)
    root.after(25,tick)

def start_drag(e):
    hit=False
    point=(e.x/c.zoom,e.y/c.zoom)
    now=time.monotonic()
    if play.kind in TOYS and play.kind!='box' and not live.paused:
        live.drag=dict(hit=True,moved=False,toy=True)
        return
    if not live.paused and play.kind in ('offer','invite','tap') and math.dist(point,live.paw_positions[play.side])<20:
        play.high_five(now)
        live.drag=dict(x=e.x_root,y=e.y_root,hit=True,moved=False,tap=True)
        return
    drag=dict(x=e.x_root,y=e.y_root,wx=root.winfo_x(),wy=root.winfo_y(),moved=False)
    if play.kind=='box':
        live.drag=dict(drag,hit=True,box_point=point,box_entered=play.box_entered)
        return
    for item in reversed(c.find_overlapping(e.x,e.y,e.x,e.y)):
        tags=c.gettags(item)
        if 'floating_key' in tags or 'click_mark' in tags or (c.type(item)=='image' and not tags):
            continue
        hit=any(t in tags for t in ('pet_target','foreleg_left','foreleg_right'))
        break
    chin=abs(point[0]-play.chin[0])<28 and abs(point[1]-play.chin[1])<17
    live.drag=dict(drag,hit=hit,chin=chin)

def move_drag(e):
    if live.drag and not (live.drag.get('tap') or live.drag.get('toy')):
        dx,dy=e.x_root-live.drag['x'],e.y_root-live.drag['y']
        if live.drag.get('chin'):
            if not live.paused and max(abs(dx),abs(dy))>=3*c.zoom:
                live.drag['rub']=True
                play.begin('chin',time.monotonic(),.55,'left')
            return
        if live.drag['moved'] or max(abs(dx),abs(dy))>=5:
            live.drag['moved']=True
            if not colors.position_fixed.get():
                root.geometry('+%d+%d'%(live.drag['wx']+dx,live.drag['wy']+dy))

def end_drag(e):
    global pet_count,last_pet
    gesture,live.drag=live.drag,None
    if gesture and 'box_point' in gesture:
        if not gesture['moved'] and play.kind=='box' and play.box_entered==gesture['box_entered']:
            play.touch_box(time.monotonic(),gesture['box_point'])
        pet_count=0
        return
    if gesture and (gesture.get('rub') or gesture.get('tap') or gesture.get('toy')):
        if gesture.get('rub') and not live.paused:
            play.begin('chin',time.monotonic(),.5,'left')
        pet_count=0
        return
    if not gesture or gesture['moved'] or not gesture['hit'] or live.paused:
        pet_count=0
        return
    now=time.monotonic()
    if live.expression=='annoyed' and now-live.expression_start<ANGER_DURATION:
        return
    pet_count=pet_count+1 if now-last_pet<=.65 else 1
    last_pet=now
    if 4 <= pet_count < 10 and live.expression=='yawn' and now-live.expression_start<1.55:
        return
    live.expression={3:'yawn',10:'annoyed'}.get(pet_count,'squint')
    live.expression_start=now
    if pet_count==10:
        pet_count=0

def toggle_pause():
    live.paused=not live.paused
    play.kind=''

size_dialog = None
transparency_dialog = None
brightness_dialog = None

def resize_pet(value):
    percent = int(float(value))
    if percent == colors.size_percent:
        return
    width, height = round(W*percent/100), round(H*percent/100)
    # Keep the keyboard's bottom edge and horizontal center in place.
    x = root.winfo_x() + (root.winfo_width()-width)//2
    y = root.winfo_y() + root.winfo_height()-height
    left, top, desktop_w, desktop_h = (user32.GetSystemMetrics(i) for i in (76,77,78,79))
    x = max(left, min(x, left+desktop_w-width))
    y = max(top, min(y, top+desktop_h-height))
    colors.size_percent = percent
    c.zoom = percent / 100
    root.geometry('%dx%d+%d+%d' % (width,height,x,y))
    c.label_cache.clear()
    volume_cache.clear()
    c.coat_overlay.clear()
    colors.save()

def percent_dialog(dialog, label, low, high, value, default, on_change):
    if dialog is not None and dialog.winfo_exists():
        dialog.lift()
        return dialog
    dialog = tk.Toplevel(root)
    dialog.title('小猫'+label)
    dialog.attributes('-topmost', True)
    dialog.resizable(False, False)
    slider = tk.Scale(dialog, label=label+'（%）', from_=low, to=high,
                      orient='horizontal', length=240, resolution=1)
    slider.set(value)
    slider.configure(command=on_change)
    slider.pack(padx=14, pady=10)
    tk.Button(dialog, text=f'恢复 {default}%', command=lambda: slider.set(default)).pack(pady=(0,10))
    dialog.bind('<Escape>', lambda event: dialog.destroy())
    return dialog

def open_size():
    global size_dialog
    size_dialog = percent_dialog(size_dialog, '大小', 50, 175, colors.size_percent, 100, resize_pet)

def set_transparency(value):
    percent = int(float(value))
    if percent != colors.transparency_percent:
        root.attributes('-alpha', 1 - percent / 100)
        colors.transparency_percent = percent
        colors.save()

def open_transparency():
    global transparency_dialog
    transparency_dialog = percent_dialog(transparency_dialog, '透明度', 0, 90,
                                         colors.transparency_percent, 0, set_transparency)

def set_brightness(value):
    percent = int(float(value))
    if percent != colors.brightness_percent:
        colors.brightness_percent = percent
        c.set_brightness(percent)
        c.label_cache.clear()
        volume_cache.clear()
        c.coat_overlay.clear()
        colors.save()

def open_brightness():
    global brightness_dialog
    brightness_dialog = percent_dialog(brightness_dialog, '明暗度', 50, 150,
                                       colors.brightness_percent, 100, set_brightness)

def make_pose_preview(parent,editor):
    panel=ttk.LabelFrame(parent,text='动作预览')
    panel.pack(fill='x')
    zoom=min(.7,parent.winfo_screenheight()/1520)
    canvas=PetCanvas(panel,width=round(W*zoom),height=round(H*zoom),bg='#e6e4df',highlightthickness=0)
    canvas.zoom=zoom
    canvas.set_brightness(colors.brightness_percent)
    canvas.coat_overlay={}
    canvas.label_cache={}
    canvas.pack()
    coat=CoatPainter(root,canvas,colors)
    selected=tk.StringVar(panel,value='坐着')

    def redraw():
        # Render the unsaved paint at a representative instant of the real pose.
        if coat.ids is not editor.ids:
            coat.ids,coat.body_ids=editor.ids,editor.body_ids
            coat.paint_area,coat.body_area=editor.paint_area,editor.body_area
            coat.forelegs=editor.forelegs
        coat.set_artwork({'base':editor.base},editor.paint,editor.underpaint)
        now=10.
        pose=PetPose(last_activity=now)
        action=CatPlay()
        pressed=set()
        mode=selected.get()
        if mode=='打字':
            pressed={ord('A'),ord('P')}
            pose.body_follow=(0,30)
            for code in pressed:
                x,y=key_positions[code]
                side='left' if x<194 else 'right'
                pose.stroke_key[side]=code
                pose.targets[side]=(x,y)
                pose.until[side]=now+1
                pose.key_contact[code]=now
        elif mode=='握鼠标':
            pose.mouse_work_until=now+1
            pose.mouse_lean=1.
            pose.body_follow=(0,28)
        elif mode=='伸懒腰':
            action.begin('stretch',now-.65,1.45,'right')
        mouse=(root.winfo_screenwidth()/2,canvas.winfo_rooty()+100*canvas.zoom)
        render_scene(canvas,coat,action,pose,now,mouse,pressed)

    controls=ttk.Frame(panel)
    controls.pack(pady=4)
    for mode in ('坐着','打字','握鼠标','伸懒腰'):
        ttk.Radiobutton(controls,text=mode,variable=selected,value=mode,command=redraw).pack(side='left')
    return redraw

painter = CoatPainter(root, c, colors, make_pose_preview)
colors.short_tail.trace_add('write',lambda *_:painter.set_tail_shape())
colors.open_painter = painter.open
colors.drawing_thumbnail = painter.thumbnail
menu=tk.Menu(root,tearoff=False)
floating_menu=colors.attach(menu,open_size,open_transparency,open_brightness)
floating_menu.add_checkbutton(label='显示浮字',variable=show_keys,command=toggle_key_display)
style_menu=tk.Menu(floating_menu,tearoff=False)
for label,value in [('彩色气泡','bubble'),('彩色文字','text'),('黑色文字','black'),('白色文字','white')]:
    style_menu.add_radiobutton(label=label,variable=colors.floating_style,value=value,command=colors.save)
style_menu.add_command(label='自定义文字 RGB…',command=colors.choose_floating_ink)
style_menu.add_radiobutton(label='带底色的小键帽',variable=colors.floating_style,
                           value='keycap',command=colors.save)
floating_menu.add_cascade(label='浮字样式',menu=style_menu)
colors.add_theme(floating_menu,'浮字按键提示')
menu.add_command(label='丢个纸团',command=play.toss)
for label,toy in [('吹个泡泡','bubble'),('晃晃逗猫棒','wand'),('丢个纸箱','box')]:
    menu.add_command(label=label,command=lambda toy=toy:play.start_toy(toy,time.monotonic()))
menu.add_checkbutton(label='固定/自由小猫',variable=colors.position_fixed,command=colors.save)
menu.add_command(label='暂停 / 继续动作',command=toggle_pause)
updates = UpdateReminder(root, colors.path.parent)
menu.add_command(label='检查更新…',command=lambda:updates.check(manual=True))
menu.add_command(label='退出小猫VCC',command=root.destroy)
c.bind('<ButtonPress-1>',start_drag)
c.bind('<B1-Motion>',move_drag)
c.bind('<ButtonRelease-1>',end_drag)
c.bind('<Button-3>',lambda e:menu.tk_popup(e.x_root,e.y_root))
root.bind('<Escape>',lambda e:root.destroy())

def setup_windows_shortcuts():
    """Register this copy for the current user after its first successful start."""
    script = Path(__file__).resolve()
    launcher = script.parent.parent / '启动小猫.bat'
    if script.parent.name == 'runtime' and launcher.is_file():
        target, arguments = launcher, ''
    else:
        target = Path(sys.executable).with_name('pythonw.exe')
        if not target.is_file():
            target = Path(sys.executable)
        arguments = '-B "' + str(script) + '"'

    stamp = colors.path.parent / 'shortcut-location.txt'
    location = str(target) + '\n' + arguments
    icon = script.with_name('calico-box.ico')
    icon_location = str(icon) + ',0' if icon.is_file() else ''
    if icon_location:
        location += '\n' + icon_location
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        # Pass paths as data, including paths with quotes, spaces or ampersands.
        env = dict(os.environ, VCC_LINK_TARGET=str(target), VCC_LINK_ARGS=arguments,
                   VCC_LINK_DIR=str(launcher.parent if target==launcher else script.parent),
                   VCC_LINK_STAMP=str(stamp), VCC_LINK_LOCATION=location,
                   VCC_LINK_ICON=icon_location)
        command = r"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$name = '小猫 VCC.lnk'
$description = '小猫 VCC · 键盘伙伴'
$wasRegistered = [IO.File]::Exists($env:VCC_LINK_STAMP)
foreach ($folder in 'Programs', 'DesktopDirectory') {
    $dir = [Environment]::GetFolderPath($folder, 'Create')
    $path = [IO.Path]::Combine($dir, $name)
    if ([string]::IsNullOrEmpty($dir)) { throw "Missing folder: $folder" }
    $exists = [IO.File]::Exists($path)
    if ($wasRegistered -and !$exists) { continue } # Respect a deleted shortcut.
    $link = $shell.CreateShortcut($path)
    if ($exists -and $link.Description -ne $description) { continue }
    if ($exists -and $link.TargetPath -eq $env:VCC_LINK_TARGET -and
        [string]$link.Arguments -eq [string]$env:VCC_LINK_ARGS -and
        $link.WorkingDirectory -eq $env:VCC_LINK_DIR -and
        (!$env:VCC_LINK_ICON -or $link.IconLocation -eq $env:VCC_LINK_ICON)) { continue }
    $link.TargetPath = $env:VCC_LINK_TARGET
    $link.Arguments = [string]$env:VCC_LINK_ARGS
    $link.WorkingDirectory = $env:VCC_LINK_DIR
    $link.Description = $description
    if ($env:VCC_LINK_ICON) { $link.IconLocation = $env:VCC_LINK_ICON }
    $link.Save()
}
if (!$wasRegistered -or [IO.File]::ReadAllText($env:VCC_LINK_STAMP) -cne $env:VCC_LINK_LOCATION) {
    [IO.File]::WriteAllText($env:VCC_LINK_STAMP, $env:VCC_LINK_LOCATION)
}
"""
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-Command', command],
                         env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, UnicodeError):
        # A read-only profile or an unavailable shell should not prevent play.
        pass

tick()
if args.smoke_test:
    root.after(1200,root.destroy)
elif __name__ == '__main__':
    root.after_idle(setup_windows_shortcuts)
    root.after(5000,updates.daily)
root.mainloop()

