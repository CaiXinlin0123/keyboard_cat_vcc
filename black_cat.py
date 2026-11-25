import tkinter as tk
from coat_painter import BODY, HEAD, TAIL, CoatPainter, leg_projection, heel_outline, coat_outline
from cat_colors import CatColors, PRESETS, KEY_BASE, KEY_ACCENTS
import ctypes
from ctypes import wintypes
import time
import math
import argparse
import random
from pathlib import Path
import os
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

class PetCanvas(tk.Canvas):
    """Draw in the original pose coordinates at the selected display size."""
    def _create(self, item_type, args, options):
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
        return ImageTk.PhotoImage(source)

c = PetCanvas(root, bg='#ff00ff', highlightthickness=0)
c.zoom = colors.size_percent / 100
width, height = round(W*c.zoom), round(H*c.zoom)
root.geometry('%dx%d+%d+%d' % (width,height,max(0,root.winfo_screenwidth()-width-45),
                                max(0,root.winfo_screenheight()-height-85)))
c.pack(fill='both', expand=True)
ink, cream, gold = '#191a1d', '#fff5d9', '#edc95b'
last_activity = time.monotonic()
previous = set()
targets = {'left':(145,320), 'right':(225,320)}
until = {'left':0, 'right':0}
STROKE_TIME = .22
CONTACT_TIME = .14
stroke_start = {'left':-10., 'right':-10.}
stroke_speed = {'left':0., 'right':0.}
stroke_key = {'left':None, 'right':None}
stroke_origin = {'left':(0,0), 'right':(0,0)}
key_contact = {}
last_mouse = None
mouse_offset = (0.0, 0.0)

def move_mini_mouse(offset, dx, dy):
    # The seated cat faces the user: its forward and right are screen-down and left.
    gain = .11
    return (max(-14, min(10, offset[0] - gain * dx)),
            max(-12, min(12, offset[1] - gain * dy)))
mouse_active_until = 0
mouse_work_until = 0
click_started = {}
last_key_time = 0
CAT_ORIGIN_X = 42
paw_positions = {"left":(CAT_ORIGIN_X+331*.34,297.54),"right":(CAT_ORIGIN_X+447*.34,297.54)}
mouse_lean = 0.0
look_turn = 0.0
head_pitch = 0.0
eye_lowering = 0.0
typing_balance = 0.0
body_follow = (0.0, 0.0)
drag = None
pet_count = 0
last_pet = -10.0
expression = ''
expression_start = 0.0
ANGER_DURATION = 2.0
paused = False
keys = []
pressed_until = {}
label_cache = {}
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

def key_label(label, x, y, dark):
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

def quad(points, color, outline=''):
    return c.create_polygon(*[n for point in points for n in point],fill=color,outline=outline,width=1)

def shade(color, factor):
    return '#'+''.join('%02x'%min(255,int(int(color[i:i+2],16)*factor)) for i in (1,3,5))

def board_rect(x,y,w,h,z=0):
    return [project(x,y,z),project(x+w,y,z),project(x+w,y+h,z),project(x,y+h,z)]

def oval(x1,y1,x2,y2,fill,outline='',width=1):
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

def draw_paw(x,bottom,w,h,tag,fur,stroke,tip_color,wide_tip=False):
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

coat_overlay = {}

def draw_coat_shading(shapes):
    # Match Tk's closed quadratic splines. Blur the combined silhouette so the
    # neck and patch boundaries stay continuous as the head and shoulders move.
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

