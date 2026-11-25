import base64
import io
import math
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from functools import lru_cache
from PIL import Image, ImageDraw, ImageTk, ImageFilter, ImageChops
from cat_colors import MAX_DRAWINGS, pick_rgb

BODY=[(240,359),(307,331),(472,331),(536,367),(558,441),
             (590,549),(601,650),(588,744),(561,786),(521,812),
             (451,829),(320,829),(241,797),(204,767),(181,705),
             (177,631),(188,548),(211,454)]
HEAD=[(225,215),(225,153),(234,105),(247,77),(267,77),
             (298,103),(330,137),(369,129),(410,129),(445,138),
             (474,104),(504,77),(524,76),(541,105),(548,154),
             (549,214),(566,251),(575,288),(569,322),(550,354),
             (530,374),(481,390),(391,397),(303,390),(251,371),
             (224,340),(208,305),(206,269),(214,238)]

TAIL = [(565,690),(633,692),(670,672),(702,613),(745,567),(779,560)]
BOB_X, BOB_Y, BOB_RADIUS = 606, 690, 27
SIZE = (352, 420)
LAYERS = ('tail','body','250','528','head','left','left_paw','right','right_paw')


def heel_outline(cx):
    return [(cx+x,812+y) for x,y in [(-40,-13),(-29,-35),(4,-40),(34,-25),(41,0),
                                      (32,25),(13,39),(-14,39),(-34,26),(-43,7)]]


def pixel(x,y):
    return ((x-140)/2,(y-45)/2)


# The tail makes the canvas wider on the right. Align guides and strokes to the torso.
MIRROR_X = int(pixel(390,0)[0])


def reference(u,v):
    return (140+2*u,45+2*v)


def coat_outline(base):
    red,green,blue=bytes.fromhex(base[1:])
    return '#000000' if .2126*red+.7152*green+.0722*blue>135 else '#ffffff'


def spline(points, closed=True):
    pts = list(points)
    chain = [pts[-1]]+pts+[pts[0]] if closed else [pts[0]]+pts+[pts[-1]]
    result = []
    for a,b,d in zip(chain,chain[1:],chain[2:]):
        for j in range(10):
            t=j/10
            result.append(tuple(b[k]+((a[k]-b[k])*(1-t)**2+(d[k]-b[k])*t*t)/2 for k in (0,1)))
    if not closed:
        result.append(pts[-1])
    return result


def leg_projection(side,shoulder,wrist,reach):
    # Project the resting paint along the straight shoulder-to-wrist axis.
    x0,end=(306,331) if side=='left' else (458,447)
    dx,dy=end-x0,222
    length=math.hypot(dx,dy)
    vx,vy=wrist[0]-shoulder[0],wrist[1]-shoulder[1]
    live=max(.01,math.hypot(vx,vy))
    def project(x,y):
        along=((x-x0)*dx+(y-609)*dy)/length**2
        across=((x-x0)*dy-(y-609)*dx)/length*.34
        across*=1-(2 if side=='left' else 1)*reach/(18-7*max(0,min(1,along)))
        return (shoulder[0]+along*vx+across*vy/live,shoulder[1]+along*vy-across*vx/live)
    return project


def tail_path():
    center=[pixel(x,y) for x,y in spline(TAIL,False)]
    left,right=[],[]
    for i,(x,y) in enumerate(center):
        ax,ay=center[max(0,i-1)]
        bx,by=center[min(i+1,len(center)-1)]
        length=math.hypot(bx-ax,by-ay)
        nx,ny=14*(by-ay)/length,14*(ax-bx)/length
        left.append((x+nx,y+ny))
        right.append((x-nx,y-ny))
    return left+right[::-1]