def draw(now, mouse, pressed):
    global mouse_lean, body_follow, typing_balance, look_turn, eye_lowering, head_pitch
    c.delete('all')
    idle = now-last_activity > 18
    quiet = max(0, now-last_activity-2)
    breath = .005*(1-math.cos(2*math.pi*quiet/4)) if not pressed and not paused else 0
    # Trace the supplied front-view reference in its original proportions.
    held_buttons = pressed & {1,2}
    mouse_buttons = held_buttons or {button for button in (1,2) if now < pressed_until.get(button,0)}
    if paused:
        mouse_buttons = set()
    mouse_down = bool(mouse_buttons)
    mouse_pose = not paused and (now < mouse_work_until or
                                 (now < mouse_active_until and now-last_key_time>.35))
    leaning = mouse_pose or mouse_down
    # Bridge the short gaps between taps so the torso settles during a word.
    sharing = leaning and now < until['right'] + .18 and now-last_key_time < .34
    typing_balance += (float(sharing)-typing_balance)*.32
    mouse_lean += (float(leaning)-mouse_lean)*.38
    if mouse_lean < .002:
        mouse_lean = 0.0

    # A forward push is screen-down for the cat. Reach a little left and down.
    mx,my = mouse_offset
    target_x = .24*mx - .33*my if leaning else 0.0
    target_y = 28 + 3*typing_balance + .60*my if leaning else 0.0
    gaze_key = None
    if leaning and now < until['right'] and stroke_key['right'] is not None:
        # The free paw can cross the entire board. Look at its actual target.
        gaze_key = targets['right']
        idle = False
    elif not leaning and not paused:
        # Prefer held keys; retain a short tap just long enough to see it.
        held = pressed.intersection(key_positions)
        visible = held or {k for k in key_positions if pressed_until.get(k,0)>now}
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
    follow_x,follow_y = body_follow
    shoulder_rate=.15 if gaze_key is not None else .28
    body_follow = (follow_x+shoulder_rate*(target_x-follow_x), follow_y+shoulder_rate*(target_y-follow_y))
    # Add a small yaw around the existing three-quarter pose, eased with the reach.
    yaw = math.radians(max(-3.3,min(3.3,.75*body_follow[0])))
    width_change = math.cos(math.radians(18)-yaw)/math.cos(math.radians(18))-1

    # Dual-input reference: the head sits about one sixth of a head-width
    # towards the mouse from the hips. The forelegs can still reach fully.
    torso_lean = mouse_lean * (1-.70*typing_balance)
    face_turn = mouse_lean * (1-.83*typing_balance)
    if gaze_key is not None:
        look_direction=(gaze_key[0]-(CAT_ORIGIN_X+390*.34+body_follow[0]))/100
    else:
        look_direction=2*mouse[0]/max(1,root.winfo_screenwidth())-1
    look_turn += .36*((0 if idle or paused else max(-1,min(1,look_direction)))-look_turn)
    def ref(x,y,tilt=True):
        x += (x-390)*.7*breath
        y += (y-852)*breath
        weight = max(0,min(1,(790-y)/430)) if tilt else 0
        x += (x-390)*width_change*weight
        return (CAT_ORIGIN_X+(x-208*torso_lean*weight)*.34 + body_follow[0]*weight,
                15+y*.34 + body_follow[1]*weight)
    # Measure height from the cat's eyes, even after the window is dragged.
    eye_screen_y = c.winfo_rooty() + c.zoom * ref(390,246)[1]
    distance_y = mouse[1] - eye_screen_y
    pitch_target = math.copysign(min(1,max(0,abs(distance_y)-10)/140),distance_y)
    if idle or paused or gaze_key is not None:
        pitch_target = 0
    head_pitch += .17*(pitch_target-head_pitch)
    age=max(0,now-expression_start)
    reaction=expression if age < {'squint':.82,'yawn':1.55,'annoyed':ANGER_DURATION}.get(expression,0) else ''
    gape=math.sin(math.pi*age/1.55)**1.3 if reaction=='yawn' else 0
    horizontal_turn=1.1*look_turn-face_turn+2*math.sin(yaw)
    def face(x,y,depth=0):
        # Fur follows the curved face: the blaze projects farther forward
        # than the cheeks, while the ears and outer contour stay anchored.
        cheek_curve=max(0,1-((x-390)/175)**2)
        brow_curve=max(0,1-((y-250)/120)**2)
        surface_depth=depth or 36*cheek_curve*brow_curve
        fx=x+horizontal_turn*surface_depth-.08*face_turn*(x-390)
        fx+=look_turn*12-abs(look_turn)*.047*(x-390)
        fy=y+(face_turn*.08+look_turn*.024)*(x-390)
        # Keep the neck anchored; the ears and forward facial features move most.
        fy+=head_pitch*(.057*(397-y)+.42*depth)
        return ref(fx,fy-8*gape)
    def contour(points,fill=ink,width=0,project_point=ref):
        return c.create_polygon(*[n for x,y in points for n in project_point(x,y)],
                         fill=fill,smooth=True,splinesteps=24,outline=stroke if width else '',width=width)
    # Fuchsia is the window's transparency key. Use its closest opaque neighbour.
    def visible(color):
        return '#fe00ff' if color=='#ff00ff' else color
    coat=visible(colors.current['身体'])
    artwork = painter.active()
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
        anchor=mouse_lean*max(0,min(1,(TAIL[-1][0]-x)/(TAIL[-1][0]-root_x)))
        px+=(hip_x-rest_x-6)*anchor
        py+=(hip_y-rest_y)*anchor
        bend=((x-565)/214)**2*turn
        return px+2*bend,py-bend

    def hind_paw_point(x,y):
        px,py=ref(x,y)
        # Shift weight above the sole; the nearer paw shows a little more white.
        height=max(0,min(1,(852-y)/71))
        side=-1 if x<390 else 1
        return px+1.4*height*turn,py+.8*height*turn*side

    # Tail, broad pear-shaped torso, and tucked white hind toes.
    tail=[n for x,y in TAIL for n in tail_point(x,y)]
    if stroke:
        c.create_line(*tail,fill=stroke,width=22,smooth=True,capstyle=tk.ROUND)
    tail_fur={'calico':'#151515','ginger_white':patch_color}.get(coat,flat)
    c.create_line(*tail,fill=tail_fur,width=19,smooth=True,capstyle=tk.ROUND)
    if artwork:
        painter.render('tail', tail_point)
    if tuxedo:
        c.create_line(*tail_point(758,566),*tail_point(779,560),
                      fill=white_fur,width=18,capstyle=tk.ROUND)
    if patched or tabby:
        band=stripe if tabby else '#e69a55'
        for a,b in [((606,690),(634,686)),((671,660),(688,635)),((715,599),(733,580))]:
            c.create_line(*tail_point(*a),*tail_point(*b),fill=band,width=17,capstyle=tk.BUTT)
        if tabby:
            c.create_line(*tail_point(757,567),*tail_point(779,560),fill=stripe,width=18,capstyle=tk.ROUND)
    body_shape, head_shape = BODY, HEAD
    # Put both silhouettes' borders beneath both fills, hiding their common seam.
    if stroke:
        contour(body_shape,flat,width=1.6)
        contour(head_shape,face_fur,width=1.6,project_point=face)
    torso_item = contour(body_shape,flat)
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
        lift=mouse_lean*60
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
    contour(head_shape,face_fur,project_point=face)
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
        draw_coat_shading(([ref(x,y) for x,y in body_shape],[face(x,y) for x,y in head_shape]))
    blink = idle or (now % 5.5 < .13)
    if gaze_key is not None:
        cx,cy=face(388,246,depth=28)
        down=gaze_key[1]-cy
        lowering=max(0,down/max(1,math.hypot(gaze_key[0]-cx,down)))
    else:
        lowering=.35*max(0,head_pitch)
    eye_lowering+=(lowering-eye_lowering)*(.34 if lowering>eye_lowering else .18)
    eye_scale=1-.22*eye_lowering
    for ex in (316,459):
        x,y=face(ex,246,depth=28)
        eye_width=17-face_turn*(3.5 if ex==316 else .8)
        eye_width-=1.9*max(0,look_turn if ex==459 else -look_turn)
        if reaction in ('squint','yawn','annoyed'):
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
            y+=1.2*eye_lowering
            oval(x-eye_width,y-14*eye_scale,x+eye_width,y+14*eye_scale,iris,eye_outline,1.5)
            dx=max(-4,min(4,(mouse[0]/max(1,root.winfo_screenwidth())-.5)*8))
            dy=2*head_pitch
            if gaze_key is not None:
                vx,vy=gaze_key[0]-x,gaze_key[1]-y
                distance=max(1,math.hypot(vx,vy))
                dx,dy=10*vx/distance,3.8*vy/distance
            oval(x-5+dx,y+(-10+dy)*eye_scale,x+5+dx,y+(10+dy)*eye_scale,pupil)
    if reaction=='yawn':
        x,y=face(390,320,14)
        oval(x-3-5*gape,y-1-8*gape,x+3+5*gape,y+1+9*gape,'#462b31','#241d20')
        if gape>.45:
            oval(x-4*gape,y+3*gape,x+4*gape,y+7*gape,'#d98e92')
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
    for item in c.find_all():
        if c.type(item)!='image':
            c.addtag_withtag('pet_target',item)
    top=board_rect(69,292,252,95)
    bottom=[(x,y+10) for x,y in top]
    base_color=colors.palette_color('键盘',white)
    if base_color!=white:
        shell=dark_color(base_color) if dark else base_color
        front,side,edge,plate,rim,well=[shade(shell,n) for n in (.68,.78,.55,.94,1.08,.81)]
    elif dark:
        front,side,edge,plate,rim,well=('#24292e','#333a40','#121518','#22262a','#4b5258','#101215')
    else:
        front,side,edge,plate,rim,well=('#9ca9b0','#b2bec3','#77868e','#e9eeee','#fafdfd','#c4ced0')
    board_layer=quad([top[0],top[1],bottom[1],bottom[0]],front,edge)
    quad([top[0],top[3],bottom[3],bottom[0]],side,edge)
    quad(top,plate,rim)
    quad(board_rect(73,296,244,87),well)
    cap_colors={key:colors.palette_color('键盘',key) for key in (white,)+KEY_ACCENTS}
    if dark:
        cap_colors={key:dark_color(value) for key,value in cap_colors.items()}
    keyboard_labels = colors.keyboard_labels.get()
    for x,y,w,h,label,code,color in sorted(keys,key=lambda k:project(k[0],k[1])[1]):
        impact = key_contact.get(code, -1)
        down = (not paused and code in key_contact and impact <= now
                and (code in pressed or now < impact+.075))
        height = .5 if down else 6
        color=cap_colors[color]
        color = shade(color,.93) if down else color
        base=board_rect(x,y,w,h)
        quad(board_rect(x-.5,y-.5,w+1,h+1),'#383d42' if dark else '#7e8a90')
        cap=board_rect(x+.5,y+.5,w-1,h-1,height)
        quad([cap[0],cap[1],base[1],base[0]],shade(color,.72))
        quad([cap[0],cap[3],base[3],base[0]],shade(color,.83))
        quad(cap,color,shade(color,.86))
        tx,ty=project(x+w/2,y+h/2,height)
        if keyboard_labels:
            c.create_image(tx,ty,image=key_label(label,x+w/2,y+h/2,dark))
    # Mouse in the cat's operating direction: palm end near the cat,
    # front buttons farther away, towards the viewer's lower left.
    def mp(x,y,z=0):
        return (57+mouse_offset[0]+17*x-11*y, 318+mouse_offset[1]+7*x+18*y-z)
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
        reach=mouse_lean
        if side=='left':
            start=ref(306-36*reach,609-94*reach)
            rest=ref(331,831)
            # Rest between the buttons and pivot slightly towards the clicked side.
            palm_y = .40 - (.12 if mouse_down else .35)*typing_balance
            contact=mp(.22*(int(left_down)-int(right_down)),palm_y,2 if mouse_down else 4)
        else:
            # Let the shoulder follow the turned chest while the paw stays planted.
            start=ref(458+12*reach-18*torso_lean,609-43*reach)
            rest=ref(447,831)
            edge_x,edge_y=project(190,387)
            contact=(edge_x,edge_y+3)
        active = now < until[side] and not paused
        shoulder_drop = max(0,body_follow[1])*.29
        if side=='left':
            shoulder_drop += 5*reach
        start=(start[0], start[1]+shoulder_drop)
        kx,ky = targets[side] if active else rest
        if active:
            ky+=5.5
            elapsed=max(0,now-stroke_start[side])
            duration=CONTACT_TIME-.085*stroke_speed[side]
            lift_time=.46*duration
            ox,oy=stroke_origin[side]
            # Fold the paw towards the chest before extending to the key.
            apex=(start[0]+(-8 if side=='left' else 8),start[1]+20)
            speed=stroke_speed[side]
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
        elif not leaning and now < until['right' if side=='left' else 'left']+.28 and not paused:
            kx,ky=start[0]+(-8 if side=='left' else 8),start[1]+22
        hand_reach = 0 if active and side=='right' else reach
        tx=kx+(contact[0]-kx)*hand_reach
        ty=ky+(contact[1]-ky)*hand_reach
        oldx,oldy=paw_positions[side]
        if not active:
            tx,ty=oldx+(tx-oldx)*.6,oldy+(ty-oldy)*.6
        paw_positions[side]=(tx,ty)
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
        draw_paw(tx,toe_bottom,toe_width,toe_height,tag,toe_fur,stroke if artwork or whisker=='#191919' else '',
                 flat if artwork else stripe if tabby else '#f6f5ed',wide_tip=orange_tabby)
        if artwork:
            center = 331 if side=='left' else 447
            painter.render(side+'_paw', lambda x,y: (tx+(x-center)*.34*toe_width/13,
                toe_bottom + ((y-831)*.34-9)*toe_height/(13*.92)), tag)
        if side=='right' and reach>.5 and not active:
            c.tag_lower(tag,board_layer)
    if colors.click_marks.get() and not paused:
        for button,born in click_started.items():
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
    if floating_keys:
        draw_floating_keys(now,ref(390,575))

def tick():
    global previous,last_activity,last_mouse,mouse_active_until,last_key_time
    global mouse_offset,mouse_work_until
    now=time.monotonic()
    point=wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    mouse=(point.x,point.y)
    if not paused and last_mouse is not None and mouse != last_mouse:
        mouse_offset = move_mini_mouse(mouse_offset, mouse[0]-last_mouse[0], mouse[1]-last_mouse[1])
    watched={1,2,*key_positions}
    if show_keys.get():
        watched.update(range(96,106))
    pressed={k for k in watched if user32.GetAsyncKeyState(k)&0x8000}
    if drag and drag['hit']:
        pressed.discard(1)
    fresh=pressed-previous
    if colors.click_marks.get() and not paused:
        for button in fresh & {1,2}:
            click_started[button]=now
    if last_mouse is not None and mouse!=last_mouse or pressed & {1,2}:
        mouse_active_until=now+2
        mouse_work_until=now+.35
    if fresh-{1,2}:
        last_key_time=now
    if not paused:
        for code in pressed:
            pressed_until[code]=now+.10
    if pressed or previous or (last_mouse is not None and mouse!=last_mouse):
        last_activity=now
    if not paused:
        for side,code in stroke_key.items():
            if code is None:
                continue
            impact=key_contact[code]
            if code in pressed:
                last_key_time=now
            elif code not in pressed:
                until[side]=min(until[side],max(now,impact+STROKE_TIME-CONTACT_TIME))
        if now < mouse_work_until and now < until['left']:
            if until['left'] >= until['right']:
                targets['right']=targets['left']
                until['right']=until['left']
                stroke_origin['right']=paw_positions['right']
                stroke_key['right']=stroke_key['left']
                stroke_start['right']=stroke_start['left']
                stroke_speed['right']=stroke_speed['left']
            until['left']=0
            stroke_key['left']=None
        for k in sorted(fresh-{1,2}):
            if show_keys.get() and 96<=k<=105:
                add_floating_key(k,now)
            if k in key_positions:
                position = key_positions[k]
                side='left' if position[0]<194 and now>=mouse_work_until else 'right'
                old=stroke_key[side]
                origin=paw_positions[side]
                if old is not None and old!=k and key_contact[old]>now:
                    key_contact[old]=now
                    origin=(targets[side][0],targets[side][1]+5.5)
                gap=now-stroke_start[side]
                stroke_speed[side]=max(0,min(1,(.34-gap)/.22))
                stroke_start[side]=now
                targets[side]=position
                stroke_origin[side]=origin
                stroke_key[side]=k
                until[side]=math.inf  # Release the paw when the physical key comes up.
                key_contact[k]=now+CONTACT_TIME-.085*stroke_speed[side]
                if show_keys.get():
                    add_floating_key(k,now)
    previous=pressed
    last_mouse=mouse
    draw(now,mouse,pressed)
    root.after(25,tick)