def atlas(show_legs=True,short_tail=False):
    # Each pixel belongs to the foremost visible piece of fur in the resting pose.
    ids=Image.new('L', SIZE)
    d=ImageDraw.Draw(ids)
    def polygon(points,part):
        d.polygon([pixel(x,y) for x,y in spline(points)],fill=LAYERS.index(part)+1)
    def disc(x,y,rx,ry,part):
        d.ellipse([pixel(x-rx,y-ry),pixel(x+rx,y+ry)],fill=LAYERS.index(part)+1)
    if short_tail:
        disc(BOB_X,BOB_Y,BOB_RADIUS,BOB_RADIUS,'tail')
    else:
        d.polygon(tail_path(),fill=1)
        for x,y in (TAIL[0],TAIL[-1]):
            disc(x,y,28,28,'tail')
    polygon(BODY,'body')
    for x in (250,528):
        polygon([(u,v-5) for u,v in heel_outline(x)],str(x))
    polygon(HEAD,'head')
    if not show_legs:
        return ids
    for side,x0,x1 in [('left',306,331),('right',458,447)]:
        dx,dy=x1-x0,222
        length=math.hypot(dx,dy)
        edges=[[],[]]
        for t,r in [(0,18),(.18,17),(.48,14),(.72,12),(.94,11.5),(1,11)]:
            for edge,sign in zip(edges,(-1,1)):
                edge.append((x0+t*dx+sign*r/.34*dy/length,609+t*dy-sign*r/.34*dx/length))
        polygon(edges[0]+[(x1,831+3/.34)]+edges[1][::-1],side)
        disc(x1,831+(9-13*.92)/.34,13/.34,13*.92/.34,side+'_paw')
    return ids


def outline_guide(ids,parts,adjacent_to=None):
    # Trace the exact regions that attach paint to each moving body part.
    guide=Image.new('RGBA',ids.size)
    for part in parts:
        region=ids.point(lambda n:255 if n==LAYERS.index(part)+1 else 0)
        inner=ImageChops.subtract(region,region.filter(ImageFilter.MinFilter(3)))
        outer=ImageChops.subtract(region.filter(ImageFilter.MaxFilter(3)),region)
        if adjacent_to is not None:
            neighbor=ids.point(lambda n:255 if n==LAYERS.index(adjacent_to)+1 else 0)
            inner=ImageChops.darker(inner,neighbor.filter(ImageFilter.MaxFilter(3)))
            outer=ImageChops.darker(outer,neighbor)
        guide.paste((252,252,250,170),mask=outer)
        guide.paste((43,48,54,190),mask=inner)
    return guide


# Earlier releases drew short thick segments with gaps between them. Only
# reconstruct newly paintable pixels, preserving erased areas in old artwork.
@lru_cache(maxsize=1)
def tail_repairs():
    old=Image.new('L',SIZE)
    draw=ImageDraw.Draw(old)
    draw.line([pixel(x,y) for x,y in spline(TAIL,False)],fill=255,width=28)
    for x,y in (TAIL[0],TAIL[-1]):
        draw.ellipse([pixel(x-28,y-28),pixel(x+28,y+28)],fill=255)
    new=atlas().point(lambda n:255 if n==1 else 0)
    gaps=ImageChops.subtract(new,old)
    steps=[]
    while gaps.getbbox():
        known=old.copy()
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            take=ImageChops.darker(gaps,ImageChops.offset(known,dx,dy))
            box=take.getbbox()
            if box:
                source=tuple(n-(dx if i%2==0 else dy) for i,n in enumerate(box))
                steps.append((source,box,take.crop(box)))
                old=ImageChops.lighter(old,take)
                gaps=ImageChops.subtract(gaps,take)
        if old==known:
            break
    return steps


def texture(record,field='png'):
    if field not in record:
        return Image.new('RGBA',SIZE)
    with Image.open(io.BytesIO(base64.b64decode(record[field]))) as image:
        if image.size != SIZE:
            raise ValueError('画布尺寸不符')
        paint=image.convert('RGBA')
    if field=='png' and record.get('tail_version',1)<2:
        for source,box,mask in tail_repairs():
            paint.paste(paint.crop(source),box,mask)
    return paint