def start_drag(e):
    global drag
    hit=False
    for item in reversed(c.find_overlapping(e.x,e.y,e.x,e.y)):
        tags=c.gettags(item)
        if 'floating_key' in tags or 'click_mark' in tags or (c.type(item)=='image' and not tags):
            continue
        hit=any(t in tags for t in ('pet_target','foreleg_left','foreleg_right'))
        break
    drag=dict(x=e.x_root,y=e.y_root,wx=root.winfo_x(),wy=root.winfo_y(),hit=hit,moved=False)

def move_drag(e):
    if drag:
        dx,dy=e.x_root-drag['x'],e.y_root-drag['y']
        if drag['moved'] or max(abs(dx),abs(dy))>=5:
            drag['moved']=True
            root.geometry('+%d+%d'%(drag['wx']+dx,drag['wy']+dy))

def end_drag(e):
    global drag,pet_count,last_pet,expression,expression_start
    gesture,drag=drag,None
    if not gesture or gesture['moved'] or not gesture['hit'] or paused:
        pet_count=0
        return
    now=time.monotonic()
    if expression=='annoyed' and now-expression_start<ANGER_DURATION:
        return
    pet_count=pet_count+1 if now-last_pet<=.65 else 1
    last_pet=now
    if 4 <= pet_count < 10 and expression=='yawn' and now-expression_start<1.55:
        return
    expression={3:'yawn',10:'annoyed'}.get(pet_count,'squint')
    expression_start=now
    if pet_count==10:
        pet_count=0

def toggle_pause():
    global paused
    paused=not paused

size_dialog = None

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
    label_cache.clear()
    volume_cache.clear()
    coat_overlay.clear()
    colors.save()

def open_size():
    global size_dialog
    if size_dialog is not None and size_dialog.winfo_exists():
        size_dialog.lift()
        return
    size_dialog = tk.Toplevel(root)
    size_dialog.title('小猫大小')
    size_dialog.attributes('-topmost', True)
    size_dialog.resizable(False, False)
    slider = tk.Scale(size_dialog, label='大小（%）', from_=50, to=175,
                      orient='horizontal', length=240, resolution=1)
    slider.set(colors.size_percent)
    slider.configure(command=resize_pet)
    slider.pack(padx=14, pady=10)
    tk.Button(size_dialog, text='恢复 100%', command=lambda: slider.set(100)).pack(pady=(0,10))
    size_dialog.bind('<Escape>', lambda event: size_dialog.destroy())

painter = CoatPainter(root, c, colors)
colors.open_painter = painter.open
colors.drawing_thumbnail = painter.thumbnail
menu=tk.Menu(root,tearoff=False)
floating_menu=colors.attach(menu,open_size)
floating_menu.add_checkbutton(label='显示浮字',variable=show_keys,command=toggle_key_display)
style_menu=tk.Menu(floating_menu,tearoff=False)
for label,value in [('彩色气泡','bubble'),('彩色文字','text'),('黑色文字','black'),('白色文字','white')]:
    style_menu.add_radiobutton(label=label,variable=colors.floating_style,value=value,command=colors.save)
style_menu.add_command(label='自定义文字 RGB…',command=colors.choose_floating_ink)
style_menu.add_radiobutton(label='带底色的小键帽',variable=colors.floating_style,
                           value='keycap',command=colors.save)
floating_menu.add_cascade(label='浮字样式',menu=style_menu)
colors.add_theme(floating_menu,'浮字按键提示')
menu.add_command(label='暂停 / 继续动作',command=toggle_pause)
menu.add_command(label='退出小猫VCC',command=root.destroy)
c.bind('<ButtonPress-1>',start_drag)
c.bind('<B1-Motion>',move_drag)
c.bind('<ButtonRelease-1>',end_drag)
c.bind('<Button-3>',lambda e:menu.tk_popup(e.x_root,e.y_root))
root.bind('<Escape>',lambda e:root.destroy())
tick()
if args.smoke_test:
    root.after(1200,root.destroy)
root.mainloop()