def encode_texture(image):
    stream=io.BytesIO()
    image.save(stream,format='PNG')
    return base64.b64encode(stream.getvalue()).decode('ascii')


class CoatPainter:
    def __init__(self,root,canvas,settings,make_preview=None):
        self.root,self.canvas,self.settings=root,canvas,settings
        self.window=None
        self.record=None
        self.images={}
        self.parts={}
        self.make_preview=make_preview
        self.preview_redraw=None
        self.preview_pending=None
        self.set_tail_shape()

    def set_tail_shape(self):
        short=self.settings.short_tail.get()
        self.ids=atlas(short_tail=short)
        self.outside=self.ids.point(lambda n: 255 if n==0 else 0)
        silhouette=ImageChops.invert(self.outside)
        self.paint_area=silhouette.filter(ImageFilter.MinFilter(5))
        self.outer_rim=ImageChops.subtract(silhouette,self.paint_area)
        self.body_ids=atlas(show_legs=False,short_tail=short)
        self.body_mask=self.body_ids.point(lambda n:255 if n else 0)
        self.body_area=self.body_mask.filter(ImageFilter.MinFilter(5))
        self.body_rim=ImageChops.subtract(self.body_mask,self.body_area)
        self.forelegs=self.ids.point(lambda n:255 if n>=LAYERS.index('left')+1 else 0)
        self.record=None
        self.parts.clear()
        self.images.clear()
        if self.window and self.window.winfo_exists():
            self.tail_guide_pixels=outline_guide(self.ids,('tail',),adjacent_to='body')
            self.display_size=(0,0)
            self.refresh()

    def active(self):
        record=self.settings.active_drawing()
        if record is not self.record:
            if record:
                paint=texture(record)
                underneath=texture(record,'underpaint') if record.get('underpaint') else None
                self.set_artwork(record,paint,underneath)
            else:
                self.record=None
                self.parts.clear()
                self.images.clear()
        return record

    def set_artwork(self,record,paint,underneath):
        self.record=record
        self.parts.clear()
        self.images.clear()
        for i,part in enumerate(LAYERS,1):
            mask=ImageChops.darker(self.paint_area,self.ids.point(lambda n:255 if n==i else 0))
            layer=Image.new('RGBA',SIZE)
            layer.paste(paint,mask=mask)
            if underneath is not None and i<=LAYERS.index('left'):
                region=self.body_ids.point(lambda n:255 if n==i else 0)
                covered=ImageChops.darker(self.forelegs,ImageChops.darker(region,self.body_area))
                layer.paste(underneath,mask=covered)
            bounds=layer.getbbox()
            if bounds:
                self.parts[part]=(bounds,layer.crop(bounds))

    def render(self,part,project,tag=None):
        if part not in self.parts:
            return
        (u,v,_,_),image=self.parts[part]
        w,h=image.size
        def pos(a,b):
            return project(*reference(a+u,b+v))
        # Sample the inverse surface on a small mesh so paint bends with the face and chest.
        corners=[pos(w*i/2,h*j/2) for i in range(3) for j in range(3)]
        x0=math.floor(min(x for x,y in corners))-2
        y0=math.floor(min(y for x,y in corners))-2
        width=math.ceil(max(x for x,y in corners))-x0+2
        height=math.ceil(max(y for x,y in corners))-y0+2
        def inverse(x,y):
            a,b=w/2,h/2
            for _ in range(3):
                px,py=pos(a,b)
                ax,ay=pos(a+1,b)
                bx,by=pos(a,b+1)
                ax,ay,bx,by=ax-px,ay-py,bx-px,by-py
                det=ax*by-ay*bx
                if abs(det)<.0001:
                    break
                ex,ey=x+x0-px,y+y0-py
                a+=(by*ex-bx*ey)/det
                b+=(ax*ey-ay*ex)/det
                if abs(ex)+abs(ey)<.08:
                    break
            return a,b
        xs=list(range(0,width,28))+[width]
        ys=list(range(0,height,28))+[height]
        grid={(x,y):inverse(x,y) for x in xs for y in ys}
        mesh=[]
        for l,r in zip(xs,xs[1:]):
            for t,b in zip(ys,ys[1:]):
                quad=grid[l,t]+grid[l,b]+grid[r,b]+grid[r,t]
                mesh.append(((l,t,r,b),quad))
        warped=image.transform((width,height),Image.Transform.MESH,mesh,Image.Resampling.BILINEAR)
        base=self.record['base']
        self.images[part]=self.canvas.photo(warped,fur_base='#fe00ff' if base=='#ff00ff' else base)
        self.canvas.create_image(x0,y0,anchor='nw',image=self.images[part],tags=tag or ())

    def open(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            return
        self.window=tk.Toplevel(self.root)
        self.window.withdraw()
        self.window.title('自定义绘制')
        self.window.attributes('-topmost',True)
        panel=ttk.Frame(self.window,padding=10)
        panel.pack(fill='both',expand=True)
        panel.columnconfigure(0,weight=1)
        panel.rowconfigure(2,weight=1)
        self.capacity=ttk.Label(panel)
        self.capacity.grid(row=0,column=0,sticky='w',pady=(0,4))
        name_row=ttk.Frame(panel)
        name_row.grid(row=1,column=0,sticky='ew',pady=(0,6))
        self.choice=ttk.Combobox(name_row,state='readonly',width=22)
        self.choice.pack(side='left',padx=(0,10))
        self.choice.bind('<<ComboboxSelected>>',lambda e:self.load())
        ttk.Label(name_row,text='小猫名字').pack(side='left',padx=(0,6))
        self.name=tk.StringVar(self.window)
        ttk.Entry(name_row,textvariable=self.name).pack(side='left',fill='x',expand=True)
        workspace=ttk.Frame(panel)
        workspace.grid(row=2,column=0,sticky='nsew')
        workspace.columnconfigure(0,weight=1)
        workspace.rowconfigure(0,weight=1)
        self.board=tk.Canvas(workspace,width=round(SIZE[0]*1.75),height=round(SIZE[1]*1.75),
                             bg='#e6e4df',highlightthickness=0,cursor='crosshair')
        self.board.grid(row=0,column=0,sticky='nsew')
        sidebar=ttk.Frame(workspace)
        sidebar.grid(row=0,column=1,sticky='n',padx=(8,0))
        if self.make_preview:
            self.preview_redraw=self.make_preview(sidebar,self)
            self.window.bind('<Destroy>',self.close_preview,add='+')
        self.gallery_index=tk.IntVar(self.window)
        self.gallery=ttk.LabelFrame(sidebar,text='最近保存')
        self.preview_item=self.board.create_image(0,0,anchor='nw')
        self.guide_pixels=outline_guide(self.ids,('left','left_paw','right','right_paw'))
        self.guide_item=self.board.create_image(0,0,anchor='nw')
        self.head_guide_pixels=outline_guide(self.ids,('head',))
        self.head_guide_item=self.board.create_image(0,0,anchor='nw')
        self.tail_guide_pixels=outline_guide(self.ids,('tail',),adjacent_to='body')
        self.tail_guide_item=self.board.create_image(0,0,anchor='nw')
        self.display_size=(0,0)
        self.board_origin=(0,0)
        for color,dash in (('#fafafa',()),('#565656',(4,4))):
            self.board.create_line(MIRROR_X,0,MIRROR_X,SIZE[1],fill=color,dash=dash,
                                   tags='mirror_axis',state='hidden')
        self.show_axis=tk.BooleanVar(self.window,value=False)
        self.show_forepaws=tk.BooleanVar(self.window,value=True)
        self.show_head_guide=tk.BooleanVar(self.window,value=True)
        self.show_tail_guide=tk.BooleanVar(self.window,value=True)
        modes=ttk.Frame(panel)
        modes.grid(row=3,column=0,sticky='ew',pady=(6,0))
        self.mode=tk.StringVar(self.window,value='pen')
        self.symmetric=tk.BooleanVar(self.window,value=False)
        for label,value in [('画笔','pen'),('吸管','pick'),('橡皮擦','erase')]:
            ttk.Radiobutton(modes,text=label,variable=self.mode,value=value).pack(side='left',padx=2)
        ttk.Checkbutton(modes,text='左右对称',variable=self.symmetric).pack(side='right')
        view=ttk.Frame(panel)
        view.grid(row=4,column=0,sticky='ew')
        self.show_legs=tk.BooleanVar(self.window,value=True)
        ttk.Checkbutton(view,text='显示前腿',variable=self.show_legs,command=self.refresh).pack(side='left')
        self.guide_toggle=ttk.Checkbutton(view,text='前脚参考线',variable=self.show_forepaws,command=self.refresh)
        self.guide_toggle.pack(side='left')
        ttk.Checkbutton(view,text='头部轮廓线',variable=self.show_head_guide,
                        command=lambda:self.board.itemconfigure(self.head_guide_item,
                            state='normal' if self.show_head_guide.get() else 'hidden')).pack(side='left')
        ttk.Checkbutton(view,text='尾根分界线',variable=self.show_tail_guide,
                        command=lambda:self.board.itemconfigure(self.tail_guide_item,
                            state='normal' if self.show_tail_guide.get() else 'hidden')).pack(side='left')
        ttk.Checkbutton(view,text='中轴辅助线',variable=self.show_axis,
                        command=lambda:self.board.itemconfigure('mirror_axis',
                            state='normal' if self.show_axis.get() else 'hidden')).pack(side='right')
        tools=ttk.Frame(panel)
        tools.grid(row=5,column=0,sticky='ew',pady=4)
        self.ink='#db8845'
        self.pen_button=tk.Button(tools,text='画笔 RGB',bg=self.ink,command=self.pick_pen)
        self.pen_button.pack(side='left')
        ttk.Button(tools,text='底色 RGB',command=self.pick_base).pack(side='left',padx=4)
        self.radius=tk.IntVar(self.window,value=8)
        tk.Scale(tools,from_=1,to=28,variable=self.radius,orient='horizontal',length=115,
                 label='笔刷大小').pack(side='right')
        actions=ttk.Frame(panel)
        actions.grid(row=6,column=0,sticky='ew')
        ttk.Button(actions,text='撤销一笔',command=self.undo).pack(side='left')
        self.delete_button=ttk.Button(actions,text='删除这只',command=self.delete_selected)
        self.delete_button.pack(side='left',padx=4)
        ttk.Button(actions,text='保存并使用',command=self.commit).pack(side='right')
        self.board.bind('<Button-1>',self.begin)
        self.board.bind('<B1-Motion>',self.move)
        self.board.bind('<ButtonRelease-1>',lambda e:setattr(self,'last',None))
        active=self.settings.active_drawing()
        self.refresh_history(self.settings.drawings.index(active)+1 if active else 0)
        self.board.bind('<Configure>',lambda event:self.display_board(event.width,event.height))
        self.window.update_idletasks()
        width=min(self.window.winfo_reqwidth(),self.window.winfo_screenwidth()-40)
        height=min(self.window.winfo_reqheight(),self.window.winfo_screenheight()-100)
        self.window.geometry(f'{width}x{height}')
        controls_height=self.window.winfo_reqheight()-workspace.winfo_reqheight()
        self.window.minsize(min(width,sidebar.winfo_reqwidth()+240),
                            min(height,controls_height+sidebar.winfo_reqheight()))
        self.window.deiconify()

    def refresh_history(self,selection):
        history=self.settings.drawings
        self.capacity.configure(text=f'最多保存最近 {MAX_DRAWINGS} 只小猫 · 已存 {len(history)} 只 · 剩余 {MAX_DRAWINGS-len(history)} 个名额')
        self.choice.configure(values=['新画一只']+[f'{i}. {item["name"]}' for i,item in enumerate(history,1)])
        self.choice.current(selection)
        for child in self.gallery.winfo_children():
            child.destroy()
        self.thumbnails=[]
        if history:
            self.gallery.pack(fill='x',pady=(6,0))
        else:
            self.gallery.pack_forget()
        for index,item in enumerate(history,1):
            image=self.thumbnail(item,(53,63))
            self.thumbnails.append(image)
            tk.Radiobutton(self.gallery,image=image,indicatoron=False,variable=self.gallery_index,
                           value=index,command=self.select_thumbnail).grid(
                               row=(index-1)//5,column=(index-1)%5,padx=2,pady=2)
        self.load()

    def delete_selected(self):
        selection=self.choice.current()
        if selection<=0:
            return
        history=self.settings.drawings
        item=history[selection-1]
        if not messagebox.askyesno('删除这只小猫',f'确定删除第 {selection} 只小猫（{item["name"]}）吗？',
                                   parent=self.window,default='no'):
            return
        active=self.settings.using_drawing
        deleting_active=item is self.settings.active_drawing()
        self.settings.drawings=history[:selection-1]+history[selection:]
        if deleting_active:
            self.settings.using_drawing=False
        if not self.settings.save():
            self.settings.drawings=history
            self.settings.using_drawing=active
            return
        if deleting_active:
            self.settings.variables['身体'].set(self.settings.current['身体'])
        self.refresh_history(min(selection,len(self.settings.drawings)))

    def select_thumbnail(self):
        self.choice.current(self.gallery_index.get())
        self.load()

    def load(self):
        i=self.choice.current()-1
        self.gallery_index.set(i+1)
        record=self.settings.drawings[i] if i>=0 else None
        self.loaded_record=record
        self.name.set(record['name'] if record else '')
        self.delete_button.state(['!disabled'] if record else ['disabled'])
        self.base=record['base'] if record else '#f3f1eb'
        self.paint=texture(record) if record else Image.new('RGBA',SIZE)
        self.underpaint=texture(record or {},'underpaint')
        self.last=None
        self.undo_stack=[]
        self.refresh()

    def compose(self,base,paint,body_only=False):
        bg=Image.new('RGB',SIZE,'#e6e4df')
        bg.paste(base,(0,0,*SIZE),self.body_mask if body_only else ImageChops.invert(self.outside))
        area=self.body_area if body_only else self.paint_area
        bg.paste(paint,mask=ImageChops.darker(area,paint.getchannel('A')))
        bg.paste(coat_outline(base),(0,0,*SIZE),self.body_rim if body_only else self.outer_rim)
        d=ImageDraw.Draw(bg)
        for x in (316,459):
            d.ellipse([pixel(x-50,205),pixel(x+50,287)],fill=self.settings.current['眼睛'],outline='#171717',width=2)
            d.ellipse([pixel(x-14,216),pixel(x+14,276)],fill=self.settings.current['瞳孔'])
        for start,end in ((301,230),(477,547)):
            for i in range(3):
                d.line([pixel(start,325+i*19),pixel(end,334+i*32)],fill='#888580',width=1)
        return bg

    def thumbnail(self,item,size):
        preview=self.compose(item['base'],texture(item))
        return ImageTk.PhotoImage(preview.resize(size,Image.Resampling.LANCZOS))

    def refresh(self):
        show=self.show_legs.get()
        paint=self.paint if show else Image.composite(self.underpaint,self.paint,self.forelegs)
        self.preview_pixels=self.compose(self.base,paint,body_only=not show)
        self.board.itemconfigure(self.guide_item,state='normal' if show and self.show_forepaws.get() else 'hidden')
        self.guide_toggle.state(['!disabled'] if show else ['disabled'])
        self.display_board(self.board.winfo_width(),self.board.winfo_height())
        if self.preview_redraw and self.preview_pending is None:
            self.preview_pending=self.window.after_idle(self.refresh_pose)

    def display_board(self,width,height):
        if min(width,height)<=1:
            return
        scale=min(width/SIZE[0],height/SIZE[1])
        size=(max(1,round(SIZE[0]*scale)),max(1,round(SIZE[1]*scale)))
        left,top=(width-size[0])//2,(height-size[1])//2
        self.board_origin=(left,top)
        if size!=self.display_size:
            self.display_size=size
            self.guide_photo=ImageTk.PhotoImage(self.guide_pixels.resize(size,Image.Resampling.NEAREST))
            self.board.itemconfigure(self.guide_item,image=self.guide_photo)
            self.head_guide_photo=ImageTk.PhotoImage(self.head_guide_pixels.resize(size,Image.Resampling.NEAREST))
            self.board.itemconfigure(self.head_guide_item,image=self.head_guide_photo)
            self.tail_guide_photo=ImageTk.PhotoImage(self.tail_guide_pixels.resize(size,Image.Resampling.NEAREST))
            self.board.itemconfigure(self.tail_guide_item,image=self.tail_guide_photo)
        self.preview=ImageTk.PhotoImage(self.preview_pixels.resize(size,Image.Resampling.NEAREST))
        self.board.itemconfigure(self.preview_item,image=self.preview)
        for item in (self.preview_item,self.guide_item,self.head_guide_item,self.tail_guide_item):
            self.board.coords(item,left,top)
        axis=left+(MIRROR_X+.5)*size[0]/SIZE[0]
        for line in self.board.find_withtag('mirror_axis'):
            self.board.coords(line,axis,top,axis,top+size[1])

    def paint_point(self,event):
        left,top=self.board_origin
        width,height=self.display_size
        return (math.floor((event.x-left+.5)*SIZE[0]/width),
                math.floor((event.y-top+.5)*SIZE[1]/height))

    def refresh_pose(self):
        self.preview_pending=None
        self.preview_redraw()

    def close_preview(self,event):
        if event.widget is self.window:
            if self.preview_pending is not None:
                self.window.after_cancel(self.preview_pending)
                self.preview_pending=None
            self.preview_redraw=None

    def use_ink(self,color):
        self.ink=color
        self.mode.set('pen')
        self.pen_button.configure(bg=color)

    def pick_pen(self):
        color=pick_rgb(self.window,self.ink,[])
        if color:
            self.use_ink(color)

    def pick_base(self):
        color=pick_rgb(self.window,self.base,[])
        if color:
            self.base=color
            self.refresh()

    def begin(self,event):
        x,y=self.paint_point(event)
        self.last=None
        if not (0<=x<SIZE[0] and 0<=y<SIZE[1]):
            return
        if self.mode.get()=='pick':
            ids=self.ids if self.show_legs.get() else self.body_ids
            if ids.getpixel((x,y)):
                self.use_ink('#%02x%02x%02x'%self.preview_pixels.getpixel((x,y)))
            return
        self.undo_stack.append((self.paint.copy(),self.underpaint.copy()))
        self.undo_stack=self.undo_stack[-24:]
        self.last=(x,y)
        self.move(event)

    def move(self,event):
        if self.last is None:
            return
        x,y=self.paint_point(event)
        r=self.radius.get()
        mask=Image.new('L',SIZE)
        brush=ImageDraw.Draw(mask)
        brush.line((self.last,(x,y)),fill=255,width=2*r)
        brush.ellipse((x-r,y-r,x+r,y+r),fill=255)
        if self.symmetric.get():
            flipped=mask.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            mirrored=Image.new('L',SIZE)
            mirrored.paste(flipped,(2*MIRROR_X-(SIZE[0]-1),0))
            mask=ImageChops.lighter(mask,mirrored)
        color='#fe00ff' if self.ink=='#ff00ff' else self.ink
        ink=(0,0,0,0) if self.mode.get()=='erase' else color
        if self.show_legs.get():
            mask=ImageChops.subtract(mask,self.outside)
        else:
            mask=ImageChops.darker(mask,self.body_mask)
            self.underpaint.paste(ink,(0,0,*SIZE),ImageChops.darker(mask,self.forelegs))
            mask=ImageChops.subtract(mask,self.forelegs)
        self.paint.paste(ink,(0,0,*SIZE),mask)
        self.last=(x,y)
        self.refresh()

    def undo(self):
        if self.undo_stack:
            self.paint,self.underpaint=self.undo_stack.pop()
            self.refresh()

    def choose_replacement(self,drawings):
        dialog=tk.Toplevel(self.window)
        dialog.title('选择要替换的小猫')
        dialog.transient(self.window)
        dialog.resizable(False,False)
        panel=ttk.Frame(dialog,padding=10)
        panel.pack()
        ttk.Label(panel,text=f'已保存 {MAX_DRAWINGS} 只小猫，请选择一只替换。').pack(anchor='w')
        gallery=ttk.Frame(panel)
        gallery.pack(pady=6)
        selected=tk.IntVar(dialog,value=-1)
        replacement=None

        def confirm():
            nonlocal replacement
            index=selected.get()
            if 0<=index<len(drawings):
                replacement=drawings[index]
                dialog.destroy()

        actions=ttk.Frame(panel)
        actions.pack(fill='x')
        cancel=ttk.Button(actions,text='取消',command=dialog.destroy)
        cancel.pack(side='left')
        replace=ttk.Button(actions,text='替换并保存',command=confirm,state='disabled')
        replace.pack(side='right')
        for i,cat in enumerate(drawings):
            image=self.thumbnail(cat,(53,63))
            button=tk.Radiobutton(gallery,text=cat['name'],image=image,compound='top',indicatoron=False,
                                  width=94,value=i,variable=selected,command=lambda:replace.state(['!disabled']))
            button.image=image
            button.grid(row=i//5,column=i%5,padx=2,pady=2)
        dialog.bind('<Escape>',lambda event:dialog.destroy())
        dialog.update_idletasks()
        width,height=dialog.winfo_reqwidth(),dialog.winfo_reqheight()
        x=self.window.winfo_rootx()+(self.window.winfo_width()-width)//2
        y=self.window.winfo_rooty()+(self.window.winfo_height()-height)//2
        dialog.geometry(f'+{x}+{y}')
        dialog.grab_set()
        cancel.focus_set()
        self.window.wait_window(dialog)
        return replacement

    def commit(self):
        png=encode_texture(self.paint)
        name=self.name.get().strip() or datetime.now().strftime('%m-%d %H:%M:%S')
        record=dict(name=name,base=self.base,png=png,tail_version=2)
        if self.underpaint.getbbox():
            record['underpaint']=encode_texture(self.underpaint)
        original=self.loaded_record
        same_art=(original is not None and original['base']==self.base
                  and texture(original).tobytes()==self.paint.tobytes()
                  and original.get('underpaint')==record.get('underpaint'))
        others=[a for a in self.settings.drawings if not (same_art and a is original)
                and (a['name'],a['base'],a['png'],a.get('underpaint'))!=(name,self.base,png,record.get('underpaint'))]
        previous=self.settings.drawings
        if len(others)>=MAX_DRAWINGS:
            replacement=self.choose_replacement(others)
            if replacement is None:
                return
            others=[cat for cat in others if cat is not replacement]
        self.settings.drawings=[record]+others
        if self.settings.use_drawing(record):
            self.window.destroy()
        else:
            self.settings.drawings=previous
